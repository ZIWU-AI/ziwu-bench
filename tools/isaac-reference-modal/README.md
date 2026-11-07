# Isaac reference validation on Modal

Run the restored Isaac Sim 5.1 bimanual pen-holder example through the manual
`GPU Task Validation` workflow. The reference controller sends 713 recorded
joint targets through the public service. A protected root recorder collects
fresh states and camera video, then a separate, no-network Isaac GPU container
replays those controls and assigns the reward. `nop` starts the service without
policy controls and expects reward zero. Neither mode calls a language model.

```sh
gh workflow run gpu-task-validation.yml --repo ZIWU-AI/ziwu-bench \
  --ref codex/isaac-modal-gpu-example \
  -f backend=isaac -f pr_number=0 -f gpu=L40S -f mode=all -f trials=1
```

Use the reviewed workflow branch until this PR is merged, then use `--ref main`.
`pr_number=0` pins the selected workflow commit; an explicit PR number pins that
PR's current head before allocation. The candidate task is data on the host;
its Python is never imported alongside Modal credentials. A different task
must implement the same protected-service/collection paths and Isaac 5.1
bundle contract. MuJoCo remains the default backend.

Required repository secrets: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`. Execution
is explicitly requested, never triggered by PR/push events. NVIDIA runtime and
extension installation accepts the component terms, as does the task Dockerfile.
Every container receives one selected GPU, 4 CPU cores and 16 GiB with a
three-hour lifetime; the reference phase is capped at one hour, collection and
verification at about two hours each. The workflow ceiling is 350 minutes.
Only one repeat runs at a time; there are no automatic paid retries.

Isaac uses GPU RTX rendering and the frozen task's **CPU PhysX** dynamics. This
is native Isaac execution, not a GPU-accelerated PhysX claim. The actual GPU and
driver are recorded per allocation. This L40S run does not inherit the older
A10/driver 580.95.05 success claim.

## Provenance and reproducibility

The task is restored from ziwu-bench PR #3's original Isaac commit
`4020e331bb35a4d42527ef7cc4be96ebbca8cabc`; the later MuJoCo PR remains separate.
Runtime dependencies, RTX system libraries, disabled online extension registry,
600-second startup allowance, and hash-verified public NVIDIA extensions come
from [upstream infrastructure PR #2195](https://github.com/harbor-framework/terminal-bench-science/pull/2195)
at `da218ea01206441256e7e9da6e76ef41e12cef65`. The task Dockerfiles explicitly
include the missing dependencies. Source scene, actions and scoring rules are
preserved. The two engine archives and all 3344 extracted files are hash checked;
the runtime archive is fetched and verified by each task Dockerfile.

For local execution, install `modal==1.5.5` using Python 3.12 and authenticate
the intended Modal profile. No model key is needed.

```sh
python tools/isaac-reference-modal/prepare_extensions.py \
  --output work/extensions --accept-nvidia-license
python tools/isaac-reference-modal/run.py --task-root . \
  --task-path tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control \
  --source-sha HEAD --extensions work/extensions --gpu L40S --mode all --output work/run
BACKEND=isaac python tools/mujoco-modal/report.py --run work/run --output work/report
```

Inspect `summary.json`, per-mode `result.json`, `input-receipt.json` and
`lifecycle.json`. A missing summary is incomplete, not a pass. Reports include
rewards and native replay metrics; recorded action plans, raw logs and camera
bundles remain outside published artifacts. The cleanup step also runs on
failure; hard container lifetimes bound a disconnected host.

The existing `upstream-task-bundle.yml` can export this task against official
main without remote writes. Official proposal, authorship and model evaluation
requirements remain independent of this zero-model reference validation.
