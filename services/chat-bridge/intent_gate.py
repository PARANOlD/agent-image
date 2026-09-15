"""Gate for passive threaded replies: should Gary answer this, or are humans
just talking to each other in a thread he happens to be in?

Only consulted for allow_new=False dispatches (no @mention). An explicit
@mention or a DM always gets a response without coming through here.

Three layers, cheapest first:
  1. His name appears -> obviously for him, no model call.
  2. Otherwise ask the model, giving it his last message in the thread as
     context so it can tell a follow-up ("what about the other field?")
     from unrelated chatter.
  3. On error, answer. Inside a thread Gary is already part of, a stray
     reply is a much smaller cost than silently ignoring a direct question
     -- which is exactly the failure this module originally caused.

Calls Ollama directly rather than going through OpenHands: this is a cheap
yes/no classification, not agentic work.
"""
from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger("intent_gate")

OLLAMA_BASE_URL = "http://ollama:11434/v1"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b-instruct-q4_K_M")

NAME_RE = re.compile(r"\bgary\b", re.IGNORECASE)

_PROMPT = """In a Slack thread, an assistant named Gary has been helping.

{context}A new message just arrived in that thread:
"{text}"

Should Gary respond to it? Answer YES if it is aimed at him -- a follow-up, a
new question, a correction, or an instruction. Answer NO only if it is clearly
two people talking to each other with no expectation that Gary replies.

Answer with just YES or NO."""


def is_directed_at_gary(text: str, last_reply: str | None = None) -> bool:
    # 1. Addressed by name -- no ambiguity, don't spend a model call on it.
    if NAME_RE.search(text or ""):
        log.info("Intent gate: %r -> True (named)", (text or "")[:60])
        return True

    context = ""
    if last_reply:
        trimmed = " ".join(last_reply.split())[:400]
        context = f'The last thing Gary said was:\n"{trimmed}"\n\n'

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user",
                              "content": _PROMPT.format(context=context, text=text)}],
                "max_tokens": 5,
                "temperature": 0,
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        directed = not answer.startswith("N")
        log.info("Intent gate: %r -> %s (%s)", (text or "")[:60], directed, answer)
        return directed
    except Exception:
        # Fail toward answering -- see module docstring.
        log.exception("Intent gate check failed, defaulting to responding")
        return True
