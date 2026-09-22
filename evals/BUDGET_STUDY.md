# 250-call paired study

## Question and estimand

Does `joint-v2-quality` increase the chance of a correct, complete answer within
180 seconds relative to the frozen `joint-v1-standard` question? Both arms use
the same current relay, 10-second routing I/O timeout, standard speed, no tools,
and technical-failure fallback to Astra-medium. This isolates the routing
question; it is not a load test or a comparison of the old 4-second transport
against the new transport. Model/effort selection remains entirely Jev's.

The target population is the explicitly defined synthetic task mixture below,
not all coding, research, visual, or multi-turn user work. The candidate policy
is frozen before new data; the earlier 12 tasks are development evidence and
are not added to this test's sample size.

## Sample and cost

Prepare 150 distinct randomized tasks from twelve families: arithmetic, record
filtering, overlapping text matches, code execution traces, shortest paths,
topological orders, weighted intervals, Boolean model counting, assignment,
modular constraints, absorbing Markov chains, and history-dependent games.
Each task has a programmatically computed answer; nontrivial oracles use
independent algorithms or independent numerical checks. No answer is sent to
either router or executing model. All full prompts fit the existing 500-character
routing projection. Per-family results and leave-one-family-out sensitivity are
mandatory because parameter variants are not unrelated task families.

Two independent routing decisions are requested for each task (300 calls).
Before generating any answer, compute the required number of unique execution
payloads for the prefixes 40, 80, 120, and 150. Select the largest prefix fitting
240 answer requests. Thus at least 120 tasks fit the request budget in the
absence of other stop conditions; 150 may fit through deduplication. Reserve
10 requests for a separately reported audit through the real HTTP relay.

Hard limits: 250 answer-request dispatches, including failed attempts and audit;
310 Jev routing calls, including audit. No user-initiated retries, quota resets,
account purchases or provider switching in the audit. An append-only ledger
claims a slot before dispatch, under a lock. Completed identical execution
payloads share one sampled answer across policies, but never across different
tasks, models or effort settings. A shared answer counts once toward actual
experiment spend. It can count toward both policies' logical outcomes; it is
not counted as two independent task samples or as production cost savings.

The native router strips `max_output_tokens` (`codex-router/src/router.mjs`),
so this is not a hard token or dollar cap. Monitor observed output tokens and
stop dispatch at 180,000 observed tokens; this is a soft threshold because an
in-flight or timed-out response may use unobserved tokens. Check shared account
usage at every stage: starting used=49%, stop at used>=57% or remaining<=35%.
This account-level signal includes unrelated activity. Missing usage is unknown.
The 180-second client deadline does not guarantee immediate upstream cancellation.

## Paired design and generation variance

If both policies choose exactly the same canonical execution request (including
model, effort, prompt, service tier and tools), generate one answer and assign it
to both arms. This couples identical treatments and prevents independent random
answers on the same Sol-high route from masquerading as a routing improvement.
If requests differ, generate both in randomized order. Use at most two concurrent
client requests. This estimates the difference in expected success under the
specified coupling; it does not estimate natural independent-run variance.

Log the routing result before answer generation. Preserve infrastructure errors,
fallbacks, timeouts and incomplete outputs in the primary result. Also report
the matched subset where both routes were normal; never silently replace or
drop a failed arm. Fail fast during routing after three consecutive errors or
an error rate above 10% after at least twenty observations, avoiding a benchmark
that mostly measures outages. Stop answer dispatch on authentication/quota
errors, model identity mismatch, or unexplained response failure.

## Sequential decisions

The 40-task checkpoint is operational only. No superiority claim before 80
tasks. At non-final checks at 80 or 120, use two-sided exact McNemar p<=.005.
At the final budget-feasible checkpoint use p<=.04. There are at most three
formal looks; their alpha allocations sum to at most .05 (Bonferroni/union bound).
This avoids repeatedly checking unadjusted p<.05 until it happens to pass.

Count candidate-only correct tasks as wins, baseline-only correct as losses.
The exact test is the symmetric binomial test on wins/(wins+losses).
Superiority requires both the allocated p threshold and >=5 percentage points
net improvement. Broad-in-mixture improvement additionally needs positive net
gains in at least three families and no observed regression in the three easy
families; otherwise report localized evidence, not broad improvement. A
significant >=5-point regression stops for harm.

For a cost-saving futility stop, use the allocated-alpha one-sided exact upper
bound on the candidate-only win probability. If even that upper bound is <.05,
stop without a superiority claim. This is not an equivalence test. At a budget
or infrastructure stop without an adjusted success decision, report inconclusive.
Family-level outcomes are descriptive, not multiple new significance tests.

The hypothesis applies to this generated mixture. Template effects, a modest
number of families, lack of repeated model draws on each task, and the single
account/time period limit generalization. Official capability descriptions are
not accuracy labels. More Astra calls is not an endpoint.

## Power, not a guarantee

Exact enumeration at the final alpha=.04 look gives the following approximate
power, assuming independent mixture draws and discordance between 15% and 25%:

| Unique tasks | True +5 points | True +10 points | True +15 points |
|---|---:|---:|---:|
| 120 | 12%-19% | 49%-76% | 89%-100% |
| 150 | 16%-24% | 61%-86% | 95%-100% |

These are assumed-effect calculations, not inferred performance. They make
explicit that this budget can detect large improvements more reliably than
small ones. Interim stopping may change total power and expected sample count.

Primary method references: [statsmodels exact McNemar](https://www.statsmodels.org/dev/generated/statsmodels.stats.contingency_tables.mcnemar.html)
and [SciPy exact binomial test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html).

## Reproduce

```bash
python3 evals/budget_study.py freeze --out local-install/budget-study-20260921
python3 evals/budget_study.py routing --out local-install/budget-study-20260921
python3 evals/budget_study.py stage --out local-install/budget-study-20260921 --n 40
# Inspect the report and account usage before each next permitted checkpoint.
python3 evals/budget_study.py audit --out local-install/budget-study-20260921
```

Use a fresh output directory for another run. `freeze` and tests are offline;
`routing`, `stage`, and `audit` consume authorized service access. Existing
dispatched requests are never silently retried. Frozen file hashes are checked
before each stage. The primary population must be a complete prefix before a
statistical decision is produced. Audit outcomes never enter its significance test.
