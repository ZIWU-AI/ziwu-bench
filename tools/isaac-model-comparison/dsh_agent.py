"""Harbor 0.23 adapter for the pinned DeepSeek Harness headless CLI.

Two explicit routes are supported: Kimi through pi-ai (the unchanged default),
and official DeepSeek through dsh's native Anthropic Messages transport.
The Docker task is the execution boundary; no host tools or directories are
exposed. Native sessions are retained, but ATIF and usage conversion are not
claimed: the headless event projection has no usage contract and is truncated.

Audited upstream: deepseek-ai/deepseek-harness@fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159.
"""

from __future__ import annotations

import json
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.options import InstalledAgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


DSH_VERSION = "0.2.2-rc.1"
NODE_VERSION = "24.9.0"
MODEL = "k3.1-pro"
USER_AGENT = (f"deepseek-harness/{DSH_VERSION} "
              "(+https://github.com/deepseek-ai/deepseek-harness)")


@dataclass(frozen=True)
class DshRoute:
    model: str
    base_url: str
    credential_env: str
    provider_id: str
    context_window: int


ROUTES = {
    "kimi": DshRoute(MODEL, "https://api.kimi.com/coding", "KIMI_API_KEY",
                     "kimi-benchmark", 262144),
    "deepseek": DshRoute("deepseek-flash", "https://api.deepseek.com/anthropic",
                         "DEEPSEEK_API_KEY", "deepseek-official", 1048576),
}


class DshIntegrationError(RuntimeError):
    """The CLI/provider integration did not produce a completed agent run."""


class DshOptions(InstalledAgentOptions):
    version: Literal["0.2.2-rc.1"] = DSH_VERSION
    provider: Literal["kimi", "deepseek"] = "kimi"
    base_url: Literal["https://api.kimi.com/coding", "https://api.deepseek.com/anthropic"] = (
        "https://api.kimi.com/coding"
    )
    model_api: Literal["anthropic-messages"] = "anthropic-messages"
    max_tokens: int = Field(default=32768, ge=1024, le=32768)

    @model_validator(mode="after")
    def validate_route(self) -> DshOptions:
        if self.base_url != self.route.base_url:
            raise ValueError(f"Provider {self.provider!r} requires base_url={self.route.base_url!r}")
        return self

    @property
    def route(self) -> DshRoute:
        return ROUTES[self.provider]


def build_profile(options: DshOptions, logs_dir: str) -> list[dict[str, Any]]:
    """Return a secret-free Cordis patch for one fresh trial."""
    route = options.route
    # Only the selected route is enabled. No account login, uploads, or
    # title-only model calls; settings cannot select another model mid-run.
    disabled = (
        "session-log-deepseek", "session-telemetry-otel", "otel",
        "plugin-package-inventory-deepseek",
        "llm-deepseek" if options.provider == "kimi" else "llm-pi-ai",
        "llm-deepseek-account", "deepseek-account", "credentials",
        "authorization", "web-search-deepseek", "web-deepseek-api",
        "session-title-llm", "plugin-manager", "tool-plugin-manager",
        "settings", "hmr",
    )
    if options.provider == "kimi":
        transport = {"id": "llm-pi-ai", "config": {"providers": {
            route.provider_id: {
                "apiKeyEnv": route.credential_env, "api": options.model_api,
                "baseURL": route.base_url,
                # Keep dsh's mandatory native attribution unmodified.
                "reasoning": "high",
                "models": [{"id": route.model, "contextWindow": route.context_window,
                            "maxTokens": options.max_tokens, "input": ["text"],
                            "reasoningEfforts": {"high": "high"}}],
                "retryPolicy": {"mode": "normal", "maxRetries": 0},
            },
        }}}
    else:
        # Native dsh maps reasoningEffort to output_config.effort and preserves
        # thinking blocks on tool replay. pi-ai's thinking budget alone does not
        # fix effort on DeepSeek. The explicit single-model catalog also stops
        # the native route's remote model-list discovery and periodic refresh.
        transport = {"id": "llm-deepseek", "disabled": False, "config": {
            "apiKeyEnv": route.credential_env, "baseURL": route.base_url,
            "thinking": "enabled", "reasoningEffort": "high",
            "defaultContextWindow": route.context_window,
            "maxTokens": options.max_tokens,
            "models": [{"id": route.model, "contextWindow": route.context_window,
                        "maxTokens": options.max_tokens, "inputModalities": ["text"],
                        "systemPromptUpdate": "in-history", "toolUpdate": "addition-only"}],
            "retryPolicy": {"mode": "normal", "maxRetries": 0},
        }}
    return [{"id": name, "disabled": True} for name in disabled] + [
        {"id": "agent-default-model", "config": {
            "provider": route.provider_id, "model": route.model,
            "reasoningEffort": "high",
        }},
        transport,
        {"id": "session-persistence-jsonl", "config": {
            "root": f"{logs_dir}/dsh-sessions", "compression": "none",
        }},
    ]


def summarize_events(path: Path, exit_code: int | None) -> dict[str, Any]:
    """Validate headless settlement without trusting the agent's final prose."""
    session_ids: list[str] = []
    final: dict[str, Any] | None = None
    error_codes: list[str] = []
    malformed = 0
    truncated = 0
    event_count = 0
    final_count = 0
    last_type = None
    if path.exists():
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    malformed += 1
                    continue
                if not isinstance(event, dict):
                    malformed += 1
                    continue
                event_count += 1
                last_type = event.get("type")
                truncated += bool(event.get("truncated"))
                if event.get("type") == "session":
                    if isinstance(event.get("sessionId"), str):
                        session_ids.append(event["sessionId"])
                elif event.get("type") == "final":
                    final_count += 1
                    final = event
                elif event.get("type") == "error":
                    error_codes.append(str(event.get("code") or "HEADLESS_ERROR"))
    reason = final.get("reason") if final else None
    reason_kind = reason.get("kind") if isinstance(reason, dict) else None
    same_session = (len(session_ids) == 1 and final is not None
                    and final.get("sessionId") == session_ids[0])
    completed = (exit_code == 0 and reason_kind == "completed" and final_count == 1
                 and last_type == "final"
                 and same_session and malformed == 0 and not error_codes)
    return {
        "completed": completed, "process_exit_code": exit_code,
        "session_id": session_ids[0] if len(session_ids) == 1 else None,
        "final_reason_kind": reason_kind,
        "final_error_code": reason.get("code") if isinstance(reason, dict) else None,
        "error_codes": error_codes, "malformed_event_lines": malformed,
        "truncated_event_count": truncated, "event_count": event_count,
        "final_event_count": final_count,
        "usage_status": "unknown: native usage conversion is not implemented",
        "trajectory_format": "dsh native session JSONL; headless NDJSON projection",
    }


class DeepSeekHarness(BaseInstalledAgent):
    options_model = DshOptions
    options: DshOptions

    def __init__(self, *args: Any, version: str = DSH_VERSION, **kwargs: Any):
        super().__init__(*args, version=version, **kwargs)
        if self.model_name != self.options.route.model:
            raise ValueError(
                f"Provider {self.options.provider!r} requires model_name={self.options.route.model!r}"
            )
        self._exit_code: int | None = None

    @staticmethod
    def name() -> str:
        return "deepseek-harness"

    def get_version_command(self) -> str:
        return '. "$HOME/.nvm/nvm.sh"; dsh --version'

    def parse_version(self, stdout: str) -> str:
        return stdout.strip().splitlines()[-1].strip()

    async def install(self, environment: BaseEnvironment) -> None:
        await self.ensure_system_dependencies(environment, ("curl",))
        await self.exec_as_agent(environment, command=(
            "set -euo pipefail; "
            "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh "
            "| env -u NODE_VERSION bash; "
            'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; '
            f"nvm install {NODE_VERSION}; nvm alias default {NODE_VERSION}; "
            f"npm install --global @deepseek-ai/dsh@{DSH_VERSION}; "
            "node --version; dsh --version"
        ))

    async def _upload_text(self, environment: BaseEnvironment, path: str, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "payload"
            source.write_text(text, encoding="utf-8")
            await self._upload_agent_owned_file(environment, source, path)

    @with_prompt_template
    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        credential_env = self.options.route.credential_env
        key = self._get_env(credential_env)
        if not key:
            raise DshIntegrationError(f"{credential_env} is missing; no model request was sent")
        root = self.environment_logs_dir.as_posix()
        home = f"{root}/dsh-home"
        profile = f"{home}/profiles/headless"
        # Refuse reuse: no conversation, credential store, or home patch can
        # leak from another trial into this fresh run.
        await self.exec_as_agent(environment, command=(
            f"test ! -e {shlex.quote(home)} && "
            f"mkdir -p {shlex.quote(profile)} && chmod 700 {shlex.quote(home)}"
        ))
        manifest = {"name": "ziwu-bench-dsh-headless", "private": True,
                    "dsh": {"profile": {"bundles": [
                        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]}}}
        await self._upload_text(environment, f"{profile}/package.json", json.dumps(manifest))
        await self._upload_text(environment, f"{profile}/cordis.patch.yml",
                                json.dumps(build_profile(self.options, root), indent=2))
        await self._upload_text(environment, f"{root}/dsh-instruction.txt", instruction)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        env = {credential_env: key, "DSH_HOME": home,
               "DSH_TELEMETRY_DISABLED": "1", "DSH_TELEMETRY_MODE": "DISABLED"}
        # Full tool permissions are limited to Harbor's task container. Do not
        # invoke this on the host or mount verifier/solution/host directories.
        command = (
            'set +e; (. "$HOME/.nvm/nvm.sh" && '
            f"nvm use {NODE_VERSION} > /dev/null && "
            "dsh --profile headless --json --permission-mode danger-full-access "
            "--approval-policy never -) "
            f"< {shlex.quote(root + '/dsh-instruction.txt')} "
            f"> {shlex.quote(root + '/dsh-events.jsonl')} "
            f"2> {shlex.quote(root + '/dsh-stderr.log')}; "
            "dsh_exit=$?; "
            f"printf '%s\\n' \"$dsh_exit\" > {shlex.quote(root + '/dsh-exit-code.txt')}; "
            'exit "$dsh_exit"'
        )
        # Use raw exec so a nonzero CLI exit remains available for structured
        # classification; never embed credentials in commands or exceptions.
        result = await environment.exec(command=command, env=env)
        self._exit_code = result.return_code
        try:
            await environment.download_file(f"{root}/dsh-events.jsonl",
                                            self.logs_dir / "dsh-events.jsonl")
        except Exception as exc:
            raise DshIntegrationError(
                "dsh event log could not be recovered; inspect the trial's execution logs"
            ) from exc
        self.populate_context_post_run(context)
        if not context.metadata["dsh"]["completed"]:
            raise DshIntegrationError(
                f"dsh did not complete (exit={self._exit_code}); "
                "inspect private dsh-status.json, dsh-stderr.log and native sessions"
            )

    def populate_context_post_run(self, context: AgentContext) -> None:
        exit_file = self.logs_dir / "dsh-exit-code.txt"
        exit_code = self._exit_code
        if exit_file.exists():
            try:
                exit_code = int(exit_file.read_text().strip())
            except ValueError:
                exit_code = None
        status = summarize_events(self.logs_dir / "dsh-events.jsonl", exit_code)
        route = self.options.route
        status.update({"harness_version": DSH_VERSION, "node_version": NODE_VERSION,
                       "provider": self.options.provider, "model": route.model,
                       "api": self.options.model_api, "base_url": self.options.base_url,
                       "user_agent": USER_AGENT, "reasoning_effort": "high",
                       "context_window": route.context_window, "max_tokens": self.options.max_tokens})
        context.metadata = {**(context.metadata or {}), "dsh": status}
        # Unknown is not zero; do not use prices for a different model/provider.
        context.n_input_tokens = context.n_output_tokens = context.n_cache_tokens = None
        context.cost_usd = None
        context.model_usage = None
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "dsh-status.json").write_text(json.dumps(status, indent=2) + "\n")
