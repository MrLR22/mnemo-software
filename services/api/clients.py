# services/api/clients.py
# How the backend talks to the two model services. Each client has the same methods as the in-process objects it
# replaces, so the diary code (modules/vlm_logger.ActionLogger) and the answers (query/llm_qa.answer) work unchanged.

import numpy as np
import requests

from services.common import TOKEN_HEADER, encode_frames


class RemoteDescriber:
    """The big model service (services/vlm). Same interface as modules.vlm_logger.VLMDescriber."""

    def __init__(self, url: str, token: str = "", timeout: float = 180.0):
        self.url, self.timeout = url.rstrip("/"), timeout
        self.headers = {TOKEN_HEADER: token} if token else {}

    def _post(self, path: str, body: dict) -> str:
        r = requests.post(self.url + path, json=body, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["text"]

    def describe(self, frames_bgr: list[np.ndarray], seconds: float, check: list[str] | None = None) -> str:
        return self._post("/describe", {"frames": encode_frames(frames_bgr), "seconds": seconds, "check": check})

    def chat(self, prompt: str, max_new_tokens: int = 300) -> str:
        return self._post("/chat", {"prompt": prompt, "max_new_tokens": max_new_tokens})

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

    def health(self) -> dict:
        return requests.get(self.url + "/health", timeout=10).json()
