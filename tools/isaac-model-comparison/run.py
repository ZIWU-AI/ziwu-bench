"""One model/harness trial on a frozen Isaac task, gated by real tool use."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from harness_common import now, write_json, make_preflight, job_config, execute, collect, scrub_tree
from profiles import PROFILES, route_for
from calibration import calibration, runtime_spec

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASK = "tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, default=ROOT)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--extensions", type=Path)
    parser.add_argument("--stage", choices=["preflight", "all"], default="all")
    parser.add_argument("--driver-policy", choices=["strict", "observed"], default="strict")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    spec = PROFILES[args.profile]
    secret = os.environ.get(spec["secret"], "")
    sha = subprocess.check_output(["git", "rev-parse", args.source_sha + "^{commit}"], cwd=args.task_root, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", sha + ":" + TASK], cwd=args.task_root, text=True).strip()
    summary = {"profile": args.profile, "model": spec["model"], "harness": args.harness,
               "source_sha": sha, "task_tree": tree, "task_path": TASK,
               "host_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "requested_trials": 1, "trial_count": 0, "reward": None, "status": "preparing",
               "agent_timeout_sec": 5400, "started_at": now(), "run_url": os.environ.get("COMPARISON_RUN_URL"),
               "harbor_version": version("harbor"), "gpu": "A10", "cpus": 4, "memory_mib": 16384, "isaac_version": "6.0.1.0"}
    summary["calibration"] = calibration(args.task_root, sha, TASK, HERE / "evidence/calibration.json", runtime_spec(ROOT))
    summary["driver_policy"] = args.driver_policy
    if args.driver_policy == "observed":
        summary["calibration"] = {"status": "exploratory_current_driver", "reference_driver": "610.57.04",
                                  "historical_acceptance_transferred": False}
    code = 1
    try:
        if version("harbor") != "0.23.0":
            raise ValueError("Requires pinned Harbor 0.23.0")
        if not secret:
            summary["status"] = "credential_missing"
            raise ValueError(spec["secret"] + " is not configured")
        with tempfile.TemporaryDirectory(prefix="ziwu-isaac-model-private-") as temp:
            private = Path(temp)
            route = route_for(args.profile, args.harness, private)
            summary["route"] = route["provenance"]
            env = os.environ.copy()
            # Keep host provider keys out of unrelated agent discovery. The
            # selected key enters only the agent config, never verifier env.
            for value in PROFILES.values():
                env.pop(value["secret"], None)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            env["PYTHONPATH"] = str(HERE)
            env.update(route["env"])
            env.update({name: secret for name in route["credential_env_names"]})
            preflight = private / "preflight"; make_preflight(preflight)
            cfg = job_config(route, preflight, output / "preflight", "check", secret, 300)
            cfg["environment"] = {"type": "modal", "delete": True,
                                  "kwargs": {"app_name": "ziwu-isaac-models", "sandbox_timeout_secs": 1800}}
            summary["status"] = "preflight_running"; write_json(output / "summary.json", summary)
            status = execute(cfg, private, output, "preflight", env)
            summary["preflight"] = collect(output / "preflight/check")
            if status or summary["preflight"]["status"] != "passed":
                summary["status"] = "preflight_failed"
                return 1
            if args.stage == "preflight":
                summary["status"] = "preflight_passed"
                code = 0
                return code
            # Materialize committed bytes only; no mutable working-tree overlay,
            # solution or authoring files are uploaded to the model environment.
            import tarfile, io
            task = private / "task"; task.mkdir()
            archive = subprocess.check_output(["git", "archive", sha + ":" + TASK], cwd=args.task_root)
            with tarfile.open(fileobj=io.BytesIO(archive)) as source:
                source.extractall(task, filter="data")
            cfg = job_config(route, task, output / "trial", "comparison", secret, 5400)
            cfg["environment"] = {"import_path": "isaac_environment:IsaacEnvironment", "delete": True,
                "kwargs": {"app_name": "ziwu-isaac-models", "sandbox_timeout_secs": 18000, "driver_policy": args.driver_policy}}
            summary.update(status="trial_running", trial_count=1); write_json(output / "summary.json", summary)
            status = execute(cfg, private, output, "trial", env)
            summary.update(collect(output / "trial/comparison"))
            summary["harbor_exit_code"] = status
            if status and summary["status"] in ("passed", "not_passed"):
                summary.update(status="execution_error", reward=None)
            code = 0 if summary["status"] in ("passed", "not_passed") else 1
    except Exception as exc:
        if summary["status"] != "credential_missing": summary["status"] = "execution_error"
        summary["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        summary["finished_at"] = now()
        write_json(output / "summary.json", summary)
        scrub_tree(output, secret)
        print(json.dumps({"profile": args.profile, "harness": args.harness,
                          "status": summary["status"], "reward": summary.get("reward")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
