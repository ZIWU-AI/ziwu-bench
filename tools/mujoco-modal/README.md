# GPU validation and official task submission

`GPU Task Validation` runs protected-service MuJoCo tasks on Modal, including
PR #3's bimanual pen transfer. A task path, immutable PR revision, GPU, mode and
1–3 repeats are selectable. `Export Official Task PR` packages any conventional
new task against official `main`, without the fork's infrastructure or history.

## Run from GitHub or the CLI

Open **Actions → GPU Task Validation → Run workflow**, select `main`, enter PR
`3`, and choose `L40S`, `all`, and `1`. The task path is prefilled. For another
compatible task, enter its PR and task path. PR `0` reads the selected workflow
revision, so the task must already exist there.

```bash
gh workflow run gpu-task-validation.yml --repo ZIWU-AI/ziwu-bench --ref main \
  -f pr_number=3 \
  -f task_path=tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control \
  -f gpu=L40S -f mode=all -f trials=1
gh run list --repo ZIWU-AI/ziwu-bench --workflow gpu-task-validation.yml
gh run watch RUN_ID --repo ZIWU-AI/ziwu-bench --exit-status
gh run download RUN_ID --repo ZIWU-AI/ziwu-bench --dir validation-evidence
```

Modes are `all`, `oracle`, and `nop`. GPUs are `L40S` and `A10`; L40S is the
default because a later A10 allocation queued during initial validation.
Repeats run sequentially, with a maximum of three. Each phase has a bounded
command timeout and each sandbox expires after 30 minutes. Normal and failed
runs terminate their sandboxes; an always-run cleanup step handles interrupted
phases where Actions can still execute cleanup. Hard job termination relies on
the sandbox lifetime. Image builds and the whole job are bounded by 90 minutes.

The workflow is also reusable through `workflow_call` with the same inputs and
the explicit `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` secrets. Configure those
encrypted Actions secrets in the destination repository's own Modal workspace.
No Modal image ID, private asset archive, model API key or NVIDIA Isaac runtime
is required. `GPU Tools Tests` runs offline on relevant PR/push changes with no
Modal credentials and no paid work.

## What the runner supports and verifies

This adapter supports the protected pen-service contract: `/opt/pen-control`
launcher and collection hook, `/app` public SDK, `agent` user, root-private
recording at `/var/lib/pen-control/export`, `solution/solve.sh`, separate
`tests/test.sh`, and `authoring/test_runtime.py`. Other runtimes must use their
own adapter or the existing Harbor validation workflow; selecting an arbitrary
task directory does not make it compatible. The exporter is not limited to
MuJoCo tasks.

Physics uses MuJoCo on CPU. NVIDIA EGL renders the three camera views on GPU.
The runner builds the task's pinned Dockerfiles, selects EGL in an image-owned
file and starts the service as root before running the oracle as `agent`.
This accommodates Modal's `no_new_privs` while preserving the protected
recording. Its SDK reuses a healthy service instead of unnecessarily invoking
sudo. Default task execution remains compatible with standard Docker/OSMesa.

The A10/L40S hardware checks, bounded lifecycle and fresh data-only verifier
follow [upstream #2195](https://github.com/harbor-framework/terminal-bench-science/pull/2195)
at `da218ea01206441256e7e9da6e76ef41e12cef65`. Isaac's driver pin is not applied
to MuJoCo. The observed GPU/driver and NVIDIA renderer identity are recorded.

Oracle must score exactly **1**, Nop exactly **0**. Each recording goes to a new
network-blocked CPU verifier, with no solution code. The Actions summary and
30-day artifact contain source hashes, runtime identity, native tests, binary
rewards, CTRF, replay errors and lifecycle receipts. Numeric oracle recordings,
policy output and camera bundles are excluded from public artifacts. They are
available when running the CLI locally. This is reference validation via the
Modal SDK, not a Harbor CLI job or a frontier-model solve. A green Nop-only job
is a successful negative-control check, not evidence of task completion.

PR task Python is never imported on the Actions host. The workflow revision
supplies trusted tooling; only the selected PR's files are checked out under
`candidate/`. Only explicitly invoked workflows receive Modal secrets, and the
secrets are not passed into task images or sandboxes. Fork PR events run only
the offline tool tests. Use a reviewed workflow revision when dispatching.

## Prepare an official PR

```bash
gh workflow run upstream-task-bundle.yml --repo ZIWU-AI/ziwu-bench --ref main \
  -f pr_number=3 \
  -f task_path=tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control
```

Download `official-task-pr-RUN_ID`. It contains `task.patch`, `task.tar`,
`submission.json`, `apply.sh`, a PR-body template and submission commands.
The exporter fetches official main, stages only the selected new task in a
temporary worktree, creates the patch and removes that worktree. Existing
upstream task paths are rejected so updates get their own review.

`ZIWU-AI/ziwu-bench` is not a GitHub fork. The included commands therefore apply
the patch to a clean official base and push a new branch to the existing
`RoboIndustrial-Benchmark/terminal-bench-science` fork, from which your own
GitHub account can open a draft PR in the official repository. The exporter
itself creates no commit, push, PR or comment. Official `main` is never pushed.
Review proposal approval, author declarations, provenance and model-trial
requirements before submitting; a green reference run does not replace them.

## Local reproduction

```bash
python -m pip install -r tools/mujoco-modal/requirements-host.txt
python tools/mujoco-modal/run.py --task-root /path/to/pr-checkout \
  --task-path tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control \
  --source-sha EXACT_TASK_COMMIT --gpu L40S --mode all --output runs/new-run
python -m unittest discover -s tools/mujoco-modal/tests -v
```

Use a fresh output directory. The selected source SHA is recorded along with
every task file's hash; the source checkout must match the SHA you supply.

For the original Isaac Sim 5.1 example, select `backend=isaac` and follow the
[Isaac runbook](../isaac-reference-modal/README.md). The default remains MuJoCo.
