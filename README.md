# mcp-prep

A hands-on MCP prototype for read-only Kubernetes diagnostics. A Python MCP
server exposes three tools; a separate Python client runs a deterministic
workflow and prints deployment, pod, and event evidence.

This is the completed MCP stage of a learning project. RAG and an AI agent are
planned next. The current client does not use an LLM.

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
