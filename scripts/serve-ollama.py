"""Run the project-local Ollama server in the foreground; stop with Ctrl+C."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / ".local" / "ollama" / "ollama"

if __name__ == "__main__":
    if not BINARY.is_file():
        raise SystemExit("Ollama binary missing; see the README local generation setup")
    os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
    os.environ["OLLAMA_MODELS"] = str(ROOT / ".local" / "ollama-models")
    os.environ["OLLAMA_NO_CLOUD"] = "1"
    os.execv(str(BINARY), [str(BINARY), "serve"])
