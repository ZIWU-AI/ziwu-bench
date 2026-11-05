# Same-model harness comparison

Run `friction-pinch-lift` once with each of four coding harnesses, all configured
for Kimi Code's official `k3.1-pro` route. Each harness first completes a fresh,
five-minute tool-use preflight. Only a successful preflight starts its benchmark
trial, which has a 90-minute agent limit. This is an exploratory comparison of
the configured harnesses and adapters, not an established ranking.

The runner accepts only the reviewed task at
`tasks/engineering-sciences/mechanical-engineering/friction-pinch-lift`, with Git
tree `98401f4e698ef0b84e92baab287c10bc257d1e97`. It rejects tracked or untracked
task changes. The budget is a Harbor runtime override; task files, hidden
verifier, six-probe limit, and scoring thresholds remain the original task's.
No hints or oracle solution are supplied to the agents.

## Versions and routes

Harbor is pinned to **0.23.0**. `routes.py` owns the client versions and provider
configuration; `dsh_agent.py` implements the additional dsh adapter.

| Harness | Client version | Wire protocol | API base |
|---|---|---|---|
| Claude Code | 2.1.318 | Anthropic Messages | `https://api.kimi.com/coding` |
| Codex | 0.155.1 | Responses | `https://api.kimi.com/coding/v1` |
| Kimi Code | 2.5.1 | Chat Completions | `https://api.kimi.com/coding/v1` |
| DeepSeek Harness | 0.2.2-rc.1 | Anthropic Messages through `llm-pi-ai` | `https://api.kimi.com/coding` |

The model name sent by each route is the bare `k3.1-pro`. The clients retain
their own identities; no User-Agent impersonation or protocol translation proxy
is used. Protocol support alone does not establish that a provider will admit
every client. A rejected dsh client is reported as a failed integration, and
does not trigger a change of identity, endpoint, or model.

All routes request a 262,144-token context and `high` reasoning. These are
configuration values, not measured equal reasoning budgets. Each native client
and protocol controls how those settings are sent, how history is compacted,
and how tools and prompts are represented. Codex explicitly compacts at 220,000
tokens. dsh sets a 32,768-token request output cap; that is a configured cap,
not a claim about the provider's maximum output capacity. The comparison does
not establish equal inference compute or inspect the provider's underlying
weights. Each result retains its route provenance and configuration differences.

## Run and inspect

### Separate DeepSeek official API trial

The optional `deepseek` profile runs **Codex 0.155.1 + deepseek-flash** through
DeepSeek's native Responses API at `https://api.deepseek.com/`. This is a
separate provider/model experiment, not a fifth row in the fixed-Kimi harness
comparison. It uses the same task, fresh preflight, one attempt, and 90-minute
agent budget. The official model catalog supplies DeepSeek-specific tool and
reasoning metadata inside each isolated container.

On 2026-11-05, an authenticated request to the official `/models` endpoint
returned HTTP 200 and listed `deepseek-flash` as DeepSeek-V4.1-Flash, with
1,048,576 context tokens and `low`, `high`, `max` effort levels. This profile
requests `high`, keeps the official 1M context configuration, and disables
Codex web search. The context differs from the Kimi profile's 262,144 tokens;
these trials should not be presented as differing only in their model weights.
The provider's unversioned model alias may resolve differently in future runs.

The user-supplied credential is kept in the repository Actions Secret
`DEEPSEEK_API_KEY`, injected into Codex only at runtime. No local Codex/desktop
configuration is changed. Dispatch this profile with:

```sh
gh workflow run run-trials.yml --repo ZIWU-AI/ziwu-bench \
  --ref codex/friction-pinch-lift-20261105 \
  -f pr_number=4 -f harness_comparison=true -f harness_provider=deepseek
```

Local invocation adds `--provider deepseek --harness codex`; aggregation also
requires `--provider deepseek`. The report rejects mixed-provider input.
Artifacts include the provider in their names, and the existing Kimi run keeps
its original commit and settings.

See [DeepSeek's Codex integration](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/codex/)
and [native Responses API](https://api-docs.deepseek.com/zh-cn/guides/responses_api/).

### Fixed-Kimi comparison

The reusable Actions implementation is
[harness-comparison.yml](../../.github/workflows/harness-comparison.yml). It uses
`workflow_call`; invoke it through the repository's dispatch workflow rather
than trying to dispatch this reusable workflow directly. It runs at most two
harness jobs concurrently, keeps other jobs running when one fails, and creates
an aggregate report even when a harness fails or produces no artifact.

Dispatch the existing [Run Agent Trials](../../.github/workflows/run-trials.yml)
entry point at the reviewed comparison branch:

```sh
gh workflow run run-trials.yml --repo ZIWU-AI/ziwu-bench \
  --ref codex/friction-pinch-lift-20261105 \
  -f pr_number=4 -f harness_comparison=true
```

Comparison mode uses the selected workflow commit and the fixed task tree above;
`pr_number` is retained for the shared entry point, not used to select a different
task. The reusable workflow does not run normal `/run` jobs, post review comments,
or upload to Harbor Hub. Only dispatch a branch whose workflow changes have been
reviewed, because it receives the repository's Kimi credential.

For a local run, use a disposable Docker-capable environment with Harbor 0.23.0
on `PATH`. Set the existing `KIMI_CODE_API_KEY` in the launch environment, then
run from the repository root:

```sh
python tools/harness-comparison/run.py run \
  --harness deepseek-harness \
  --output comparison-output/deepseek-harness

python tools/harness-comparison/run.py report \
  --input comparison-output \
  --output comparison-report
```

Valid harness names are `claude-code`, `codex`, `kimi-code`, and
`deepseek-harness`. The runner injects the existing key into each client's
required environment variable. It keeps private Harbor job configuration in a
temporary directory and scrubs the literal credential from collected output
before artifact upload. Do not put a key in CLI arguments or route files.

Artifacts include each harness's `summary.json`, the preflight and trial Harbor
results, execution logs, and verifier evidence. The report emits
`comparison.json` and `comparison.md`, including a row for every requested
harness. A `not_passed` result is a completed, scored attempt, so its comparison
job can succeed even when its reward is zero.

## Reading results

| Status | Meaning | Benchmark reward |
|---|---|---|
| `passed` | Completed trial and verifier passed | 1 |
| `not_passed` | Completed trial and verifier rejected the submitted controller | 0 |
| `preflight_failed` | Connectivity/tool-use check did not pass; benchmark was not started | Unknown |
| `execution_error` | Agent, provider, container, or verifier execution raised an error | Unknown |
| `budget_exhausted` | Agent reached the 90-minute runtime limit | Unknown |
| `invalid_result` | No valid binary reward was produced | Unknown |
| `credential_missing` / `job_missing` | No authorized credential or no collected job result | Unknown |

Consult `exception_info` and the corresponding logs to distinguish provider
refusal, setup failure, and other execution errors. A successful CI job is not
the same as passing the scientific task. The physical episode count is useful
diagnostic evidence, but it is not the binary reward: the original verifier
also enforces per-group thresholds.

Missing usage and cost remain `null`, not zero. Harbor 0.23.0 does not convert
the selected Kimi Code client's output into complete usage/ATIF records. This
initial dsh adapter also leaves token usage, cache usage, and cost unknown; it
does not infer them from text length or use another model's prices. Do not rank
the clients by cost or tokens when that evidence is missing.
CLI cost estimates are retained separately as `cli_reported_cost_usd`; the
comparison's `cost_usd` remains unknown without verified Kimi billing.

## dsh adapter boundary

The Harbor import path is `dsh_agent:DeepSeekHarness`, with
`tools/harness-comparison` on `PYTHONPATH`. It implements Harbor's
`BaseInstalledAgent` interface, installs dsh 0.2.2-rc.1 and Node 24.9.0, and accepts
the following kwargs:

```json
{
  "version": "0.2.2-rc.1",
  "model_api": "anthropic-messages",
  "base_url": "https://api.kimi.com/coding",
  "max_tokens": 32768
}
```

The required model is `k3.1-pro`, and the required credential environment name
is `KIMI_API_KEY`. The runner maps the existing `KIMI_CODE_API_KEY` to it.
No official DeepSeek credential is required.

Each trial has a fresh `DSH_HOME` at `/logs/agent/dsh-home`. Its `headless` profile
uses only a credential reference (`apiKeyEnv`), disables both session-log upload
and OpenTelemetry, disables DeepSeek account/model routes, and disables
title-only model calls. dsh keeps its native attribution:
`deepseek-harness/0.2.2-rc.1 (+https://github.com/deepseek-ai/deepseek-harness)`.
Full tool permissions apply inside the Harbor task container; the adapter does
not mount host paths or the separate verifier's solution/test files.

The adapter passes the instruction through a file on stdin, captures the real
process exit code, and requires exactly one final event with
`reason.kind == "completed"`, matching the opening session ID, before treating
the agent run as complete. API errors, nonzero exits, malformed event streams,
or missing terminal receipts raise `DshIntegrationError`. The verifier then
decides the scientific reward for a completed run.

Evidence under the trial's agent logs includes:

- `dsh-events.jsonl`: headless NDJSON, including truncation flags.
- `dsh-sessions/`: full native durable session logs, with compression disabled.
- `dsh-stderr.log` and `dsh-exit-code.txt`: process diagnostics and exit status.
- `dsh-status.json`: validated settlement, configured model route, and explicit
  unknown usage status.

Headless progress fields can be truncated; retain the durable native sessions
when inspecting complete tool I/O. This adapter does not claim ATIF conversion,
session resume, or cross-trial history reuse.

## Offline tests

With Harbor 0.23.0 installed:

```sh
python -m unittest discover -s tools/harness-comparison -p 'test_*.py' -v
```

The tests do not use model APIs. They check route/configuration contracts,
result classification, task boundaries, dsh terminal receipts, missing
credentials, native attribution, and preservation of unknown usage.

Implementation references: [Harbor 0.23 custom-agent factory](https://github.com/harbor-framework/harbor/blob/1e5c5c6db929a10a140d05e606882c671ae20729/src/harbor/agents/factory.py),
[dsh headless contract](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/bundle/headless/README.md),
[dsh custom provider adapter](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/llm/llm-pi-ai/README.md).
