# services/api/clips.py
# Which recorded videos were processed: name, when the recording started, how long it is. The replay in the web app
# uses this to line the diary up with the video (diary line at 09:22:41 = 0:41 into a video started at 09:22:00).
# Only these numbers are kept, never the video.

import sqlite3
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    start       TEXT NOT NULL,          -- ISO time the recording started
    seconds     REAL NOT NULL,
    windows     INTEGER,
    described   INTEGER,                -- windows the big model described
    created     TEXT NOT NULL,
    status      TEXT DEFAULT 'done',    -- processing | done | failed
    processed_s REAL                    -- the diary is complete up to this many seconds into the video
);
"""


class ClipIndex:
    def __init__(self, db: str):
        self.db = db
        with sqlite3.connect(db) as c:
            c.executescript(_SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(clips)")}
            for col, typ in (("status", "TEXT DEFAULT 'done'"), ("processed_s", "REAL")):
                if col not in cols:                       # a diary file from before progressive processing
                    c.execute(f"ALTER TABLE clips ADD COLUMN {col} {typ}")

    def add(self, clip_id: str, name: str, result: dict):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT OR REPLACE INTO clips (id, name, start, seconds, windows, described, created, status, "
                      "processed_s) VALUES (?, ?, ?, ?, ?, ?, ?, 'done', ?)",
                      (clip_id, name, result["start"], result["video_seconds"], result["windows"],
                       result["big_model_calls"], datetime.now().isoformat(timespec="seconds"), result["video_seconds"]))

    def start(self, clip_id: str, name: str, start: str, seconds: float):
        """A long video being processed piece by piece: listed at once, answerable up to processed_s."""
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT OR REPLACE INTO clips (id, name, start, seconds, windows, described, created, status, "
                      "processed_s) VALUES (?, ?, ?, ?, 0, 0, ?, 'processing', 0)",
                      (clip_id, name, start, seconds, datetime.now().isoformat(timespec="seconds")))

    def progress(self, clip_id: str, processed_s: float, windows: int, described: int, status: str = "processing"):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE clips SET processed_s = ?, windows = ?, described = ?, status = ? WHERE id = ?",
                      (processed_s, windows, described, status, clip_id))

    def all(self) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM clips ORDER BY created DESC")]

    def get(self, clip_id: str) -> dict | None:
        return next((c for c in self.all() if c["id"] == clip_id), None)

    def delete(self, clip_id: str) -> bool:
        """Forget one recording and the diary lines and fingerprints inside its time span."""
        c = self.get(clip_id)
        if c is None:
            return False
        from datetime import timedelta
        t1 = (datetime.fromisoformat(c["start"]) + timedelta(seconds=c["seconds"] + 5)).isoformat(timespec="seconds")
        with sqlite3.connect(self.db) as con:
            con.execute("DELETE FROM activities WHERE ts_start >= ? AND ts_start < ?", (c["start"], t1))
            con.execute("DELETE FROM fingerprints WHERE ts_start >= ? AND ts_start < ?", (c["start"], t1))
            con.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        return True
