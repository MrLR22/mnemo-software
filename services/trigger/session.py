# services/trigger/session.py
# Live trigger: the video arrives in short pieces (a few seconds each) and the small model must give the same
# scores as on one continuous video. The model is causal (it only looks back ~6 s = its receptive field), so each
# new piece is scored together with the last receptive-field frames of the previous ones, and the hand / camera
# motion state (FeatureExtractor, ego motion) carries on between pieces.

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np

import config as C
from modules.features import FeatureExtractor
from modules.types import FrameObs


class TriggerSession:
    def __init__(self, gate, window_s: float = C.VLM_WINDOW_S):
        from model.train import predict_activity
        self.gate, self.window_s, self.predict = gate, window_s, predict_activity
        self.perception = gate.perception
        self.perception.reset()
        self.fx = FeatureExtractor()
        self.rf = gate.model.receptive_field
        self.feats: list[np.ndarray] = []
        self.times: list[float] = []
        self.probs: list[float] = []
        self.emitted = 0                                    # windows already returned
        self.pool = ThreadPoolExecutor(2)                   # hands and objects at the same time (2 CPU cores)

    def _observe(self, frame) -> FrameObs:
        p = self.perception
        hands_f = self.pool.submit(p.hands.detect, frame.image)
        objects_f = self.pool.submit(p.objects.detect, frame.image)
        hands = hands_f.result()
        return FrameObs(t=frame.t, hands=hands, detections=objects_f.result(),
                        ego=p.ego.update(frame.image, [h.box for h in hands]))

    def add_piece(self, path: str, offset_s: float) -> list[dict]:
        """offset_s: when this piece starts, in seconds since the session started. Returns the windows that are
        now complete: [{"k", "score"}], window k = [k * window_s, (k + 1) * window_s)."""
        from modules.video_source import get_frames
        new_f, new_t = [], []
        try:
            for frame in get_frames(path):
                t = offset_s + frame.t
                if self.times and t <= self.times[-1]:     # pieces may overlap by a frame
                    continue
                new_f.append(self.fx(self._observe(replace(frame, t=t))))
                new_t.append(t)
        except ValueError:                                  # an empty or broken piece: skip it, keep the session
            return []
        if new_f:
            hist = self.feats[-(self.rf - 1):]
            p = self.predict(self.gate.model, np.stack(hist + new_f).astype(np.float32))
            self.probs += [float(x) for x in p[len(hist):]]
            self.feats += new_f
            self.times += new_t
            self.feats = self.feats[-self.rf:]             # only the receptive field is needed later
        return self._windows(final=False)

    def finish(self) -> list[dict]:
        return self._windows(final=True)

    def _windows(self, final: bool) -> list[dict]:
        if not self.times:
            return []
        last = self.times[-1]
        # a window is complete once a frame of the NEXT window was seen (or the session ended)
        upto = int(last // self.window_s) + (1 if final else 0)
        t, p = np.array(self.times), np.array(self.probs)
        out = []
        for k in range(self.emitted, upto):
            m = (t >= k * self.window_s) & (t < (k + 1) * self.window_s)
            out.append({"k": k, "score": round(float(p[m].max()), 4) if m.any() else 0.0})
        self.emitted = max(self.emitted, upto)
        keep = t >= (self.emitted * self.window_s)          # scores of finished windows are no longer needed
        self.times, self.probs = list(t[keep]), list(p[keep])
        return out
