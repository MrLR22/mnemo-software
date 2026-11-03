# ENGRAM software

A chest camera that keeps a **reference diary** of what you did, and answers *"Did I close the fridge?"* with the
time, from the diary only. No video is kept. This folder is the software; the research (training, experiments,
evaluations) is in `../mnemo`.

## Parts

```
 ① phone (apps/mobile)   ② web app (apps/web)          frontends: send clips, show the diary, ask
          └──────────────┬──────────────┘
                         ▼  HTTP
              ③ backend (services/api)                 receives clips, runs the pipeline, answers
          ┌──────────────┼───────────────────┐
          ▼              ▼                   ▼
 ④ small model      ⑤ big model         ⑥ database (database/)
 services/trigger   services/vlm        diary + search vectors, SQLite
 OUR HOI-TCN, CPU   Qwen3-VL, GPU
```

| Part | Folder | Runs on | Swap it by |
|---|---|---|---|
| ① Mobile app | `apps/mobile` | phone browser (now) | a native app using the same API |
| ② Web app | `apps/web` | any browser | any frontend using the same API |
| ③ Backend | `services/api` | laptop / server | — |
| ④ Small model (ours) | `services/trigger`, `models/hoi_tcn.pt` | CPU | `ENGRAM_TRIGGER_MODEL=<checkpoint>` |
| ⑤ Big model | `services/vlm` | GPU (Kaggle while testing) | `ENGRAM_VLM_MODEL=<model id>` or another service with the same 3 endpoints |
| ⑥ Database | `database/` | next to the backend | `ENGRAM_DB=<file>` |

The parts only talk over HTTP. The model wrappers, diary and search code come from `../mnemo` (`MNEMO_PATH`).

## Run it (testing)

1. **Big model on Kaggle:** import `services/vlm/kaggle_vlm_service.ipynb`, GPU T4 + Internet on, **Run All**,
   keep the tab open. Its last cell prints `ENGRAM_VLM_URL=...` and `ENGRAM_VLM_TOKEN=...`.
2. **On the laptop:** `cp .env.example .env`, paste those two lines, then `./scripts/run_local.sh`.
3. Open **http://localhost:8000**, or on the phone (same Wi-Fi) the address the script prints.

Without Kaggle: `FAKE=1 ./scripts/run_local.sh` (a fake big model, to try the apps).

## Demo replay (recorded video)

Add a recorded first-person video in step 1: it is processed without any lag limit (every window the small model
flags is described), then deleted from the backend. Under **Demo replay**, pick it and choose the same file on the
device: while it plays, diary lines and alerts appear at the moment they happen in the video, and questions are
answered as of that moment (`/api/clips`, `/api/clips/{id}/diary`, `/api/ask` with `at`).

## Live mode (lag ≤ 45 s, never above 60 s; in development)

The web app's **Start live** button records a new 4-second piece every 4 seconds and sends each one at once; the
diary is written while you record (`services/api/stream.py`).

- **Small model** keeps its state across pieces (`services/trigger/session.py`); hands and objects run in parallel.
- **Lag guard:** a window the big model could not finish within `ENGRAM_MAX_LAG_S` (45 s) is skipped by the big
  model (its image fingerprint is still kept). **Trigger guard:** if pieces pile up, the small model skips one.
  So when a part is too slow, fewer windows are described instead of the lag growing.

Measured on the laptop (live simulation `scripts/simulate_live.py`, 169 s of real video, big model faked at
Qwen3-VL-4B's speed on a T4, 6.6 s per window):

| Case | Lag mean | Lag max | Windows skipped by the lag guard |
|---|---|---|---|
| normal (trigger on, 38% of windows described) | 14.6 s | 19.4 s | 0 of 42 |
| worst case (every window sent to the big model) | 36.5 s | 45.1 s | 13 of 42 |

Small model: 2.3 s per 4-s piece on the laptop CPU (320-px object detection, `ENGRAM_YOLO_IMGSZ`).

**Phone camera in live mode needs https:** `TUNNEL=1 ./scripts/run_local.sh` prints a private https link with an app
token (it opens your diary: keep it private). Without it, the phone can still upload recorded clips over Wi-Fi.

## Backend API

| Method | Path | What |
|---|---|---|
| POST | `/api/clips` | upload a video (`file`, optional `recorded_at`) → job id |
| GET | `/api/jobs/{id}` | progress / result of a clip |
| GET | `/api/diary?day=YYYY-MM-DD` | the diary of a day |
| POST | `/api/ask` | `{"question", "at"?}` → answer, best moment, evidence (as of `at` if given) |
| GET | `/api/alerts` | objects last seen open / on |
| DELETE | `/api/diary` | delete the whole diary |
| GET | `/api/health` | which parts are reachable |
| GET | `/api/clips` | processed recordings (name, start, length, windows described) |
| GET | `/api/clips/{id}/diary` | a recording's diary, each line with `offset_s` (seconds into the video) |
| POST | `/api/live/start` | start a live session → session id |
| POST | `/api/live/{sid}/piece` | one piece (`file`, `offset` = seconds since start) |
| POST | `/api/live/{sid}/stop` | end of the session |
| GET | `/api/live/{sid}` | lag (last / max / mean), described and skipped windows, recent diary lines |

With `ENGRAM_APP_TOKEN` set, every `/api/` call needs header `X-Engram-Token` (or `?token=`).
