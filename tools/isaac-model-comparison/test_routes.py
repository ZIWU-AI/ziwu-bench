"""Offline contract checks: no model calls, credentials or runtime installs."""

import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from routes import AGENT_TIMEOUT_SEC, CONTEXT_TOKENS, HARNESSES, MODEL, build_route


class RouteTests(unittest.TestCase):
    def test_credentials_never_enter_route_or_generated_configuration(self):
        sentinel = "synthetic-credential-do-not-copy"
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"KIMI_CODE_API_KEY": sentinel}):
                routes = [build_route(name, temporary) for name in HARNESSES]
            self.assertNotIn(sentinel, json.dumps(routes))
            for route in routes:
                self.assertTrue(route["credential_env_names"])
                self.assertFalse(
                    set(route["credential_env_names"]) & set(route["env"])
                )
                self.assertNotIn("${", json.dumps(route))
            for path in Path(temporary).rglob("*"):
                if path.is_file():
                    self.assertNotIn(sentinel, path.read_text())

    def test_codex_configuration_uses_native_responses_without_websockets(self):
        with tempfile.TemporaryDirectory() as temporary:
            route = build_route("codex", temporary)
            config = tomllib.loads(Path(route["kwargs"]["config"]).read_text())
        provider = config["model_providers"][config["model_provider"]]
        self.assertEqual(provider["base_url"], "https://api.kimi.com/coding/v1")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertIs(provider["supports_websockets"], False)
        self.assertEqual(provider["env_key"], route["credential_env_names"][0])
        self.assertEqual(config["model_context_window"], CONTEXT_TOKENS)
        self.assertLess(config["model_auto_compact_token_limit"], CONTEXT_TOKENS)
        self.assertEqual(route["kwargs"]["version"], "0.155.1")

    def test_claude_pins_background_and_subagent_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            route = build_route("claude-code", temporary)
        for name in (
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
        ):
            self.assertEqual(route["env"][name], MODEL)
        self.assertEqual(route["kwargs"]["reasoning_effort"], "high")
        self.assertEqual(route["env"]["ANTHROPIC_BASE_URL"], "https://api.kimi.com/coding")

    def test_kimi_uses_node_adapter_and_native_environment_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            route = build_route("kimi-code", temporary)
        self.assertEqual(route["agent"], "kimi-code")
        self.assertEqual(route["kwargs"], {"version": "2.5.1"})
        self.assertEqual(route["env"]["KIMI_MODEL_NAME"], MODEL)
        self.assertEqual(route["env"]["KIMI_MODEL_THINKING_EFFORT"], "high")
        self.assertIn("always_thinking", route["env"]["KIMI_MODEL_CAPABILITIES"])
        self.assertEqual(route["credential_env_names"], ["KIMI_MODEL_API_KEY"])

    def test_dsh_uses_custom_adapter_and_explicit_messages_protocol(self):
        with tempfile.TemporaryDirectory() as temporary:
            route = build_route("deepseek-harness", temporary)
        self.assertIsNone(route["agent"])
        self.assertEqual(route["import_path"], "dsh_agent:DeepSeekHarness")
        self.assertEqual(route["kwargs"]["model_api"], "anthropic-messages")
        self.assertEqual(route["credential_env_names"], ["KIMI_API_KEY"])

    def test_comparison_has_common_model_context_and_budget_without_ua_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            routes = [build_route(name, temporary) for name in HARNESSES]
        for route in routes:
            self.assertEqual(route["model_name"], MODEL)
            self.assertEqual(route["agent_timeout_sec"], AGENT_TIMEOUT_SEC)
            self.assertEqual(route["provenance"]["context_limit_tokens"], CONTEXT_TOKENS)
            self.assertEqual(route["provenance"]["reasoning_effort"], "high")
            self.assertFalse(any("HEADER" in key or "IDENTITY" in key for key in route["env"]))

    def test_unknown_harness_is_rejected_before_writing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                build_route("kimi-cli", temporary)
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
