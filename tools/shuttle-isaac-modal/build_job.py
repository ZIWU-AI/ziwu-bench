"""Emit a validated Harbor JobConfig using the trusted image-cache adapter."""
import argparse
import json
from pathlib import Path
from harbor.models.job.config import JobConfig

root=Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser()
ap.add_argument('--agent',default='oracle',choices=['oracle','nop'])
ap.add_argument('--output',type=Path,required=True)
a=ap.parse_args()
payload={'name':'shuttle-isaac-'+a.agent,'jobs_dir':str(root/'runs/harbor-shuttle'),
    'environment':{'import_path':'harbor_environment:ShuttleIsaacEnvironment','delete':True,
        'kwargs':{'app_name':'ziwu-shuttle-isaac','sandbox_timeout_secs':21600}},
    'agents':[{'name':a.agent}],
    'tasks':[{'path':str(root/'tasks/engineering-sciences/mechanical-engineering/shuttle-docking-isaac')}],
    'n_attempts':1,'orchestrator':{'n_concurrent_trials':1}}
config=JobConfig.model_validate(payload)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(config.model_dump_json(indent=2,exclude_none=True)+'\n')
print(a.output)
