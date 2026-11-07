# Isaac shuttle validation

`tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac` is a full-contract port of RoboIndustrial PR #34 at `6a5f992804f0f9b63da5eb57aeacdc7371a2e385`. It retains 20 public and 48 hidden cases and the original 47/48 threshold. It uses native Isaac 6.0.1 CPU PhysX TGS, with an A10 host, hard 4 CPU / 16 GiB allocation, and no MuJoCo simulation path.

Use host Python 3.12 and `requirements-host.txt`. Credentials stay on the host. The task Dockerfiles support NGC provisioning; `image.py` uses the already tested immutable Isaac 6 engine image `im-VbjOSj3gdypwNyoZQA58DH`, removes inherited task content, then applies the same task provisioning steps. Task Python is never imported on the host. Never use an oracle-derived image for a model run.

Explicit, bounded author runs (no automatic paid PR/push trigger):

```sh
python tools/shuttle-isaac-modal/smoke_host.py
python tools/shuttle-isaac-modal/validate.py --mode oracle --output runs/shuttle-isaac/oracle
python tools/shuttle-isaac-modal/validate.py --mode nop --output runs/shuttle-isaac/nop
```

The oracle runs as `agent`, fits the public bench data, spends two metered native probes, and produces `/app/controller.py`. Its sandbox is destroyed before a fresh no-network verifier is created. The negative control is a valid controller commanding zero braking, so its failure exercises physics instead of merely rejecting a missing file. Every phase is recorded by sandbox/image ID and source/candidate hashes and terminated in `finally`. The 48 hidden episodes are serial in one native engine; each submitted controller has a fresh, resource-limited, unprivileged child process. Engine startup/shutdown errors are distinct from candidate failures. There is no model trial implied by these author checks.

`--reuse-controller <local-file>` is an explicit author replay option, useful for engine or verifier debugging; it does not regenerate calibration and is labeled by the candidate hash. Do not claim a fresh end-to-end oracle from that mode. Local `controller.py`, probe traces and raw logs remain private; only metrics, source/candidate hashes and resource/lifecycle receipts should be published.

For a standard Harbor reference trial (the Harbor `nop` agent submits no file, unlike the physical zero-braking control above):

```sh
python tools/shuttle-isaac-modal/build_job.py --agent oracle --output runs/shuttle-isaac/job.json
PYTHONPATH=tools/shuttle-isaac-modal harbor run -c runs/shuttle-isaac/job.json
```

For model runs with Harbor 0.23.0, set `PYTHONPATH=tools/shuttle-isaac-modal` and use `environment.import_path="harbor_environment:ShuttleIsaacEnvironment"` in JobConfig. The task's standard environment healthcheck starts the root-owned simulator before the agent budget. The agent is uid `agent`; the verifier is fresh and network isolated. Standard Docker/Modal NGC builds use the task Dockerfiles and the same healthcheck. The image-ID adapter is required when using the cached Modal engine. Keep this host adapter trusted separately from task PR content.

Check core identity with:

```sh
python tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac/authoring/provenance/sync_core.py --check
```

The runtime helper was adapted from RoboIndustrial PR #47; it records actual engine/device/driver configuration and checks every simulation clock increment. Pose/velocity resets occur only before integration. The brake uses a zero-target-velocity, zero-stiffness, force-limited PhysX joint drive; thermal work is measured from momentum change. Native contact is independently bounded by the original acceptance conditions. Source MuJoCo evidence is archived under `authoring/source-mujoco-evidence` and is not native acceptance evidence.
