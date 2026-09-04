# Gary — Offering & Roadmap

## Vision

Developers keep working locally with lightweight or free local LLMs for their own day-to-day IDE-assisted coding — fast, private, no dependency on Gary for the small stuff. When they want heavier lifting, they prompt an Agent from a Slack channel. The Agent picks up the request, does the work, and hands back a **feature branch** — often the same branch the developer is already working in — so the developer can pull it down, make their own changes, collaborate, test and run it locally, or ask the Agent for another round of changes. Work moves back and forth between human and Agent on the same branch; the Agent is a collaborator, not an isolated black box.

Beyond Slack prompts, Agents pick up **and write** tickets — Jira or GitHub Issues — as a first-class coordination channel, not just a place humans leave instructions. The ecosystem is made of multiple specialized Agents working together: one sets up and runs the application, tests it, and documents behavior changes; another keeps the team — human and Agent alike — on task against the business's acceptance criteria, writing and refining requirements and feeding them back into the ecosystem as tickets. For low-complexity changes that don't need human judgment, an Agent can review and approve a PR itself, reserving human attention for what actually needs it.

All of this runs on **open-source models, on the minimum hardware required** to make the workflow above actually work well — not the biggest hardware available, the least that still delivers it. As hardware scales (GTX 1050 → RTX 5060 Ti → Blackwell-class and beyond), the system captures real performance data and uses it to recommend the right open-source model for whatever's available, so the same image set stays usable from a single home GPU up to a team's shared hardware.

End state: a team opens Gary's configuration portal, connects their chat tool and their source-control/ticketing system, is matched to a model for their hardware, and from then on works alongside a small ecosystem of Agents in Slack/Discord/Teams threads and GitHub/GitLab/Bitbucket issues and PRs — prompting, being handed branches, having low-risk PRs approved automatically, and watching requirements and documentation stay in sync — all driven by locally-hosted models with per-repo `AGENTS.md` files and configurable guardrails.

## Core principles

1. **Images carry no secrets or proprietary configuration.** Slack tokens, GitHub/GitLab/Bitbucket App credentials, per-org settings — none of it is baked into an image. Everything integration-specific is supplied post-pull, through configuration (today: `.env` + `secrets/`; later: the web portal).
2. **Open-source models only, run locally.** No cloud LLM API calls. The tradeoff (weaker models than frontier cloud LLMs) is treated as a solvable hardware/tuning problem, not worked around by reaching for a hosted API.
3. **Minimum sufficient hardware, not maximum available hardware.** The goal isn't "run great on a big GPU" — it's finding the least hardware that still delivers the full collaborative workflow, and being explicit about that floor as models and hardware both improve.
4. **The Agent is a branch collaborator, not a black box.** Work products (feature branches, PRs) are handed back into the developer's normal flow — pulled, built on, redirected — not delivered as a final, isolated artifact.
5. **Tickets and PRs are a coordination channel, not just an inbox.** Agents both consume and produce tickets, and can close the loop on low-complexity PRs autonomously; human review is reserved for what needs judgment.
6. **Config over code changes.** Swapping a model, a chat provider, a source-control provider, or an Agent's role should be a configuration action through the portal, not a redeploy of custom code, once the portal exists.

## Where things stand today (2026-09-04)

Working prototype at this repo root: `docker-compose.yml` running `ollama` (GPU-accelerated), `openhands` (agent-server, driven via REST API), and `chat-bridge` (our own service, bridges Slack + GitHub to one shared OpenHands conversation per thread). Slack (channel mentions, DMs, thread continuation) is fully verified live. GitHub App auth (JWT → installation token) works. ACR mirroring scripts exist (`scripts/pin-versions.sh`, `mirror-to-acr.sh`, `pull-and-run.sh`) but haven't been exercised against a real registry yet. Secrets already live outside the image, in gitignored `.env` / `secrets/` — the seed of principle #1 above, not yet a portal. There is exactly one Agent role today (a general chat-only conversational responder) — the multi-agent ecosystem below is not started.

**Known gap:** no model tested on the current GTX 1050 (qwen2.5-coder 1.5b/3b, qwen3:1.7b) reliably executes real tool calls through Ollama — confirmed at the Ollama API level. Real tool use (reading tickets, editing files, opening PRs) is blocked on this until either a better-fitting model is found or more VRAM arrives (RTX 5060 Ti, already inbound).

## Implementation phases

Each phase builds on the last; none are started except Phase 1.

### Phase 1 — Chat-only single-integration prototype ✅ done
Slack + GitHub, one repo, no tool execution, manual `.env` configuration. This repo, today.

### Phase 2 — Real tool execution + persistent, collaborative git workspace
Re-enable `terminal` / `file_editor` / `task_tracker` tools (already wired, currently disabled — see `openhands_client.py`). Requires a model that actually does tool-calling reliably; likely gated on the 5060 Ti. Pair with a **persistent per-repo git checkout** in `./workspace` (pull deltas like a developer, not fresh-clone-per-task) that supports the hand-back model from the vision above: an Agent works on a feature branch — possibly one the developer already has open — commits, and leaves it in a pullable state rather than a finished, disconnected artifact. Deliberate `confirmation_policy` / `AGENTS.md` guardrails per repo (see Phase 9).

### Phase 3 — Multi-agent coordination & ticket-driven work
Move from one general Agent to specialized roles coordinating through shared state: an **Implementer** (picks up Slack prompts and tickets, produces branches/PRs), a **Build/Test/Document** agent (sets up and runs the application, tests it, documents behavior changes as they happen), and a **Requirements/AC steward** (keeps work aligned to business acceptance criteria, writes and refines requirements, files tickets back into Jira/GitHub). Tickets become bidirectional: Agents read them as work items and write them as output, not just a human-authored inbox. Open design question to resolve here: whether roles are distinct OpenHands conversations/processes or persona-configured variants of one — decide once tool execution (Phase 2) is stable enough to build on.

### Phase 4 — Autonomous low-risk PR review & approval
A complexity/risk-scoring step for PRs (size, files touched, test coverage, prior human-edit patterns) that lets an Agent review and approve a PR itself when it's genuinely low-risk, and routes everything else to a human. This is the mechanism that makes the Phase 3 ecosystem net-reduce human load rather than just relocate it.

### Phase 5 — Performance capture + model/hardware scoring
Instrument Gary to record, per (GPU, model, quantization) combination: tokens/sec, VRAM used, tool-call success rate, task completion rate. Build a scoring system that ranks candidate open-source models for a given detected GPU and recommends (or auto-selects) one, in line with principle #3 (minimum sufficient hardware). Foundation for Phase 9's user-facing matching UI and for keeping Gary fast as new hardware tiers (Blackwell, etc.) come online.

### Phase 6 — Web configuration portal
Replace hand-edited `.env` with a web UI: walks a user through connecting chat and source-control integrations, generates/stores tokens outside the image (volume-mounted secrets store, not the image itself), and becomes the front door for every later phase (model tuning, AGENTS.md generation, team collaboration). This is the phase that actually enables "pull the image and configure through a workflow" as a real product experience rather than a repo you clone and edit.

### Phase 7 — Additional chat integrations
Discord and Microsoft Teams, following the same bridge pattern already established for Slack (`chat-bridge`'s listener abstraction should generalize).

### Phase 8 — Additional source-control integrations
GitLab and Bitbucket, following the same pattern established for the GitHub App (auth + polling or webhook, ticket/PR read-write) — needed so the Phase 3 ecosystem isn't GitHub-only.

### Phase 9 — GPU/model matching UI + tuning UI
Surface Phase 5's scoring system in the portal: given detected hardware, show which open-source models are viable and expected-good, and let the user apply a recommendation with one click. Alongside it, expose per-Agent configuration — active model, which skills/tools an Agent has, which MCP servers it can reach, and the `AGENTS.md`/guardrail authoring flow flagged in Phase 2 — instead of hand-edited.

### Phase 10 — Semi-dedicated/pooled GPU support
Architecture for attaching shared or semi-dedicated GPU resources to a configuration set, rather than assuming one box owns one GPU exclusively. Needed before this can scale beyond a single-user home box to a team running several Agent roles concurrently.

### Phase 11 — Team collaboration surface
Multiple users on one Gary deployment, working through the portal and through chat/source-control threads together with the full Agent ecosystem from Phase 3-4 — shared visibility into what each Agent is doing, review workflows, and an audit trail across code generation, PRs, commits, requirements, and reviews.

## Explicit non-goals

- No cloud or third-party LLM calls, at any phase.
- No proprietary/secret data in a published image, at any phase.
