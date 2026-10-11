"""Deterministic Kubernetes diagnostics using tools exposed over MCP."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class WorkflowError(Exception):
    """The diagnostic workflow cannot continue with the available results."""


def error_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(error_message(child) for child in exc.exceptions)
    return str(exc) or type(exc).__name__


async def call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments=arguments)
    text = "\n".join(
        block.text for block in result.content if block.type == "text"
    )
    if result.is_error:
        raise WorkflowError(f"{name}: {text or 'Tool execution failed'}")

    data = result.structured_content
    if data is None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"{name}: response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"{name}: expected a JSON object")
    return data


async def diagnose(namespace: str, deployment_name: str, selector: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve().with_name("server.py"))],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            deployment = await call_tool(session, "get_deployment_status", {
                "namespace": namespace,
                "deployment_name": deployment_name,
            })
            print(f"Deployment: {namespace}/{deployment_name}")
            print(
                f"Ready replicas: {deployment['ready_replicas']}/"
                f"{deployment['desired_replicas']}; "
                f"available: {deployment['available_replicas']}"
            )

            result = await call_tool(session, "list_pods", {
                "namespace": namespace,
                "label_selector": selector,
            })
            pods = result["pods"]
            print(f"Pods matching {selector!r}: {len(pods)}")
            if result.get("truncated"):
                print("WARNING: pod list is incomplete; only the first page is shown.")
            if not pods:
                print("No matching pods. Check the selector; event lookup skipped.")
                return

            for pod in pods:
                print(f"  {pod['name']}: phase={pod['phase']}")
                statuses = pod.get("container_statuses") or []
                if not statuses:
                    print("    Container status is not available yet.")
                for container in statuses:
                    state = container.get("state") or {}
                    waiting = state.get("waiting") or {}
                    terminated = state.get("terminated") or {}
                    reason = waiting.get("reason") or terminated.get("reason")
                    print(
                        f"    {container['name']}: ready={container['ready']}, "
                        f"restarts={container['restart_count']}, "
                        f"reason={reason or '-'}"
                    )

            selected = pods[0]
            uid = selected.get("uid")
            if not uid:
                raise WorkflowError("Selected pod has no UID; event lookup cannot continue")
            events = await call_tool(session, "get_pod_events", {
                "namespace": namespace,
                "pod_uid": uid,
            })
            print(f"Events for first pod: {selected['name']} (UID: {uid})")
            if events.get("truncated"):
                print("WARNING: event list is incomplete; only the first page is shown.")
            warnings = [event for event in events["events"] if event.get("type") == "Warning"]
            print(f"Retained events: {len(events['events'])}; warnings: {len(warnings)}")
            for event in warnings:
                print(
                    f"  [{event.get('last_seen') or 'unknown time'}] "
                    f"{event.get('reason') or '-'}: {event.get('message') or '-'}"
                )
            if not warnings:
                print("No retained warnings in this result; this does not prove absence of failures.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="mcp-demo")
    parser.add_argument("--deployment", default="payments")
    parser.add_argument(
        "--label-selector",
        help="Pod selector; defaults to app=<deployment>, a convention of this lab.",
    )
    args = parser.parse_args()
    selector = args.label_selector if args.label_selector is not None else f"app={args.deployment}"
    try:
        asyncio.run(asyncio.wait_for(
            diagnose(args.namespace, args.deployment, selector), timeout=60,
        ))
    except TimeoutError:
        print("ERROR: diagnostic workflow exceeded 60 seconds", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {error_message(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
