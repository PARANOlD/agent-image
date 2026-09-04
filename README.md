# gary — self-hosted autonomous coding agent

[OpenHands](https://github.com/OpenHands/OpenHands) running against a local
**Qwen** model (via Ollama, GPU-accelerated), reachable from **Slack** and
from **GitHub** issue/PR comments, with a single conversation continuable
from either surface. Containerized, versioned, and mirrorable to Azure
Container Registry for delivery to other machines.

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
- `GITHUB_TOKEN` — a fine-grained PAT scoped to the repos you list in `GITHUB_REPOS`, with **Contents**, **Issues**, and **Pull requests** read/write.
- `GITHUB_REPOS` — comma-separated `owner/repo` list to watch for `@agent` mentions.
- `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` — see below.
- `OPENHANDS_API_KEY` — any random string (`openssl rand -hex 32`); authenticates chat-bridge to the openhands API.

Don't paste these into chat with me — edit `.env` directly.

### Creating the Slack app
1. https://api.slack.com/apps → **Create New App** → From scratch.
2. **Socket Mode** → enable it → generate an app-level token with the `connections:write` scope → this is `SLACK_APP_TOKEN` (`xapp-...`).
3. **OAuth & Permissions** → Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `channels:history`. Install to workspace → this is `SLACK_BOT_TOKEN` (`xoxb-...`).
4. **Event Subscriptions** → enable, subscribe to bot events: `app_mention`, `message.im`.
5. Invite the bot to whichever channel you want it in.

## Bring the stack up
```bash
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
1. Message the bot in Slack (`@agent list the files in <repo>`) and confirm a reply.
2. Comment `@agent ...` on an issue/PR in one of `GITHUB_REPOS` and confirm a reply comment.
3. Reply again on either surface and confirm it continues the *same* OpenHands conversation rather than starting a new one (check `state/bridge.db`).

## GPU upgrade path (GTX 1050 → RTX 5060 Ti)
Nothing to change except one line in `.env`:
```
OLLAMA_MODEL=qwen2.5-coder:14b        # or a larger/quantized variant that fits 16GB
```
Re-pull the model (`docker compose exec ollama ollama pull ...`) and restart `openhands`.

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
