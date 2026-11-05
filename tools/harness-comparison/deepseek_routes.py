"""Native harness routes for DeepSeek's official Flash API.

The runner injects DEEPSEEK_API_KEY into the declared credential names. This
module never reads a secret. Kimi Code needs a small adapter only to upload its
native thinking settings; its CLI, protocol serializer and identity are intact.
"""

from pathlib import Path
from typing import Any

from harbor.agents.installed.kimi_code import KimiCode

from routes import HARNESSES, VERSIONS


MODEL = "deepseek-flash"
CONTEXT_TOKENS = 1048576
AGENT_TIMEOUT_SEC = 5400
CHAT_BASE = "https://api.deepseek.com"
MESSAGES_BASE = "https://api.deepseek.com/anthropic"
CLAUDE_MODEL_SELECTOR = MODEL + "[1m]"
KIMI_THINKING_CONFIG = '[thinking]\nenabled = true\neffort = "high"\n'
_KIMI_SOURCE = (
    "https://github.com/MoonshotAI/kimi-code/blob/"
    "@moonshot-ai/kimi-code@2.5.1/"
)


class DeepSeekKimiCode(KimiCode):
    """Upload native high-effort settings before the unchanged Kimi CLI runs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.model_name != MODEL or self.version() != VERSIONS["kimi-code"]:
            raise ValueError("DeepSeekKimiCode requires deepseek-flash and Kimi Code 2.5.1")
        if (self._get_env("KIMI_MODEL_PROVIDER_TYPE") != "openai"
                or self._get_env("KIMI_MODEL_BASE_URL") != CHAT_BASE):
            raise ValueError("DeepSeekKimiCode requires the official OpenAI-compatible route")

    async def setup(self, environment) -> None:
        await super().setup(environment)
        env = self._runtime_env()
        await self.exec_as_agent(
            environment, command='mkdir -p "$KIMI_CODE_HOME"', env=env,
        )
        await self._upload_config_text(
            environment, content=KIMI_THINKING_CONFIG,
            remote_path=env["KIMI_CODE_HOME"] + "/config.toml",
            filename="deepseek-kimi-config.toml",
        )


def build_route(harness: str, config_dir: str | Path) -> dict[str, Any]:
    if harness not in HARNESSES:
        raise ValueError(f"Unsupported harness {harness!r}")
    if harness == "codex":
        from deepseek_codex import build_route as codex_route
        return codex_route(config_dir)

    route: dict[str, Any] = {
        "agent": harness, "import_path": None, "model_name": MODEL,
        "kwargs": {"version": VERSIONS[harness]}, "env": {},
        "credential_env_names": [], "agent_timeout_sec": AGENT_TIMEOUT_SEC,
        "provenance": {
            "harness": harness, "harness_version": VERSIONS[harness],
            "harbor_version": "0.23.0", "provider": "deepseek-official",
            "model": MODEL, "model_alias_target_documented": "DeepSeek-V4.1-Flash-1017",
            "reasoning_effort": "high", "context_limit_tokens": CONTEXT_TOKENS,
            "credential_source_env": "DEEPSEEK_API_KEY",
            "agent_timeout_sec": AGENT_TIMEOUT_SEC,
            "client_identity": "native; no client impersonation", "sources": [],
            "limitations": [
                "The model slug is a server-managed alias, not an immutable model pin.",
                "Native harness prompts, compression policies and tool behavior differ.",
                "Account access and live compatibility must pass the separate preflight.",
            ],
        },
    }
    env = route["env"]
    provenance = route["provenance"]

    if harness == "claude-code":
        # [1m] is Claude's documented context selector, not a different API model.
        route["model_name"] = CLAUDE_MODEL_SELECTOR
        route["kwargs"]["reasoning_effort"] = "high"
        env.update(
            ANTHROPIC_BASE_URL=MESSAGES_BASE,
            ANTHROPIC_MODEL=CLAUDE_MODEL_SELECTOR,
            ANTHROPIC_DEFAULT_FABLE_MODEL=CLAUDE_MODEL_SELECTOR,
            ANTHROPIC_DEFAULT_OPUS_MODEL=CLAUDE_MODEL_SELECTOR,
            ANTHROPIC_DEFAULT_SONNET_MODEL=CLAUDE_MODEL_SELECTOR,
            ANTHROPIC_DEFAULT_HAIKU_MODEL=CLAUDE_MODEL_SELECTOR,
            CLAUDE_CODE_SUBAGENT_MODEL=CLAUDE_MODEL_SELECTOR,
            CLAUDE_CODE_EFFORT_LEVEL="high",
            CLAUDE_CODE_AUTO_COMPACT_WINDOW="786432",
            CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(CONTEXT_TOKENS),
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
        )
        route["credential_env_names"] = ["ANTHROPIC_API_KEY"]
        provenance.update(
            protocol="anthropic-messages", api_base=MESSAGES_BASE,
            native_model_selector=CLAUDE_MODEL_SELECTOR,
            context_compact_window_tokens=786432,
            sources=[
                "https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code/",
                "https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/",
            ],
        )
        provenance["limitations"].append(
            "All background aliases use the Flash selector. The requested high "
            "effort differs from the official guide's max example."
        )
    elif harness == "kimi-code":
        route["agent"] = None
        route["import_path"] = "deepseek_routes:DeepSeekKimiCode"
        env.update(
            KIMI_MODEL_PROVIDER_TYPE="openai", KIMI_MODEL_NAME=MODEL,
            KIMI_MODEL_BASE_URL=CHAT_BASE,
            KIMI_MODEL_MAX_CONTEXT_SIZE=str(CONTEXT_TOKENS),
            KIMI_MODEL_CAPABILITIES="image_in,thinking,tool_use",
            KIMI_MODEL_REASONING_KEY="reasoning_content",
            KIMI_DISABLE_TELEMETRY="1", KIMI_CODE_NO_AUTO_UPDATE="1",
        )
        route["credential_env_names"] = ["KIMI_MODEL_API_KEY"]
        provenance.update(
            protocol="chat-completions", api_base=CHAT_BASE,
            native_config={"thinking": {"enabled": True, "effort": "high"}},
            thinking_request="reasoning_effort=high enables DeepSeek thinking",
            sources=[
                "https://api-docs.deepseek.com/api/create-chat-completion/",
                _KIMI_SOURCE + "docs/en/configuration/config-files.md",
                _KIMI_SOURCE + "packages/agent-core-v2/src/human/llm/builtin/protocol/openai/lower.ts",
            ],
        )
        provenance["limitations"].extend([
            "Kimi Code 2.5.1 has no deepseek provider. Its native openai "
            "serializer sends top-level reasoning_effort, not Kimi thinking.effort.",
            "KIMI_MODEL_THINKING_EFFORT is Kimi-provider-only; high is set in "
            "the native config uploaded by the adapter.",
            "Harbor has no KimiCode ATIF/usage converter; missing token usage "
            "and costs remain unknown.",
        ])
    else:
        route["agent"] = None
        route["import_path"] = "dsh_agent:DeepSeekHarness"
        route["kwargs"].update(
            provider="deepseek", model_api="anthropic-messages", base_url=MESSAGES_BASE,
        )
        route["credential_env_names"] = ["DEEPSEEK_API_KEY"]
        provenance.update(
            protocol="anthropic-messages", api_base=MESSAGES_BASE,
            native_provider="deepseek-official",
            requested_max_output_tokens=32768,
            sources=[
                "https://github.com/deepseek-ai/deepseek-harness/tree/"
                "fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159",
                "https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/",
            ],
        )
        provenance["limitations"].append(
            "32768 is this adapter's requested output cap, not the model's maximum."
        )

    provenance["credential_env_names"] = list(route["credential_env_names"])
    return route
