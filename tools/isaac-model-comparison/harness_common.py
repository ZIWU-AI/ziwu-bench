"""Shared trial helpers imported from ziwu-bench PR #4 at 95febe6264a860bc69ee0364ff479788a536526b.
No task-specific routing or historical result is imported.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat()

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

def make_preflight(root):
    """A fresh, unscored connectivity/tool-use check, separate from the real task."""
    (root / "environment").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "instruction.md").write_text(
        "Use a shell or file-writing tool to create /app/harness-preflight.txt "
        "containing exactly ZIWU_HARNESS_OK followed by a newline. Then finish.\n")
    (root / "task.toml").write_text('''schema_version = "1.4"
[task]
name = "ziwu/harness-preflight"
description = "Synthetic tool-use preflight, not a benchmark result."
[agent]
timeout_sec = 300
[verifier]
timeout_sec = 60
network_mode = "no-network"
[environment]
build_timeout_sec = 1200
cpus = 2
memory_mb = 4096
network_mode = "public"
''')
    (root / "environment/Dockerfile").write_text('''FROM python:3.11.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates jq && rm -rf /var/lib/apt/lists/*
WORKDIR /app
CMD ["sleep", "infinity"]
''')
    (root / "tests/test.sh").write_text('''#!/bin/sh
mkdir -p /logs/verifier
python3 - <<'PY'
from pathlib import Path
p = Path('/app/harness-preflight.txt')
ok = p.is_file() and p.read_bytes() == b'ZIWU_HARNESS_OK\\n'
Path('/logs/verifier/reward.txt').write_text('1' if ok else '0')
PY
''')
    (root / "tests/test.sh").chmod(0o755)

def job_config(route, task, jobs, name, credential, timeout):
    agent = {"model_name": route["model_name"], "kwargs": route["kwargs"],
             "env": dict(route["env"]), "override_timeout_sec": timeout,
             "override_setup_timeout_sec": 1200}
    if route.get("import_path"):
        agent["import_path"] = route["import_path"]
    else:
        agent["name"] = route["agent"]
    agent["env"].update({key: credential for key in route["credential_env_names"]})
    return {"job_name": name, "jobs_dir": str(jobs.resolve()), "n_attempts": 1,
            "n_concurrent_trials": 1, "retry": {"max_retries": 0},
            "environment": {"type": "docker", "delete": True},
            "agents": [agent], "tasks": [{"path": str(task.resolve())}]}

def trial_result(job_dir):
    found = [p for p in job_dir.glob("*/result.json") if "__" in p.parent.name]
    if len(found) != 1:
        raise ValueError(f"Expected one trial result, found {len(found)}")
    return found[0], json.loads(found[0].read_text())

def classify(result):
    """Never turn infrastructure errors, missing scores or timeout into a scored 0."""
    error = result.get("exception_info")
    reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
    if error:
        kind = error.get("exception_type", "unknown")
        return ("budget_exhausted" if kind == "AgentTimeoutError" else "execution_error"), None
    if isinstance(reward, bool) or reward not in (0, 1):
        return "invalid_result", None
    return ("passed" if reward == 1 else "not_passed"), reward

def collect(job_dir):
    path, result = trial_result(job_dir)
    status, reward = classify(result)
    agent = result.get("agent_result") or {}
    metrics_path = path.parent / "verifier/metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
    return {"status": status, "reward": reward,
            "task_checksum": result.get("task_checksum"),
            "exception_info": result.get("exception_info"),
            "agent_info": result.get("agent_info"),
            "started_at": result.get("started_at"), "finished_at": result.get("finished_at"),
            "agent_execution": result.get("agent_execution"),
            "usage": {key: agent.get(key) for key in
                      ("n_input_tokens", "n_cache_tokens", "n_output_tokens")},
            "cost_usd": None,
            "cli_reported_cost_usd": agent.get("cost_usd"),
            "cost_status": "unknown: CLI estimates are not verified provider billing",
            "physical_metrics": metrics,
            "result_path": str(path.relative_to(job_dir.parent.parent))}

def scrub_tree(root, secret):
    """Remove literal credentials from all regular output files, not just JSON."""
    if not secret:
        return
    raw = secret.encode()
    for path in root.rglob("*"):
        if path.is_symlink():
            path.unlink()
        elif path.is_file():
            data = path.read_bytes()
            if raw in data:
                path.write_bytes(data.replace(raw, b"REDACTED"))

def execute(config, private_dir, output, stage, env):
    from harbor.models.job.config import JobConfig
    JobConfig.model_validate(config)  # Reject a broken adapter/config before model work.
    config_path = private_dir / f"{stage}.json"
    write_json(config_path, config)
    config_path.chmod(0o600)
    # Never echo the private JobConfig or complete inherited environment.
    with (output / f"{stage}-harbor.log").open("w") as log:
        result = subprocess.run(["harbor", "run", "-c", str(config_path)],
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    # Docker bind-mount output can be owned by root (including mode-0700 CLI
    # session directories). Recover it before collecting or scrubbing results.
    # This is limited to GitHub's disposable runner and this output directory.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
        target = output.resolve()
        if output.is_symlink() or not target.is_relative_to(workspace / "comparison-output"):
            raise ValueError("Refusing permission repair outside comparison-output")
        subprocess.run(["sudo", "chown", "-hR", "--", f"{os.getuid()}:{os.getgid()}", str(target)], check=True)
        subprocess.run(["sudo", "find", "-P", str(target), "-type", "d", "-exec", "chmod", "u+rwx", "{}", "+"], check=True)
        subprocess.run(["sudo", "find", "-P", str(target), "-type", "f", "-exec", "chmod", "u+rw", "{}", "+"], check=True)
    return result.returncode
