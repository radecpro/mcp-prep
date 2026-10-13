# mcp-prep

A hands-on MCP prototype for read-only Kubernetes diagnostics. A Python MCP
server exposes three tools; a separate Python client runs a deterministic
workflow and prints deployment, pod, and event evidence.

This learning project includes MCP diagnostics and local RAG over runbooks:
semantic retrieval plus cited answers through Ollama. `integrate.py` combines
live MCP evidence with runbooks and local generation. `agent.py` adds a
controlled local agent that chooses scoped read-only actions through Ollama.

## Choose an entry point

| Goal | Entry point | Instructions |
| --- | --- | --- |
| Inspect live cluster evidence without a model | `client.py` | [Run diagnostics](#run-diagnostics) |
| Search runbook fragments without generation | `rag.py search` | [Local semantic retrieval](#local-semantic-retrieval) |
| Ask a documentation question without cluster access | `answer.py` | [Local RAG answers](#local-rag-answers) |
| Run a fixed collection-and-answer workflow | `integrate.py` | [MCP and RAG integration](#mcp-and-rag-integration) |
| Let the model choose subsequent scoped reads | `agent.py` | [Controlled diagnostic agent](#controlled-diagnostic-agent) |

For a first end-to-end run, follow [lab setup](#set-up-the-local-lab), install
the RAG dependencies and [build the index](#local-semantic-retrieval), then
[start Ollama and pull the model](#local-rag-answers). Keep Ollama running in
one terminal and run the integration or agent from another. For later runs,
reuse the lab, index, and cached models; start Ollama if needed and
[refresh the reader token](#credentials-and-authorization) if it has expired.

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

## MCP and RAG integration

Start Ollama and build the local index using the instructions above.
Refresh an expired reader token with `python scripts/refresh-kubeconfig.py`.

```bash
python integrate.py --deployment catalog
python integrate.py --deployment payments
python integrate.py --deployment payments --json
python scripts/verify_integration.py
python scripts/verify_integration.py --live
python scripts/verify_scenarios.py --live
```

The workflow has three fixed stages:

1. Collect replica counts, matching pods, and events for **every returned pod UID**
   over MCP. Preserve original results with IDs `E1`, `E2`, etc. and UTC read
   timestamps. Collection has a 60-second timeout; tool errors stop the flow.
2. Build a bounded retrieval query from known diagnostic terms in complete
   container reasons/messages and warning events, plus Pending and restart
   history. Arbitrary event instructions do not enter the query. Retrieve
   extra chunks before filtering fixture examples and expand complete
   sections. Exclude static lab-example sections to avoid fixture bias.
   Integration also excludes command-procedure sections: this stage generates
   interpretation and evidence gaps, not executable diagnostic procedures.
   The integration defaults to three retrieved chunks; `--top-k` can increase
   context, but the same input-size guard still applies.
3. Send evidence, limitations, and runbooks to local Ollama using the shared
   `answer.generate` transport. Generate at most one best-supported hypothesis
   and three missing proofs. Validate runbook citations and evidence IDs.
   The model selects one best runbook reference and one supporting observation
   per hypothesis; the public report retains these as arrays. This avoids
   duplicate-reference generation while preserving the report contract.

Missing proofs are selected from a small, validated list appropriate to the
observed symptom (or a clean snapshot), preventing unrelated diagnostic gaps.
Registry-access caveats for `not found` are also preserved deterministically
in report limitations, regardless of generated wording. OOM and scheduling
resource caveats are likewise preserved. The primary verification gap is
always included, even if the model selects only secondary gaps.

Hypotheses require a recognized symptom context and specific cause evidence;
replica counts alone cannot support a cause. A bare Pending/CrashLoopBackOff
without cause evidence, an empty selector, or an unrelated warning must abstain.
Evidence references for hypotheses are limited to observations containing such
signals. This conservative gate is specific to the current runbook corpus;
extend it together with scenario tests when adding diagnostic coverage.
OOMKilled remains an observed termination reason, but the flow abstains from
attributing an underlying cause to container limits versus node pressure without
limits, metrics, or node evidence. A model-generated guess is not enough.

The report separates original cluster observations, possible causes, and missing
evidence. JSON retains exact source sections, the retrieval query, assessment,
timestamps, and model name. No model output is executed. No dependencies,
Kubernetes permissions, or write tools are added. The loopback transport bypasses
proxies, rejects oversized context, and has a 180-second HTTP timeout.

`no_issue_detected` requires positive desired replicas, ready/available counts
equal to desired, ready returned containers, complete lists, and no observed
waiting/termination reasons, restart history, or retained warning events.
Returned pods must be Running and container states must show running.
Otherwise the assessment
is `needs_investigation`. The validator rejects generated causes for a snapshot
classified `no_issue_detected`; this assessment does not guarantee end-to-end
application health. Empty pods, missing states, and truncated lists prevent it.

The default selector `app=<deployment>` does not establish ownership. Reads are
not atomic, event history expires, and tools do not return image specs, logs,
or traffic tests. Exit `0` means reporting completed, even for an unhealthy
workload; errors return `1`.

The live verifier checks `catalog` (2/2, no generated failure hypotheses) and
`payments` (0/3, pull failure evidence and an image-pull runbook citation),
including event collection for every returned pod. Exact reports are saved in
ignored `.local/catalog-integration.json` and `.local/payments-integration.json`.
Contract tests cover incomplete snapshots, invalid citations/evidence IDs,
invented healthy-workload causes, all-pod event collection, and tool failures.
They establish flow and reference integrity, not general semantic correctness.
Citation support, cautious wording, and prompt-injection resistance still require
reviewing generated text. A `not found` message supports a missing-reference
hypothesis, but registry authorization can mask resource existence.

`verify_scenarios.py --live` uses **synthetic MCP snapshots** with real local
embeddings, runbooks, and Ollama. It never connects to Kubernetes or creates
failures in the cluster. Twelve cases cover absent events, empty selectors,
truncated lists, Pending without scheduling evidence, insufficient CPU,
CrashLoopBackOff without logs, OOMKilled, registry authorization, a diagnostic
message tail after 600 characters, unrelated warnings, and an instruction
injected into event text. Results and exact inputs/outputs are saved to ignored
`.local/integration-scenarios.json`. Automated checks validate expected
abstention, source selection, basic evidence terms, and unchanged observations;
semantic correctness still requires reading the generated hypotheses.
Passing the injected-event case is evidence for that example, not a general
prompt-injection guarantee. Fixed tool selection and read-only RBAC keep model
text from performing changes even if generation is misled.

## Controlled diagnostic agent

```bash
python agent.py --deployment catalog --output .local/agent-catalog.json
python agent.py --deployment payments --output .local/agent-payments.json
python agent.py --deployment payments --max-steps 10 --timeout 240 --json
python scripts/verify_agent.py
python scripts/verify_agent.py --live
python scripts/verify_agent.py --scenarios
```

Use the same cached embeddings, local Ollama server, and reader kubeconfig as
the integration. No additional dependency or Kubernetes permission is needed.
`--live` reads the real lab. `--scenarios` uses real Ollama/retrieval and synthetic
MCP results; it never connects to Kubernetes.

The controller presents a numbered menu of currently valid actions. Ollama
chooses a number and a short rationale; it does not create tool arguments.
Deployment and pod reads establish the diagnostic scope. Later choices include
events for an unread discovered UID, evidence-derived runbook search, and finish.
Event order and the point of retrieval/termination are model decisions, rather
than a replay of the deterministic integration workflow.

Controls are enforced in Python:

- Only the three existing read-only MCP tools, local retrieval, and finish are
  available. Namespace, deployment, and selector come from CLI scope. Event UIDs
  must be valid UUIDs discovered in the scoped pod list. Tool result identities,
  shapes, list limits, and size are checked before recording evidence.
- A deployment, pod list, and current runbook context are required before finish.
  A healthy assessment also requires event reads for every discovered pod. An
  abnormal workload may stop earlier when existing evidence supports a hypothesis;
  unread events remain an explicit completeness limitation.
- No duplicate MCP reads are offered. New evidence invalidates the previous
  retrieval revision, so finish requires refreshing runbooks. Canonical sections
  and index freshness are checked again during final interpretation.
- The default limit is 10 decisions (range 1–40), with a 240-second overall
  deadline (range 1–900). This includes planning, MCP, retrieval, and final
  generation. Blocking HTTP/embedding jobs run in an isolated Python worker,
  killed on cancellation; closing MCP also terminates its stdio server. Process
  cleanup can add a short delay after the deadline. The local Ollama service
  remains running independently.
- Invalid decisions, denied reads, malformed results, stale indexes, incomplete
  generation, and budget exhaustion stop the session. Partial reports retain
  observations and completed decisions but contain no generated diagnosis.

The final report separates original observations, runbook-cited hypotheses,
missing evidence, and a timestamped decision trace. Rationale text is generated
by the planner and is not a cluster observation. It is never executed.
The existing conservative evidence gate still applies: Pending/CrashLoopBackOff
alone cannot identify a cause, and OOMKilled alone does not establish a container
limit versus node-pressure cause. No logs, pod specifications, metrics, registry
verification, or repairs are performed; unsupported evidence needs are reported.

`agent_status=completed` and exit `0` mean the diagnostic report finished, even
for unhealthy workloads. `step_limit`, `timeout`, or `error` return exit `1` and
an explicitly partial report. `--output` saves exact results, sources, scope,
limits, and trace as JSON; use ignored `.local/` for operational data. Source and
model wording still need review; control of actions does not guarantee semantic
correctness or general prompt-injection resistance.

See [the agent verification report](agent-verification.md) for acceptance checks,
recorded live paths, and the tested limits.

## Architecture

```text
client.py / integrate.py / agent.py
  -> MCP over stdio -> server.py -> Kubernetes API (mcp-reader)

integrate.py / agent.py
  -> rag.py -> cached E5 embeddings + runbooks/ -> source sections
  -> answer.py -> local Ollama -> Qwen -> validated report

agent.py
  -> agent_worker.py -> Qwen selects the next menu action
  -> controller validates and dispatches that action -> next observation
```

MCP is the tool interface, not the model or the agent. `server.py` owns the
Kubernetes reads. RAG retrieves documentation and adds it to generation context;
it does not train the model. The E5 embedding model ranks runbook passages,
while Qwen chooses agent actions and writes answers. Ollama serves Qwen locally.
`agent_worker.py` isolates blocking planning, retrieval, and interpretation so
the controller can cancel them. `integrate.py` supplies shared evidence checks,
runbook handling, and interpretation to both entry points.

| Tool | Inputs | Output |
| --- | --- | --- |
| `get_deployment_status` | namespace, deployment name | Desired, ready, and available replica counts |
| `list_pods` | namespace, optional label selector | Pod names/UIDs, phases, container states and restart counts |
| `get_pod_events` | namespace, pod UID | Retained events, bounded messages, and last-observed timestamps |

`client.py` discovers pod UIDs from `list_pods`, then fetches events for the
first matching pod. Tool execution failures are checked before parsing results.

## Use the MCP server from Codex

From the repository root, register the existing stdio server:

```bash
codex mcp add k8s-diagnostics -- "$PWD/.venv/bin/python" "$PWD/server.py"
codex mcp list
```

Open a new Codex session and ask it to diagnose `mcp-demo/payments` using
`k8s-diagnostics`. Verify that its reads appear as MCP tool calls.

The MCP client starts `server.py`; do not start another copy manually. This
connection uses the reader kubeconfig but does not need Ollama or the RAG index.
Codex receives only the three tools listed above. It runs its own agent loop;
registration does not automatically include our `agent.py` controller, its
limits, answer validation, or local runbook search.

To direct Codex toward this interface, add a project instruction to `AGENTS.md`:

```text
For Kubernetes diagnostics, use only the k8s-diagnostics MCP server.
Do not query the cluster through shell commands, Python clients, or direct HTTP.
If a required read is unavailable, report the missing evidence instead of
bypassing MCP. Separate cluster observations from hypotheses.
```

Instructions guide tool choice; they are not an access-control boundary.
Direct credential/API access through other tools must be restricted to enforce
MCP-only access. In this lab both kubeconfigs are under `.local/`; a general
agent with filesystem and shell access could read them. Strong isolation means
keeping credentials in the MCP server's separate execution environment and
denying the client a direct Kubernetes API route. Kubernetes RBAC still limits
the server's credentials, but does not sandbox the local operating-system user.

Exposing runbook search or the complete controlled diagnostic workflow through
MCP would require additional tools; neither is part of the current server.
See [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
and [instructions for directing MCP usage](https://developers.openai.com/learn/docs-mcp).

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
- `client.py` shows all returned pods but fetches events only for the first one.
  `integrate.py` fetches all returned UIDs. The agent chooses its reads and reports
  missing event coverage; none proves ownership or an end-to-end rollout result.
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
