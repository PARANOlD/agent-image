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
from github_app_auth import GitHubAppAuth
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

    def handle(surface: str, thread_key: str, text: str, repo: str | None = None,
               allow_new: bool = True) -> str | None:
        """Route an inbound message to a new-or-existing OpenHands conversation
        and return the agent's reply text, or None if nothing should happen
        (a passive threaded reply into a thread Gary was never in)."""
        conversation_id = state.get_conversation_id(surface, thread_key)
        if conversation_id is None:
            if not allow_new:
                return None
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
    slack_signing_secret = env("SLACK_SIGNING_SECRET")
    if slack_bot_token and slack_app_token and slack_signing_secret:
        def on_slack_message(thread_key: str, text: str, reply, allow_new: bool):
            try:
                response = handle("slack", thread_key, text, allow_new=allow_new)
                if response is not None:
                    reply(response)
            except Exception:
                log.exception("Failed handling Slack message on %s", thread_key)
                reply("Something went wrong handling that -- check chat-bridge logs.")

        slack = SlackListener(slack_bot_token, slack_app_token, slack_signing_secret, on_slack_message)
        threads.append(threading.Thread(target=slack.run_forever, daemon=True, name="slack"))
    else:
        log.warning("SLACK_BOT_TOKEN/SLACK_APP_TOKEN/SLACK_SIGNING_SECRET not fully set -- Slack listener disabled")

    github_app_id = env("GITHUB_APP_ID")
    github_private_key_path = env("GITHUB_APP_PRIVATE_KEY_PATH")
    github_installation_id = env("GITHUB_APP_INSTALLATION_ID")
    github_repos = [r.strip() for r in env("GITHUB_REPOS").split(",") if r.strip()]
    if github_app_id and github_private_key_path and github_installation_id and github_repos:
        def on_github_mention(thread_key: str, repo: str, issue_number: str, body: str, url: str):
            try:
                reply = handle("github", thread_key, body, repo=repo)
                poller.post_comment(repo, issue_number, reply)
            except Exception:
                log.exception("Failed handling GitHub mention on %s", thread_key)

        auth = GitHubAppAuth(
            app_id=github_app_id,
            private_key_path=github_private_key_path,
            installation_id=github_installation_id,
        )
        poller = GitHubPoller(
            auth=auth,
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
