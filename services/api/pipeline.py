# services/api/pipeline.py
# One uploaded clip → diary rows:
#   1. normalise the video (any phone format → 640 px H.264, so OpenCV reads it the same everywhere)
#   2. small model service: which 4-s windows need the big model (optional: without it every window is described)
#   3. modules/vlm_logger.ActionLogger with the big model service: diary rows + object states, written to the store,
#      plus an image fingerprint of every window for search
#   4. the video files are deleted: only the diary is kept

import os
import shutil
import subprocess
from datetime import datetime, timedelta

import cv2

from modules.vlm_logger import ActionLogger


def normalise(src: str, dst: str) -> str:
    """Convert to 640 px wide H.264 without audio; falls back to the original if ffmpeg is missing or fails."""
    if not shutil.which("ffmpeg"):
        return src
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", "scale=640:-2,fps=30", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "23", "-an", dst], capture_output=True)
    return dst if r.returncode == 0 and os.path.getsize(dst) > 0 else src


def duration_s(path: str) -> float:
    cap = cv2.VideoCapture(path)
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return n / fps if fps else 0.0


def process_clip(path: str, store, describer, trigger=None, embedder=None, recorded_at: datetime | None = None,
                 progress=lambda msg: None) -> dict:
    """recorded_at: when the recording STARTED; default: it just ended now."""
    work = path + ".norm.mp4"
    try:
        progress("preparing the video")
        video = normalise(path, work)
        sec = duration_s(video)
        start = recorded_at or (datetime.now() - timedelta(seconds=sec))
        call = scores = None
        trig = None
        if trigger is not None:
            progress("small model: finding the moments with hand actions")
            scores, call, trig = trigger.score(video)
        n_win = max(1, round(sec / 4))
        progress(f"big model: describing {int(call.sum()) if call is not None else n_win} of {n_win} windows")
        logger = ActionLogger(describer, store, embedder=embedder)
        rows, stats = logger.run(video, start_time=start, verbose=False, call=call, scores=scores)
        return {"video_seconds": stats["video_seconds"], "windows": stats["windows"], "big_model_calls": stats["vlm_calls"],
                "big_model_seconds": stats["model_seconds"], "rows": stats["rows"], "trigger": trig,
                "start": start.isoformat(timespec="seconds")}
    finally:
        for p in (path, work):                     # privacy: no video is kept
            if os.path.exists(p):
                os.remove(p)
