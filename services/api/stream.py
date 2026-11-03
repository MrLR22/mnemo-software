# services/api/stream.py
# Live mode: the camera sends a short piece of video every few seconds while recording, and the diary is written
# while the person is still recording. The lag (end of a 4-s window → its diary line exists) is kept under
# ENGRAM_MAX_LAG_S (default 45 s, never above 60 s):
#
#   thread A (pieces, in arrival order): piece → small model service (keeps its state across pieces) → window
#            scores; the frames for the big model are cut out of the piece (8 per 4-s window)
#   thread B (windows, in time order): call the big model if the trigger fired (or the 20-s heartbeat is due);
#            LAG GUARD: if the window could not be finished within the limit (now + the big model's recent time
#            per window > window end + limit), the big model skips it. Every window still gets its image
#            fingerprint, so a skipped window can still be found by image search.
#   TRIGGER GUARD: if pieces pile up in thread A (more than 2 waiting = over 8 s behind), the small model skips
#            the oldest piece (its windows get score 0: only the heartbeat can describe them).
# So the lag cannot pile up: when a model is too slow, fewer windows are scored / described instead of falling behind.

import collections
import os
import queue
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np

import config as C
from modules.storage import EventStore
from modules.types import Frame
from modules.vlm_logger import ActionLogger
from services.api.pipeline import normalise

MAX_LAG_S = min(60.0, float(os.environ.get("ENGRAM_MAX_LAG_S", "45")))
W = C.VLM_WINDOW_S
FPS = C.VLM_FRAMES / C.VLM_WINDOW_S                      # frames per second the big model needs (2)


class StreamSession:
    def __init__(self, sid: str, db: str, describer, trigger=None, embedder=None, threshold: float = C.GATE_THRESHOLD,
                 max_lag_s: float = MAX_LAG_S, started_at: datetime | None = None):
        self.sid, self.db, self.describer, self.trigger, self.embedder = sid, db, describer, trigger, embedder
        self.threshold, self.max_lag_s = threshold, max_lag_s
        self.started = started_at or datetime.now()
        self.heartbeat = max(1, round(C.GATE_HEARTBEAT_S / W))
        self.pieces: "queue.Queue[tuple[str, float] | None]" = queue.Queue()
        self.windows: "queue.Queue[dict | None]" = queue.Queue()
        self.frames: dict[int, list[Frame]] = collections.defaultdict(list)
        self.last_t = 0.0
        self.vlm_s = 7.0                                  # recent big-model seconds per window (updated live)
        self.stats = {"pieces": 0, "windows": 0, "described": 0, "skipped_no_action": 0, "skipped_lag": 0,
                      "trigger_skipped_pieces": 0, "triggered": 0, "lag_s": [], "trigger_s": [], "big_model_s": [],
                      "errors": []}
        self.rows: list[dict] = []
        self.done = threading.Event()
        threading.Thread(target=self._pieces_worker, daemon=True).start()
        threading.Thread(target=self._windows_worker, daemon=True).start()

    # ── input ──
    def add_piece(self, path: str, offset_s: float):
        self.pieces.put((path, offset_s))

    def stop(self):
        self.pieces.put(None)

    # ── thread A ──
    def _pieces_worker(self):
        from modules.video_source import get_frames
        self.next_k = 0                                   # next window to hand to thread B
        while True:
            item = self.pieces.get()
            if item is None:
                break
            path, offset = item
            work = path + ".norm.mp4"
            try:
                video = normalise(path, work)
                behind = self.pieces.qsize() > 2          # trigger guard
                t0 = time.time()
                scored = self.trigger.piece(self.sid, video, offset) if self.trigger and not behind else None
                if self.trigger and behind:
                    self.stats["trigger_skipped_pieces"] += 1
                elif self.trigger:
                    self.stats["trigger_s"].append(round(time.time() - t0, 2))
                for f in get_frames(video, start_time=self.started + timedelta(seconds=offset), fps=FPS):
                    t = offset + f.t
                    self.frames[int(t // W)].append(replace(f, t=t))
                    self.last_t = max(self.last_t, t)
                self.stats["pieces"] += 1
                if scored is None:                        # no small model (or skipped): score 0 / 1 for the new windows
                    scored = [{"k": k, "score": 0.0 if self.trigger else 1.0} for k in range(self.next_k, int(self.last_t // W))]
                self._emit_all(scored)
            except Exception as e:                        # a broken piece must not stop the session
                self.stats["errors"].append(f"piece at {offset:.0f}s: {type(e).__name__}: {e}")
            finally:
                for p in (path, work):                    # privacy: no video is kept
                    if os.path.exists(p):
                        os.remove(p)
        rest = self.trigger.finish(self.sid) if self.trigger else []
        self._emit_all(rest + [{"k": k, "score": 0.0 if self.trigger else 1.0}
                               for k in range(self.next_k, int(self.last_t // W) + 1)])
        self.windows.put(None)

    def _emit_all(self, scored: list[dict]):
        """Hand windows to thread B in time order, each once (the trigger may report a window already handed on)."""
        for w in sorted(scored, key=lambda w: w["k"]):
            if w["k"] < self.next_k:
                continue
            for k in range(self.next_k, w["k"]):          # a window with no score at all: score 0
                self.windows.put({"k": k, "score": 0.0, "frames": self.frames.pop(k, [])})
            self.stats["triggered"] += w["score"] >= self.threshold
            self.windows.put({"k": w["k"], "score": w["score"], "frames": self.frames.pop(w["k"], [])})
            self.next_k = w["k"] + 1

    # ── thread B ──
    def _windows_worker(self):
        store = EventStore(self.db)                       # this thread's own connection
        logger = ActionLogger(self.describer, store, embedder=self.embedder)
        logger.windows = []
        since, call = self.heartbeat, []
        while True:
            w = self.windows.get()
            if w is None:
                break
            k, frames = w["k"], w["frames"]
            while len(logger.windows) < k:               # a gap (lost piece): keep the window numbering
                logger.windows.append({"k": len(logger.windows), "t": len(logger.windows) * W, "text": None,
                                       "called": False, "dt": 0.0})
                call.append(False)
            end = self.started + timedelta(seconds=(k + 1) * W)
            want = w["score"] >= self.threshold or since >= self.heartbeat
            # 25% margin on the big model's recent time, so a slower-than-usual answer still stays under the limit
            late = want and (datetime.now() + timedelta(seconds=1.25 * self.vlm_s) - end).total_seconds() > self.max_lag_s
            go = want and not late and len(frames) >= 2
            call.append(go)
            self.stats["windows"] += 1
            if len(frames) >= 2:
                try:
                    n_rows = len(self.rows)
                    logger._window(frames, self.rows, False, np.array(call), None)
                    rec = logger.windows[-1]
                    if go:
                        self.vlm_s = 0.7 * self.vlm_s + 0.3 * rec["dt"]
                        self.stats["big_model_s"].append(round(rec["dt"], 2))
                    for r in self.rows[n_rows:]:
                        r["ready_at"] = datetime.now()
                except Exception as e:
                    self.stats["errors"].append(f"window {k}: {type(e).__name__}: {e}")
                    go = False
            else:
                logger.windows.append({"k": k, "t": k * W, "text": None, "called": False, "dt": 0.0})
            if go:
                since = 1
                self.stats["described"] += 1
                self.stats["lag_s"].append(round((datetime.now() - end).total_seconds(), 1))
            else:
                since += 1
                self.stats["skipped_lag" if late else "skipped_no_action"] += 1
        self.done.set()

    def summary(self) -> dict:
        s = dict(self.stats)
        lags, trig = s.pop("lag_s"), s.pop("trigger_s")
        s.update({"session": self.sid, "started": self.started.isoformat(timespec="seconds"), "finished": self.done.is_set(),
                  "max_lag_limit_s": self.max_lag_s, "lag_last_s": lags[-1] if lags else None,
                  "lag_max_s": max(lags) if lags else None, "lag_mean_s": round(float(np.mean(lags)), 1) if lags else None,
                  "big_model_s_per_window": round(self.vlm_s, 1), "queue": self.windows.qsize(),
                  "trigger_s_mean": round(float(np.mean(trig)), 2) if trig else None,
                  "recent": [{"start": r["ts_start"].isoformat(timespec="seconds"), "verb": r["verb"], "object": r["object"]}
                             for r in self.rows[-8:] if r.get("verb")]})
        s.pop("big_model_s")
        return s
