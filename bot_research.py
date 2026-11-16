"""Free web research for the forecasting bot.

Why this exists
---------------
The top-scoring open-source bot in this benchmark (nostreambot, top 10th
percentile three seasons running) reports that research *breadth* is the driver
of its edge: ablations showed gap-fill research beat no research at statistical
significance, and two independent research sources beat either alone. The
template bot has no research source at all -- its "researcher" is a bare LLM call
with no web access, so every forecast comes from parametric memory.

Two backends, tried in order
----------------------------
1. **DeepSeek's Search API** (`POST /v1/tools/search`, `need_content=true`). It
   returns the page text itself, so no scraping is involved. Bills at $0.75 per
   1000 successful requests -- about $0.0015 for a two-query question -- and runs
   on api.deepseek.com, which is reachable from networks where DuckDuckGo is
   blocked and where Bing serves bot-detection pages.
2. **Scraping DuckDuckGo's HTML endpoint, then Bing.** Free, and it works from
   GitHub's runners, but from a mainland-China connection DuckDuckGo times out and
   Bing redirects to cn.bing.com and returns unrelated results (cricket scores for
   an Ibovespa query, observed 2026-11-16). Kept as the fallback so the bot still
   researches something when no DeepSeek key is present.

Design constraints
------------------
- Never raise. Any failure returns "" and the bot falls back to LLM-only research,
  because losing a forecast is worse than forecasting without research.
- Hard time budget. A run must finish inside the 3-hour question window, so
  providers have short timeouts and a provider that fails once is skipped for the
  rest of the process.
- Search quality dominates page quality: feeding a whole question sentence as the
  query returns dictionary definitions, so queries are short keyword strings
  produced by the LLM upstream (see main.py).
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, unquote, urlparse

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)

MAX_PAGES = 3
MAX_CHARS_PER_PAGE = 3500
SEARCH_TIMEOUT = 8
PAGE_TIMEOUT = 10
TOTAL_BUDGET_SECONDS = 60
DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
DEEPSEEK_SEARCH_TIMEOUT = 30

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[\s\S]*?</\1>", re.I)
_WS_RE = re.compile(r"\s+")
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[\s\S]{0,400}?>(.*?)</a>', re.I
)
_BING_BLOCK_RE = re.compile(r'<li class="b_algo"[\s\S]{0,3000}?</li>', re.I)
_BING_LINK_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.I
)

# Provider health, per process. DuckDuckGo is unreachable from mainland China
# networks; without this the bot would burn 8s per question rediscovering that.
_PROVIDER_DOWN: dict[str, float] = {}
_PROVIDER_COOLDOWN = 3600  # seconds before a failed provider is retried


def _provider_available(name: str) -> bool:
    failed_at = _PROVIDER_DOWN.get(name)
    return failed_at is None or (time.time() - failed_at) > _PROVIDER_COOLDOWN


def _clean_html(raw: str) -> str:
    text = _SCRIPT_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _unwrap_ddg_link(href: str) -> str:
    """DuckDuckGo wraps outbound links as /l/?uddg=<encoded url>."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        query = parse_qs(urlparse(href).query)
        if "uddg" in query:
            return unquote(query["uddg"][0])
    return href


def _get(url: str, params: dict | None = None, timeout: int = SEARCH_TIMEOUT):
    try:
        return requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - research must never break a forecast
        logger.warning("search request failed (%s): %s", url, exc)
        return None


def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
    if not _provider_available("ddg"):
        return []
    response = _get("https://html.duckduckgo.com/html/", {"q": query})
    if response is None or response.status_code != 200:
        _PROVIDER_DOWN["ddg"] = time.time()
        logger.warning("DuckDuckGo marked down for %ss", _PROVIDER_COOLDOWN)
        return []
    hits = []
    for href, title_html in _DDG_RESULT_RE.findall(response.text):
        url = _unwrap_ddg_link(href)
        title = _clean_html(title_html)
        if url.startswith("http") and title:
            hits.append({"title": title, "url": url})
        if len(hits) >= max_results:
            break
    return hits


def _search_bing(query: str, max_results: int) -> list[dict]:
    if not _provider_available("bing"):
        return []
    response = _get("https://www.bing.com/search", {"q": query, "setlang": "en"})
    if response is None or response.status_code != 200:
        _PROVIDER_DOWN["bing"] = time.time()
        return []
    hits = []
    for block in _BING_BLOCK_RE.findall(response.text):
        match = _BING_LINK_RE.search(block)
        if not match:
            continue
        url, title = match.group(1), _clean_html(match.group(2))
        if url.startswith("http") and title and "bing.com" not in url:
            hits.append({"title": title, "url": url})
        if len(hits) >= max_results:
            break
    return hits


def search(query: str, max_results: int = MAX_PAGES) -> list[dict]:
    """Try each provider in quality order; return the first non-empty result set."""
    for name, provider in (("ddg", _search_duckduckgo), ("bing", _search_bing)):
        hits = provider(query, max_results)
        if hits:
            logger.info("search via %s for %r: %d hits", name, query, len(hits))
            return hits
    return []


def _deepseek_search(query: str, count: int) -> list[dict]:
    """DeepSeek's own search index, with page text included.

    Returns hits shaped like the scrapers' but carrying `text`, so the caller can
    skip fetching. An empty list means "fall through to scraping".
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        response = requests.post(
            DEEPSEEK_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "count": max(count, 1), "need_content": True},
            timeout=DEEPSEEK_SEARCH_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - research must never break a forecast
        logger.warning("DeepSeek search request failed for %r: %s", query, exc)
        return []
    if response.status_code != 200:
        logger.warning(
            "DeepSeek search returned %s for %r: %s",
            response.status_code,
            query,
            response.text[:200],
        )
        return []
    try:
        results = response.json().get("results") or []
    except ValueError:
        return []

    hits = []
    for item in results:
        text = (item.get("content") or item.get("summary") or "").strip()
        if len(text) < 200:  # nothing to read, no point spending prompt on it
            continue
        hits.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "text": text[:MAX_CHARS_PER_PAGE],
            }
        )
    return hits


def fetch_text(url: str) -> str:
    """Fetch a page and reduce it to plain text. '' on any failure."""
    response = _get(url, timeout=PAGE_TIMEOUT)
    if response is None or response.status_code != 200:
        return ""
    if "text/html" not in response.headers.get("Content-Type", ""):
        return ""
    return _clean_html(response.text)[:MAX_CHARS_PER_PAGE]


def _format_block(title: str, url: str, text: str) -> str:
    return f"[{title}]\nURL: {url}\n{text}"


def gather_research(queries: list[str], max_pages: int = MAX_PAGES) -> str:
    """Search the given queries, gather page text, format it for the prompt.

    DeepSeek's search API is tried first because it needs no scraping and works
    behind the GFW. Scraping is the fallback, not the plan.
    """
    started = time.time()

    blocks: list[str] = []
    seen: set[str] = set()
    for query in queries:
        for hit in _deepseek_search(query, max_pages):
            if hit["url"] in seen:
                continue
            seen.add(hit["url"])
            blocks.append(_format_block(hit["title"], hit["url"], hit["text"]))
            if len(blocks) >= max_pages:
                break
        if len(blocks) >= max_pages or time.time() - started > TOTAL_BUDGET_SECONDS:
            break
    if blocks:
        logger.info("DeepSeek search: %d pages for %d queries", len(blocks), len(queries))
        return "\n\n---\n\n".join(blocks)
    logger.info("DeepSeek search gave nothing; falling back to scraping")

    hits: list[dict] = []
    for query in queries:
        for hit in search(query, max_results=max_pages):
            if hit["url"] in seen:
                continue
            seen.add(hit["url"])
            hits.append(hit)
            if len(hits) >= max_pages:
                break
        if len(hits) >= max_pages or time.time() - started > TOTAL_BUDGET_SECONDS:
            break

    if not hits:
        return ""

    with ThreadPoolExecutor(max_workers=len(hits)) as pool:
        texts = list(pool.map(fetch_text, [hit["url"] for hit in hits]))

    blocks = []
    for hit, text in zip(hits, texts):
        if time.time() - started > TOTAL_BUDGET_SECONDS:
            break
        if len(text) < 200:  # paywall, JS shell, or blocked
            continue
        blocks.append(_format_block(hit["title"], hit["url"], text))

    if not blocks:
        return ""
    logger.info("Web research: %d/%d pages used", len(blocks), len(hits))
    return "\n\n---\n\n".join(blocks)
