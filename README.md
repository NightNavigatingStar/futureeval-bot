# futureeval-bot

Entry for the **Metaculus Fall 2026 FutureEval Bot Tournament** (`fall-futureeval-2026`, tournament id 33121).

A bot, not a model submission: it polls Metaculus for open questions, forecasts each
one with an LLM, and posts that forecast through the Metaculus API. Scoring uses the
last forecast before a question closes, so coverage matters more than speed.

## What this is based on

Forked from [Metaculus/metac-bot-template](https://github.com/Metaculus/metac-bot-template)
(`FallTemplateBot2026`), which supplies the question-type handling, the research/forecast
loop, prediction aggregation, and the Metaculus API plumbing via
[forecasting-tools](https://github.com/Metaculus/forecasting-tools). The changes here are
the model wiring, the run cadence, and the environment checks.

## Configuration

| Role | Model | Notes |
|---|---|---|
| `default` (forecasting reasoning) | `deepseek/deepseek-chat` | temperature 0.3 |
| `parser` (prose -> structured prediction) | `deepseek/deepseek-chat` | temperature 0 |
| `researcher` | `deepseek/deepseek-chat` | reads web excerpts, see below |
| `summarizer` | `deepseek/deepseek-chat` | temperature 0 |

Pinned in `bot_llms.py` rather than left to defaults, so the bot cannot silently fall
back to a provider whose key is not present.

## Web research

`bot_research.py` gives the researcher something to read. The researcher LLM first
turns the question into two short keyword queries (~5 words; a full question sentence
returns dictionary entries), then `bot_research.py` searches, scrapes the top pages,
strips them to text, and hands the excerpts over as cited blocks. No paid search API is
configured: DuckDuckGo's HTML endpoint is tried first (works from CI, blocked in mainland
China), then Bing, with a per-process circuit breaker so an unreachable provider is not
re-tried for every question.

Spend is routed by how far away the question resolves, measured on 86 open MiniBench
questions on 2026-11-16:

| Horizon | Questions | Research |
|---|---|---|
| ≤ 60 days | 43 | 2 queries, 3 pages |
| 60–180 days | 3 | 1 query, 2 pages |
| > 180 days | 40 | none — base rates only |

The long-horizon cut is deliberate: questions like "how many US states in 2050?" have no
reporting that changes the answer, so scraping there buys noise at the cost of time.
Set `WEB_RESEARCH=0` to disable research entirely and get the LLM-only baseline.

## Cadence

`.github/workflows/forecast.yaml` runs hourly (`13 * * * *`).

Why hourly: of the 152 questions in this tournament, 151 had an open window of exactly
3.0 hours. The constraint is therefore "one successful run per 3-hour window" — hourly
gives three attempts per window, which absorbs a transient failure without spending a
run every 20 minutes.

## MiniBench needs a different loader

MiniBench is registered as a *question series*, not a tournament, so the SDK's
`get_all_open_questions_from_tournament("minibench")` returns **zero** questions even
when the series is open. `bot_tournaments.py` pages
`/api/posts/?question_series=minibench` instead and parses each post with the SDK's own
`DataOrganizer.get_question_from_post_json`.

It deliberately does not call `get_question_by_post_id()` per question: that is one HTTP
request each, and ~40 of them tripped Metaculus' rate limiter (HTTP 429 / Cloudflare
1015) even at four workers, after which the SDK's retry backoff cost more time than the
forecasts themselves.

## Secrets

Repository secrets, never committed:

- `METACULUS_TOKEN` — the bot account's write token (`/accounts/settings/bots/`)
- `DEEPSEEK_API_KEY`

Local runs read the same names from `.env` (see `.env.template`).

## One forecast per question

Bot-only tournaments ask for a single forecast per question, so re-runs must not
re-submit. `MetaculusQuestion.already_forecasted` cannot be used for that here: the
series list payload carries no `my_forecasts`, and asking per question costs one HTTP
request each, which trips Metaculus' rate limiter at ~85 questions.

`bot_state.py` records question ids after each batch into `state/forecasted.json`, and
the workflow commits that file back so it survives ephemeral runners. If the file is
lost, `python seed_state.py minibench` rebuilds it from the server.

## Running locally

```bash
pip install -r requirements.txt
python smoke.py            # dry run on one question, publishes nothing
python main.py             # real run: forecast + publish
python seed_state.py       # rebuild state/forecasted.json from the server
```

`run_bot.cmd` is the Windows wrapper used by a local Task Scheduler entry; it clears
any inherited proxy variables first, since those break both PyPI and the DeepSeek endpoint.
