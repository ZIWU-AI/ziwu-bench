"""Official DeepSeek Responses route using the unchanged pinned Codex client.

The adjacent catalog is the deepseek-flash entry from DeepSeek's official
Codex integration documentation, retrieved 2026-11-05. Only the unrequested
Pro entry was removed; the Flash entry, including its instructions, is intact.
No setup script, protocol proxy or alternative Codex distribution is used.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from harbor.agents.installed.codex import Codex


MODEL = "deepseek-flash"
VERSION = "0.155.1"
API_BASE = "https://api.deepseek.com/"
CONTEXT_TOKENS = 1048576
COMPACT_TOKENS = 943718  # Codex 0.155.1's 90% default for this official catalog.
CATALOG_PATH = Path(__file__).with_name("deepseek-model-catalog.json")
REMOTE_CATALOG = "/installed-agent/deepseek-model-catalog.json"
SOURCE = "https://api-docs.deepseek.com/quick_start/agent_integrations/codex/"


def catalog_content() -> str:
    """Validate the reviewed catalog before copying it into a trial container."""
    content = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = json.loads(content)
    models = catalog.get("models", [])
    if len(models) != 1 or models[0].get("slug") != MODEL:
        raise ValueError("The DeepSeek comparison requires exactly the Flash catalog entry")
    model = models[0]
    if (model.get("context_window") != CONTEXT_TOKENS
            or model.get("max_context_window") != CONTEXT_TOKENS
            or model.get("default_reasoning_level") != "high"
            or model.get("effective_context_window_percent") != 95):
        raise ValueError("Official DeepSeek model metadata has changed")
    if not model.get("base_instructions") or not model.get("model_messages", {}).get("instructions_template"):
        raise ValueError("The official catalog must retain its model instructions")
    return content


class DeepSeekCodex(Codex):
    """Harbor's native Codex adapter, plus upload of its non-secret catalog."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.model_name != MODEL or self.version() != VERSION:
            raise ValueError("DeepSeekCodex requires deepseek-flash and Codex 0.155.1")
        if self._base_config.get("model_catalog_json") != REMOTE_CATALOG:
            raise ValueError("Codex must reference the catalog uploaded inside its container")
        provider = self._base_config.get("model_providers", {}).get("deepseek_official", {})
        if (provider.get("base_url") != API_BASE or provider.get("wire_api") != "responses"
                or provider.get("env_key") != "OPENAI_API_KEY"
                or provider.get("supports_websockets") is not False):
            raise ValueError("DeepSeekCodex requires the reviewed official Responses route")
        self._catalog_content = catalog_content()

    async def setup(self, environment) -> None:
        await super().setup(environment)
        await self._upload_config_text(
            environment, content=self._catalog_content, remote_path=REMOTE_CATALOG,
            filename="deepseek-model-catalog.json",
        )


def build_route(config_dir: str | Path) -> dict[str, Any]:
    """Return the common runner interface without accessing any credentials."""
    catalog = catalog_content()
    directory = Path(config_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "codex-deepseek.toml"
    config_path.write_text(
        f'model = "{MODEL}"\n'
        'model_provider = "deepseek_official"\n'
        'forced_login_method = "api"\n'
        'model_reasoning_effort = "high"\n'
        'model_reasoning_summary = "none"\n'
        'web_search = "disabled"\n'
        'show_raw_agent_reasoning = true\n'
        f'model_catalog_json = "{REMOTE_CATALOG}"\n'
        f'model_context_window = {CONTEXT_TOKENS}\n'
        f'model_auto_compact_token_limit = {COMPACT_TOKENS}\n'
        '[model_providers.deepseek_official]\n'
        'name = "DeepSeek official"\n'
        f'base_url = "{API_BASE}"\n'
        'wire_api = "responses"\n'
        'env_key = "OPENAI_API_KEY"\n'
        'supports_websockets = false\n',
        encoding="utf-8",
    )
    return {
        "agent": None,
        "import_path": "deepseek_codex:DeepSeekCodex",
        "model_name": MODEL,
        "kwargs": {
            "version": VERSION, "reasoning_effort": "high",
            "reasoning_summary": "none", "web_search": "disabled",
            "config": str(config_path),
        },
        "env": {"OPENAI_BASE_URL": API_BASE},
        "credential_env_names": ["OPENAI_API_KEY"],
        "agent_timeout_sec": 5400,
        "provenance": {
            "harness": "codex", "harness_version": VERSION,
            "harbor_version": "0.23.0", "provider": "deepseek-official",
            "model": MODEL, "model_alias_target_documented": "DeepSeek-V4.1-Flash-1017",
            "protocol": "responses", "api_base": API_BASE,
            "reasoning_effort": "high", "context_limit_tokens": CONTEXT_TOKENS,
            "effective_context_window_percent": 95,
            "context_compact_at_tokens": COMPACT_TOKENS,
            "credential_source_env": "DEEPSEEK_API_KEY",
            "credential_env_names": ["OPENAI_API_KEY"], "agent_timeout_sec": 5400,
            "client_identity": "native Codex; no client impersonation",
            "catalog_source": SOURCE, "catalog_retrieved_at": "2026-11-05",
            "catalog_sha256": hashlib.sha256(catalog.encode()).hexdigest(),
            "catalog_selection": "Official Flash entry unchanged; Pro entry omitted",
            "sources": [SOURCE, "https://api-docs.deepseek.com/guides/responses_api/"],
            "limitations": [
                "Uses the official 1M catalog and its model instructions; the Kimi "
                "run uses a 256K context. This is not an equal-context model comparison.",
                "DeepSeek's model slug is an alias; the documented target is not "
                "an immutable server-side model pin.",
                "Account access and live compatibility must pass the separate preflight.",
            ],
        },
    }
