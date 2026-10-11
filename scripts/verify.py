"""Read-only MCP integration checks for the running mcp-demo lab."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def request(session, tool, arguments, error=None):
    result = await session.call_tool(tool, arguments=arguments)
    text = "\n".join(block.text for block in result.content if block.type == "text")
    if error is not None:
        assert result.is_error and error in text, text
        return None
    assert not result.is_error, text
    return result.structured_content or json.loads(text)


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_deployment_status", "list_pods", "get_pod_events",
            }
            print("PASS tool discovery: three Kubernetes tools")
            for app, ready, desired in [("catalog", 2, 2), ("payments", 0, 3)]:
                status = await request(session, "get_deployment_status", {
                    "namespace": "mcp-demo", "deployment_name": app,
                })
                assert (status["ready_replicas"], status["desired_replicas"]) == (ready, desired), status
                pods = await request(session, "list_pods", {
                    "namespace": "mcp-demo", "label_selector": f"app={app}",
                })
                assert len(pods["pods"]) == desired and pods["truncated"] is False, pods
                for pod in pods["pods"]:
                    assert pod["uid"] and pod["container_statuses"], pod
                    for container in pod["container_statuses"]:
                        assert isinstance(container["restart_count"], int), container
                        if app == "catalog":
                            assert container["ready"] is True, container
                        else:
                            assert container["ready"] is False, container
                            assert container["state"]["waiting"]["reason"] in {
                                "ErrImagePull", "ImagePullBackOff",
                            }, container
                events = await request(session, "get_pod_events", {
                    "namespace": "mcp-demo", "pod_uid": pods["pods"][0]["uid"],
                })
                assert events["truncated"] is False, events
                for event in events["events"]:
                    assert len(event["message"]) <= 500 and "last_seen" in event, event
                print(f"PASS {app}: replicas, pod state, UID and retained events")
            await request(session, "get_deployment_status", {
                "namespace": "mcp-demo", "deployment_name": "unknown",
            }, error="not found")
            await request(session, "get_deployment_status", {
                "namespace": "default", "deployment_name": "catalog",
            }, error="Access denied")
            await request(session, "list_pods", {
                "namespace": "default", "label_selector": "",
            }, error="Access denied")
            unknown_uid = "00000000-0000-0000-0000-000000000000"
            await request(session, "get_pod_events", {
                "namespace": "default", "pod_uid": unknown_uid,
            }, error="Access denied")
            print("PASS missing deployment and namespace access boundaries")
            empty_pods = await request(session, "list_pods", {
                "namespace": "mcp-demo", "label_selector": "app=unknown",
            })
            assert empty_pods["pods"] == [] and empty_pods["truncated"] is False
            empty_events = await request(session, "get_pod_events", {
                "namespace": "mcp-demo", "pod_uid": unknown_uid,
            })
            assert empty_events["events"] == [] and empty_events["truncated"] is False
            print("PASS empty results and session continuity after errors")
    print("All MCP integration checks passed.")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=60))
