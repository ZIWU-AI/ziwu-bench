"""Explicit Modal GPU validation of the MuJoCo task; no model API calls.

Lifecycle adapted from upstream PR #2195 (da218ea01206441256e7e9da6e76ef41e12cef65):
A10 hardware preflight, bounded sandboxes, no-network data-only replay, cleanup.
The Isaac image/driver pin is deliberately not used for MuJoCo.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import threading
import time

import modal
from config import validate_task

ROOT = Path(__file__).resolve().parents[2]
IGNORE = ["**/__pycache__/**", "**/*.pyc"]


def command(sb, output, label, *args, timeout=600, check=True):
    print(label, flush=True)
    proc = sb.exec(*args, timeout=timeout)
    def drain(stream, path):
        with path.open("w") as log:
            for chunk in stream:
                log.write(chunk)
                log.flush()
    readers = [threading.Thread(target=drain, args=(stream, output / (label + suffix)))
               for stream, suffix in ((proc.stdout, ".stdout"), (proc.stderr, ".stderr"))]
    for reader in readers:
        reader.start()
    code = proc.wait()
    for reader in readers:
        reader.join()
    if check and code:
        raise RuntimeError(f"{label} exited {code}: {(output / (label + '.stderr')).read_text()[-4000:]}")
    return code


async def preflight(sb):
    async def query():
        proc = await sb.exec.aio("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader", timeout=30)
        text = await proc.stdout.read.aio()
        if await proc.wait.aio():
            raise RuntimeError("GPU inventory failed")
        return text.strip()
    return await asyncio.wait_for(query(), timeout=300)


def download(sb, remote, local):
    sb.filesystem.copy_to_local(remote, local)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", choices=("A10", "L40S"), default="A10")
    parser.add_argument("--mode", choices=("all", "oracle", "nop"), default="all")
    parser.add_argument("--task-root", type=Path, default=ROOT)
    parser.add_argument("--task-path", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--app-name", default="benchmark-mujoco-validation")
    args = parser.parse_args()
    task = validate_task(args.task_root, args.task_path)
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "task_path": args.task_path, "source_sha": args.source_sha,
        "runner_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "infra_pr": "https://github.com/harbor-framework/terminal-bench-science/pull/2195",
        "infra_commit": "da218ea01206441256e7e9da6e76ef41e12cef65",
        "modal_version": modal.__version__, "gpu": args.gpu, "model_calls": 0,
        "files": {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(task.rglob("*")) if p.is_file() and "__pycache__" not in p.parts},
    }
    (args.output / "input-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    app = modal.App.lookup(args.app_name, create_if_missing=True)
    base = (modal.Image.from_dockerfile(task / "environment/Dockerfile", context_dir=task / "environment", ignore=IGNORE)
            .apt_install("libegl1", "libgles2")
            .env({"MUJOCO_GL": "egl", "PYOPENGL_PLATFORM": "egl", "LIBGL_ALWAYS_SOFTWARE": "0",
                  "NVIDIA_DRIVER_CAPABILITIES": "all"})
            .run_commands("printf 'egl\\n' > /opt/pen-control/render-backend"))
    verifier = modal.Image.from_dockerfile(task / "tests/Dockerfile", context_dir=task / "tests", ignore=IGNORE)
    records = []
    def save():
        (args.output / "lifecycle.json").write_text(json.dumps(records, indent=2) + "\n")
    def allocate(image, role, gpu=None):
        with modal.enable_output():
            sb = modal.Sandbox.create("sleep", "infinity", app=app, image=image, gpu=gpu,
                                      cpu=4, memory=4096, timeout=1800, block_network=True)
        record = {"role": role, "sandbox_id": sb.object_id, "started": time.time(), "gpu_requested": gpu}
        records.append(record)
        save()
        return sb, record
    outcomes = {}
    for mode in (("oracle", "nop") if args.mode == "all" else (args.mode,)):
        output = args.output / mode
        output.mkdir()
        image = base.add_local_dir(task / "solution", "/solution", copy=True, ignore=IGNORE)
        if mode == "oracle":
            image = image.add_local_dir(task, "/validation/task", copy=True, ignore=IGNORE)
        sb, record = allocate(image, mode, args.gpu)
        try:
            record["hardware"] = asyncio.run(preflight(sb)); save()
            command(sb, output, "packages", "/opt/venv/bin/pip", "freeze")
            command(sb, output, "gpu-renderer", "/opt/venv/bin/python", "-c",
                    "import sys,json;sys.path.insert(0,'/opt/pen-control');from world import World;"
                    "from OpenGL import GL;w=World();"
                    "r=GL.glGetString(GL.GL_RENDERER).decode();v=GL.glGetString(GL.GL_VENDOR).decode();"
                    "print(json.dumps({'renderer':r,'vendor':v}));assert 'NVIDIA' in v;w.close()")
            if mode == "oracle":
                command(sb, output, "native-tests", "/opt/venv/bin/python", "-m", "pytest", "-q",
                        "/validation/task/authoring/test_runtime.py", "--junitxml=/tmp/native-tests.xml", timeout=900)
                download(sb, "/tmp/native-tests.xml", output / "native-tests.xml")
            command(sb, output, "permissions", "sh", "-c",
                    "! runuser -u agent -- test -r /opt/pen-control/model.py && "
                    "! runuser -u agent -- sudo -n /usr/local/bin/start-pen-service unexpected")
            command(sb, output, "start-service", "/opt/venv/bin/python", "-I", "/opt/pen-control/launch.py", timeout=60)
            if mode == "oracle":
                command(sb, output, "policy", "runuser", "-u", "agent", "--", "sh", "/solution/solve.sh", timeout=900)
            command(sb, output, "collect", "/opt/venv/bin/python", "-I", "/opt/pen-control/collect.py", timeout=120)
            command(sb, output, "pack", "tar", "-czf", "/tmp/recording.tar.gz", "-C", "/var/lib/pen-control/export", ".")
            download(sb, "/tmp/recording.tar.gz", output / "recording.tar.gz")
            record["status"] = "complete"
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            try:
                command(sb, output, "service-log", "cat", "/var/lib/pen-control/private/service.log", timeout=10, check=False)
            except Exception:
                pass
            raise
        finally:
            sb.terminate(); record["cleanup_requested"] = True; record["ended"] = time.time(); save()
        data = output / "recording"
        with tarfile.open(output / "recording.tar.gz") as archive:
            archive.extractall(data, filter="data")
        sb, record = allocate(verifier.add_local_dir(data, "/var/lib/pen-control/export", copy=True), mode + "-verifier")
        try:
            command(sb, output, "replay", "sh", "/tests/test.sh", timeout=600)
            for name in ("result.json", "reward.txt", "ctrf.json"):
                download(sb, "/logs/verifier/" + name, output / name)
            result = json.loads((output / "result.json").read_text())
            assert result["reward"] == (1 if mode == "oracle" else 0), result
            outcomes[mode] = result["reward"]
            record.update(status="complete", result=result)
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            raise
        finally:
            sb.terminate(); record["cleanup_requested"] = True; record["ended"] = time.time(); save()
    summary = {"passed": True, "outcomes": outcomes, "model_calls": 0}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
