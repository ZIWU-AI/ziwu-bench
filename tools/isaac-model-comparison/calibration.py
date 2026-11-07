"""Bind calibration to evaluation bytes, independently of authoring-only edits."""
import hashlib
import json
from pathlib import Path
import subprocess


def identity(root, sha, task):
    paths = [task + '/' + part for part in ('environment', 'tests', 'instruction.md', 'task.toml')]
    tree = subprocess.check_output(['git', 'ls-tree', '-r', sha, '--', *paths], cwd=root)
    if not tree:
        raise ValueError('Evaluation task tree is empty')
    return hashlib.sha256(tree).hexdigest()


def calibration(root, sha, task, evidence, runtime=None):
    digest = identity(root, sha, task)
    if not evidence.is_file():
        return {'status': 'not_recorded', 'evaluation_tree_sha256': digest}
    data = json.loads(evidence.read_text())
    if data.get('evaluation_tree_sha256') != digest:
        return {'status': 'different_evaluation_tree', 'evaluation_tree_sha256': digest}
    if runtime is not None and data.get("runtime") != runtime:
        return {"status": "different_runtime", "evaluation_tree_sha256": digest, "runtime": runtime}
    return data


def runtime_spec(host_root):
    return {"gpu": "A10", "cpus": 4, "memory_mib": 16384,
            "isaac_version": "6.0.1.0", "modal_version": "1.5.5",
            "cloud": "oci", "region": "eu-west", "required_driver": "610.57.04",
            "a10_runtime_sha256": hashlib.sha256((Path(host_root) / "tools/isaac-reference-modal/a10_runtime.py").read_bytes()).hexdigest(),
            "image_builder_sha256": hashlib.sha256(
                (Path(host_root) / "tools/isaac-reference-modal/image.py").read_bytes()).hexdigest()}
