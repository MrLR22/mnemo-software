# services/api/alerts.py
# "The fridge was last seen OPEN at 9:22": the last open/close/on/off of each object in the diary.

from datetime import datetime

from modules.vlm_logger import canon_state_object

_STATE = {"opens": "open", "closes": "closed", "turns on": "on", "turns off": "off"}


def object_states(rows: list[dict]) -> dict[str, tuple[str, datetime]]:
    """{object: (last state, time)} from diary rows in time order."""
    out = {}
    for r in sorted(rows, key=lambda r: r["ts_start"]):
        state = _STATE.get((r.get("verb") or "").strip())
        c = canon_state_object(r.get("object")) if state else None
        if c:
            name = c[0] + (" power" if c[1] == "both" and state in ("on", "off") else "")
            out[name] = (state, r["ts_end"])
    return out


def alerts(rows: list[dict]) -> list[dict]:
    return [{"object": o.removesuffix(" power"), "state": s, "since": t.isoformat(timespec="seconds")}
            for o, (s, t) in object_states(rows).items() if s in ("open", "on")]
