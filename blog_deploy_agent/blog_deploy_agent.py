from datetime import datetime, timezone
from pathlib import Path

from agency_swarm import Agent, ModelSettings
from agency_swarm.tools import IPythonInterpreter
from openai.types.shared import Reasoning

from config import get_default_model, is_openai_provider

_INSTRUCTIONS_PATH = Path(__file__).parent / "instructions.md"


def _build_instructions() -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = _INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    return f"{body}\n\nCurrent date/time (UTC): {now_utc}\n"


def create_blog_deploy_agent() -> Agent:
    return Agent(
        name="Blog Deploy Agent",
        description=(
            "Deployment & Localization Engineer. After the SEO Director approves a blog, this agent "
            "pulls the v-try-on repo, wires the English post into BLOG_POSTS, generates full Hindi and "
            "Gujarati translations for i18n, copies generated images into the repo, and opens a PR to main."
        ),
        instructions=_build_instructions(),
        tools_folder="./tools",
        tools=[IPythonInterpreter],
        model=get_default_model(),
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="high", summary="auto") if is_openai_provider() else None,
        ),
        conversation_starters=[
            "Deploy the approved blog post to the v-try-on repo with Hindi and Gujarati translations.",
            "Pull the latest main and show me the current BLOG_POSTS structure before I insert a post.",
        ],
    )


if __name__ == "__main__":
    from agency_swarm import Agency

    Agency(create_blog_deploy_agent()).terminal_demo()
