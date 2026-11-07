"""Static controller contract tests using an in-memory filesystem."""
import hashlib
import json
import sys
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_native_task as check


class MemoryPath:
    files = {}
    links = set()

    def __init__(self, value):
        self.path = PurePosixPath(str(value).replace('\\', '/'))

    def __truediv__(self, other):
        return MemoryPath(self.path / str(other).replace('\\', '/'))

    def __eq__(self, other):
        return isinstance(other, MemoryPath) and self.path == other.path

    def __hash__(self):
        return hash(self.path)

    @property
    def name(self):
        return self.path.name

    @property
    def parents(self):
        return [MemoryPath(p) for p in self.path.parents]

    def resolve(self):
        return self

    def is_relative_to(self, other):
        return self.path.is_relative_to(other.path)

    def relative_to(self, other):
        return self.path.relative_to(other.path)

    def is_symlink(self):
        return str(self.path) in self.links

    def is_file(self):
        return str(self.path) in self.files

    def is_dir(self):
        prefix = str(self.path).rstrip('/') + '/'
        return any(p.startswith(prefix) for p in self.files)

    def exists(self):
        return self.is_file() or self.is_dir() or self.is_symlink()

    def read_bytes(self):
        try:
            return self.files[str(self.path)]
        except KeyError:
            raise FileNotFoundError(str(self.path)) from None

    def read_text(self, encoding=None):
        return self.read_bytes().decode(encoding or 'utf-8')

    def rglob(self, pattern):
        assert pattern == '*'
        prefix = str(self.path).rstrip('/') + '/'
        paths = set()
        for name in set(self.files) | self.links:
            if name.startswith(prefix):
                p = PurePosixPath(name)
                paths.add(p)
                paths.update(parent for parent in p.parents
                             if str(parent).startswith(prefix))
        return [MemoryPath(p) for p in sorted(paths)]


class ControllerNativeTaskTests(unittest.TestCase):
    root = '/virtual/align-blocks-isaac'

    def setUp(self):
        MemoryPath.files = {}
        MemoryPath.links = set()
        self.path_patch = patch.object(check, 'Path', MemoryPath)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.put('task.toml', '''schema_version = "1.4"
artifacts = ["/app/controller.py"]
[task]
name = "terminal-bench-science/align-blocks-isaac"
[verifier]
environment_mode = "separate"
[verifier.environment]
network_mode = "no-network"
gpus = 1
gpu_types = ["L40S"]
[environment]
validate_env = "modal"
gpus = 1
gpu_types = ["L40S"]
''')
        for phase in ('environment', 'tests'):
            for name in ('isaac_scene.py', 'controller_runtime.py', 'sim/predicates.py'):
                self.put(f'{phase}/payload/{name}', name)
        self.put('environment/payload/public_rollout.py', 'public rollout')
        self.put('environment/payload/sim/schemas.json', '{}')
        self.put('environment/payload/sim/scene.xml', 'generic public scene')
        for case in check.PUBLIC_CASES:
            self.put_json(f'environment/payload/instances/{case}/instance.json', {'instance_id': case})
        for case in check.HIDDEN_CASES:
            self.put_json(f'tests/payload/sim/heldout_instances/{case}/instance.json', {'instance_id': case})
            self.put(f'tests/payload/sim/heldout_instances/{case}/scene.xml', 'hidden scene ' + case)
        self.put_json('tests/payload/sim/heldout_split_manifest.json', {
            'episodes': {case: {} for case in sorted(check.HIDDEN_CASES)}})
        for name in ('native_worker.py', 'verify.py', 'harbor_verify.py', 'sim/hidden_spec.json'):
            self.put(f'tests/payload/{name}', 'private ' + name)
        self.put('tests/payload/test.sh', 'run verifier\n')
        self.put('tests/test.sh', 'run verifier\n')
        for phase in ('environment', 'tests'):
            ids = check.PUBLIC_CASES if phase == 'environment' else check.HIDDEN_CASES
            prefix = f'{self.root}/{phase}/payload/'
            registered = {path[len(prefix):]: hashlib.sha256(data).hexdigest()
                          for path, data in MemoryPath.files.items() if path.startswith(prefix)}
            registration = {
                'task_id': 'align-blocks-isaac', 'task_version': 'v1',
                'worker_timeout_sec': 900,
                'task_spec': {
                    'controller_schema': check.CONTROLLER_SCHEMA,
                    'api_version': check.CONTROLLER_API, 'status': 'implemented',
                    'engine': 'isaac-physx', 'case_ids': sorted(ids),
                    'entrypoint': 'public_rollout.py' if phase == 'environment' else 'native_worker.py',
                    'files': registered, 'requires_gpu_physics': False,
                },
            }
            self.put_json(f'{phase}/payload/registration.json', registration)
        self.rehash()

    def put(self, rel, value):
        MemoryPath.files[f'{self.root}/{rel}'] = value.encode() if isinstance(value, str) else value

    def put_json(self, rel, value):
        self.put(rel, json.dumps(value, sort_keys=True))

    def get_json(self, rel):
        return json.loads(MemoryPath.files[f'{self.root}/{rel}'])

    def hash_file(self, rel):
        return hashlib.sha256(MemoryPath.files[f'{self.root}/{rel}']).hexdigest()

    def rehash(self):
        for phase, destination in (('environment', '/app'), ('tests', '/tests')):
            prefix = f'{self.root}/{phase}/payload/'
            files = {path[len(prefix):]: hashlib.sha256(data).hexdigest()
                     for path, data in MemoryPath.files.items() if path.startswith(prefix)}
            self.put_json(f'{phase}/roboindustrial-image.json', {
                'destination': destination, 'files': files})

    def edit_registration(self, phase, edit):
        rel = f'{phase}/payload/registration.json'
        registration = self.get_json(rel)
        edit(registration)
        self.put_json(rel, registration)
        self.rehash()

    def assert_rejected(self):
        with self.assertRaises((ValueError, check.InfrastructureError, KeyError, TypeError)):
            check.validate_native_task(self.root)

    def test_controller_contract(self):
        result = check.validate_native_task(self.root)
        self.assertEqual(result['task_id'], 'align-blocks-isaac')
        self.assertEqual(len(result['task_spec']['case_ids']), 12)
        self.assertEqual(len(check.HIDDEN_CASES), 60)
        self.assertIn('public_square_00', result['task_spec']['case_ids'])
        self.assertIn('hidden_square_23', check.HIDDEN_CASES)

    def test_artifact_and_slug_do_not_enable_other_tasks(self):
        data = MemoryPath.files[f'{self.root}/task.toml']
        self.put('task.toml', data.replace(b'/app/controller.py', b'/app/output/submission.json'))
        self.assert_rejected()
        self.put('task.toml', data.replace(b'environment_mode = "separate"',
                                         b'environment_mode = "separate"\nartifacts = ["/app/other"]'))
        self.assert_rejected()
        self.put('task.toml', data.replace(b'terminal-bench-science/align-blocks-isaac',
                                         b'terminal-bench-science/other-task'))
        self.assert_rejected()
        self.put('task.toml', data)
        other = '/virtual/other-task'
        MemoryPath.files = {p.replace(self.root, other, 1): v for p, v in MemoryPath.files.items()}
        with self.assertRaises(ValueError):
            check.validate_native_task(other)

    def test_phase_ids_and_identity_files_are_enforced(self):
        self.edit_registration('environment', lambda r: r['task_spec']['case_ids'].__setitem__(0, sorted(check.HIDDEN_CASES)[0]))
        self.assert_rejected()
        self.setUpFresh()
        self.edit_registration('tests', lambda r: r['task_spec']['case_ids'].__setitem__(0, r['task_spec']['case_ids'][1]))
        self.assert_rejected()
        self.setUpFresh()
        case = sorted(check.HIDDEN_CASES)[0]
        rel = f'sim/heldout_instances/{case}/instance.json'
        self.put_json(f'tests/payload/{rel}', {'instance_id': 'other'})
        self.edit_registration('tests', lambda r: r['task_spec']['files'].__setitem__(rel, self.hash_file(f'tests/payload/{rel}')))
        self.assert_rejected()
        self.setUpFresh()
        self.put_json('tests/payload/sim/heldout_split_manifest.json', {'episodes': {}})
        self.edit_registration('tests', lambda r: r['task_spec']['files'].__setitem__(
            'sim/heldout_split_manifest.json', self.hash_file('tests/payload/sim/heldout_split_manifest.json')))
        self.assert_rejected()

    def setUpFresh(self):
        self.path_patch.stop()
        self.setUp()

    def test_no_private_content_in_public_overlay(self):
        rel = 'environment/payload/extra.py'
        self.put(rel, 'unapproved public content')
        self.edit_registration('environment', lambda r: r['task_spec']['files'].__setitem__('extra.py', self.hash_file(rel)))
        self.assert_rejected()
        self.setUpFresh()
        rel = 'environment/payload/public_rollout.py'
        self.put(rel, 'source ' + sorted(check.HIDDEN_CASES)[0])
        self.edit_registration('environment', lambda r: r['task_spec']['files'].__setitem__('public_rollout.py', self.hash_file(rel)))
        self.assert_rejected()
        self.setUpFresh()
        self.put('environment/payload/sim/hidden_spec.json', 'private')
        self.rehash()
        self.assert_rejected()
        self.setUpFresh()
        rel = 'environment/payload/public_rollout.py'
        self.put(rel, MemoryPath.files[f'{self.root}/tests/payload/verify.py'])
        self.edit_registration('environment', lambda r: r['task_spec']['files'].__setitem__('public_rollout.py', self.hash_file(rel)))
        self.assert_rejected()
        self.setUpFresh()
        case = sorted(check.PUBLIC_CASES)[0]
        rel = f'instances/{case}/scene.xml'
        self.put(f'environment/payload/{rel}', 'latent per-case scene')
        self.edit_registration('environment', lambda r: r['task_spec']['files'].__setitem__(
            rel, self.hash_file(f'environment/payload/{rel}')))
        self.assert_rejected()
        self.setUpFresh()
        case = sorted(check.HIDDEN_CASES)[0]
        rel = 'environment/payload/sim/scene.xml'
        self.put(rel, MemoryPath.files[f'{self.root}/tests/payload/sim/heldout_instances/{case}/scene.xml'])
        self.edit_registration('environment', lambda r: r['task_spec']['files'].__setitem__(
            'sim/scene.xml', self.hash_file(rel)))
        self.assert_rejected()

    def test_hash_paths_and_symlinks(self):
        self.put('tests/payload/verify.py', 'changed without new hash')
        self.assert_rejected()
        self.setUpFresh()
        manifest = self.get_json('tests/roboindustrial-image.json')
        manifest['files']['../escape'] = '0' * 64
        self.put_json('tests/roboindustrial-image.json', manifest)
        self.assert_rejected()
        self.setUpFresh()
        self.put('environment/payload/unregistered', 'extra')
        self.assert_rejected()
        self.setUpFresh()
        MemoryPath.links.add(f'{self.root}/tests/payload/sim/heldout_instances')
        self.assert_rejected()
        self.setUpFresh()
        MemoryPath.links.add(f'{self.root}/tests/payload/empty-link')
        self.assert_rejected()

    def test_network_resource_and_registration_guards(self):
        original = MemoryPath.files[f'{self.root}/task.toml']
        for source, target in (
            (b'validate_env = "modal"', b'validate_env = "docker"'),
            (b'network_mode = "no-network"', b'network_mode = "public"'),
            (b'gpu_types = ["L40S"]', b'gpu_types = ["A100"]'),
            (b'environment_mode = "separate"', b'environment_mode = "shared"'),
        ):
            self.put('task.toml', original.replace(source, target, 1))
            self.assert_rejected()
        self.put('task.toml', original.replace(b'environment_mode = "separate"',
                                             b'environment_mode = "separate"\nnetwork_mode = "public"'))
        self.assert_rejected()
        self.put('task.toml', original)
        for key, value in (('requires_gpu_physics', True), ('api_version', 'other'),
                           ('controller_schema', 'numerical'), ('engine', 'mujoco')):
            self.edit_registration('tests', lambda r: r['task_spec'].__setitem__(key, value))
            self.assert_rejected()
            self.setUpFresh()
        for value in (True, 0, 1801):
            self.edit_registration('tests', lambda r: r.__setitem__('worker_timeout_sec', value))
            self.assert_rejected()
            self.setUpFresh()
        self.edit_registration('tests', lambda r: r.__setitem__('task_version', 'other'))
        self.assert_rejected()

    def test_entrypoint_and_manifest_must_remain_bound(self):
        self.edit_registration('tests', lambda r: r['task_spec']['files'].__setitem__('native_worker.py', '0' * 64))
        self.assert_rejected()
        self.setUpFresh()
        self.edit_registration('tests', lambda r: r['task_spec'].__setitem__('entrypoint', 'other.py'))
        self.assert_rejected()
        self.setUpFresh()
        manifest = self.get_json('environment/roboindustrial-image.json')
        manifest['schema'] = check.CONTROLLER_SCHEMA
        self.put_json('environment/roboindustrial-image.json', manifest)
        self.assert_rejected()
        self.setUpFresh()
        self.put('environment/payload/registration.json', '{"task_id":"a","task_id":"b"}')
        self.rehash()
        self.assert_rejected()
        self.setUpFresh()
        self.put('tests/test.sh', 'different')
        self.assert_rejected()
        self.setUpFresh()
        self.put('tests/payload/isaac_scene.py', 'different API')
        self.edit_registration('tests', lambda r: r['task_spec']['files'].__setitem__(
            'isaac_scene.py', self.hash_file('tests/payload/isaac_scene.py')))
        self.assert_rejected()

    def test_existing_numerical_contract_is_unchanged(self):
        self.root = '/virtual/numerical-task'
        MemoryPath.files = {}
        self.put('task.toml', '''artifacts = ["/app/output/submission.json"]
[verifier]
environment_mode = "separate"
[verifier.environment]
network_mode = "no-network"
gpus = 1
gpu_types = ["L40S"]
[environment]
validate_env = "modal"
gpus = 1
gpu_types = ["L40S"]
''')
        for phase in ('environment', 'tests'):
            for name in ('protocol.py', 'worker.py'):
                self.put(f'{phase}/payload/{name}', name)
            self.put(f'{phase}/payload/implementation/port.py', 'numerical port')
            self.put_json(f'{phase}/payload/registration.json', {
                'task_id': 'numerical', 'task_version': 'v1', 'worker_timeout_sec': 900,
                'task_spec': {'status': 'implemented', 'engine': 'isaac-physx',
                              'case_ids': ['b0'], 'entrypoint': 'port.py:evaluate',
                              'files': {'port.py': self.hash_file(f'{phase}/payload/implementation/port.py')},
                              'requires_gpu_physics': True}})
        self.put('tests/payload/test.sh', 'run verifier\n')
        self.put('tests/test.sh', 'run verifier\n')
        self.put('tests/payload/harbor_verify.py', 'numerical verifier')
        self.rehash()
        self.assertEqual(check.validate_native_task(self.root)['task_id'], 'numerical')
        self.put('tests/payload/implementation/port.py', 'tampered')
        self.assert_rejected()
        self.put('tests/payload/implementation/port.py', 'numerical port')
        self.rehash()
        self.edit_registration('tests', lambda r: r['task_spec'].__setitem__('case_ids', ['b1']))
        self.assert_rejected()
        self.put('task.toml', MemoryPath.files[f'{self.root}/task.toml'].replace(
            b'/app/output/submission.json', b'/app/controller.py'))
        self.assert_rejected()


if __name__ == '__main__':
    unittest.main()
