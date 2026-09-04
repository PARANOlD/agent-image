"""Gate for passive threaded replies: is a message actually directed at
Gary, or are humans just continuing to talk in a thread he happens to be
in? Only used for allow_new=False dispatches (no @mention) -- an explicit
@mention or DM always gets a response, no gating needed.

Calls Ollama directly rather than going through OpenHands -- this is a
cheap yes/no classification, not agentic work, and doesn't need
OpenHands' tool/system-prompt machinery or its slower conversation
lifecycle.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("intent_gate")

OLLAMA_BASE_URL = "http://ollama:11434/v1"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:3b-instruct-q4_K_M")

# Deliberately simple, un-hedged framing -- tested live against both 1.5b and
# 3b: 1.5b gave inconsistent/biased answers (flipped between all-YES and
# all-NO depending on prompt wording) even on obvious cases, 3b was
# reasonably accurate with this exact phrasing. Don't swap this back to
# 1.5b-only phrasing without re-testing against real examples.
_PROMPT = 'Slack message: "{text}"\n\nIs this message talking TO an AI assistant named Gary, or is it people talking to each other? Answer with just YES or NO.'


def is_directed_at_gary(text: str) -> bool:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": _PROMPT.format(text=text)}],
                "max_tokens": 5,
                "temperature": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        directed = answer.startswith("Y")
        log.info("Intent gate: %r -> %s (%s)", text[:60], directed, answer)
        return directed
    except Exception:
        # Fail toward staying quiet -- the whole point of this gate is
        # reducing noise, so an error shouldn't fall back to responding.
        log.exception("Intent gate check failed, defaulting to NOT responding")
        return False
