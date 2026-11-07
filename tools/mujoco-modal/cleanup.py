"""Stop only sandboxes recorded by this workflow's trusted runner."""
import argparse
import json
from pathlib import Path
import modal


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    lifecycle = args.run / "lifecycle.json"
    if lifecycle.exists():
        result = []
        for record in json.loads(lifecycle.read_text()):
            sandbox = modal.Sandbox.from_id(record["sandbox_id"])
            sandbox.terminate()
            result.append({"sandbox_id": sandbox.object_id, "cleanup_requested": True})
        (args.run / "cleanup.json").write_text(json.dumps(result, indent=2) + "\n")
