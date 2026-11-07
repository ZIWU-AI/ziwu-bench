"""One bounded author-only GPU smoke, with unconditional cleanup."""
from pathlib import Path
import json
import modal
from image import image_for,PYTHON
ROOT=Path(__file__).resolve().parents[2]
TASK=ROOT/'tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac'
OUT=ROOT/'runs/shuttle-isaac';OUT.mkdir(parents=True,exist_ok=True)
receipt={}
with modal.enable_output():
    image=image_for(TASK/'environment').add_local_file(str(Path(__file__).with_name('smoke.py')),'/tmp/smoke.py',copy=True)
    sb=modal.Sandbox.create('sleep','infinity',image=image,app=modal.App.lookup('ziwu-shuttle-isaac',create_if_missing=True),gpu='A10',cpu=(4,4),memory=(16384,16384),cloud='oci',region='eu-west',timeout=1800,block_network=True)
    receipt.update(sandbox_id=sb.object_id,image_id=image.object_id,gpu='A10',cpu=4,memory_mb=16384)
    (OUT/'smoke-lifecycle.json').write_text(json.dumps(receipt,indent=2))
    try:
        p=sb.exec(PYTHON,'/tmp/smoke.py',timeout=1200)
        for line in p.stdout: print(line,end='',flush=True)
        code=p.wait(); print('WORKER_EXIT',code,flush=True)
        (OUT/'smoke-stderr.log').write_text(p.stderr.read())
        if code:raise RuntimeError('native worker failed')
        (OUT/'smoke-result.json').write_bytes(sb.filesystem.read_bytes('/tmp/smoke-result.json'))
    finally:
        sb.terminate();receipt['cleanup_requested']=True
        (OUT/'smoke-lifecycle.json').write_text(json.dumps(receipt,indent=2))
