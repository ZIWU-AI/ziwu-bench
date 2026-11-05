#!/usr/bin/env python3
"""Run a pinned, same-model harness comparison without changing task contents."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HARNESSES = ("claude-code", "codex", "kimi-code", "deepseek-harness")
TASK = "tasks/engineering-sciences/mechanical-engineering/friction-pinch-lift"
TASK_TREE = "98401f4e698ef0b84e92baab287c10bc257d1e97"
HARBOR_VERSION = "0.23.0"


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def check_task(path):
    if path != TASK:
        raise ValueError("This comparison only accepts the reviewed friction-pinch-lift task")
    tree = git("rev-parse", f"HEAD:{path}")
    if tree != TASK_TREE:
        raise ValueError(f"Task tree changed: {tree}")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", path], check=True,
                   stdout=subprocess.DEVNULL)
    if git("ls-files", "--others", "--exclude-standard", "--", path):
        raise ValueError("Untracked task files would change the comparison")
    return tree


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
            "cost_status": "unknown: CLI estimates are not verified Kimi billing",
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


def run_one(args):
    from importlib.metadata import version
    from routes import build_route
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": 1, "harness": args.harness, "model": "k3.1-pro",
               "provider": "kimi-code-official", "status": "preparing", "reward": None,
               "started_at": now(), "requested_trial_count": 1, "trial_count": 0, "hints": False,
               "run_url": os.environ.get("COMPARISON_RUN_URL"),
               "workflow_sha": os.environ.get("GITHUB_SHA"),
               "source_ref": os.environ.get("COMPARISON_TASK_REF", git("rev-parse", "HEAD")),
               "agent_timeout_sec": 5400, "harbor_version": version("harbor")}
    write_json(output / "summary.json", summary)
    secret = os.environ.get("KIMI_CODE_API_KEY", "")
    exit_code = 1
    try:
        if summary["harbor_version"] != HARBOR_VERSION:
            raise ValueError("This comparison requires Harbor 0.23.0")
        summary["task_tree"] = check_task(args.task)
        if not secret:
            summary["status"] = "credential_missing"
            raise ValueError("KIMI_CODE_API_KEY is not configured")
        with tempfile.TemporaryDirectory(prefix="ziwu-harness-private-") as private:
            private_dir = Path(private)
            route = build_route(args.harness, private_dir)
            summary["route"] = route["provenance"]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent)
            env.update(route["env"])
            env.update({name: secret for name in route["credential_env_names"]})
            preflight = private_dir / "preflight"
            make_preflight(preflight)
            cfg = job_config(route, preflight, output / "preflight", "check", secret, 300)
            summary["status"] = "preflight_running"
            write_json(output / "summary.json", summary)
            code = execute(cfg, private_dir, output, "preflight", env)
            summary["preflight"] = collect(output / "preflight/check")
            summary["preflight"]["harbor_exit_code"] = code
            if code or summary["preflight"]["status"] != "passed":
                summary["status"] = "preflight_failed"
                return 1
            summary["status"] = "trial_running"
            summary["trial_count"] = 1
            write_json(output / "summary.json", summary)
            cfg = job_config(route, Path(args.task), output / "trial", "comparison", secret, 5400)
            code = execute(cfg, private_dir, output, "trial", env)
            summary.update(collect(output / "trial/comparison"))
            summary["harbor_exit_code"] = code
            if code and summary["status"] in ("passed", "not_passed"):
                summary["status"], summary["reward"] = "execution_error", None
            exit_code = 0 if summary["status"] in ("passed", "not_passed") else 1
    except Exception as exc:
        if summary["status"] != "credential_missing":
            summary["status"] = "execution_error"
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        summary["finished_at"] = now()
        write_json(output / "summary.json", summary)
        scrub_tree(output, secret)
        print(json.dumps({"harness": args.harness, "status": summary["status"],
                          "reward": summary.get("reward")}, ensure_ascii=False))
    return exit_code


def report(source, output):
    rows = {}
    for path in source.rglob("summary.json"):
        data = json.loads(path.read_text())
        if data.get("harness") in HARNESSES:
            if data["harness"] in rows:
                raise ValueError("Duplicate harness result; do not silently choose a trial")
            rows[data["harness"]] = data
    for name in HARNESSES:
        rows.setdefault(name, {"harness": name, "status": "job_missing", "reward": None})
    write_json(output / "comparison.json", {"schema_version": 1, "results": list(rows.values())})
    text = ["# Same-model harness comparison", "", "Model: Kimi k3.1-pro. One exploratory trial per harness; 90-minute agent limit.",
            "This measures the configured harness + adapter, not a statistically established ranking.", "",
            "| Harness | Status | Reward | Physical episodes passed |", "|---|---|---:|---:|"]
    for name in HARNESSES:
        row = rows[name]
        metrics = row.get("physical_metrics") or {}
        passed, total = metrics.get("passed"), metrics.get("episodes")
        physical = f"{passed}/{total}" if passed is not None and total is not None else "—"
        reward = row.get("reward")
        text.append(f"| {name} | {row['status']} | {reward if reward is not None else '—'} | {physical} |")
    text += ["", "Missing usage is unknown, not zero. Execution errors and exhausted budgets are not scored as model failures.",
             "See comparison.json and each job's scrubbed artifacts for versions, configuration differences and verification evidence.", ""]
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.md").write_text("\n".join(text))
    return output / "comparison.md"


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--harness", choices=HARNESSES, required=True)
    run.add_argument("--task", default=TASK)
    run.add_argument("--output", type=Path, required=True)
    aggregate = commands.add_parser("report")
    aggregate.add_argument("--input", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run_one(args)
    path = report(args.input, args.output)
    print(path.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
