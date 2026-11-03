# The parts working together with a fake big model service (no GPU) and a fake small model service.
import os
import sys

import cv2
import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _video(path, seconds=8, fps=10):
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 120))
    for i in range(seconds * fps):
        w.write(np.full((120, 160, 3), i % 255, np.uint8))
    w.release()
    return path


def test_vlm_service_needs_the_token(monkeypatch):
    monkeypatch.setenv("ENGRAM_VLM_FAKE", "1")
    monkeypatch.setenv("ENGRAM_VLM_TOKEN", "secret")
    from services.common import encode_frames
    from services.vlm.app import app
    c = TestClient(app)
    body = {"frames": encode_frames([np.zeros((60, 80, 3), np.uint8)] * 2), "seconds": 4.0}
    assert c.post("/describe", json=body).status_code == 401
    r = c.post("/describe", json=body, headers={"X-Engram-Token": "secret"})
    assert r.status_code == 200 and "DID:" in r.json()["text"]


def test_backend_clip_to_diary_to_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_DB", str(tmp_path / "e.db"))
    monkeypatch.setenv("ENGRAM_SEARCH", "keyword")
    monkeypatch.setenv("ENGRAM_USE_TRIGGER", "0")
    monkeypatch.setenv("ENGRAM_VLM_URL", "http://unused")
    import importlib
    import services.api.app as api
    importlib.reload(api)
    from services.vlm.app import FakeDescriber
    api._parts["describer"] = FakeDescriber()
    c = TestClient(api.app)
    vid = _video(str(tmp_path / "clip.avi"))
    with open(vid, "rb") as f:
        job = c.post("/api/clips", files={"file": ("clip.avi", f, "video/x-msvideo")}).json()["job"]
    for _ in range(200):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] in ("done", "failed"):
            break
        import time
        time.sleep(0.05)
    assert j["status"] == "done", j
    assert not os.path.exists(vid + ".norm.mp4")
    rows = c.get("/api/diary").json()["rows"]
    assert rows and rows[0]["object"] == "cup"
    assert c.post("/api/ask", json={"question": "did I pick up the cup?"}).json()["answer"]
    assert c.delete("/api/diary").json()["deleted"] and c.get("/api/diary").json()["rows"] == []


def test_replay_diary_with_offsets_and_ask_as_of(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("ENGRAM_SEARCH", "keyword")
    monkeypatch.setenv("ENGRAM_USE_TRIGGER", "0")
    monkeypatch.setenv("ENGRAM_VLM_URL", "http://unused")
    import importlib
    import time
    import services.api.app as api
    importlib.reload(api)

    class Script:
        """Window 0: opens the fridge; window 1: closes it."""
        n = 0

        def describe(self, frames, seconds, check=None):
            Script.n += 1
            return "PLACE: kitchen\nDID: opens | fridge | -" if Script.n == 1 else "PLACE: kitchen\nDID: closes | fridge | -"

        def chat(self, prompt, max_new_tokens=300):
            return "1" if max_new_tokens <= 8 else ("closed" if "closes" in prompt else "open")

    api._parts["describer"] = Script()
    c = TestClient(api.app)
    vid = _video(str(tmp_path / "kitchen.avi"), seconds=8)
    with open(vid, "rb") as f:
        job = c.post("/api/clips", files={"file": ("kitchen.avi", f, "video/x-msvideo")},
                     data={"recorded_at": "2026-11-04T09:00:00"}).json()["job"]
    for _ in range(200):
        if c.get(f"/api/jobs/{job}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    clips = c.get("/api/clips").json()["clips"]
    assert clips[0]["id"] == job and clips[0]["name"] == "kitchen.avi" and clips[0]["seconds"] > 7
    d = c.get(f"/api/clips/{job}/diary").json()
    assert [(r["verb"], r["offset_s"]) for r in d["rows"]] == [("opens", 0.0), ("closes", 4.0)]
    assert d["rows"][0]["state"] == [{"object": "fridge", "state": "open"}]
    early = c.post("/api/ask", json={"question": "did I close the fridge?", "at": "2026-11-04T09:00:03"}).json()
    late = c.post("/api/ask", json={"question": "did I close the fridge?", "at": "2026-11-04T09:00:09"}).json()
    assert all("closes" not in e["verb"] for e in early["evidence"])           # as of 0:03 the closing has not happened
    assert any(e["verb"] == "closes" for e in late["evidence"])
