"""Pinned, credential-free routes for the Kimi Code harness comparison.

The caller injects its existing KIMI_CODE_API_KEY into credential_env_names at
process launch. This module never reads a credential or writes one to a file.
Route metadata describes configuration, not a claim of live compatibility.
"""

from pathlib import Path
from typing import Any


HARNESSES = ("claude-code", "codex", "kimi-code", "deepseek-harness")
HARBOR_VERSION = "0.23.0"
MODEL = "k3.1-pro"
CONTEXT_TOKENS = 262144
AGENT_TIMEOUT_SEC = 90 * 60
KIMI_BASE = "https://api.kimi.com/coding"
VERSIONS = {
    "claude-code": "2.1.318",
    "codex": "0.155.1",
    "kimi-code": "2.5.1",
    "deepseek-harness": "0.2.2-rc.1",
}

_HARBOR_SOURCE = (
    "https://github.com/harbor-framework/harbor/blob/"
    "1e5c5c6db929a10a140d05e606882c671ae20729/src/harbor/agents/installed/"
)
_KIMI_SOURCE = (
    "https://github.com/MoonshotAI/kimi-code/blob/"
    "131c21a35a0440309f3b0e965961eccd4a7f417f/"
)


def build_route(harness: str, config_dir: str | Path) -> dict[str, Any]:
    """Return a route; write only Codex's non-secret provider configuration.

    Map agent_timeout_sec to Harbor AgentConfig.override_timeout_sec. The
    runner owns credential injection, process isolation, terminal-outcome
    validation and secret removal before it publishes logs or artifacts.
    """
    if harness not in HARNESSES:
        raise ValueError(f"Unsupported harness {harness!r}; choose from {HARNESSES}")

    route: dict[str, Any] = {
        "agent": harness,
        "import_path": None,
        "model_name": MODEL,
        "kwargs": {"version": VERSIONS[harness]},
        "env": {},
        "credential_env_names": [],
        "agent_timeout_sec": AGENT_TIMEOUT_SEC,
        "provenance": {
            "harness": harness,
            "harness_version": VERSIONS[harness],
            "harbor_version": HARBOR_VERSION,
            "provider": "kimi-code-official",
            "model": MODEL,
            "reasoning_effort": "high",
            "context_limit_tokens": CONTEXT_TOKENS,
            "credential_source_env": "KIMI_CODE_API_KEY",
            "agent_timeout_sec": AGENT_TIMEOUT_SEC,
            "client_identity": "native; no client impersonation",
            "sources": [],
            "limitations": [],
        },
    }
    env = route["env"]
    provenance = route["provenance"]

    if harness == "codex":
        directory = Path(config_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        config = directory / "codex-kimi-code.toml"
        config.write_text(
            'model_provider = "kimi_code_official"\n'
            f'model = "{MODEL}"\n'
            'model_reasoning_effort = "high"\n'
            f"model_context_window = {CONTEXT_TOKENS}\n"
            "model_auto_compact_token_limit = 220000\n"
            "[model_providers.kimi_code_official]\n"
            'name = "Kimi Code official"\n'
            f'base_url = "{KIMI_BASE}/v1"\n'
            'env_key = "OPENAI_API_KEY"\n'
            'wire_api = "responses"\n'
            "supports_websockets = false\n",
            encoding="utf-8",
        )
        route["kwargs"].update(reasoning_effort="high", config=str(config))
        env["OPENAI_BASE_URL"] = f"{KIMI_BASE}/v1"
        route["credential_env_names"] = ["OPENAI_API_KEY"]
        provenance.update(
            protocol="responses",
            api_base=f"{KIMI_BASE}/v1",
            context_compact_at_tokens=220000,
            sources=[
                "https://www.kimi.com/code/docs/third-party-tools/codex.html",
                _HARBOR_SOURCE + "codex.py",
            ],
        )
    elif harness == "claude-code":
        route["kwargs"]["reasoning_effort"] = "high"
        env.update(
            ANTHROPIC_BASE_URL=KIMI_BASE,
            ANTHROPIC_MODEL=MODEL,
            ANTHROPIC_DEFAULT_FABLE_MODEL=MODEL,
            ANTHROPIC_DEFAULT_OPUS_MODEL=MODEL,
            ANTHROPIC_DEFAULT_SONNET_MODEL=MODEL,
            ANTHROPIC_DEFAULT_HAIKU_MODEL=MODEL,
            CLAUDE_CODE_SUBAGENT_MODEL=MODEL,
            CLAUDE_CODE_EFFORT_LEVEL="high",
            CLAUDE_CODE_AUTO_COMPACT_WINDOW=str(CONTEXT_TOKENS),
            CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(CONTEXT_TOKENS),
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
        )
        route["credential_env_names"] = ["ANTHROPIC_API_KEY"]
        provenance.update(
            protocol="anthropic-messages",
            api_base=KIMI_BASE,
            sources=[
                "https://www.kimi.com/code/docs/third-party-tools/claude-code.html",
                _HARBOR_SOURCE + "claude_code.py",
            ],
        )
    elif harness == "kimi-code":
        # Harbor's Node KimiCode adapter has no reasoning_effort kwarg. The
        # native environment overlay sets effort and preserves tool reasoning.
        env.update(
            KIMI_MODEL_PROVIDER_TYPE="kimi",
            KIMI_MODEL_NAME=MODEL,
            KIMI_MODEL_BASE_URL=f"{KIMI_BASE}/v1",
            KIMI_MODEL_MAX_CONTEXT_SIZE=str(CONTEXT_TOKENS),
            KIMI_MODEL_CAPABILITIES="thinking,always_thinking,image_in,tool_use",
            KIMI_MODEL_THINKING_EFFORT="high",
            KIMI_MODEL_THINKING_KEEP="all",
            KIMI_DISABLE_TELEMETRY="1",
            KIMI_CODE_NO_AUTO_UPDATE="1",
        )
        route["credential_env_names"] = ["KIMI_MODEL_API_KEY"]
        provenance.update(
            protocol="chat-completions",
            api_base=f"{KIMI_BASE}/v1",
            sources=[
                _HARBOR_SOURCE + "kimi_code.py",
                _KIMI_SOURCE + "docs/en/configuration/env-vars.md",
                _KIMI_SOURCE + "docs/en/reference/kimi-command.md",
            ],
            limitations=[
                "Harbor 0.23.0 has no KimiCode ATIF/usage converter; missing "
                "usage and cost must remain unknown.",
                "Kimi Code 2.5.1 stream-json does not include token usage; "
                "its meta events are not terminal-success receipts.",
            ],
        )
    else:
        route["agent"] = None
        route["import_path"] = "dsh_agent:DeepSeekHarness"
        route["kwargs"].update(
            model_api="anthropic-messages", base_url=KIMI_BASE
        )
        route["credential_env_names"] = ["KIMI_API_KEY"]
        provenance.update(
            protocol="anthropic-messages",
            api_base=KIMI_BASE,
            sources=[
                "https://github.com/deepseek-ai/deepseek-harness/blob/"
                "fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/"
                "packages/bundle/headless/README.md",
                "https://www.kimi.com/code/docs/en/",
            ],
            limitations=[
                "Kimi documents the protocol, but this dsh client route needs "
                "a real-identity preflight; rejection is a provider/adapter "
                "failure, not a model score.",
                "dsh JSON progress fields can be truncated; retain its "
                "private durable session log for usage and diagnostics.",
            ],
        )

    return route
