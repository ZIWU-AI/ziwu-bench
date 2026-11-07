# Isaac / Modal model and harness trials

This extends the manual GPU workflow with `backend=isaac-model`. It ports the
pinned adapters from ziwu-bench PR #4 at
`95febe6264a860bc69ee0364ff479788a536526b`, whose task/evidence format follows
[upstream PR #2224](https://github.com/harbor-framework/terminal-bench-science/pull/2224).
The Isaac task, states, scoring and independent verifier are shared across rows;
none of the friction-pinch-lift results are transferred to Isaac.

| Profile | Model | Harnesses |
|---|---|---|
| kimi | k3.1-pro | Codex, Claude Code, Kimi Code, DeepSeek Harness |
| deepseek | deepseek-flash | Codex, Claude Code, Kimi Code, DeepSeek Harness |
| astra | gpt-6-astra | Codex |
| sol | gpt-6-sol | Codex |
| opus | claude-opus-5-5 | Claude Code |

Each combination gets one exploratory trial, high reasoning, and a 5400-second
agent budget. Native clients/prompts, protocol, context windows and compaction
policies differ; this does not equalize inference compute or establish a model
ranking. Native versions: Harbor 0.23.0, Codex 0.155.1, Claude Code 2.1.318,
Node Kimi Code 2.5.1, DeepSeek Harness 0.2.2-rc.1.

Start with CPU-only tool-use preflights using the real clients and credentials:

```sh
gh workflow run gpu-task-validation.yml --repo ZIWU-AI/ziwu-bench \
  --ref codex/isaac-modal-gpu-example -f backend=isaac-model \
  -f model_profile=kimi -f harness=all -f model_stage=preflight
```

After Oracle/Nop pass on the same native configuration, select `model_stage=all`
for preflight plus a real Isaac task. `model_profile=all` selects all 11 pairs;
at most two run concurrently, with no trial retry. The model agent runs as the
unprivileged `agent` user; the host starts the root-owned protected simulator,
collects sealed execution, and runs a fresh no-network GPU verifier. No Oracle
solution is included in a model image. Network access is allowed for the model
agent, as declared in the task. Native containers have explicit lifetimes and
an always-run cleanup step.

The repository uses `KIMI_CODE_API_KEY` and `DEEPSEEK_API_KEY` for their official
endpoints. Frontier profiles require explicit `FRONTIER_OPENAI_API_KEY`,
`FRONTIER_OPENAI_BASE_URL`, `FRONTIER_ANTHROPIC_API_KEY` and
`FRONTIER_ANTHROPIC_BASE_URL` Secrets. There is no implicit relay or model fallback.
Do not pass a ziwu proxy credential to an official provider endpoint.
Codex provider configuration follows the [official configuration reference](https://developers.openai.com/codex/config-reference).

GitHub artifacts expose sanitized result rows, native lifecycle records and an
aggregate table. Raw model histories, credentials, Oracle actions and camera
recordings are not published. A genuine task failure has verified reward 0;
API/authentication errors, native infrastructure failures, budget exhaustion and
missing results retain distinct statuses and no model score. Usage absent from
native clients remains unknown. CLI cost estimates are not provider invoices.

Initial native L40S/610.57.04 startup currently crashes inside Isaac 5.1 RTX;
no task or model score is claimed for that configuration. The PR records probes
and will pin a working placement before launching scored trials. The original
A10/580.95.05 evidence in PR #2195 is historical, not acceptance of this PR.
