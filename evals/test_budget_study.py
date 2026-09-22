from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from scipy.stats import binomtest
import budget_cases as cases
import budget_study as s


class BudgetStudy(unittest.TestCase):
    def test_fraction_alternatives_follow_the_question_contract(self):
        case={'family':'markov','answer':{'p':'1/2','expected':'1'}}
        self.assertTrue(s.grade(case,{'p':'1/2','expected':'1/1'}))
        self.assertFalse(s.grade(case,{'p':'2/4','expected':'1'}))
        self.assertFalse(s.grade(case,{'p':.5,'expected':'1'}))

    def test_exact_p_matches_independent_library(self):
        for wins in range(15):
            for losses in range(15):
                expected=binomtest(wins,wins+losses,.5).pvalue if wins+losses else 1.
                self.assertAlmostEqual(s.exact_p(wins,losses),expected)

    def test_hard_budget_and_idempotency_survive_concurrent_claims(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            def claim(i):
                try:return s.claim(out,str(i),'primary')
                except RuntimeError:return False
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(claim,range(260)))
            self.assertEqual(len(s.lines(out/'answer-attempts.jsonl')),240)
            self.assertFalse(s.claim(out,'0','primary'))
            for i in range(10):self.assertTrue(s.claim(out,'audit-'+str(i),'audit'))
            with self.assertRaises(RuntimeError):s.claim(out,'one-too-many','audit')

    def test_sharing_requires_identical_model_effort_and_full_prompt(self):
        case={'task':'Calculate 1+1'}
        p=s.payload(case,'gpt-5.6-sol','high')
        self.assertEqual(s.hash_value(p),s.hash_value(s.payload(case,'gpt-5.6-sol','high')))
        for other in [s.payload(case,'gpt-5.6-sol','medium'),s.payload(case,'gpt-6-astra','high'),s.payload({'task':'Calculate 1+2'},'gpt-5.6-sol','high')]:
            self.assertNotEqual(s.hash_value(p),s.hash_value(other))

    def test_all_generators_validate_and_stay_within_projection(self):
        data=cases.generate()
        self.assertEqual(len(data),150)
        self.assertEqual(len({c['task'] for c in data}),150)
        self.assertEqual({c['family'] for c in data},set(cases.FAMILIES))
        self.assertTrue(all(len(s.prompt(c))<=500 for c in data))


if __name__=='__main__':unittest.main()
