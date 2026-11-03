# Database

The reference diary: one SQLite file per user, `database/engram.db` (not in git).

| Table | One row per | Written by |
|---|---|---|
| `activities` | diary line: time, verb, object, where, place | backend, from the big model's answer |
| `fingerprints` | 4-s window: CLIP image fingerprint (float16, ~1 kB), also windows the trigger skipped | backend |
| `text_vectors` | distinct diary line: meaning vector for search | backend, when a question is asked |

No video and no images are stored. The fingerprints come from the camera images, so the whole file is private
data: it never leaves the device running the backend. The code is `mnemo/modules/storage.py` (EventStore).
