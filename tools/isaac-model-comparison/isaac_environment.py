"""Trusted Harbor adapter for the reviewed protected Isaac 5.1.0 service.

No policy or scoring patches. Agent runs as uid agent; root starts and collects
its simulator. The independent GPU verifier receives data, not agent secrets.
"""
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

import modal
from harbor.environments.modal import ModalEnvironment

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "isaac-reference-modal"))
from image import image_for, BASE_IMAGE, verify_hardware


class IsaacEnvironment(ModalEnvironment):
    def __init__(self, *args, **kwargs):
        if importlib.metadata.version("harbor") != "0.23.0":
            raise ValueError("This adapter requires Harbor 0.23.0")
        if kwargs.get("secrets") or kwargs.get("volumes") or kwargs.get("extra_docker_compose"):
            raise ValueError("No shared secrets, volumes or extra services in native trial")
        super().__init__(*args, **kwargs)
        self._isaac_role = "agent" if (self.environment_dir / "sim-service").is_dir() else "verifier"
        manifest = json.loads((self.environment_dir / "bundle/manifest.json").read_text())
        if manifest["isaac_version"] != "5.1.0.0":
            raise ValueError("This adapter requires the Isaac 5.1.0 bundle")
        if self._compose_mode or self._vm_runtime_enabled:
            raise ValueError("Only direct Modal containers are supported")
        if self._isaac_role == "verifier" and not self._network_disabled:
            raise ValueError("The verifier must be network isolated")
        self._native_receipt = {"role": self._isaac_role, "status": "preparing"}

    def _save_native(self):
        out = self.trial_paths.trial_dir / "native-lifecycle"
        out.mkdir(parents=True, exist_ok=True)
        (out / (self._isaac_role + ".json")).write_text(json.dumps(self._native_receipt, indent=2) + "\n")

    async def _create_sandbox(self, *, entrypoint=None, block_network=None, experimental_options=None):
        if experimental_options:
            raise ValueError("Experimental runtimes are not registered")
        self._image = image_for(self.environment_dir)
        if block_network is None: block_network = self._network_disabled
        options = {}
        if self._dynamic_network:
            block_network = False
            options.update(self._dynamic_network_kwargs(self.network_policy))
        elif self._network_is_allowlist:
            options.update(self._allowlist_network_kwargs(self.network_policy))
        # One allocation, no paid replacement loop. Fresh source-only Dockerfile
        # image: never reuse the Oracle image that contains /solution.
        sb = await modal.Sandbox.create.aio(*(entrypoint or ["sleep", "infinity"]),
            app=self._app, image=self._image, gpu="A10", cloud="oci", region="eu-west", cpu=(4, 4), memory=(16384, 16384),
            timeout=18000 if self._isaac_role == "agent" else 10800,
            block_network=block_network, **options)
        self._sandbox_termination_requested = False
        self._native_receipt.update(sandbox_id=sb.object_id, image_id=self._image.object_id,
            started_at=time.time(), status="allocated", network=self.network_policy.network_mode.value,
            base_image_id=BASE_IMAGE, cpus=4, memory_mib=16384, isaac_version="5.1.0.0")
        self._save_native()
        try:
            proc = await sb.exec.aio("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader", timeout=30)
            self._native_receipt["hardware"] = (await proc.stdout.read.aio()).strip()
            self._save_native()
            self._native_receipt.update(await verify_hardware(sb))
            self._save_native()
            return sb
        except BaseException:
            await sb.terminate.aio()
            self._native_receipt["cleanup_requested"] = True; self._save_native()
            raise

    async def start(self, force_build):
        try:
            await super().start(force_build)
            if self._isaac_role == "agent":
                result = await self.exec("/opt/venv/bin/python -I /opt/pen-runtime/environment/start_service.py",
                                         cwd="/", user="root", timeout_sec=660)
                if result.return_code:
                    raise RuntimeError("Protected Isaac startup failed before model execution")
                self._native_receipt["status"] = "native_ready"
                self._save_native()
        except BaseException:
            if self._sandbox:
                await asyncio.shield(self._terminate_sandbox())
            raise

    async def _terminate_sandbox(self):
        if not self._sandbox: return
        sb = self._sandbox
        # Keep bounded native diagnostics private, including startup failures.
        try:
            proc = await sb.exec.aio("sh", "-c",
                "tail -100 /var/lib/pen-render/startup.log /logs/verifier/native.log 2>/dev/null", timeout=20)
            data = await proc.stdout.read.aio()
            out = self.trial_paths.trial_dir / "private-native"
            out.mkdir(parents=True, exist_ok=True)
            (out / (self._isaac_role + ".log")).write_text(data[-16384:])
        except Exception:
            pass
        await sb.terminate.aio()
        self._sandbox_termination_requested = True
        self._native_receipt.update(cleanup_requested=True, ended_at=time.time())
        deadline = time.monotonic() + 30
        status = await sb.poll.aio()
        while status is None and time.monotonic() < deadline:
            await asyncio.sleep(1); status = await sb.poll.aio()
        self._native_receipt.update(exit_code=status, cleanup_confirmed=status is not None)
        self._save_native()
        if status is None: raise RuntimeError("Native sandbox termination not confirmed")
