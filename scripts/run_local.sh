#!/usr/bin/env bash
# Start the laptop parts: small model service (:8001) and backend + web app (:8000).
# The big model service runs elsewhere (Kaggle: services/vlm/kaggle_vlm_service.ipynb) and is set in .env.
#   ./scripts/run_local.sh            then open http://localhost:8000 (phone: http://<laptop IP>:8000, same Wi-Fi)
#   FAKE=1 ./scripts/run_local.sh     also starts a fake big model on :8002 (try the apps without Kaggle)
#   TUNNEL=1 ./scripts/run_local.sh   also prints a secure https link for the PHONE (needed for live camera
#                                     recording in a phone browser), protected by a random app token
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
PY="${PYTHON:-../mnemo/.mnemovenv/bin/python}"
pids=()
trap 'kill "${pids[@]}" 2>/dev/null' EXIT
if [ "${FAKE:-0}" = "1" ]; then
  ENGRAM_VLM_FAKE=1 ENGRAM_VLM_TOKEN="" "$PY" -m uvicorn services.vlm.app:app --port 8002 --log-level warning & pids+=($!)
  export ENGRAM_VLM_URL=http://127.0.0.1:8002 ENGRAM_VLM_TOKEN=""
fi
# live mode on a laptop CPU: 320-px object detection (1.8 s per 4-s piece instead of 3.3 s, measured)
ENGRAM_YOLO_IMGSZ="${ENGRAM_YOLO_IMGSZ:-320}" "$PY" -m uvicorn services.trigger.app:app --port 8001 --log-level warning & pids+=($!)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ "${TUNNEL:-0}" = "1" ]; then
  export ENGRAM_APP_TOKEN="${ENGRAM_APP_TOKEN:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')}"
  mkdir -p bin
  [ -x bin/cloudflared ] || { curl -sL -o bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x bin/cloudflared; }
  bin/cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate > bin/tunnel.log 2>&1 & pids+=($!)
  ( for _ in $(seq 1 30); do sleep 1; URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' bin/tunnel.log | head -1); [ -n "$URL" ] && break; done
    echo; echo "ENGRAM phone link (keep it private: it opens your diary):"; echo "  ${URL:-tunnel failed, see bin/tunnel.log}/?token=${ENGRAM_APP_TOKEN}"; echo ) &
fi
echo "ENGRAM: laptop http://localhost:8000 | phone (same Wi-Fi, upload only) http://${IP:-<laptop-ip>}:8000 | big model: ${ENGRAM_VLM_URL:-NOT SET}"
"$PY" -m uvicorn services.api.app:app --host 0.0.0.0 --port 8000 --log-level warning
