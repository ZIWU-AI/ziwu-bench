"""Contract tests for the task-specific sandbox lifetime; not native evidence."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ControllerTimeoutTests(unittest.TestCase):
    def test_lifetimes_derive_from_phase_budget(self):
        captured = []

        class ModalEnvironment:
            def __init__(self, *args, **kwargs):
                captured.append(kwargs["sandbox_timeout_secs"])
                self._compose_mode = self._vm_runtime_enabled = False
                self._sandbox_v2_enabled = False

        modal = types.ModuleType("modal")
        modal.App = modal.Image = object
        harbor = types.ModuleType("harbor.environments.modal")
        harbor.ModalEnvironment = ModalEnvironment
        harbor._ModalDirect = lambda environment: None
        with patch.dict(sys.modules, {"modal": modal, "harbor.environments.modal": harbor}), \
                patch("importlib.metadata.version", return_value="0.21.0"):
            spec = importlib.util.spec_from_file_location(
                "controller_adapter_test", ROOT / "harbor_image_adapter.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as tmp:
                task = Path(tmp) / "align-blocks-isaac"
                task.mkdir()
                (task / "task.toml").write_text(
                    'artifacts=["/app/controller.py"]\n'
                    '[task]\nname="terminal-bench-science/align-blocks-isaac"\n'
                    '[agent]\ntimeout_sec=18000\n'
                    '[verifier]\ntimeout_sec=1800\n')
                module.AlignBlocksControllerEnvironment(task / "environment")
                module.AlignBlocksControllerEnvironment(task / "tests")
                with self.assertRaises(ValueError):
                    module.AlignBlocksControllerEnvironment(
                        task / "environment", sandbox_timeout_secs=1)
        self.assertEqual(captured, [19800, 3600])


if __name__ == "__main__":
    unittest.main()
