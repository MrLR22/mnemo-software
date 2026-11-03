#!/usr/bin/env bash
# Start the laptop parts: small model service (:8001) and backend + web app (:8000).
# The big model service runs elsewhere (Kaggle: services/vlm/kaggle_vlm_service.ipynb) and is set in .env.
#   ./scripts/run_local.sh            then open http://localhost:8000 (phone: http://<laptop IP>:8000, same Wi-Fi)
#   FAKE=1 ./scripts/run_local.sh     also starts a fake big model on :8002 (try the apps without Kaggle)
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
"$PY" -m uvicorn services.trigger.app:app --port 8001 --log-level warning & pids+=($!)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "ENGRAM: laptop http://localhost:8000 | phone (same Wi-Fi) http://${IP:-<laptop-ip>}:8000 | big model: ${ENGRAM_VLM_URL:-NOT SET}"
"$PY" -m uvicorn services.api.app:app --host 0.0.0.0 --port 8000 --log-level warning
