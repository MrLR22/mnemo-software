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

## Backend API

| Method | Path | What |
|---|---|---|
| POST | `/api/clips` | upload a video (`file`, optional `recorded_at`) → job id |
| GET | `/api/jobs/{id}` | progress / result of a clip |
| GET | `/api/diary?day=YYYY-MM-DD` | the diary of a day |
| POST | `/api/ask` | `{"question"}` → answer, best moment, evidence |
| GET | `/api/alerts` | objects last seen open / on |
| DELETE | `/api/diary` | delete the whole diary |
| GET | `/api/health` | which parts are reachable |
