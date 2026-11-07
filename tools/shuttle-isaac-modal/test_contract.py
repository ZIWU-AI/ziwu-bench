"""CPU checks for the preserved scientific contract and deployment boundaries."""
import ast
import hashlib
import json
from pathlib import Path
import tomllib
import unittest

ROOT=Path(__file__).resolve().parents[2]
TASK=ROOT/'tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac'

class ContractTests(unittest.TestCase):
    def test_source_experiments_are_unchanged(self):
        source=json.loads((TASK/'authoring/source.json').read_text())
        self.assertEqual(source['source_sha'],'6a5f992804f0f9b63da5eb57aeacdc7371a2e385')
        files=source['unchanged_source_data_sha256']
        self.assertEqual(len(files),28) # 5 bench records, 20 public cases, 3 hidden-set files
        for name,digest in files.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((TASK/name).read_bytes()).hexdigest(),digest)
        cases=json.loads((TASK/'tests/verification/hidden_instances.json').read_text())
        split=json.loads((TASK/'tests/verification/split.json').read_text())
        self.assertEqual(len(cases),48)
        self.assertEqual(split['required'],47)
        self.assertEqual(len({c['instance_id'] for c in cases}),48)

    def test_probe_and_verifier_share_physics_and_isolation(self):
        for name in ['plant.py','runtime.py','episode.py','scoring.py','station.json',
                     'controller_runtime.py','controller_worker.py']:
            with self.subTest(file=name):
                self.assertEqual((TASK/'environment/sim'/name).read_bytes(),
                                 (TASK/'tests/sim'/name).read_bytes())

    def test_no_mujoco_execution_in_native_bundle(self):
        for folder in ['environment/sim','tests/sim']:
            for path in (TASK/folder).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node,ast.Import):
                        self.assertFalse(any(x.name.split('.')[0]=='mujoco' for x in node.names),str(path))
                    if isinstance(node,ast.ImportFrom):
                        self.assertNotEqual((node.module or '').split('.')[0],'mujoco',str(path))

    def test_fresh_verifier_and_hard_resource_contract(self):
        c=tomllib.loads((TASK/'task.toml').read_text())
        self.assertEqual(c['artifacts'],['/app/controller.py'])
        self.assertEqual(c['agent']['user'],'agent')
        self.assertEqual(c['verifier']['environment_mode'],'separate')
        self.assertEqual(c['verifier']['environment']['network_mode'],'no-network')
        for config in [c['environment'],c['verifier']['environment']]:
            self.assertEqual((config['cpus'],config['memory_mb'],config['gpus'],config['gpu_types']),
                             (4,16384,1,['A10']))
        agent=(TASK/'environment/Dockerfile').read_text()
        for forbidden in ['COPY tests','COPY solution','COPY verification']:
            self.assertNotIn(forbidden,agent)

if __name__=='__main__':unittest.main()
