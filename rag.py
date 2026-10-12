"""Local semantic retrieval of runbooks; no answer generation or cluster access."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "runbooks"
INDEX = ROOT / ".local" / "rag-index.json"
MODEL = "intfloat/multilingual-e5-small"
DIMENSION = 384
MAX_TOKENS = 256
OVERLAP = 40
VERSION = 1


def corpus_fingerprint(directory: Path) -> str:
    files = sorted(directory.glob("*.md"))
    if not files:
        raise ValueError(f"No Markdown runbooks in {directory}")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def sections(path: Path):
    """Yield H2 sections and their body line numbers, ignoring fenced headings."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    title = path.stem
    section = "Wprowadzenie"
    start = 1
    body = []
    fence = None
    for number, line in enumerate(lines, 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker:
            fence = marker[1]
        elif line.startswith("# "):
            title = line[2:].strip()
            start = number + 1
            continue
        elif line.startswith("## "):
            if "".join(body).strip():
                yield title, section, start, "".join(body)
            section = line[3:].strip()
            start = number + 1
            body = []
            continue
        body.append(line)
    if fence:
        raise ValueError(f"Unclosed code fence in {path.name}")
    if "".join(body).strip():
        yield title, section, start, "".join(body)


def load_model(*, offline: bool):
    # All downloaded assets stay in the ignored project directory.
    os.environ.setdefault("HF_HOME", str(ROOT / ".local" / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    from tokenizers import Tokenizer

    # The small E5 model is registered explicitly; use its documented mean pooling.
    if MODEL not in {item["model"] for item in TextEmbedding.list_supported_models()}:
        TextEmbedding.add_custom_model(
            model=MODEL, pooling=PoolingType.MEAN, normalization=True,
            sources=ModelSource(hf=MODEL), dim=DIMENSION,
            model_file="onnx/model.onnx", license="mit",
        )
    model = TextEmbedding(
        model_name=MODEL, cache_dir=str(ROOT / ".local" / "models"),
        threads=2, providers=["CPUExecutionProvider"], local_files_only=offline,
    )
    # Clone the actual model tokenizer so length checks cannot silently truncate.
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return model, tokenizer


def make_chunks(directory: Path, tokenizer) -> list[dict]:
    """Token windows within H2 sections; repeat title and section in each chunk."""
    chunks = []
    for path in sorted(directory.glob("*.md")):
        for title, section, line, body in sections(path):
            # References are provenance, not troubleshooting passages.
            if section == "Źródła":
                continue
            prefix = f"# {title}\n\n## {section}\n\n"
            prefix_length = len(tokenizer.encode("passage: " + prefix).ids)
            budget = MAX_TOKENS - prefix_length - 8
            if budget <= OVERLAP:
                raise ValueError(f"Heading too long in {path.name}")
            encoded = tokenizer.encode(body, add_special_tokens=False)
            offset = 0
            while offset < len(encoded.ids):
                end = min(offset + budget, len(encoded.ids))
                first_char = encoded.offsets[offset][0]
                last_char = encoded.offsets[end - 1][1]
                excerpt = body[first_char:last_char]
                text = prefix + excerpt
                if len(tokenizer.encode("passage: " + text).ids) > MAX_TOKENS:
                    raise ValueError(f"Chunk exceeds token budget in {path.name}")
                source = f"runbooks/{path.name}"
                chunk_id = hashlib.sha256((source + "\0" + text).encode()).hexdigest()[:16]
                chunks.append({
                    "id": chunk_id, "source": source, "title": title,
                    "section": section,
                    "start_line": line + body[:first_char].count("\n"),
                    "end_line": line + body[:last_char].count("\n"),
                    "text": text,
                })
                if end == len(encoded.ids):
                    break
                offset = end - OVERLAP
    if not chunks:
        raise ValueError("No indexable runbook content")
    return chunks


def unit_vectors(vectors, *, expected_rows: int):
    import numpy as np
    array = np.asarray(vectors, dtype=np.float32)
    if array.shape != (expected_rows, DIMENSION) or not np.isfinite(array).all():
        raise ValueError("Invalid embedding shape or non-finite values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("Zero-length embedding")
    return array / norms


def build_index() -> None:
    fingerprint = corpus_fingerprint(CORPUS)
    model, tokenizer = load_model(offline=False)
    chunks = make_chunks(CORPUS, tokenizer)
    # Custom models do not automatically add E5 query/passage prefixes.
    vectors = unit_vectors(
        list(model.embed(["passage: " + chunk["text"] for chunk in chunks], batch_size=8)),
        expected_rows=len(chunks),
    )
    if corpus_fingerprint(CORPUS) != fingerprint:
        raise ValueError("Runbooks changed while indexing; rebuild the index")
    data = {
        "version": VERSION, "model": MODEL, "dimension": DIMENSION,
        "max_tokens": MAX_TOKENS, "overlap": OVERLAP,
        "corpus_fingerprint": fingerprint,
        "chunks": chunks, "vectors": vectors.tolist(),
    }
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=INDEX.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, allow_nan=False)
            output.write("\n")
        temporary.replace(INDEX)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Indexed {len(chunks)} chunks from {len(list(CORPUS.glob('*.md')))} runbooks: {INDEX}")


def load_index() -> dict:
    if not INDEX.exists():
        raise ValueError("Index missing; run: python rag.py index")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    expected = {
        "version": VERSION, "model": MODEL, "dimension": DIMENSION,
        "max_tokens": MAX_TOKENS, "overlap": OVERLAP,
        "corpus_fingerprint": corpus_fingerprint(CORPUS),
    }
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError("Index is stale or incompatible; run: python rag.py index")
    if not data.get("chunks"):
        raise ValueError("Index contains no chunks; rebuild it")
    return data


def search(query: str, top_k: int = 3) -> list[dict]:
    if not query.strip():
        raise ValueError("Query must not be empty")
    if not 1 <= top_k <= 20:
        raise ValueError("top-k must be between 1 and 20")
    data = load_index()
    model, tokenizer = load_model(offline=True)
    query_text = "query: " + query.strip()
    if len(tokenizer.encode(query_text).ids) > 512:
        raise ValueError("Query exceeds the model's 512-token input limit")
    vectors = unit_vectors(data["vectors"], expected_rows=len(data["chunks"]))
    query_vector = unit_vectors(list(model.embed([query_text])), expected_rows=1)[0]
    scores = vectors @ query_vector
    order = scores.argsort(kind="stable")[::-1][:top_k]
    return [{**data["chunks"][int(i)], "score": float(scores[i])} for i in order]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="Download/cache model and build the runbook index")
    retrieval = commands.add_parser("search", help="Search using cached model; no downloads")
    retrieval.add_argument("query")
    retrieval.add_argument("--top-k", type=int, default=3)
    retrieval.add_argument("--json", action="store_true", help="Print structured results")
    args = parser.parse_args()
    try:
        if args.command == "index":
            build_index()
        else:
            results = search(args.query, args.top_k)
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            else:
                for rank, item in enumerate(results, 1):
                    print(f"\n[{rank}] {item['source']}:{item['start_line']} | {item['section']} | cosine={item['score']:.3f}")
                    print(item["text"])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
