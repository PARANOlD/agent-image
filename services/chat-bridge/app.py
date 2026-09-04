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
from github_poller import GitHubPoller
from openhands_client import OpenHandsClient
from slack_listener import SlackListener

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")


def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val or ""


def main():
    openhands = OpenHandsClient(base_url=env("OPENHANDS_API_BASE", "http://openhands:8000"))

    def handle(surface: str, thread_key: str, text: str, repo: str | None = None) -> str:
        """Route an inbound message to a new-or-existing OpenHands conversation
        and return the agent's reply text."""
        conversation_id = state.get_conversation_id(surface, thread_key)
        if conversation_id is None:
            log.info("New conversation for %s/%s", surface, thread_key)
            conversation_id = openhands.create_conversation(initial_message=text, repo=repo)
            state.link_thread(surface, thread_key, conversation_id)
        else:
            log.info("Continuing conversation %s for %s/%s", conversation_id, surface, thread_key)
            openhands.send_message(conversation_id, text)

        return openhands.wait_for_reply(conversation_id)

    threads = []

    slack_bot_token = env("SLACK_BOT_TOKEN")
    slack_app_token = env("SLACK_APP_TOKEN")
    if slack_bot_token and slack_app_token:
        def on_slack_message(thread_key: str, text: str, reply):
            try:
                reply(handle("slack", thread_key, text))
            except Exception:
                log.exception("Failed handling Slack message on %s", thread_key)
                reply("Something went wrong handling that -- check chat-bridge logs.")

        slack = SlackListener(slack_bot_token, slack_app_token, on_slack_message)
        threads.append(threading.Thread(target=slack.run_forever, daemon=True, name="slack"))
    else:
        log.warning("SLACK_BOT_TOKEN/SLACK_APP_TOKEN not set -- Slack listener disabled")

    github_token = env("GITHUB_TOKEN")
    github_repos = [r.strip() for r in env("GITHUB_REPOS").split(",") if r.strip()]
    if github_token and github_repos:
        def on_github_mention(thread_key: str, repo: str, issue_number: str, body: str, url: str):
            try:
                reply = handle("github", thread_key, body, repo=repo)
                poller.post_comment(repo, issue_number, reply)
            except Exception:
                log.exception("Failed handling GitHub mention on %s", thread_key)

        poller = GitHubPoller(
            token=github_token,
            repos=github_repos,
            trigger=env("GITHUB_TRIGGER", "@agent"),
            interval=int(env("GITHUB_POLL_INTERVAL", "30")),
            on_mention=on_github_mention,
        )
        threads.append(threading.Thread(target=poller.run_forever, daemon=True, name="github"))
    else:
        log.warning("GITHUB_TOKEN/GITHUB_REPOS not set -- GitHub listener disabled")

    if not threads:
        raise RuntimeError("Neither Slack nor GitHub is configured -- nothing to do")

    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
