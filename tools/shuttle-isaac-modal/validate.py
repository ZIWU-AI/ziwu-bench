"""Explicit author validation: unprivileged reference, then a fresh native verifier.

Only controller source crosses into the verifier. Source is never imported on
this credential-bearing host. No model API, GitHub comment or business volume.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import shutil
import modal
from image import image_for, PYTHON, BASE_IMAGE

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / 'tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--mode',choices=['oracle','nop'],default='oracle')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--reuse-controller',type=Path,help='Author-only replay of a previously generated candidate')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    task = out / 'frozen-task'
    shutil.copytree(TASK, task, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    receipt={'mode':args.mode,'reused_controller':bool(args.reuse_controller),'base_image':BASE_IMAGE,'gpu':'A10','cpu':4,'memory_mb':16384,'phases':[],
             'source_sha256':{str(p.relative_to(task)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(task.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}}
    def save(): (out/'lifecycle.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def launch(image,role):
        sb=modal.Sandbox.create('sleep','infinity',image=image,
            app=modal.App.lookup('ziwu-shuttle-isaac',create_if_missing=True),gpu='A10',
            cpu=(4,4),memory=(16384,16384),cloud='oci',region='eu-west',timeout=18000,
            block_network=role=='verifier')
        phase={'role':role,'sandbox_id':sb.object_id,'image_id':image.object_id,'started_at':time.time()}
        receipt['phases'].append(phase);save()
        try:
            hardware=sb.exec('nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader')
            phase['hardware']=hardware.stdout.read().strip()
            if hardware.wait()!=0:raise RuntimeError('GPU inspection failed')
            save();print('ALLOCATED '+json.dumps(phase),flush=True)
        except BaseException:
            sb.terminate();phase['cleanup_requested']=True;save()
            raise
        return sb,phase
    def execute(sb,phase,label,command,timeout):
        start=time.monotonic();p=sb.exec(*command,timeout=timeout)
        with (out/(label+'.log')).open('w') as log:
            for line in p.stdout:
                log.write(line);log.flush()
                if line.startswith(('ISAAC_','{','PASSED','FAILED')):print(line,end='',flush=True)
            log.write(p.stderr.read())
        code=p.wait();phase[label]={'exit_code':code,'seconds':time.monotonic()-start};save()
        print(label+' EXIT '+str(code),flush=True)
        if code:raise RuntimeError(label+' failed; see '+str(out/(label+'.log')))
    def stop(sb,phase):
        sb.terminate();phase.update(cleanup_requested=True,ended_at=time.time());save()
    if args.reuse_controller:
        candidate=args.reuse_controller.read_bytes()
    elif args.mode=='nop':
        candidate=b'class Controller:\n def __init__(self, instance): pass\n def step(self, observation): return [0.0, 0.0]\n'
    else:
        image=image_for(task/'environment').add_local_dir(str(task/'solution'),'/solution',copy=True)
        sb,phase=launch(image,'oracle')
        try:
            execute(sb,phase,'startup',[PYTHON,'/opt/start_shuttle_service.py'],660)
            execute(sb,phase,'oracle',['su','-s','/bin/bash','agent','-c','export PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; cd /app && bash /solution/solve.sh'],7200)
            candidate=sb.filesystem.read_bytes('/app/controller.py')
            (out/'controller.py').write_bytes(candidate) # private local evidence, not publication
            (out/'probe-usage.json').write_bytes(sb.filesystem.read_bytes('/var/shuttle/probe_usage.json'))
            (out/'probe-records.json').write_bytes(sb.filesystem.read_bytes('/tmp/probe_records.json'))
            # Private author diagnostics; never included in PR artifacts.
            for name in ['01-pub_012.json', '02-pub_017.json']:
                (out/name).write_bytes(sb.filesystem.read_bytes('/var/shuttle/episodes/'+name))
        finally:
            try: (out/'service.log').write_bytes(sb.filesystem.read_bytes('/var/shuttle/startup.log'))
            except Exception:pass
            stop(sb,phase)
    if not 0<len(candidate)<=262144:raise ValueError('candidate size out of bounds')
    receipt['candidate_sha256']=hashlib.sha256(candidate).hexdigest();save()
    sb,phase=launch(image_for(task/'tests'),'verifier')
    try:
        sb.filesystem.write_bytes(candidate, '/app/controller.py')
        execute(sb,phase,'verifier',['bash','/tests/test.sh'],17800)
        for name in ['metrics.json','results.jsonl','reward.txt','ctrf.json','completed.json']:
            (out/name).write_bytes(sb.filesystem.read_bytes('/logs/verifier/'+name))
        reward=(out/'reward.txt').read_text().strip()
        if reward!=('1' if args.mode=='oracle' else '0'):raise RuntimeError('Unexpected '+args.mode+' reward '+reward)
        receipt['validated']=True;receipt['reward']=int(reward);save()
    finally:
        for name in ['infrastructure-error.json','results.jsonl']:
            try:(out/name).write_bytes(sb.filesystem.read_bytes('/logs/verifier/'+name))
            except Exception:pass
        stop(sb,phase)

if __name__=='__main__':
    with modal.enable_output():main()
