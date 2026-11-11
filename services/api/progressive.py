# services/api/progressive.py
# A recorded video of any length is processed piece by piece (PIECE_S seconds each) through the same chain as live
# mode (services/api/stream.py: small model with its state carried over, big model in time order), but with no lag
# limit: every window the small model flags is described. The diary grows while it runs, so questions about the
# part already processed can be asked at once; ClipIndex keeps "processed up to" for the apps.
# A 1-hour video takes about as long as its windows take in the big model (~10 s each for the flagged ones).

import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta

from services.db import open_clips
from services.api.stream import StreamSession

PIECE_S = 20.0


def video_seconds(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        from services.api.pipeline import duration_s
        return duration_s(path)


def process_progressive(path: str, clip_id: str, name: str, db: str, describer, trigger=None, embedder=None,
                        recorded_at: datetime | None = None, progress=lambda info: None) -> dict:
    clips = open_clips(db)
    work = tempfile.mkdtemp(prefix="engram_pieces_")
    try:
        sec = video_seconds(path)
        if sec <= 0:
            raise ValueError("could not read the video length")
        start = recorded_at or (datetime.now() - timedelta(seconds=sec))
        clips.start(clip_id, name, start.isoformat(timespec="seconds"), sec)
        s = StreamSession(clip_id, db, describer, trigger, embedder, max_lag_s=10 ** 9, started_at=start)

        def report(state="processing"):
            st = s.stats
            clips.progress(clip_id, min(s.processed_s, sec), st["windows"], st["described"], state)
            progress({"processed_s": round(min(s.processed_s, sec), 1), "seconds": round(sec, 1),
                      "described": st["described"], "windows": st["windows"]})

        offset = 0.0
        while offset < sec - 0.25:
            while s.pieces.qsize() > 2:                   # cut pieces only a little ahead of processing
                report()
                time.sleep(1.0)
            piece = os.path.join(work, f"{int(offset):07d}.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{offset:.2f}", "-t", f"{PIECE_S:.2f}", "-i", path,
                            "-vf", "scale=640:-2,fps=30", "-an", "-c:v", "libx264", "-preset", "veryfast", piece], check=True)
            s.add_piece(piece, offset)                    # the session deletes the piece after use
            offset += PIECE_S
            report()
        s.stop()
        while not s.done.wait(2.0):
            report()
        report("done")
        sm = s.summary()
        return {"video_seconds": round(sec, 1), "windows": sm["windows"], "big_model_calls": sm["described"],
                "rows": sum(1 for r in s.rows if r.get("verb")), "start": start.isoformat(timespec="seconds"),
                "errors": sm["errors"][:5]}
    except Exception:
        clips.progress(clip_id, 0, 0, 0, "failed")
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(path):                          # privacy: the uploaded video is deleted
            os.remove(path)
