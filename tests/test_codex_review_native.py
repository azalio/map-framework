"""Opt-in native Codex acceptance: actual host boundary, reports and crash recovery.

MAP_LIVE_CODEX_REVIEW=1 uv run pytest -m slow tests/test_codex_review_native.py -v
Uses the installed/authenticated Codex CLI and its configured model.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from mapify_cli import app

pytestmark = [pytest.mark.slow, pytest.mark.skipif(
    os.environ.get("MAP_LIVE_CODEX_REVIEW") != "1" or not shutil.which("codex"),
    reason="Explicit opt-in and an authenticated Codex CLI are required",
)]


@pytest.mark.parametrize("recovery,files", [(False, 62), (True, 1)], ids=["full-62-files", "recovery"])
def test_native_review_completes_with_host_proofs(tmp_path, monkeypatch, recovery, files):
    monkeypatch.chdir(tmp_path)
    installed = CliRunner().invoke(app, ["init", ".", "--provider", "codex", "--no-git", "--force", "--mcp", "none"])
    assert installed.exit_code == 0, installed.output
    (tmp_path / ".gitignore").write_text(".map/\n.agents/\n.codex/\n")
    (tmp_path / "dependency.py").write_text("OTHER = 7\n")
    for index in range(files):
        (tmp_path / f"module_{index:02d}.py").write_text("VALUE = 1\n")
    for args in [("init", "-b", "main"), ("config", "user.name", "Test"),
                 ("config", "user.email", "test@example.invalid"), ("add", "."),
                 ("commit", "-m", "base"), ("checkout", "-b", "feature")]:
        subprocess.run(["git", *args], check=True, capture_output=True)
    for index in range(files):
        (tmp_path / f"module_{index:02d}.py").write_text("VALUE = 2\n")
    task = tmp_path / ".map/feature"
    task.mkdir(parents=True, exist_ok=True)
    (task / "spec_feature.md").write_text("# Task\nSet VALUE to 2 in every module_NN.py.\n")
    (task / "task_plan_feature.md").write_text("Update the constants and verify their exact values.\n")
    # Import only the fresh installed runtime, independent of pytest's shared modules.
    harness = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('.map/scripts').resolve()))
import map_step_runner as runner
import codex_review_runner as driver
recovery = json.loads(sys.argv[1])
command = [sys.executable, '-c', "from pathlib import Path; assert all(p.read_text() == 'VALUE = 2' + chr(10) for p in Path('.').glob('module_*.py'))"]
admitted = runner.begin_review_run(branch='feature', provider='codex', round_id='native',
    mode='lightweight' if recovery else 'full', required_checks=['smoke'], check_specs={'smoke':command})
assert admitted['status'] == 'success', admitted
check = runner.run_test_gate(branch='feature', check_id='smoke')
assert check['passed'], check
assert runner.create_review_bundle(branch='feature')['status'] == 'success'
preferences = 'Requested standalone change: set VALUE to 2 in all module_NN.py files. No other behavior is intended.'
if recovery:
    original = driver.Delivery.observe
    def interrupt_after_ack(self, event):
        original(self, event)
        if self.transfers:
            raise driver.HostError('intentional interruption after durable ACK')
    driver.Delivery.observe = interrupt_after_ack
    try:
        driver.run('feature', timeout=300, review_preferences=preferences)
        raise AssertionError('Interruption did not occur')
    except driver.HostError as exc:
        assert 'intentional interruption' in str(exc), str(exc)
    finally:
        driver.Delivery.observe = original
    before = runner._read_review_ledger(Path('.map/feature'))['convergence']['rounds'][-1]
result = driver.run('feature', timeout=300, review_preferences=None if recovery else preferences)
assert result['status'] == 'success', result
if recovery:
    after = runner._read_review_ledger(Path('.map/feature'))['convergence']['rounds'][-1]
    assert before['context_active'] == after['context_active']
    for identity, old in before['context_sessions'].items():
        new = after['context_sessions'][identity]
        assert old['agent_id'] == new['agent_id']
        assert old['offsets']
        assert all(new['offsets'][name] >= offset for name, offset in old['offsets'].items())
verdict = runner.write_review_verdict_ledger(current_run=True, branch='feature')
assert verdict['completeness']['status'] == 'COMPLETE', verdict
assert verdict['code_approval']['approved'] is True, verdict
print(json.dumps({'completeness':verdict['completeness'], 'reviewers':result['reviewers']}))
'''
    result = subprocess.run([sys.executable, "-c", harness, json.dumps(recovery)],
                            text=True, capture_output=True, timeout=1800, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
