"""No-network unit doubles for adapter overlay selection; not a Harbor GPU run."""
import asyncio,hashlib,importlib.util,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class AdapterTests(unittest.TestCase):
    def test_from_id_immutable_overlay_and_hash_rejection(self):
        calls={}
        class Image:
            @classmethod
            def from_id(cls,id):calls['image_id']=id;return cls()
            def env(self,env):return self
            def run_commands(self,*cmd):calls.setdefault('commands',[]).extend(cmd);return self
            def add_local_dir(self,source,destination,copy=False):calls.update(destination=destination,copy=copy);return self
        async def lookup(*args,**kwargs):return 'APP-TEST'
        class Direct:
            def __init__(self,env):self._env=env
        stub=types.ModuleType('harbor.environments.modal');stub.ModalEnvironment=object;stub._ModalDirect=Direct
        modal=types.ModuleType('modal');modal.Image=Image;modal.App=types.SimpleNamespace(lookup=types.SimpleNamespace(aio=lookup))
        with patch.dict(sys.modules,{'harbor.environments.modal':stub,'modal':modal}),patch('importlib.metadata.version',return_value='0.21.0'):
            spec=importlib.util.spec_from_file_location('adapter_under_test',ROOT/'harbor_image_adapter.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);payload=directory/'payload';payload.mkdir();(payload/'test.sh').write_text('true\n')
            digest=hashlib.sha256(b'true\n').hexdigest();(directory/'roboindustrial-image.json').write_text(json.dumps({'destination':'/tests','files':{'test.sh':digest}}))
            async def create(**kwargs):calls['create']=kwargs;return 'SANDBOX-TEST'
            async def ensure(dirs):calls['dirs']=dirs
            env=types.SimpleNamespace(environment_dir=directory,_ri_image_id='im-TEST',_app_name='roboindustrial-isaac',_create_sandbox=create,ensure_dirs=ensure,_mount_targets=lambda **kw:['/logs/verifier'],task_env_config=types.SimpleNamespace(workdir=None))
            strategy=m._ExistingImageDirect(env);asyncio.run(strategy.start(False))
            self.assertEqual(calls['image_id'],'im-TEST');self.assertTrue(calls['copy']);self.assertEqual(calls['destination'],'/tests')
            self.assertFalse(any('venv' in c for c in calls['commands']))
            (payload/'test.sh').write_text('changed\n')
            with self.assertRaises(Exception):asyncio.run(strategy.start(False))
            (payload/'test.sh').write_text('true\n')
            req=payload/'planner-requirements.txt';req.write_text('mujoco==3.3.7\nnumpy==2.2.6\nscipy==1.15.3\n')
            files={'test.sh':digest,req.name:hashlib.sha256(req.read_bytes()).hexdigest()}
            manifest=directory/'roboindustrial-image.json';manifest.write_text(json.dumps({'destination':'/app','files':files}))
            asyncio.run(strategy.start(False))
            self.assertIn('/workspace/miniconda3/envs/RoboDojo/bin/python -m venv /app/planner-venv',calls['commands'])
            self.assertTrue(any('/app/planner-venv/bin/python -m pip install' in c for c in calls['commands']))
            manifest.write_text(json.dumps({'destination':'/tests','files':files}))
            with self.assertRaisesRegex(Exception,'forbidden'):asyncio.run(strategy.start(False))
            req.write_text('mujoco==3.8.0\nnumpy==2.2.6\nscipy==1.15.3\n');files[req.name]=hashlib.sha256(req.read_bytes()).hexdigest()
            manifest.write_text(json.dumps({'destination':'/app','files':files}))
            with self.assertRaisesRegex(Exception,'approved'):asyncio.run(strategy.start(False))

if __name__=='__main__':unittest.main()
