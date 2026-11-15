"""One-off: rebuild state/forecasted.json from what Metaculus already has.

Needed when the state file is missing but the bot has already submitted
forecasts (for example after a run that predates bot_state.py). It walks the open
questions in a series and asks the per-question endpoint whether `my_forecasts`
has any history.

This is deliberately NOT part of the normal run: it costs one HTTP request per
question, and a burst of those trips Metaculus' rate limiter. The bot itself
deduplicates from the state file, which is free.

    python seed_state.py [series ...]
"""

from __future__ import annotations

import logging
import sys
import time

import dotenv
import requests

dotenv.load_dotenv()

from bot_state import already_forecasted, record_forecasted  # noqa: E402
from bot_tournaments import list_open_posts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed")

GAP_SECONDS = 1.2


def seed(series: str) -> None:
    posts = list_open_posts(series)
    known = already_forecasted(series)
    found: list[int] = []
    for index, post in enumerate(posts, 1):
        question = post.get("question") or {}
        question_id = question.get("id")
        if question_id in known:
            continue
        time.sleep(GAP_SECONDS)
        try:
            response = requests.get(
                f"https://www.metaculus.com/api/posts/{post['id']}/",
                headers={
                    "Authorization": f"Token {_token()}",
                    "User-Agent": "metaculus-futureeval-bot/1.0",
                },
                timeout=30,
            )
            response.raise_for_status()
            detail = (response.json().get("question") or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("%d/%d post %s failed: %s", index, len(posts), post["id"], exc)
            continue
        history = (detail.get("my_forecasts") or {}).get("history") or []
        if history and question_id:
            found.append(int(question_id))
        if index % 10 == 0:
            logger.info("%d/%d scanned, %d forecasted", index, len(posts), len(found))
    record_forecasted(series, found)
    logger.info("%r: seeded %d forecasted questions", series, len(found))


def _token() -> str:
    import os

    return os.environ["METACULUS_TOKEN"].strip()


if __name__ == "__main__":
    for name in sys.argv[1:] or ["minibench"]:
        seed(name)
