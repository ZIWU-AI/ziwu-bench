import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matrix import matrix
from profiles import route_for
from aggregate import aggregate
from harness_common import classify, job_config, make_preflight


class ComparisonTests(unittest.TestCase):
    def test_matrix_preserves_exact_models_and_harnesses(self):
        self.assertEqual(len(matrix()["include"]), 11)
        self.assertEqual(len(matrix("kimi")["include"]), 4)
        self.assertEqual(matrix("sol")["include"], [{"profile": "sol", "harness": "codex"}])
        with self.assertRaises(ValueError): matrix("opus", "kimi-code")

    def test_frontier_has_no_implicit_relay_or_substitution(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):route_for("astra", "codex", directory)
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"FRONTIER_OPENAI_BASE_URL":"https://example.invalid/v1"}):
            route=route_for("sol", "codex", directory)
            self.assertEqual(route["model_name"], "gpt-6-sol")
            self.assertNotIn("secret", (Path(directory)/"codex-frontier.toml").read_text())

    def test_errors_and_absent_rows_never_become_zero(self):
        self.assertEqual(classify({"exception_info":{"exception_type":"AgentTimeoutError"},"verifier_result":{"rewards":{"reward":0}}}), ("budget_exhausted",None))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);aggregate(root,root/"out","kimi","all")
            rows=json.loads((root/"out/comparison.json").read_text())
            self.assertEqual(len(rows),4)
            self.assertTrue(all(r["reward"] is None for r in rows))

    def test_codex_prefix_override_survives_harbor_config_resolution(self):
        from harbor.models.job.config import JobConfig
        from harbor.utils.env import resolve_env_vars

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "FRONTIER_OPENAI_BASE_URL": "https://example.invalid/v1",
            "NPM_CONFIG_PREFIX": "/home/agent/.local",
        }):
            root = Path(directory)
            for profile, harness in (("kimi", "codex"), ("deepseek", "codex"),
                                     ("astra", "codex"), ("sol", "codex"),
                                     ("kimi", "claude-code")):
                with self.subTest(profile=profile, harness=harness):
                    route = route_for(profile, harness, root)
                    cfg = JobConfig.model_validate(job_config(route, root, root, "check", "test-key", 300))
                    effective = resolve_env_vars(cfg.agents[0].env)
                    if harness == "codex":
                        self.assertEqual(effective["NPM_CONFIG_PREFIX"], "")
                    else:
                        self.assertNotIn("NPM_CONFIG_PREFIX", effective)
                    self.assertEqual(effective[route["credential_env_names"][0]], "test-key")
                    self.assertNotIn("NPM_CONFIG_PREFIX", route["env"])

    def test_preflight_covers_native_agent_user_and_npm_prefix(self):
        from harbor.models.task.config import TaskConfig
        import tomllib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "preflight"
            make_preflight(root)
            cfg = TaskConfig.model_validate(tomllib.loads((root / "task.toml").read_text()))
            self.assertEqual(cfg.agent.user, "agent")
            self.assertEqual(cfg.verifier.user, "root")
            dockerfile = (root / "environment/Dockerfile").read_text()
            self.assertIn("ENV NPM_CONFIG_PREFIX=/home/agent/.local", dockerfile)
            self.assertIn("chown agent:agent /app", dockerfile)


if __name__ == "__main__":unittest.main()
