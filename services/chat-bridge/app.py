"""Wires the Slack and GitHub listeners to one shared OpenHands backend.

Either surface can start or continue a conversation; state.py's mapping
table is the source of truth for "does this thread already have a running
OpenHands conversation".
"""
from __future__ import annotations

import logging
import os
import threading

import state
from github_actions import format_pr_list, format_pr_status, get_pr, list_prs
from github_app_auth import GitHubAppAuth
from github_poller import GitHubPoller
from github_pr_creator import PrCreationError, VALID_BRANCH_TYPES, create_branch_and_pr
from github_ticket_creator import TicketCreationError, create_ticket
from intent_gate import is_directed_at_gary
from llm_router import route as route_command
from openhands_client import OpenHandsClient
from slack_listener import SlackListener

# Registry for llm_router.route() -- the model's only job is picking one of
# these (or "none") and extracting params; execution is 100% the plain
# Python functions above. Add future deterministic tools here.
#
# Workflow note: create_ticket vs create_pr are deliberately separate --
# per the ticket -> pick-up -> draft-PR -> collaborate -> merge workflow,
# "I'd like X" should open a ticket to discuss first, not immediately cut
# code. create_pr stays for the narrower "just cut a branch and PR this"
# case. The "pick up ticket #N" step (ticket -> branch -> draft PR) isn't
# built yet -- create_pr doesn't take an issue number or open as draft.
GITHUB_COMMANDS = {
    "pr_status": {
        "description": "the status/details of one specific pull request",
        "params": "number (integer, the PR number)",
    },
    "pr_list": {
        "description": "a list of open pull requests",
        "params": "none",
    },
    "create_pr": {
        "description": "cut a branch and open a pull request right now for a described code/file change -- only when explicitly asked to cut a branch or open a PR, not for a general feature request",
        "params": "branch_type: one of feature, bugfix, hotfix (default feature if unclear)",
    },
    "create_ticket": {
        "description": "open a new GitHub issue/ticket to propose and discuss a requested code change before any branch or PR is created -- this is the default for a general feature/change request",
        "params": "none",
    },
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

# Slack emoji names (no colons) used to mark a message Gary is working on.
# WORKING goes on as soon as he decides to engage and comes off when he
# answers, so a thread shows at a glance what he's still chewing on.
WORKING_EMOJI = "gear"
DONE_EMOJI = "white_check_mark"
FAILED_EMOJI = "warning"


def _snip(text: str, limit: int = 300) -> str:
    """One-line, length-capped version of a message for logging."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val or ""


def main():
    openhands = OpenHandsClient(base_url=env("OPENHANDS_API_BASE", "http://openhands:8000"))

    # Built once, shared by the deterministic PR lookup (Slack) and the
    # poller (GitHub) below -- both need the same App credentials.
    github_app_id = env("GITHUB_APP_ID")
    github_private_key_path = env("GITHUB_APP_PRIVATE_KEY_PATH")
    github_installation_id = env("GITHUB_APP_INSTALLATION_ID")
    github_repos = [r.strip() for r in env("GITHUB_REPOS").split(",") if r.strip()]
    github_auth = None
    if github_app_id and github_private_key_path and github_installation_id:
        github_auth = GitHubAppAuth(
            app_id=github_app_id,
            private_key_path=github_private_key_path,
            installation_id=github_installation_id,
        )

    def handle(surface: str, thread_key: str, text: str, repo: str | None = None,
               allow_new: bool = True, on_start=None) -> str | None:
        """Route an inbound message to a new-or-existing OpenHands conversation
        and return the agent's reply text, or None if nothing should happen
        (a passive threaded reply into a thread Gary was never in). on_start
        fires once we've actually decided to engage -- after the intent-gate
        check -- so a message Gary ignores never gets marked as in-progress."""
        # Content lines (IN/OUT) exist so scripts/watch-gary.py can show what
        # was actually said, not just that something happened. Truncated to
        # keep the log readable.
        log.info("IN %s/%s | %s", surface, thread_key, _snip(text))

        conversation_id = state.get_conversation_id(surface, thread_key)
        if conversation_id is None:
            if not allow_new:
                return None
            log.info("New conversation for %s/%s", surface, thread_key)
            if on_start:
                on_start()
            conversation_id = openhands.create_conversation(initial_message=text, repo=repo)
            state.link_thread(surface, thread_key, conversation_id)
        else:
            if not allow_new and not is_directed_at_gary(
                    text, last_reply=openhands.last_reply(conversation_id)):
                log.info("Passive reply on %s/%s judged not directed at Gary, staying quiet", surface, thread_key)
                return None
            log.info("Continuing conversation %s for %s/%s", conversation_id, surface, thread_key)
            if on_start:
                on_start()
            openhands.send_message(conversation_id, text)

        reply_text = openhands.wait_for_reply(conversation_id)
        log.info("OUT %s/%s | %s", surface, thread_key, _snip(reply_text))
        return reply_text

    threads = []

    slack_bot_token = env("SLACK_BOT_TOKEN")
    slack_app_token = env("SLACK_APP_TOKEN")
    slack_signing_secret = env("SLACK_SIGNING_SECRET")
    if slack_bot_token and slack_app_token and slack_signing_secret:
        def on_slack_message(thread_key: str, text: str, reply, allow_new: bool, react):
            # PR questions are recognized by an LLM router (natural language
            # in, one of PR_COMMANDS out -- see llm_router.py) but *answered*
            # deterministically: a direct GitHub API call, never routed
            # through OpenHands. The model's job stops at classification; it
            # never gets a chance to fabricate a call or a result.
            #
            # Only for allow_new (an explicit @mention or a DM) -- a passive
            # thread reply that merely mentions a PR in conversation isn't
            # necessarily addressed to Gary, and this shortcut bypasses the
            # intent gate, so it must not run for those.
            if github_auth and allow_new and len(github_repos) == 1:
                repo = github_repos[0]
                routed = route_command(text, GITHUB_COMMANDS)

                if routed["command"] == "pr_status" and isinstance(routed["params"].get("number"), int):
                    number = routed["params"]["number"]
                    react(WORKING_EMOJI)
                    log.info("PR lookup: %s#%d (requested by %s/%s)", repo, number, "slack", thread_key)
                    data = get_pr(github_auth, repo, number)
                    reply(format_pr_status(repo, number, data))
                    react(WORKING_EMOJI, remove=True)
                    react(DONE_EMOJI if data is not None else FAILED_EMOJI)
                    return

                if routed["command"] == "pr_list":
                    react(WORKING_EMOJI)
                    log.info("PR list: %s (requested by %s/%s)", repo, "slack", thread_key)
                    prs = list_prs(github_auth, repo)
                    reply(format_pr_list(repo, prs))
                    react(WORKING_EMOJI, remove=True)
                    react(DONE_EMOJI if prs is not None else FAILED_EMOJI)
                    return

                if routed["command"] == "create_pr":
                    branch_type = routed["params"].get("branch_type")
                    if branch_type not in VALID_BRANCH_TYPES:
                        branch_type = "feature"
                    react(WORKING_EMOJI)
                    log.info("PR creation requested: %s/%s (from %s/%s)", branch_type, repo, "slack", thread_key)
                    try:
                        result = create_branch_and_pr(github_auth, repo, branch_type, text)
                        message = f"Opened `{result['branch']}` → `main`: {result['pr_url']}"
                        reply(message)
                        react(WORKING_EMOJI, remove=True)
                        react(DONE_EMOJI)
                        status_channel = env("SLACK_STATUS_CHANNEL")
                        requesting_channel = thread_key.split(":", 1)[0]
                        if status_channel and status_channel != requesting_channel:
                            slack.post_to_channel(status_channel, f"*New PR opened by Gary*\n{message}")
                    except PrCreationError as exc:
                        reply(str(exc))
                        react(WORKING_EMOJI, remove=True)
                        react(FAILED_EMOJI)
                    except Exception:
                        log.exception("PR creation failed unexpectedly for %s/%s", "slack", thread_key)
                        reply("Something went wrong opening that PR -- check chat-bridge logs.")
                        react(WORKING_EMOJI, remove=True)
                        react(FAILED_EMOJI)
                    return

                if routed["command"] == "create_ticket":
                    react(WORKING_EMOJI)
                    log.info("Ticket creation requested: %s (from %s/%s)", repo, "slack", thread_key)
                    try:
                        ticket = create_ticket(github_auth, repo, text)
                        reply(f"Opened ticket #{ticket['number']}: {ticket['title']}\n{ticket['url']}")
                        react(WORKING_EMOJI, remove=True)
                        react(DONE_EMOJI)
                    except TicketCreationError as exc:
                        reply(str(exc))
                        react(WORKING_EMOJI, remove=True)
                        react(FAILED_EMOJI)
                    except Exception:
                        log.exception("Ticket creation failed unexpectedly for %s/%s", "slack", thread_key)
                        reply("Something went wrong opening that ticket -- check chat-bridge logs.")
                        react(WORKING_EMOJI, remove=True)
                        react(FAILED_EMOJI)
                    return

            engaged = False

            def mark_working():
                nonlocal engaged
                engaged = True
                react(WORKING_EMOJI)

            try:
                response = handle("slack", thread_key, text, allow_new=allow_new,
                                  on_start=mark_working)
                if response is not None:
                    reply(response)
                if engaged:
                    react(WORKING_EMOJI, remove=True)
                    react(DONE_EMOJI)
            except Exception:
                log.exception("Failed handling Slack message on %s", thread_key)
                if engaged:
                    react(WORKING_EMOJI, remove=True)
                    react(FAILED_EMOJI)
                reply("Something went wrong handling that -- check chat-bridge logs.")

        slack = SlackListener(slack_bot_token, slack_app_token, slack_signing_secret, on_slack_message)
        threads.append(threading.Thread(target=slack.run_forever, daemon=True, name="slack"))
    else:
        log.warning("SLACK_BOT_TOKEN/SLACK_APP_TOKEN/SLACK_SIGNING_SECRET not fully set -- Slack listener disabled")

    if github_auth and github_repos:
        def on_github_mention(thread_key: str, repo: str, issue_number: str, body: str, url: str):
            try:
                reply = handle("github", thread_key, body, repo=repo)
                poller.post_comment(repo, issue_number, reply)
            except Exception:
                log.exception("Failed handling GitHub mention on %s", thread_key)

        poller = GitHubPoller(
            auth=github_auth,
            repos=github_repos,
            trigger=env("GITHUB_TRIGGER", "@agent"),
            interval=int(env("GITHUB_POLL_INTERVAL", "30")),
            on_mention=on_github_mention,
        )
        threads.append(threading.Thread(target=poller.run_forever, daemon=True, name="github"))
    else:
        log.warning(
            "GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY_PATH/GITHUB_APP_INSTALLATION_ID/GITHUB_REPOS "
            "not fully set -- GitHub listener disabled"
        )

    if not threads:
        raise RuntimeError("Neither Slack nor GitHub is configured -- nothing to do")

    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
