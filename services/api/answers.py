# services/api/answers.py
# Answering for the apps, on top of the research code's query/llm_qa.answer:
#   - "How many times did I ...?" is counted from the diary (exact, with the times); the language model is not
#     asked to count, because with a long diary it miscounts or gives up ("I didn't see that").
#   - "Did I close the fridge?" / "Is the tap still on?" come from the object-state memory (the last open / close /
#     on / off of that object), so a missing "close" is reported as "I did not see you close it", not "no record".
#   - Everything else goes to llm_qa.answer with the combined search, but only the best QA_SEARCH_LINES lines
#     (a 4B model answered worse with ~50 lines than with ~20).

import re

from query.llm_qa import answer as llm_answer, norm_tokens, time_range

QA_SEARCH_LINES = 20
_COUNT = re.compile(r"\bhow (many|often)\b|\bnumber of times\b", re.I)
_ONOFF = re.compile(r"\b(on|off)\b", re.I)  # "turned on" ≠ "turned off" (norm_tokens drops "on" as a stop word)


class _Top:
    """A Searcher that hands the language model only the best k lines."""

    def __init__(self, searcher, k: int):
        self.s, self.k = searcher, k

    def search(self, question, start=None, end=None, k=20, diary_only=False):
        return self.s.search(question, start, end, k=min(k, self.k), diary_only=diary_only)


def matches(row: dict, q: set[str], question: str = "") -> bool:
    """The diary line does what the question asks: its object is named and its verb is the asked one."""
    obj, verb = norm_tokens(row.get("object")), norm_tokens(row.get("verb"))
    if not obj or not verb or not obj <= q:
        return False
    if not (verb - {"up", "down", "off", "on"}) & q:
        return False
    onoff = {m.lower() for m in _ONOFF.findall(row.get("verb") or "")}
    return onoff <= {m.lower() for m in _ONOFF.findall(question)}


def count_answer(question: str, store, now) -> dict | None:
    """None when the question is not a count, or nothing in the diary matches it (then the model answers)."""
    if not _COUNT.search(question):
        return None
    start, end, period = time_range(question, now)
    q = norm_tokens(question)
    hits = [r for r in store.activities(start, end) if r.get("verb") and matches(r, q, question)]
    if not hits:
        return None
    what = f"{hits[0]['verb']} {hits[0]['object']}"
    times = ", ".join(r["ts_start"].strftime("%I:%M:%S %p").lstrip("0") for r in hits[:10]) + (" …" if len(hits) > 10 else "")
    n = len(hits)
    return {"answer": f"{n} time{'s' if n != 1 else ''} {period} ({what}): at {times}.", "lines": hits, "mode": "count"}


_STATE_Q = re.compile(r"\b(close|closed|shut|turn(ed)? off|switch(ed)? off|turn(ed)? on|switch(ed)? on|open(ed)?|"
                      r"leave|left|still)\b", re.I)
_WANT = {"open": ("open", "opened"), "closed": ("closed", "close"), "on": ("on",), "off": ("off",)}


def state_answer(question: str, store, now) -> dict | None:
    """'Did I close the fridge?' / 'Is the tap still on?' from the object-state memory: the last open / close /
    on / off of that object in the diary. None when the question names no tracked object or nothing is known."""
    from modules.vlm_logger import canon_state_object
    from services.api.alerts import object_states
    if not _STATE_Q.search(question):
        return None
    c = canon_state_object(question)
    if c is None:
        return None
    start, end, period = time_range(question, now)
    rows = [r for r in store.activities(start, end) if r.get("verb")]
    states = object_states(rows)
    power = bool(re.search(r"\b(on|off)\b", question, re.I)) and c[1] in ("on", "both")
    key = c[0] + (" power" if power and c[1] == "both" else "")
    if key not in states:
        return None
    state, _ = states[key]
    name = c[0]
    verb = {"open": "open", "closed": "close", "on": "turn on", "off": "turn off"}[state]
    done = {"open": "opened", "closed": "closed", "on": "turned on", "off": "turned off"}[state]
    lines = [r for r in rows if canon_state_object(r.get("object")) and canon_state_object(r["object"])[0] == name]
    last = [r for r in lines if (r.get("verb") or "").strip() in ("opens", "closes", "turns on", "turns off")][-1]
    t = last["ts_start"].strftime("%I:%M:%S %p").lstrip("0")         # when it started, as in the diary and counts
    asks_closed = bool(re.search(r"\b(close|closed|shut|turn(ed)? off|switch(ed)? off)\b", question, re.I))
    if state in ("closed", "off"):
        text = f"{'Yes' if asks_closed else 'No'}: you {done} the {name} at {t} (the last thing I saw it do)."
    else:
        undo = "close" if state == "open" else "turn off"
        text = (f"{'Not that I saw' if asks_closed else 'Probably yes'}: I saw you {verb} the {name} at {t}, and I did not "
                f"see you {undo} it after that. It may still be {state.upper()}.")
    return {"answer": text, "lines": lines[-5:], "mode": "state"}


def smart_answer(question: str, store, llm=None, now=None, searcher=None) -> dict:
    return count_answer(question, store, now) or state_answer(question, store, now) or \
        llm_answer(question, store, llm=llm, now=now, searcher=_Top(searcher, QA_SEARCH_LINES) if searcher else None)
