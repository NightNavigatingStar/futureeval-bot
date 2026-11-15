"""LLM wiring shared by main.py and the local smoke test.

Kept in one place so the smoke test exercises exactly the production models.
Provider: DeepSeek (litellm prefix "deepseek/"), key read from DEEPSEEK_API_KEY.
"""

from __future__ import annotations

import re
from typing import get_origin

from forecasting_tools import GeneralLlm

DEEPSEEK_MODEL = "deepseek/deepseek-chat"

_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.S)


def _repair_ndjson(text: str) -> str:
    """Wrap newline-separated JSON objects into a JSON array.

    deepseek-chat emits numeric percentile ladders as one object per line:

        {"percentile": 0.1, "value": 22}
        {"percentile": 0.2, "value": 27}

    The SDK parses the reply as `list[Percentile]`, so it raises
    "Extra data: line 2 column 1" and the whole prediction is discarded. Retrying
    does not help -- temperature 0 reproduces the same shape -- so the shape is
    repaired here instead. Measured on 2026-11-16: 4 of 40 questions lost this way,
    all of them numeric.
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
    return {
        # Reasoning behind each forecast.
        "default": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0.3,
            timeout=210,
            allowed_tries=3,
        ),
        # Turns prose reasoning into the structured prediction object. This is the
        # role that needs the NDJSON repair: numeric and discrete questions are
        # parsed through it as list[Percentile].
        "parser": NdjsonTolerantLlm(
            model=DEEPSEEK_MODEL,
            temperature=0,
            timeout=210,
            allowed_tries=3,
        ),
        # Reads the web excerpts gathered by bot_research.py and writes the brief.
        "researcher": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0.6,
            timeout=210,
            allowed_tries=3,
        ),
        "summarizer": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0,
            timeout=120,
            allowed_tries=2,
        ),
    }
