"""Publish one sanitized result row; never raw model logs, keys or recordings."""
import argparse
import json
import os
from pathlib import Path


def publish(source, output):
    output.mkdir(parents=True, exist_ok=True)
    path = source / "summary.json"
    data = json.loads(path.read_text()) if path.is_file() else {
        "status": "job_incomplete", "reward": None, "profile": os.environ.get("MODEL_PROFILE"),
        "harness": os.environ.get("HARNESS"), "trial_count": 0}
    # Exceptions can include full commands/transcripts; expose only their type.
    for item in [data, data.get("preflight", {})]:
        error = item.get("exception_info")
        if error: item["exception_info"] = {"exception_type": error.get("exception_type")}
    if "error" in data: data["error"] = data["error"].split(":", 1)[0]
    (output / "result.json").write_text(json.dumps(data, indent=2) + "\n")
    lifecycle = []
    for path in source.glob("trial/comparison/*/native-lifecycle/*.json"):
        lifecycle.append(json.loads(path.read_text()))
    (output / "lifecycle.json").write_text(json.dumps(lifecycle, indent=2) + "\n")
    text = (f"### {data.get('model', data.get('profile'))} / {data.get('harness')}\n\n"
            f"Status: **{data['status']}**; reward: **{data.get('reward')}**.\n\n"
            f"Task source: `{data.get('source_sha', 'unknown')}`. One exploratory trial; no ranking claimed.\n")
    (output / "SUMMARY.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f: f.write(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--source", type=Path, required=True);p.add_argument("--output", type=Path, required=True)
    a = p.parse_args();publish(a.source,a.output)
