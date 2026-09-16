"""Natural-language front-end for deterministic tools.

One narrow LLM call decides which (if any) registered command a message is
asking for and extracts its parameters as JSON. The model's only job is
understanding the sentence -- it never decides *how* to act, and nothing
here executes a side effect. Every command it can route to is a plain
Python function elsewhere (see github_actions.py for the first ones).

This deliberately does NOT use Ollama's tools/tool_calls API. That's the
mechanism openhands_client.py gave up on: qwen2.5-coder never emits a real
structured tool_calls response regardless of size (see its
native_tool_calling comment). Asking for a bare JSON object as normal chat
text sidesteps that -- it's well within a coding model's comfort zone, and
is in fact the exact shape of output qwen kept producing *anyway* during
every failed tool-calling attempt, just misdirected into a tool_calls slot
instead of read back as data.

Meant to be reused for future deterministic tools, not just PR status/list:
pass whatever `commands` registry your caller wants routed.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("llm_router")

OLLAMA_BASE_URL = "http://ollama:11434/v1"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b-instruct-q4_K_M")

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

NO_MATCH = {"command": None, "params": {}}


def route(text: str, commands: dict) -> dict:
    """commands: {name: {"description": str, "params": str}}.

    Returns {"command": <name or None>, "params": {...}}. Fails toward
    NO_MATCH on any error or unparseable response -- callers treat that as
    "not a recognized command, handle as normal chat", so failing safe here
    means falling through to existing behavior, never a false positive
    action."""
    if not commands:
        return dict(NO_MATCH)

    listing = "\n".join(
        f'- "{name}": {c["description"]} (params: {c["params"]})'
        for name, c in commands.items()
    )
    prompt = (
        "You are a command router. Given a message, decide which ONE of "
        "these commands it is asking for, if any:\n\n"
        f"{listing}\n\n"
        'If none apply -- it\'s general conversation, a coding question, '
        'anything else -- use "none".\n\n'
        f'Message: "{text}"\n\n'
        "Respond with ONLY a JSON object, nothing else, no markdown fences: "
        '{"command": "<name or none>", "params": {...}}'
    )
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 120,
                "temperature": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        m = _JSON_BLOCK.search(content)
        if not m:
            log.warning("Router: no JSON in response for %r: %r", text[:60], content[:200])
            return dict(NO_MATCH)
        parsed = json.loads(m.group(0))
        cmd = parsed.get("command")
        if cmd not in commands:
            cmd = None
        params = parsed.get("params")
        result = {"command": cmd, "params": params if isinstance(params, dict) else {}}
        log.info("Router: %r -> %s", text[:60], result)
        return result
    except Exception:
        log.exception("Router call failed for %r", text[:60])
        return dict(NO_MATCH)
