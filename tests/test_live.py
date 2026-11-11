# Live mode: pieces → windows in order → big model or skipped, the lag guard, and the app token.
import os
import sys
import time
from datetime import datetime, timedelta

import cv2
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import services  # noqa: E402,F401


def _piece(path, seconds=4, fps=10):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 120))
    for i in range(seconds * fps):
        w.write(np.full((120, 160, 3), (i * 7) % 255, np.uint8))
    w.release()
    return path


class FakeTrigger:
    """Scores 0.9 for even windows, 0.1 for odd ones; reports windows once a later frame exists."""

    def __init__(self):
        self.k = 0

    def piece(self, sid, path, offset):
        upto = int((offset + 3.95) // 4)
        out = [{"k": k, "score": 0.9 if k % 2 == 0 else 0.1} for k in range(self.k, upto)]
        self.k = max(self.k, upto)
        return out

    def finish(self, sid):
        return [{"k": self.k, "score": 0.9}]


class SlowDescriber:
    def __init__(self, delay=0.0):
        self.delay, self.calls = delay, 0

    def describe(self, frames, seconds, check=None):
        self.calls += 1
        time.sleep(self.delay)
        return "PLACE: kitchen\nDID: opens | fridge | -"

    def chat(self, prompt, max_new_tokens=300):
        return "1"


def _run(tmp_path, describer, started_at=None, n=4, max_lag_s=45.0):
    from services.api.stream import StreamSession
    s = StreamSession("t", str(tmp_path / "d.db"), describer, FakeTrigger(), None, threshold=0.6,
                      max_lag_s=max_lag_s, started_at=started_at)
    for i in range(n):
        s.add_piece(_piece(str(tmp_path / f"p{i}.avi")), 4.0 * i)
    s.stop()
    assert s.done.wait(60)
    return s, s.summary()


def test_windows_in_order_trigger_and_heartbeat(tmp_path):
    d = SlowDescriber()
    s, sm = _run(tmp_path, d)
    assert sm["windows"] == 4 and sm["errors"] == []                     # 4 pieces of 4 s = windows 0-3
    assert sm["described"] == 3 and sm["skipped_no_action"] == 1         # 0 and 2 triggered, 3 reported on finish
    assert d.calls == 3 and sm["skipped_lag"] == 0
    assert not any(os.path.exists(str(tmp_path / f"p{i}.avi")) for i in range(4))   # pieces deleted
    from modules.storage import EventStore
    rows = [r for r in EventStore(str(tmp_path / "d.db")).activities() if r["verb"]]
    assert rows and rows[0]["object"] == "fridge"


def test_lag_guard_skips_instead_of_falling_behind(tmp_path):
    # the session "started" 2 minutes ago: every window is already far past the 45-s limit
    s, sm = _run(tmp_path, SlowDescriber(), started_at=datetime.now() - timedelta(minutes=2))
    assert sm["described"] == 0 and sm["skipped_lag"] == 4 and sm["lag_max_s"] is None   # heartbeat wants all


def test_app_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_APP_TOKEN", "tok")
    monkeypatch.setenv("ENGRAM_DB", str(tmp_path / "e.db"))
    monkeypatch.delenv("ENGRAM_DB_URL", raising=False)
    web = tmp_path / "web"                                               # stand-in for the built React app
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>Mnemo</title>")
    monkeypatch.setenv("ENGRAM_WEB_DIR", str(web))
    import importlib
    import services.api.app as api
    importlib.reload(api)
    c = TestClient(api.app)
    assert c.get("/api/diary").status_code == 401
    assert c.get("/api/diary", headers={"X-Engram-Token": "tok"}).status_code == 200
    assert c.get("/api/diary?token=tok").status_code == 200
    assert c.get("/").status_code == 200                                 # the page holds no data


class StuckDescriber(SlowDescriber):
    """Like a dropped connection: answers only after 30 s, but honours the timeout it is given."""

    def describe(self, frames, seconds, check=None, timeout=None):
        self.calls += 1
        if timeout is not None and timeout < 30:
            time.sleep(timeout)
            raise TimeoutError("read timed out")
        time.sleep(30)
        return "PLACE: kitchen"


def test_a_stuck_call_is_cancelled_at_the_lag_limit(tmp_path):
    t0 = time.time()
    s, sm = _run(tmp_path, StuckDescriber(), started_at=datetime.now() - timedelta(seconds=4), n=1, max_lag_s=3.0)
    assert sm["skipped_lag"] == 1 and sm["described"] == 0 and sm["errors"] == []
    assert time.time() - t0 < 10                                         # cancelled at the limit, not after 30 s
