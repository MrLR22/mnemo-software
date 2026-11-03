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
    created     TEXT NOT NULL
);
"""


class ClipIndex:
    def __init__(self, db: str):
        self.db = db
        with sqlite3.connect(db) as c:
            c.executescript(_SCHEMA)

    def add(self, clip_id: str, name: str, result: dict):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT OR REPLACE INTO clips VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (clip_id, name, result["start"], result["video_seconds"], result["windows"],
                       result["big_model_calls"], datetime.now().isoformat(timespec="seconds")))

    def all(self) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM clips ORDER BY created DESC")]

    def get(self, clip_id: str) -> dict | None:
        return next((c for c in self.all() if c["id"] == clip_id), None)
