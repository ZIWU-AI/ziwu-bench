# Active cohort: Isaac 6.0.1 / Modal A10

On 2026-11-07 the user requested Isaac 6.0.1 after the actual Isaac 5.1 / A10
attempt failed during native startup. The 5.1 attempt and its result comment
remain historical; they are not counted as a model task failure.

The current task uses PR #2195's pinned Isaac 6 base image
`im-VbjOSj3gdypwNyoZQA58DH`, cleaned of inherited task code and solutions.
GPU placement remains A10 / OCI eu-west. Hard limits are 4 CPU / 16 GiB,
as explicitly requested by the user; no automatic resource increase is enabled. The observed 610.57.04
driver is retained; changing the Isaac engine does not change NVIDIA's driver.
The original task scoring and independent sealed-data replay are preserved.
Earlier L40S / Isaac 6 diagnostics do not establish acceptance on A10.

The selected model attempt is Kimi k3.1-pro / Codex 0.155.1, high reasoning,
one 5400-second agent budget. The current native runner emits `ISAAC_PROGRESS`
every 30 seconds using only phase and lifecycle fields, never model transcripts
or credentials. Final sanitized results update the per-run PR comment.

```sh
gh workflow run gpu-task-validation.yml -R ZIWU-AI/ziwu-bench \
  --ref codex/isaac-modal-gpu-example -f backend=isaac-model \
  -f model_profile=kimi -f harness=codex -f model_stage=all-current-driver \
  -f gpu=A10 -f pr_number=0
```

Native image build, startup, model execution, collection and independent
verification are distinct phases. Startup errors have no task score. Raw
histories and recordings remain private. No model/harness substitution or
automatic paid trial retry is enabled.

## Historical Isaac 5.1 configuration (superseded)

# Isaac 5.1 / Modal A10 reference validation

The active configuration follows [PR #2195](https://github.com/harbor-framework/terminal-bench-science/pull/2195)
at `da218ea01206441256e7e9da6e76ef41e12cef65`: **Isaac Sim 5.1.0.0,
NVIDIA A10, driver 580.95.05, OCI eu-west, hard 4 CPU / 16 GiB limits**.
The Isaac 6 migration is withdrawn at the user's request. No current result
inherits acceptance from the historical controls.

The simulation, verifier, instruction and references are restored byte-for-byte
from the infra's accepted task commit `fed3c441ab5c112e998b27e26eb17f2693d96f99`.
PR #3's submitting-author metadata is retained. `a10_runtime.py` vendors the
original host provisioning and hardware inspection helpers; `image.py` applies
its RTX packages, pinned Python dependencies and verified public NVIDIA cache
to the original task Dockerfiles. No private Isaac 6 image is used. The Harbor
integration is adapted to pinned Harbor 0.23.0 / Modal 1.5.5.

## Current execution status

A fresh operator-host A10 allocation on 2026-11-07 returned **610.57.04**.
It was terminated and cleanup confirmed. This differs from the reviewed
580.95.05 hardware contract: native model trials are blocked, not scored zero.
See `../isaac-model-comparison/evidence/a10-placement-2026-11-07.json`.
Previous Isaac 6 diagnostics are historical and excluded from this cohort.

## Run

```sh
gh workflow run gpu-task-validation.yml --repo ZIWU-AI/ziwu-bench \
  --ref codex/isaac-modal-gpu-example \
  -f backend=isaac -f pr_number=0 -f gpu=A10 -f mode=all -f trials=1
```

The manual workflow prepares the hash-pinned public extension cache. Local runs:

```sh
python tools/isaac-reference-modal/prepare_extensions.py \
  --output work/extensions --accept-nvidia-license
python tools/isaac-reference-modal/run.py --task-root . \
  --task-path tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control \
  --source-sha HEAD --gpu A10 --mode all --extensions work/extensions --output work/run
```

Use your own authenticated Modal profile or the repository's `MODAL_TOKEN_ID`
and `MODAL_TOKEN_SECRET`. Task code is data on the host and runs only in Modal.
One reference sends recorded joint targets through the public service; root
collects sealed evidence; a fresh no-network GPU verifier assigns reward.
Nop has no policy actions and expects reward zero. Neither uses a model key.
The GPU renders; frozen PhysX dynamics use CPU. Hardware/placement/resource
checks run before task commands. Mismatches fail without paid replacement loops.
Each container has a three-hour lifetime; collection and verification have
separate approximately two-hour budgets. Cleanup runs on failure as well.

Other references are explicit `--reference v13-round01-layout0` or
`v13-smoke-layout0` variants. All selected control outcomes are retained; an
unexpected Oracle reward does not prevent Nop, and fails the overall check.
Only sanitized receipts and metrics are published, never trajectories or keys.
Official task proposal/hosting/authorship requirements remain separate gates.
