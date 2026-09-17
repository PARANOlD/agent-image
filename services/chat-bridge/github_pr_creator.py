"""Cuts a branch, writes a file, commits, pushes, and opens a PR -- the
git/GitHub mechanics are 100% deterministic Python (real subprocess calls,
real API calls), same principle as github_actions.py. The model is used
for exactly two narrow things, each in its own call:

  1. Metadata extraction (branch slug, commit message, PR title/body,
     filename) -- small JSON, same shape as llm_router.py's classification.
  2. File content generation -- plain text, the model's proven strength
     (see the qwen vs llama3.1 coding comparison, 2026-09-16). Deliberately
     NOT folded into the same call as (1): asking for one big JSON blob
     with escaped file content embedded in it is exactly the kind of
     "do too much in one shot" request that degraded into malformed output
     during the multi-step tool-calling tests earlier this session. Keeping
     the two calls separate keeps each one narrow.

v1 scope: a single file per PR. Multi-file is a natural extension once
this is proven reliable in real use, not added speculatively now.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import requests

from github_actions import get_branch

log = logging.getLogger("github_pr_creator")

GITHUB_API = "https://api.github.com"
OLLAMA_BASE_URL = "http://ollama:11434/v1"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b-instruct-q4_K_M")

VALID_BRANCH_TYPES = {"feature", "bugfix", "hotfix"}

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\n?|\n?```\s*$")


class PrCreationError(Exception):
    """Raised with a message safe to show the user directly -- every
    raise site below explains what actually went wrong, not a stack trace."""


def _chat(prompt: str, max_tokens: int) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _generate_metadata(branch_type: str, description: str) -> dict:
    prompt = (
        "You are preparing a pull request for the following request:\n\n"
        f'"{description}"\n\n'
        "Produce exactly this JSON object, nothing else, no markdown fences:\n"
        '{"slug": "short-kebab-case-branch-suffix", '
        '"filename": "relative/path/for/a/new/file", '
        '"commit_message": "one line, imperative mood", '
        '"pr_title": "short title", '
        '"pr_body": "one or two sentences describing the change"}\n\n'
        "The slug must be lowercase, hyphen-separated, under 40 characters, "
        "no special characters. Pick a filename that makes sense for the "
        "request (e.g. a new markdown doc, a new script, a new config file "
        "-- whatever the request actually calls for)."
    )
    content = _chat(prompt, max_tokens=300)
    m = _JSON_BLOCK.search(content)
    if not m:
        raise PrCreationError("Couldn't work out a branch name/filename for that request.")
    try:
        meta = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise PrCreationError("Couldn't work out a branch name/filename for that request.")

    for key in ("slug", "filename", "commit_message", "pr_title", "pr_body"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise PrCreationError(f"Model response was missing '{key}'; try rephrasing the request.")

    slug = re.sub(r"[^a-z0-9-]", "-", meta["slug"].lower()).strip("-")[:40]
    if not slug:
        raise PrCreationError("Couldn't derive a usable branch name from that request.")
    meta["slug"] = slug
    meta["filename"] = meta["filename"].strip().lstrip("/")
    return meta


def _generate_file_content(filename: str, description: str) -> str:
    prompt = (
        f'Write the complete contents of the file "{filename}" for this request:\n\n'
        f'"{description}"\n\n'
        "Respond with ONLY the raw file content. No markdown code fences, "
        "no explanation before or after, no commentary -- just the file "
        "as it should be saved to disk."
    )
    content = _chat(prompt, max_tokens=2000)
    return _FENCE.sub("", content).strip() + "\n"


def _run(cmd: list[str], cwd: str, env: dict | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error("Command failed: %s\nstdout: %s\nstderr: %s", cmd, result.stdout, result.stderr)
        raise PrCreationError(f"`{cmd[0]} {cmd[1]}` failed -- check chat-bridge logs for details.")


def _generate_pr_title_and_body(branch: str, latest_commit_message: str) -> dict:
    prompt = (
        f'Write a pull request title and body for branch "{branch}", whose '
        f'latest commit message is:\n\n"{latest_commit_message}"\n\n'
        "Produce exactly this JSON object, nothing else, no markdown fences:\n"
        '{"title": "short PR title", "body": "one or two sentences describing the change"}'
    )
    content = _chat(prompt, max_tokens=300)
    m = _JSON_BLOCK.search(content)
    if not m:
        raise PrCreationError("Couldn't draft a PR title/body for that branch.")
    try:
        meta = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise PrCreationError("Couldn't draft a PR title/body for that branch.")
    if not meta.get("title") or not meta.get("body"):
        raise PrCreationError("Model response was missing a PR title or body.")
    return meta


def open_pr_for_branch(auth, repo: str, branch: str, draft: bool = True) -> dict:
    """Opens a PR for a branch that ALREADY EXISTS (e.g. tracked via
    start_work) -- no clone, no new branch, no invented file content. Use
    create_branch_and_pr instead when there's no branch yet and Gary needs
    to cut one and write a file. Returns {"pr_url": str, "branch": str,
    "draft": bool}. Raises PrCreationError with a user-safe message."""
    branch_data = get_branch(auth, repo, branch)
    if branch_data is None:
        raise PrCreationError(f"Couldn't find branch `{branch}` in {repo} -- check the exact name.")
    latest_message = branch_data["commit"]["commit"]["message"].split("\n", 1)[0]
    meta = _generate_pr_title_and_body(branch, latest_message)

    resp = requests.post(
        f"{GITHUB_API}/repos/{repo}/pulls",
        headers={
            "Authorization": f"Bearer {auth.get_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": meta["title"], "head": branch, "base": "main", "body": meta["body"], "draft": draft},
        timeout=15,
    )
    if not resp.ok:
        log.error("PR creation for existing branch failed: %s %s", resp.status_code, resp.text[:500])
        raise PrCreationError(f"Opening the PR failed ({resp.status_code}).")

    return {"pr_url": resp.json()["html_url"], "branch": branch, "draft": draft}


def create_branch_and_pr(auth, repo: str, branch_type: str, description: str) -> dict:
    """Returns {"pr_url": str, "branch": str}. Raises PrCreationError with a
    user-safe message on any failure -- callers should catch that
    specifically and show its message directly, unlike other exceptions."""
    if branch_type not in VALID_BRANCH_TYPES:
        raise PrCreationError(f"Branch type must be one of {sorted(VALID_BRANCH_TYPES)}, got {branch_type!r}.")

    meta = _generate_metadata(branch_type, description)
    branch = f"{branch_type}/{meta['slug']}"
    file_content = _generate_file_content(meta["filename"], description)

    token = auth.get_token()
    workdir = tempfile.mkdtemp(prefix="gary-pr-")
    try:
        clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        _run(["git", "clone", "--depth", "1", clone_url, "repo"], cwd=workdir)
        repo_dir = os.path.join(workdir, "repo")

        _run(["git", "checkout", "-b", branch], cwd=repo_dir)

        file_path = os.path.join(repo_dir, meta["filename"])
        os.makedirs(os.path.dirname(file_path) or repo_dir, exist_ok=True)
        with open(file_path, "w") as fh:
            fh.write(file_content)

        _run(["git", "-c", "user.name=Gary", "-c", "user.email=gary@acclitech.com",
              "add", meta["filename"]], cwd=repo_dir)
        _run(["git", "-c", "user.name=Gary", "-c", "user.email=gary@acclitech.com",
              "commit", "-m", meta["commit_message"]], cwd=repo_dir)
        _run(["git", "push", "origin", branch], cwd=repo_dir)

        resp = requests.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": meta["pr_title"], "head": branch, "base": "main", "body": meta["pr_body"]},
            timeout=15,
        )
        if not resp.ok:
            log.error("PR creation failed: %s %s", resp.status_code, resp.text[:500])
            raise PrCreationError(f"Branch pushed, but opening the PR failed ({resp.status_code}).")

        return {"pr_url": resp.json()["html_url"], "branch": branch}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
