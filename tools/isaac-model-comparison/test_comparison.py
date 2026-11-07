import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matrix import matrix
from profiles import route_for
from aggregate import aggregate
from harness_common import classify


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


if __name__ == "__main__":unittest.main()
