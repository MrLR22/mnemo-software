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

import collections
import contextlib
import os
import re
import queue
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta

import services  # noqa: F401  (puts the research code on the path)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
import requests
from fastapi.responses import FileResponse
from pydantic import BaseModel

from query.llm_qa import fmt_row, time_range
from services.api.answers import smart_answer
from services.api.alerts import alerts as find_alerts, object_states
from services.api.clients import RemoteDescriber, RemoteTrigger
from services.db import browse as db_browse, is_postgres, location, open_clips, open_questions, open_store, stats as db_stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.abspath(os.environ.get("ENGRAM_WEB_DIR", os.path.join(ROOT, "apps", "web", "dist")))  # built React app
DB = location()                                               # ENGRAM_DB_URL (PostgreSQL) or ENGRAM_DB (SQLite file)
STARTED = datetime.now()


@contextlib.contextmanager
def reading():
    """A short-lived connection for one request: a slow question never holds up the other screens."""
    if not is_postgres(DB):
        store()                                      # creates the diary file and its tables
    db = open_store(DB)
    try:
        yield db
    finally:
        db.close()


@contextlib.asynccontextmanager
async def lifespan(_app):
    try:                                             # processing lives in this process: nothing survives a restart
        open_clips(DB).mark_interrupted()
    except Exception as e:
        print(f"database not reachable at startup: {e}")
    threading.Thread(target=lambda: _try(search_models), daemon=True).start()   # so the first question is not slow
    yield


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


app = FastAPI(title="Mnemo backend", lifespan=lifespan)


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
_lock = threading.Lock()                         # the shared connection: one request at a time
_models_lock = threading.Lock()
jobs: dict[str, dict] = {}
_queue: "queue.Queue[tuple[str, str, datetime | None]]" = queue.Queue()


def store():
    """The backend's shared diary connection (PostgreSQL, or the SQLite file as a fallback)."""
    if "store" not in _parts:
        if is_postgres(DB):
            _parts["store"] = open_store(DB)
        else:
            import sqlite3
            from modules.storage import EventStore
            os.makedirs(os.path.dirname(DB), exist_ok=True)
            _parts["store"] = EventStore(DB)
            _parts["store"].conn.close()
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
    with _models_lock:                               # loaded in the background at startup; a question waits for it
        if "text" not in _parts:
            from modules.landmarks import ClipEmbedder
            from modules.text_embed import TextEmbedder
            _parts["text"], _parts["clip"] = TextEmbedder(), ClipEmbedder()
    return _parts["text"], _parts["clip"]


def _why(e: Exception) -> str:
    """The reason a job failed, in words the app can show."""
    if isinstance(e, HTTPException):
        return str(e.detail)
    if isinstance(e, requests.RequestException):
        return "A model service stopped responding. Check the System screen, then upload the video again."
    return f"{type(e).__name__}: {e}"


def _worker():
    while True:
        job_id, path, recorded_at = _queue.get()
        job = jobs[job_id]
        job["status"] = "running"
        try:
            from services.api.progressive import process_progressive
            _, clip = search_models()
            store()                                      # creates the diary file and its tables

            def progress(info):
                job["progress"] = info
                job["step"] = (f"processed {info['processed_s']:.0f} of {info['seconds']:.0f} s "
                               f"(big model on {info['described']} of {info['windows']} windows so far)")
            job["result"] = process_progressive(path, job_id, job.get("file") or "video", DB, describer(), trigger(),
                                                clip, recorded_at, progress)
            job["status"], job["step"] = "done", "done"
        except Exception as e:                           # the job fails, the backend keeps running
            job["status"], job["error"] = "failed", _why(e)
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


_NOT_A_PLACE = re.compile(r"(puts?|places?|picks?|takes?)\b", re.I)


def ended_up(where: str | None) -> str | None:
    """The model sometimes writes "counter -> puts down" or "counter -> shelf": keep where the object ended up."""
    places = [p.strip() for p in (where or "").split("->") if p.strip() and not _NOT_A_PLACE.match(p.strip())]
    return places[-1] if places else None


def _row(r: dict) -> dict:
    return {"start": r["ts_start"].isoformat(timespec="seconds"), "end": r["ts_end"].isoformat(timespec="seconds"),
            "verb": r.get("verb"), "object": r.get("object"), "where": ended_up(r.get("where")), "place": r.get("place"),
            "source": r.get("source"), "line": fmt_row(r)}


def _states(r: dict) -> list[dict]:
    """The object state this diary line sets (open / closed / on / off), if any."""
    return [{"object": o.removesuffix(" power"), "state": s} for o, (s, _) in object_states([r]).items()]


@app.get("/api/diary")
def diary(day: str | None = None):
    d = datetime.fromisoformat(day) if day else datetime.now()
    d0 = d.replace(hour=0, minute=0, second=0, microsecond=0)
    with reading() as db:
        rows = db.activities(d0, d0 + timedelta(days=1))
    out = []
    for r in rows:
        if r.get("verb"):
            d = _row(r)
            d["state"] = _states(r)
            out.append(d)
    return {"day": d0.date().isoformat(), "rows": out}


@app.get("/api/days")
def days():
    """The days that have diary lines, newest first."""
    with reading() as db:
        n = collections.Counter(r["ts_start"].date().isoformat() for r in db.activities() if r.get("verb"))
    return {"days": [{"day": d, "lines": n[d]} for d in sorted(n, reverse=True)]}


class AskIn(BaseModel):
    question: str
    at: str | None = None            # answer as of this time (replay: the moment the video is at)
    clip_id: str | None = None       # asked while viewing this recording (kept with the question)


@app.post("/api/ask")
def ask(req: AskIn):
    from search.engine import Searcher
    t0 = time.perf_counter()
    text, clip = search_models()
    now = datetime.fromisoformat(req.at) if req.at else datetime.now()
    llm = _try(describer) if _big_model_up() else None      # counts and open/closed answers never need it
    degraded = llm is None
    with reading() as db:
        s = Searcher(db, text=text, clip=clip) if text is not None else None
        try:
            r = smart_answer(req.question, db, llm=llm, now=now, searcher=s)
        except requests.RequestException:            # the tunnel dropped: still answer from the diary
            llm, degraded = None, True
            r = smart_answer(req.question, db, llm=None, now=now, searcher=s)
        moment = None
        if s is not None:
            start, end, _ = time_range(req.question, now)
            m = _try(lambda: s.moment(req.question, start, end, llm=llm))
            if m:
                moment = {"start": m["ts_start"].isoformat(timespec="seconds"), "end": m["ts_end"].isoformat(timespec="seconds"),
                          "what": "not described; the camera image matches" if m["row"].get("image_only")
                          else " ".join(x for x in (m["row"].get("verb"), m["row"].get("object")) if x)}
    evidence = [_row(x) for x in r["lines"][:5]]
    ms = int((time.perf_counter() - t0) * 1000)
    try:
        qid = open_questions(DB).add(req.question, r["answer"], r.get("mode", "search"), req.clip_id,
                                     datetime.fromisoformat(req.at) if req.at else None,
                                     datetime.fromisoformat(moment["start"]) if moment else None, evidence, ms)
    except Exception:                                # the answer matters more than its log entry
        qid = None
    return {"id": qid, "answer": r["answer"], "kind": r.get("mode", "search"), "moment": moment,
            "evidence": evidence, "latency_ms": ms, "degraded": degraded and r.get("mode") not in ("count", "state")}


@app.get("/api/questions")
def questions(limit: int = 20, clip_id: str | None = None):
    store()
    return {"questions": open_questions(DB).recent(min(limit, 200), clip_id)}


@app.get("/api/clips")
def clips():
    store()
    return {"clips": open_clips(DB).all()}


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: str):
    c = open_clips(DB)
    if not hasattr(c, "delete") or not c.delete(clip_id):
        raise HTTPException(404, "no such clip")
    return {"deleted": clip_id}


@app.get("/api/clips/{clip_id}/diary")
def clip_diary(clip_id: str):
    """The diary of one processed video, each line with offset_s = seconds into the video, and the object state
    after each open / close / on / off (for alerts during the replay)."""
    c = open_clips(DB).get(clip_id) if store() else None
    if c is None:
        raise HTTPException(404, "no such clip")
    start = datetime.fromisoformat(c["start"])
    own = open_store(DB)                             # own connection: never waits for the worker
    try:
        rows = own.activities(start, start + timedelta(seconds=c["seconds"] + 5))
    finally:
        own.close()
    out = []
    for r in rows:
        if not r.get("verb"):
            continue
        d = _row(r)
        d["offset_s"] = round((r["ts_start"] - start).total_seconds(), 1)
        d["state"] = _states(r)
        out.append(d)
    return {"clip": c, "rows": out}


@app.get("/api/alerts")
def alerts():
    with reading() as db:
        rows = db.activities()
    if rows:                                         # the 24 hours up to the last thing recorded
        rows = [r for r in rows if r["ts_end"] >= rows[-1]["ts_end"] - timedelta(days=1)]
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


def _database_health() -> str:
    try:
        return db_stats(DB)["engine"]
    except Exception as e:
        return f"unreachable: {type(e).__name__}"


_health: dict = {"t": 0.0, "value": None}


@app.get("/api/health")
def health():
    """Which parts are reachable (asked at most every 10 s: the checks go over the network)."""
    if _health["value"] is None or time.monotonic() - _health["t"] > 10:
        out = {"backend": "ok", "database": _database_health()}
        for name, get in (("big_model", describer), ("small_model", trigger)):
            try:
                part = get()
                out[name] = part.health() if part is not None else "off"
            except Exception as e:
                out[name] = f"unreachable: {type(e).__name__}"
        _health.update(t=time.monotonic(), value=out)
    return _health["value"]


def _big_model_up() -> bool:
    h = _try(health)
    return bool(h) and isinstance(h.get("big_model"), dict)


@app.get("/api/overview")
def overview():
    """Numbers for the home screen: recordings, diary lines, objects, questions, last activity."""
    with reading() as db:
        rows = [r for r in db.activities() if r.get("verb")]
    clip_list = open_clips(DB).all()
    verbs = collections.Counter((r["verb"] or "").strip() for r in rows)
    objs = collections.Counter((r.get("object") or "").strip().lower() for r in rows if r.get("object"))
    return {
        "recordings": len(clip_list),
        "recorded_seconds": round(sum(c["seconds"] for c in clip_list), 1),
        "processing": sum(1 for c in clip_list if c.get("status") == "processing"),
        "diary_lines": len(rows),
        "objects": len(objs),
        "questions": len(open_questions(DB).recent(10 ** 6)),
        "last_activity": rows[-1]["ts_end"].isoformat(timespec="seconds") if rows else None,
        "top_objects": [{"object": o, "count": n} for o, n in objs.most_common(8)],
        "top_actions": [{"verb": v, "count": n} for v, n in verbs.most_common(8)],
    }


@app.get("/api/objects")
def objects():
    """Every object in the diary: how often it was handled, the last thing done with it, where it ended up,
    and its open/closed/on/off state if it has one ("where did I leave my keys?" at a glance)."""
    with reading() as db:
        rows = [r for r in db.activities() if r.get("verb") and r.get("object")]
    states = object_states(rows)
    by: dict[str, dict] = {}
    for r in rows:
        name = r["object"].strip().lower()
        o = by.setdefault(name, {"object": name, "count": 0, "first": r["ts_start"], "where": None})
        o["count"] += 1
        o["last"], o["last_action"] = r["ts_end"], r["verb"]
        o["where"] = ended_up(r.get("where")) or o["where"]
    out = []
    for o in by.values():
        st = states.get(o["object"]) or states.get(o["object"] + " power")
        out.append({**o, "first": o["first"].isoformat(timespec="seconds"), "last": o["last"].isoformat(timespec="seconds"),
                    "state": st[0] if st else None})
    return {"objects": sorted(out, key=lambda o: o["last"], reverse=True)}


@app.get("/api/system")
def system():
    """The parts of the system and how each one is doing: the System screen of the app."""
    h = health()
    try:
        db = db_stats(DB)
    except Exception as e:
        db = {"engine": "unreachable", "error": f"{type(e).__name__}: {e}", "tables": []}
    return {
        "backend": {"status": "ok", "started": STARTED.isoformat(timespec="seconds"),
                    "uptime_s": int((datetime.now() - STARTED).total_seconds()),
                    "jobs": {s: sum(1 for j in jobs.values() if j["status"] == s) for s in ("queued", "running", "done", "failed")},
                    "search": os.environ.get("ENGRAM_SEARCH", "hybrid")},
        "database": db,
        "small_model": {"status": h["small_model"], "url": os.environ.get("ENGRAM_TRIGGER_URL", "http://127.0.0.1:8001"),
                        "name": "HOI-TCN interaction trigger (ours)"},
        "big_model": {"status": h["big_model"], "name": "Qwen3-VL-4B describer (remote GPU)"},
    }


@app.get("/api/system/tables/{table}")
def browse_table(table: str, limit: int = 100):
    """Read-only view of one database table for the System screen; vectors are shown by size, not content."""
    try:
        return db_browse(DB, table, min(limit, 500))
    except KeyError:
        raise HTTPException(404, "no such table")


@app.get("/{path:path}")
def web_app(path: str):
    """The React app: real files from apps/web/dist, every other path is a screen of the app (index.html)."""
    if path.startswith("api/"):
        raise HTTPException(404, "no such endpoint")
    f = os.path.normpath(os.path.join(WEB, path))
    if path and f.startswith(WEB) and os.path.isfile(f):
        return FileResponse(f)
    index = os.path.join(WEB, "index.html")
    if not os.path.exists(index):
        raise HTTPException(503, "The web app is not built yet: cd apps/web && npm install && npm run build")
    return FileResponse(index)
