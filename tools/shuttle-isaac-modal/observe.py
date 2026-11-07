"""Read bounded progress from only the sandbox IDs in one author run's receipt."""
import argparse,json
from pathlib import Path
import modal
ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args()
receipt=json.loads((args.output/'lifecycle.json').read_text())
for phase in receipt['phases']:
    if phase.get('cleanup_requested'):continue
    sb=modal.Sandbox.from_id(phase['sandbox_id'])
    p=sb.exec('bash','-lc', 'cat /var/shuttle/probe_usage.json 2>/dev/null; tail -3 /logs/verifier/results.jsonl 2>/dev/null; tail -4 /var/shuttle/startup.log 2>/dev/null; cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max 2>/dev/null',timeout=30)
    print(phase['role'],phase['sandbox_id']);print(p.stdout.read());print('observer_exit',p.wait())
