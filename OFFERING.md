# Gary — Offering & Roadmap

## Vision

Gary becomes a **versioned, distributable set of container images** — not a one-off box — that any team can pull, configure through a **web-based portal**, and run as a self-hosted autonomous coding agent reachable from their chat and source-control tools. It runs entirely on **open-source models, on the team's own hardware** — no cloud or third-party LLM calls, ever. As GPU hardware scales (GTX 1050 → RTX 5060 Ti → Blackwell-class and beyond), Gary captures real performance data and uses it to recommend and auto-configure the right open-source model for whatever's available.

End state: a team opens Gary's configuration portal, connects their chat tool and their source control/ticketing system, picks or is recommended a model for their hardware, and from then on collaborates with Gary in Slack/Discord/Teams threads and GitHub/GitLab/Bitbucket issues and PRs — generating code, opening PRs, responding to review, all driven by locally-hosted models with per-repo `AGENTS.md` files and configurable guardrails.

## Core principles

1. **Images carry no secrets or proprietary configuration.** Slack tokens, GitHub/GitLab/Bitbucket App credentials, per-org settings — none of it is baked into an image. Everything integration-specific is supplied post-pull, through configuration (today: `.env` + `secrets/`; later: the web portal).
2. **Open-source models only, run locally.** No cloud LLM API calls. The tradeoff (weaker models than frontier cloud LLMs) is treated as a solvable hardware/tuning problem, not worked around by reaching for a hosted API.
3. **Hardware-aware, not hardware-fixed.** The same image set should behave sensibly on a 2GB card and a 96GB card by selecting/recommending different models — not by requiring different images.
4. **Config over code changes.** Swapping a model, a chat provider, or a source-control provider should be a configuration action through the portal, not a redeploy of custom code, once the portal exists.

## Where things stand today (2026-09-04)

Working prototype at this repo root: `docker-compose.yml` running `ollama` (GPU-accelerated), `openhands` (agent-server, driven via REST API), and `chat-bridge` (our own service, bridges Slack + GitHub to one shared OpenHands conversation per thread). Slack (channel mentions, DMs, thread continuation) is fully verified live. GitHub App auth (JWT → installation token) works. ACR mirroring scripts exist (`scripts/pin-versions.sh`, `mirror-to-acr.sh`, `pull-and-run.sh`) but haven't been exercised against a real registry yet. Secrets already live outside the image, in gitignored `.env` / `secrets/` — the seed of principle #1 above, not yet a portal.

**Known gap:** no model tested on the current GTX 1050 (qwen2.5-coder 1.5b/3b, qwen3:1.7b) reliably executes real tool calls through Ollama — confirmed at the Ollama API level. Real tool use (reading tickets, editing files, opening PRs) is blocked on this until either a better-fitting model is found or more VRAM arrives (RTX 5060 Ti, already inbound).

## Implementation phases

Each phase builds on the last; none are started except Phase 1.

### Phase 1 — Chat-only single-integration prototype ✅ done
Slack + GitHub, one repo, no tool execution, manual `.env` configuration. This repo, today.

### Phase 2 — Real tool execution
Re-enable `terminal` / `file_editor` / `task_tracker` tools (already wired, currently disabled — see `openhands_client.py`). Requires a model that actually does tool-calling reliably; likely gated on the 5060 Ti. Pair with a **persistent per-repo git checkout** in `./workspace` (pull deltas like a developer, not fresh-clone-per-task — discussed separately) and deliberate `confirmation_policy` / `AGENTS.md` guardrails per repo (see Phase 9).

### Phase 3 — Performance capture + model/hardware scoring
Instrument Gary to record, per (GPU, model, quantization) combination: tokens/sec, VRAM used, tool-call success rate, task completion rate. Build a scoring system that ranks candidate open-source models for a given detected GPU and recommends (or auto-selects) one. This is the foundation for Phase 7's user-facing matching UI and for keeping Gary fast as new hardware tiers (Blackwell, etc.) come online.

### Phase 4 — Web configuration portal
Replace hand-edited `.env` with a web UI: walks a user through connecting chat and source-control integrations, generates/stores tokens outside the image (volume-mounted secrets store, not the image itself), and becomes the front door for every later phase (model tuning, AGENTS.md generation, team collaboration). This is the phase that actually enables "pull the image and configure through a workflow" as a real product experience rather than a repo you clone and edit.

### Phase 5 — Additional chat integrations
Discord and Microsoft Teams, following the same bridge pattern already established for Slack (`chat-bridge`'s listener abstraction should generalize).

### Phase 6 — Additional source-control integrations
GitLab and Bitbucket, following the same pattern established for the GitHub App (auth + polling or webhook, ticket/PR read-write).

### Phase 7 — GPU/model matching UI
Surface Phase 3's scoring system in the portal: given detected hardware, show which open-source models are viable and expected-good, and let the user apply a recommendation with one click.

### Phase 8 — Semi-dedicated/pooled GPU support
Architecture for attaching shared or semi-dedicated GPU resources to a configuration set, rather than assuming one box owns one GPU exclusively. Needed before this can scale beyond a single-user home box.

### Phase 9 — Tuning UI: models, skills, tools, MCPs
Portal-exposed configuration for which model is active, which skills/tools an agent has, and which MCP servers it can reach — plus the AGENTS.md / guardrail authoring flow flagged as part of Phase 2, surfaced here instead of hand-edited.

### Phase 10 — Team collaboration surface
Multiple users on one Gary deployment, working through the portal and through chat/source-control threads together — shared visibility into what Gary is doing, review workflows, and audit trail across code generation, PRs, commits, and reviews.

## Explicit non-goals

- No cloud or third-party LLM calls, at any phase.
- No proprietary/secret data in a published image, at any phase.
