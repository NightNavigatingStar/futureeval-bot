"""LLM wiring shared by main.py and the local smoke test.

Kept in one place so the smoke test exercises exactly the production models.
Provider: DeepSeek (litellm prefix "deepseek/"), key read from DEEPSEEK_API_KEY.
"""

from __future__ import annotations

from forecasting_tools import GeneralLlm

DEEPSEEK_MODEL = "deepseek/deepseek-chat"


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
        # Turns prose reasoning into the structured prediction object.
        # Temperature 0 keeps the parsing deterministic.
        "parser": GeneralLlm(
            model=DEEPSEEK_MODEL,
            temperature=0,
            timeout=210,
            allowed_tries=3,
        ),
        # No web-search provider is configured, so research falls back to the
        # model's own knowledge. A real search API (AskNews/Exa/Perplexity)
        # would replace this.
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
