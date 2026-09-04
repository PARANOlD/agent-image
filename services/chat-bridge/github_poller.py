"""Polls configured GitHub repos for @mentions in issue/PR comments.

No public endpoint required (the box is behind NAT) -- this just polls the
REST API on an interval. A mention on a thread we haven't seen starts a new
OpenHands conversation; a mention in a thread already linked (state.py)
continues it.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

import state

log = logging.getLogger("github_poller")

GITHUB_API = "https://api.github.com"


class GitHubPoller:
    def __init__(self, token: str, repos: list[str], trigger: str, interval: int, on_mention):
        self.token = token
        self.repos = repos
        self.trigger = trigger.lower()
        self.interval = interval
        self.on_mention = on_mention  # callback(thread_key, repo, issue_number, comment_body, comment_url)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def run_forever(self):
        log.info("Watching %s for %r mentions every %ss", self.repos, self.trigger, self.interval)
        while True:
            for repo in self.repos:
                try:
                    self._poll_repo(repo)
                except Exception:
                    log.exception("Error polling %s", repo)
            time.sleep(self.interval)

    def _poll_repo(self, repo: str):
        default_since = datetime.now(timezone.utc).isoformat()
        since = state.get_poll_cursor(repo, default_since)

        resp = self.session.get(
            f"{GITHUB_API}/repos/{repo}/issues/comments",
            params={"since": since, "sort": "created", "direction": "asc", "per_page": 100},
            timeout=15,
        )
        resp.raise_for_status()
        comments = resp.json()

        latest_seen = since
        for comment in comments:
            created_at = comment["created_at"]
            if created_at > latest_seen:
                latest_seen = created_at

            body = comment.get("body") or ""
            if self.trigger not in body.lower():
                continue
            if comment.get("user", {}).get("type") == "Bot":
                continue  # don't react to our own / other bots' comments

            issue_url = comment["issue_url"]  # .../repos/{owner}/{repo}/issues/{n}
            issue_number = issue_url.rstrip("/").split("/")[-1]
            thread_key = f"{repo}#{issue_number}"
            log.info("Mention in %s: %s", thread_key, comment["html_url"])
            self.on_mention(thread_key, repo, issue_number, body, comment["html_url"])

        if latest_seen != since:
            state.set_poll_cursor(repo, latest_seen)

    def post_comment(self, repo: str, issue_number: str, body: str):
        resp = self.session.post(
            f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments",
            json={"body": body},
            timeout=15,
        )
        resp.raise_for_status()
