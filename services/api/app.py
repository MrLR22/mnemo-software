# services/api/app.py
# The backend: the only part the apps talk to. It receives clips, runs the pipeline through the two model services,
# keeps the reference diary (database/engram.db) and answers questions from it. It never loads Qwen itself.
#
#   POST   /api/clips        multipart file=<video> [recorded_at=ISO time the recording started] → {"job"}
#   GET    /api/jobs/{id}    → {"status": queued | running | done | failed, "step", "result" | "error"}
#   GET    /api/diary        [?day=YYYY-MM-DD] → diary lines of that day (default today)
#   POST   /api/ask          {"question"} → {"answer", "moment", "evidence"}
#   GET    /api/alerts       → objects last seen open / on
#   DELETE /api/diary        → deletes the whole diary and its search vectors
#   GET    /api/health       → which services are reachable
#   Live (services/api/stream.py; lag kept under ENGRAM_MAX_LAG_S, default 45 s):
#   POST   /api/live/start                → {"session"}
#   POST   /api/live/{sid}/piece          file=<piece> offset=<seconds since start> → {"queued"}
#   POST   /api/live/{sid}/stop           → summary
#   GET    /api/live/{sid}                → summary: lag (last / max / mean), described / skipped windows
#   GET    /                 → the web app (apps/web)
#
# Settings (environment or .env): ENGRAM_VLM_URL + ENGRAM_VLM_TOKEN (big model service), ENGRAM_TRIGGER_URL and
# ENGRAM_USE_TRIGGER=1 (small model service), ENGRAM_DB (default database/engram.db), ENGRAM_SEARCH=hybrid|keyword.
#
#   uvicorn services.api.app:app --host 0.0.0.0 --port 8000

import os
import queue
import tempfile
import threading
import uuid
from datetime import datetime, timedelta

import services  # noqa: F401  (puts the research code on the path)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from modules.storage import EventStore
from query.llm_qa import answer, fmt_row, time_range
from services.api.alerts import alerts as find_alerts
from services.api.clients import RemoteDescriber, RemoteTrigger
from services.api.pipeline import process_clip

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "apps", "web")
DB = os.environ.get("ENGRAM_DB", os.path.join(ROOT, "database", "engram.db"))

app = FastAPI(title="ENGRAM backend")


@app.middleware("http")
async def app_token(request, call_next):
    """With ENGRAM_APP_TOKEN set (always when the backend is reachable from the internet), every /api/ request
    needs it: header X-Engram-Token or ?token=. The page itself holds no data."""
    from fastapi.responses import JSONResponse
    want = os.environ.get("ENGRAM_APP_TOKEN", "")
    if want and request.url.path.startswith("/api/"):
        got = request.headers.get("X-Engram-Token") or request.query_params.get("token", "")
        import hmac
        if not hmac.compare_digest(got, want):
            return JSONResponse({"detail": "wrong or missing app token"}, status_code=401)
    return await call_next(request)
_parts: dict = {}
_lock = threading.Lock()                         # SQLite connection: one thread at a time
jobs: dict[str, dict] = {}
_queue: "queue.Queue[tuple[str, str, datetime | None]]" = queue.Queue()


def store() -> EventStore:
    if "store" not in _parts:
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        _parts["store"] = EventStore(DB)
        _parts["store"].conn.close()
        import sqlite3
        _parts["store"].conn = sqlite3.connect(DB, check_same_thread=False)   # used by the API and the worker
        _parts["store"].conn.row_factory = sqlite3.Row
    return _parts["store"]


def describer():
    if "describer" not in _parts:
        url = os.environ.get("ENGRAM_VLM_URL")
        if not url:
            raise HTTPException(503, "No big model service: set ENGRAM_VLM_URL (see .env.example)")
        _parts["describer"] = RemoteDescriber(url, os.environ.get("ENGRAM_VLM_TOKEN", ""))
    return _parts["describer"]


def trigger():
    if os.environ.get("ENGRAM_USE_TRIGGER", "1") != "1":
        return None
    if "trigger" not in _parts:
        _parts["trigger"] = RemoteTrigger(os.environ.get("ENGRAM_TRIGGER_URL", "http://127.0.0.1:8001"))
    return _parts["trigger"]


def search_models():
    """(text, clip) for hybrid search, loaded once; (None, None) with ENGRAM_SEARCH=keyword."""
    if os.environ.get("ENGRAM_SEARCH", "hybrid") != "hybrid":
        return None, None
    if "text" not in _parts:
        from modules.landmarks import ClipEmbedder
        from modules.text_embed import TextEmbedder
        _parts["text"], _parts["clip"] = TextEmbedder(), ClipEmbedder()
    return _parts["text"], _parts["clip"]


def _worker():
    while True:
        job_id, path, recorded_at = _queue.get()
        job = jobs[job_id]
        job["status"] = "running"
        try:
            _, clip = search_models()
            def progress(msg):
                job["step"] = msg
            with _lock:
                job["result"] = process_clip(path, store(), describer(), trigger(), clip, recorded_at, progress)
            job["status"], job["step"] = "done", "done"
        except Exception as e:                           # the job fails, the backend keeps running
            job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"
        finally:
            if os.path.exists(path):
                os.remove(path)


threading.Thread(target=_worker, daemon=True).start()


@app.post("/api/clips")
def upload(file: UploadFile = File(...), recorded_at: str | None = Form(None)):
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="engram_")
    with os.fdopen(fd, "wb") as out:
        while chunk := file.file.read(1 << 20):
            out.write(chunk)
    start = datetime.fromisoformat(recorded_at) if recorded_at else None
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "step": "waiting", "file": file.filename, "created": datetime.now().isoformat(timespec="seconds")}
    _queue.put((job_id, path, start))
    return {"job": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "no such job")
    return jobs[job_id]


def _row(r: dict) -> dict:
    return {"start": r["ts_start"].isoformat(timespec="seconds"), "end": r["ts_end"].isoformat(timespec="seconds"),
            "verb": r.get("verb"), "object": r.get("object"), "where": r.get("where"), "place": r.get("place"),
            "source": r.get("source"), "line": fmt_row(r)}


@app.get("/api/diary")
def diary(day: str | None = None):
    d = datetime.fromisoformat(day) if day else datetime.now()
    d0 = d.replace(hour=0, minute=0, second=0, microsecond=0)
    with _lock:
        rows = store().activities(d0, d0 + timedelta(days=1))
    return {"day": d0.date().isoformat(), "rows": [_row(r) for r in rows if r.get("verb")]}


class AskIn(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskIn):
    from search.engine import Searcher
    text, clip = search_models()
    now = datetime.now()
    with _lock:
        s = Searcher(store(), text=text, clip=clip) if text is not None else None
        r = answer(req.question, store(), llm=describer(), now=now, searcher=s)
        moment = None
        if s is not None:
            start, end, _ = time_range(req.question, now)
            m = s.moment(req.question, start, end, llm=describer())
            if m:
                moment = {"start": m["ts_start"].isoformat(timespec="seconds"), "end": m["ts_end"].isoformat(timespec="seconds"),
                          "what": "not described; the camera image matches" if m["row"].get("image_only") else fmt_row(m["row"]).split(" | ", 1)[1]}
    return {"answer": r["answer"], "moment": moment, "evidence": [_row(x) for x in r["lines"][:5]]}


@app.get("/api/alerts")
def alerts():
    with _lock:
        rows = store().activities(datetime.now() - timedelta(days=1), None)
    return {"alerts": find_alerts(rows)}


@app.delete("/api/diary")
def delete_diary():
    with _lock:
        store().clear_activities()
    return {"deleted": True}


_live: dict = {}


@app.post("/api/live/start")
def live_start():
    from services.api.stream import StreamSession
    _, clip = search_models()
    sid = uuid.uuid4().hex[:12]
    store()                                          # creates the diary file and its tables
    _live[sid] = StreamSession(sid, DB, describer(), trigger(), clip)
    return {"session": sid, "max_lag_s": _live[sid].max_lag_s}


def _session(sid: str):
    if sid not in _live:
        raise HTTPException(404, "no such live session")
    return _live[sid]


@app.post("/api/live/{sid}/piece")
def live_piece(sid: str, file: UploadFile = File(...), offset: float = Form(...)):
    s = _session(sid)
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or "")[1] or ".webm", prefix="engram_live_")
    with os.fdopen(fd, "wb") as out:
        while chunk := file.file.read(1 << 20):
            out.write(chunk)
    s.add_piece(path, offset)
    return {"queued": s.pieces.qsize()}


@app.post("/api/live/{sid}/stop")
def live_stop(sid: str):
    s = _session(sid)
    s.stop()
    return s.summary()


@app.get("/api/live/{sid}")
def live_status(sid: str):
    return _session(sid).summary()


@app.get("/api/health")
def health():
    out = {"backend": "ok", "database": DB}
    for name, get in (("big_model", describer), ("small_model", trigger)):
        try:
            part = get()
            out[name] = part.health() if part is not None else "off"
        except Exception as e:
            out[name] = f"unreachable: {type(e).__name__}"
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/static", StaticFiles(directory=WEB), name="static")
