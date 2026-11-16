"""LLM wiring shared by main.py and the local smoke test.

Kept in one place so the smoke test exercises exactly the production models.
Provider: DeepSeek (litellm prefix "deepseek/"), key read from DEEPSEEK_API_KEY.

Model choice
------------
`deepseek-flash` (DeepSeek-V4.1-Flash) at $0.15/M input, $0.60/M output off-peak
($0.30/$1.20 at peak) -- about 4x cheaper per token than deepseek-v4-pro.

Thinking mode is DISABLED by default, for two reasons that are specific to this
bot rather than general preference:

1. Cost. The template fires ~10 LLM calls per question. Reasoning tokens bill as
   output, and at `high` effort they dwarf the visible answer.
2. Diversity. Thinking mode ignores `temperature` (DeepSeek documents this), and
   this bot gets its aggregate from `predictions_per_research_report=3` runs at
   different temperatures. With thinking on, the three reports converge and the
   aggregation stops meaning anything.

Set DEEPSEEK_THINKING=enabled (plus DEEPSEEK_EFFORT=low|high|max) to flip it.
"""

from __future__ import annotations

import os
import re
from typing import get_origin

from forecasting_tools import GeneralLlm

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-flash")

_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.S)

_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def _thinking_kwargs() -> dict:
    """Thinking-mode kwargs for every litellm call, straight from the env."""
    if os.getenv("DEEPSEEK_THINKING", "disabled").strip().lower() in _TRUTHY:
        return {
            "reasoning_effort": os.getenv("DEEPSEEK_EFFORT", "high").strip().lower(),
            "extra_body": {"thinking": {"type": "enabled"}},
        }
    return {"extra_body": {"thinking": {"type": "disabled"}}}


def _repair_ndjson(text: str) -> str:
    """Wrap newline-separated JSON objects into a JSON array.

    The model emits numeric percentile ladders as one object per line:

        {"percentile": 0.1, "value": 22}
        {"percentile": 0.2, "value": 27}

    The SDK parses the reply as `list[Percentile]`, so it raises
    "Extra data: line 2 column 1" and the whole prediction is discarded. Retrying
    does not help -- temperature 0 reproduces the same shape -- so the shape is
    repaired here instead. Measured on 2026-11-16 on deepseek-chat: 4 of 40
    questions lost this way, all of them numeric.
    """
    stripped = text.strip()
    if not stripped or stripped.startswith("["):
        return text
    objects = _JSON_OBJECT_RE.findall(stripped)
    if len(objects) < 2:
        return text
    return "[" + ",".join(objects) + "]"


class NdjsonTolerantLlm(GeneralLlm):
    """GeneralLlm whose list parsing survives newline-delimited JSON."""

    @classmethod
    def transform_response_to_type(cls, response, normal_complex_or_pydantic_type):
        if get_origin(normal_complex_or_pydantic_type) is list:
            response = _repair_ndjson(response)
        return super().transform_response_to_type(response, normal_complex_or_pydantic_type)


def deepseek_llms() -> dict:
    """Role -> GeneralLlm mapping expected by ForecastBot's `llms` argument."""
    thinking = _thinking_kwargs()
    return {
        # Reasoning behind each forecast.
        "default": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0.3,
            timeout=210,
            allowed_tries=3,
            **thinking,
        ),
        # Turns prose reasoning into the structured prediction object. This is the
        # role that needs the NDJSON repair: numeric and discrete questions are
        # parsed through it as list[Percentile].
        "parser": NdjsonTolerantLlm(
            model=DEEPSEEK_MODEL,
            temperature=0,
            timeout=210,
            allowed_tries=3,
            **thinking,
        ),
        # Reads the web excerpts gathered by bot_research.py and writes the brief.
        "researcher": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0.6,
            timeout=210,
            allowed_tries=3,
            **thinking,
        ),
        "summarizer": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0,
            timeout=120,
            allowed_tries=2,
            **thinking,
        ),
    }
