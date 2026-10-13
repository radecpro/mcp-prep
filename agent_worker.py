"""Internal subprocess worker; agent.py owns cancellation and tool dispatch."""

import json
import sys

import answer
import integrate


def main():
    request = json.loads(sys.stdin.read(1_000_001))
    kind = request["kind"]
    if kind == "plan":
        result = answer.generate(request["context"], request["system"], request["schema"],
                                 request["model"], num_predict=512)
    elif kind == "retrieve":
        result = integrate.retrieve(request["evidence"], request["top_k"])
    elif kind == "interpret":
        result = integrate.interpret(request["evidence"], model=request["model"], sources=request["sources"])
    else:
        raise ValueError("Unknown worker operation")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
