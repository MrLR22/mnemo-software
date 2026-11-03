#!/usr/bin/env bash
# Start the laptop parts: small model service (:8001) and backend + web app (:8000).
# The big model service runs elsewhere (Kaggle: services/vlm/kaggle_vlm_service.ipynb) and is set in .env.
#   ./scripts/run_local.sh            then open http://localhost:8000 (phone: http://<laptop IP>:8000, same Wi-Fi)
#   FAKE=1 ./scripts/run_local.sh     also starts a fake big model on :8002 (try the apps without Kaggle)
#   HTTPS=1 ./scripts/run_local.sh    https on THIS Wi-Fi for the PHONE (a phone browser records live only on
#                                     https): self-made certificate, the phone warns once → "Advanced → Proceed"
#   TUNNEL=1 ./scripts/run_local.sh   a public https link instead (Cloudflare; blocked on some college networks)
# Both protect the diary with a random app token that is part of the printed link.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
PY="${PYTHON:-$(cd ../mnemo && pwd)/.mnemovenv/bin/python}"     # absolute path: no venv warnings
pids=()
trap 'kill "${pids[@]}" 2>/dev/null' EXIT
if [ "${FAKE:-0}" = "1" ]; then
  ENGRAM_VLM_FAKE=1 ENGRAM_VLM_TOKEN="" "$PY" -m uvicorn services.vlm.app:app --port 8002 --log-level warning & pids+=($!)
  export ENGRAM_VLM_URL=http://127.0.0.1:8002 ENGRAM_VLM_TOKEN=""
fi
# live mode on a laptop CPU: 320-px object detection (1.8 s per 4-s piece instead of 3.3 s, measured)
ENGRAM_YOLO_IMGSZ="${ENGRAM_YOLO_IMGSZ:-320}" "$PY" -m uvicorn services.trigger.app:app --port 8001 --log-level warning & pids+=($!)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
SSL=()
if [ "${HTTPS:-0}" = "1" ] || [ "${TUNNEL:-0}" = "1" ]; then
  export ENGRAM_APP_TOKEN="${ENGRAM_APP_TOKEN:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')}"
  mkdir -p bin
fi
if [ "${HTTPS:-0}" = "1" ]; then
  [ -f bin/engram.key ] || openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=engram-local" \
      -addext "subjectAltName=IP:${IP:-127.0.0.1},IP:127.0.0.1,DNS:localhost" -keyout bin/engram.key -out bin/engram.crt 2>/dev/null
  SSL=(--ssl-keyfile bin/engram.key --ssl-certfile bin/engram.crt)
  echo; echo "ENGRAM phone link (same Wi-Fi; keep it private: it opens your diary):"
  echo "  https://${IP:-<laptop-ip>}:8000/?token=${ENGRAM_APP_TOKEN}"
  echo "  The phone warns 'not private / not secure' once: tap Advanced → Proceed (it is your own laptop)."; echo
fi
if [ "${TUNNEL:-0}" = "1" ]; then
  [ -x bin/cloudflared ] || { echo "downloading cloudflared…"; curl -sL -o bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x bin/cloudflared; }
  bin/cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate > bin/tunnel.log 2>&1 & TPID=$!; pids+=($TPID)
  ( for _ in $(seq 1 45); do sleep 1; URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' bin/tunnel.log | head -1); [ -n "$URL" ] && break; done
    if [ -n "$URL" ] && ! grep -q "hard_fail=true" bin/tunnel.log; then
      echo; echo "ENGRAM phone link (keep it private: it opens your diary):"; echo "  $URL/?token=${ENGRAM_APP_TOKEN}"; echo
    else
      echo; echo "TUNNEL FAILED: this network blocks Cloudflare tunnels (port 7844). Use HTTPS=1 instead."; echo
      kill "$TPID" 2>/dev/null
    fi ) &
fi
SCHEME=http; [ "${HTTPS:-0}" = "1" ] && SCHEME=https
echo "ENGRAM: laptop ${SCHEME}://localhost:8000 | big model: ${ENGRAM_VLM_URL:-NOT SET}"
"$PY" -m uvicorn services.api.app:app --host 0.0.0.0 --port 8000 --log-level warning "${SSL[@]}"
