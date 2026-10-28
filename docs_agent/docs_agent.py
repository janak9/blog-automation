from datetime import datetime, timezone
from pathlib import Path

from agency_swarm import Agent, ModelSettings, Agency
from agency_swarm.tools import IPythonInterpreter, WebSearchTool
from openai.types.shared import Reasoning
from shared_tools import CopyFile

from config import allow_code_execution, get_default_model, is_openai_provider

_INSTRUCTIONS_PATH = Path(__file__).parent / "instructions.md"


def _build_instructions() -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = _INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    return f"{body}\n\nCurrent date/time (UTC): {now_utc}\n"


def create_docs_agent() -> Agent:
    """Blog Writer Agent — produces SEO blog posts in the BLOG_POSTS JSON shape."""
    return Agent(
        name="Blog Writer",
        description=(
            "SEO blog writer for the Vtryon fashion / AI virtual try-on blog. Turns a research brief "
            "into a complete, on-brand article emitted as a ready-to-deploy BLOG_POSTS object "
            "(slug, title, description, date, readingTime, author, featuredImage, category, "
            "content[], faq[]) plus image direction for the Blog Image Agent."
        ),
        instructions=_build_instructions(),
        tools_folder="./tools",
        model=get_default_model(),
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="medium", summary="auto") if is_openai_provider() else None,
            response_include=["web_search_call.action.sources"] if is_openai_provider() else None,
        ),
        tools=[WebSearchTool(), *([IPythonInterpreter] if allow_code_execution() else []), CopyFile],
        conversation_starters=[
            "Write a blog post from this SEO brief and emit it as a BLOG_POSTS object.",
            "Draft a 10-minute guide on AI virtual try-on for saree sellers with FAQs.",
            "Turn these keywords into an on-brand Vtryon article with headings, lists, and images.",
            "Write a comparison post on standard vs premium AI image generation for fashion.",
        ],
    )


if __name__ == "__main__":
    import contextlib
    import os

    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        Agency(create_docs_agent()).terminal_demo()
