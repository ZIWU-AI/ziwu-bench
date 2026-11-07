# Driver selection and archived inputs (2026-11-07)

The active engine is Isaac 5.1.0.0. No Isaac 6 fallback is enabled.

## What the original infra did

PR #2195 at `da218ea01206441256e7e9da6e76ef41e12cef65` requests A10,
OCI eu-west and 4 CPU / 16 GiB, then checks the actual driver against 580.95.05.
Its `a10_environment.py` passes no driver selector to Modal. The earlier
`isaac51-a10-acceptance.json` records a rejected A10G/610 allocation followed
by an accepted A10/580 allocation; that is post-allocation checking, not a
scheduler guarantee. Current reviewed infra allows one allocation per role.

[Modal's CUDA guide](https://modal.com/docs/guide/cuda) states kernel-mode
components belong to the host and cannot be changed by the container user.
The documented [Sandbox API](https://modal.com/docs/sdk/py/latest/Sandbox)
and installed Modal 1.5.5 SDK expose GPU, cloud and region selection, but no
public NVIDIA driver-version selector. `experimental_options` is not evidence
that an invented driver option is supported. An undocumented workspace-specific
route would need confirmation from Modal or an existing working configuration.
We have not contacted Modal or changed the account.

Two successful operator-host inventory probes of A10 / OCI eu-west returned
610.57.04. Two compound probes produced no JSON and establish no driver fact.
All four containers were terminated. This does not establish that every Modal
node has 610; it does establish that the requested placement alone does not
ensure the historical 580 contract. See the model comparison's placement receipt.

## Hugging Face assets that can be reused

- [Runtime](https://huggingface.co/datasets/HugoLiuDev/physicalrsi-bimanual-control-runtime):
  `physicalrsi-bimanual-control/runtime/runtime.tar.gz`, 476198876 bytes,
  SHA-256 `92d6863fbf03b95eea01dc1f3c6b6f186d2ac3077f454f408f201face669866b`.
  The local archive matches this digest. Its 3330 entries contain task sources,
  assets, RoboDojo, XPolicyLab, IsaacLab and cuRobo; inspection found no kernel
  modules, NVIDIA driver installers, libcuda or libnvidia driver binaries.
  The task already fetches its pinned review copy.
- [Trial evidence](https://huggingface.co/datasets/HugoLiuDev/physicalrsi-bimanual-control-trial-evidence):
  historical Astra, Opus and Fable recordings, logs and verifier receipts.
  Its README explicitly excludes Isaac/Kit binaries and the extension cache.
  These archives stay outside the evaluated agent's environment and cannot
  substitute for fresh model trials or change the allocated host's driver.
- The public 3344-file extension cache remains reproducible from the two
  hash-pinned NVIDIA ZIPs in `prepare_extensions.py`, as in PR #2195.

A compatible 580 allocation or a Modal-supported driver-pinned pool is needed
to reproduce this exact hardware contract. No reward is assigned while blocked.
