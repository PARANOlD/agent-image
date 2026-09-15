"""Slack side of the bridge, via Socket Mode (no inbound public URL needed)."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

log = logging.getLogger("slack_listener")

_DEDUP_MAX = 500  # Slack fires both app_mention and message for the same
                   # mention-in-channel event -- track recently seen (channel,
                   # ts) pairs so we don't dispatch it twice.


class SlackListener:
    def __init__(self, bot_token: str, app_token: str, signing_secret: str, on_message):
        self.app_token = app_token
        # callback(thread_key, text, reply_fn, allow_new, user_name, react_fn)
        # -- allow_new is False for a passive threaded reply that isn't an
        # @mention or a DM: only continue a conversation Gary is already in,
        # never start one. react_fn(emoji, remove=False) marks the triggering
        # message.
        self.on_message = on_message
        self.app = App(token=bot_token, signing_secret=signing_secret)
        self._seen_lock = threading.Lock()
        self._seen: list[tuple[str, str]] = []
        self._name_cache: dict[str, str] = {}
        self._register_handlers()

    def _display_name(self, user_id: str) -> str:
        """Resolve a Slack user ID to a display name (users:read scope).
        Falls back to a generic greeting if the lookup fails or the scope
        isn't granted -- this is cosmetic, never worth failing a reply over.
        """
        if not user_id:
            return "there"
        if user_id in self._name_cache:
            return self._name_cache[user_id]
        try:
            info = self.app.client.users_info(user=user_id)["user"]
            profile = info.get("profile", {})
            name = profile.get("display_name") or info.get("real_name") or info.get("name") or "there"
        except Exception:
            log.exception("Failed to resolve display name for %s", user_id)
            name = "there"
        self._name_cache[user_id] = name
        return name

    def _already_handled(self, channel: str, ts: str) -> bool:
        key = (channel, ts)
        with self._seen_lock:
            if key in self._seen:
                return True
            self._seen.append(key)
            if len(self._seen) > _DEDUP_MAX:
                self._seen.pop(0)
            return False

    def _register_handlers(self):
        @self.app.event("app_mention")
        def handle_mention(event, say):
            if self._already_handled(event["channel"], event["ts"]):
                return
            self._dispatch(event, say, allow_new=True)

        @self.app.event("message")
        def handle_message(event, say):
            if "bot_id" in event or event.get("subtype"):
                return
            # Dedup check must happen per-branch, right before an actual
            # dispatch -- not unconditionally at the top. Slack sends both
            # "message" and "app_mention" for a channel mention; a top-level
            # channel message matches neither branch below and does nothing,
            # but marking it "seen" anyway used to poison the dedup set for
            # the app_mention event that follows, silently swallowing every
            # channel mention.
            if event.get("channel_type") == "im":
                if self._already_handled(event["channel"], event["ts"]):
                    return
                self._dispatch(event, say, allow_new=True)
            elif event.get("thread_ts"):
                # A threaded reply in a channel, no @mention -- only continue
                # a thread Gary is already in (decided downstream in app.py
                # via state.py), never start a fresh conversation from it.
                if self._already_handled(event["channel"], event["ts"]):
                    return
                self._dispatch(event, say, allow_new=False)

    def _dispatch(self, event, say, allow_new: bool):
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        thread_key = f"{channel}:{thread_ts}"
        text = event.get("text", "")
        user_name = self._display_name(event.get("user"))
        # Reactions go on the message that triggered us, not the thread root.
        message_ts = event["ts"]

        def reply(message: str):
            say(text=message, thread_ts=thread_ts, channel=channel)

        def react(emoji: str, remove: bool = False):
            """Add/remove a reaction on the triggering message. Needs the
            reactions:write scope; failures are logged and swallowed since a
            missing reaction should never cost us the actual reply."""
            try:
                fn = self.app.client.reactions_remove if remove else self.app.client.reactions_add
                fn(channel=channel, timestamp=message_ts, name=emoji)
            except Exception as exc:
                log.warning("reaction %s%s failed: %s", "-" if remove else "+", emoji, exc)

        self.on_message(thread_key, text, reply, allow_new, user_name, react)

    def _announce_startup(self):
        """Posts a deploy note to SLACK_STATUS_CHANNEL every time chat-bridge
        (re)starts -- i.e. every redeploy -- so it's visible in Slack when
        Gary comes back up with new code/config, not just in docker logs.
        Uses the Web API directly, so it doesn't need the Socket Mode
        connection to be up yet.

        Version and change list come from state/deploy-info.json, written by
        scripts/write-deploy-info.sh at deploy time (the container has no git
        repo of its own to read). Falls back to a bare timestamp if that file
        is missing, e.g. someone ran `docker compose up` by hand."""
        channel = os.environ.get("SLACK_STATUS_CHANNEL")
        if not channel:
            log.info("SLACK_STATUS_CHANNEL not set, skipping startup announcement")
            return

        info = {}
        info_path = Path(os.environ.get("STATE_DIR", "/app/state")) / "deploy-info.json"
        try:
            info = json.loads(info_path.read_text())
        except FileNotFoundError:
            log.info("No deploy-info.json; announcing without a change list")
        except Exception:
            log.exception("Could not read %s", info_path)

        version = info.get("version") or datetime.now().strftime("%Y.%m.%d-unknown")
        model = info.get("model") or os.environ.get("OLLAMA_MODEL", "unknown")
        lines = [f"*v{version} deployed.*", f"[_{model}_]"]
        lines += [f"• {change}" for change in info.get("changes", [])]

        try:
            self.app.client.chat_postMessage(channel=channel, text="\n".join(lines))
        except Exception:
            log.exception("Failed to post startup announcement to %s", channel)

    def run_forever(self):
        log.info("Starting Slack Socket Mode handler")
        self._announce_startup()
        SocketModeHandler(self.app, self.app_token).start()
