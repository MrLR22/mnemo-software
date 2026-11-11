# services/vlm/batch.py
# Several 4-second windows described in ONE generate() call. Writing the answer word by word is limited by memory
# speed, not by computation, so a batch of 4 windows costs little more GPU time than one window. Same prompt, same
# frames and same greedy decoding as VLMDescriber.describe; only the batching is new.

import cv2
import numpy as np

import config as C
from modules.vlm_logger import build_prompt, loop_or_full


def _video(frames_bgr: list[np.ndarray], seconds: float) -> tuple[np.ndarray, dict]:
    if len(frames_bgr) % 2:
        frames_bgr = frames_bgr + [frames_bgr[-1]]               # the model pairs frames in time
    h, w = frames_bgr[0].shape[:2]
    size = (C.VLM_FRAME_W, round(h * C.VLM_FRAME_W / w))
    video = np.stack([cv2.cvtColor(cv2.resize(f, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                      for f in frames_bgr])
    meta = {"total_num_frames": len(frames_bgr), "fps": len(frames_bgr) / max(seconds, 1e-3),
            "frames_indices": list(range(len(frames_bgr)))}
    return video, meta


def describe_batch(d, items: list[tuple[list[np.ndarray], float, list[str] | None]]) -> list[str]:
    """d: a modules.vlm_logger.VLMDescriber. items: (frames_bgr, seconds, check) per window → one text per window."""
    from transformers import StoppingCriteria, StoppingCriteriaList
    from transformers.video_utils import VideoMetadata
    torch, proc = d.torch, d.processor
    texts, videos, metas = [], [], []
    for frames, seconds, check in items:
        video, meta = _video(frames, seconds)
        prompt = build_prompt(meta["total_num_frames"], seconds, d.track_states, check)
        msgs = [{"role": "user", "content": [{"type": "video"}, {"type": "text", "text": prompt}]}]
        texts.append(proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
        videos.append(video)
        metas.append(VideoMetadata(**meta))
    proc.tokenizer.padding_side = "left"                        # generation continues from the right end
    inputs = proc(text=texts, videos=videos, video_metadata=metas, do_sample_frames=False, padding=True,
                  return_tensors="pt").to(d.device)
    n0 = inputs["input_ids"].shape[1]

    class _Loop(StoppingCriteria):                              # per window: stop a repetition loop early
        def __call__(self, input_ids, scores, **kw):
            done = [loop_or_full(proc.decode(row[n0:], skip_special_tokens=True)) for row in input_ids]
            return torch.tensor(done, dtype=torch.bool, device=input_ids.device)

    stop = StoppingCriteriaList([_Loop()]) if C.VLM_FORMAT == "lines" else None
    with torch.no_grad():
        out = d.model.generate(**inputs, max_new_tokens=C.VLM_MAX_NEW_TOKENS, do_sample=False,
                               pad_token_id=proc.tokenizer.pad_token_id or proc.tokenizer.eos_token_id,
                               **({"stopping_criteria": stop} if stop else {}))
    return [proc.decode(row[n0:], skip_special_tokens=True) for row in out]
