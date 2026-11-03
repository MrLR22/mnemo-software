# scripts/simulate_live.py
# Pretend to be a phone recording live: cut a video into PIECE_S-second pieces and send each one to the backend
# when it would really be ready (real-time pace), then print the lag the backend measured.
#   python scripts/simulate_live.py video.mp4 [--url http://localhost:8000] [--piece-s 4] [--speed 1]

import argparse
import json
import os
import subprocess
import tempfile
import time

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--piece-s", type=float, default=4.0)
    ap.add_argument("--speed", type=float, default=1.0, help="2 = send twice as fast as real time")
    a = ap.parse_args()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video],
                               capture_output=True, text=True).stdout)
    tmp = tempfile.mkdtemp()
    n = int(dur // a.piece_s)
    sid = requests.post(a.url + "/api/live/start").json()["session"]
    print(f"session {sid}: {n} pieces of {a.piece_s:.0f}s ({dur:.0f}s of video)")
    t0 = time.time()
    for i in range(n):
        p = os.path.join(tmp, f"p{i:04d}.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(i * a.piece_s), "-t", str(a.piece_s), "-i", a.video,
                        "-an", "-c:v", "libx264", "-preset", "veryfast", p], check=True)
        ready = t0 + (i + 1) * a.piece_s / a.speed        # a real recorder has the piece only after it was filmed
        time.sleep(max(0.0, ready - time.time()))
        with open(p, "rb") as f:
            requests.post(f"{a.url}/api/live/{sid}/piece", files={"file": ("piece.mp4", f, "video/mp4")},
                          data={"offset": str(i * a.piece_s)})
        os.remove(p)
        if i % 5 == 4:
            s = requests.get(f"{a.url}/api/live/{sid}").json()
            print(f"  {time.time() - t0:5.0f}s sent {i + 1}/{n} | described {s['described']}, skipped (no action) "
                  f"{s['skipped_no_action']}, skipped (lag guard) {s['skipped_lag']} | lag last {s['lag_last_s']}s max {s['lag_max_s']}s",
                  flush=True)
    requests.post(f"{a.url}/api/live/{sid}/stop")
    while not (s := requests.get(f"{a.url}/api/live/{sid}").json())["finished"]:
        time.sleep(2)
    s.pop("recent")
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
