#!/usr/bin/env python3
"""Offline evidence audit. Never fills missing routes with guesses."""
from collections import Counter
import json
from pathlib import Path
import sys

from quality_compare import digest, strict_equal


def verify(out):
    plan = json.loads((out/'plan.json').read_text())
    for name, expected in plan['hashes'].items():
        assert digest(out/name) == expected, f'changed frozen input: {name}'
    rows = json.loads((out/'results.json').read_text())
    cases = {c['id']: c for c in json.loads((out/'cases.json').read_text())}
    assert Counter((r['arm'], r['id'], r['repeat']) for r in rows) == Counter(map(tuple, plan['jobs'])), 'missing/duplicate trials'
    counts = Counter()
    for row in rows:
        if row['outcome'] in ('correct', 'wrong'):
            assert row.get('terminal') == 'response.completed'
            answer = json.loads(row['text'])
            assert (row['outcome'] == 'correct') == strict_equal(answer, cases[row['id']]['answer'])
        if row['outcome'] == 'timeout':
            assert row['seconds'] >= plan['wall_budget_seconds'] - .1
        route = row.get('routing')
        if route:
            config = json.loads((out/f"{row['arm']}-policy.json").read_text())
            assert route['policy_version'] == config['policy_version']
            assert route['task'].startswith(row['tag'])
            assert not route['sticky'], 'a new trial accidentally reused a route'
            if row.get('served_model'):
                assert row['served_model'] == route['model'], 'selection/execution model mismatch'
            counts['technical_fallbacks'] += route['gate'] != 'apply'
        else:
            counts['missing_route_records'] += 1
        counts[row['outcome']] += 1
    print('PASS: complete paired population, frozen hashes, exact grading, deadlines, route/model identity.')
    print(json.dumps(dict(counts), indent=2))
    return dict(counts)


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve())
