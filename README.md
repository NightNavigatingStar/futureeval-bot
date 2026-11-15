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
| `researcher` | `deepseek/deepseek-chat` | no search provider configured yet |
| `summarizer` | `deepseek/deepseek-chat` | temperature 0 |

Pinned in `bot_llms.py` rather than left to defaults, so the bot cannot silently fall
back to a provider whose key is not present.

Known limitation: `researcher` is a plain LLM call with no web access, so "research"
is the model's own knowledge. Adding a search API (AskNews / Exa / Perplexity) is the
obvious next improvement.

## Cadence

`.github/workflows/forecast.yaml` runs hourly (`13 * * * *`).

Why hourly: of the 152 questions in this tournament, 151 had an open window of exactly
3.0 hours. The constraint is therefore "one successful run per 3-hour window" — hourly
gives three attempts per window, which absorbs a transient failure without spending a
run every 20 minutes.

## Secrets

Repository secrets, never committed:

- `METACULUS_TOKEN` — the bot account's write token (`/accounts/settings/bots/`)
- `DEEPSEEK_API_KEY`

Local runs read the same names from `.env` (see `.env.template`).

## Running locally

```bash
pip install -r requirements.txt
python smoke.py   # dry run on one question, publishes nothing
python main.py    # real run: forecast + publish
```

`run_bot.cmd` is the Windows wrapper used by a local Task Scheduler entry; it clears
any inherited proxy variables first, since those break both PyPI and the DeepSeek endpoint.
