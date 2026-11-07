"""Validate data and paths without importing task-controlled Python."""
from pathlib import Path
import re
import tomllib

TASK_PATTERN = r"tasks/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+"


def task_path(value):
    if not re.fullmatch(TASK_PATTERN, value):
        raise ValueError("task_path must be tasks/<domain>/<field>/<slug>")
    return value


def safe_task(root, value):
    task_path(value)
    root = Path(root).resolve()
    task = root / value
    task.resolve().relative_to(root)
    for p in [task, *task.parents]:
        if p == root:
            break
        if p.is_symlink():
            raise ValueError("symlink task paths are not supported")
    if not task.is_dir() or any(p.is_symlink() for p in task.rglob("*")):
        raise ValueError("task must exist and contain no symlinks")
    return task


def validate_task(root, value):
    task = safe_task(root, value)
    required = ["task.toml", "environment/Dockerfile", "environment/runtime/launch.py",
                "environment/runtime/collect.py", "environment/runtime/world.py",
                "environment/client.py", "solution/solve.sh", "tests/Dockerfile",
                "tests/test.sh", "authoring/test_runtime.py"]
    for name in required:
        if not (task / name).is_file():
            raise ValueError(f"unsupported protected MuJoCo task: missing {name}")
    config = tomllib.loads((task / "task.toml").read_text())
    if config.get("verifier", {}).get("environment_mode") != "separate":
        raise ValueError("a separate verifier is required")
    return task
