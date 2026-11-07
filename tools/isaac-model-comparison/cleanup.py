"""Stop and confirm only native sandboxes recorded by this job's trusted adapter."""
import argparse
import json
from pathlib import Path
import time
import modal


def cleanup(source, timeout=30):
    failed = []
    for path in source.glob("trial/comparison/*/native-lifecycle/*.json"):
        record = json.loads(path.read_text())
        identifier = record.get("sandbox_id")
        if not identifier:
            continue
        try:
            sb = modal.Sandbox.from_id(identifier)
            sb.terminate()
            record["cleanup_requested"] = True
            deadline = time.monotonic() + timeout
            code = sb.poll()
            while code is None and time.monotonic() < deadline:
                time.sleep(1)
                code = sb.poll()
            record.update(cleanup_exit_code=code, cleanup_confirmed=code is not None)
            if code is None:
                failed.append(identifier)
        except modal.exception.NotFoundError:
            record.update(cleanup_confirmed=True, cleanup_status="already_absent")
        except Exception as exc:
            record.update(cleanup_confirmed=False, cleanup_error_type=type(exc).__name__)
            failed.append(identifier)
        path.write_text(json.dumps(record, indent=2) + "\n")
    if failed:
        raise RuntimeError("Sandbox cleanup not confirmed: " + ", ".join(failed))


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--source", type=Path, required=True)
    cleanup(p.parse_args().source)
