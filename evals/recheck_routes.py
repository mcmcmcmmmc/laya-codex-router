#!/usr/bin/env python3
"""Supplemental routing-only check after the timeout fix; no answer-model calls.

Does not replace or repair the original A/B trial records.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sys
import time

import quality_compare as q
import jev_server as j


def run(out):
    cases = json.loads((out/'cases.json').read_text())
    runid = json.loads((out/'run.json').read_text())['runid']
    key = j.load_key()
    if not key:
        raise SystemExit('Missing local TypeSafe credential file')
    configs = {arm: json.loads((out/f'{arm}-policy.json').read_text()) for arm in q.ARMS}
    save = out/'routing-only.jsonl'
    if save.exists():
        raise SystemExit('Refusing to overwrite routing-only observations')
    def one(arm, case):
        tag = f'[{runid}-{case["id"]}-1]'
        payload = {'input': [{'role': 'user', 'content': tag+'\n'+case['task']+q.SUFFIX}]}
        task, previous, signals = j.extract(payload)
        state = j.jev_state(task, previous, signals, j.classify(payload))
        row = {'arm': arm, 'id': case['id'], 'state': state,
               'policy_version': configs[arm]['policy_version'],
               'io_timeout_seconds': j.ROUTING_TIMEOUT, 'answer_model_called': False}
        start = time.monotonic()
        try:
            response = j.call_jev_routed(key, state, configs[arm]['questions'])
            decision = j.decision_from_answers(response.get('answers'))
            row.update(jev_model=response.get('model'), answer=response.get('answers'),
                       selected_model=decision['model'], selected_effort=decision['effort'])
        except Exception as exc:
            row['error'] = j.jev_error_details(exc)
        row['seconds'] = round(time.monotonic()-start, 3)
        return row
    jobs = [(arm, case) for case in cases for arm in q.ARMS]
    random.Random(1010).shuffle(jobs)
    with save.open('x') as output, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(one, arm, case) for arm, case in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            output.write(json.dumps(row, ensure_ascii=False)+'\n')
            output.flush()
            print(index, '/24', row['arm'], row['id'], row.get('selected_model'), row.get('selected_effort'), row.get('error'), row['seconds'], flush=True)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
