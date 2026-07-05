# Command the SEO Blog Swarm from your phone via Claude

This lets you talk to Claude on your phone and have it drive your local swarm
(research → write → images → **your approval** → deploy-as-PR). The swarm runs on
your Mac (it needs your local binary, keys, and the `v-try-on` repo path); Claude
reaches it through a public tunnel and an MCP connector.

```
Claude app (phone)  ──MCP over HTTPS──▶  cloudflared tunnel  ──▶  mcp_bridge.py (:9000)  ──▶  server.py (:8080)  ──▶  swarm
```

## One-time setup

### 1. Set two secrets in `.env`

```bash
# A token server.py requires (protects the local API)
APP_TOKEN=<make-a-long-random-string>

# A second secret this bridge requires from Claude (protects the public tunnel)
MCP_BRIDGE_TOKEN=<make-another-long-random-string>
```

Generate strong values with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

> The swarm can open PRs on your production repo, so treat these like passwords.
> The swarm's built-in approval gate still applies — deploy only runs after you approve,
> and it opens a PR (never pushes to `main`).

### 2. Fix the image key while you're in `.env`

Make sure `GOOGLE_API_KEY` is a real Gemini key (`AIza…`), not the current `AQ.…` value,
or image steps will fail. (See earlier notes.)

## Every time you want mobile control

Open **three terminals** on your Mac (all from the project dir, venv active):

**Terminal 1 — the swarm API:**
```bash
./.venv/bin/python3 server.py
```

**Terminal 2 — the MCP bridge:**
```bash
./.venv/bin/python3 mcp_bridge.py
```

**Terminal 3 — the public tunnel:**
```bash
cloudflared tunnel --url http://localhost:9000
```
cloudflared prints a URL like `https://random-words.trycloudflare.com`.
**Your MCP connector URL is that URL + `/mcp`**, e.g.
`https://random-words.trycloudflare.com/mcp`

(The quick-tunnel URL changes every run. For a stable URL, set up a *named* Cloudflare
tunnel with a domain later — the bridge code doesn't change.)

## Connect it to Claude

1. On **claude.ai** (web — do this once from a laptop or your phone browser):
   **Settings → Connectors → Add custom connector**.
2. Paste the MCP URL (`https://…trycloudflare.com/mcp`).
3. For auth, provide the header `Authorization: Bearer <your MCP_BRIDGE_TOKEN>`
   (use the connector's custom-header / token field). This is the `MCP_BRIDGE_TOKEN`
   you set in `.env`.
4. Enable the connector. It becomes available in your Claude chats, including the mobile app.
   *(If your mobile app build doesn't surface custom connectors yet, just use claude.ai in
   your phone's browser — same account, same connector.)*

Once connected, Claude sees three tools: `run_seo_blog_swarm`, `check_blog_job`, and
`reset_conversation`.

## How to "guide Claude what to do"

Create a **Claude Project** (or paste these as a custom instruction / your first message)
so Claude knows how to operate the swarm:

> You control the **Vtryon SEO Blog Swarm** through the `run_seo_blog_swarm` tool.
> The pipeline is: research an SEO topic → write an on-brand blog post with images →
> show it to me for approval → after I explicitly approve, deploy it to the v-try-on repo
> (English + Hindi + Gujarati) as a **pull request**.
>
> Rules:
> - Tasks run in the background. Call `run_seo_blog_swarm(instruction, conversation_id="mobile")`
>   to start (it returns a job id instantly), then call `check_blog_job(job_id)` and keep polling
>   until it returns the result. **Never resend the instruction while a job is running** — that
>   starts a duplicate pipeline.
> - Keep one conversation going by passing a stable `conversation_id` (e.g. "mobile").
> - Always show me the draft (title, slug, meta description, key sections, FAQs, images)
>   and **wait for my explicit "approve"** before telling the swarm to deploy.
> - Never instruct a deploy or a push to `main` on your own. Deployment is always a PR.
> - When you deploy, report back the PR URL the swarm returns.
> - If the swarm reports an error (e.g. image generation, dirty repo), relay it plainly
>   and ask me how to proceed.

Then from your phone you just say things like:
- *"Research and draft a blog on virtual try-on for lehenga sellers, then show me."*
- *"Tighten the intro and swap the second image for a checklist graphic."*
- *"Approved — deploy it."*

## Verified working

The full chain was tested end-to-end locally: `mcp_bridge.py` → `server.py` → the SEO
Director agency and back, with a real model round-trip; the static-token gate correctly
blocks a wrong token; and the bridge serves a valid MCP endpoint at `/mcp` (the `initialize`
handshake returns a proper JSON-RPC response). Both auth modes below construct cleanly.

## Auth modes (`MCP_AUTH_MODE`)

The bridge supports two ways for Claude to authenticate:

### `token` (default) — static bearer, simplest
Set `MCP_BRIDGE_TOKEN` in `.env`; Claude sends `Authorization: Bearer <that value>`.
Works with the quick tunnel (URL changes each run). Use this to get going.

### `github` — real OAuth, frictionless connector
Authenticates a real GitHub identity, so you don't manage a shared secret. Requires a
**stable public URL** (the named tunnel below), because the OAuth callback must be registered.

1. Create a GitHub OAuth app: GitHub → Settings → Developer settings → **OAuth Apps → New**.
   - Homepage URL: `https://swarm.yourdomain.com`
   - Authorization callback URL: `https://swarm.yourdomain.com/auth/callback`
2. Put the credentials in `.env`:
   ```bash
   MCP_AUTH_MODE=github
   PUBLIC_BASE_URL=https://swarm.yourdomain.com
   GITHUB_OAUTH_CLIENT_ID=<from the OAuth app>
   GITHUB_OAUTH_CLIENT_SECRET=<from the OAuth app>
   ```
3. Restart `mcp_bridge.py`. When you add the connector in Claude, it runs the GitHub login
   flow automatically — no token to paste.

   > Note: this proves a GitHub identity but doesn't by itself restrict *which* GitHub user.
   > Since it's your personal OAuth app on your own tunnel, that's usually fine; tell me if
   > you want a hard allow-list of GitHub usernames and I'll add the check.

## Stable named Cloudflare tunnel (URL that doesn't change)

The quick tunnel is easiest but its URL changes every run — which also breaks OAuth (the
callback URL would keep changing). For a permanent URL (and required for `github` auth):

1. You need a domain on Cloudflare (free plan is fine).
2. One-time, interactive (browser opens — you run these):
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create vtryon-swarm
   cloudflared tunnel route dns vtryon-swarm swarm.yourdomain.com
   ```
3. Copy [deploy/cloudflared-config.example.yml](../deploy/cloudflared-config.example.yml) to
   `~/.cloudflared/config.yml` and fill in your Tunnel ID + hostname.
4. Run it (instead of the quick tunnel):
   ```bash
   cloudflared tunnel run vtryon-swarm
   ```
Your connector URL is then the stable `https://swarm.yourdomain.com/mcp`.

## Notes & limits

- Your Mac must be **awake and online** for all three processes to serve requests.
- Each `run_seo_blog_swarm` call can take minutes (research/writing/deploy); the bridge
  allows up to a 10-minute per-call timeout.
- Conversation history in the bridge is in-memory — restarting `mcp_bridge.py` starts fresh.
- Security: the tunnel URL is public, so the `MCP_BRIDGE_TOKEN` is what actually protects
  you. Don't run the bridge without it. Rotate tokens if a URL leaks.
