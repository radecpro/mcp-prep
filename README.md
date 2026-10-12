# mcp-prep

A hands-on MCP prototype for read-only Kubernetes diagnostics. A Python MCP
server exposes three tools; a separate Python client runs a deterministic
workflow and prints deployment, pod, and event evidence.

This learning project includes MCP diagnostics and local RAG over runbooks:
semantic retrieval plus cited answers through Ollama. The deterministic MCP
client still prints cluster evidence separately. Combining that evidence with
RAG and adding an AI agent are subsequent stages.

## Runbook knowledge base

The initial Polish-language corpus for the RAG stage lives in `runbooks/`:

- [ImagePullBackOff](runbooks/image-pull-backoff.md): image references, registry access, and pull failures.
- [CrashLoopBackOff](runbooks/crash-loop-back-off.md): termination evidence, logs, and probe failures.
- [Pending](runbooks/pending-pod.md): scheduling versus preparation on an assigned node.

Each runbook includes read-only diagnostic commands, evidence interpretation,
MCP data limitations, completion criteria, and official documentation sources.
Additional lab administrator reads are explicitly marked.

## Local semantic retrieval

The retrieval stage runs independently of Kubernetes and the MCP server.
It uses FastEmbed with the multilingual `intfloat/multilingual-e5-small` model
on CPU, with explicit E5 `passage:` and `query:` prefixes and cosine ranking.
No embedding API or API key is needed. This stage is tested on Python 3.14;
the additional dependencies have their own Python/platform requirements.

```bash
source .venv/bin/activate
python -m pip install -r requirements-rag.txt
python rag.py index
python rag.py search 'Nie można pobrać obrazu: manifest unknown' --top-k 3
python rag.py search 'Gdzie znajdę logi poprzedniego uruchomienia?' --json
python scripts/verify_rag.py
```

Indexing downloads the model on first use, splits each H2 section into windows
of at most 256 model tokens (including the repeated title and section heading),
and overlaps long sections by 40 body tokens. Source-reference sections are
excluded from retrieval. Each result includes the source file, section, line
range, chunk ID, text, and cosine score. Token windows can split code or tables;
consult the linked source for the complete diagnostic procedure.

The JSON index and model cache live under ignored `.local/`. Search uses cached
model files only and can run offline after indexing. Re-run `python rag.py index`
after changing, adding, or removing a runbook; search rejects a stale index.
The model name is fixed, but downloaded model assets are not revision-pinned.

Search always returns the nearest fragments, including for unrelated questions.
A cosine score is a ranking signal, not a probability or proof that a fragment
answers the question. The verifier covers six diagnostic queries in Polish;
it is a smoke check rather than a general retrieval benchmark.

References: [FastEmbed](https://github.com/qdrant/fastembed) and the
[multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-small).

## Local RAG answers

`answer.py` retrieves runbook fragments, expands the matching H2 sections to
restore complete commands/tables, and sends the question and those sections to
Ollama on `127.0.0.1:11434`. The default model is `qwen3:4b-instruct`.
The model receives no live Kubernetes state. The answer contains cited claims
and missing evidence, or an `insufficient_context` status for an unsupported
question. Neither the Python code nor the model executes diagnostic commands.

The bundled setup helper is for macOS and Python 3.12+ (tested on Apple Silicon
with Python 3.14 and 24 GB RAM). It downloads the official Ollama v0.40.3 runtime
and verifies its pinned SHA-256. Other platforms can use an existing Ollama
installation listening on the same loopback address, with cloud features disabled.

```bash
python scripts/setup-ollama.py
python scripts/serve-ollama.py
```

The server runs in the foreground. In a second terminal, from the repository:

```bash
source .venv/bin/activate
OLLAMA_HOST=127.0.0.1:11434 .local/ollama/ollama pull qwen3:4b-instruct
python answer.py 'Kontener ma ImagePullBackOff. Event mówi manifest unknown. Co sprawdzić?'
python answer.py 'Jak odczytać logi poprzedniego uruchomienia kontenera?' --json
python scripts/verify_answers.py
python scripts/verify_answers.py --live
```

Stop the foreground server with Ctrl+C. The runtime and downloaded models are
ignored under `.local/`; Ollama may also create its normal user key under
`~/.ollama/`. The server helper binds to loopback and sets `OLLAMA_NO_CLOUD=1`.
Internet access is needed for initial downloads; inference uses local assets.
The model tag is not revision-pinned. `--model` selects another locally pulled
model; quality and structured-output support must be checked separately.

Generation uses temperature 0, a 16K context, up to 1536 output tokens, and a
180-second HTTP timeout. Oversized input is rejected rather than intentionally
truncated. Returned JSON is validated: every claim needs an existing source ID;
incomplete generation and unknown citations are errors. An unsupported question
is a successful report with `status=insufficient_context`, not a transport error.
`--json` includes the exact source sections supplied to the model for inspection.

Citation validation checks references, not factual support. A valid citation
does not prove that the model's claim follows from the source. Abstention and
resistance to instructions embedded in retrieved text are prompted behaviors,
not guarantees. Live checks cover three diagnostic questions and one unrelated
question; these do not establish general reliability. `client.py` remains a
separate MCP evidence workflow.

References: [Ollama API](https://docs.ollama.com/api/chat),
[Ollama v0.40.3](https://github.com/ollama/ollama/releases/tag/v0.40.3), and
[Qwen3 4B Instruct](https://ollama.com/library/qwen3:4b-instruct).

## Architecture

```text
Python CLI client (or MCP Inspector)
  -> MCP over stdio
  -> Python MCP server
  -> Kubernetes API using a namespace-scoped ServiceAccount
```

| Tool | Inputs | Output |
| --- | --- | --- |
| `get_deployment_status` | namespace, deployment name | Desired, ready, and available replica counts |
| `list_pods` | namespace, optional label selector | Pod names/UIDs, phases, container states and restart counts |
| `get_pod_events` | namespace, pod UID | Retained events, bounded messages, and last-observed timestamps |

The client discovers pod UIDs from `list_pods`, then fetches events for the
first matching pod. Tool execution failures are checked before parsing results.

## Requirements

- Python 3.11+ (tested with Python 3.14)
- Docker, kind, and kubectl
- Node.js 22.19+ and npx only if using MCP Inspector
- Network access to pull the kind node image and nginx

Direct Python dependencies are pinned in `requirements.txt`.

## Set up the local lab

Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

mkdir -p .local
kind create cluster --name mcp \
  --image kindest/node:v1.37.0 \
  --kubeconfig "$PWD/.local/admin-kubeconfig" \
  --wait 120s

kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp \
  apply -f k8s/demo.yaml
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp \
  apply -f k8s/rbac.yaml
kubectl --kubeconfig .local/admin-kubeconfig --context kind-mcp \
  -n mcp-demo rollout status deployment/catalog --timeout=120s

python scripts/refresh-kubeconfig.py
```

The lab creates two deployments:

- `catalog`: two healthy nginx replicas.
- `payments`: three replicas with an intentionally nonexistent nginx image tag.
  Its containers should reach `ErrImagePull` or `ImagePullBackOff`.

The nginx tag for the healthy workload is mutable; this is a disposable lab,
not an image-pinning or supply-chain-hardening example.

## Run diagnostics

```bash
python client.py
python client.py --deployment catalog
python client.py --deployment payments --label-selector app=payments
```

Defaults are namespace `mcp-demo` and deployment `payments`. The default pod
selector is `app=<deployment>`, a convention of this lab. Supply
`--label-selector` for workloads with different labels. The client does not
infer arbitrary deployment selectors or prove pod ownership.

Example evidence from `payments`:

```text
Deployment: mcp-demo/payments
Ready replicas: 0/3; available: 0
Pods matching 'app=payments': 3
... reason=ImagePullBackOff
... Failed to pull image "nginx:mcp-demo-nonexistent" ... not found
```

Exit status `0` means the report completed, even when the workload is unhealthy.
Tool, transport, or workflow failures return `1`. An empty pod list stops the
workflow with an explanation. The overall workflow has a 60-second timeout.

## Explore with MCP Inspector

After activating the virtual environment:

```bash
npx @modelcontextprotocol/inspector \
  "$PWD/.venv/bin/python" "$PWD/server.py"
```

Open the URL printed by Inspector, connect the stdio server, and use the Tools
tab. The CLI client and Inspector each launch their own server process.
For stdio servers, logs must go to stderr; stdout carries protocol messages.

## Credentials and authorization

`k8s/rbac.yaml` grants the `mcp-reader` ServiceAccount:

- `get/list` deployments in API group `apps`.
- `get/list` pods in the core API group.
- `list` events in the core API group.

The RoleBinding applies only in `mcp-demo`. It grants no workload modifications
or Secret access. The server always loads `.local/mcp-kubeconfig` and context
`mcp-reader`; it does not fall back to an administrator kubeconfig.

`refresh-kubeconfig.py` uses the administrator kubeconfig to request a token
with a one-hour duration. The API server determines the actual lifetime. The
script writes the reader kubeconfig atomically with mode `0600` and never prints
the token. Re-run it when the token expires:

```bash
python scripts/refresh-kubeconfig.py
```

Both kubeconfigs and the virtual environment are ignored by Git. The MCP
process runs locally and still has the operating-system permissions of its
user; Kubernetes RBAC is not a local-process sandbox.

## Verify

```bash
python scripts/verify.py
```

The verifier performs read-only MCP integration checks against the running lab:
tool discovery, replica counts, pod state, UID-to-event lookup, response limits,
empty results, missing resources, access denial, and continued operation after
a tool error. Image pulls must have settled before running it.

Check additional authorization boundaries using the reader's credentials:

```bash
kubectl --kubeconfig .local/mcp-kubeconfig auth can-i patch deployments -n mcp-demo
kubectl --kubeconfig .local/mcp-kubeconfig auth can-i get secrets -n mcp-demo
kubectl --kubeconfig .local/mcp-kubeconfig auth can-i list deployments -n default
```

All three should return `no` (exit status `1`).

## Prototype limitations

- Local stdio transport only; no remote MCP authentication or multi-user service.
- Lists return at most 20 objects and expose `truncated`; the client does not
  fetch subsequent pages. API order is not guaranteed to be chronological.
- The diagnostic workflow shows all returned pods but fetches events for only
  the first one. It is not a complete rollout assessment.
- Events are retained temporarily. No events, or no warnings, does not prove
  there was no failure. An unknown UID returns an empty list, not a missing-pod
  error, and historical events may outlive a pod.
- Event messages are limited to 500 characters. Container states are returned
  more broadly and may contain operational details.
- HTTP 401/403/404 errors have explicit handling. Transport errors are reported
  by the client; they can still produce SDK tracebacks on server stderr.
- This is a diagnostics prototype, not a production agent or an automated
  remediation system.

## Cleanup

When the disposable lab is no longer needed:

```bash
kind delete cluster --name mcp
```

This targets only the `mcp` cluster. Remove its local kubeconfig files separately
if desired. Other kind clusters are independent.
