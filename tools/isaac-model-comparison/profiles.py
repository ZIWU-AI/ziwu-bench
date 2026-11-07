"""Explicit model/harness identities; no automatic model substitution."""
import os
from pathlib import Path

from routes import HARNESSES, VERSIONS

PROFILES = {
    "kimi": {"model": "k3.1-pro", "secret": "KIMI_CODE_API_KEY", "harnesses": HARNESSES},
    "deepseek": {"model": "deepseek-flash", "secret": "DEEPSEEK_API_KEY", "harnesses": HARNESSES},
    "astra": {"model": "gpt-6-astra", "secret": "FRONTIER_OPENAI_API_KEY", "harnesses": ("codex",)},
    "sol": {"model": "gpt-6-sol", "secret": "FRONTIER_OPENAI_API_KEY", "harnesses": ("codex",)},
    "opus": {"model": "claude-opus-5-5", "secret": "FRONTIER_ANTHROPIC_API_KEY", "harnesses": ("claude-code",)},
}


def route_for(profile, harness, directory):
    spec = PROFILES[profile]
    if harness not in spec["harnesses"]:
        raise ValueError("Unsupported profile/harness pair")
    if profile in ("kimi", "deepseek"):
        if profile == "kimi":
            from routes import build_route
        else:
            from deepseek_routes import build_route
        return build_route(harness, directory)
    # Endpoints must be explicitly configured by the operator. No third-party
    # relay or fallback model is silently selected.
    name = "FRONTIER_ANTHROPIC_BASE_URL" if profile == "opus" else "FRONTIER_OPENAI_BASE_URL"
    base = os.environ.get(name, "").rstrip("/")
    if not base.startswith("https://"):
        raise ValueError(name + " must be configured with an HTTPS endpoint")
    model = spec["model"]
    route = {"agent": harness, "import_path": None, "model_name": model,
             "kwargs": {"version": VERSIONS[harness], "reasoning_effort": "high"},
             "env": {}, "agent_timeout_sec": 5400,
             "credential_env_names": ["ANTHROPIC_API_KEY" if profile == "opus" else "OPENAI_API_KEY"],
             "provenance": {"model": model, "harness": harness, "harness_version": VERSIONS[harness],
                            "harbor_version": "0.23.0", "api_base": base,
                            "reasoning_effort": "high", "agent_timeout_sec": 5400,
                            "context_limit_tokens": None,
                            "context_policy": "native pinned client model metadata",
                            "credential_source_env": spec["secret"],
                            "client_identity": "native; no client impersonation"}}
    if profile == "opus":
        route["env"] = {"ANTHROPIC_BASE_URL": base, "CLAUDE_CODE_EFFORT_LEVEL": "high",
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"}
        for key in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            route["env"][key] = model
        route["provenance"]["protocol"] = "anthropic-messages"
    else:
        import json
        path = Path(directory) / "codex-frontier.toml"
        path.write_text('model_provider = "ziwu_frontier"\n'
                        + 'model = ' + json.dumps(model) + '\nmodel_reasoning_effort = "high"\n'
                        + '[model_providers.ziwu_frontier]\nname = "Explicit frontier endpoint"\n'
                        + 'base_url = ' + json.dumps(base) + '\nenv_key = "OPENAI_API_KEY"\n'
                        + 'wire_api = "responses"\nsupports_websockets = false\n')
        route["kwargs"]["config"] = str(path)
        route["env"]["OPENAI_BASE_URL"] = base
        route["provenance"]["protocol"] = "responses"
    return route
