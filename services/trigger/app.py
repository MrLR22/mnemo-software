# services/trigger/app.py
# The small model service: OUR trained trigger (HOI-TCN, modules/hoi_gate.py) behind HTTP. For a video it returns,
# per 4-s window, the score "is the wearer doing something with their hands?" and whether the big model should be
# called there. Runs on a CPU (hands with MediaPipe, objects with YOLOv8n, then the 240k-parameter model).
#
#   POST /score   multipart file=<video>  [threshold]   → {"window_s", "scores", "call", "threshold", "stats"}
#   Live (video in pieces, services/trigger/session.py):
#   POST /session/{sid}/piece   file=<piece> offset=<s since start>  → {"windows": [{"k", "score"}], "seconds"}
#   POST /session/{sid}/finish                                       → {"windows": [...]}
#   GET  /health                                         → {"model", "parameters"}
#
#   uvicorn services.trigger.app:app --port 8001
#   ENGRAM_TRIGGER_MODEL=path/to/other_checkpoint.pt  (same architecture) swaps the model

import os
import shutil
import tempfile

import services  # noqa: F401  (puts the research code on the path)

import config as C
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

if os.environ.get("ENGRAM_YOLO_IMGSZ"):              # 320 = ~2.4x faster object detection on a CPU (live use)
    C.YOLO_IMGSZ = int(os.environ["ENGRAM_YOLO_IMGSZ"])

app = FastAPI(title="ENGRAM small model service (trigger)")
MODEL = os.environ.get("ENGRAM_TRIGGER_MODEL", os.path.join(os.path.dirname(__file__), "..", "..", "models", "hoi_tcn.pt"))
_gate = {}
_sessions: dict = {}


def gate():
    if "g" not in _gate:
        from modules.hoi_gate import HOIGate
        _gate["g"] = HOIGate(MODEL)
    return _gate["g"]


@app.get("/health")
def health():
    g = gate()
    return {"model": os.path.basename(MODEL), "parameters": g.model.count_parameters(), "window_s": C.VLM_WINDOW_S,
            "yolo_imgsz": C.YOLO_IMGSZ}


@app.post("/score")
def score(file: UploadFile = File(...), threshold: float = Form(C.GATE_THRESHOLD)):
    from modules.hoi_gate import gate_decisions
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:   # deleted below: no video is kept
        shutil.copyfileobj(file.file, tmp)
    try:
        scores, stats = gate().scores(tmp.name)
    finally:
        os.unlink(tmp.name)
    call = gate_decisions(scores, threshold)
    return {"window_s": C.VLM_WINDOW_S, "threshold": threshold, "scores": [round(float(s), 4) for s in scores],
            "call": [bool(c) for c in call], "stats": stats}


def _save(file: UploadFile) -> str:
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    return tmp.name


@app.post("/session/{sid}/piece")
def piece(sid: str, file: UploadFile = File(...), offset: float = Form(...)):
    import time
    from services.trigger.session import TriggerSession
    if sid not in _sessions:
        _sessions.clear()                              # one live session at a time (one wearer)
        _sessions[sid] = TriggerSession(gate())
    path = _save(file)
    t0 = time.time()
    try:
        windows = _sessions[sid].add_piece(path, offset)
    finally:
        os.unlink(path)
    return {"windows": windows, "seconds": round(time.time() - t0, 2)}


@app.post("/session/{sid}/finish")
def finish(sid: str):
    if sid not in _sessions:
        raise HTTPException(404, "no such session")
    return {"windows": _sessions.pop(sid).finish()}
