"""
MCP bridge for the Vtryon SEO Blog Swarm.

Exposes the swarm to Claude (as a custom connector) so you can command it from
the Claude app on your phone. It is a thin, stateful proxy in front of the
existing FastAPI server (`server.py`) — it reuses all of that server's tested
request handling, so this file stays small.

Architecture:
    Claude app  ──(MCP over HTTPS, via cloudflared tunnel)──▶  this bridge (:9000)
    this bridge ──(local HTTP)──▶  server.py  (:8080)  ──▶  the swarm

Run (in a second terminal, with server.py already running):
    ./.venv/bin/python3 mcp_bridge.py

Then expose it:
    cloudflared tunnel --url http://localhost:9000
and add the printed https URL (with the /mcp path) as a custom connector in Claude.

Environment variables:
    SWARM_API_URL     Base URL of server.py            (default http://127.0.0.1:8080)
    SWARM_AGENCY      Agency name from server.py        (default "open-swarm")
    APP_TOKEN         Bearer token server.py expects    (must match server.py)
    MCP_BRIDGE_TOKEN  Shared secret this bridge requires from Claude (optional but
                      strongly recommended, since the tunnel URL is public).
    MCP_BRIDGE_PORT   Port for this bridge              (default 9000)
"""

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from cost_tracker import CostTracker
from run_utils import _load_openswarm_dotenv

# Load the OpenSwarm state-root .env (if present) AND the project-local .env.
# The state-root file usually doesn't exist for a DIY run, so the local .env is
# what actually provides APP_TOKEN / MCP_BRIDGE_TOKEN / API keys here.
_load_openswarm_dotenv()
load_dotenv(Path(__file__).with_name(".env"))

SWARM_API_URL = os.getenv("SWARM_API_URL", "http://127.0.0.1:8080").rstrip("/")
SWARM_AGENCY = os.getenv("SWARM_AGENCY", "open-swarm")
APP_TOKEN = os.getenv("APP_TOKEN", "")
MCP_BRIDGE_TOKEN = os.getenv("MCP_BRIDGE_TOKEN", "")
MCP_BRIDGE_PORT = int(os.getenv("MCP_BRIDGE_PORT", "9000"))

# How Claude authenticates to this bridge:
#   "token"  (default) — static bearer (MCP_BRIDGE_TOKEN); simplest, works with a quick tunnel.
#   "github"           — real OAuth via GitHub; needs a stable public URL (named tunnel) +
#                        a GitHub OAuth app. Set GITHUB_OAUTH_CLIENT_ID/SECRET and PUBLIC_BASE_URL.
MCP_AUTH_MODE = os.getenv("MCP_AUTH_MODE", "token").strip().lower()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Per-conversation history so multi-turn commands (draft -> revise -> approve ->
# deploy) keep context. The swarm's FastAPI is stateless, so the client (this
# bridge) owns the history and replays it on each turn.
_HISTORY: dict[str, list] = {}


def _build_auth():
    """Return a fastmcp auth provider for the configured mode (or None for token/no-auth)."""
    if MCP_AUTH_MODE == "github":
        if not PUBLIC_BASE_URL:
            raise RuntimeError("MCP_AUTH_MODE=github requires PUBLIC_BASE_URL (your stable tunnel URL).")
        client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
        client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
        if not (client_id and client_secret):
            raise RuntimeError("MCP_AUTH_MODE=github requires GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET.")
        from fastmcp.server.auth.providers.github import GitHubProvider

        return GitHubProvider(
            client_id=client_id,
            client_secret=client_secret,
            base_url=PUBLIC_BASE_URL,
        )
    return None  # token mode (or none) — enforced per-call in _check_auth()


mcp = FastMCP("Vtryon SEO Blog Swarm", auth=_build_auth())


def _check_auth() -> None:
    """Static-token gate for 'token' mode. OAuth modes enforce auth at the transport layer."""
    if MCP_AUTH_MODE != "token":
        return  # OAuth (e.g. github) already authenticated the request.
    if not MCP_BRIDGE_TOKEN:
        return  # No secret set — relies on the tunnel URL being private. Not recommended.
    headers = get_http_headers() or {}
    provided = (headers.get("authorization") or headers.get("Authorization") or "").strip()
    if provided != f"Bearer {MCP_BRIDGE_TOKEN}":
        raise PermissionError("Unauthorized: missing or invalid bridge token.")


# Streamed events carry `agent` (the currently-active agent) and typed
# run_item events for tool calls. We emit a friendly line when the active agent
# changes, plus a sub-step line for notable tools.
_AGENT_LABELS = {
    "SEO Director": "🧭 SEO Director: planning / reviewing",
    "SEO Research Agent": "🔎 Research Agent: building the SEO brief",
    "Blog Writer": "✍️  Blog Writer: drafting the post",
    "Blog Image Agent": "🖼️  Image Agent: generating images",
    "Blog Deploy Agent": "🚀 Deploy Agent: publishing to the repo",
}
_TOOL_LABELS = [
    ("CommitAndOpenPR", "   · opening the pull request"),
    ("InsertBlogPost", "   · inserting blog + hi/gu translations"),
    ("PrepareBlogBranch", "   · preparing the git branch"),
    ("GenerateImages", "   · generating an image"),
    ("web_search", "   · searching the web"),
]


def _extract_final_text(messages: list) -> str:
    """Pull the final assistant text out of the streamed new_messages list."""
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") not in (None, "assistant"):
            continue
        content = m.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    parts.append(p.get("text") or p.get("output_text") or "")
                elif isinstance(p, str):
                    parts.append(p)
            joined = "\n".join(t for t in parts if t).strip()
            if joined:
                return joined
    return ""


def _call_swarm(instruction: str, conversation_id: str = "mobile", on_progress=None) -> str:
    """Forward one instruction to server.py's streaming endpoint.

    Streams server-sent events, calls on_progress(label) as the active agent/tool
    changes, and returns the final assistant text. Kept plain (no auth / no MCP
    context) so it can be unit-tested.
    """
    history = _HISTORY.setdefault(conversation_id, [])

    payload = {"message": instruction}
    if history:
        payload["chat_history"] = history

    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if APP_TOKEN:
        headers["Authorization"] = f"Bearer {APP_TOKEN}"

    url = f"{SWARM_API_URL}/{SWARM_AGENCY}/get_response_stream"
    final_text = ""
    new_messages: list = []
    cur_agent = None
    last_tool = None
    cost = CostTracker()
    seen_image_calls: set = set()

    def push(label: str) -> None:
        if label and on_progress:
            on_progress(label)

    try:
        with httpx.stream(
            "POST", url, json=payload, headers=headers,
            timeout=httpx.Timeout(600.0, connect=15.0),
        ) as resp:
            if resp.status_code == 401:
                return "Swarm rejected the request (401). APP_TOKEN here must match server.py's APP_TOKEN."
            if resp.status_code >= 400:
                body = resp.read().decode("utf-8", "ignore")[:400]
                return f"Swarm returned HTTP {resp.status_code}: {body}"

            cur_event = None
            for line in resp.iter_lines():
                line = (line or "").strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    cur_event = line[len("event:"):].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if cur_event == "messages":
                    new_messages = obj.get("new_messages") or []
                    text = _extract_final_text(new_messages)
                    if text:
                        final_text = text
                    continue
                if isinstance(obj, dict) and obj.get("error"):
                    push(f"⚠️  {str(obj['error'])[:200]}")
                    continue

                inner = obj.get("data") if isinstance(obj, dict) else None
                if not isinstance(inner, dict):
                    continue

                # Active-agent transition (precise: the event's own `agent` field).
                agent = inner.get("agent")
                if isinstance(agent, str) and agent and agent != cur_agent:
                    cur_agent = agent
                    push(_AGENT_LABELS.get(agent, f"• {agent}"))

                # Token usage — each model round-trip emits a completed event carrying usage.
                d = inner.get("data")
                if isinstance(d, dict) and "completed" in str(d.get("type", "")):
                    resp = d.get("response") or {}
                    u = resp.get("usage") or {}
                    if u:
                        cost.add_text_usage(
                            agent or cur_agent or "unknown",
                            resp.get("model") or "",
                            int(u.get("input_tokens") or 0),
                            int(u.get("output_tokens") or 0),
                            int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0),
                            int((u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0),
                        )

                # Notable tool calls — scan only the small `item` object, not the
                # whole event (which lists the full agent roster and would be noisy).
                if inner.get("type") == "run_item_stream_event" and "tool" in str(inner.get("name") or ""):
                    item_str = json.dumps(inner.get("item") or "")
                    for key, sub in _TOOL_LABELS:
                        if key in item_str and sub != last_tool:
                            last_tool = sub
                            push(sub)
                            break
                    # Count generated images once per tool call (for image pricing).
                    if "GenerateImages" in item_str:
                        m = re.search(r'"call_id"\s*:\s*"([^"]+)"', item_str) or re.search(
                            r'"id"\s*:\s*"([^"]+)"', item_str
                        )
                        cid = m.group(1) if m else item_str[:48]
                        if cid not in seen_image_calls:
                            seen_image_calls.add(cid)
                            mv = re.search(r'"num_variants"\s*:\s*"?(\d+)"?', item_str)
                            n = int(mv.group(1)) if mv else 1
                            img_model = next(
                                (k for k in ("gemini-3-pro-image-preview", "gemini-2.5-flash-image", "gpt-image-1.5")
                                 if k in item_str),
                                "unknown",
                            )
                            cost.add_images(img_model, n)
    except httpx.RequestError as exc:
        return f"Could not reach the swarm at {url}: {exc}. Is server.py running?"

    if new_messages:
        history.extend(new_messages)
    push("✅ done")

    result = final_text or "(the swarm completed but returned no text)"
    report = cost.report()
    if report:
        _log_cost(cost, instruction)
        result = f"{result}\n\n{report}"
    return result


def _log_cost(cost: CostTracker, instruction: str) -> None:
    """Print the cost report to the bridge log and append a machine-readable line to costs.jsonl."""
    try:
        print("\n" + cost.report() + "\n", flush=True)
        t = cost.totals()
        rec = {
            "ts": int(time.time()),
            "instruction": (instruction or "")[:200],
            "grand_total": round(t["grand_total"], 4),
            "buckets": {k: round(v, 4) for k, v in t["buckets"].items()},
            "tokens": t["tokens"],
            "images": cost.images,
        }
        with open(Path(__file__).with_name("costs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Async job model.
#
# A single swarm instruction (research/write/deploy) can take several minutes,
# but MCP clients (Claude) and tunnels time out a synchronous call in ~30-60s
# and then RETRY it — which restarts the whole pipeline and looks "stuck".
# So we run each instruction in a background thread and let the client poll.
# ---------------------------------------------------------------------------
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _run_job(job_id: str, instruction: str, conversation_id: str) -> None:
    def on_progress(label: str) -> None:
        with _JOBS_LOCK:
            _JOBS[job_id].setdefault("progress", []).append(label)

    try:
        result = _call_swarm(instruction, conversation_id, on_progress=on_progress)
        with _JOBS_LOCK:
            _JOBS[job_id].update(status="done", result=result, finished=time.time())
    except Exception as exc:  # noqa: BLE001 — report any failure back to the poller
        with _JOBS_LOCK:
            _JOBS[job_id].update(status="error", error=f"{type(exc).__name__}: {exc}", finished=time.time())


@mcp.tool
def run_seo_blog_swarm(instruction: str, conversation_id: str = "mobile") -> str:
    """Start a Vtryon SEO Blog Swarm task in the background and return a job id immediately.

    The swarm researches SEO topics, writes on-brand blog posts (with images), and — only
    after you approve — deploys an approved post to the v-try-on repo (English + Hindi +
    Gujarati) as a pull request. A task can take several minutes, so this returns right away
    with a job id instead of blocking.

    IMPORTANT: after calling this, call `check_blog_job(job_id)` to get the result. Do NOT
    resend the same instruction while a job is running — that starts a duplicate pipeline.
    Keep the same conversation_id across turns to continue a thread (draft -> revise ->
    "approved, deploy it").

    Args:
        instruction: What you want the swarm to do, in plain language.
        conversation_id: Stable id to keep multi-turn context (default "mobile").
    """
    _check_auth()
    job_id = uuid.uuid4().hex[:8]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",
            "instruction": instruction,
            "conversation_id": conversation_id,
            "started": time.time(),
            "progress": [],
        }
    threading.Thread(
        target=_run_job, args=(job_id, instruction, conversation_id), daemon=True
    ).start()
    return (
        f"Started job `{job_id}` (running in the background — may take a few minutes). "
        f"Call check_blog_job('{job_id}') to get progress and the result. Do not resend "
        f"the instruction; just poll that job id."
    )


@mcp.tool
def check_blog_job(job_id: str) -> str:
    """Check a swarm job started by run_seo_blog_swarm. Returns the result when ready.

    This waits briefly (long-poll) for the job to finish before returning, so you usually
    only need a few calls. If it says 'still running', call again.

    Args:
        job_id: The id returned by run_seo_blog_swarm.
    """
    _check_auth()
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return f"No job '{job_id}' found. Start one with run_seo_blog_swarm, or it may have expired."

    # Long-poll up to ~45s so each check stays under client/tunnel timeouts.
    deadline = time.time() + 45
    while time.time() < deadline:
        with _JOBS_LOCK:
            status = _JOBS[job_id]["status"]
        if status != "running":
            break
        time.sleep(2)

    with _JOBS_LOCK:
        job = _JOBS[job_id]
        status = job["status"]
        elapsed = int(time.time() - job["started"])
        progress = list(job.get("progress", []))
        result = job.get("result")
        error = job.get("error")

    trail = "\n".join(progress[-12:]) if progress else "  (starting…)"
    if status == "running":
        return (
            f"Job `{job_id}` still running ({elapsed}s). Progress so far:\n{trail}\n\n"
            f"Call check_blog_job('{job_id}') again to keep watching."
        )
    if status == "error":
        return f"Job `{job_id}` failed after {elapsed}s.\nProgress:\n{trail}\n\nError: {error}"
    return f"Job `{job_id}` finished in {elapsed}s.\nProgress:\n{trail}\n\n----- RESULT -----\n{result}"


@mcp.tool
def reset_conversation(conversation_id: str = "mobile") -> str:
    """Clear the stored history for a conversation so the next instruction starts fresh."""
    _check_auth()
    _HISTORY.pop(conversation_id, None)
    return f"Conversation '{conversation_id}' reset."


if __name__ == "__main__":
    if not MCP_BRIDGE_TOKEN:
        print(
            "WARNING: MCP_BRIDGE_TOKEN is not set — anyone who discovers the tunnel URL can "
            "command your swarm. Set it in .env before exposing this publicly.",
            flush=True,
        )
    # Streamable HTTP transport; the MCP endpoint is served at /mcp
    mcp.run(transport="http", host="127.0.0.1", port=MCP_BRIDGE_PORT)
