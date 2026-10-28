from agency_swarm import Agent, ModelSettings
from agency_swarm.tools import WebSearchTool, IPythonInterpreter
from openai.types.shared import Reasoning

from config import allow_code_execution, get_default_model, is_openai_provider


def create_deep_research() -> Agent:
    """SEO Research & Keyword Agent for the v-try-on blog swarm."""
    return Agent(
        name="SEO Research Agent",
        description=(
            "SEO strategist and keyword researcher. Finds high-intent topics, keywords, and SERP gaps "
            "for the v-try-on fashion / AI virtual try-on audience, analyzes competing content, and "
            "produces a content brief (target keyword, search intent, outline, entities, internal-link "
            "and FAQ ideas) that the Blog Writer turns into a post."
        ),
        instructions="./instructions.md",
        tools=[WebSearchTool(), *([IPythonInterpreter] if allow_code_execution() else [])],
        model=get_default_model(),
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="medium", summary="auto") if is_openai_provider() else None,
            response_include=["web_search_call.action.sources"] if is_openai_provider() else None,
        ),
        conversation_starters=[
            "Find 5 high-intent blog topics for saree/kurti sellers considering AI virtual try-on.",
            "Build an SEO content brief for the keyword 'virtual try-on for ethnic wear'.",
            "Analyze what competitors rank for around 'reduce clothing returns with AI'.",
            "Suggest long-tail keywords and FAQs for an AI fashion photoshoot article.",
        ],
    )
