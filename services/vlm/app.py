# services/vlm/app.py
# The big model service: wraps the vision-language model (modules/vlm_logger.VLMDescriber, Qwen3-VL today) behind
# HTTP, so the backend never imports it and the model can run on another machine (a GPU).
#
#   POST /describe  {"frames": [base64 JPEG], "seconds": 4.0, "check": ["fridge"]}  → {"text", "model_seconds"}
#   POST /chat      {"prompt": "...", "max_new_tokens": 300}                          → {"text", "model_seconds"}
#   GET  /health                                                                     → {"model", "ready"}
# Every request needs the header X-Engram-Token = $ENGRAM_VLM_TOKEN (if set).
# Swap the model: set ENGRAM_VLM_MODEL to another Hugging Face id, or replace this service with any program that
# answers the same three endpoints.
#
#   ENGRAM_VLM_TOKEN=secret uvicorn services.vlm.app:app --port 8002
#   ENGRAM_VLM_FAKE=1 → scripted answers, no GPU (tests and trying the apps without Kaggle)

import os
import time

import services  # noqa: F401  (puts the research code on the path)

import config as C
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from services.common import decode_frames, require_token

app = FastAPI(title="ENGRAM big model service")
auth = require_token("ENGRAM_VLM_TOKEN")
_model = {"describer": None, "name": None}


class FakeDescriber:
    """No GPU: always the same plausible answer (for tests and for trying the apps)."""

    def describe(self, frames, seconds, check=None):
        time.sleep(float(os.environ.get("ENGRAM_VLM_FAKE_DELAY", "0")))   # e.g. 6.6 = Qwen3-VL-4B on a T4
        return "PLACE: kitchen\nSTATE: fridge = closed\nDID: picks up | cup | counter"

    def chat(self, prompt, max_new_tokens=300):
        return "1" if max_new_tokens <= 8 else "I didn't see that in my records."


def describer():
    if _model["describer"] is None:
        if os.environ.get("ENGRAM_VLM_FAKE"):
            _model["describer"], _model["name"] = FakeDescriber(), "fake"
        else:
            from modules.vlm_logger import VLMDescriber
            name = os.environ.get("ENGRAM_VLM_MODEL", C.VLM_MODEL)
            _model["describer"], _model["name"] = VLMDescriber(name), name
    return _model["describer"]


class DescribeIn(BaseModel):
    frames: list[str]
    seconds: float
    check: list[str] | None = None


class ChatIn(BaseModel):
    prompt: str
    max_new_tokens: int = 300


@app.on_event("startup")
def _load():
    describer()                                   # load the model once, before the first request


@app.get("/health")
def health():
    return {"model": _model["name"], "ready": _model["describer"] is not None, "prompt": C.VLM_PROMPT_VERSION}


@app.post("/describe", dependencies=[Depends(auth)])
def describe(req: DescribeIn):
    frames = decode_frames(req.frames)
    t0 = time.time()
    text = describer().describe(frames, req.seconds, check=req.check) if req.check else describer().describe(frames, req.seconds)
    return {"text": text, "model_seconds": round(time.time() - t0, 2)}


@app.post("/chat", dependencies=[Depends(auth)])
def chat(req: ChatIn):
    t0 = time.time()
    return {"text": describer().chat(req.prompt, max_new_tokens=req.max_new_tokens),
            "model_seconds": round(time.time() - t0, 2)}
