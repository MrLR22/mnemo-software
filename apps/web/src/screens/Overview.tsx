import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, CornerDownLeft } from "lucide-react";

import { get, type Alert, type Clip, type DiaryRow, type Overview, type QuestionRecord } from "../lib/api";
import { ago, capital, dateTime, duration, shortClock } from "../lib/format";
import { useData } from "../lib/hooks";
import { ActivityStrip, ClipStatusTag, Empty, Failure, Page, SkeletonRows, StatePill } from "../components/ui";

interface Home {
  stats: Overview;
  alerts: Alert[];
  clips: { clip: Clip; rows: DiaryRow[] }[];
  questions: QuestionRecord[];
}

async function loadHome(): Promise<Home> {
  const [stats, alerts, clips, questions] = await Promise.all([
    get<Overview>("/api/overview"),
    get<{ alerts: Alert[] }>("/api/alerts"),
    get<{ clips: Clip[] }>("/api/clips"),
    get<{ questions: QuestionRecord[] }>("/api/questions?limit=5"),
  ]);
  const withRows = await Promise.all(clips.clips.slice(0, 4).map(async (clip) =>
    ({ clip, rows: (await get<{ rows: DiaryRow[] }>(`/api/clips/${clip.id}/diary`)).rows })));
  return { stats, alerts: alerts.alerts, clips: withRows, questions: questions.questions };
}

export function OverviewScreen() {
  const { data, error, loading, reload } = useData(loadHome, [], 8000);
  const [q, setQ] = useState("");
  const nav = useNavigate();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (q.trim()) nav(`/ask?q=${encodeURIComponent(q.trim())}`);
  };

  const s = data?.stats;
  const maxObject = Math.max(1, ...(s?.top_objects.map((o) => o.count) ?? [1]));

  return (
    <Page title="Overview" sub={s?.last_activity ? `Last activity ${dateTime(s.last_activity)}` : "Nothing recorded yet"}>
      <form className="ask-box ask-hero" onSubmit={submit}>
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Ask a question"
               placeholder="Ask about anything you did. “Did I close the fridge?”" />
        <button type="submit" aria-label="Ask"><CornerDownLeft size={16} /></button>
      </form>

      {error && <Failure message={error} retry={reload} />}

      {s && (
        <dl className="kpis">
          <div><dt>Recordings</dt><dd>{s.recordings}</dd></div>
          <div><dt>Footage</dt><dd>{duration(s.recorded_seconds)}</dd></div>
          <div><dt>Actions logged</dt><dd>{s.diary_lines}</dd></div>
          <div><dt>Objects tracked</dt><dd>{s.objects}</dd></div>
          <div><dt>Questions asked</dt><dd>{s.questions}</dd></div>
        </dl>
      )}

      {loading && !data && <SkeletonRows n={6} />}

      {data && (
        <div className="home-grid">
          <section>
            <div className="section-head"><h2>Recent recordings</h2><Link to="/recordings">All recordings <ArrowUpRight size={13} /></Link></div>
            {data.clips.length === 0 && (
              <Empty title="No recordings yet" action={<Link className="btn primary" to="/recordings">Add a recording</Link>}>
                Upload a first-person video and Mnemo writes its diary.
              </Empty>
            )}
            <div className="home-clips">
              {data.clips.map(({ clip, rows }) => (
                <Link key={clip.id} to={`/recordings/${clip.id}`} className="home-clip">
                  <div className="home-clip-top">
                    <strong>{clip.name ?? "Recording"}</strong>
                    <ClipStatusTag clip={clip} />
                  </div>
                  <ActivityStrip rows={rows} seconds={clip.seconds} processed={clip.status === "done" ? clip.seconds : clip.processed_s ?? 0} />
                  <div className="home-clip-meta">{dateTime(clip.start)} · {duration(clip.seconds)} · {rows.length} actions</div>
                </Link>
              ))}
            </div>

            {data.questions.length > 0 && (
              <>
                <div className="section-head spaced"><h2>Recent questions</h2><Link to="/ask">Ask <ArrowUpRight size={13} /></Link></div>
                <ul className="plain-list">
                  {data.questions.map((x) => (
                    <li key={x.id} className="home-q">
                      <span>{x.question}</span><time>{ago(x.asked_at)}</time>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <aside>
            <div className="section-head"><h2>Still open</h2></div>
            {data.alerts.length === 0
              ? <p className="quiet">Everything you opened or turned on was seen closing.</p>
              : (
                <ul className="plain-list">
                  {data.alerts.map((a) => (
                    <li key={a.object} className="alert-row">
                      <span>{capital(a.object)}</span>
                      <StatePill state={a.state} />
                      <time>since {shortClock(a.since)}</time>
                    </li>
                  ))}
                </ul>
              )}

            <div className="section-head spaced"><h2>Most handled</h2><Link to="/objects">All objects <ArrowUpRight size={13} /></Link></div>
            <ul className="bars">
              {s!.top_objects.map((o) => (
                <li key={o.object}>
                  <span>{capital(o.object)}</span>
                  <i style={{ width: `${(100 * o.count) / maxObject}%` }} />
                  <b>{o.count}</b>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </Page>
  );
}
