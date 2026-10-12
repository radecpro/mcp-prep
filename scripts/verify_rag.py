"""Offline retrieval smoke checks and index/chunk boundary checks."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag


class RetrievalChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.tokenizer = rag.load_model(offline=True)

    def test_polish_retrieval(self):
        cases = [
            ("Kontener nie może pobrać obrazu z registry: manifest unknown, tag nie istnieje.", "image-pull-backoff.md", "manifest unknown"),
            ("Aplikacja ciągle się restartuje. Gdzie znajdę logi poprzedniego uruchomienia?", "crash-loop-back-off.md", "--previous"),
            ("Pod nie ma przypisanego węzła. Scheduler zgłasza Insufficient cpu.", "pending-pod.md", "Insufficient cpu"),
            ("Registry zwraca unauthorized podczas pobierania obrazu.", "image-pull-backoff.md", "unauthorized"),
            ("Kontener ma OOMKilled i rosnący licznik restartów.", "crash-loop-back-off.md", "OOMKilled"),
            ("PersistentVolumeClaim jest unbound i pod czeka na scheduling.", "pending-pod.md", "unbound"),
        ]
        for query, source, evidence in cases:
            with self.subTest(query=query):
                results = rag.search(query, top_k=3)
                self.assertEqual(results[0]["source"], f"runbooks/{source}")
                relevant = [item for item in results if item["source"] == f"runbooks/{source}"]
                self.assertTrue(any(evidence in item["text"] for item in relevant), results)
                self.assertTrue(all(-1.001 <= item["score"] <= 1.001 for item in results))
                self.assertEqual(len(results), 3)

    def test_source_metadata_and_token_limit(self):
        chunks = rag.make_chunks(rag.CORPUS, self.tokenizer)
        self.assertEqual(len({item["id"] for item in chunks}), len(chunks))
        for item in chunks:
            source_lines = (rag.ROOT / item["source"]).read_text().splitlines()
            self.assertLessEqual(len(self.tokenizer.encode("passage: " + item["text"]).ids), rag.MAX_TOKENS)
            self.assertTrue(1 <= item["start_line"] <= item["end_line"] <= len(source_lines))
            self.assertNotEqual(item["section"], "Źródła")

    def test_long_section_retains_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.md"
            body = " ".join(f"unikalny{i}" for i in range(250))
            path.write_text(f"# Test\n\n## Długa sekcja\n\n{body}\n")
            chunks = rag.make_chunks(Path(directory), self.tokenizer)
            self.assertGreater(len(chunks), 1)
            for word in body.split():
                self.assertTrue(any(word in item["text"] for item in chunks), word)

    def test_heading_inside_code_is_not_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fence.md"
            path.write_text("# Test\n\n## Diagnostyka\n\n```bash\n## komentarz\necho ok\n```\n")
            sections = list(rag.sections(path))
            self.assertEqual(len(sections), 1)
            self.assertEqual(sections[0][1], "Diagnostyka")
            self.assertIn("## komentarz", sections[0][3])
            path.write_text("# Test\n\n```bash\necho ok\n")
            with self.assertRaisesRegex(ValueError, "Unclosed"):
                list(rag.sections(path))

    def test_changed_corpus_rejected_before_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "runbooks"
            corpus.mkdir()
            runbook = corpus / "test.md"
            runbook.write_text("# Test\n\nBefore\n")
            index = Path(directory) / "index.json"
            data = {
                "version": rag.VERSION, "model": rag.MODEL,
                "dimension": rag.DIMENSION, "max_tokens": rag.MAX_TOKENS,
                "overlap": rag.OVERLAP, "corpus_fingerprint": rag.corpus_fingerprint(corpus),
                "chunks": [{"text": "Before"}], "vectors": [],
            }
            index.write_text(json.dumps(data))
            with patch.object(rag, "CORPUS", corpus), patch.object(rag, "INDEX", index):
                self.assertEqual(rag.load_index()["chunks"][0]["text"], "Before")
                runbook.write_text("# Test\n\nAfter\n")
                with patch.object(rag, "load_model") as model:
                    with self.assertRaisesRegex(ValueError, "stale"):
                        rag.search("Test")
                    model.assert_not_called()

    def test_invalid_query_and_vectors(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            rag.search("   ")
        with self.assertRaisesRegex(ValueError, "top-k"):
            rag.search("Test", top_k=0)
        with self.assertRaisesRegex(ValueError, "Zero-length"):
            rag.unit_vectors([[0] * rag.DIMENSION], expected_rows=1)
        with self.assertRaisesRegex(ValueError, "Invalid embedding"):
            rag.unit_vectors([[float("nan")] * rag.DIMENSION], expected_rows=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
