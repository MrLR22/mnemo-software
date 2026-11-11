# services/vlm/app.py
# The big model service: wraps the vision-language model (modules/vlm_logger.VLMDescriber, Qwen3-VL today) behind
# HTTP, so the backend never imports it and the model can run on another machine (a GPU).
#
#   POST /describe  {"frames": [base64 JPEG], "seconds": 4.0, "check": ["fridge"]}  → {"text", "model_seconds"}
#   POST /describe_batch {"items": [{"frames", "seconds", "check"}, ...]}             → {"texts", "model_seconds"}
#   POST /chat      {"prompt": "...", "max_new_tokens": 300}                          → {"text", "model_seconds"}
#   GET  /health                                                                     → {"model", "ready"}
# Every request needs the header X-Engram-Token = $ENGRAM_VLM_TOKEN (if set).
# Swap the model: set ENGRAM_VLM_MODEL to another Hugging Face id, or replace this service with any program that
# answers the same three endpoints.
#
#   ENGRAM_VLM_TOKEN=secret uvicorn services.vlm.app:app --port 8002
#   ENGRAM_VLM_FAKE=1 → scripted answers, no GPU (tests and trying the apps without Kaggle)
#   ENGRAM_VLM_PROMPT: the prompt version used when a request names none (default lines-v6: any place, any action
#   verb; lines-v3 = the kitchen-era prompt of the paper's experiments). A request may name its own ("prompt").
#   ENGRAM_VLM_REPLICAS: model copies, one per GPU (default: every GPU, e.g. 2 on Kaggle "GPU T4 x2"). A batch is
#   split between them, so two GPUs describe twice as many windows in the same time.

import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor

import services  # noqa: F401  (puts the research code on the path)

import config as C
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from services.common import decode_frames, require_token

app = FastAPI(title="ENGRAM big model service")
auth = require_token("ENGRAM_VLM_TOKEN")
_model = {"describer": None, "name": None, "pool": None, "replicas": []}


class FakeDescriber:
    """No GPU: always the same plausible answer (for tests and for trying the apps)."""

    def describe(self, frames, seconds, check=None, version=None):
        time.sleep(float(os.environ.get("ENGRAM_VLM_FAKE_DELAY", "0")))   # e.g. 6.6 = Qwen3-VL-4B on a T4
        return "PLACE: kitchen\nSTATE: fridge = closed\nDID: picks up | cup | counter"

    def describe_batch(self, items, version=None):
        return [self.describe(f, s, c) for f, s, c in items]

    def chat(self, prompt, max_new_tokens=300):
        return "1" if max_new_tokens <= 8 else "I didn't see that in my records."


def _load_replicas():
    if os.environ.get("ENGRAM_VLM_FAKE"):
        return [FakeDescriber()], "fake"
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from modules.vlm_logger import VLMDescriber
    name = os.environ.get("ENGRAM_VLM_MODEL", C.VLM_MODEL)
    gpus = torch.cuda.device_count()
    n = int(os.environ.get("ENGRAM_VLM_REPLICAS", gpus or 1))
    if gpus <= 1 or n <= 1:
        return [VLMDescriber(name)], name
    proc = AutoProcessor.from_pretrained(name)
    out = []
    for i in range(min(n, gpus)):                 # a whole copy on each GPU (not one model split across them)
        model = AutoModelForImageTextToText.from_pretrained(name, dtype=torch.float16, device_map={"": i})
        out.append(VLMDescriber(name, model=model, processor=proc))
    return out, name


def describer():
    """The first model copy (the notebook's warm-up call loads them all)."""
    if _model["describer"] is None:
        reps, name = _load_replicas()
        _model.update(describer=reps[0], name=name, replicas=reps, pool=queue.Queue())
        for r in reps:
            _model["pool"].put(r)
    return _model["describer"]


class _Borrow:
    """One free model copy for the length of a request."""

    def __enter__(self):
        describer()
        self.d = _model["pool"].get()
        return self.d

    def __exit__(self, *exc):
        _model["pool"].put(self.d)


def _prompt(version: str | None) -> str:
    return version or os.environ.get("ENGRAM_VLM_PROMPT", "lines-v6")


def _run_batch(d, items, version):
    if isinstance(d, FakeDescriber):
        return d.describe_batch(items, version)
    from services.vlm.batch import describe_batch
    return describe_batch(d, items, version)


class DescribeIn(BaseModel):
    frames: list[str]
    seconds: float
    check: list[str] | None = None
    prompt: str | None = None                     # prompt version; None = the service default


class BatchItem(BaseModel):
    frames: list[str]
    seconds: float
    check: list[str] | None = None


class BatchIn(BaseModel):
    items: list[BatchItem]
    prompt: str | None = None


class ChatIn(BaseModel):
    prompt: str
    max_new_tokens: int = 300


@app.on_event("startup")
def _load():
    describer()                                   # load the model once, before the first request


@app.get("/health")
def health():
    return {"model": _model["name"], "ready": _model["describer"] is not None, "prompt": _prompt(None),
            "replicas": len(_model["replicas"]), "batch": True}


@app.post("/describe", dependencies=[Depends(auth)])
def describe(req: DescribeIn):
    frames = decode_frames(req.frames)
    t0 = time.time()
    with _Borrow() as d:
        text = d.describe(frames, req.seconds, check=req.check, version=_prompt(req.prompt))
    return {"text": text, "model_seconds": round(time.time() - t0, 2)}


@app.post("/describe_batch", dependencies=[Depends(auth)])
def describe_batch(req: BatchIn):
    """Several windows at once, in order. With two GPUs, each copy takes half of the batch at the same time."""
    items = [(decode_frames(i.frames), i.seconds, i.check) for i in req.items]
    t0 = time.time()
    describer()
    k = len(_model["replicas"])
    parts = [list(range(len(items)))[j::k] for j in range(k)]
    parts = [p for p in parts if p]

    def work(idx):
        with _Borrow() as d:
            return idx, _run_batch(d, [items[i] for i in idx], _prompt(req.prompt))

    texts = [""] * len(items)
    with ThreadPoolExecutor(len(parts)) as ex:
        for idx, out in ex.map(work, parts):
            for i, t in zip(idx, out):
                texts[i] = t
    return {"texts": texts, "model_seconds": round(time.time() - t0, 2)}


@app.post("/chat", dependencies=[Depends(auth)])
def chat(req: ChatIn):
    t0 = time.time()
    with _Borrow() as d:
        text = d.chat(req.prompt, max_new_tokens=req.max_new_tokens)
    return {"text": text, "model_seconds": round(time.time() - t0, 2)}
