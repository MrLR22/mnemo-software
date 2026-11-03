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
