"""Guard against false wins in a model evaluation, without any network calls."""
import unittest
import json
from pathlib import Path
import tempfile
import quality_compare as q


class Grading(unittest.TestCase):
    def test_partial_runs_cannot_produce_a_promotion_verdict(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            (out/'plan.json').write_text(json.dumps({'jobs': [['candidate', 'h1', 1]]}))
            (out/'results.jsonl').write_text('')
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                q.report(out)

    def test_json_booleans_are_not_integers(self):
        self.assertFalse(q.strict_equal({'count': True}, {'count': 1}))
        self.assertFalse(q.strict_equal({'count': 1.0}, {'count': 1}))

    def test_missing_extra_and_incomplete_answers_fail(self):
        expected = {'winning_moves': [[2, 2], [3, 2]]}
        self.assertFalse(q.strict_equal({'winning_moves': [[2, 2]]}, expected))
        self.assertFalse(q.strict_equal(dict(expected, extra=0), expected))
        self.assertFalse(q.strict_equal({}, expected))
        self.assertTrue(q.strict_equal(expected, expected))

    def test_independent_oracles_match_original_regressions(self):
        self.assertEqual(q.game_oracle((7, 5, 4)), {'winning_moves': [[2, 2], [3, 2]]})
        self.assertEqual(q.race_oracle(('HHTH', 'THHH'), q.F(2, 3)),
                         {'p': '17/36', 'expected': '239/32'})


if __name__ == '__main__':
    unittest.main()
