# Native Isaac dispatcher and Harbor adapter

This directory contains infrastructure, not ten completed Isaac benchmarks. `registry.json` pairs ten existing MuJoCo tasks with ten Isaac entries initially marked `planned`. Registering reviewed code changes one entry to `implemented`; only independent native replay evidence can justify `validated`.

The only supported execution route creates a fresh `roboindustrial-isaac` Modal sandbox from existing image `im-Nm8iLJCxhB14rzlvQjzhLD`, requests L40S, and mounts no business, asset, weight or history volumes. The configuration contains no tokens. Credentials remain in the trusted host environment / GitHub secrets. Production `anchor-robodojo` code is not modified.

The installed production Modal SDK was inspected read-only and is 1.5.4. Its `Sandbox.create`, `exec`, `Image.add_local_dir(copy=True)` and integer-returning `ContainerProcess.wait()` signatures were confirmed. A real server call subsequently rejected the legacy `Sandbox.open` API despite its presence in the SDK; the dispatcher now uses `sandbox.filesystem.write_bytes/read_bytes`, following the [official migration guide](https://modal.com/docs/guide/migrate-sandbox-filesystem). Native engine startup and shutdown are separate integration evidence; integration testing observed a real native shutdown abort, so an already-written successful metric never overrides a nonzero process exit.

## Standalone native replay

Use the confirmed host SDK Python `/root/anchor-trigger/.venv/bin/python`, or an isolated host environment with Modal 1.5.4. Keep credentials in the host environment. The example below assumes a separately reviewed native bundle at `../isaac-port`; it is not supplied by the infrastructure-only change. Run commands from `tools/isaac-modal`.

Register the current native dual port after its author freezes the files:

```sh
python register.py --registry registry.json --task dual-load-balance \
  --bundle ../isaac-port --entrypoint dual_load_balance.py:evaluate \
  --include dual_load_balance.py --include runtime.py \
  --case-id b0 --case-id b1 --case-id b2 --case-id b3 \
  --case-id b4 --case-id b5 --case-id b6 --case-id b7 \
  --cpu-physics-explicit
python dispatch.py --task dual-load-balance \
  --candidate ../isaac-port/authoring/dual-oracle.json \
  --output dual-native-result.json
```

The existing native port currently uses CPU PhysX on a Modal GPU host. `--cpu-physics-explicit` records that boundary; it does not label it GPU dynamics. Omit this flag only when the native implementation actually reports enabled GPU physics. A candidate named oracle is not presumed to pass. Edits after registration cause a hash mismatch and require explicit re-registration.

The dispatcher validates numeric JSON before allocating GPU, uploads only fixed source and candidate bytes, invokes native replay, binds the result to nonce/source/candidate hashes, checks every registered episode and aggregate, requires normal process exit, and terminates the sandbox in `finally`. Exit codes: 0 physical pass, 1 physical/format failure, 2 infrastructure error. The host's `dispatch_evidence` records the actual sandbox ID and requested image/GPU; the trusted native port records actual engine/version/physics device. No result supplied by the agent is accepted.

`evaluate(candidate, context)` is the native port contract. Context supports `begin_episode(id)`, `record_engine(version=..., physics_device=...)`, `record_step(sim_time)`. Every registered episode must advance finite monotonic simulation time. Native results require Boolean `passed`, ordered `episodes` with matching IDs, finite JSON metrics and matching aggregate. A schema rejection may return `passed=False, episodes=[], error="..."`. Native `SimulationApp` must explicitly set `fast_shutdown=True` when paired with `skip_cleanup=True`; real 6.0.1 tests with `fast_shutdown=False` still crashed. The worker atomically publishes its complete result, then calls the hash-pinned runtime’s official `close(skip_cleanup=True,exit_code=0 or 2)`, which exits immediately in Isaac 6.0.1. The host accepts the file only after a normal zero exit. Abort during/after shutdown is infrastructure failure; a saved file does not override it. This order follows a real native 3000-step run that exited normally; each full task still needs its own replay evidence.

## Harbor 0.21.0 integration

Use **host Python >=3.12**, `harbor[modal]==0.21.0` and `modal==1.5.4` in an isolated environment. The existing production trigger Python is 3.11 and must not be upgraded for this task. The adapter is `harbor_image_adapter:RoboIndustrialModalEnvironment`; it rejects any other Harbor version until its ABI is revalidated.

Released [Harbor v0.21.0 Modal source](https://github.com/harbor-framework/harbor/blob/v0.21.0/src/harbor/environments/modal.py) selects registry/Dockerfile images and has no Modal image-ID option. The adapter replaces only its direct image-start strategy: it derives an immutable task overlay from `Image.from_id`, then reuses Harbor's GPU/resource/network handling and independent environment lifecycle. Its [environment factory](https://github.com/harbor-framework/harbor/blob/v0.21.0/src/harbor/environments/factory.py) accepts an import-path class; the [separate-verifier path](https://github.com/harbor-framework/harbor/blob/v0.21.0/src/harbor/trial/trial.py) copies the runtime environment config, so the same adapter is used for a fresh verifier. The agent overlay goes to `/app`; the verifier overlay goes to `/tests`. `copy=True` bakes trusted files into the derived image, satisfying Harbor's `skip_tests_upload=True` behavior. The network policy is public for the agent and no-network for the verifier.

Build an **integration fixture**, then run it through actual Harbor:

```sh
python build_smoke_task.py --registry registry.json --task dual-load-balance \
  --candidate ../isaac-port/authoring/dual-oracle.json \
  --destination ../harbor-dual-smoke
PYTHONPATH="$PWD" harbor run -c ../harbor-dual-smoke-job.json
```

This fixture's oracle copies a fixed candidate to exercise transfer and replay; it is deliberately **not an algorithmic benchmark reference solution**. It must not be published as a calibrated task. `harbor_verify.py` launches a native subprocess and emits no reward on crash, timeout or infrastructure error. A genuine completed physical failure emits zero. Native JSON is written atomically before immediate Isaac shutdown; the separate verifier publishes final metrics/reward only after confirming normal native exit. Engine source and case identity are trusted image contents, not candidate choices.

The adapter's metadata file is `roboindustrial-image.json`, containing `/app` or `/tests` destination and every payload hash. It refuses unregistered/changed files, shared business volumes, secrets, compose, VM runtime and alternate sandbox modes. There is no fallback to `docker_image="im-..."`, which would be interpreted as a container registry reference by vanilla Harbor.

The custom image definition is checked by `check_native_task.py`. The workflow shim recognizes this manifest and selects the reviewed adapter for `/run env=modal`, `/validate`, `/oracle`, and `/cheat`. Host infrastructure must be present on the trusted base branch; task-only PR overlays cannot activate an unmerged infrastructure change. Do not load host adapter code from agent artifacts or PR task contents.

## Local tests and limits

```sh
python -m unittest discover -s tests -v
```

Twenty-one local tests cover duplicate/nonfinite/deep/oversized-schema input handling, symlinks, placeholder rejection, immutable source hashes, complete case identity, nonce/candidate binding, aggregate consistency, physics clock/device guards, atomic result publication, exit-134 rejection, immutable from-ID overlay selection, no business mounts/secrets, and cleanup after worker failure. SDK/engine objects in these tests are explicit synthetic doubles. Their success is **not** a GPU/Isaac/Harbor end-to-end result.

A real Harbor 0.21.0 agent→artifact→fresh verifier run has completed with reward 0 and zero exceptions for `{}` (format rejection, no physics). The concise metadata is in `evidence/harbor-empty-summary.json`; it is not an oracle or model-difficulty result.

A second real Harbor run replayed eight native PhysX no-op episodes (24,000 steps) in the no-network separate verifier. It completed in 175.41 seconds with reward 0, no exception, and documented physical constraint failures. See `evidence/harbor-physical-negative-summary.json`. This proves physical rejection, not task solvability.

Remaining per-task acceptance evidence: independently calibrated oracle/alternative/physical-counterexample replay and model trials. Register and calibrate ports independently; do not change all pending entries to ready after one smoke run.

## Repository integration

`check_native_task.py` validates the manifest, source hashes, fixed numerical artifact, registered case identity, GPU allocation, no-network separate verifier, and absence of private oracle/grader files in the public overlay. `ci_harbor.py` routes native tasks to the fixed reviewed adapter while preserving existing agent flags; ordinary task invocations pass through unchanged. Native infrastructure and unclassified API/agent errors exit 70 without being counted as reward zero. A documented agent-budget timeout with a complete binary verifier result retains that result. Mixed ordinary/native batches must be split into distinct jobs.

The workflow changes cover `/run`, `/validate`, `/oracle`, `/cheat`, and the separate-verifier check. Modal pinning applies only when selected tasks use native manifests. The workflows load host code from the trusted base checkout; until this infrastructure is merged, use the equivalent isolated-server harness for end-to-end validation.

## Optional fast planning model

An agent-only `planner-requirements.txt` may declare exactly `mujoco==3.3.7`, `numpy==2.2.6`, and `scipy==1.15.3`. The adapter builds `/app/planner-venv` in the derived agent image, before the solve budget starts. It leaves the pinned Isaac runtime intact and does not create this environment in the verifier. All dependencies are explicit and the requirements file is covered by the immutable overlay hash. Native PhysX remains authoritative; an approximate planning model cannot supply final metrics. The reused image already has other packages, including MuJoCo 3.8.0; the invariant is that the trusted native worker never imports MuJoCo, not that no MuJoCo files exist anywhere in the base image.
