"""Isaac 5.1 provisioning and hardware contract from PR #2195's A10 infra.

Task Dockerfiles are unchanged. Host layers contain only the original reviewed
RTX packages, pinned Python dependencies, and hash-verified NVIDIA extensions.
"""
import os
from pathlib import Path
import modal
from a10_runtime import (RTX_USERSPACE_PACKAGES, NATIVE_BUILD_COMMANDS,
    EXTENSION_ROOTS, EXTENSION_TARGET, verified_host_extension_cache,
    inspect_gpu, inspect_placement, inspect_resources, GPU_NAME, DRIVER_VERSION,
    CLOUD, REGION)

BASE_IMAGE = "task Dockerfile: nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04"
ENGINE = "5.1.0.0"
IGNORE = ["**/__pycache__/**", "**/*.pyc"]


def image_for(directory, extensions=None):
    directory = Path(directory)
    root = Path(extensions or os.environ["ZIWU_ISAAC_EXTENSIONS"]).resolve()
    os.environ["PR61_ISAAC_EXTENSION_CACHE"] = str(root)
    os.environ["PR61_ISAAC_EXTENSION_MANIFEST"] = str(root / "EXTENSIONS.json")
    root, _ = verified_host_extension_cache()
    image = modal.Image.from_dockerfile(directory / "Dockerfile",
        context_dir=directory, ignore=IGNORE)
    image = image.apt_install(*RTX_USERSPACE_PACKAGES).run_commands(*NATIVE_BUILD_COMMANDS)
    for name in EXTENSION_ROOTS:
        image = image.add_local_dir(root / name, EXTENSION_TARGET + "/" + name, copy=True)
    return image


async def verify_hardware(sb):
    name, driver = await inspect_gpu(sb)
    result = {"hardware": name + ", " + driver,
              "required_driver_version": DRIVER_VERSION}
    if name != GPU_NAME or driver != DRIVER_VERSION:
        raise RuntimeError("PR #2195 hardware mismatch: expected " + GPU_NAME +
            " / " + DRIVER_VERSION + "; allocated " + result["hardware"])
    placement = await inspect_placement(sb)
    result.update(placement)
    if placement["cloud_provider"] not in (None, CLOUD) or placement["region"] not in (None, REGION):
        raise RuntimeError("PR #2195 OCI eu-west placement mismatch")
    result["resources"] = await inspect_resources(sb)
    if result["resources"]["measured"]["limit_check"] != "matches_requested_hard_limits":
        raise RuntimeError("Unable to confirm PR #2195 hard 4 CPU / 16 GiB limits")
    return result
