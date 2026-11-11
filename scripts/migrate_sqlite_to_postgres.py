# scripts/migrate_sqlite_to_postgres.py
# Copies an existing SQLite diary (database/engram.db) into the PostgreSQL database, table by table.
# Safe to run twice: it refuses to copy into a database that already holds diary lines (unless --replace).
#
#   python scripts/migrate_sqlite_to_postgres.py [--sqlite database/engram.db] [--url postgresql:///mnemo] [--replace]

import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import services  # noqa: F401,E402
from services.db.postgres import connect  # noqa: E402

TS = lambda s: datetime.fromisoformat(s) if s else None  # noqa: E731


def main():
    ap = argparse.ArgumentParser()
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ap.add_argument("--sqlite", default=os.path.join(root, "database", "engram.db"))
    ap.add_argument("--url", default=os.environ.get("ENGRAM_DB_URL", "postgresql:///mnemo"))
    ap.add_argument("--replace", action="store_true", help="empty the Postgres tables first")
    a = ap.parse_args()

    src = sqlite3.connect(a.sqlite)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    pg = connect(a.url)
    if pg.execute("SELECT count(*) AS n FROM activities").fetchone()["n"] and not a.replace:
        sys.exit("The Postgres diary is not empty. Run again with --replace to overwrite it.")
    if a.replace:
        pg.execute("TRUNCATE activities, fingerprints, text_vectors, questions, clips, events RESTART IDENTITY")

    n = {}
    with pg.transaction():
        if "clips" in have:
            rows = src.execute("SELECT * FROM clips").fetchall()
            for r in rows:
                r = dict(r)
                pg.execute("INSERT INTO clips (id, name, started_at, seconds, windows, described, status, processed_s, "
                           "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                           (r["id"], r["name"], TS(r["start"]), r["seconds"], r["windows"] or 0, r["described"] or 0,
                            r.get("status") or "done", r.get("processed_s") if r.get("processed_s") is not None
                            else r["seconds"], TS(r["created"])))
            n["clips"] = len(rows)
        rows = src.execute("SELECT * FROM activities ORDER BY id").fetchall()
        with pg.cursor() as cur:
            cur.executemany("INSERT INTO activities (ts_start, ts_end, verb, object, place, where_, seen, raw, source) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            [(TS(r["ts_start"]), max(TS(r["ts_end"]), TS(r["ts_start"])), r["verb"], r["object"],
                              r["place"], r["where_"], r["seen"] if "seen" in r.keys() else None, r["raw"], r["source"])
                             for r in rows])
        n["activities"] = len(rows)
        if "fingerprints" in have:
            rows = src.execute("SELECT * FROM fingerprints ORDER BY id").fetchall()
            with pg.cursor() as cur:
                cur.executemany("INSERT INTO fingerprints (ts_start, ts_end, model, vec) VALUES (%s, %s, %s, %s)",
                                [(TS(r["ts_start"]), TS(r["ts_end"]), r["model"], r["vec"]) for r in rows])
            n["fingerprints"] = len(rows)
        if "text_vectors" in have:
            rows = src.execute("SELECT * FROM text_vectors").fetchall()
            with pg.cursor() as cur:
                cur.executemany("INSERT INTO text_vectors (text, model, vec) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                                [(r["text"], r["model"], r["vec"]) for r in rows])
            n["text_vectors"] = len(rows)
        if "events" in have:
            rows = src.execute("SELECT * FROM events ORDER BY id").fetchall()
            with pg.cursor() as cur:
                cur.executemany("INSERT INTO events (ts, object, action, landmark, confidence, note, source) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                [(TS(r["ts"]), r["object"], r["action"], r["landmark"], r["confidence"], r["note"],
                                  r["source"]) for r in rows])
            n["events"] = len(rows)
    print("Copied into", a.url, "->", ", ".join(f"{k}: {v}" for k, v in n.items()))


if __name__ == "__main__":
    main()
