# services/db: the database part. One setting chooses where the reference diary lives:
#   ENGRAM_DB_URL=postgresql:///mnemo        → PostgreSQL server (the default setup, see database/README.md)
#   ENGRAM_DB=database/engram.db (no URL)    → a single SQLite file (no server needed; tests and fallback)
# Every other part asks this module for its store, so the backend code is the same for both.

import json
import os
import sqlite3
from datetime import datetime

import services  # noqa: F401  (puts the research code on the path)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def location() -> str:
    """The configured database: a postgresql:// URL or a SQLite file path."""
    return os.environ.get("ENGRAM_DB_URL") or os.environ.get("ENGRAM_DB", os.path.join(ROOT, "database", "engram.db"))


def is_postgres(db: str) -> bool:
    return db.startswith(("postgresql://", "postgres://"))


def open_store(db: str):
    if is_postgres(db):
        from services.db.postgres import PgEventStore
        return PgEventStore(db)
    from modules.storage import EventStore
    return EventStore(db)


def open_clips(db: str):
    if is_postgres(db):
        from services.db.postgres import PgClipIndex
        return PgClipIndex(db)
    from services.api.clips import ClipIndex
    return ClipIndex(db)


def open_questions(db: str):
    if is_postgres(db):
        from services.db.postgres import PgQuestionLog
        return PgQuestionLog(db)
    return SqliteQuestionLog(db)


def stats(db: str) -> dict:
    if is_postgres(db):
        from services.db.postgres import table_stats
        return table_stats(db)
    with sqlite3.connect(db) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        tables = [{"table": n, "rows": c.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0], "bytes": None}
                  for n in sorted(names)]
    return {"engine": f"SQLite {sqlite3.sqlite_version}", "database": os.path.basename(db),
            "bytes": os.path.getsize(db) if os.path.exists(db) else 0, "tables": tables}


BROWSABLE = ("clips", "activities", "fingerprints", "text_vectors", "questions", "events", "clip_diary", "clip_summary")


def _cell(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"vector · {len(bytes(v)) // 2} numbers"
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="milliseconds" if v.microsecond else "seconds")
    if isinstance(v, str) and len(v) > 240:
        return v[:240] + "…"
    return v


def browse(db: str, table: str, limit: int = 100) -> dict:
    """The newest rows of one table, ready to display."""
    if table not in BROWSABLE:
        raise KeyError(table)
    if is_postgres(db):
        from services.db.postgres import browse as pg_browse
        cols, rows, total = pg_browse(db, table, limit)
    else:
        with sqlite3.connect(db) as c:
            try:
                cur = c.execute(f'SELECT * FROM "{table}" ORDER BY 1 DESC LIMIT ?', (limit,))
            except sqlite3.OperationalError:
                raise KeyError(table)
            cols, rows = [d[0] for d in cur.description], cur.fetchall()
            total = c.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    return {"table": table, "columns": cols, "rows": [[_cell(v) for v in r] for r in rows], "total": total}


class SqliteQuestionLog:
    _SCHEMA = """CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asked_at TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
        kind TEXT, clip_id TEXT, as_of TEXT, moment TEXT, evidence TEXT, latency_ms INTEGER)"""

    def __init__(self, db: str):
        self.db = db
        with sqlite3.connect(db) as c:
            c.execute(self._SCHEMA)

    def add(self, question, answer, kind=None, clip_id=None, as_of=None, moment=None, evidence=None, latency_ms=None):
        iso = lambda t: t.isoformat(timespec="seconds") if isinstance(t, datetime) else t
        with sqlite3.connect(self.db) as c:
            return c.execute("INSERT INTO questions (asked_at, question, answer, kind, clip_id, as_of, moment, evidence, "
                             "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (datetime.now().isoformat(timespec="seconds"), question, answer, kind, clip_id, iso(as_of),
                              iso(moment), json.dumps(evidence or [], default=str), latency_ms)).lastrowid

    def recent(self, limit=20, clip_id=None):
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            q, args = "SELECT * FROM questions", []
            if clip_id:
                q += " WHERE clip_id = ?"
                args.append(clip_id)
            rows = [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]
        for r in rows:
            r["evidence"] = json.loads(r["evidence"] or "[]")
        return rows
