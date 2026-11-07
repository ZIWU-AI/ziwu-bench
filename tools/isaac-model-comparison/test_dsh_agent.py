"""Offline contract tests; no Docker, model API, or real credentials required."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harbor.agents.factory import AgentFactory
from harbor.models.agent.context import AgentContext
from harbor.models.trial.config import AgentConfig

from dsh_agent import (
    DSH_VERSION, ROUTES, USER_AGENT, DeepSeekHarness, DshIntegrationError,
    DshOptions, build_profile, summarize_events,
)


def events(*extra, reason=None, session="session-test"):
    return [
        {"type": "session", "sessionId": session}, *extra,
        {"type": "final", "sessionId": session,
         "reason": reason or {"kind": "completed"}, "text": "done"},
    ]


class EventContractTests(unittest.TestCase):
    def summarize(self, rows, code=0):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows))
            return summarize_events(path, code)

    def test_only_completed_matching_session_and_zero_exit_succeed(self):
        self.assertTrue(self.summarize(events())["completed"])
        for code in (1, 137, None):
            self.assertFalse(self.summarize(events(), code)["completed"])
        for reason in ({"kind": "aborted"}, {"kind": "error", "code": "QUOTA"}):
            self.assertFalse(self.summarize(events(reason=reason))["completed"])

    def test_api_error_is_integration_failure_even_with_success_prose(self):
        status = self.summarize(events({"type": "error", "code": "AUTHENTICATION"}))
        self.assertFalse(status["completed"])
        self.assertEqual(status["error_codes"], ["AUTHENTICATION"])

    def test_missing_final_and_wrong_session_cannot_succeed(self):
        self.assertFalse(self.summarize(events()[:-1])["completed"])
        rows = events()
        rows[-1]["sessionId"] = "other"
        self.assertFalse(self.summarize(rows)["completed"])
        self.assertFalse(self.summarize([])["completed"])
        self.assertFalse(self.summarize(events() + [events()[-1]])["completed"])
        self.assertFalse(self.summarize(events() + [{"type": "status"}])["completed"])

    def test_truncated_tools_are_reported_not_treated_as_full_trajectory(self):
        status = self.summarize(events({"type": "tool_result", "truncated": True}))
        self.assertTrue(status["completed"])
        self.assertEqual(status["truncated_event_count"], 1)
        self.assertIn("unknown", status["usage_status"])

    def test_malformed_ndjson_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("not json\n" + "\n".join(map(json.dumps, events())))
            status = summarize_events(path, 0)
            self.assertFalse(status["completed"])
            self.assertEqual(status["malformed_event_lines"], 1)


class ProfileTests(unittest.TestCase):
    def test_fixed_model_no_secret_no_external_uploads(self):
        rows = {row["id"]: row for row in build_profile(DshOptions(), "/logs/agent")}
        route = rows["llm-pi-ai"]["config"]["providers"]["kimi-benchmark"]
        self.assertEqual(route["apiKeyEnv"], "KIMI_API_KEY")
        self.assertNotIn("apiKey", route)
        self.assertNotIn("headers", route)
        self.assertTrue(USER_AGENT.startswith("deepseek-harness/"))
        self.assertNotIn("claude", USER_AGENT.lower())
        self.assertEqual(route["models"][0]["id"], "k3.1-pro")
        self.assertEqual(route["models"][0]["contextWindow"], 262144)
        self.assertEqual(route["reasoning"], "high")
        self.assertEqual(rows["agent-default-model"]["config"], {
            "provider": "kimi-benchmark", "model": "k3.1-pro", "reasoningEffort": "high"})
        for key in ("session-log-deepseek", "session-telemetry-otel", "otel",
                    "credentials", "deepseek-account", "llm-deepseek"):
            self.assertTrue(rows[key]["disabled"])
        self.assertEqual(rows["session-persistence-jsonl"]["config"]["compression"], "none")

    def test_deepseek_uses_native_transport_with_fixed_effort_and_catalog(self):
        options = DshOptions(provider="deepseek", base_url="https://api.deepseek.com/anthropic")
        rows = {row["id"]: row for row in build_profile(options, "/logs/agent")}
        self.assertEqual(rows["agent-default-model"]["config"], {
            "provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "high"})
        transport = rows["llm-deepseek"]
        self.assertFalse(transport["disabled"])
        config = transport["config"]
        self.assertEqual(config["apiKeyEnv"], "DEEPSEEK_API_KEY")
        self.assertEqual(config["baseURL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(config["thinking"], "enabled")
        self.assertEqual(config["reasoningEffort"], "high")
        self.assertEqual(config["defaultContextWindow"], 1048576)
        self.assertEqual(config["maxTokens"], 32768)
        self.assertEqual(config["models"], [{
            "id": "deepseek-flash", "contextWindow": 1048576,
            "maxTokens": 32768, "inputModalities": ["text", "image"],
            "systemPromptUpdate": "in-history", "toolUpdate": "addition-only"}])
        self.assertEqual(config["retryPolicy"]["maxRetries"], 0)
        for unsupported in ("protocol", "api", "headers", "apiKey"):
            self.assertNotIn(unsupported, config)
        for key in ("llm-pi-ai", "llm-deepseek-account", "credentials",
                    "deepseek-account", "session-log-deepseek", "session-telemetry-otel",
                    "otel", "plugin-package-inventory-deepseek", "session-title-llm",
                    "web-search-deepseek", "settings"):
            self.assertTrue(rows[key]["disabled"])
        self.assertNotIn("KIMI_API_KEY", json.dumps(rows))

    def test_no_unpinned_version_endpoint_or_cross_provider_route(self):
        for options in ({"version": "latest"}, {"base_url": "https://example.com"},
                        {"provider": "other"}, {"model_api": "openai-completions"},
                        {"provider": "deepseek"},
                        {"provider": "kimi", "base_url": "https://api.deepseek.com/anthropic"},
                        {"provider": "deepseek", "base_url": "https://api.kimi.com/coding"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                DshOptions(**options)

    def test_harbor_factory_import_path_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = AgentFactory.create_agent_from_config(
                AgentConfig(import_path="dsh_agent:DeepSeekHarness", model_name="k3.1-pro",
                            kwargs={"version": DSH_VERSION}), logs_dir=Path(tmp))
            self.assertIsInstance(agent, DeepSeekHarness)
            self.assertFalse(agent.capabilities.atif)
            self.assertEqual(agent.options.version, DSH_VERSION)
            with self.assertRaises(ValueError):
                DeepSeekHarness(logs_dir=Path(tmp), model_name="other")

    def test_harbor_factory_deepseek_route_and_model_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = {"version": DSH_VERSION, "provider": "deepseek",
                      "base_url": "https://api.deepseek.com/anthropic",
                      "model_api": "anthropic-messages"}
            agent = AgentFactory.create_agent_from_config(
                AgentConfig(import_path="dsh_agent:DeepSeekHarness", model_name="deepseek-flash",
                            kwargs=kwargs), logs_dir=Path(tmp))
            self.assertEqual(agent.options.route.credential_env, "DEEPSEEK_API_KEY")
            self.assertFalse(agent.capabilities.atif)
            with self.assertRaises(ValueError):
                DeepSeekHarness(logs_dir=Path(tmp), model_name="k3.1-pro", **kwargs)
            with self.assertRaises(ValueError):
                DeepSeekHarness(logs_dir=Path(tmp), model_name="deepseek-flash")


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_never_executes_model(self):
        for provider, route in ROUTES.items():
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as tmp:
                other_key = "KIMI_API_KEY" if provider == "deepseek" else "DEEPSEEK_API_KEY"
                agent = DeepSeekHarness(
                    logs_dir=Path(tmp), model_name=route.model, provider=provider,
                    base_url=route.base_url,
                    extra_env={route.credential_env: "", other_key: "wrong-provider-key"})
                environment = SimpleNamespace(exec=AsyncMock())
                with self.assertRaisesRegex(DshIntegrationError, route.credential_env):
                    await agent.run("task", environment, AgentContext())
                environment.exec.assert_not_awaited()

    async def test_success_captures_exit_and_unknown_usage(self):
        for provider in ROUTES:
            with self.subTest(provider=provider):
                await self.check_run(0, events(), expected_error=False, provider=provider)

    async def test_provider_rejection_keeps_failure_separate_from_score(self):
        for provider in ROUTES:
            with self.subTest(provider=provider):
                await self.check_run(1, events(reason={"kind": "error", "code": "AUTHENTICATION"}),
                                     expected_error=True, provider=provider)

    async def check_run(self, code, rows, expected_error, provider):
        with tempfile.TemporaryDirectory() as tmp:
            route = ROUTES[provider]
            other_key = "KIMI_API_KEY" if provider == "deepseek" else "DEEPSEEK_API_KEY"
            agent = DeepSeekHarness(logs_dir=Path(tmp), model_name=route.model,
                                    provider=provider, base_url=route.base_url,
                                    extra_env={route.credential_env: "test-not-a-real-key",
                                               other_key: "wrong-provider-key"})
            async def download(_source, target):
                Path(target).write_text("\n".join(map(json.dumps, rows)))
            environment = SimpleNamespace(
                exec=AsyncMock(return_value=SimpleNamespace(return_code=code)),
                download_file=AsyncMock(side_effect=download))
            context = AgentContext()
            with patch.object(agent, "exec_as_agent", new=AsyncMock()), \
                    patch.object(agent, "_upload_text", new=AsyncMock()) as upload:
                if expected_error:
                    with self.assertRaises(DshIntegrationError):
                        await agent.run("literal $(no-shell-expansion)", environment, context)
                else:
                    await agent.run("literal $(no-shell-expansion)", environment, context)
            call = environment.exec.call_args.kwargs
            self.assertNotIn("test-not-a-real-key", call["command"])
            self.assertNotIn("$(no-shell-expansion)", call["command"])
            self.assertIn("--approval-policy never", call["command"])
            self.assertEqual(call["env"]["DSH_TELEMETRY_DISABLED"], "1")
            self.assertEqual(call["env"]["DSH_HOME"], "/logs/agent/dsh-home")
            self.assertEqual(call["env"][route.credential_env], "test-not-a-real-key")
            self.assertNotIn(other_key, call["env"])
            for call_upload in upload.call_args_list:
                self.assertNotIn("test-not-a-real-key", call_upload.args[2])
                self.assertNotIn("wrong-provider-key", call_upload.args[2])
            self.assertEqual(context.metadata["dsh"]["process_exit_code"], code)
            self.assertEqual(context.metadata["dsh"]["provider"], provider)
            self.assertEqual(context.metadata["dsh"]["model"], route.model)
            self.assertEqual(context.metadata["dsh"]["base_url"], route.base_url)
            self.assertEqual(context.metadata["dsh"]["context_window"], route.context_window)
            self.assertIsNone(context.n_input_tokens)
            self.assertIsNone(context.cost_usd)
            self.assertTrue((Path(tmp) / "dsh-status.json").exists())


if __name__ == "__main__":
    unittest.main()
