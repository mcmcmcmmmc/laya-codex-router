"""Offline integrity review and descriptive summaries; never dispatch requests."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

import budget_study as study
from scipy.stats import binomtest


def review(out):
    study.verify(out)
    cases = {c['id']: c for c in study.load(out / 'cases.json')}
    pairs = sorted(study.lines(out / 'pairs.jsonl'), key=lambda r: r['id'])
    generations = study.lines(out / 'generations.jsonl')
    attempts = study.lines(out / 'answer-attempts.jsonl')
    routes = study.lines(out / 'routes.jsonl')
    by_request = {r['request_id']: r for r in generations}
    route_map = {(r['id'], r['arm']): r for r in routes}
    assert len(by_request) == len(generations)
    assert len({r['request_id'] for r in attempts}) == len(attempts) <= 250
    assert [r['ordinal'] for r in attempts] == list(range(1, len(attempts) + 1))
    assert len(routes) == len(route_map) == 300
    assert all(route_map[cid, 'baseline']['state_hash'] == route_map[cid, 'candidate']['state_hash'] for cid in cases)
    assert [r['id'] for r in pairs] == list(cases)[:len(pairs)]
    dispatched = {r['request_id'] for r in attempts if r['kind'] == 'primary'}
    assert dispatched == set(by_request), 'Review only after all primary requests finish'
    for g in generations:
        if g['outcome'] in ('correct', 'wrong'):
            assert study.grade(cases[g['id']], json.loads(g['text'])) == (g['outcome'] == 'correct')
        assert not g.get('served_model') or g['served_model'] == g['requested_model']
    for p in pairs:
        keys = []
        for arm, a in p['arms'].items():
            r = route_map[p['id'], arm]
            key = study.hash_value(study.payload(cases[p['id']], r['model'], r['effort']))
            assert key == a['request_id']
            assert a['outcome'] == by_request[key]['outcome']
            assert a['gate'] == r['gate']
            keys.append(key)
        assert p['shared'] == (len(set(keys)) == 1)
    def summarize(rows):
        win = sum(r['arms']['candidate']['outcome'] == 'correct' and r['arms']['baseline']['outcome'] != 'correct' for r in rows)
        loss = sum(r['arms']['baseline']['outcome'] == 'correct' and r['arms']['candidate']['outcome'] != 'correct' for r in rows)
        exact = binomtest(win, win + loss, .5).pvalue if win + loss else 1.
        assert abs(exact - study.exact_p(win, loss)) < 1e-12
        return {'n': len(rows), 'wins': win, 'losses': loss, 'exact_p': exact,
                'correct': {a: sum(r['arms'][a]['outcome'] == 'correct' for r in rows) for a in study.ARMS}}
    arms = {}
    for arm in study.ARMS:
        rows = [p['arms'][arm] for p in pairs]
        uses = [by_request[r['request_id']] for r in rows]
        arms[arm] = {
            'outcomes': dict(Counter(r['outcome'] for r in rows)),
            'selected_models': dict(Counter(r['model'] for r in rows)),
            'model_effort': dict(Counter(r['model'] + '/' + r['effort'] for r in rows)),
            'technical_fallbacks': sum(r['gate'] != 'apply' for r in rows),
            'median_answer_seconds': statistics.median(r['answer_seconds'] for r in rows),
            'mean_answer_seconds_including_timeout': statistics.mean(r['answer_seconds'] for r in rows),
            'median_route_seconds': statistics.median(r['route_seconds'] for r in rows),
            'logical_observed_output_tokens': sum((g.get('usage') or {}).get('output_tokens', 0) for g in uses),
            'logical_missing_usage': sum(not g.get('usage') for g in uses),
        }
    normal = [p for p in pairs if all(a['gate'] == 'apply' for a in p['arms'].values())]
    no_native_error = [p for p in pairs if all(a['outcome'] != 'request_error' for a in p['arms'].values())]
    discordant = [{'id': p['id'], 'family': p['family'], 'expected': cases[p['id']]['answer'],
                   'arms': {arm: dict(a, text=by_request[a['request_id']]['text']) for arm, a in p['arms'].items()}}
                  for p in pairs if (p['arms']['candidate']['outcome'] == 'correct') != (p['arms']['baseline']['outcome'] == 'correct')]
    result = {'integrity': 'PASS', 'primary': summarize(pairs),
              'both_routes_normal_descriptive_only': summarize(normal),
              'excluding_native_stream_errors_descriptive_only': summarize(no_native_error),
              'arms': arms, 'discordant_cases': discordant,
              'actual_answer_dispatches': len(attempts),
              'actual_completed_primary_records': len(generations),
              'actual_observed_output_tokens': sum((g.get('usage') or {}).get('output_tokens', 0) for g in generations),
              'missing_usage_generations': sum(not g.get('usage') for g in generations),
              'route_errors': dict(Counter((r.get('error') or {}).get('category', 'unspecified') for r in routes if r['gate'] != 'apply'))}
    (out / 'independent-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'discordant_cases'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    review(parser.parse_args().out)
