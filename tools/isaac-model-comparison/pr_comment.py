"""Render and upsert one explicit ziwu PR results comment per workflow run."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import subprocess
from profiles import PROFILES

REPO = 'ZIWU-AI/ziwu-bench'
TASK = 'tasks/engineering-sciences/mechanical-engineering/physicalrsi-bimanual-control'


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def minutes(row):
    execution = row.get('agent_execution') or {}
    try:
        start = datetime.fromisoformat(execution['started_at'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(execution['finished_at'].replace('Z', '+00:00'))
        return number((end - start).total_seconds() / 60)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def render(rows, run_id):
    if not re.fullmatch(r'[0-9]+', str(run_id)): raise ValueError('Invalid run ID')
    url = f'https://github.com/{REPO}/actions/runs/{run_id}'
    engines = sorted({str(row.get('isaac_version', 'unknown')) for row in rows})
    resources = sorted({f"{row.get('cpus', '—')} CPU / {row.get('memory_mib', '—')} MiB" for row in rows})
    engine_label = ', '.join(engines)
    if not re.fullmatch(r'[0-9a-z., ]+', engine_label): raise ValueError('Invalid engine label')
    lines = [f'<!-- ziwu-isaac-agent-trial:{run_id} -->', '## 🧪 Agent Trial Results', '',
        '**physicalrsi-bimanual-control**  ', f'`{TASK}`', '',
        f'**Isaac Sim {engine_label} · Modal A10 · OCI eu-west · {", ".join(resources)}**', '',
        '| Model (Agent) | Trial 1 | Average | Hub Link |', '|---|---|---|---|']
    scored=[]; costs=[]; times=[]
    for row in rows:
        spec=PROFILES[row['profile']]; harness=row['harness']
        if harness not in spec['harnesses']: raise ValueError('Invalid pair')
        status=row.get('status'); reward=row.get('reward')
        valid = status in ('passed','not_passed') and type(reward) in (int,float) and reward in (0,1)
        elapsed=minutes(row); cost=number(row.get('cost_usd')); estimate=number(row.get('cli_reported_cost_usd'))
        time_text=f'{elapsed:.1f}m' if elapsed is not None else 'runtime —'
        cost_text=f'${cost:.2f}' if cost is not None else f'~${estimate:.2f} CLI estimate' if estimate is not None else 'cost —'
        if valid:
            scored.append(reward)
            if elapsed is not None: times.append(elapsed)
            if cost is not None: costs.append(cost)
            trial='✅' if reward else '❌'; average=f'{int(reward)}/1'
        else:
            trial={'preflight_passed':'🔎 Tool preflight only', 'credential_missing':'⚠️ Missing credentials',
                'execution_error':'⚠️ Infrastructure / execution error', 'budget_exhausted':'⚠️ Budget exhausted',
                'preflight_failed':'⚠️ Tool preflight failed', 'result_missing':'⚠️ No result',
                'trial_running':'⏳ Running'}.get(status,'⚠️ Unscored')
            average='— (unscored)'
        effort=(row.get('route') or {}).get('reasoning_effort','high')
        if effort not in ('low','medium','high','xhigh'): effort='unknown'
        lines.append(f"| **{spec['model']} ({harness})**<br>`reasoning_effort={effort}` · agent budget `90m` | {trial}<br>{time_text} · {cost_text} | {average} | — (not uploaded) |")
    rate=f'{sum(scored)/len(scored):.0%} ({int(sum(scored))}/{len(scored)} passed)' if scored else 'Pending / unavailable (0 scored trials)'
    cost=f'${sum(costs)/len(costs):.2f} ({len(costs)}/{len(scored)} scored trials with verified cost)' if costs else '— (verified billing unavailable)'
    runtime=f'{sum(times)/len(times):.1f}m ({len(times)}/{len(scored)} scored trials with agent timing)' if times else '— (no scored agent timing)'
    lines += ['', f'✅ **Pass rate across scored trials:** {rate}  ', f'💰 **Average verified cost:** {cost}  ',
        f'⏱️ **Average agent runtime:** {runtime}', '', '**Job Analysis:** Not run; no judge verdict is claimed.', '',
        f'**Evidence:** [CI run and sanitized artifacts]({url}). Infrastructure/API failures and tool preflights are unscored. '
        'CLI cost estimates are not verified billing. Each engine/driver cohort is separate; historical acceptance is not transferred.', '',
        '<details>', '<summary>Download published results</summary>', '', '```sh',
        f'gh run download {run_id} --repo {REPO} --name isaac-comparison-{run_id} --dir isaac-results',
        '```', '', 'Sanitized results only; raw transcripts, keys and camera recordings are excluded.', '</details>', '']
    return '\n'.join(lines)


def gh(*args):
    return json.loads(subprocess.check_output(['gh', *args], text=True))


def post(body_file, run_id, pr, branch, repo):
    if repo != REPO: raise ValueError('Comments are authorized only in ziwu-bench')
    if not pr:
        prs=gh('pr','list','--repo',repo,'--head',branch,'--state','open','--json','number')
        if len(prs)!=1: raise ValueError('Expected exactly one open PR for workflow branch')
        pr=prs[0]['number']
    info=gh('pr','view',str(pr),'--repo',repo,'--json','headRefName,headRepository,headRepositoryOwner')
    if info['headRefName']!=branch or info['headRepository']['name']!='ziwu-bench' or info['headRepositoryOwner']['login'].lower()!='ziwu-ai':
        raise ValueError('Comment target must be this ziwu workflow branch')
    marker=f'<!-- ziwu-isaac-agent-trial:{run_id} -->'
    pages=gh('api',f'repos/{repo}/issues/{pr}/comments','--paginate','--slurp')
    matches=[c for page in pages for c in page if marker in c['body'].splitlines() and c['user']['login'] in ('lwhere1314','github-actions[bot]')]
    if len(matches)>1: raise ValueError('Duplicate result comments')
    path=f'repos/{repo}/issues/comments/{matches[0]["id"]}' if matches else f'repos/{repo}/issues/{pr}/comments'
    result=gh('api',path,'--method','PATCH' if matches else 'POST','--field','body=@'+str(body_file))
    print(result['html_url'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--pr',type=int,default=0);p.add_argument('--branch',default='');p.add_argument('--repo',default=REPO);p.add_argument('--post',action='store_true')
    a=p.parse_args();a.output.write_text(render(json.loads(a.source.read_text()),a.run_id))
    if a.post: post(a.output,a.run_id,a.pr,a.branch,a.repo)
