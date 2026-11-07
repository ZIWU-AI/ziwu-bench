import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cleanup import cleanup


def test_cleanup_attempts_both_roles_even_when_one_fails(tmp_path):
    directory = tmp_path / 'trial/comparison/fixture__id/native-lifecycle'
    directory.mkdir(parents=True)
    for role in ('agent', 'verifier'):
        (directory / (role + '.json')).write_text(json.dumps({'sandbox_id': role}))
    agent = SimpleNamespace(terminate=Mock(side_effect=RuntimeError('transient')), poll=Mock())
    verifier = SimpleNamespace(terminate=Mock(), poll=Mock(return_value=137))
    with patch('cleanup.modal.Sandbox.from_id', side_effect=lambda name: {'agent': agent, 'verifier': verifier}[name]):
        with pytest.raises(RuntimeError, match='agent'):
            cleanup(tmp_path, timeout=0)
    verifier.terminate.assert_called_once()
    assert json.loads((directory / 'verifier.json').read_text())['cleanup_confirmed'] is True
    assert json.loads((directory / 'agent.json').read_text())['cleanup_confirmed'] is False
