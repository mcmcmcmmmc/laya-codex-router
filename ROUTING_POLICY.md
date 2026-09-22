# Quality-first routing experiment

`joint-v2-quality` changes the question sent to Jev. It does not train Jev,
override a valid answer, reinterpret confidence as accuracy, or force a model
using keywords. All 15 model/effort pairs remain available at standard speed.

## Evidence and intended change

Official OpenAI documentation, checked 2026-09-21:

- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna):
  high-volume, cost-sensitive positioning, corresponding roughly to the earlier
  nano tier.
- [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol):
  flagship GPT-5.6 model for complex professional work.
- [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra):
  most capable model, covering difficult reasoning and end-to-end work.

These are provider capability descriptions, not task-specific accuracy or
latency guarantees. The operational examples in the policy are our hypotheses.

A local six-task development comparison found Astra-high completed all six,
while Sol-high completed four correctly, made one exact-calculation error, and
hit a 180-second client deadline once. Auto also completed all six, but its one
Astra call came from a provider error rather than a successful Jev decision.
Three subsequent routing-only probes of the deadline case selected Sol-high.
These are small, single-trial observations, not general model success rates;
Sol's timeout does not establish that it could never solve that problem.

The revised question therefore assesses the whole remaining turn (matching the
existing sticky-turn implementation), distinguishes producing one plausible
answer from checking completeness, asks about available verification, and makes
result quality the primary objective. It allows Astra when adequacy of a weaker
model is uncertain on demanding work. It keeps easy tasks eligible for Luna.
No original task text, answer, task ID, benchmark score, or numerical confidence
cutoff is embedded in the live routing question.

## Evaluation and limits

`evals/quality_compare.py` compares the frozen original question with the new
one through two isolated instances of the real Jev HTTP handler. Both relay to
the same locally authenticated Codex Router. They use separate logs/turn caches
and never replace the running service during evaluation. The baseline question
is stored in `evals/policies/joint-v1-standard.json`.

The evaluation freezes tasks, exact oracles, policy hashes, request ordering,
and acceptance criteria before any paid/model call. It includes development
regressions, newly authored easy/medium controls, and held-out parameter variants
of two hard task families. Those variants test transfer within a family, not
generalization to unseen domains. Both arms receive the same prompt and deadline.
Each task is repeated twice. Model answers are checked by strict JSON equality,
including types, with no model-based judge. Oracles are never sent to the router.
Concurrency is limited to two client requests. An upstream generation may
continue after the client deadline; the existing relay does not guarantee
immediate upstream cancellation. A timed-out call can lack its final route log;
retain the observed model and mark missing routing metadata explicitly.

Primary outcome: correct completion within 180 seconds. Report wrong answers,
timeouts, infrastructure failures, active selections, and technical fallbacks
separately. More Astra calls alone do not establish improvement. Promotion needs
more correct completions, no loss on easy controls, and no technical fallback
confound in either arm. A small synthetic sample cannot prove production quality.

Run the offline suite with `python3 -m unittest discover -s server`.
The live evaluator requires existing local TypeSafe credentials and authorized
ChatGPT session sharing; it never prints credentials. Run its `--help` first.
Raw outputs belong under the git-ignored `local-install/` directory.

```bash
python3 evals/quality_compare.py freeze \
  --output local-install/quality-comparison \
  --development-cases evals/development_cases.json
python3 evals/quality_compare.py run --output local-install/quality-comparison
python3 evals/quality_compare.py report --output local-install/quality-comparison
```

Use a new output directory for each run. `run` makes 48 real routed model calls;
`freeze`, `report`, and `python3 -m unittest discover -s evals` are offline.
The two evaluation relays bind only `127.0.0.1:14319` and `127.0.0.1:14320`.

Remaining limitations: 500-character routing projection, no answer verifier,
no mid-turn quality-based escalation, and diagnostic-only confidence. These are
unchanged so this experiment isolates the routing-question change.

## 2026-09-21 result and subsequent transport change

The frozen 48-call experiment returned 16/24 correct, five wrong and three
timeouts for the baseline, versus 24/24 correct for the candidate. Each arm had
three technical fallbacks. Only 16 paired trials had complete, normal routing
records in both arms: baseline 12/16, candidate 16/16. Two of those four wins
used the same Sol-high pair on both sides, so generation variance is a plausible
explanation for part of the observed gain. The other two switched Luna-medium
to Sol-medium. These data are encouraging, not a reliable general accuracy rate.

The strict automatic promotion gate failed because technical fallbacks and
missing timeout logs occurred. The running background service is not replaced
automatically by these evaluation commands. Raw records remain in the local
evaluation directory; the candidate is available in source for review/testing.

After freezing those results, the routed Jev socket-I/O timeout was raised from
4 to 10 seconds; `/ask` retains its independent 15-second timeout. Safe error
categories distinguish timeout, DNS, TLS, HTTP, network and invalid-response
failures without logging raw exceptions, URLs or credentials. The original
48-call outcome comparison did not include this transport change.

`python3 evals/recheck_routes.py local-install/quality-v2-20260921` made 24
supplemental Jev-only calls (no answer-model calls), all successful. Both
questions used the new timeout. Candidate selected Astra-high for both game
tasks and scheduling; baseline selected Sol-high. Every supplemental call took
less than four seconds, so this run does not establish that the longer timeout
resolved the original transient failures. It is not substituted into the first
experiment's missing or fallback records.
