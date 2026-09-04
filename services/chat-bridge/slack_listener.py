"""Slack side of the bridge, via Socket Mode (no inbound public URL needed)."""
from __future__ import annotations

import logging
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

log = logging.getLogger("slack_listener")

_DEDUP_MAX = 500  # Slack fires both app_mention and message for the same
                   # mention-in-channel event -- track recently seen (channel,
                   # ts) pairs so we don't dispatch it twice.


class SlackListener:
    def __init__(self, bot_token: str, app_token: str, signing_secret: str, on_message):
        self.app_token = app_token
        # callback(thread_key, text, reply_fn, allow_new: bool) -- allow_new is
        # False for a passive threaded reply that isn't an @mention or a DM:
        # only continue a conversation Gary is already in, never start one.
        self.on_message = on_message
        self.app = App(token=bot_token, signing_secret=signing_secret)
        self._seen_lock = threading.Lock()
        self._seen: list[tuple[str, str]] = []
        self._register_handlers()

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
            if self._already_handled(event["channel"], event["ts"]):
                return
            if event.get("channel_type") == "im":
                self._dispatch(event, say, allow_new=True)
            elif event.get("thread_ts"):
                # A threaded reply in a channel, no @mention -- only continue
                # a thread Gary is already in (decided downstream in app.py
                # via state.py), never start a fresh conversation from it.
                self._dispatch(event, say, allow_new=False)

    def _dispatch(self, event, say, allow_new: bool):
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        thread_key = f"{channel}:{thread_ts}"
        text = event.get("text", "")

        def reply(message: str):
            say(text=message, thread_ts=thread_ts, channel=channel)

        self.on_message(thread_key, text, reply, allow_new)

    def run_forever(self):
        log.info("Starting Slack Socket Mode handler")
        SocketModeHandler(self.app, self.app_token).start()
