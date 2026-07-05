import os

from run_utils import _bootstrap, _configure_product_env, _openswarm_state_root, _preload_agentswarm_bin

_RUNTIME_CONFIGURED = False


def _configure_runtime() -> None:
    global _RUNTIME_CONFIGURED
    if _RUNTIME_CONFIGURED:
        return

    from dotenv import load_dotenv
    from agents import set_tracing_disabled, set_tracing_export_api_key
    from patches.patch_ipython_interpreter_composio import (
        apply_ipython_composio_context_patch,
    )
    from patches.patch_utf8_file_reads import apply_utf8_file_read_patch

    load_dotenv(dotenv_path=_openswarm_state_root() / ".env")

    apply_utf8_file_read_patch()
    apply_ipython_composio_context_patch()

    _tracing_key = os.getenv("OPENAI_API_KEY")
    if _tracing_key:
        set_tracing_export_api_key(_tracing_key)
    else:
        set_tracing_disabled(True)

    _RUNTIME_CONFIGURED = True


if __name__ == "__main__":
    _preload_agentswarm_bin()
    _bootstrap()

_configure_runtime()


def create_agency(load_threads_callback=None):
    _configure_runtime()
    _configure_product_env()

    from agency_swarm import Agency
    from agency_swarm.tools import Handoff, SendMessage

    # SEO Blog Swarm — 5 agents.
    #   orchestrator            -> SEO Director (coordinator + human-in-the-loop approver)
    #   deep_research           -> SEO Research & Keyword Agent
    #   docs_agent              -> Blog Writer Agent (produces BLOG_POSTS JSON)
    #   image_generation_agent  -> Blog Image Agent (featured / inline imagery)
    #   blog_deploy_agent       -> Blog Deployment & Localization Agent (git + i18n -> PR)
    from orchestrator import create_orchestrator
    from deep_research import create_deep_research
    from docs_agent import create_docs_agent
    from image_generation_agent import create_image_generation_agent
    from blog_deploy_agent import create_blog_deploy_agent

    seo_director = create_orchestrator()
    seo_research = create_deep_research()
    blog_writer = create_docs_agent()
    blog_image = create_image_generation_agent()
    blog_deploy = create_blog_deploy_agent()

    all_agents = [
        seo_director,
        seo_research,
        blog_writer,
        blog_image,
        blog_deploy,
    ]

    # The Director can dispatch to every specialist.
    send_message_flows = [
        (seo_director, specialist, SendMessage)
        for specialist in all_agents
        if specialist is not seo_director
    ]

    # Full handoff mesh so specialists can chain the pipeline
    # (research -> write -> image -> deploy) without round-tripping the Director.
    handoff_flows = [
        (a > b, Handoff)
        for a in all_agents
        for b in all_agents
        if a is not b
    ]

    agency = Agency(
        *all_agents,
        communication_flows=send_message_flows + handoff_flows,
        name="SEOBlogSwarm",
        shared_instructions="shared_instructions.md",
        load_threads_callback=load_threads_callback,
    )

    return agency


def _main() -> None:
    agency = create_agency()
    agency.tui(show_reasoning=True, reload=False)


if __name__ == "__main__":
    _main()
