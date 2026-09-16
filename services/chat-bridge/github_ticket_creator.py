"""Opens a GitHub issue (ticket) from a chat request -- the AC-discussion
step in the ticket -> pick-up -> draft-PR -> collaborate -> merge workflow.
No git operations here at all (issues don't need a checkout); just one
narrow model call for title/body, then a plain deterministic API call,
same split as github_pr_creator.py.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("github_ticket_creator")

GITHUB_API = "https://api.github.com"
OLLAMA_BASE_URL = "http://ollama:11434/v1"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b-instruct-q4_K_M")

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class TicketCreationError(Exception):
    """Raised with a message safe to show the user directly."""


def _generate_issue_metadata(description: str) -> dict:
    prompt = (
        "You are drafting a GitHub issue for a requested code change, to be "
        "discussed and refined before any work starts.\n\n"
        f'Requested change: "{description}"\n\n'
        "Respond with exactly this JSON object and nothing else -- no markdown "
        "fences, no commentary:\n"
        '{"title": "short issue title", "body": "a clear description of the '
        'requested change, ending with a placeholder heading for acceptance '
        'criteria to be filled in during discussion"}'
    )
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    match = _JSON_BLOCK.search(content)
    if not match:
        raise TicketCreationError("Couldn't draft a ticket for that request -- try rephrasing.")
    try:
        meta = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise TicketCreationError("Couldn't draft a ticket for that request -- try rephrasing.")
    if not meta.get("title") or not meta.get("body"):
        raise TicketCreationError("Model response was missing a title or body -- try rephrasing.")
    return meta


def create_ticket(auth, repo: str, description: str) -> dict:
    """Returns {"number": int, "url": str, "title": str}. Raises
    TicketCreationError with a user-safe message on failure."""
    meta = _generate_issue_metadata(description)
    try:
        resp = requests.post(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {auth.get_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": meta["title"], "body": meta["body"]},
            timeout=15,
        )
    except requests.RequestException:
        log.exception("Ticket creation network error")
        raise TicketCreationError("Couldn't reach GitHub to open the ticket -- check chat-bridge logs.")
    if not resp.ok:
        log.error("Ticket creation failed: %s %s", resp.status_code, resp.text[:500])
        raise TicketCreationError(f"GitHub rejected the ticket ({resp.status_code}).")
    data = resp.json()
    return {"number": data["number"], "url": data["html_url"], "title": data["title"]}
