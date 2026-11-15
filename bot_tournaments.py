"""Load open questions from a Metaculus "question series" (e.g. MiniBench).

Why this exists
---------------
`forecasting_tools.MetaculusClient.get_all_open_questions_from_tournament()` maps
to `/api/posts/?tournaments=<slug>`. MiniBench is registered as a *question
series*, not a tournament, so that filter returns zero posts even though the
series has dozens of open questions. Verified 2026-11-16:

    client.get_all_open_questions_from_tournament("minibench")  -> 0 questions
    GET /api/posts/?question_series=minibench                   -> 41 open

Why it does not hydrate per question
------------------------------------
The obvious fix is `get_question_by_post_id()` per open question, but that is one
HTTP round-trip each: ~40 requests tripped Metaculus' rate limiter (HTTP 429 /
Cloudflare 1015) even at 4 workers, and the SDK's retry backoff then cost more
wall-clock time than the forecasts themselves. The list endpoint already returns
complete question objects, and the SDK ships a parser for exactly that shape
(`DataOrganizer.get_question_from_post_json`), so paging the list a few times is
enough -- no per-question requests at all.
"""

from __future__ import annotations

import logging

import requests
from forecasting_tools import DataOrganizer, MetaculusClient, MetaculusQuestion

logger = logging.getLogger(__name__)

API_BASE = "https://www.metaculus.com/api/posts/"
USER_AGENT = "metaculus-futureeval-bot/1.0"
PAGE_SIZE = 100
MAX_PAGES = 6


def list_open_posts(series: str, max_pages: int = MAX_PAGES) -> list[dict]:
    """Raw post payloads for questions that are currently open in the series.

    The API's `statuses=open` filter refers to the *post* lifecycle, not the
    question: passing it returned 100 posts of which 39 were open questions.
    Filtering on question.status is what actually matches the site.
    """
    token = _token()
    posts: list[dict] = []
    for page in range(max_pages):
        params = {
            "question_series": series,
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
        }
        try:
            response = requests.get(
                API_BASE,
                params=params,
                headers={"Authorization": f"Token {token}", "User-Agent": USER_AGENT},
                timeout=45,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - one bad fetch must not kill the run
            logger.error("Could not list series %r page %d: %s", series, page, exc)
            break
        batch = response.json().get("results") or []
        posts.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    open_posts = [p for p in posts if (p.get("question") or {}).get("status") == "open"]
    logger.info(
        "Series %r: %d posts scanned, %d open questions",
        series,
        len(posts),
        len(open_posts),
    )
    return open_posts


def load_open_questions_from_series(
    series: str, client: MetaculusClient | None = None
) -> list[MetaculusQuestion]:
    """Return typed question objects for every open question in the series."""
    del client  # kept for call-site compatibility; parsing needs no HTTP client
    questions: list[MetaculusQuestion] = []
    for post in list_open_posts(series):
        try:
            questions.append(DataOrganizer.get_question_from_post_json(post))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping post %s: %s", post.get("id"), exc)
    logger.info("Series %r: parsed %d questions", series, len(questions))
    return questions


def _token() -> str:
    import os

    token = os.getenv("METACULUS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("METACULUS_TOKEN is not set")
    return token
