import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from config import safe_task, task_path, validate_task
from export_task import bundle
from report import report
from resolve import main as resolve

TASK = "tasks/engineering-sciences/mechanical-engineering/example"


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = self.root / TASK
        self.task.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_path_traversal_and_shell_inputs(self):
        for value in ["/etc/passwd", "tasks/../a/b", "tasks/a/b/c;id", "tasks/a/b/c\nx", "tasks/a/b/c/"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                task_path(value)
        self.assertEqual(task_path(TASK), TASK)

    def test_symlink_cannot_escape_upload_context(self):
        (self.task / "secret").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            safe_task(self.root, TASK)

    def test_unknown_task_contract_fails_before_allocation(self):
        with self.assertRaisesRegex(ValueError, "missing task.toml"):
            validate_task(self.root, TASK)

    def test_pr_source_is_pinned_to_sha(self):
        output = self.root / "outputs"
        env = {"GITHUB_OUTPUT": str(output), "TASK_PATH": TASK, "PR_NUMBER": "3",
               "TRIALS": "2", "GITHUB_REPOSITORY": "example/repository"}
        with patch.dict(os.environ, env), patch("subprocess.check_output", return_value=json.dumps({"head": {"sha": "a" * 40}})) as api:
            resolve()
        self.assertIn("source_sha=" + "a" * 40, output.read_text())
        self.assertIn("matrix=[1, 2]", output.read_text())
        self.assertEqual(api.call_args.args[0], ["gh", "api", "repos/example/repository/pulls/3"])

    def test_bad_pr_and_repeat_budget_are_rejected(self):
        for key, value in [("PR_NUMBER", "3;id"), ("TRIALS", "4"), ("TRIALS", "0")]:
            env = {"TASK_PATH": TASK, "PR_NUMBER": "0", "TRIALS": "1", key: value}
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                resolve()

    def test_report_excludes_oracle_and_recording_files(self):
        run = self.root / "run"
        (run / "oracle/recording").mkdir(parents=True)
        (run / "oracle/recording/actions.jsonl").write_text("private reference")
        (run / "oracle/recording/result.json").write_text("also private")
        (run / "oracle/policy.stdout").write_text("policy output")
        (run / "oracle/result.json").write_text('{"reward":1}')
        (run / "summary.json").write_text('{"passed":true}')
        dest = self.root / "public"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
            report(run, dest)
        self.assertTrue((dest / "oracle/result.json").exists())
        self.assertFalse((dest / "oracle/recording").exists())
        self.assertFalse((dest / "oracle/policy.stdout").exists())

    def test_incomplete_run_is_not_reported_as_pass(self):
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
            report(self.root / "missing", self.root / "report")
        self.assertIn('"passed": false', (self.root / "report/SUMMARY.md").read_text())

    def test_export_patch_applies_to_upstream_and_contains_only_task(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)
        git("init")
        git("config", "user.name", "test")
        git("config", "user.email", "test@example.invalid")
        (repo / "README.md").write_text("official base")
        git("add", ".")
        git("commit", "-m", "base")
        (self.task / "task.toml").write_text('schema_version="1.4"')
        (self.task / "instruction.md").write_text("task instructions")
        (self.task / "__pycache__").mkdir()
        (self.task / "__pycache__/bad.pyc").write_bytes(b"cache")
        output = self.root / "bundle"
        manifest = bundle(repo, self.root, TASK, "a" * 40, output, base_ref="HEAD")
        git("apply", "--check", str(output / "task.patch"))
        git("apply", "--index", str(output / "task.patch"))
        changed = git("diff", "--cached", "--name-only").decode().splitlines()
        self.assertEqual(changed, [TASK + "/instruction.md", TASK + "/task.toml"])
        self.assertEqual(manifest["source_sha"], "a" * 40)
        self.assertEqual(git("worktree", "list", "--porcelain").decode().count("worktree "), 1)


if __name__ == "__main__":
    unittest.main()
