# Laya Codex Router

[![ci](https://github.com/mcmcmcmmmc/laya-codex-router/actions/workflows/ci.yml/badge.svg)](https://github.com/mcmcmcmmmc/laya-codex-router/actions/workflows/ci.yml)

**Per-turn model routing for Codex, driven locally by [Laya](https://github.com/NandhaKishorM/laya).**

Laya chooses a model and thinking effort together for each model call, including
continuations after tools. Every route uses standard speed. The objective is
sufficient capability for the next decision with no unnecessary quota consumption.

The router still keeps the original Jev backend as an optional compatibility
path. Laya is the default even when
`~/.codex/codex-router/decision-backend` does not exist; local inference does
not call TypeSafe and does not consume GPT or ChatGPT tokens. The `jev/auto`
slug stays for compatibility with existing Codex Router state, while the picker
displays **Laya Codex Router**.

**Historical simulation: ≈ −60 % vs full Astra** on 237 turns under the old
policy. This is not measured Codex quota saved, nor evidence for the current
policy — protocol and limitations in [BACKTEST.md](BACKTEST.md).
Installing with an AI agent? Hand it [AGENTS.md](AGENTS.md).

This repository is based on
[0xNatoshi/jev-codex-router](https://github.com/0xNatoshi/jev-codex-router)
and retains its MIT notice. The Laya runtime comes from
[NandhaKishorM/laya](https://github.com/NandhaKishorM/laya) under Apache-2.0;
its source and model weights are downloaded separately and are not bundled
here. This extension plugs into an existing local **Codex Router** installation
through its generic-provider and curated-model extension points, so router
updates do not overwrite it.

## How it works

```
Codex ──▶ Codex Router (:4202)
            ├─ native models ──────────────▶ ChatGPT backend (your plan)
            └─ "jev/auto" ─▶ LiteLLM ─▶ API forwarder
                                     │
                                     ▼
                          jev_server.py (127.0.0.1:4319)
                            ├─ compact decision state ─▶ Laya (local)
                            │                           └─ model + effort
                            │
                            └─ canonical Codex replay + decision
                               └─▶ local caller edge (shared native session)
                                    └─▶ luna / sol / astra
```

- **Responses in, Responses out** — no format conversion; the SSE stream is
  relayed verbatim, so tool calls, reasoning and compaction behave natively.
- **Two independent projections** — the decision backend sees only the bounded decision state.
  The executing model receives the complete canonical replay held by Codex:
  instructions, history or compaction handoff, tool calls and tool results.
  The upstream Codex Router must therefore exempt the exact `jev/auto` route
  from conversation windowing and tool-result aging; those optimizations would
  otherwise destroy context before this server could relay it.
- **Fail-open** — any decision-backend error keeps the turn alive through the
  separately logged fallback route.
- **Kill switch** — a sentinel file bypasses the decision backend instantly.
- **Codex-dry tandem** — when native (ChatGPT) usage is exhausted (sentinel
  file, or an observed 429 / usage-limit response), the triptych is replaced:
  GLM (`opencode-go/glm-5.3-flash`) for frontier-tier steps, deepseek
  (`opencode-go/deepseek-v4.1-flash`) for everything else. The failed call is
  retried on the tandem, at the thinking depth the backend decided, mapped onto the Go
  models' own ladder; a tandem call that comes back retryable is tried once on
  the sibling model before the turn is lost. The next successful native call
  clears an auto flip.
- **Decision log** — every routed turn is logged locally for calibration
  (`~/.codex/codex-router/jev-router-live.jsonl`), never published.

## Laya backend

The Laya backend is the default for this fork. It loads the multilingual
checkpoint from `~/github/laya/models/multilingual` in offline mode, evaluates
the same 15 model/effort choices used by the router policy, and returns the
selected native Codex model to the local caller edge. The first load is slow
because the checkpoint is large; warm requests are local and do not need a
TypeSafe API key.

The backend is selected by a local state file:

```bash
printf 'laya\n' > ~/.codex/codex-router/decision-backend
curl -s http://127.0.0.1:4319/health
# ... "decision_backend":"laya"
```

The visible response header starts with
`**[Router] gpt-5.6-luna | high | Laya local**`, so the model, effort and
backend are visible in the Codex conversation. The decision log adds
`decision_backend` and bounded `decision_error` fields. Laya routing is a
local classifier decision; it is not evidence that the selected model will
finish every task correctly, so evaluate quality on completed tasks.

## Let Codex install it

Copy the prompt below into Codex. It is deliberately explicit about the
checkout paths, local-only model inference, health checks and secret handling.
The prompt assumes the public repository will be published as
`https://github.com/mcmcmcmmmc/laya-codex-router`.

```text
Install and verify the public Laya Codex Router from:
https://github.com/mcmcmcmmmc/laya-codex-router

You are operating on macOS. Read the repository's AGENTS.md before changing
anything and keep all services bound to 127.0.0.1.

Use these checkouts:
- router: ~/github/laya-codex-router
- Laya package and model runtime: ~/github/laya
- the existing local Codex Router checkout: discover it under ~/github before
  changing any generated state

Do the following:
1. Clone or fast-forward the router repository into ~/github/laya-codex-router.
2. Run `bash server/install-laya-runtime.sh` from the router checkout. It must
   clone or fast-forward https://github.com/NandhaKishorM/laya into
   `~/github/laya`, create its virtual environment, install the package, and
   download the public multilingual checkpoint to the path the service reads
   and finish with `Laya runtime OK`. Do not ask for or print Hugging Face,
   TypeSafe, Codex, or ChatGPT tokens.
3. Confirm that `~/github/laya/.venv/bin/python` can import both `laya` and
   `server/laya_backend.py`. Set
   `~/.codex/codex-router/decision-backend` to exactly `laya`.
4. Register the existing local router provider and model through its documented
   CLI extension points. Preserve existing user models and generated managed
   blocks; do not hand-edit generated files. Share the existing native session
   only if it is already authorized by the user.
5. Start or reload `server/jev_server.py` using the user's own Terminal when
   launchd requires it. Verify:
   - `GET http://127.0.0.1:4319/health` returns HTTP 200 and
     `"decision_backend":"laya"`;
   - `GET http://127.0.0.1:4319/v1/models` succeeds;
   - the existing Codex Router health endpoint remains healthy;
   - one streamed end-to-end request completes with `response.completed`.
6. Run the repository's unit tests, including the Laya backend tests. Report
   exact pass/fail counts and the selected model from the end-to-end request.
7. Confirm that the first visible response line has the form
   `[Router] <native-model> | <effort> | Laya local`.
8. Do not claim installation succeeded unless the health and end-to-end checks
    pass. Do not publish local logs, prompt excerpts, model weights, caches,
    launchd plists, or secrets.

At the end, report the checkout paths, the backend health response (with secret
values removed), the test result, and any step that still requires the user to
run a command in their own Terminal.
```

## Routing policy

`joint-v2-quality` prioritizes correct completion of the whole turn. It asks
the decision backend to assess interacting constraints, exhaustive coverage and available
verification before choosing a model. Official model positioning and the local
development evidence are separated in [ROUTING_POLICY.md](ROUTING_POLICY.md),
which also documents the paired live evaluation and its limits.

The shared contract in `server/routing_policy.py` gives the decision backend
15 explicit pairs: Luna, Sol or Astra × low, medium, high, xhigh or max
thinking. Laya or Jev chooses the pair in one Choice question, using capability profiles and the current request,
recent assistant intent, and the available tool result. Every pair uses standard
speed, overriding an incoming Fast setting, including retries and bypass modes.

There is no preferred model, target distribution, keyword-to-model rule,
low-confidence fallback to Sol, mechanical-step exception, or compaction pin.
A valid decision is applied unchanged even when several pairs are close. Jev's
confidence and full choice distribution are logged separately; neither is a
measured probability that the selected model will successfully finish the task.

The model descriptions are capability priors, not calibrated success rates.
The policy must be evaluated on completed tasks, errors and deadlines,
not on a desired model share or artificially high confidence. Schema
checks and synthetic routing samples establish wiring, not equal-quality savings.
A missing/invalid decision response or a provider error still uses the
separately logged technical fail-open route (Astra at medium); the manual kill switch and
native-quota exhaustion are operational bypasses, not Jev decisions.

### Codex-dry tandem — only while native usage is exhausted

The triptych is the policy **unless** the ChatGPT usage window is exhausted
(manual sentinel file, or an automatic flip on a 429 / usage-limit response,
which also retries the failed call on the tandem). While dry:

| Native tier | Dry substitute |
|---|---|
| `gpt-6-astra` (frontier) | `opencode-go/glm-5.3-flash` |
| `gpt-5.6-sol` / `gpt-5.6-luna` | `opencode-go/deepseek-v4.1-flash` |

An automatic flip lasts until the instant the edge announced for the window
reset, so the first call after the quota returns is served by the triptych
again; when a refusal announces no instant it falls back to a 30-minute
re-probe, and a week is the ceiling on anything a refusal claims. It is cleared
by the first successful native call, and the manual sentinel file is never
auto-cleared.

Two details keep the substitute transparent. The decided depth travels with the
call, mapped onto the Go ladder — `low` stays `low`, `medium` and `high` become
`high`, `xhigh` or above become `max` — because those models declare three rungs
where the triptych exposes five, and the API forwarder clamps the value once more
onto the route's own ladder. And a tandem call that comes back retryable
(429/5xx) is tried once on the sibling model: opencode Go meters the two Go
models against separate allowances and reports a spent one the same way it
reports a transient outage. If both refuse, the caller receives that refusal
rather than a request nobody answers.

A third detail keeps the relay legal for the Responses consumer in front of it.
A dry turn crosses the local edge, which encodes response ids, so the terminal
event of the stream the relay receives repeats the id under a fresh encoding.
Read as-is, that is a completion that renamed its own response, and the consumer
replaces the finished turn with an `invalid_responses_stream` error; the relay
therefore rewrites the terminal id onto the one `response.created` announced.
Native turns are untouched — their ids already match.

## Measuring what it served

The router logs one JSON line per decision (`~/.codex/codex-router/jev-router-live.jsonl`).
`server/report_routing.py` turns that log into the routing/savings report — the
table a third party can reproduce on their own machine:

```bash
python3 server/report_routing.py --days 7          # text tables (default window)
python3 server/report_routing.py --days 30 --json  # machine-readable
```

It prints the served model distribution (luna/sol/astra, plus the Codex-dry
tandem when it took over: turns + %), the share of turns served by the cheapest
tier, the share of turns held below the confidence gate, the gates encountered,
median latency (end-to-end and Jev's own decision time), and an estimate of the
real cost against two counterfactuals — every turn on `gpt-6-astra`, and every
turn on `gpt-5.6-sol`.

New log entries record a versioned decision and each upstream attempt's model,
effort, standard speed, terminal event and token usage when the provider reports
it. Only numeric usage counters are retained. Unknown usage is not counted as
zero, retries are retained, and reasoning tokens are already included in output.
The report estimates standard ChatGPT credits from these observed tokens against
all-Sol and all-Astra counterfactuals. External fallback calls are excluded from
that comparison. These are published-rate estimates, not observed account debits;
counterfactual token volumes and task quality have not been experimentally measured.

Historical entries without usage keep a separate fixed-volume API-rate proxy.
Their logged Fast speed retains its surcharge instead of being repriced by the
new policy. The old backtest is clearly labelled as a simulation. Current replay
scripts share the live decision contract and reject a cache from another policy.

Routing is turn-scoped: the call that opens a turn (a user message) gets one
backend decision, and every continuation of that turn — tool steps, retries,
and the call that follows a mid-turn compaction — reuses it, so the serving
model cannot flip mid-turn. A new user ask opens the next turn; an entry that
reused the turn's route carries `sticky: true` and the `gate` of the decision
that opened it. The compact projection sent to the decision backend (task,
signals, tool digest) is judgement input
only: it is never reused as an execution prompt. The executing model always
receives the caller's canonical request, with only the selected model, reasoning
effort, standard service tier and required streaming flag applied to the relay.

## Ask surface (`POST /ask`)

The server also answers typed questions directly through the selected decision
backend, for local callers that bring their own question set. The Laya backend
answers locally. The optional Jev backend sends the bounded typed request to
System One.

```sh
curl -s http://127.0.0.1:4319/ask -X POST -H 'Content-Type: application/json' \
  -d '{"state":{"goal":"open the docs"},"questions":{"next":{"type":"choice","instructions":"Which element advances the goal?","criteria":{"e5":"link Documentation"}}}}'
# → {"model":"jev-1.13.0","answers":{"next":{...}},"usage":{...},"ms":612}
```

Validation is the whole contract: a JSON-serialisable `state` under 120k chars,
at most 40 questions, each a `noul`, `choice` or `score` with its instructions
and criteria. The caller's state is never logged. With the optional Jev backend,
`502` surfaces an upstream failure (`402` means the TypeSafe account is out of
credits) and `503` means no key is configured.

## Repository layout

```
BACKTEST.md  Savings backtest — protocol, tables, limitations (the "proof")
AGENTS.md    Autonomous install & operations playbook (for AI agents)
poc/         Tiering POC, shadow replay, and the backtest tool
server/      The live server + service install (this is what runs)
hook/        Explored alternative (LiteLLM callback tap) — kept for reference
```

## Quickstart

Prerequisites: macOS, a Codex desktop install wired to a **Codex Router**
(checkout with `bin/codex-router`) and Python 3.11+. A TypeSafe API key is
needed only when deliberately selecting the optional Jev backend.

**1. Install Laya and select the decision backend.** The Laya variant does not
require a TypeSafe key:

```bash
bash server/install-laya-runtime.sh
printf 'laya\n' > ~/.codex/codex-router/decision-backend
```

The original Jev backend remains available if you deliberately set the file to
`jev`; only then does the server read `TYPESAFE_API_KEY`.

**2. Start the server** (foreground test):

```bash
../laya/.venv/bin/python server/jev_server.py
curl -s http://127.0.0.1:4319/health
```

For the optional Jev backend, give the server your TypeSafe key — either
`export TYPESAFE_API_KEY=...` in the service environment, or:

```bash
echo 'TYPESAFE_API_KEY=your-key' >> ~/.hermes/.env   # default env file
# (override the path with JEV_ENV_FILE=/path/to/env)
```

**3. Register with the Codex Router:**

```bash
cd <codex-router checkout>

# share the native ChatGPT session with local clients (revisit if it expires)
./bin/codex-router chatgpt-session enable

# declare the generic provider (our local server, native Responses format)
./bin/codex-router providers generic add jev \
  --name "Laya Router" --base-url http://127.0.0.1:4319/v1 \
  --adapter openai-responses --allow-private

# declare the model: ~/.codex/codex-router/user-models.json
# (this file is local state — router updates won't touch it)
```

```json
{
  "version": 1,
  "models": [
    {
      "slug": "jev/auto",
      "gatewayModel": "jev-auto",
      "compHash": "jev-auto-user-v1",
      "upstreamModel": "auto",
      "provider": "jev",
      "listed": true,
      "displayName": "Laya Codex Router",
      "description": "Local routing by Laya: every turn is classified and served by luna, sol or astra at the thinking depth it needs.",
      "priority": 95,
      "defaultEffort": "medium",
      "reasoningLevels": [
        { "effort": "low", "description": "Quick reasoning" },
        { "effort": "medium", "description": "Balanced reasoning" },
        { "effort": "high", "description": "Deep reasoning" },
        { "effort": "xhigh", "description": "Extended reasoning" },
        { "effort": "max", "description": "Maximum reasoning" }
      ],
      "contextWindow": 258400,
      "autoCompact": 219640,
      "inputModalities": ["text", "image"]
    }
  ]
}
```

```bash
# publish the catalog and make the model visible in the picker
./bin/codex-router refresh-catalog
./bin/control picker set jev/auto show
```

**4. Quit and reopen Codex**, then pick **“Laya Codex Router”** in the model picker.
Check the transport as well as the picker: `jev/auto` must reach the local
router, not OpenAI's native endpoint. A catalog entry or a
`[model_providers.jev]` declaration alone does not select that transport.
See [transport troubleshooting](server/INSTALL.md#model-visible-but-rejected-by-chatgpt)
if Codex reports that `jev/auto` is unsupported with a ChatGPT account.

**5. Make it permanent** (optional but recommended): run the service installer
in your own Terminal (launchd management is intentionally restricted inside
supervised agents):

```bash
bash server/install-service.sh
```

Without it, `server/watchdog.sh` (cron every 5 min) restarts the server if it
stops answering.

## Operations

| Action | Command |
|---|---|
| Watch decisions | `tail -f ~/.codex/codex-router/jev-router-live.jsonl` |
| See the picked model in the thread | every reasoning summary part carries the routed tag, separators on both sides: ` · 🧠sol:low · ` — one glyph per route: ⚡ luna (economical) · 🧠 sol (workhorse) · 🚀 astra (frontier) · 🌍 terra; 🐳 deepseek / ✨ glm while the Codex-dry tandem is serving |
| Show the model and thinking above every assistant message | Enabled by default — a leading `**🧠 sol · thinking: high**` appears from the first text fragment, including commentary and unphased replies. Create `~/.codex/codex-router/jev-router.signature.off` to disable |
| Shadow mode (decide + log, serve astra) | `touch ~/.codex/codex-router/jev-router.shadow` |
| Debug capture (shapes + raw streams) | `touch ~/.codex/codex-router/jev-router.debug` |
| Kill switch (bypass decision backend → frontier) | `touch ~/.codex/codex-router/jev-router.off` (delete the file to re-enable) |
| Force the Codex-dry tandem | `touch ~/.codex/codex-router/jev-router.codex-dry` (delete the file to return to luna/sol/astra) |
| Inspect the dry auto state | `cat ~/.codex/codex-router/jev-router.codex-dry.json` (reason + expiry; auto-cleared by the next successful native call) |
| Hide the model | `./bin/control picker set jev/auto hide` |
| Disable the provider | `./bin/codex-router providers generic disable jev` |
| Revoke native sharing | `./bin/codex-router chatgpt-session disable` |
| Service status | `launchctl print gui/$(id -u)/com.thibaultsaintjean.jev-router` |

**After a Codex Router update**, verify nothing was lost:

```bash
./bin/codex-router providers generic list        # shows: SHOW jev
cat ~/.codex/codex-router/model-picker.json      # jev/auto in "visible"
curl -s http://127.0.0.1:4319/health
```

## Notes & quirks

- The router's local edge requires `stream: true` — the server always forces it.
- The edge returns SSE with **no Content-Type header**; the server re-emits
  `text/event-stream` because the API forwarder picks its parser from it
  (otherwise it tries to JSON-parse the stream and fails with
  `invalid_responses_response`).
- The shared ChatGPT session authorization has a validity window; re-run
  `chatgpt-session enable` if native routing stops after a while.
- Code comments are in French for now (author's working language) — PRs welcome.

## Security

- **No secrets in this repository.** The server reads `TYPESAFE_API_KEY` from an
  env file or the process environment; everything else stays on your machine.
- The server binds `127.0.0.1` only, talks to your local Codex Router only, and
  never logs prompt content beyond a short task excerpt used for calibration.
- Local decision logs and replay data are git-ignored by default.

## Status

Early, but running in production on the author's setup. The joint routing policy needs outcome calibration on real usage; the local
decision and attempt logs provide observations, not quality labels.

## License

MIT
