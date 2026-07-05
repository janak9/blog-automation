from agency_swarm import Agent, ModelSettings
from openai.types.shared import Reasoning

from config import get_default_model, is_openai_provider
from run_utils import _load_openswarm_dotenv

_load_openswarm_dotenv()


def create_orchestrator() -> Agent:
    return Agent(
        name="SEO Director",
        description=(
            "SEO Director and entry point for the Vtryon blog swarm. Plans the content pipeline "
            "(research -> write -> images), reviews drafts, acts as the human-in-the-loop approval "
            "gate, and only after approval dispatches the Blog Deploy Agent to publish the post with "
            "Hindi/Gujarati i18n via a PR."
        ),
        instructions="./instructions.md",
        model=get_default_model(),
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="medium", summary="auto") if is_openai_provider() else None,
        ),
        conversation_starters=[
            "Plan and write a new SEO blog post for saree sellers, then show it to me for approval.",
            "Research topics for the Vtryon blog and recommend the best one to write next.",
            "Draft a blog on reducing clothing returns with AI virtual try-on for my review.",
            "The last draft is approved — deploy it to the v-try-on repo with hi/gu translations.",
        ],
    )


if __name__ == "__main__":
    from agency_swarm import Agency
    Agency(create_orchestrator()).terminal_demo()
