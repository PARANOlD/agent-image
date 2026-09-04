"""Shared conversation-continuity store.

Maps an external thread (a Slack thread_ts, or a GitHub "owner/repo#123") to
the OpenHands conversation_id handling it, so a follow-up on either surface
continues the same underlying conversation instead of starting a new one.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

# NOT Path(__file__).parent.parent.parent -- that assumed the host's nested
# services/chat-bridge/ layout, but the Dockerfile copies files flat into
# /app, so it silently resolved to /state/bridge.db (outside the ./state
# bind mount) instead. Bug: conversation continuity was never actually
# persisted -- every restart lost the surface->conversation_id mapping.
DB_PATH = Path(os.environ.get("STATE_DIR", "/app/state")) / "bridge.db"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            surface TEXT NOT NULL,       -- 'slack' or 'github'
            thread_key TEXT NOT NULL,    -- slack thread_ts, or 'owner/repo#123'
            conversation_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (surface, thread_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS github_poll_cursor (
            repo TEXT PRIMARY KEY,       -- 'owner/repo'
            since TEXT NOT NULL          -- ISO 8601 timestamp of last processed comment
        )
        """
    )
    conn.commit()
    return conn


_conn = _connect()


def get_conversation_id(surface: str, thread_key: str) -> str | None:
    with _lock:
        row = _conn.execute(
            "SELECT conversation_id FROM threads WHERE surface = ? AND thread_key = ?",
            (surface, thread_key),
        ).fetchone()
    return row[0] if row else None


def link_thread(surface: str, thread_key: str, conversation_id: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO threads (surface, thread_key, conversation_id) "
            "VALUES (?, ?, ?)",
            (surface, thread_key, conversation_id),
        )
        _conn.commit()


def find_thread_by_conversation(conversation_id: str) -> tuple[str, str] | None:
    """Reverse lookup, e.g. to cross-post an update to the other surface later."""
    with _lock:
        row = _conn.execute(
            "SELECT surface, thread_key FROM threads WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return tuple(row) if row else None


def get_poll_cursor(repo: str, default: str) -> str:
    with _lock:
        row = _conn.execute(
            "SELECT since FROM github_poll_cursor WHERE repo = ?", (repo,)
        ).fetchone()
    return row[0] if row else default


def set_poll_cursor(repo: str, since: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO github_poll_cursor (repo, since) VALUES (?, ?)",
            (repo, since),
        )
        _conn.commit()
