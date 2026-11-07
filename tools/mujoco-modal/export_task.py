"""Create a task-only patch against official main; never push or open a PR."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from config import safe_task

UPSTREAM = "https://github.com/harbor-framework/terminal-bench-science.git"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def bundle(repo, task_root, path, source_sha, output, base_ref=None):
    task = safe_task(task_root, path)
    if not (task / "task.toml").is_file() or not (task / "instruction.md").is_file():
        raise ValueError("task.toml and instruction.md are required")
    output.mkdir(parents=True, exist_ok=False)
    if base_ref is None:
        git(repo, "fetch", "--no-tags", UPSTREAM, "main")
        base_ref = "FETCH_HEAD"
    base_sha = git(repo, "rev-parse", base_ref).decode().strip()
    with tempfile.TemporaryDirectory(prefix="task-export-") as directory:
        worktree = Path(directory) / "official"
        git(repo, "worktree", "add", "--detach", str(worktree), base_sha)
        try:
            destination = worktree / path
            if destination.exists():
                raise ValueError("task already exists upstream; review an update diff manually")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(task, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            git(worktree, "add", "--force", "--", path)
            patch = git(worktree, "diff", "--cached", "--binary", "--", path)
            if not patch:
                raise ValueError("empty task patch")
            (output / "task.patch").write_bytes(patch)
            # The archive is produced by Git from exactly the staged task tree.
            tree = git(worktree, "write-tree").decode().strip()
            (output / "task.tar").write_bytes(git(worktree, "archive", tree, "--", path))
        finally:
            git(repo, "worktree", "remove", "--force", str(worktree))
    manifest = {"source_sha": source_sha, "task_path": path, "upstream": UPSTREAM,
                "upstream_base_sha": base_sha,
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "files": {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(task.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}}
    (output / "submission.json").write_text(json.dumps(manifest, indent=2) + "\n")
    slug = task.name
    script = f'''#!/usr/bin/env bash
set -euo pipefail
bundle_dir=$(cd -- "$(dirname -- "$0")" && pwd)
destination=${{1:?Usage: bash apply.sh NEW_DIRECTORY}}
test ! -e "$destination"
git clone --no-checkout https://github.com/RoboIndustrial-Benchmark/terminal-bench-science.git "$destination"
git -C "$destination" fetch {UPSTREAM} {base_sha}
git -C "$destination" switch -c submission/{slug} FETCH_HEAD
git -C "$destination" apply --index "$bundle_dir/task.patch"
printf '%s\\n' 'Task staged for review. No commit, push or PR has been created.'
'''
    (output / "apply.sh").write_text(script)
    (output / "PR_BODY.md").write_text(f"""## Task submission: {slug}

Task source: `{source_sha}`. Official base: `{base_sha}`.
This patch contains only `{path}/`.

Before submitting, include the approved proposal URL, author declarations,
the GPU validation run URL and the exact source SHA tested. GPU reference
validation alone does not establish a frontier-model solve or task admission.
See the task's authoring files for provenance and remaining review gates.
""")
    (output / "README.md").write_text(f"""# Official task submission bundle

Run `bash apply.sh ../{slug}-submission` to create a clean checkout based on
official `{base_sha}` and stage the task patch. Review the diff and PR body.
Then commit as your own GitHub account and push the submission branch to
`RoboIndustrial-Benchmark/terminal-bench-science`, which belongs to the official
fork network. `ZIWU-AI/ziwu-bench` is an independent repository and cannot be
used as the cross-fork PR head directly.

```bash
git -C ../{slug}-submission diff --cached --stat
git -C ../{slug}-submission commit -m 'Add {slug} task'
git -C ../{slug}-submission push git@github.com:RoboIndustrial-Benchmark/terminal-bench-science.git HEAD
gh pr create --draft --repo harbor-framework/terminal-bench-science \\
  --head RoboIndustrial-Benchmark:submission/{slug} --base main \\
  --title '[TASK] {slug}' --body-file PR_BODY.md
```

These are explicit operator commands. The exporter never pushes to the official
repository, never touches another contributor's fork and never posts comments.
The bundle does not attest that proposal, authorship or model-trial gates passed.
""")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--task-path", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle(Path.cwd(), args.task_root, args.task_path, args.source_sha, args.output)
