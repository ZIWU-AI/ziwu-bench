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
    DSH_VERSION, USER_AGENT, DeepSeekHarness, DshIntegrationError,
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
        for key in ("session-log-deepseek", "session-telemetry-otel", "otel",
                    "credentials", "deepseek-account", "llm-deepseek"):
            self.assertTrue(rows[key]["disabled"])
        self.assertEqual(rows["session-persistence-jsonl"]["config"]["compression"], "none")

    def test_no_unpinned_version_or_different_endpoint(self):
        for options in ({"version": "latest"}, {"base_url": "https://example.com"}):
            with self.assertRaises(ValueError):
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


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_never_executes_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = DeepSeekHarness(logs_dir=Path(tmp), model_name="k3.1-pro",
                                    extra_env={"KIMI_API_KEY": ""})
            environment = SimpleNamespace(exec=AsyncMock())
            with self.assertRaises(DshIntegrationError):
                await agent.run("task", environment, AgentContext())
            environment.exec.assert_not_awaited()

    async def test_success_captures_exit_and_unknown_usage(self):
        await self.check_run(0, events(), expected_error=False)

    async def test_provider_rejection_keeps_failure_separate_from_score(self):
        await self.check_run(1, events(reason={"kind": "error", "code": "AUTHENTICATION"}),
                             expected_error=True)

    async def check_run(self, code, rows, expected_error):
        with tempfile.TemporaryDirectory() as tmp:
            agent = DeepSeekHarness(logs_dir=Path(tmp), model_name="k3.1-pro",
                                    extra_env={"KIMI_API_KEY": "test-not-a-real-key"})
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
            for call_upload in upload.call_args_list:
                self.assertNotIn("test-not-a-real-key", call_upload.args[2])
            self.assertEqual(context.metadata["dsh"]["process_exit_code"], code)
            self.assertIsNone(context.n_input_tokens)
            self.assertIsNone(context.cost_usd)
            self.assertTrue((Path(tmp) / "dsh-status.json").exists())


if __name__ == "__main__":
    unittest.main()
