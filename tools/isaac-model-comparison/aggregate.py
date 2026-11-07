"""Preserve one result per requested pair; missing/error rows are never zeros."""
import argparse
import json
import os
from pathlib import Path
from matrix import matrix
from profiles import PROFILES


def aggregate(source, output, profile, harness):
    rows = {}
    for path in source.glob("*/result.json"):
        row = json.loads(path.read_text()); key = (row.get("profile"), row.get("harness"))
        if key in rows: raise ValueError("Duplicate result for " + repr(key))
        rows[key] = row
    result = []
    for pair in matrix(profile, harness)["include"]:
        key = (pair["profile"], pair["harness"])
        result.append(rows.get(key, {**pair, "model": PROFILES[key[0]]["model"], "status": "result_missing", "reward": None}))
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Isaac / Modal model and harness comparison", "",
             "One exploratory trial per pair. Preflight is not a task score; errors and missing results have no reward.", "",
             "| Model | Harness | Status | Reward |", "|---|---|---|---:|"]
    for row in result:
        reward = row.get("reward")
        lines.append(f"| {row.get('model', row['profile'])} | {row['harness']} | {row['status']} | {reward if reward is not None else '—'} |")
    lines += ["", "See comparison.json for task/host SHAs, timings, usage, native metrics and route differences.",
              "Provider billing is unknown unless independently measured; CLI cost estimates are separate."]
    text = "\n".join(lines) + "\n"; (output / "COMPARISON.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:f.write(text)


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--source", type=Path, required=True);p.add_argument("--output", type=Path, required=True)
    p.add_argument("--profile", default="all");p.add_argument("--harness", default="all")
    a=p.parse_args();aggregate(a.source,a.output,a.profile,a.harness)
