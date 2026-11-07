import json
import subprocess
from calibration import identity, calibration


def test_calibration_does_not_transfer_to_changed_evaluation_code(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, stderr=subprocess.DEVNULL).decode().strip()
    git('init')
    task = tmp_path / 'task'
    (task / 'environment').mkdir(parents=True)
    (task / 'environment/Dockerfile').write_text('FROM example\n')
    (task / 'README.md').write_text('documentation\n')
    def commit():
        git('add', 'task')
        git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
        return git('rev-parse', 'HEAD')
    first = commit()
    evidence = tmp_path / 'calibration.json'
    evidence.write_text(json.dumps({'status':'passed', 'evaluation_tree_sha256':identity(tmp_path, first, 'task')}))
    (task / 'README.md').write_text('new documentation\n')
    docs = commit()
    assert calibration(tmp_path, docs, 'task', evidence)['status'] == 'passed'
    assert calibration(tmp_path, docs, 'task', evidence, {"memory_mib":65536})['status'] == 'different_runtime'
    (task / 'environment/Dockerfile').write_text('FROM changed-engine\n')
    changed = commit()
    assert calibration(tmp_path, changed, 'task', evidence)['status'] == 'different_evaluation_tree'
