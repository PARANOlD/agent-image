"""Deterministic GitHub actions: direct REST API calls, no LLM/tool-calling
involved anywhere in this module. Given a recognized request, this always
returns the same real data (or a clear "couldn't find it"), never a guess --
the opposite failure mode from routing the same question through OpenHands'
agent loop, which has repeatedly hallucinated fake API calls instead of
making real ones (see openhands_client.py's native_tool_calling comment).

This is intentionally the first of what should become a small, hand-written
command set (PR status today; branch/PR creation are natural next additions)
rather than depending on model tool-calling for actions we can just write
directly and keep working.
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger("github_actions")

GITHUB_API = "https://api.github.com"

# "PR #12", "pr 12", "pull request #12", optionally with an explicit
# "owner/repo#12" prefix so a message can name a repo other than the default.
_PR_REF = re.compile(
    r"(?:(?P<repo>[\w.-]+/[\w.-]+)#|\b(?:pr|pull request)\s*#?)(?P<number>\d+)",
    re.IGNORECASE,
)


def find_pr_reference(text: str, default_repo: str | None) -> tuple[str, int] | None:
    """Look for a PR reference in free text. Returns (repo, number), or None
    if the text doesn't look like a PR question at all."""
    m = _PR_REF.search(text or "")
    if not m:
        return None
    repo = m.group("repo") or default_repo
    if not repo:
        return None
    return repo, int(m.group("number"))


def get_pr(auth, repo: str, number: int) -> dict | None:
    """Fetch a PR's real data. None on any failure (doesn't exist, network
    error, etc.) -- the caller decides how to report that, this never
    fabricates a result."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {auth.get_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.exception("Failed to fetch PR %s#%d", repo, number)
        return None


def format_pr_status(repo: str, number: int, data: dict | None) -> str:
    if data is None:
        return f"Couldn't find PR #{number} in {repo} (or the lookup failed -- check chat-bridge logs)."

    state = data["state"]
    if data.get("merged"):
        state = "merged"
    elif state == "open" and data.get("draft"):
        state = "draft"

    lines = [
        f"*PR #{number}: {data['title']}*",
        f"Status: {state}",
        f"Author: {data['user']['login']}",
        f"Branch: `{data['head']['ref']}` → `{data['base']['ref']}`",
    ]
    if data.get("state") == "open" and data.get("mergeable_state"):
        lines.append(f"Mergeable: {data['mergeable_state']}")
    lines.append(data["html_url"])
    return "\n".join(lines)
