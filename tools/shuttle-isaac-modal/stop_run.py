"""Stop only sandboxes listed by this author run, retaining bounded diagnostic reports."""
import argparse,json
from pathlib import Path
import modal
ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);ap.add_argument('--reason',default='Superseded by corrected native validation');a=ap.parse_args()
r=json.loads((a.output/'lifecycle.json').read_text())
for phase in r['phases']:
    if phase.get('cleanup_requested'):continue
    sb=modal.Sandbox.from_id(phase['sandbox_id'])
    try:
        data=sb.filesystem.read_bytes('/logs/verifier/results.jsonl')
        if len(data)<2*1024*1024:(a.output/'early-stop-results.jsonl').write_bytes(data)
    except Exception:
        pass
    finally:
        sb.terminate()
        print('stopped',phase['sandbox_id'])
(a.output/'author-stop.json').write_text(json.dumps({'reason':a.reason, 'sandboxes':[p['sandbox_id'] for p in r['phases']]},indent=2)+'\n')
