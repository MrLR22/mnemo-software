# tests/test_postgres.py
# The PostgreSQL store must behave exactly like the SQLite one. Runs only when a throwaway test database is given:
#   createdb mnemo_test && ENGRAM_TEST_PG_URL=postgresql:///mnemo_test pytest tests/test_postgres.py
# (The tables of that database are emptied by the tests.)

import os
from datetime import datetime, timedelta

import numpy as np
import pytest

URL = os.environ.get("ENGRAM_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set ENGRAM_TEST_PG_URL to a throwaway Postgres database")


@pytest.fixture
def pg():
    from services.db.postgres import PgEventStore
    s = PgEventStore(URL)
    s.conn.execute("TRUNCATE activities, fingerprints, text_vectors, questions, clips, events RESTART IDENTITY")
    yield s
    s.close()


def test_diary_lines_round_trip(pg):
    t = datetime(2026, 11, 16, 9, 22, 0)
    i = pg.add_activity({"ts_start": t, "ts_end": t + timedelta(seconds=4), "verb": "opens", "object": "fridge",
                         "where": None, "place": "kitchen", "raw": "x"}, source="vlm")
    pg.extend_activity(i, t + timedelta(seconds=8), "fridge, milk")
    rows = pg.activities(t - timedelta(minutes=1), t + timedelta(minutes=1))
    assert len(rows) == 1 and rows[0]["verb"] == "opens" and rows[0]["where"] is None
    assert rows[0]["ts_end"] == t + timedelta(seconds=8) and rows[0]["seen"] == "fridge, milk"
    assert pg.activities(t + timedelta(minutes=5)) == []


def test_vectors_round_trip(pg):
    t = datetime(2026, 11, 16, 9, 0, 0)
    v = np.random.default_rng(0).normal(size=512).astype(np.float32)
    pg.add_fingerprint(t, t + timedelta(seconds=4), v, "clip")
    starts, ends, m = pg.fingerprints("clip", t, t + timedelta(seconds=10))
    assert starts == [t] and m.shape == (1, 512) and np.allclose(m[0], v, atol=1e-2)
    assert pg.fingerprints("clip", t + timedelta(seconds=4))[2].shape == (0, 0)   # a window ending at start is out
    pg.add_text_vectors({"opens fridge": v}, "minilm")
    pg.add_text_vectors({"opens fridge": v * 0}, "minilm")                        # replaced, not duplicated
    assert np.allclose(pg.text_vectors(["opens fridge", "x"], "minilm")["opens fridge"], 0)


def test_clips_questions_and_delete(pg):
    from services.db.postgres import PgClipIndex, PgQuestionLog
    t = datetime(2026, 11, 16, 10, 0, 0)
    clips = PgClipIndex(URL)
    clips.start("c1", "kitchen.mp4", t.isoformat(), 60.0)
    clips.progress("c1", 20.0, 5, 2)
    pg.add_activity({"ts_start": t + timedelta(seconds=10), "ts_end": t + timedelta(seconds=14), "verb": "takes",
                     "object": "cup"}, source="vlm")
    c = clips.get("c1")
    assert c["status"] == "processing" and c["processed_s"] == 20.0 and c["actions"] == 1 and c["start"] == t.isoformat()
    q = PgQuestionLog(URL)
    q.add("what did I take?", "a cup", "search", "c1", evidence=[{"line": "takes cup"}], latency_ms=12)
    assert q.recent(clip_id="c1")[0]["evidence"] == [{"line": "takes cup"}]
    assert clips.delete("c1") and clips.get("c1") is None and pg.activities() == [] and q.recent() == []
