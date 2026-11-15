"""Dry-run smoke test: forecast one question, publish nothing.

Exists so the pipeline can be verified (pull question -> research -> predict ->
parse structured output) without touching the tournament, and so anyone
reviewing the method can reproduce a single run cheaply.

    python smoke.py
"""

import asyncio
import os

import dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
dotenv.load_dotenv(os.path.join(HERE, ".env"))

from forecasting_tools import MetaculusClient  # noqa: E402

from bot_llms import deepseek_llms  # noqa: E402
from main import FallTemplateBot2026  # noqa: E402


def main() -> None:
    client = MetaculusClient()
    questions = client.get_all_open_questions_from_tournament("bot-testing-area")
    print(f"[smoke] open questions in bot-testing-area: {len(questions)}")
    if not questions:
        print("[smoke] nothing open right now -- try again later")
        return

    binary = [q for q in questions if type(q).__name__ == "BinaryQuestion"]
    target = (binary or questions)[0]
    print(f"[smoke] target: {type(target).__name__} | {target.page_url}")

    bot = FallTemplateBot2026(
        research_reports_per_question=1,
        predictions_per_research_report=1,
        publish_reports_to_metaculus=False,  # never publish from the smoke test
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=False,
        llms=deepseek_llms(),
    )

    reports = asyncio.run(bot.forecast_questions([target], return_exceptions=True))
    for report in reports:
        if isinstance(report, BaseException):
            print(f"[smoke] FAILED: {type(report).__name__}: {report}")
        else:
            print(f"[smoke] OK prediction={report.prediction}")
            print(f"[smoke] reasoning_chars={len(report.explanation or '')}")


if __name__ == "__main__":
    main()
