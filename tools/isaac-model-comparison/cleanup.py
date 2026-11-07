"""Stop only native sandboxes recorded by this job's trusted Harbor adapter."""
import argparse
import json
from pathlib import Path
import modal

p = argparse.ArgumentParser(); p.add_argument("--source", type=Path, required=True); a = p.parse_args()
for path in a.source.glob("trial/comparison/*/native-lifecycle/*.json"):
    record = json.loads(path.read_text())
    if record.get("sandbox_id"):
        sb = modal.Sandbox.from_id(record["sandbox_id"])
        sb.terminate()
        record["cleanup_requested"] = True
        record["cleanup_exit_code"] = sb.poll()
        path.write_text(json.dumps(record, indent=2) + "\n")
