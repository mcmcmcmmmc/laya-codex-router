#!/usr/bin/env python3
"""Frozen, paired live evaluation; credentials remain inside the local relay.

freeze --output DIR --development-cases PATH prepares 12 cases without network.
run --output DIR makes 48 real calls, two concurrent at most, no retries.
report --output DIR regenerates the summary from saved results and relay logs.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction as F
from functools import lru_cache
import hashlib
import http.client
import itertools
import json
import os
from pathlib import Path
import random
import socket
import statistics
import subprocess
import sys
import threading
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))
import routing_policy as policy

BUDGET = 180
ARMS = ("baseline", "candidate")
PORTS = {"baseline": 14319, "candidate": 14320}
SUFFIX = '\n独立求解，不使用工具；只输出题目指定JSON，不加解释。本次调用时间上限180秒。'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    return a == b


def game_oracle(start):
    @lru_cache(None)
    def win(p, last):
        for h in range(3):
            if h == last:
                continue
            for k in (1, 2):
                if p[h] < k:
                    continue
                q = list(p)
                q[h] -= k
                if sum(q) and not win(tuple(q), h):
                    return True
        return False

    table = {}
    for p in sorted(itertools.product(*(range(x + 1) for x in start)), key=sum):
        for last in (-1, 0, 1, 2):
            successors = []
            for h in range(3):
                for k in (1, 2):
                    if h != last and p[h] >= k:
                        q = tuple(v - (k if i == h else 0) for i, v in enumerate(p))
                        successors.append(bool(sum(q)) and not table[q, h])
            table[p, last] = any(successors)
            assert table[p, last] == win(p, last)
    moves = []
    for h in range(3):
        for k in (1, 2):
            q = list(start)
            q[h] -= k
            if q[h] >= 0 and sum(q) and not win(tuple(q), h):
                moves.append([h + 1, k])
    return {"winning_moves": moves}


def race_oracle(patterns, ph):
    # Exact prefix automaton / rational Gaussian elimination.
    states = sorted({""} | {p[:i] for p in patterns for i in range(1, len(p))}, key=lambda x: (len(x), x))
    def trans(s, x):
        t = s + x
        for p in patterns:
            if t.endswith(p):
                return p
        return max((a for a in states if t.endswith(a)), key=len)
    n = len(states)
    matrix = [[F(i == j) for j in range(n)] + [F(0), F(1)] for i in range(n)]
    for i, s in enumerate(states):
        for x, pr in (("H", ph), ("T", 1-ph)):
            t = trans(s, x)
            if t == patterns[0]:
                matrix[i][-2] += pr
            elif t in states:
                matrix[i][states.index(t)] -= pr
    for k in range(n):
        pivot = next(i for i in range(k, n) if matrix[i][k])
        matrix[k], matrix[pivot] = matrix[pivot], matrix[k]
        div = matrix[k][k]
        matrix[k] = [v/div for v in matrix[k]]
        for i in range(n):
            if i != k:
                mul = matrix[i][k]
                matrix[i] = [a-mul*b for a, b in zip(matrix[i], matrix[k])]
    probability, expectation = matrix[0][-2:]
    # Independent numeric propagation over full recent suffixes, not prefixes.
    mass = {"": 1.0}
    pa = et = 0.0
    width = max(map(len, patterns))
    for _ in range(600):
        et += sum(mass.values())
        nxt = {}
        for s, weight in mass.items():
            for x, pr in (("H", float(ph)), ("T", float(1-ph))):
                t = s+x
                if t.endswith(patterns[0]):
                    pa += weight*pr
                elif not t.endswith(patterns[1]):
                    tail = t[-(width-1):]
                    nxt[tail] = nxt.get(tail, 0.0) + weight*pr
        mass = nxt
    assert abs(pa-float(probability)) < 1e-9
    assert abs(et-float(expectation)) < 1e-8
    return {"p": str(probability), "expected": str(expectation)}


def new_cases():
    edges = [(0, 2), (1, 2), (1, 3), (2, 4), (3, 4)]
    orders = [p for p in itertools.permutations(range(5)) if all(p.index(a) < p.index(b) for a, b in edges)]
    dp = {0: 1}
    for mask in range(32):
        for v in range(5):
            if mask & (1 << v) or any(not mask & (1 << a) for a, b in edges if b == v):
                continue
            nxt = mask | (1 << v)
            dp[nxt] = dp.get(nxt, 0) + dp.get(mask, 0)
    assert len(orders) == dp[31]
    return [
        dict(id="h1", split="new_easy", title="结构化抽取", task='从“编号Q17，颜色蓝，数量8；编号Q18，颜色红，数量3”中抽取Q18的颜色和数量。返回{"color":"颜色","quantity":整数}。', answer={"color": "红", "quantity": 3}),
        dict(id="h2", split="new_easy", title="直接算术", task='计算(27−9)×4+11，返回{"value":整数}。', answer={"value": 83}),
        dict(id="h3", split="new_medium", title="重叠计数", task='字符串ababababa中子串ababa出现几次？允许重叠，索引从0开始。返回{"count":整数,"positions":[全部起始索引升序]}。', answer={"count": 3, "positions": [0, 2, 4]}),
        dict(id="h4", split="new_medium", title="拓扑序完整性", task='有向图顶点A,B,C,D,E，边A→C、B→C、B→D、C→E、D→E。求所有拓扑序数量及字典序最小拓扑序。返回{"count":整数,"first":"字母串"}。', answer={"count": len(orders), "first": ''.join(chr(65+i) for i in min(orders))}),
        dict(id="h5", split="new_hard_variant", title="新随机模式竞争", task='每次独立抛硬币，P(H)=3/5、P(T)=2/5，从空序列开始，首次出现连续模式HTHH或THHT之一即停止，模式可重叠。求HTHH先出现的精确概率及停止时的期望总抛掷次数（含最后一次），用最简分数字符串。返回{"p":"分子/分母","expected":"分子/分母"}。', answer=race_oracle(("HTHH", "THHT"), F(3, 5))),
        dict(id="h6", split="new_hard_variant", title="新历史约束博弈", task='两人轮流取石子，三堆初始分别有6、4、3颗，堆号1、2、3。每步选一堆取1或2颗；不能选上一步对手刚选的堆，首步无限制。取走全局最后一颗者立即输；没有合法动作的人也输。双方最优，列出先手所有必胜首步，按堆号、数量升序；无必胜首步则空数组。返回{"winning_moves":[[堆号,数量],...]}。', answer=game_oracle((6, 4, 3))),
    ]


def freeze(out, development):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "plan.json").exists():
        raise SystemExit("Refusing to overwrite a frozen plan")
    cases = json.loads(development.read_text())
    assert len(cases) == 6 and {c['id'] for c in cases} == {f't{i}' for i in range(1, 7)}
    for c in cases:
        c["split"] = "development"
    cases += new_cases()
    for c in cases:
        assert len(c["task"] + SUFFIX) + 50 < 500
    save(out / "cases.json", cases)
    baseline = json.loads((REPO / "evals/policies/joint-v1-standard.json").read_text())
    save(out / "baseline-policy.json", baseline)
    save(out / "candidate-policy.json", {"policy_version": policy.POLICY_VERSION, "questions": policy.QUESTIONS})
    jobs = [(arm, c['id'], repeat) for c in cases for repeat in (1, 2) for arm in ARMS]
    random.Random(92126).shuffle(jobs)
    files = ["cases.json", "baseline-policy.json", "candidate-policy.json"]
    save(out / "plan.json", {"requests": len(jobs), "jobs": jobs, "repeats": 2, "concurrency": 2,
         "wall_budget_seconds": BUDGET, "suffix": SUFFIX, "retry": "none", "tools": "none",
         "hashes": {f: digest(out/f) for f in files}, "server_sha256": digest(REPO/'server/jev_server.py'),
         "evaluator_sha256": digest(Path(__file__)),
         "acceptance": "candidate correct > baseline correct, no easy-control regression, zero technical fallback or infrastructure confounds",
         "limits": ["small synthetic sample", "two repeats", "new hard cases are within-family variants", "not a savings experiment"]})
    print("FROZEN", len(cases), "cases", len(jobs), "calls", flush=True)


def serve(out, arm):
    import jev_server as j
    config = json.loads((out/f"{arm}-policy.json").read_text())
    policy.POLICY_VERSION = j.POLICY_VERSION = config['policy_version']
    policy.QUESTIONS = j.QUESTIONS = config['questions']
    j.LISTEN = ("127.0.0.1", PORTS[arm])
    j.LOG_PATH = str(out/f"{arm}-routes.jsonl")
    # Isolate operational flags too; never write production service state.
    for name in ("OFF_PATH", "SHADOW_PATH", "DEBUG_PATH", "SIGNATURE_PATH", "DRY_MANUAL_PATH", "DRY_STATE_PATH"):
        setattr(j, name, str(out/f"{arm}-{name}.unused"))
    j.main()


def one(arm, case, repeat, runid):
    tag = f'[{runid}-{case["id"]}-{repeat}]'
    body = {"model": "auto", "input": [{"role": "user", "content": tag+'\n'+case['task']+SUFFIX}],
            "store": False, "stream": True, "prompt_cache_key": tag}
    row = dict(arm=arm, id=case['id'], split=case['split'], repeat=repeat, tag=tag)
    conn = http.client.HTTPConnection("127.0.0.1", PORTS[arm], timeout=BUDGET+10)
    expired = threading.Event()
    sock = timer = None
    start = time.monotonic()
    chunks = []
    def stop():
        expired.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    try:
        conn.connect()
        sock = conn.sock
        timer = threading.Timer(BUDGET, stop)
        timer.daemon = True
        timer.start()
        conn.request('POST', '/v1/responses', json.dumps(body, ensure_ascii=False).encode(), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        row['status'] = response.status
        if response.status == 200:
            for line in response:
                if expired.is_set():
                    break
                line = line.decode().strip()
                if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                    continue
                event = json.loads(line[5:])
                obj = event.get('response') or {}
                if obj.get('model'):
                    row['served_model'] = obj['model']
                if event.get('type') == 'response.output_text.delta':
                    chunks.append(event.get('delta', ''))
                if event.get('type') in ('response.completed', 'response.failed', 'response.incomplete'):
                    row['terminal'] = event['type']
                    row['usage'] = obj.get('usage')
    except Exception as exc:
        # Never record raw URLs/exception strings which could contain credentials.
        row['error_type'] = type(exc).__name__
    finally:
        if timer:
            timer.cancel()
        conn.close()
    row.update(seconds=round(time.monotonic()-start, 3), text=''.join(chunks).strip())
    row['outcome'] = 'timeout' if expired.is_set() else 'request_error'
    if row.get('terminal') == 'response.completed' and not expired.is_set():
        try:
            row['answer'] = json.loads(row['text'])
            row['outcome'] = 'correct' if strict_equal(row['answer'], case['answer']) else 'wrong'
        except ValueError:
            row['outcome'] = 'format_error'
    return row


def run(out):
    plan = json.loads((out/'plan.json').read_text())
    for f, expected in plan['hashes'].items():
        assert digest(out/f) == expected, f
    assert digest(REPO/'server/jev_server.py') == plan['server_sha256']
    assert digest(Path(__file__)) == plan['evaluator_sha256']
    if (out/'results.jsonl').exists():
        raise SystemExit('Refusing to overwrite an existing run')
    cases = {c['id']: c for c in json.loads((out/'cases.json').read_text())}
    runid = 'qv2-'+uuid.uuid4().hex[:8]
    save(out/'run.json', {'runid': runid, 'started': time.strftime('%Y-%m-%dT%H:%M:%S')})
    processes, handles = [], []
    try:
        for arm in ARMS:
            handle = (out/f'{arm}-server.log').open('w')
            handles.append(handle)
            processes.append(subprocess.Popen([sys.executable, __file__, 'serve', '--output', str(out), '--arm', arm], stdout=handle, stderr=handle))
        for arm in ARMS:
            ready = False
            for _ in range(40):
                conn = http.client.HTTPConnection('127.0.0.1', PORTS[arm], timeout=1)
                try:
                    conn.request('GET', '/health')
                    health = json.loads(conn.getresponse().read())
                    expected = json.loads((out/f'{arm}-policy.json').read_text())['policy_version']
                    assert health['policy_version'] == expected
                    ready = True
                    break
                except OSError:
                    time.sleep(.1)
                finally:
                    conn.close()
            assert ready, f'{arm} did not start'
        with (out/'results.jsonl').open('x') as output, ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(one, arm, cases[cid], repeat, runid) for arm, cid, repeat in plan['jobs']]
            for index, future in enumerate(as_completed(futures), 1):
                row = future.result()
                output.write(json.dumps(row, ensure_ascii=False)+'\n')
                output.flush()
                print(index, '/', len(futures), row['arm'], row['id'], row['repeat'], row['outcome'], row.get('served_model'), row['seconds'], flush=True)
        # A client deadline can leave a remote response running; log collection
        # does not treat a missing route record as a successful Jev decision.
        time.sleep(1)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)
        for handle in handles:
            handle.close()
    report(out)


def report(out):
    rows = [json.loads(s) for s in (out/'results.jsonl').read_text().splitlines()]
    plan = json.loads((out/'plan.json').read_text())
    actual = Counter((r['arm'], r['id'], r['repeat']) for r in rows)
    if actual != Counter(map(tuple, plan['jobs'])):
        raise ValueError('Incomplete or duplicate paired trials; no promotion verdict')
    summary = {}
    for arm in ARMS:
        logfile = out/f'{arm}-routes.jsonl'
        logs = [json.loads(s) for s in logfile.read_text().splitlines()] if logfile.exists() else []
        subset = [r for r in rows if r['arm'] == arm]
        for row in subset:
            row['routing'] = next((r for r in logs if r.get('task', '').startswith(row['tag'])), None)
        summary[arm] = dict(outcomes=dict(Counter(r['outcome'] for r in subset)),
            active_routes=dict(Counter(r['routing']['model']+':'+str(r['routing']['effort']) for r in subset if r['routing'] and r['routing']['gate']=='apply')),
            technical_fallbacks=sum(bool(r['routing'] and r['routing']['gate']!='apply') for r in subset),
            missing_routes=sum(r['routing'] is None for r in subset),
            median_seconds=statistics.median(r['seconds'] for r in subset),
            splits={split: dict(Counter(r['outcome'] for r in subset if r['split']==split)) for split in sorted({r['split'] for r in subset})})
    baseline, candidate = summary['baseline'], summary['candidate']
    def correct(s):
        return s['outcomes'].get('correct', 0)
    summary['promotion_pass'] = (correct(candidate) > correct(baseline)
        and candidate['splits']['new_easy'].get('correct', 0) >= baseline['splits']['new_easy'].get('correct', 0)
        and all(not s['technical_fallbacks'] and not s['missing_routes'] and not s['outcomes'].get('request_error') for s in (baseline, candidate)))
    save(out/'results.json', rows)
    save(out/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'run', 'report', 'serve'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development-cases', type=Path)
    parser.add_argument('--arm', choices=ARMS)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.action == 'freeze':
        freeze(out, args.development_cases)
    elif args.action == 'serve':
        serve(out, args.arm)
    else:
        {'run': run, 'report': report}[args.action](out)
