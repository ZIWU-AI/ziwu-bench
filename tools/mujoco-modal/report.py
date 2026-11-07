"""Publish allowlisted evidence; never publish oracle action recordings."""
import argparse
import json
import os
from pathlib import Path
import shutil


def report(run, output):
    output.mkdir(parents=True, exist_ok=True)
    names = {"summary.json", "input-receipt.json", "lifecycle.json", "cleanup.json", "result.json",
             "reward.txt", "ctrf.json", "native-tests.xml", "gpu-renderer.stdout", "packages.stdout"}
    for path in run.rglob("*"):
        relative = path.relative_to(run)
        if path.is_file() and path.name in names and "recording" not in relative.parts:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    summary = json.loads((run / "summary.json").read_text()) if (run / "summary.json").exists() else {"passed": False, "error": "incomplete run; inspect workflow logs and lifecycle"}
    lines = ["### GPU task validation", "", f"Source: `{os.environ.get('SOURCE_SHA', 'local')}`",
             f"Task: `{os.environ.get('TASK_PATH', 'local')}`", "", "```json", json.dumps(summary, indent=2), "```", "",
             "MuJoCo CPU physics / NVIDIA EGL rendering. Reference validation; no model calls.",
             "The artifact excludes oracle recordings, action plans and camera bundles."]
    text = "\n".join(lines) + "\n"
    (output / "SUMMARY.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report(args.run, args.output)
