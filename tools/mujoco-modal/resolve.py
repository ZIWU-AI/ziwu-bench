"""Resolve maintainer-selected PR files to one immutable commit before secrets."""
import json
import os
import re
import subprocess
from config import task_path


def main():
    path = task_path(os.environ["TASK_PATH"])
    pr = os.environ.get("PR_NUMBER", "0")
    if not pr.isascii() or not pr.isdecimal():
        raise ValueError("PR number must be a nonnegative integer")
    trials = int(os.environ.get("TRIALS", "1"))
    if not 1 <= trials <= 3:
        raise ValueError("trials must be between 1 and 3")
    repo = os.environ["GITHUB_REPOSITORY"]
    if int(pr):
        data = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/pulls/{int(pr)}"], text=True))
        sha = data["head"]["sha"]
    else:
        sha = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("expected an immutable source SHA")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"source_sha={sha}\ntask_path={path}\nmatrix={json.dumps(list(range(1, trials+1)))}\n")


if __name__ == "__main__":
    main()
