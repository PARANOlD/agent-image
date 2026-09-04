"""GitHub App authentication: App ID + private key -> JWT -> installation
access token (valid ~1hr, auto-refreshed). Used instead of a static PAT
since github_poller.py runs indefinitely.
"""
from __future__ import annotations

import calendar
import threading
import time
from pathlib import Path

import jwt
import requests

GITHUB_API = "https://api.github.com"
_REFRESH_MARGIN_SECONDS = 300  # regenerate 5 min before actual expiry


class GitHubAppAuth:
    def __init__(self, app_id: str, private_key_path: str, installation_id: str):
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key = Path(private_key_path).read_text()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 600, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - _REFRESH_MARGIN_SECONDS:
                return self._token

            resp = requests.post(
                f"{GITHUB_API}/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self._generate_jwt()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["token"]
            # "2026-09-04T16:30:00Z" -> epoch seconds (UTC, not local time)
            self._expires_at = calendar.timegm(time.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))
            return self._token
