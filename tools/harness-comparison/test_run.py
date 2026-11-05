import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

spec = importlib.util.spec_from_file_location("comparison_run", Path(__file__).with_name("run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class ReportingTests(unittest.TestCase):
    def test_preflight_checks_same_container_and_all_routes_validate(self):
        from harbor.models.job.config import JobConfig
        from harbor.models.task.config import TaskConfig
        from routes import build_route
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run.make_preflight(root / "preflight")
            task = TaskConfig.model_validate(tomllib.loads((root / "preflight/task.toml").read_text()))
            self.assertIsNone(task.verifier.environment)
            self.assertIn(task.verifier.environment_mode, (None, "shared"))
            for name in run.HARNESSES:
                route = build_route(name, root / name)
                config = JobConfig.model_validate(run.job_config(
                    route, root / "preflight", root / "jobs", name, "synthetic-credential", 300))
                self.assertEqual(config.agents[0].override_timeout_sec, 300)
                self.assertEqual(config.n_attempts, 1)
                self.assertEqual(config.retry.max_retries, 0)
                self.assertEqual(config.agents[0].model_name, "k3.1-pro")

    def test_zero_reward_is_valid_only_without_exception(self):
        good = {"verifier_result": {"rewards": {"reward": 0}}, "exception_info": None}
        self.assertEqual(run.classify(good), ("not_passed", 0))
        good["exception_info"] = {"exception_type": "AgentAuthenticationError"}
        self.assertEqual(run.classify(good), ("execution_error", None))

    def test_timeout_and_missing_reward_are_not_model_scores(self):
        self.assertEqual(run.classify({"exception_info": {"exception_type": "AgentTimeoutError"}}),
                         ("budget_exhausted", None))
        self.assertEqual(run.classify({}), ("invalid_result", None))
        self.assertEqual(run.classify({"verifier_result": {"rewards": {"reward": 0.5}}}),
                         ("invalid_result", None))

    def test_missing_matrix_job_remains_visible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run.write_json(root / "inputs/codex/summary.json", {"harness": "codex", "status": "not_passed", "reward": 0})
            run.report(root / "inputs", root / "report")
            rows = json.loads((root / "report/comparison.json").read_text())["results"]
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(row["status"] == "job_missing" for row in rows), 3)
            self.assertTrue(all(row["reward"] is None for row in rows if row["status"] == "job_missing"))

    def test_deepseek_report_is_separate_and_rejects_mixed_providers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = {"harness": "codex", "provider": "deepseek-official",
                   "model": "deepseek-flash", "status": "not_passed", "reward": 0}
            run.write_json(root / "inputs/codex/summary.json", row)
            run.report(root / "inputs", root / "report", "deepseek")
            result = json.loads((root / "report/comparison.json").read_text())
            self.assertEqual(result["model"], "deepseek-flash")
            self.assertEqual(len(result["results"]), 4)
            self.assertIn("DeepSeek official API", (root / "report/comparison.md").read_text())
            with self.assertRaisesRegex(ValueError, "mix providers"):
                run.report(root / "inputs", root / "wrong-report", "kimi")

    def test_external_codex_evidence_requires_matching_run_task_and_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_id = "42033852755"
            row = {"harness": "codex", "provider": "deepseek-official",
                   "model": "deepseek-flash", "status": "not_passed", "reward": 0,
                   "run_url": f"https://github.com/ZIWU-AI/ziwu-bench/actions/runs/{run_id}",
                   "task_tree": run.TASK_TREE, "agent_timeout_sec": 5400,
                   "harbor_version": run.HARBOR_VERSION}
            path = root / "inputs/reused-codex/summary.json"
            run.write_json(path, row)
            run.report(root / "inputs", root / "report", "deepseek", run_id)
            rows = json.loads((root / "report/comparison.json").read_text())["results"]
            self.assertEqual(next(r for r in rows if r["harness"] == "codex")["reward"], 0)
            row["agent_timeout_sec"] = 28800
            run.write_json(path, row)
            with self.assertRaisesRegex(ValueError, "does not match"):
                run.report(root / "inputs", root / "report", "deepseek", run_id)

    def test_missing_external_artifact_stays_unknown_and_mixed_models_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run.report(root / "inputs", root / "report", "deepseek", "42033852755")
            rows = json.loads((root / "report/comparison.json").read_text())["results"]
            codex = next(r for r in rows if r["harness"] == "codex")
            self.assertEqual(codex["status"], "external_result_unavailable")
            self.assertIsNone(codex["reward"])
            run.write_json(root / "inputs/other/summary.json", {
                "harness": "kimi-code", "provider": "deepseek-official", "model": "k3.1-pro"})
            with self.assertRaisesRegex(ValueError, "mix models"):
                run.report(root / "inputs", root / "report", "deepseek")

    def test_scrubber_covers_plaintext_and_removes_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "output").mkdir()
            outside = root / "outside.txt"
            outside.write_text("synthetic-credential")
            (root / "output/log.txt").write_text("header synthetic-credential tail")
            (root / "output/link.txt").symlink_to(outside)
            run.scrub_tree(root / "output", "synthetic-credential")
            self.assertEqual((root / "output/log.txt").read_text(), "header REDACTED tail")
            self.assertFalse((root / "output/link.txt").exists())
            self.assertEqual(outside.read_text(), "synthetic-credential")


if __name__ == "__main__":
    unittest.main()
