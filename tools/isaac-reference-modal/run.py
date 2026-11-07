"""Explicit Isaac 5.1 reference/Nop execution with fresh native GPU verification.

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
from prepare_extensions import MANIFEST, MANIFEST_SHA256, RELEASES

IGNORE = ["**/__pycache__/**", "**/*.pyc"]
PYTHON = "/opt/venv/bin/python"


def extension_cache(root):
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Extension manifest changed")
    expected = json.loads(raw)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(expected) | {"EXTENSIONS.json"} or any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Extension cache file set changed")
    for name, digest in expected.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Extension cache digest differs: " + name)
    if (root / "EXTENSIONS.json").read_bytes() != raw:
        raise ValueError("Extension cache manifest differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, default=ROOT)
    parser.add_argument("--task-path", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--extensions", type=Path, required=True)
    parser.add_argument("--gpu", choices=["L40S", "A10"], default="L40S")
    parser.add_argument("--mode", choices=["all", "oracle", "nop"], default="all")
    args = parser.parse_args()
    args.source_sha = subprocess.check_output(["git", "rev-parse", "--verify", args.source_sha + "^{commit}"], cwd=args.task_root, text=True).strip()
    task = safe_task(args.task_root, args.task_path)
    for role in ("environment", "tests"):
        manifest = json.loads((task / role / "bundle/manifest.json").read_text())
        if manifest["isaac_version"] != "5.1.0.0":
            raise ValueError("This runner requires Isaac Sim 5.1")
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
    extension_cache(args.extensions)
    args.output.mkdir(parents=True, exist_ok=False)
    def write(path, data):
        path.write_text(json.dumps(data, indent=2) + "\n")
    write(args.output / "input-receipt.json", {
        "task_path": args.task_path, "source_sha": args.source_sha,
        "runner_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "infra_pr": "https://github.com/harbor-framework/terminal-bench-science/pull/2195",
        "infra_commit": "da218ea01206441256e7e9da6e76ef41e12cef65",
        "engine": "Isaac Sim 5.1.0.0", "physics": "PhysX CPU", "rendering": "NVIDIA RTX GPU",
        "extensions_manifest_sha256": MANIFEST_SHA256, "gpu": args.gpu,
        "modal_version": modal.__version__, "model_calls": 0, "files": files,
    })
    app = modal.App.lookup("ziwu-isaac-reference", create_if_missing=True)
    records = []
    def save():
        write(args.output / "lifecycle.json", records)
    def image_for(role):
        image = modal.Image.from_dockerfile(task / role / "Dockerfile", context_dir=task / role, ignore=IGNORE)
        for release in RELEASES:
            name = release["root"]
            image = image.add_local_dir(args.extensions / name,
                "/opt/venv/lib/python3.11/site-packages/isaacsim/extscache/" + name, copy=True)
        return image
    def allocate(image, role):
        print("Allocating " + role, flush=True)
        with modal.enable_output():
            sb = modal.Sandbox.create("sleep", "infinity", app=app, image=image, gpu=args.gpu,
                cpu=(4, 4), memory=(16384, 16384), timeout=10800, block_network=True)
        record = {"role": role, "sandbox_id": sb.object_id, "image_id": image.object_id,
                  "started": time.time(), "gpu_requested": args.gpu, "network": "blocked"}
        records.append(record); save()
        return sb, record
    def stop(sb, record):
        sb.terminate()
        record.update(cleanup_requested=True, ended=time.time(), exit_code=sb.poll())
        save()
    def diagnostics(sb, out):
        command(sb, out, "native-diagnostics", "sh", "-c",
            "tail -100 /var/lib/pen-render/startup.log /logs/verifier/native.log 2>/dev/null", timeout=30, check=False)
    outcomes = {}
    for mode in (("oracle", "nop") if args.mode == "all" else (args.mode,)):
        out = args.output / mode; out.mkdir()
        image = image_for("environment").add_local_dir(task / "solution", "/solution", copy=True, ignore=IGNORE)
        sb, record = allocate(image, mode)
        try:
            record["hardware"] = asyncio.run(preflight(sb)); save()
            if args.gpu not in record["hardware"]:
                raise RuntimeError("Requested GPU was not allocated")
            command(sb, out, "packages", PYTHON, "-m", "pip", "freeze")
            command(sb, out, "permissions", "sh", "-c",
                "! runuser -u agent -- test -r /opt/pen-runtime/registration.json && "
                "! runuser -u agent -- test -r /opt/robodojo/task/RoboDojo/tasks/fill_pen_holder.py")
            command(sb, out, "start-service", PYTHON, "-I", "/opt/pen-runtime/environment/start_service.py", timeout=660)
            if mode == "oracle":
                command(sb, out, "policy", "runuser", "-u", "agent", "--", "bash", "/solution/solve.sh", timeout=3600)
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
            command(sb, out, "replay", "bash", "/tests/test.sh", timeout=7300)
            download(sb, "/logs/verifier/reward.txt", out / "reward.txt")
            reward = int((out / "reward.txt").read_text().strip())
            metrics = None
            if mode == "oracle":
                download(sb, "/logs/verifier/metrics.json", out / "metrics.json")
                metrics = json.loads((out / "metrics.json").read_text())
            result = {"reward": reward, "mode": mode, "metrics": metrics, "model_calls": 0}
            write(out / "result.json", result)
            if reward != (1 if mode == "oracle" else 0):
                raise RuntimeError("Reference/control reward differs from expectation: " + str(reward))
            outcomes[mode] = reward
            record.update(status="complete", reward=reward)
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            try: diagnostics(sb, out)
            except Exception: pass
            raise
        finally:
            stop(sb, record)
    summary = {"passed": True, "engine": "Isaac Sim 5.1.0.0", "outcomes": outcomes, "model_calls": 0}
    write(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
