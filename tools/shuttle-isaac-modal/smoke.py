"""Runs only inside the author validation sandbox; never receives host credentials."""
import json
from pathlib import Path
import sys
import time
import faulthandler
faulthandler.dump_traceback_later(60, repeat=True)
sys.path.insert(0, '/opt/sim')
from plant import Plant, load_station
from runtime import close
inst=json.loads(Path('/app/instances/pub_001.json').read_text())
private=json.loads(Path('/opt/sim/public_private.json').read_text())[inst['instance_id']]
started=time.monotonic()
try:
    results=[]
    for label,command in [('coast',[0.,0.]),('brake',[1.,1.])]:
        print("SMOKE_BUILD "+label,flush=True)
        p=Plant(inst,private,load_station())
        print("SMOKE_BUILT "+label,flush=True)
        for k in range(100):
            p.advance(command)
            if k%20==0:print("SMOKE_STEP "+str(k),flush=True)
        results.append(dict(label=label,state=p.true_state(),steps=p.scene.steps,
            peak_contact=p.peak_contact,physics=p.scene.physics_metadata))
        p.close()
    assert results[1]['state']['v'] < results[0]['state']['v'], results
    out=dict(results=results,elapsed=time.monotonic()-started)
    Path('/tmp/smoke-result.json').write_text(json.dumps(out,indent=2))
    print('SMOKE_RESULT '+json.dumps(out),flush=True)
except BaseException:
    import traceback
    traceback.print_exc()
    close(skip_cleanup=True,exit_code=2)
    raise
else:close(skip_cleanup=True,exit_code=0)
