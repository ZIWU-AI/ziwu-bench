import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import AsyncMock, patch

from harbor.agents.factory import AgentFactory
from harbor.agents.installed.kimi_code import KimiCode
from harbor.models.trial.config import AgentConfig

from deepseek_routes import (
    CLAUDE_MODEL_SELECTOR, CONTEXT_TOKENS, DeepSeekKimiCode,
    HARNESSES, KIMI_THINKING_CONFIG, MESSAGES_BASE, MODEL, build_route,
)


class DeepSeekHarnessRoutesTests(unittest.TestCase):
    def test_routes_keep_credentials_out_of_configuration_and_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "synthetic-do-not-copy"}):
                routes = [build_route(name, td) for name in HARNESSES]
            text = json.dumps(routes) + "".join(p.read_text() for p in Path(td).iterdir())
            self.assertNotIn("synthetic-do-not-copy", text)
            for route in routes:
                self.assertEqual(route["provenance"]["model"], MODEL)
                self.assertEqual(route["provenance"]["context_limit_tokens"], CONTEXT_TOKENS)
                self.assertEqual(route["provenance"]["reasoning_effort"], "high")
                self.assertEqual(route["agent_timeout_sec"], 5400)
                for key in route["credential_env_names"]:
                    self.assertNotIn(key, route["env"])

    def test_claude_uses_official_context_selector_and_pins_every_alias(self):
        route = build_route("claude-code", "/unused")
        self.assertEqual(route["model_name"], CLAUDE_MODEL_SELECTOR)
        self.assertEqual(route["env"]["ANTHROPIC_BASE_URL"], MESSAGES_BASE)
        for key, value in route["env"].items():
            if key.endswith("_MODEL"):
                self.assertEqual(value, CLAUDE_MODEL_SELECTOR)
        self.assertEqual(route["kwargs"]["reasoning_effort"], "high")
        self.assertEqual(route["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "786432")

    def test_kimi_uses_generic_openai_and_native_thinking_config(self):
        route = build_route("kimi-code", "/unused")
        self.assertEqual(route["import_path"], "deepseek_routes:DeepSeekKimiCode")
        self.assertEqual(route["env"]["KIMI_MODEL_PROVIDER_TYPE"], "openai")
        self.assertEqual(route["env"]["KIMI_MODEL_REASONING_KEY"], "reasoning_content")
        self.assertNotIn("KIMI_MODEL_THINKING_EFFORT", route["env"])
        self.assertNotIn("KIMI_MODEL_THINKING_KEEP", route["env"])
        self.assertNotIn("config", route["kwargs"])
        self.assertEqual(tomllib.loads(KIMI_THINKING_CONFIG)["thinking"],
                         {"enabled": True, "effort": "high"})

    def test_harbor_constructs_claude_and_kimi_routes(self):
        with tempfile.TemporaryDirectory() as td:
            for harness in ("claude-code", "kimi-code"):
                route = build_route(harness, td)
                config = AgentConfig(name=route["agent"], import_path=route["import_path"],
                                     model_name=route["model_name"], kwargs=route["kwargs"],
                                     env=route["env"])
                agent = AgentFactory.create_agent_from_config(config, logs_dir=Path(td)/harness)
                self.assertEqual(agent.model_name, route["model_name"])
                self.assertEqual(agent.version(), route["kwargs"]["version"])

    def test_dsh_uses_native_deepseek_provider_contract(self):
        route = build_route("deepseek-harness", "/unused")
        self.assertEqual(route["import_path"], "dsh_agent:DeepSeekHarness")
        self.assertEqual(route["credential_env_names"], ["DEEPSEEK_API_KEY"])
        self.assertEqual(route["kwargs"]["provider"], "deepseek")
        self.assertEqual(route["kwargs"]["base_url"], MESSAGES_BASE)

    def test_codex_delegates_to_existing_route(self):
        with tempfile.TemporaryDirectory() as td:
            from deepseek_codex import build_route as codex_route
            self.assertEqual(build_route("codex", td), codex_route(td))

    def test_unknown_harness_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                build_route("kimi-cli", td)
            self.assertEqual(list(Path(td).iterdir()), [])


class KimiSettingsUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_uploads_thinking_config_to_native_home(self):
        with tempfile.TemporaryDirectory() as td:
            route = build_route("kimi-code", td)
            agent = DeepSeekKimiCode(logs_dir=Path(td)/"logs", model_name=MODEL,
                                    extra_env=route["env"], **route["kwargs"])
            agent.exec_as_agent = AsyncMock()
            agent._upload_config_text = AsyncMock()
            environment = object()
            with patch.object(KimiCode, "setup", new_callable=AsyncMock) as setup:
                await agent.setup(environment)
            setup.assert_awaited_once_with(environment)
            agent._upload_config_text.assert_awaited_once_with(
                environment, content=KIMI_THINKING_CONFIG,
                remote_path="/logs/agent/.kimi-code/config.toml",
                filename="deepseek-kimi-config.toml",
            )
            self.assertIs(DeepSeekKimiCode.run, KimiCode.run)


if __name__ == "__main__":
    unittest.main()
