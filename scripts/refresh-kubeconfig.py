"""Create a local lab kubeconfig with a short-lived mcp-reader token."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / ".local" / "admin-kubeconfig"
OUTPUT = ROOT / ".local" / "mcp-kubeconfig"


def kubectl(*arguments: str) -> str:
    return subprocess.check_output(
        ["kubectl", "--kubeconfig", str(ADMIN), "--context", "kind-mcp", *arguments],
        text=True,
    )


def main() -> None:
    source = json.loads(kubectl("config", "view", "--minify", "--flatten", "--raw", "-o", "json"))
    cluster = source["clusters"][0]["cluster"]
    # Copy only the endpoint and CA, never the administrator's credentials.
    connection = {
        "server": cluster["server"],
        "certificate-authority-data": cluster["certificate-authority-data"],
    }
    token = kubectl("-n", "mcp-demo", "create", "token", "mcp-reader", "--duration=1h").strip()
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "kind-mcp", "cluster": connection}],
        "users": [{"name": "mcp-reader", "user": {"token": token}}],
        "contexts": [{"name": "mcp-reader", "context": {
            "cluster": "kind-mcp", "user": "mcp-reader", "namespace": "mcp-demo",
        }}],
        "current-context": "mcp-reader",
    }
    # Atomic replacement; the temporary file is created with mode 0600.
    descriptor, temporary = tempfile.mkstemp(dir=OUTPUT.parent, prefix=".mcp-kubeconfig-")
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(config, file, indent=2)
            file.write("\n")
        os.replace(temporary, OUTPUT)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Saved reader kubeconfig: {OUTPUT}")
    print("Requested token duration: 1 hour. Re-run this script to refresh it.")


if __name__ == "__main__":
    main()
