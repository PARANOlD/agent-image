"""Deterministic GitHub actions: direct REST API calls, no LLM involved
anywhere in this module. Given a repo/PR-number pair (recognized upstream
by llm_router.py), this always returns the same real data or a clear
"couldn't find it" -- never a guess. Opposite failure mode from routing
the same question through OpenHands' agent loop, which has repeatedly
hallucinated fake API calls instead of making real ones (see
openhands_client.py's native_tool_calling comment).

Natural language understanding lives in llm_router.py; this module never
sees free text, only already-extracted parameters. Intentionally the
first of what should become a small, hand-written command set (branch/PR
creation are natural next additions) rather than depending on model
tool-calling for actions we can just write directly and keep working.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("github_actions")

GITHUB_API = "https://api.github.com"


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


def list_prs(auth, repo: str, state: str = "open") -> list[dict] | None:
    """Fetch open (by default) PRs for a repo. None on failure -- distinct
    from an empty list, which means the call succeeded and there are none."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/pulls",
            params={"state": state, "per_page": 20, "sort": "created", "direction": "desc"},
            headers={
                "Authorization": f"Bearer {auth.get_token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.exception("Failed to list PRs for %s", repo)
        return None


def get_branch(auth, repo: str, branch: str) -> dict | None:
    """Fetch a branch's real data (name + latest commit). None on any
    failure (doesn't exist, network error, etc.) -- same never-fabricate
    contract as get_pr."""
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/branches/{branch}",
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
        log.exception("Failed to fetch branch %s in %s", branch, repo)
        return None


def format_branch_status(repo: str, branch: str, data: dict | None) -> str:
    if data is None:
        return f"Couldn't find branch `{branch}` in {repo} -- check the exact name and try again."
    commit = data["commit"]
    sha = commit["sha"][:7]
    message = commit["commit"]["message"].split("\n", 1)[0]
    return f"Tracking `{branch}` for this thread. Latest commit: `{sha}` {message}"


def format_pr_list(repo: str, prs: list[dict] | None) -> str:
    if prs is None:
        return f"Couldn't list PRs for {repo} (lookup failed -- check chat-bridge logs)."
    if not prs:
        return f"No open PRs in {repo}."

    lines = [f"*Open PRs in {repo}:*"]
    for pr in prs:
        draft = " (draft)" if pr.get("draft") else ""
        lines.append(
            f"• [#{pr['number']}]({pr['html_url']}) {pr['title']}{draft} "
            f"— `{pr['head']['ref']}` by {pr['user']['login']}"
        )
    return "\n".join(lines)


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
