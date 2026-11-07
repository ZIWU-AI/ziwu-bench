"""Explicit Isaac 6.0.1 reference/Nop execution with fresh native GPU verification.

Runtime dependencies and public extensions originate from upstream PR #2195 at
 da218ea01206441256e7e9da6e76ef41e12cef65. Task code runs only in Modal.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import modal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "mujoco-modal"))
from config import safe_task
from run import command, download, preflight
from image import image_for as native_image, BASE_IMAGE, verify_hardware

IGNORE = ["**/__pycache__/**", "**/*.pyc"]
PYTHON = "/opt/venv/bin/python"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, default=ROOT)
    parser.add_argument("--task-path", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--extensions", type=Path, help="Legacy Isaac 5 cache; unused by Isaac 6")
    parser.add_argument("--gpu", choices=["A10"], default="A10")
    parser.add_argument("--mode", choices=["all", "oracle", "nop"], default="all")
    parser.add_argument("--reference", choices=["v12-layout0", "v13-round01-layout0", "v13-smoke-layout0"], default="v12-layout0")
    args = parser.parse_args()
    args.source_sha = subprocess.check_output(["git", "rev-parse", "--verify", args.source_sha + "^{commit}"], cwd=args.task_root, text=True).strip()
    task = safe_task(args.task_root, args.task_path)
    for role in ("environment", "tests"):
        manifest = json.loads((task / role / "bundle/manifest.json").read_text())
        if manifest["isaac_version"] != "6.0.1.0":
            raise ValueError("This runner requires Isaac Sim 6.0.1")
    # Task bytes stay data on the credential-bearing host; only reviewed host
    # modules are imported. Fail if the selected task differs from its receipt.
    tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", args.source_sha, "--", args.task_path], cwd=args.task_root, text=True).splitlines()
    if not tracked:
        raise ValueError("Task must be committed at source-sha")
    files = {}
    for name in tracked:
        data = (args.task_root / name).read_bytes()
        original = subprocess.check_output(["git", "show", args.source_sha + ":" + name], cwd=args.task_root)
        if data != original:
            raise ValueError("Working task differs from source-sha: " + name)
        files[str(Path(name).relative_to(args.task_path))] = hashlib.sha256(data).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    def write(path, data):
        path.write_text(json.dumps(data, indent=2) + "\n")
    write(args.output / "input-receipt.json", {
        "task_path": args.task_path, "source_sha": args.source_sha,
        "runner_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "infra_pr": "https://github.com/harbor-framework/terminal-bench-science/pull/2195",
        "infra_commit": "da218ea01206441256e7e9da6e76ef41e12cef65",
        "engine": "Isaac Sim 6.0.1.0", "physics": "PhysX CPU", "rendering": "NVIDIA RTX GPU",
        "base_image_id": BASE_IMAGE, "gpu": args.gpu, "cpus": 4, "memory_mib": 16384,
        "modal_version": modal.__version__, "model_calls": 0, "reference": args.reference, "files": files,
    })
    app = modal.App.lookup("ziwu-isaac-reference", create_if_missing=True)
    records = []
    def save():
        write(args.output / "lifecycle.json", records)
    def image_for(role):
        return native_image(task / role)
    def allocate(image, role):
        print("Allocating " + role, flush=True)
        with modal.enable_output():
            sb = modal.Sandbox.create("sleep", "infinity", app=app, image=image, gpu=args.gpu, cloud="oci", region="eu-west",
                cpu=(4, 4), memory=(16384, 16384), timeout=10800, block_network=True)
        record = {"role": role, "sandbox_id": sb.object_id, "image_id": image.object_id,
                  "started": time.time(), "gpu_requested": args.gpu, "network": "blocked"}
        records.append(record); save()
        return sb, record
    def stop(sb, record):
        sb.terminate()
        deadline = time.monotonic() + 30
        code = sb.poll()
        while code is None and time.monotonic() < deadline:
            time.sleep(1)
            code = sb.poll()
        record.update(cleanup_requested=True, cleanup_confirmed=code is not None,
                      ended=time.time(), exit_code=code)
        save()
        if code is None:
            raise RuntimeError("Sandbox termination not confirmed")
    def diagnostics(sb, out):
        for name, path in {"startup": "/var/lib/pen-render/startup.log", "verifier": "/logs/verifier/native.log"}.items():
            try:
                (out / (name + ".log")).write_bytes(sb.filesystem.read_bytes(path)[-131072:])
            except Exception:
                pass
    outcomes = {}
    for mode in (("oracle", "nop") if args.mode == "all" else (args.mode,)):
        out = args.output / mode; out.mkdir()
        image = image_for("environment").add_local_dir(task / "solution", "/solution", copy=True, ignore=IGNORE)
        sb, record = allocate(image, mode)
        try:
            record["hardware"] = asyncio.run(preflight(sb)); save()
            record.update(asyncio.run(verify_hardware(sb))); save()
            if args.gpu not in record["hardware"]:
                raise RuntimeError("Requested GPU was not allocated")
            command(sb, out, "packages", PYTHON, "-m", "pip", "freeze")
            command(sb, out, "permissions", "sh", "-c",
                "! runuser -u agent -- test -r /opt/pen-runtime/registration.json && "
                "! runuser -u agent -- test -r /opt/robodojo/task/RoboDojo/tasks/fill_pen_holder.py")
            command(sb, out, "start-service", PYTHON, "-I", "/opt/pen-runtime/environment/start_service.py", timeout=660)
            if mode == "oracle":
                command(sb, out, "policy", "runuser", "-u", "agent", "--", "env", "RI_ORACLE_REFERENCE=" + args.reference, "bash", "/solution/solve.sh", timeout=3600)
            command(sb, out, "collect", PYTHON, "-I", "/opt/pen-runtime/environment/collect_recording.py", timeout=7300)
            command(sb, out, "pack", "tar", "-czf", "/tmp/recording.tar.gz", "-C", "/var/lib/pen-transfer/recording", ".")
            download(sb, "/tmp/recording.tar.gz", out / "recording.tar.gz")
            record["status"] = "complete"
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            try: diagnostics(sb, out)
            except Exception: pass
            raise
        finally:
            stop(sb, record)
        data = out / "recording"
        with tarfile.open(out / "recording.tar.gz") as archive:
            archive.extractall(data, filter="data")
        sb, record = allocate(image_for("tests").add_local_dir(data, "/var/lib/pen-transfer/recording", copy=True), mode + "-verifier")
        try:
            record["hardware"] = asyncio.run(preflight(sb)); save()
            record.update(asyncio.run(verify_hardware(sb))); save()
            command(sb, out, "replay", "bash", "/tests/test.sh", timeout=7300)
            download(sb, "/logs/verifier/reward.txt", out / "reward.txt")
            reward = int((out / "reward.txt").read_text().strip())
            metrics = None
            if mode == "oracle":
                download(sb, "/logs/verifier/metrics.json", out / "metrics.json")
                metrics = json.loads((out / "metrics.json").read_text())
            result = {"reward": reward, "mode": mode, "metrics": metrics, "model_calls": 0}
            write(out / "result.json", result)
            outcomes[mode] = reward
            expected = 1 if mode == "oracle" else 0
            record.update(status="complete" if reward == expected else "unexpected_reward", reward=reward)
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            try: diagnostics(sb, out)
            except Exception: pass
            raise
        finally:
            stop(sb, record)
    summary = {"passed": all(v == (1 if k == "oracle" else 0) for k, v in outcomes.items()), "engine": "Isaac Sim 6.0.1.0", "outcomes": outcomes, "model_calls": 0}
    write(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
