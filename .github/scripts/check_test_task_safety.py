"""Decide which PR tasks the open /test command may run on the GitHub runner.

/run is maintainer-only, so it trusts the task it runs. /test runs for any PR
author, and the task's environment/ is theirs: harbor builds and starts it on
the runner's Docker daemon, in the same job that holds the /test model key.
A plain Dockerfile cannot see the host, but a docker-compose file can ask for
it (bind mounts, privileged, host pid/network, devices, extra capabilities,
a build context outside the task). Any of those would let the task read the
runner's environment, so /test refuses such a task and points at /run instead.

The task's declared backend is checked too: /test is docker-only, so a task
that needs Modal (or any other remote backend) is skipped rather than run on a
runner it does not fit.

Reads a JSON list of task dirs on stdin; prints
  {"runnable": [...], "skipped": [{"task": ..., "reason": ...}, ...]}
"""
import json
import pathlib
import re
import sys
import tomllib

import yaml

# Service keys that reach the host or widen the container's privileges.
FORBIDDEN_SERVICE_KEYS = {
    "privileged", "pid", "ipc", "network_mode", "devices", "device_cgroup_rules",
    "userns_mode", "cgroup_parent", "cgroup", "volumes_from", "uts", "runtime",
    "sysctls", "extra_hosts", "secrets", "configs", "env_file",
}
# Capabilities the existing tasks actually use (noisy-blackbox-optimization
# drops ALL and adds these back); anything else is refused.
ALLOWED_CAPS = {"KILL", "SETGID", "SETUID", "CHOWN", "DAC_OVERRIDE", "FOWNER", "NET_BIND_SERVICE"}


# Compose interpolates ${VAR} from the environment of the process that runs it --
# harbor, on the runner, holding the model key. So `environment: {X: ${OPENAI_API_KEY}}`
# would hand the key to the container. Only harbor's own variables and the sizing
# knobs existing tasks use may be referenced.
ALLOWED_VARS = {
    "CONTEXT_DIR", "CPUS", "MEMORY", "HARBOR_CONTAINER_NAME", "PREBUILT_IMAGE_NAME",
    "EGRESS_CONTROL_INITIAL_ALLOWED_HOSTS", "EGRESS_CONTROL_INITIAL_NETWORK_MODE",
    "EGRESS_CONTROL_SIDECAR_IMAGE_NAME",
}
VAR_REF = re.compile(r"(?<!\$)\$\{?([A-Za-z_][A-Za-z0-9_]*)")


def compose_problems(path: pathlib.Path) -> list[str]:
    text = path.read_text()
    try:
        doc = yaml.safe_load(text) or {}
    except Exception as e:  # unparseable compose is refused, not guessed at
        return [f"{path.name} does not parse ({e.__class__.__name__})"]
    problems = []
    foreign = sorted({v for v in VAR_REF.findall(text.replace("$$", "")) if v not in ALLOWED_VARS})
    if foreign:
        problems.append(f"references environment variables {foreign}")
    if doc.get("volumes") or doc.get("secrets") or doc.get("configs"):
        problems.append("top-level volumes/secrets/configs")
    for name, svc in (doc.get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        for key in sorted(FORBIDDEN_SERVICE_KEYS & svc.keys()):
            problems.append(f"service `{name}` sets `{key}`")
        for vol in svc.get("volumes") or []:
            # Named ("data:/x") and anonymous ("/x") volumes are fine; a host path
            # source ("/", ".", "~" or a $VAR that may expand to one) is not.
            if isinstance(vol, dict):
                src, is_bind = str(vol.get("source", "")), vol.get("type") == "bind"
            else:
                parts = str(vol).split(":")
                src, is_bind = (parts[0] if len(parts) > 1 else ""), False
            if is_bind or src.startswith(("/", ".", "~", "$")):
                problems.append(f"service `{name}` bind-mounts a host path")
        caps = {str(c).upper().removeprefix("CAP_") for c in svc.get("cap_add") or []}
        if caps - ALLOWED_CAPS:
            problems.append(f"service `{name}` adds capabilities {sorted(caps - ALLOWED_CAPS)}")
        for opt in svc.get("security_opt") or []:
            if not str(opt).startswith("no-new-privileges"):
                problems.append(f"service `{name}` sets security_opt `{opt}`")
        build = svc.get("build")
        ctx = build.get("context", ".") if isinstance(build, dict) else (build or ".")
        if ".." in pathlib.PurePosixPath(str(ctx)).parts or str(ctx).startswith("/"):
            problems.append(f"service `{name}` builds from outside the task")
    return problems


def main() -> None:
    tasks = json.load(sys.stdin)
    runnable, skipped = [], []
    for task in tasks:
        tdir = pathlib.Path(task)
        toml_text = (tdir / "task.toml").read_text() if (tdir / "task.toml").is_file() else ""
        # harbor resolves ${VAR} in task.toml env tables (verifier/solution/agent)
        # from its own environment -- the same leak as compose interpolation. No
        # task in the repo uses it, so /test refuses any reference outright.
        templated = sorted(set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", toml_text)))
        if templated:
            skipped.append({"task": task, "reason": f"task.toml templates host environment variables {templated}"})
            continue
        try:
            backend = tomllib.loads(toml_text).get("environment", {}).get("validate_env") or "docker"
        except Exception:
            backend = "docker"
        if backend != "docker":
            skipped.append({"task": task, "reason": f"declares the `{backend}` backend; /test only runs on the docker runner"})
            continue
        problems = []
        for compose in sorted((tdir / "environment").glob("docker-compose*.y*ml")):
            problems += compose_problems(compose)
        if problems:
            skipped.append({"task": task, "reason": "docker-compose " + "; ".join(problems)})
        else:
            runnable.append(task)
    print(json.dumps({"runnable": runnable, "skipped": skipped}))


if __name__ == "__main__":
    main()
