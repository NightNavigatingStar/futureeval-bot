"""Which questions this bot has already forecasted.

Why a local file
----------------
Bot-only tournaments ask for one forecast per question, so a re-run must not
re-submit. `MetaculusQuestion.already_forecasted` is the natural signal, but it
is only populated by the per-question endpoint: the series list payload has no
`my_forecasts`, and fetching details for ~85 questions trips Metaculus' rate
limiter (HTTP 429 / Cloudflare 1015), with retry backoff so slow the sweep never
finishes.

So the bot records its own submissions. The file is written after every batch and
committed back by the workflow, which makes it survive ephemeral CI runners.
If it is lost, the cost is duplicate submissions -- noisy, not fatal.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_PATH = Path(os.getenv("FORECAST_STATE_PATH", "state/forecasted.json"))


def _read() -> dict[str, list[int]]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", STATE_PATH, exc)
        return {}


def already_forecasted(series: str) -> set[int]:
    return set(_read().get(series, []))


def record_forecasted(series: str, question_ids: list[int]) -> None:
    if not question_ids:
        return
    data = _read()
    merged = sorted(set(data.get(series, [])) | {int(q) for q in question_ids})
    data[series] = merged
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    logger.info("Recorded %d forecasted questions for %r (total %d)",
                len(question_ids), series, len(merged))
