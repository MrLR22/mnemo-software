# Database

The reference diary lives on a **PostgreSQL** server, a separate part of the system. The schema is in
[`schema.sql`](schema.sql); the code that talks to it is `services/db/`.

| Table | One row per | Written by |
|---|---|---|
| `clips` | processed recording: name, start time, length, progress (never the video) | backend |
| `activities` | diary line: time, verb, object, where, place | backend, from the big model's answer |
| `fingerprints` | 4-s window: CLIP image fingerprint (float16, ~1 kB), also windows the trigger skipped | backend |
| `text_vectors` | distinct diary line: meaning vector for search | backend, when a question is asked |
| `questions` | question asked in the app: answer, route, evidence, time taken | backend |
| `events` | pick-up / put-down event of the first prototype | older code paths |

| View | What |
|---|---|
| `clip_diary` | each diary line with its recording and its position in the video (`offset_s`) |
| `clip_summary` | each recording with its numbers of actions, objects and questions |

No video and no images are stored. The fingerprints come from the camera images, so the whole database is private
data: it stays on the machine running the backend.

## Set up (Arch)

```
sudo pacman -S --needed postgresql
sudo -iu postgres initdb -D /var/lib/postgres/data --locale=C.UTF-8 --encoding=UTF8
sudo systemctl enable --now postgresql
sudo -iu postgres createuser --createdb $USER
createdb mnemo
```

`.env` holds `ENGRAM_DB_URL=postgresql:///mnemo`. The tables are created when the backend first connects.
Without that line the backend falls back to a single SQLite file (`database/engram.db`).

## Look inside

- In the app: **System → Database contents**.
- `psql mnemo`, or DBeaver (new connection → PostgreSQL → host `localhost`, database `mnemo`, your user name).

## Move an old SQLite diary across

```
python scripts/migrate_sqlite_to_postgres.py --url postgresql:///mnemo
```
