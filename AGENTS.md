# Vtryon SEO Blog Swarm — Customization Guide

This file gives coding agents (Cursor, Claude Code, Codex, etc.) everything they need to understand and customize this swarm. Read it before making any changes.

---

## What is this swarm?

This is an **SEO blog automation swarm** (forked from OpenSwarm) that writes, illustrates, approves,
and deploys blog posts for **https://vtryon.legresca.ai/blog** — Vtryon's AI virtual try-on / AI
fashion imagery product (garment sellers, boutiques, strong India / ethnic-wear focus).

**Pipeline:** SEO Research → Blog Writer → Blog Image Agent → **SEO Director review + user approval**
→ Blog Deploy Agent opens a **pull request** to the site repo with the post + full **Hindi and
Gujarati** translations for i18n.

- **Site repo (deploy target):** `/Users/janakvaghela/projects/legresca/v-try-on` (Next.js + next-intl)
- **A post touches 4 files:** `lib/blog-data.ts` (English `BLOG_POSTS`), `messages/en.json` (metadata),
  `messages/hi.json` + `messages/gu.json` (full translated `content[]` + `faqs[]`). See the Blog Deploy
  Agent's `instructions.md` for the exact contract.

The base framework is still OpenSwarm — a multi-agent team you can fork and reshape. Each agent is a
specialist; they collaborate through the SEO Director.

---

## Folder Structure

```
swarm.py                  ← main config: imports all agents, defines how they connect
shared_instructions.md    ← context shared across every agent
run.py                    ← CLI entry point (terminal demo)
server.py                 ← API entry point (FastAPI server)

orchestrator/
  orchestrator.py         ← agent definition
  instructions.md         ← system prompt

data_analyst_agent/
  data_analyst_agent.py
  instructions.md
  tools/                  ← custom tools for this agent

docs_agent/
  docs_agent.py
  instructions.md
  tools/

slides_agent/
  slides_agent.py
  instructions.md
  tools/

image_generation_agent/
  image_generation_agent.py
  instructions.md
  tools/

video_generation_agent/
  video_generation_agent.py
  instructions.md
  tools/

deep_research/
  deep_research.py
  instructions.md
  tools/

virtual_assistant/
  virtual_assistant.py
  instructions.md
  tools/

shared_tools/             ← tools available to all agents (Composio integrations, etc.)
```

---

## How Agents Connect (`swarm.py`)

`swarm.py` is the only file you need to edit when adding, removing, or rewiring agents. It:

1. Imports a `create_*` factory function from each agent folder
2. Instantiates all agents
3. Defines communication flows — who can talk to whom

The default pattern is **orchestrator-to-all**: the orchestrator can send messages to every specialist, and all agents can hand off to each other.

---

## How to Customize

To build your own swarm from this repo:

1. **Fork and rename** the repo (e.g., `seo-swarm`)
2. **Decide which agents to keep, rename, or replace**
   - Rename the folder and its files to match the new agent's purpose
   - Update `instructions.md` with the new system prompt
   - Update `swarm.py` to import and register the renamed agent
3. **Add or remove tools** inside each agent's `tools/` folder
4. **Update `shared_instructions.md`** with any context all agents should share
5. **Run** with `python run.py`

### Example prompt to give your coding agent

> "Turn this into an SEO optimization swarm. The Research Agent becomes an SEO Keyword Planner, the Docs Agent becomes a Blog Post Writer, the Data Analyst becomes an SEO Analytics Agent (Google Search Console + GA4), and the General Agent handles technical SEO like schema markup and site audits. Keep the orchestrator and shared tools as-is."

The coding agent will read this file, understand the structure, and make the right changes automatically.

---

## Current Agents (SEO Blog Swarm)

The swarm is wired in `swarm.py`. Folder names are kept from the OpenSwarm base to avoid breaking
packaging, but each has been repurposed — the **agent name** is what matters at runtime.

| Folder | Agent name | Purpose |
|---|---|---|
| `orchestrator` | **SEO Director** | Plans the pipeline, reviews drafts, owns the human approval gate, dispatches deployment |
| `deep_research` | **SEO Research Agent** | Keyword/topic research, SERP analysis, content briefs |
| `docs_agent` | **Blog Writer** | Writes posts as a ready-to-deploy `BLOG_POSTS` object |
| `image_generation_agent` | **Blog Image Agent** | Featured + inline blog imagery (`<name>_thumb.webp`) |
| `blog_deploy_agent` | **Blog Deploy Agent** | Pulls v-try-on repo, wires post + hi/gu i18n, opens PR to `main` |

### Dormant folders (not wired into the SEO swarm)

`virtual_assistant`, `data_analyst_agent`, `slides_agent`, `video_generation_agent` remain on disk
(so `package.json` packaging and `slides_preview_server.py` don't break) but are **not** included in
`swarm.py`. Delete them if you want a leaner fork, and remove their entries from `package.json`.

---

## Key Conventions

- Each agent folder has one `<name>.py` file and one `instructions.md`
- `instructions.md` is the agent's system prompt — edit it to change behavior
- Tools live in `tools/` and are auto-loaded by the agent definition
- `shared_tools/` contains Composio-powered integrations (Gmail, Slack, GitHub, etc.) available to all agents
- Models are configured via `DEFAULT_MODEL` in `.env` — never hardcoded

Before proceeding with agent creation, please read the following instructions carefully:

- `.cursor/rules/agency-swarm-workflow.mdc` - your primary guide for creating agents and agencies

The following files can be read on demand, depending on the task at hand:

- `.cursor/commands/add-mcp.md` - how to add MCP servers to an agent
- `.cursor/commands/mcp-code-exec.md` - how to convert an MCP server into the Code Execution Pattern (progressive tool disclosure, 98% token reduction)
- `.cursor/commands/write-instructions.md` - how to write effective instructions for AI agents
- `.cursor/commands/create-prd.md` - how to create a PRD for an agent (use for complex multi agent systems)
