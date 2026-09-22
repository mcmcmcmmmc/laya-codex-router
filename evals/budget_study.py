#!/usr/bin/env python3
"""Budgeted paired study. Freeze first; routing, stages, and audit are explicit.

Only synthetic prompts are sent. Calls are recorded before dispatch. No retries,
no reset credits, no purchases. Same execution payloads share one generation.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import random
import re
import socket
import subprocess
import sys
import threading
import time

import budget_cases
import quality_compare as q
import jev_server as j

SUFFIX = '\n不使用工具，独立求解。只输出指定JSON，不加解释；本次调用时间上限180秒。'
LOCK = threading.RLock()
PRIMARY_LIMIT = 240
TOTAL_LIMIT = 250
TOKEN_SOFT_LIMIT = 180_000
ARMS = ('baseline', 'candidate')


def load(path):
    return json.loads(path.read_text())


def lines(path):
    with LOCK:
        return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def append(path, row):
    with LOCK, path.open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False)+'\n')
        f.flush()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def hash_value(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def prompt(case):
    return '[study-'+hash_value(case['task'])[:12]+']\n'+case['task']+SUFFIX


def payload(case, model, effort):
    return {'model':model, 'reasoning':{'effort':effort}, 'service_tier':'default',
            'input':[{'role':'user','content':prompt(case)}], 'store':False, 'stream':True,
            'prompt_cache_key':'study-'+hash_value(case['task'])[:20]}


def exact_p(wins, losses):
    n = wins+losses
    return min(1., 2*sum(math.comb(n, k) for k in range(min(wins, losses)+1))/2**n) if n else 1.


def grade(case,answer):
    # The Markov prompt explicitly allows integer strings as an alternative
    # to reduced fractions. Honor both 1 and 1/1, without accepting 2/4.
    if case['family']=='markov' and isinstance(answer,dict):
        normalized={}
        for key,value in answer.items():
            if not isinstance(value,str) or not re.fullmatch(r'-?\d+(?:/[1-9]\d*)?',value):return False
            if '/' in value:
                numerator,denominator=map(int,value.split('/'))
                if math.gcd(numerator,denominator)!=1:return False
            normalized[key]=str(budget_cases.F(value))
        answer=normalized
    return q.strict_equal(answer,case['answer'])


def freeze(out):
    out.mkdir(parents=True, exist_ok=True)
    if (out/'plan.json').exists():
        raise SystemExit('Frozen plan exists; do not overwrite')
    cases=budget_cases.generate()
    assert all(len(prompt(c))<=j.TASK_CHARS for c in cases)
    assert len({c['task'] for c in cases})==150
    q.save(out/'cases.json',cases)
    q.save(out/'baseline-policy.json',load(q.REPO/'evals/policies/joint-v1-standard.json'))
    q.save(out/'candidate-policy.json',{'policy_version':j.POLICY_VERSION,'questions':j.QUESTIONS})
    tasks=[(c['id'],a) for c in cases for a in ARMS]
    random.Random(410927).shuffle(tasks)
    q.save(out/'plan.json',{
        'cases':150, 'task_seed':927310, 'route_jobs':tasks, 'checkpoints':[40,80,120,150],
        'answer_request_hard_limit':TOTAL_LIMIT,'primary_request_limit':PRIMARY_LIMIT,'audit_reserve':10,
        'routing_request_limit':310, 'deadline_seconds':180,'route_io_timeout_seconds':10,
        'concurrency':2,'soft_observed_output_token_limit':TOKEN_SOFT_LIMIT,
        'account_guard':'Inspect shared usage at each stage; stop if weekly used >=57%, or remaining <=35%, whichever first. Started at 49% used. No credit redemption.',
        'sharing':'Only identical canonical execution payloads, within this experiment; same sampled output assigned to both policies. Count once as actual experimental spend, twice only as logical per-policy usage.',
        'primary':'Correct complete JSON within 180 seconds, including technical fallback outcomes; two independent Jev decisions per task.',
        'transport':'Both arms use identical 10-second I/O timeout and original Astra-medium technical fallback; decisions logged before answer generation.',
        'looks':'40 is operational only. At 80/120 intermediate alpha=.005; final budget-feasible checkpoint alpha=.04. Total two-sided alpha <=.05. No positive stop before 80.',
        'success':'Exact paired McNemar p <= allocated alpha, net gain >=5 percentage points. Broad improvement additionally requires net wins in >=3 families and no easy-family regression; otherwise label local evidence.',
        'futility':'At a formal checkpoint stop without superiority if one-sided Clopper-Pearson upper bound on candidate-only win probability is below .05. Not proof of equivalence.',
        'failure':'No retry. Fail fast on 3 consecutive routing errors or >10% after >=20 routing calls. Stop on native quota/auth failures. Missing usage is unknown, never zero.',
        'scope':'Fixed synthetic mixture, not general production reliability; report by family and leave-one-family-out sensitivity.',
        'hashes':{name:q.digest(out/name) for name in ['cases.json','baseline-policy.json','candidate-policy.json']},
        'source_hashes':{str(f.relative_to(q.REPO)):q.digest(f) for f in [Path(__file__),q.REPO/'evals/budget_cases.py',q.REPO/'evals/quality_compare.py',q.REPO/'server/jev_server.py',q.REPO/'server/routing_policy.py']}})
    print('FROZEN: 150 tasks;',dict(Counter(c['family'] for c in cases)),flush=True)


def verify(out):
    plan=load(out/'plan.json')
    for name,digest in plan['hashes'].items():
        assert q.digest(out/name)==digest,name
    for name,digest in plan['source_hashes'].items():
        assert q.digest(q.REPO/name)==digest,name
    return plan


def routing(out):
    plan=verify(out);cases={c['id']:c for c in load(out/'cases.json')}
    configs={a:load(out/f'{a}-policy.json') for a in ARMS}
    if (out/'routes.jsonl').exists():raise SystemExit('Routing has already started; inspect before resuming')
    key=j.load_key()
    if not key:raise SystemExit('Local TypeSafe key file missing')
    stop=threading.Event();counts=[]
    def one(cid,arm):
        if stop.is_set():return None
        case=cases[cid];task,prev,signals=j.extract(payload(case,'auto','medium'))
        state=j.jev_state(task,prev,signals,j.classify(payload(case,'auto','medium')))
        row={'id':cid,'arm':arm,'state_hash':hash_value(state),'policy_version':configs[arm]['policy_version']}
        append(out/'route-attempts.jsonl',row)
        start=time.monotonic()
        try:
            result=j.call_jev_routed(key,state,configs[arm]['questions'])
            decision=j.decision_from_answers(result.get('answers'))
            row.update(model=decision['model'],effort=decision['effort'],gate='apply',
                       answers=result.get('answers'),jev_model=result.get('model'),usage=result.get('usage'))
        except Exception as exc:
            row.update(model=j.ASTRA,effort='medium',gate='technical_fallback',error=j.jev_error_details(exc))
        row['seconds']=round(time.monotonic()-start,3)
        append(out/'routes.jsonl',row)
        return row
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one,cid,a) for cid,a in plan['route_jobs']]
        for future in as_completed(futures):
            row=future.result()
            if row is None:continue
            counts.append(row['gate']!='apply')
            if len(counts)%20==0 or counts[-1]:print('routes',len(counts),'/300','errors',sum(counts),row['id'],row['arm'],flush=True)
            if len(counts)>=3 and all(counts[-3:]) or len(counts)>=20 and sum(counts)/len(counts)>.1:
                stop.set()
    if len(counts)!=300:raise SystemExit('Routing error guard stopped the experiment; no answers generated')
    routes={(r['id'],r['arm']):r for r in lines(out/'routes.jsonl')}
    counts={}
    for n in plan['checkpoints']:
        counts[n]=sum(len({hash_value(payload(c,routes[c['id'],a]['model'],routes[c['id'],a]['effort'])) for a in ARMS}) for c in list(cases.values())[:n])
    maximum=max(n for n,cost in counts.items() if cost<=PRIMARY_LIMIT)
    audit=random.Random(121).sample([c['id'] for c in list(cases.values())[:40]],5)
    q.save(out/'allocation.json',{'unique_generation_counts':counts,'maximum_n':maximum,'audit_cases':audit,
                                'route_errors':sum(counts_ for counts_ in [r['gate']!='apply' for r in routes.values()])})
    print('ALLOCATION',load(out/'allocation.json'),flush=True)


def claim(out,request_id,kind):
    with LOCK:
        attempts=lines(out/'answer-attempts.jsonl')
        if any(r['request_id']==request_id for r in attempts):return False
        limit=PRIMARY_LIMIT if kind=='primary' else TOTAL_LIMIT
        if len(attempts)>=limit:raise RuntimeError('Answer request hard limit reached')
        with (out/'answer-attempts.jsonl').open('a') as f:
            f.write(canonical({'request_id':request_id,'kind':kind,'ordinal':len(attempts)+1,'at':time.time()})+'\n');f.flush()
        return True


def native(out,case,body,secret):
    request_id=hash_value(body)
    if not claim(out,request_id,'primary'):
        known=next((r for r in lines(out/'generations.jsonl') if r['request_id']==request_id),None)
        if known:return known
        raise RuntimeError('A prior dispatched request has no terminal record; refusing a silent retry')
    row={'request_id':request_id,'id':case['id'],'requested_model':body['model'],'effort':body['reasoning']['effort']}
    conn=http.client.HTTPConnection('127.0.0.1',4202,timeout=190)
    expired=threading.Event();sock=timer=None;chunks=[];start=time.monotonic()
    def cutoff():
        expired.set()
        try:sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
    try:
        conn.connect();sock=conn.sock
        timer=threading.Timer(180,cutoff);timer.daemon=True;timer.start()
        conn.request('POST','/_codex-router/'+secret+'/v1/responses',canonical(body).encode(),{'Content-Type':'application/json'})
        response=conn.getresponse();row['status']=response.status
        if response.status==200:
            for line in response:
                if expired.is_set():break
                text=line.decode().strip()
                if not text.startswith('data:') or text[5:].strip()=='[DONE]':continue
                event=json.loads(text[5:]);obj=event.get('response') or {}
                if obj.get('model'):row['served_model']=obj['model']
                if event.get('type')=='response.output_text.delta':chunks.append(event.get('delta',''))
                if event.get('type') in ('response.completed','response.failed','response.incomplete'):
                    row['terminal']=event['type'];row['usage']=obj.get('usage')
    except Exception as exc:row['error_type']=type(exc).__name__
    finally:
        if timer:timer.cancel()
        conn.close()
    row.update(seconds=round(time.monotonic()-start,3),text=''.join(chunks).strip(),outcome='timeout' if expired.is_set() else 'request_error')
    if row.get('terminal')=='response.completed' and not expired.is_set():
        try:
            row['answer']=json.loads(row['text'])
            row['outcome']='correct' if grade(case,row['answer']) else 'wrong'
        except ValueError:row['outcome']='format_error'
    if row.get('served_model') and row['served_model']!=body['model']:row['outcome']='model_mismatch'
    append(out/'generations.jsonl',row)
    return row


def stage(out,n):
    verify(out);allocation=load(out/'allocation.json')
    assert n in (40,80,120,150) and n<=allocation['maximum_n']
    previous=lines(out/'pairs.jsonl')
    if len(previous)>n:raise SystemExit('Already beyond this stage')
    cases=load(out/'cases.json');assert [r['id'] for r in sorted(previous,key=lambda r:r['id'])]==[c['id'] for c in cases[:len(previous)]]
    routes={(r['id'],r['arm']):r for r in lines(out/'routes.jsonl')}
    secret=Path(j.CALLER_SECRET_PATH).read_text().strip()
    stopped=threading.Event()
    def one(case):
        if stopped.is_set() or (out/'STOP').exists():return None
        observed=sum((r.get('usage') or {}).get('output_tokens',0) for r in lines(out/'generations.jsonl'))
        if observed>=TOKEN_SOFT_LIMIT:stopped.set();return None
        arms=list(ARMS);random.Random(case['id']).shuffle(arms);cache={};answers={}
        for arm in arms:
            route=routes[case['id'],arm];body=payload(case,route['model'],route['effort']);key=hash_value(body)
            if key not in cache:cache[key]=native(out,case,body,secret)
            result=cache[key];answers[arm]={'request_id':key,'outcome':result['outcome'],'model':route['model'],'effort':route['effort'],
                'gate':route['gate'],'route_seconds':route['seconds'],'answer_seconds':result['seconds']}
            if result.get('status') in (401,402,403,429) or result['outcome'] in ('model_mismatch','request_error'):stopped.set()
        row={'id':case['id'],'family':case['family'],'arms':answers,'shared':len(cache)==1}
        append(out/'pairs.jsonl',row);return row
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one,c) for c in cases[len(previous):n]]
        for future in as_completed(futures):
            row=future.result()
            if row:print('pair',row['id'],row['family'],[(a,row['arms'][a]['model'],row['arms'][a]['outcome']) for a in ARMS],'shared',row['shared'],flush=True)
    if len(lines(out/'pairs.jsonl'))!=n:raise SystemExit('Budget/infrastructure guard interrupted stage; do not claim significance')
    report(out,n)


def report(out,n):
    from scipy.stats import beta
    rows=sorted(lines(out/'pairs.jsonl'),key=lambda r:r['id'])
    assert len(rows)==n
    def success(row,arm):return row['arms'][arm]['outcome']=='correct'
    wins=sum(success(r,'candidate') and not success(r,'baseline') for r in rows)
    losses=sum(success(r,'baseline') and not success(r,'candidate') for r in rows)
    maximum=load(out/'allocation.json')['maximum_n']
    alpha=.04 if n==maximum else .005 if n in (80,120) else 0.
    p=exact_p(wins,losses);delta=(wins-losses)/n
    byfamily={f:{'n':sum(r['family']==f for r in rows),
                 'baseline':sum(r['family']==f and success(r,'baseline') for r in rows),
                 'candidate':sum(r['family']==f and success(r,'candidate') for r in rows)} for f in budget_cases.FAMILIES}
    familywins=sum(v['candidate']>v['baseline'] for v in byfamily.values())
    easy_ok=all(byfamily[f]['candidate']>=byfamily[f]['baseline'] for f in ('arithmetic','records','overlap'))
    upper=float(beta.ppf(1-alpha,wins+1,n-wins)) if alpha and wins<n else 1.
    decision='continue'
    if alpha and p<=alpha and delta>=.05:decision='superior_in_mixture' if familywins>=3 and easy_ok else 'localized_gain'
    elif alpha and p<=alpha and delta<=-.05:decision='harm'
    elif alpha and upper<.05:decision='futility_no_meaningful_gain_evidence'
    elif n==maximum:decision='inconclusive'
    gens=lines(out/'generations.jsonl')
    result={'n':n,'correct':{a:sum(success(r,a) for r in rows) for a in ARMS},'wins':wins,'losses':losses,
            'difference':delta,'mcnemar_two_sided_p':p,'alpha_this_look':alpha,'decision':decision,
            'candidate_only_win_probability_upper':upper,'family_results':byfamily,'shared_generations':sum(r['shared'] for r in rows),
            'answer_requests':len(lines(out/'answer-attempts.jsonl')),
            'observed_output_tokens':sum((r.get('usage')or{}).get('output_tokens',0) for r in gens),
            'missing_usage_generations':sum(not r.get('usage') for r in gens),
            'technical_fallback_pairs':sum(any(r['arms'][a]['gate']!='apply' for a in ARMS) for r in rows),
            'leave_one_family_out_delta':{f:sum(int(success(r,'candidate'))-int(success(r,'baseline')) for r in rows if r['family']!=f)/max(1,sum(r['family']!=f for r in rows)) for f in byfamily}}
    q.save(out/f'look-{n}.json',result);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


def audit_server(out,arm):
    # A budget audit never switches to another provider on quota exhaustion.
    def no_quota_fallback(*args):raise RuntimeError('Audit stops on native quota')
    j.dry_target=no_quota_fallback
    q.serve(out,arm)


def audit(out):
    verify(out)
    cases={c['id']:dict(c,split='audit') for c in load(out/'cases.json')}
    selected=load(out/'allocation.json')['audit_cases']
    if (out/'audit.jsonl').exists():raise SystemExit('Audit already started')
    processes=[];handles=[]
    try:
        for a in ARMS:
            f=(out/f'{a}-audit-server.log').open('w');handles.append(f)
            processes.append(subprocess.Popen([sys.executable,__file__,'audit-server','--out',str(out),'--arm',a],stdout=f,stderr=f))
        time.sleep(.7)
        assert all(p.poll() is None for p in processes)
        for cid in selected:
            for a in ARMS:
                assert claim(out,'audit-'+cid+'-'+a,'audit')
                row=q.one(a,cases[cid],1,'audit-budget')
                append(out/'audit.jsonl',row)
                print('audit',a,cid,row['outcome'],row.get('served_model'),flush=True)
    finally:
        for p in processes:p.terminate()
        for p in processes:p.wait(timeout=10)
        for f in handles:f.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['freeze','routing','stage','report','audit','audit-server'])
    p.add_argument('--out',type=Path,required=True);p.add_argument('--n',type=int);p.add_argument('--arm',choices=ARMS)
    a=p.parse_args();out=a.out.resolve()
    if a.action in ('stage','report'):globals()[a.action](out,a.n)
    elif a.action=='audit-server':audit_server(out,a.arm)
    else:globals()[a.action](out)
