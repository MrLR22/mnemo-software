-- database/schema.sql
-- The Mnemo reference diary on PostgreSQL. Applied automatically by services/db/postgres.py when the backend starts
-- (every statement is idempotent), or by hand:  psql mnemo -f database/schema.sql
--
-- No video and no images are stored. Recordings are kept only as numbers (name, start time, length, progress);
-- what happened in them is kept as diary lines; search uses small vectors derived from the frames.

-- A recorded first-person video that was processed. The video file itself is deleted after processing.
CREATE TABLE IF NOT EXISTS clips (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    started_at    TIMESTAMP   NOT NULL,              -- when the recording started (diary times are absolute)
    seconds       REAL        NOT NULL CHECK (seconds >= 0),
    windows       INTEGER     NOT NULL DEFAULT 0,    -- 4-second windows seen by the small model
    described     INTEGER     NOT NULL DEFAULT 0,    -- windows the big model described
    status        TEXT        NOT NULL DEFAULT 'done' CHECK (status IN ('processing', 'done', 'failed')),
    processed_s   REAL        NOT NULL DEFAULT 0,    -- the diary is complete up to this point of the video
    created_at    TIMESTAMP   NOT NULL DEFAULT now()
);

-- The reference diary: one line per thing the hands did (or a place-only line when nothing was done).
CREATE TABLE IF NOT EXISTS activities (
    id            BIGSERIAL PRIMARY KEY,
    ts_start      TIMESTAMP   NOT NULL,
    ts_end        TIMESTAMP   NOT NULL CHECK (ts_end >= ts_start),
    verb          TEXT,                              -- NULL = nothing done with the hands
    object        TEXT,
    place         TEXT,
    where_        TEXT,                              -- where the object is / ended up
    seen          TEXT,                              -- objects in view, comma-separated
    raw           TEXT,                              -- the model's full answer, kept for checking
    source        TEXT                               -- 'vlm' (described) or 'state' (open/closed memory)
);
CREATE INDEX IF NOT EXISTS idx_activities_ts     ON activities (ts_start);
CREATE INDEX IF NOT EXISTS idx_activities_object ON activities (lower(object));

-- Search: one image fingerprint (CLIP, float16, ~1 kB) per 4-second window, also for windows not described.
CREATE TABLE IF NOT EXISTS fingerprints (
    id            BIGSERIAL PRIMARY KEY,
    ts_start      TIMESTAMP(3) NOT NULL,
    ts_end        TIMESTAMP(3) NOT NULL,
    model         TEXT         NOT NULL,             -- vectors of different models never mix
    vec           BYTEA        NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fingerprints_model_ts ON fingerprints (model, ts_start);

-- Search: one meaning vector per distinct diary line (cached the first time a question needs it).
CREATE TABLE IF NOT EXISTS text_vectors (
    text          TEXT  NOT NULL,
    model         TEXT  NOT NULL,
    vec           BYTEA NOT NULL,
    PRIMARY KEY (text, model)
);

-- Every question asked in the app, with its answer: the app's "recent questions" and the review's audit trail.
CREATE TABLE IF NOT EXISTS questions (
    id            BIGSERIAL PRIMARY KEY,
    asked_at      TIMESTAMP   NOT NULL DEFAULT now(),
    question      TEXT        NOT NULL,
    answer        TEXT        NOT NULL,
    kind          TEXT,                              -- count | state | search: which answering route was used
    clip_id       TEXT REFERENCES clips (id) ON DELETE SET NULL,
    as_of         TIMESTAMP,                         -- asked "as of" this moment of a recording (replay), else NULL
    moment        TIMESTAMP,                         -- the diary moment the answer points to
    evidence      JSONB       NOT NULL DEFAULT '[]', -- diary lines the answer was built from
    latency_ms    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_questions_asked ON questions (asked_at DESC);

-- Pick-up / put-down events of the first prototype (kept so old code paths still work).
CREATE TABLE IF NOT EXISTS events (
    id            BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMP NOT NULL,
    object        TEXT      NOT NULL,
    action        TEXT      NOT NULL CHECK (action IN ('pickup', 'putdown')),
    landmark      TEXT,
    confidence    REAL      NOT NULL,
    note          TEXT,
    source        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_obj_ts ON events (object, ts);

-- Diary lines per recording: a line belongs to the recording whose time span contains it.
CREATE OR REPLACE VIEW clip_diary AS
SELECT c.id AS clip_id, c.name AS clip_name,
       EXTRACT(EPOCH FROM (a.ts_start - c.started_at))::REAL AS offset_s,
       a.*
FROM clips c
JOIN activities a
  ON a.ts_start >= c.started_at
 AND a.ts_start <  c.started_at + make_interval(secs => c.seconds + 5);

-- One row per recording with its numbers: what the "Library" screen shows.
CREATE OR REPLACE VIEW clip_summary AS
SELECT c.*,
       (SELECT count(*) FROM clip_diary d WHERE d.clip_id = c.id AND d.verb IS NOT NULL) AS actions,
       (SELECT count(DISTINCT lower(d.object)) FROM clip_diary d WHERE d.clip_id = c.id) AS objects,
       (SELECT count(*) FROM questions q WHERE q.clip_id = c.id) AS questions
FROM clips c;
