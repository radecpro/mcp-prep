from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pathlib import Path

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

mcp = MCPServer("platform-diagnostics")

@mcp.tool()
def get_deployment_status(
    namespace: str,
    deployment_name: str,
) -> dict:
    """Read deployment replica counts from Kubernetes.

    Does not determine the cause of unavailable replicas.
    """
    kubeconfig = Path(__file__).parent / ".local" / "mcp-kubeconfig"

    configuration = client.Configuration()
    config.load_kube_config(
        config_file=str(kubeconfig),
        context="mcp-reader",
        client_configuration=configuration,
        persist_config=False,
    )

    try:
        with client.ApiClient(configuration) as api_client:
            apps = client.AppsV1Api(api_client)

            deployment = apps.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                _request_timeout=(3, 10),
            )

            return {
                "namespace": namespace,
                "deployment_name": deployment_name,
                "desired_replicas": deployment.spec.replicas,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "available_replicas": deployment.status.available_replicas or 0,
            }

    except ApiException as exc:
        if exc.status == 404:
            raise ToolError(
                f"Deployment {namespace}/{deployment_name} not found"
            ) from exc
        if exc.status == 403:
            raise ToolError(
                f"Access denied to deployment {namespace}/{deployment_name}"
            ) from exc
        if exc.status == 401:
            raise ToolError(
                "Authentication failed; refresh the MCP kubeconfig token"
            ) from exc
        raise ToolError(
            f"Kubernetes API request failed: HTTP {exc.status}"
        ) from exc

@mcp.tool()
def list_pods(namespace: str, label_selector: str = "") -> dict:
    """List pods and container states matching a label selector."""
    kubeconfig = Path(__file__).parent / ".local" / "mcp-kubeconfig"

    configuration = client.Configuration()
    config.load_kube_config(
        config_file=str(kubeconfig),
        context="mcp-reader",
        client_configuration=configuration,
        persist_config=False,
    )

    try:
        with client.ApiClient(configuration) as api_client:
            core = client.CoreV1Api(api_client)

            pods = core.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                _request_timeout=(3, 10),
                limit=20,
            )

            return {
                "namespace": namespace,
                "label_selector": label_selector,
                "pods": [
                    {
                        "name": pod.metadata.name,
                        "uid": pod.metadata.uid,
                        "phase": pod.status.phase,
                        "container_statuses": [
                            {
                                "name": cs.name,
                                "ready": cs.ready,
                                "restart_count": cs.restart_count,
                                "state": cs.state.to_dict() if cs.state is not None else None,
                            }
                            for cs in (pod.status.container_statuses or [])
                        ],
                    }
                    for pod in pods.items
                ],
                "truncated": bool(pods.metadata._continue),
            }

    except ApiException as exc:
        if exc.status == 404:
            raise ToolError(f"Namespace {namespace} not found") from exc
        if exc.status == 403:
            raise ToolError(f"Access denied to namespace {namespace}") from exc
        if exc.status == 401:
            raise ToolError(
                "Authentication failed; refresh the MCP kubeconfig token"
            ) from exc
        raise ToolError(
            f"Kubernetes API request failed: HTTP {exc.status}"
        ) from exc

def _event_last_seen(event: client.CoreV1Event) -> str | None:
    timestamp = (
        (event.series.last_observed_time if event.series is not None else None)
        or event.last_timestamp
        or event.event_time
        or event.metadata.creation_timestamp
    )
    return timestamp.isoformat() if timestamp is not None else None


@mcp.tool()
def get_pod_events(namespace: str, pod_uid: str) -> dict:
    """Read retained Kubernetes events matching a pod UID.

    Does not verify that the pod still exists. No matching events returns an
    empty list, including for unknown UIDs or expired event history.
    """
    kubeconfig = Path(__file__).parent / ".local" / "mcp-kubeconfig"

    configuration = client.Configuration()
    config.load_kube_config(
        config_file=str(kubeconfig),
        context="mcp-reader",
        client_configuration=configuration,
        persist_config=False,
    )

    try:
        with client.ApiClient(configuration) as api_client:
            core = client.CoreV1Api(api_client)

            events = core.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.uid={pod_uid},involvedObject.kind=Pod",
                _request_timeout=(3, 10),
                limit=20,
            )

            return {
                "namespace": namespace,
                "pod_uid": pod_uid,
                "events": [
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": (event.message or "")[:500],
                        "last_seen": _event_last_seen(event),
                        "first_timestamp": event.first_timestamp.isoformat()
                        if event.first_timestamp is not None
                        else None,
                        "last_timestamp": event.last_timestamp.isoformat()
                        if event.last_timestamp is not None
                        else None,
                    }
                    for event in events.items
                ],
                "truncated": bool(events.metadata._continue),
            }

    except ApiException as exc:
        if exc.status == 404:
            raise ToolError(
                f"Event listing unavailable for namespace {namespace}: HTTP 404"
            ) from exc
        if exc.status == 403:
            raise ToolError(f"Access denied to events in namespace {namespace}") from exc
        if exc.status == 401:
            raise ToolError(
                "Authentication failed; refresh the MCP kubeconfig token"
            ) from exc
        raise ToolError(
            f"Kubernetes API request failed: HTTP {exc.status}"
        ) from exc

if __name__ == "__main__":
    mcp.run(transport="stdio")
