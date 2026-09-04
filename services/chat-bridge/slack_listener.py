"""Slack side of the bridge, via Socket Mode (no inbound public URL needed)."""
from __future__ import annotations

import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

log = logging.getLogger("slack_listener")


class SlackListener:
    def __init__(self, bot_token: str, app_token: str, on_message):
        self.app_token = app_token
        self.on_message = on_message  # callback(thread_key, channel, text, say_fn)
        self.app = App(token=bot_token)
        self._register_handlers()

    def _register_handlers(self):
        @self.app.event("app_mention")
        def handle_mention(event, say):
            self._dispatch(event, say)

        @self.app.event("message")
        def handle_dm(event, say):
            if event.get("channel_type") == "im" and "bot_id" not in event:
                self._dispatch(event, say)

    def _dispatch(self, event, say):
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        thread_key = f"{channel}:{thread_ts}"
        text = event.get("text", "")

        def reply(message: str):
            say(text=message, thread_ts=thread_ts, channel=channel)

        self.on_message(thread_key, text, reply)

    def run_forever(self):
        log.info("Starting Slack Socket Mode handler")
        SocketModeHandler(self.app, self.app_token).start()
