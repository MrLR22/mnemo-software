# services/common.py
# What the services share: frames as JPEG text (base64) over HTTP, and the shared-secret check.

import base64
import hmac
import os

import cv2
import numpy as np
from fastapi import Header, HTTPException

TOKEN_HEADER = "X-Engram-Token"


def encode_frames(frames_bgr: list[np.ndarray], width: int = 448, quality: int = 85) -> list[str]:
    """BGR frames → base64 JPEG strings, downscaled to `width` (the big model sees 448 px anyway)."""
    out = []
    for f in frames_bgr:
        h, w = f.shape[:2]
        if w > width:
            f = cv2.resize(f, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise ValueError("could not encode a frame")
        out.append(base64.b64encode(buf.tobytes()).decode("ascii"))
    return out


def decode_frames(frames_b64: list[str]) -> list[np.ndarray]:
    out = []
    for s in frames_b64:
        img = cv2.imdecode(np.frombuffer(base64.b64decode(s), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "a frame is not a valid JPEG")
        out.append(img)
    return out


def require_token(env_var: str):
    """FastAPI dependency: the request must carry the token in env_var (no token set = open, for local use)."""
    def check(x_engram_token: str | None = Header(default=None)):
        want = os.environ.get(env_var, "")
        if want and not hmac.compare_digest(x_engram_token or "", want):
            raise HTTPException(401, "wrong or missing token")
    return check
