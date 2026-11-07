"""Harbor 0.23 native image cache adapter; standard healthcheck starts the service."""
import importlib.metadata
import json
from pathlib import Path
import time
import modal
from harbor.environments.modal import ModalEnvironment
from image import image_for, BASE_IMAGE

class ShuttleIsaacEnvironment(ModalEnvironment):
    def __init__(self,*args,**kwargs):
        if importlib.metadata.version('harbor')!='0.23.0':raise RuntimeError('Requires Harbor 0.23.0')
        if kwargs.get('secrets') or kwargs.get('volumes'):raise ValueError('No host secrets or shared volumes')
        super().__init__(*args,**kwargs)
        if self._compose_mode or self._vm_runtime_enabled:raise ValueError('Direct native sandboxes only')
        self._role='agent' if (self.environment_dir/'start_service.py').exists() else 'verifier'
        if self._role=='verifier' and not self._network_disabled:raise ValueError('Verifier requires no-network')

    async def _create_sandbox(self,*,entrypoint=None,block_network=None,experimental_options=None):
        if experimental_options:raise ValueError('Unregistered sandbox options')
        self._image=image_for(self.environment_dir)
        sb=await modal.Sandbox.create.aio(*(entrypoint or ['sleep','infinity']),
            app=self._app,image=self._image,gpu='A10',cpu=(4,4),memory=(16384,16384),
            cloud='oci',region='eu-west',timeout=21600,block_network=self._network_disabled)
        out=self.trial_paths.trial_dir/'native-lifecycle';out.mkdir(parents=True,exist_ok=True)
        (out/(self._role+'.json')).write_text(json.dumps({'sandbox_id':sb.object_id,
            'image_id':self._image.object_id,'base_image_id':BASE_IMAGE,'gpu':'A10',
            'cpus':4,'memory_mb':16384,'role':self._role,'started_at':time.time()},indent=2))
        return sb
