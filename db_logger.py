#!/usr/bin/env python3
"""
db_logger.py — SQLite logging backend for ClipCommand.

Creates clipcommand.db in the project root (next to clipcommand.py).
Thread-safe via a dedicated writer thread and queue.

Schema:
    log_entries(id, session_id, timestamp, tag, message, transform_name)
    sessions(id, started_at, transforms_folder)

Auto-purges entries older than RETAIN_DAYS (default 30).
"""

import sqlite3
import threading
import queue
import uuid
from datetime import datetime, timedelta
from pathlib import Path

RETAIN_DAYS = 30
DB_NAME     = "clipcommand.db"


class DBLogger:
    def __init__(self, project_root: str):
        self._db_path   = str(Path(project_root) / DB_NAME)
        self._queue     = queue.Queue()
        self._session   = str(uuid.uuid4())[:8]
        self._stop_evt  = threading.Event()

        self._init_db()
        self._start_session()
        self._purge_old()

        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id           TEXT PRIMARY KEY,
                    started_at   TEXT NOT NULL,
                    transforms_folder TEXT
                );
                CREATE TABLE IF NOT EXISTS log_entries (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id     TEXT NOT NULL,
                    timestamp      TEXT NOT NULL,
                    tag            TEXT NOT NULL,
                    message        TEXT NOT NULL,
                    transform_name TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_log_ts
                    ON log_entries(timestamp);
                CREATE INDEX IF NOT EXISTS idx_log_session
                    ON log_entries(session_id);
                CREATE INDEX IF NOT EXISTS idx_log_tag
                    ON log_entries(tag);
            """)

    def _start_session(self, transforms_folder: str = ""):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id, started_at, transforms_folder) VALUES(?,?,?)",
                (self._session, datetime.now().isoformat(), transforms_folder)
            )

    def _purge_old(self):
        cutoff = (datetime.now() - timedelta(days=RETAIN_DAYS)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM log_entries WHERE timestamp < ?", (cutoff,)
            )
            conn.execute(
                "DELETE FROM sessions WHERE started_at < ? "
                "AND id NOT IN (SELECT DISTINCT session_id FROM log_entries)",
                (cutoff,)
            )

    # ── Writer thread ─────────────────────────────────────────────────────────

    def _writer_loop(self):
        conn = self._connect()
        while not self._stop_evt.is_set():
            try:
                item = self._queue.get(timeout=0.2)
                if item is None:
                    break
                conn.execute(
                    "INSERT INTO log_entries"
                    "(session_id, timestamp, tag, message, transform_name)"
                    " VALUES(?,?,?,?,?)",
                    item
                )
                conn.commit()
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass
        conn.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def log(self, message: str, tag: str = "info", transform_name: str = ""):
        self._queue.put((
            self._session,
            datetime.now().isoformat(),
            tag,
            message,
            transform_name,
        ))

    def get_entries(self, session_id: str = None, tag: str = None,
                    limit: int = 500) -> list:
        """
        Fetch log entries. Returns list of dicts:
            {id, session_id, timestamp, tag, message, transform_name}
        """
        clauses = []
        params  = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if tag:
            clauses.append("tag = ?")
            params.append(tag)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT id, session_id, timestamp, tag, message, transform_name "
            f"FROM log_entries {where} "
            f"ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_sessions(self, limit: int = 50) -> list:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, started_at, transforms_folder FROM sessions "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    @property
    def session_id(self) -> str:
        return self._session

    @property
    def db_path(self) -> str:
        return self._db_path

    def stop(self):
        self._stop_evt.set()
        self._queue.put(None)
        self._writer.join(timeout=3)

