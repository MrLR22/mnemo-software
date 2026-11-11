# scripts/eval_ood.py: how well does the diary describe first-person video OUTSIDE kitchens?
# Runs the app's own pipeline (small model service on :8001, big model from .env) on non-kitchen clips of
# EgoActionBench (people labelled every hand action), into a throwaway database, and scores the diary:
#
#   coverage         windows where people labelled hand activity that the small model sent to the big model
#   object recall    labelled main objects (named in >= 2 actions) that appear in the diary (word match)
#   pick/put share   share of diary actions that are "picks up" / "puts down" (lower = more varied verbs)
#   distinct verbs   different verbs used over all clips
#   kitchen invented diary objects like fridge / tap / stove that people never mention in that clip
#
#   createdb mnemo_bench
#   python scripts/eval_ood.py --prompt lines-v6 --out eval_v6.json      (and --prompt lines-v3 to compare)
# Clips: ~/Documents/Engram/data_ood/videos (EgoActionBench, https://huggingface.co/datasets/play0718/EgoActionBench)

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import services  # noqa: E402,F401

W = 4.0
STOP = {"the", "a", "of", "and", "edge", "side", "top", "end", "part", "other", "hand", "right", "left", "lower",
        "upper", "front", "back", "inside", "interior", "small", "large", "piece", "object", "surface", "corner"}
KITCHEN = {"fridge", "tap", "stove", "oven", "microwave", "kettle", "sink", "freezer", "dishwasher", "faucet"}


def words(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


def env_file() -> dict:
    p = os.path.join(ROOT, ".env")
    return dict(l.strip().split("=", 1) for l in open(p) if "=" in l and not l.lstrip().startswith("#")) if os.path.exists(p) else {}


def main():
    data = os.path.expanduser("~/Documents/Engram/data_ood")
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", default=os.path.join(data, "videos"))
    ap.add_argument("--ann", default=os.path.join(data, "annotations.jsonl"))
    ap.add_argument("--db", default="postgresql:///mnemo_bench")
    ap.add_argument("--prompt", default="lines-v6", help="prompt version the big model uses (lines-v6 / lines-v3)")
    ap.add_argument("--batch", default="4")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    os.environ["ENGRAM_VLM_PROMPT"] = a.prompt               # read by RemoteDescriber
    os.environ["ENGRAM_VLM_BATCH"] = a.batch
    import psycopg
    from modules.landmarks import ClipEmbedder
    from services.api.clients import RemoteDescriber, RemoteTrigger
    from services.api.progressive import process_progressive

    env = {**env_file(), **os.environ}
    ann = {x["video_id"]: x for x in map(json.loads, open(a.ann))}
    emb = ClipEmbedder()
    describer = RemoteDescriber(env["ENGRAM_VLM_URL"], env.get("ENGRAM_VLM_TOKEN", ""))
    trigger = RemoteTrigger(env.get("ENGRAM_TRIGGER_URL", "http://127.0.0.1:8001"))
    base = datetime(2030 + (abs(hash(a.prompt + a.batch)) % 50), 1, 1, 9, 0, 0)   # each run in its own time span
    results, t_all = [], time.time()
    for i, f in enumerate(sorted(os.listdir(a.videos))):
        vid = f[:-4]
        if vid not in ann:
            continue
        x = ann[vid]
        work = tempfile.mkdtemp()
        path = shutil.copy(os.path.join(a.videos, f), work)       # the pipeline deletes its input (privacy)
        start = base + timedelta(hours=i)
        t0 = time.time()
        res = process_progressive(path, f"eval-{a.prompt}-{a.batch}-{i}", f, a.db, describer, trigger, emb, recorded_at=start)
        took = time.time() - t0
        with psycopg.connect(a.db) as c:
            rows = c.execute("SELECT ts_start, verb, object, where_ FROM activities WHERE ts_start >= %s AND ts_start < %s "
                             "ORDER BY ts_start, id", (start, start + timedelta(seconds=x["duration"] + 5))).fetchall()
        described = {round((r[0] - start).total_seconds() / W) for r in rows}
        active = {k for g in x["gt"] for k in range(int(g["start"] // W), int(max(g["start"], g["end"] - 1e-6) // W) + 1)}
        counts: dict[str, int] = {}
        for g in x["gt"]:
            for it in g["facet"]["objects"].get("items", []):
                ws = words(it["value"])
                if ws:
                    k = " ".join(sorted(ws))
                    counts[k] = counts.get(k, 0) + 1
        main_objs = [k for k, n in counts.items() if n >= 2] or list(counts)
        ours = set().union(*[words(r[2]) for r in rows if r[2]]) if rows else set()
        hit = [k for k in main_objs if set(k.split()) & ours]
        verbs = [r[1] for r in rows if r[1]]
        gt_words = set().union(*[words(g["caption"]) for g in x["gt"]])
        invented = [r[2] for r in rows if r[2] and (words(r[2]) & KITCHEN) and not (words(r[2]) & gt_words)]
        truth = []
        for g in sorted(x["gt"], key=lambda g: g["start"]):
            line = f'{g["start"]:5.1f}s {g["hand"]:5} {g["caption"]}'
            if g["caption"] not in " ".join(truth):
                truth.append(line)
        results.append({
            "clip": vid, "seconds": x["duration"], "took_s": round(took, 1), "windows": res["windows"],
            "described": res["big_model_calls"], "coverage": round(len(active & described) / max(1, len(active)), 2),
            "main_objects": main_objs, "objects_found": hit, "object_recall": round(len(hit) / max(1, len(main_objs)), 2),
            "pickput_share": round(sum(v in ("picks up", "puts down") for v in verbs) / max(1, len(verbs)), 2),
            "verbs": sorted(set(verbs)), "kitchen_invented": invented,
            "diary": [f'{(r[0] - start).total_seconds():5.1f}s {r[1] or "-"} | {r[2] or ""}' + (f" -> {r[3]}" if r[3] else "")
                      for r in rows],
            "truth": truth[:25]})
        r = results[-1]
        print(f"{vid}: {r['seconds']}s in {r['took_s']}s | coverage {r['coverage']} | objects {r['object_recall']} | "
              f"pick/put {r['pickput_share']} | verbs {', '.join(r['verbs'])[:90]}", flush=True)
    n = max(1, len(results))
    summary = {"prompt": a.prompt, "batch": a.batch, "clips": len(results), "total_s": round(time.time() - t_all, 1),
               "video_s": round(sum(r["seconds"] for r in results), 1),
               "coverage": round(sum(r["coverage"] for r in results) / n, 2),
               "object_recall": round(sum(r["object_recall"] for r in results) / n, 2),
               "pickput_share": round(sum(r["pickput_share"] for r in results) / n, 2),
               "distinct_verbs": len(set().union(*[set(r["verbs"]) for r in results])) if results else 0,
               "kitchen_invented": sum(len(r["kitchen_invented"]) for r in results)}
    json.dump({"summary": summary, "clips": results}, open(a.out, "w"), indent=1)
    print("SUMMARY", json.dumps(summary))


if __name__ == "__main__":
    main()
