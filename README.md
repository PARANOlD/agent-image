# gary — self-hosted autonomous coding agent

[OpenHands](https://github.com/OpenHands/OpenHands) running against a local
**Qwen** model (via Ollama, GPU-accelerated), reachable from **Slack** and
from **GitHub** issue/PR comments, with a single conversation continuable
from either surface. Containerized, versioned, and mirrorable to Azure
Container Registry for delivery to other machines. See [OFFERING.md](OFFERING.md)
for the longer-term vision and phased roadmap this fits into.

## Current status (2026-09-15)
Running `qwen2.5-coder:14b-instruct-q4_K_M` on an RTX 5060 Ti (16GB), ~13GB
VRAM, ~18s per coding answer. Slack (channel mentions, DMs, thread follow-up
without re-mentioning) is fully working; GitHub App auth works but hasn't
been exercised with real tool use yet.

**Still chat-only.** No tools (`terminal`/`file_editor`/`task_tracker`) are
attached to conversations — none of the small models tested on the old GTX
1050 (qwen2.5-coder 1.5b/3b, qwen3:1.7b) would reliably emit real tool calls
through Ollama, confirmed at the Ollama API level. The 14B has the headroom
to be retested; that's the gate on turning tools back on in
`services/chat-bridge/openhands_client.py`.

## Components
- `ollama` — serves the local Qwen model over an OpenAI-compatible API, GPU-accelerated.
- `openhands` — [`openhands-agent-server`](https://github.com/OpenHands/software-agent-sdk) run standalone (REST API on `:8000`), not the "classic" OpenHands app. `chat-bridge` sends the LLM config (pointing at `ollama`) per-request, so nothing LLM-related is baked into this container. Has a `GITHUB_TOKEN` for repo + Issues access.
- `chat-bridge` — our own service. Listens on Slack (Socket Mode) and polls GitHub for `@agent` mentions, and keeps both talking to the same OpenHands conversation via a small SQLite mapping (`state/bridge.db`).

## One-time host setup (you run this — needs sudo)
```bash
./scripts/setup-host.sh
```
Installs the `docker compose` plugin and `nvidia-container-toolkit`, wires up the nvidia Docker runtime, and smoke-tests GPU access from a container.

## Configure secrets
```bash
cp .env.example .env
```
Fill in:
- `GITHUB_APP_ID` / `GITHUB_APP_INSTALLATION_ID` / `GITHUB_APP_PRIVATE_KEY_FILENAME` — see below.
- `GITHUB_REPOS` — comma-separated `owner/repo` list to watch for `@agent` mentions.
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` — see below.
- `OPENHANDS_API_KEY` — any random string (`openssl rand -hex 32`); authenticates chat-bridge to the openhands API.

Don't paste these into chat with me — edit `.env` directly.

### GitHub access (via a GitHub App, not a PAT)
1. https://github.com/settings/apps/new → give it repo-scoped permissions (Contents, Issues, Pull requests: read/write). Under **Webhook**, uncheck **Active** — we poll instead of receiving webhooks, no public endpoint needed.
2. On the app's settings page: **Generate a private key** → downloads a `.pem` file. Save it into `./secrets/` (create the directory if needed) and set `GITHUB_APP_PRIVATE_KEY_FILENAME` to its filename.
3. **Install App** on the repo(s) you want it to work on → note the installation ID from the URL at github.com/settings/installations → `GITHUB_APP_INSTALLATION_ID`.
4. `chat-bridge` mints its own short-lived tokens per-request from these (see `services/chat-bridge/github_app_auth.py`). The `openhands` container's own git operations use a separately-minted, longer-lived-in-`.env` token — run `./scripts/mint-github-app-token.sh` once initially and again whenever it expires (~hourly; git push/clone in the sandbox will start failing auth when it has).

### Creating the Slack app
1. https://api.slack.com/apps → **Create New App** → From scratch.
2. **Socket Mode** → enable it → generate an app-level token with the `connections:write` scope → this is `SLACK_APP_TOKEN` (`xapp-...`).
3. **OAuth & Permissions** → Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `channels:history`, `reactions:write` (mark messages he's working on). Install to workspace → this is `SLACK_BOT_TOKEN` (`xoxb-...`).
4. **Event Subscriptions** → enable, subscribe to bot events: `app_mention`, `message.im`, `message.channels` (and `message.groups` for private channels) -- the last two let Gary auto-continue a thread he's already in without being re-@mentioned on every reply.
5. Invite the bot to whichever channel you want it in.

**Whenever you change scopes or event subscriptions later**, Slack requires you to explicitly reinstall the app (OAuth & Permissions → reinstall banner) before the change takes effect -- saving alone does nothing, and the running installation silently keeps using the old permission set. Cost us a very confusing debugging session; don't skip it.

## Bring the stack up
```bash
mkdir -p workspace secrets state
chmod 777 workspace   # openhands runs as uid 10001; the bind mount is owned
                      # by your host user, so without this it fails to even
                      # start ("PermissionError: workspace/conversations")
docker compose up -d
docker compose exec ollama ollama pull "$(grep OLLAMA_MODEL .env | cut -d= -f2)"
docker compose ps
```

## Verify
```bash
curl localhost:11434/api/tags                                   # model shows up
curl -H "X-Session-API-Key: $(grep OPENHANDS_API_KEY .env | cut -d= -f2)" \
     localhost:8000/api/conversations                            # openhands API reachable (localhost only)
```
Then:
1. Message the bot in Slack (`@Gary who are you?`) and confirm a reply. There's no "processing" message -- just a ⚙️ reaction on your message while he works, then the answer.
2. Comment `@agent ...` on an issue/PR in one of `GITHUB_REPOS` and confirm a reply comment.
3. Reply again on either surface (no re-mention needed in an existing Slack thread) and confirm it continues the *same* OpenHands conversation rather than starting a new one (check `state/bridge.db`).

## Behavior notes
- **Persona**: Gary's name, SDLC-focused purpose, concision rules and Slack formatting rules are injected via `agent_context.system_message_suffix` in `openhands_client.py` (appends to OpenHands' default system prompt rather than replacing it, so its own tool/repo instructions stay intact).
- **Concise by default**: answers lead with the answer and stop -- no reasoning narration, no `Explanation`/`Usage` sections bolted onto code, no preamble. Ask for detail, a walkthrough, or reasoning and he expands. Asked to convert a timestamp he returns the timestamp, not a description of the conversion.
- **Won't respond to everything**: an explicit `@mention` or a DM always gets a response. A plain threaded reply with no mention only gets a response if `intent_gate.py` judges it's actually directed at Gary (a cheap direct call to Ollama, not routed through OpenHands) -- otherwise Gary stays quiet. Fails toward staying quiet on any error.
- **Bare replies**: no name prefix, no "processing" ack, no sign-off. Gary's own @-mention is stripped from the incoming text before the model sees it, so it can't be echoed back into the answer.
- **Progress reactions**: instead of an ack message, Gary reacts to the triggering message with ⚙️ once he decides to engage, swapping it for ✅ when he answers (or ⚠️ if it blew up). Emoji names are constants at the top of `app.py`. Needs `reactions:write`; without it the reactions are skipped with a logged warning and everything else still works.

## Changing models
One line in `.env`, then re-pull and restart:
```bash
OLLAMA_MODEL=qwen2.5-coder:14b-instruct-q4_K_M   # 9GB weights, ~13GB loaded at 24k ctx
```
```bash
docker compose exec ollama ollama pull "$(grep OLLAMA_MODEL .env | cut -d= -f2)"
./scripts/restart-gary.sh
```
Mind the VRAM math: Ollama sizes the KV cache as `context_length × num_parallel`,
so the loaded footprint is well above the weights. A 14B at 24k context needs
~13GB at one request slot and ~20GB at two -- and if it doesn't fit, Ollama
silently runs it at 100% CPU instead of erroring. `OLLAMA_NUM_PARALLEL` is
pinned to 1 for that reason, and `restart-gary.sh` verifies GPU placement.

## Shipping to another machine via ACR
```bash
./scripts/pin-versions.sh      # resolve :latest to digests, write to .env
./scripts/mirror-to-acr.sh     # az acr login, build+push everything to your ACR
```
On the target machine: copy this repo + your `.env` (with ACR-mirrored image refs), run `scripts/setup-host.sh` there too, then:
```bash
./scripts/pull-and-run.sh
```

## Known tradeoffs / open questions
- **No Docker socket mount.** Unlike the "classic" OpenHands app (which mounts `/var/run/docker.sock` to launch per-task sandbox containers), `openhands-agent-server` run standalone executes tools directly in its own container against the `./workspace` bind mount. This is a smaller blast radius, but if your tasks need to run Docker themselves *inside* the sandbox (Docker-in-Docker), you'll need to add that back (see Agent Canvas docs on `--privileged`) -- not done here by default.
- **Repo targeting is prompt-driven.** `openhands_client.py` tells the agent which repo it's working on in the initial message text rather than a dedicated API field, because the exact `workspace` JSON schema for repo/clone config wasn't confirmed. Watch the first few GitHub-triggered runs; if it doesn't reliably clone the right repo, check `docs.openhands.dev/sdk` for a proper field and fix `create_conversation()` in `services/chat-bridge/openhands_client.py`.
- **Official alternative to our GitHub poller**: OpenHands publishes [`openhands-github-action`](https://github.com/OpenHands/openhands-github-action), which speaks the same REST API and lets GitHub itself dispatch the trigger (no polling) -- but it needs network reachability from the Action runner to this box's `openhands` API, which means either a public endpoint or a self-hosted GitHub Actions runner on this LAN. Our poller avoids that requirement entirely, at the cost of up-to-`GITHUB_POLL_INTERVAL`-seconds latency. Worth revisiting if you add a self-hosted runner later.
- Treat this box's OpenHands instance as trusted-automation-only, not something exposed to untrusted input -- it has real GitHub write access.
