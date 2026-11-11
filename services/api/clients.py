# services/api/clients.py
# How the backend talks to the two model services. Each client has the same methods as the in-process objects it
# replaces, so the diary code (modules/vlm_logger.ActionLogger) and the answers (query/llm_qa.answer) work unchanged.

import os

import numpy as np
import requests

from services.common import TOKEN_HEADER, encode_frames


class RemoteDescriber:
    """The big model service (services/vlm). Same interface as modules.vlm_logger.VLMDescriber."""

    def __init__(self, url: str, token: str = "", timeout: float = 180.0):
        self.url, self.timeout = url.rstrip("/"), timeout
        self.headers = {TOKEN_HEADER: token} if token else {}
        self.prompt = os.environ.get("ENGRAM_VLM_PROMPT") or None    # None: the service's default prompt

    def _post(self, path: str, body: dict, timeout: float | None = None) -> str:
        r = requests.post(self.url + path, json=body, headers=self.headers, timeout=timeout or self.timeout)
        r.raise_for_status()
        return r.json()["text"]

    def describe(self, frames_bgr: list[np.ndarray], seconds: float, check: list[str] | None = None,
                 timeout: float | None = None) -> str:
        """timeout: give up after this many seconds (live mode: the time left before the lag limit)."""
        return self._post("/describe", {"frames": encode_frames(frames_bgr), "seconds": seconds, "check": check,
                                        "prompt": self.prompt}, timeout)

    batch: bool | None = None                    # None: not known yet whether the service has /describe_batch

    def describe_batch(self, items: list[tuple[list[np.ndarray], float, list[str] | None]],
                       timeout: float | None = None) -> list[str] | None:
        """Several windows in one call (one generation pass on the GPU). None if the service is an older version
        without the batch endpoint: the caller then describes the windows one by one."""
        if self.batch is False:
            return None
        body = {"items": [{"frames": encode_frames(f), "seconds": s, "check": c} for f, s, c in items], "prompt": self.prompt}
        r = requests.post(self.url + "/describe_batch", json=body, headers=self.headers, timeout=timeout or self.timeout)
        if r.status_code in (404, 405):
            self.batch = False
            return None
        r.raise_for_status()
        self.batch = True
        return r.json()["texts"]

    def chat(self, prompt: str, max_new_tokens: int = 300) -> str:
        return self._post("/chat", {"prompt": prompt, "max_new_tokens": max_new_tokens}, timeout=60)  # a person is waiting

    def health(self) -> dict:
        return requests.get(self.url + "/health", timeout=10).json()


class RemoteTrigger:
    """The small model service (services/trigger): per-window scores and call decisions for a video file."""

    def __init__(self, url: str, timeout: float = 600.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def score(self, video_path: str) -> tuple[np.ndarray, np.ndarray, dict]:
        with open(video_path, "rb") as f:
            r = requests.post(self.url + "/score", files={"file": (video_path.rsplit("/", 1)[-1], f, "video/mp4")},
                              timeout=self.timeout)
        r.raise_for_status()
        d = r.json()
        return np.array(d["scores"], float), np.array(d["call"], bool), d["stats"]

    def piece(self, sid: str, video_path: str, offset_s: float) -> list[dict]:
        """Live: one piece of video → the windows that are now complete, [{"k", "score"}]."""
        with open(video_path, "rb") as f:
            r = requests.post(f"{self.url}/session/{sid}/piece", files={"file": ("piece.mp4", f, "video/mp4")},
                              data={"offset": str(offset_s)}, timeout=60)
        r.raise_for_status()
        return r.json()["windows"]

    def finish(self, sid: str) -> list[dict]:
        r = requests.post(f"{self.url}/session/{sid}/finish", timeout=60)
        return r.json()["windows"] if r.ok else []

    def health(self) -> dict:
        return requests.get(self.url + "/health", timeout=10).json()
