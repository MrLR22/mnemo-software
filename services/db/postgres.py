# services/db/postgres.py
# The reference diary on a PostgreSQL server. PgEventStore has exactly the methods of mnemo's SQLite EventStore
# (modules/storage.py), so the research code (logger, search, answers) runs on it unchanged. The schema lives in
# database/schema.sql and is applied when the first connection opens.

import json
import os
from datetime import datetime

import numpy as np
import psycopg
from psycopg.rows import dict_row

from modules.types import Event

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "..", "database", "schema.sql")
_applied: set[str] = set()


def _blob(v) -> bytes:
    return np.asarray(v, np.float16).tobytes()


def _vec(b) -> np.ndarray:
    return np.frombuffer(bytes(b), np.float16).astype(np.float32)


def connect(url: str) -> psycopg.Connection:
    conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    if url not in _applied:                                  # once per process: CREATE ... IF NOT EXISTS
        with open(SCHEMA) as f:
            conn.execute(f.read())
        _applied.add(url)
    return conn


class PgEventStore:
    def __init__(self, url: str):
        self.url = url
        self.conn = connect(url)

    # ── pick/put events of the first prototype ──
    def add(self, ev: Event, source: str = "") -> int:
        return self.conn.execute(
            "INSERT INTO events (ts, object, action, landmark, confidence, note, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (ev.ts.replace(microsecond=0), ev.object, ev.action, ev.landmark, float(ev.confidence), ev.note, source)
        ).fetchone()["id"]

    @staticmethod
    def _to_event(r: dict) -> Event:
        return Event(ts=r["ts"], object=r["object"], action=r["action"], landmark=r["landmark"],
                     confidence=r["confidence"], note=r["note"])

    def latest(self, obj: str, action: str | None = None, before: datetime | None = None) -> Event | None:
        q, args = "SELECT * FROM events WHERE object = %s", [obj]
        if action:
            q += " AND action = %s"
            args.append(action)
        if before:
            q += " AND ts <= %s"
            args.append(before)
        r = self.conn.execute(q + " ORDER BY ts DESC, id DESC LIMIT 1", args).fetchone()
        return self._to_event(r) if r else None

    def between(self, start: datetime, end: datetime, obj: str | None = None) -> list[Event]:
        q, args = "SELECT * FROM events WHERE ts >= %s AND ts < %s", [start, end]
        if obj:
            q += " AND object = %s"
            args.append(obj)
        return [self._to_event(r) for r in self.conn.execute(q + " ORDER BY ts, id", args)]

    def all(self) -> list[Event]:
        return [self._to_event(r) for r in self.conn.execute("SELECT * FROM events ORDER BY ts, id")]

    def objects(self) -> list[str]:
        return [r["object"] for r in self.conn.execute("SELECT DISTINCT object FROM events ORDER BY object")]

    def clear(self):
        self.conn.execute("DELETE FROM events")

    # ── the diary ──
    def add_activity(self, row: dict, source: str = "") -> int:
        return self.conn.execute(
            "INSERT INTO activities (ts_start, ts_end, verb, object, place, where_, seen, raw, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (row["ts_start"].replace(microsecond=0), row["ts_end"].replace(microsecond=0), row.get("verb"),
             row.get("object"), row.get("place"), row.get("where"), row.get("seen"), row.get("raw"), source)
        ).fetchone()["id"]

    def extend_activity(self, activity_id: int, ts_end: datetime, seen: str | None = None):
        self.conn.execute("UPDATE activities SET ts_end = GREATEST(ts_start, %s), seen = COALESCE(%s, seen) "
                          "WHERE id = %s", (ts_end.replace(microsecond=0), seen, activity_id))

    def activities(self, start: datetime | None = None, end: datetime | None = None) -> list[dict]:
        q, args = "SELECT * FROM activities WHERE TRUE", []
        if start:
            q += " AND ts_end >= %s"
            args.append(start)
        if end:
            q += " AND ts_start < %s"
            args.append(end)
        rows = []
        for r in self.conn.execute(q + " ORDER BY ts_start, id", args):
            r["where"] = r.pop("where_")
            rows.append(r)
        return rows

    def clear_activities(self):
        """Delete the diary and its search vectors (recordings and questions go with it)."""
        self.conn.execute("TRUNCATE activities, fingerprints, text_vectors, questions, clips")

    # ── search vectors ──
    def add_fingerprint(self, ts_start: datetime, ts_end: datetime, vec, model: str):
        self.conn.execute("INSERT INTO fingerprints (ts_start, ts_end, model, vec) VALUES (%s, %s, %s, %s)",
                          (ts_start, ts_end, model, _blob(vec)))

    def fingerprints(self, model: str, start: datetime | None = None, end: datetime | None = None
                     ) -> tuple[list[datetime], list[datetime], np.ndarray]:
        q, args = "SELECT ts_start, ts_end, vec FROM fingerprints WHERE model = %s", [model]
        if start:
            q += " AND ts_end > %s"
            args.append(start)
        if end:
            q += " AND ts_start < %s"
            args.append(end)
        rows = self.conn.execute(q + " ORDER BY ts_start", args).fetchall()
        if not rows:
            return [], [], np.zeros((0, 0), np.float32)
        return [r["ts_start"] for r in rows], [r["ts_end"] for r in rows], np.stack([_vec(r["vec"]) for r in rows])

    def text_vectors(self, texts: list[str], model: str) -> dict[str, np.ndarray]:
        if not texts:
            return {}
        rows = self.conn.execute("SELECT text, vec FROM text_vectors WHERE model = %s AND text = ANY(%s)",
                                 (model, list(texts)))
        return {r["text"]: _vec(r["vec"]) for r in rows}

    def add_text_vectors(self, vecs: dict[str, np.ndarray], model: str):
        with self.conn.cursor() as cur:
            cur.executemany("INSERT INTO text_vectors (text, model, vec) VALUES (%s, %s, %s) "
                            "ON CONFLICT (text, model) DO UPDATE SET vec = EXCLUDED.vec",
                            [(t, model, _blob(v)) for t, v in vecs.items()])

    def close(self):
        self.conn.close()


class PgClipIndex:
    """Same methods as services/api/clips.ClipIndex; times come back as ISO strings like the SQLite version."""

    def __init__(self, url: str):
        self.url = url
        connect(url).close()

    def _run(self, q: str, args=()):
        with connect(self.url) as c:
            return c.execute(q, args).fetchall() if q.lstrip().upper().startswith("SELECT") else c.execute(q, args)

    def add(self, clip_id: str, name: str, result: dict):
        self._run("INSERT INTO clips (id, name, started_at, seconds, windows, described, status, processed_s) "
                  "VALUES (%s, %s, %s, %s, %s, %s, 'done', %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, "
                  "started_at = EXCLUDED.started_at, seconds = EXCLUDED.seconds, windows = EXCLUDED.windows, "
                  "described = EXCLUDED.described, status = 'done', processed_s = EXCLUDED.processed_s",
                  (clip_id, name, datetime.fromisoformat(result["start"]), result["video_seconds"], result["windows"],
                   result["big_model_calls"], result["video_seconds"]))

    def start(self, clip_id: str, name: str, start: str, seconds: float):
        self._run("INSERT INTO clips (id, name, started_at, seconds, status, processed_s) "
                  "VALUES (%s, %s, %s, %s, 'processing', 0) ON CONFLICT (id) DO UPDATE SET status = 'processing', "
                  "processed_s = 0, seconds = EXCLUDED.seconds, started_at = EXCLUDED.started_at",
                  (clip_id, name, datetime.fromisoformat(start), seconds))

    def progress(self, clip_id: str, processed_s: float, windows: int, described: int, status: str = "processing"):
        self._run("UPDATE clips SET processed_s = %s, windows = %s, described = %s, status = %s WHERE id = %s",
                  (processed_s, windows, described, status, clip_id))

    def all(self) -> list[dict]:
        rows = self._run("SELECT * FROM clip_summary ORDER BY created_at DESC")
        out = []
        for r in rows:
            r["start"] = r.pop("started_at").isoformat(timespec="seconds")
            r["created"] = r.pop("created_at").isoformat(timespec="seconds")
            out.append(r)
        return out

    def get(self, clip_id: str) -> dict | None:
        return next((c for c in self.all() if c["id"] == clip_id), None)

    def delete(self, clip_id: str) -> bool:
        """Forget one recording: its diary lines, search vectors and questions go with it."""
        with connect(self.url) as c:
            r = c.execute("SELECT started_at, seconds FROM clips WHERE id = %s", (clip_id,)).fetchone()
            if not r:
                return False
            span = (r["started_at"], r["seconds"] + 5)
            c.execute("DELETE FROM activities WHERE ts_start >= %s AND ts_start < %s + make_interval(secs => %s)",
                      (span[0], span[0], span[1]))
            c.execute("DELETE FROM fingerprints WHERE ts_start >= %s AND ts_start < %s + make_interval(secs => %s)",
                      (span[0], span[0], span[1]))
            c.execute("DELETE FROM questions WHERE clip_id = %s", (clip_id,))
            c.execute("DELETE FROM clips WHERE id = %s", (clip_id,))
            return True


class PgQuestionLog:
    def __init__(self, url: str):
        self.url = url

    def add(self, question: str, answer: str, kind: str | None = None, clip_id: str | None = None,
            as_of: datetime | None = None, moment: datetime | None = None, evidence: list | None = None,
            latency_ms: int | None = None) -> int:
        with connect(self.url) as c:
            return c.execute(
                "INSERT INTO questions (question, answer, kind, clip_id, as_of, moment, evidence, latency_ms) "
                "VALUES (%s, %s, %s, (SELECT id FROM clips WHERE id = %s), %s, %s, %s::jsonb, %s) RETURNING id",
                (question, answer, kind, clip_id, as_of, moment, json.dumps(evidence or [], default=str), latency_ms)
            ).fetchone()["id"]

    def recent(self, limit: int = 20, clip_id: str | None = None) -> list[dict]:
        with connect(self.url) as c:
            q, args = "SELECT * FROM questions", []
            if clip_id:
                q += " WHERE clip_id = %s"
                args.append(clip_id)
            rows = c.execute(q + " ORDER BY asked_at DESC LIMIT %s", (*args, limit)).fetchall()
        for r in rows:
            for k in ("asked_at", "as_of", "moment"):
                r[k] = r[k].isoformat(timespec="seconds") if r[k] else None
        return rows


def table_stats(url: str) -> list[dict]:
    """Rows and size per table: the System screen shows the database as its own part."""
    with connect(url) as c:
        rows = c.execute(
            "SELECT relname AS table, n_live_tup AS rows, pg_total_relation_size(relid) AS bytes "
            "FROM pg_stat_user_tables ORDER BY relname").fetchall()
        exact = {}
        for r in rows:
            exact[r["table"]] = c.execute(f'SELECT count(*) AS n FROM "{r["table"]}"').fetchone()["n"]
        ver = c.execute("SHOW server_version").fetchone()["server_version"]
        size = c.execute("SELECT pg_database_size(current_database()) AS b, current_database() AS db").fetchone()
    return {"engine": f"PostgreSQL {ver}", "database": size["db"], "bytes": size["b"],
            "tables": [dict(r, rows=exact[r["table"]]) for r in rows]}
