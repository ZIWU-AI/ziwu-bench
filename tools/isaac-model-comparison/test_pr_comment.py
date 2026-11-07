from pr_comment import render, post
import pytest

def test_errors_are_not_scored_failures_or_zero_cost():
    rows=[{'profile':'kimi','harness':'codex','status':'execution_error','reward':0,'cost_usd':None},
          {'profile':'deepseek','harness':'codex','status':'not_passed','reward':0,'cost_usd':None}]
    text=render(rows,'123')
    assert '0% (0/1 passed)' in text
    assert '— (unscored)' in text
    assert '$0.00' not in text
    assert 'Job Analysis:** Not run' in text

def test_cost_estimate_is_not_billing():
    text=render([{'profile':'kimi','harness':'codex','status':'passed','reward':1,'cli_reported_cost_usd':1.2}], '123')
    assert '~$1.20 CLI estimate' in text
    assert 'verified billing unavailable' in text
    assert '100% (1/1 passed)' in text

def test_official_repo_comments_are_refused(tmp_path):
    with pytest.raises(ValueError,match='only in ziwu-bench'):
        post(tmp_path/'body', '123', 1, 'branch', 'harbor-framework/terminal-bench-science')
