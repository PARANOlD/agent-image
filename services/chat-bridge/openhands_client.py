"""Client for openhands-agent-server's REST API (run standalone, not the
"classic" Socket.IO app -- see docker-compose.yml comment on the openhands
service for why).

Endpoints (verified against openhands/software-agent-sdk source, Sept 2026):
  POST /api/conversations                          -- create + optionally start
  POST /api/conversations/{id}/events               -- send a follow-up message
  POST /api/conversations/{id}/run                  -- start if not auto-run
  GET  /api/conversations/{id}                      -- ConversationInfo.execution_status
  GET  /api/conversations/{id}/agent_final_response -- {"response": "..."}

`workspace.working_dir` beyond a bare path, and any dedicated "clone this repo"
field, weren't confirmed by research -- so repo targeting is done by telling
the agent which repo/issue it's working on in the initial message text and
relying on its GitHub-aware tools + the GITHUB_TOKEN already on the
openhands container. If that proves unreliable in testing, check
docs.openhands.dev/sdk for a proper `workspace` repo field and switch to it.
"""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("openhands_client")

TERMINAL_STATUSES = {"finished", "error", "stuck"}

PERSONA = (
    "Your name is Gary. Refer to yourself as Gary, never as \"OpenHands\" or "
    "\"an OpenHands agent\". You assist with all tasks across the software "
    "development lifecycle -- planning, writing and reviewing code, testing, "
    "documentation, tickets and pull requests -- for the team you work with."
    "\n\n"
    "BE CONCISE. This is your most important instruction:\n"
    "- Lead with the answer. Asked a direct question, give the direct answer "
    "and stop. A one-line question deserves a one-line answer.\n"
    "- Never explain your reasoning, your method, or how you arrived at an "
    "answer unless explicitly asked. If asked to convert a timestamp, give "
    "the converted timestamp -- do not describe the conversion.\n"
    "- Never append 'Explanation', 'Usage', 'Notes' or similar sections to "
    "code. Return the code with at most one short line of context.\n"
    "- No preamble ('Certainly!', 'Great question'), no restating the "
    "question, no summarising what you just said.\n"
    "- Expand only when the user asks for detail, a walkthrough, reasoning, "
    "or a comparison of options. Then be as thorough as they need.\n"
    "\n"
    "Formatting (your replies render in Slack):\n"
    "- Put code, commands, file contents and terminal output in fenced code "
    "blocks (triple backticks), with a language tag where it helps.\n"
    "- Use inline single backticks for short code references in a sentence.\n"
    "- Do not sign your messages or add your name at the end.\n"
    "- Do not end with an offer of further help.\n"
    "- Do not repeat or echo the user's @-mention back to them."
)


class OpenHandsClient:
    def __init__(self, base_url: str, api_key: str | None = None, model: str | None = None,
                 llm_base_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENHANDS_API_KEY", "")
        self.model = model or f"openai/{os.environ.get('OLLAMA_MODEL', 'qwen2.5-coder:1.5b-instruct-q4_K_M')}"
        self.llm_base_url = llm_base_url or "http://ollama:11434/v1"
        self.reply_timeout = int(os.environ.get("OPENHANDS_REPLY_TIMEOUT", "900"))
        self.poll_interval = int(os.environ.get("OPENHANDS_POLL_INTERVAL", "5"))
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["X-Session-API-Key"] = self.api_key

    def _llm_config(self) -> dict:
        return {
            "usage_id": "main",
            "model": self.model,
            "base_url": self.llm_base_url,
            "api_key": "dummy",
        }

    def create_conversation(self, initial_message: str, repo: str | None = None) -> str:
        text = initial_message
        if repo:
            text = f"You are working on the GitHub repository {repo}. {initial_message}"

        body = {
            # No tools attached: tested qwen2.5-coder (1.5b, 3b) and qwen3:1.7b
            # via Ollama and none reliably emit real tool_calls (they either
            # print JSON-shaped text as plain content, or reason it through and
            # never emit the call at all -- confirmed at the Ollama API level,
            # not an openhands issue). Asking for tools it can't actually
            # invoke just produces garbage output, so chat-only until a bigger
            # GPU (RTX 5060 Ti) is in and this gets revisited. Registered tool
            # names, when we do re-enable this, are lowercase snake_case
            # (confirmed via GET /api/tools/) -- e.g. {"name": "terminal",
            # "params": {}} -- the OpenAPI schema's own examples ("TerminalTool"
            # etc.) are stale/wrong. Requires --import-modules openhands.tools
            # on the server (see docker-compose.yml).
            #
            # include_default_tools must be explicitly emptied -- leaving out
            # "tools" alone doesn't disable it, and it defaults to
            # ["FinishTool", "ThinkTool"], so the model was still trying (and
            # failing, same as above) to call ThinkTool on every message.
            "agent": {
                "kind": "Agent",
                "llm": self._llm_config(),
                "include_default_tools": [],
                # Appends to the default system prompt rather than replacing
                # it (which would lose OpenHands' own tool/repo instructions).
                "agent_context": {"system_message_suffix": PERSONA},
            },
            "workspace": {"working_dir": "/workspace"},
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
                "run": True,
            },
        }
        resp = self.session.post(f"{self.base_url}/api/conversations", json=body, timeout=30)
        resp.raise_for_status()
        conversation_id = resp.json()["id"]
        log.info("Created conversation %s", conversation_id)
        return conversation_id

    def send_message(self, conversation_id: str, text: str) -> None:
        body = {"role": "user", "content": [{"type": "text", "text": text}], "run": True}
        resp = self.session.post(
            f"{self.base_url}/api/conversations/{conversation_id}/events", json=body, timeout=30
        )
        resp.raise_for_status()

    def wait_for_reply(self, conversation_id: str) -> str:
        deadline = time.monotonic() + self.reply_timeout
        while time.monotonic() < deadline:
            try:
                resp = self.session.get(f"{self.base_url}/api/conversations/{conversation_id}", timeout=15)
                resp.raise_for_status()
                status = resp.json().get("execution_status")
                if status in TERMINAL_STATUSES:
                    break
            except requests.RequestException:
                # A single slow/dropped poll shouldn't abort the whole wait --
                # this box is resource-constrained and a status check can
                # occasionally stall while the LLM call itself is in flight.
                log.warning("Transient error polling conversation %s, retrying", conversation_id)
            time.sleep(self.poll_interval)
        else:
            return "The agent is still working on this -- it's taking longer than expected, check back shortly."

        resp = self.session.get(
            f"{self.base_url}/api/conversations/{conversation_id}/agent_final_response", timeout=15
        )
        resp.raise_for_status()
        return resp.json().get("response") or "(no response text)"

    def last_reply(self, conversation_id: str) -> str | None:
        """Gary's most recent answer in a conversation, used as context when
        deciding whether a bare follow-up is aimed at him. Best-effort."""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/conversations/{conversation_id}/agent_final_response",
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("response") or None
        except Exception:
            log.warning("Could not fetch last reply for %s", conversation_id)
            return None
