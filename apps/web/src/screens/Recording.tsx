import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, FileVideo, Pause, Play } from "lucide-react";

import { ask, get, type Clip, type DiaryRow, type Moment, type QuestionRecord } from "../lib/api";
import { capital, dateTime, duration, groupByMoment, localIso, suggestions, timecode } from "../lib/format";
import { useData } from "../lib/hooks";
import { loadVideo, saveVideo } from "../lib/localVideo";
import { Conversation, type Turn } from "../components/Conversation";
import { Timeline } from "../components/Timeline";
import { Action, ClipStatusTag, Empty, Failure, KindLegend, Skeleton } from "../components/ui";

const RATES = [1, 2, 4];

export function RecordingScreen() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const [polling, setPolling] = useState(true);
  const { data, error, reload } = useData(() => get<{ clip: Clip; rows: DiaryRow[] }>(`/api/clips/${id}/diary`), [id], polling ? 3000 : null);
  const clip = data?.clip;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const processed = clip ? (clip.status === "done" ? clip.seconds : clip.processed_s ?? 0) : 0;

  useEffect(() => { if (clip) setPolling(clip.status === "processing"); }, [clip]);

  // ── the clock: the video when there is one, otherwise the position picked on the timeline ──
  const video = useRef<HTMLVideoElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [t, setT] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [tab, setTab] = useState<"diary" | "ask">("diary");
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let url: string | null = null;
    let live = true;
    void loadVideo(id).then((blob) => {
      if (blob && live) { url = URL.createObjectURL(blob); setSrc(url); }
    });
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [id]);

  useEffect(() => {                                // keep the playhead smooth while playing
    if (!playing) return;
    let raf = 0, last = 0;
    const tick = (now: number) => {
      if (now - last > 66 && video.current) { last = now; setT(video.current.currentTime); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const seek = useCallback((to: number) => {
    setT(to);
    if (video.current) video.current.currentTime = to;
  }, []);

  useEffect(() => {                                // /recordings/x?t=72 opens at that moment
    const at = params.get("t");
    if (at && clip) seek(Number(at));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip?.id, src]);

  const toggle = useCallback(() => {
    const v = video.current;
    if (!v) return;
    if (v.paused) void v.play(); else v.pause();
  }, []);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.code === "Space") { e.preventDefault(); toggle(); }
      if (e.code === "ArrowRight" && video.current) seek(video.current.currentTime + 5);
      if (e.code === "ArrowLeft" && video.current) seek(video.current.currentTime - 5);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [seek, toggle]);

  // Without a video the diary shows everything processed; with one it fills up as the video plays.
  const at = Math.min(t ?? (src ? 0 : processed), processed);
  const shown = useMemo(() => rows.filter((r) => (r.offset_s ?? 0) <= at), [rows, at]);
  const moments = useMemo(() => groupByMoment(shown).reverse(), [shown]);

  const stillOpen = useMemo(() => {
    const now = new Map<string, { state: string; since: number }>();
    for (const r of shown) for (const s of r.state ?? []) now.set(s.object, { state: s.state, since: r.offset_s ?? 0 });
    return [...now.entries()].filter(([, v]) => v.state === "open" || v.state === "on");
  }, [shown]);

  // ── questions about this recording, answered as of the moment the video is at ──
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTurns([]);
    void get<{ questions: QuestionRecord[] }>(`/api/questions?limit=20&clip_id=${id}`).then((d) =>
      setTurns(d.questions.slice().reverse().map((q) => ({
        key: `h${q.id}`, question: q.question,
        result: { answer: q.answer, kind: q.kind ?? "search", moment: null, evidence: q.evidence, latency_ms: q.latency_ms ?? 0, degraded: false },
      })))).catch(() => undefined);
  }, [id]);

  async function onAsk(q: string) {
    if (!clip) return;
    const key = `n${Date.now()}`;
    const asOf = at;
    setBusy(true);
    setTurns((x) => [...x, { key, question: q, note: `As of ${timecode(asOf)} in this recording` }]);
    try {
      const atIso = localIso(new Date(new Date(clip.start).getTime() + asOf * 1000 + 1000));
      const result = await ask(q, atIso, clip.id);
      setTurns((x) => x.map((m) => (m.key === key ? { ...m, result } : m)));
    } catch (e) {
      const error = e instanceof Error ? e.message : "Could not answer";
      setTurns((x) => x.map((m) => (m.key === key ? { ...m, error } : m)));
    } finally {
      setBusy(false);
    }
  }

  const offsetOf = (iso: string) => (new Date(iso).getTime() - new Date(clip!.start).getTime()) / 1000;

  const renderMoment = (m: Moment) => {
    const from = offsetOf(m.start);
    if (from < 0 || from > clip!.seconds) return null;
    return <button className="jump" onClick={() => seek(from)}>Go to {timecode(from)} · {m.what}</button>;
  };

  async function pick(file: File) {
    await saveVideo(id, file);
    setSrc(URL.createObjectURL(file));
    setT(0);
  }

  if (error && !data) {
    return (
      <div className="page">
        <Link className="back" to="/recordings"><ArrowLeft size={14} />Recordings</Link>
        <Failure message={error === "no such clip" ? "This recording no longer exists." : error} retry={reload} />
      </div>
    );
  }
  if (!clip) return <div className="page"><Skeleton h={24} w={280} /><br /><Skeleton h={420} /></div>;

  const shownTo = processed < clip.seconds ? `Analysed up to ${timecode(processed)} of ${timecode(clip.seconds)}` : null;

  return (
    <div className="work">
      <header className="work-head">
        <Link className="icon-btn" to="/recordings" aria-label="Back to recordings"><ArrowLeft size={15} /></Link>
        <h1>{clip.name ?? "Recording"}</h1>
        <ClipStatusTag clip={clip} />
        <span className="work-meta">{dateTime(clip.start)} · {duration(clip.seconds)}{clip.windows ? ` · ${clip.described} of ${clip.windows} windows described` : ""}</span>
        {shownTo && <span className="work-meta strong">{shownTo}</span>}
      </header>

      <div className="work-body">
        <div className="stage">
          {src ? (
            <video ref={video} src={src} playsInline onClick={toggle} data-testid="player"
                   onPlay={() => { setPlaying(true); if (video.current) video.current.playbackRate = rate; }}
                   onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
                   onSeeked={(e) => setT(e.currentTarget.currentTime)} />
          ) : (
            <div className="stage-empty">
              <FileVideo size={22} strokeWidth={1.5} />
              <p>The server does not keep videos. Choose the original file to play it here; it stays on this computer.</p>
              <button className="btn" onClick={() => picker.current?.click()}>Choose video file</button>
              <input ref={picker} type="file" accept="video/*" hidden data-testid="replay-input"
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) void pick(f); }} />
            </div>
          )}
          {stillOpen.length > 0 && (
            <div className="stage-alerts">
              {stillOpen.map(([name, v]) => (
                <button key={name} onClick={() => seek(v.since)}><b>{capital(name)}</b> {v.state} since {timecode(v.since)}</button>
              ))}
            </div>
          )}
        </div>

        <aside className="panel">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "diary"} className={tab === "diary" ? "on" : ""} onClick={() => setTab("diary")}>Diary <span>{shown.length}</span></button>
            <button role="tab" aria-selected={tab === "ask"} className={tab === "ask" ? "on" : ""} onClick={() => setTab("ask")}>Ask</button>
          </div>
          {tab === "diary" && (
            <div className="diary-scroll">
              {moments.length === 0 && (
                <Empty title={rows.length ? "Nothing yet at this point" : clip.status === "processing" ? "Writing the diary" : "No actions in this recording"}>
                  {rows.length ? "Press play. Lines appear when they happen." : clip.status === "processing" ? "The first lines appear in a few seconds." : undefined}
                </Empty>
              )}
              {moments.map((m) => (
                <button key={m.offset} className={`moment${m === moments[0] && playing ? " current" : ""}`} onClick={() => seek(m.offset)}>
                  <time>{timecode(m.offset)}</time>
                  <div>{m.rows.map((r, i) => <div key={i}><Action row={r} /></div>)}</div>
                </button>
              ))}
            </div>
          )}
          {tab === "ask" && (
            <Conversation turns={turns} onAsk={(q) => void onAsk(q)} busy={busy} suggestions={turns.length ? [] : suggestions(rows)}
                          placeholder="Ask about this recording"
                          context={<>Answering as of <b>{timecode(at)}</b>{processed < clip.seconds ? ` · analysed to ${timecode(processed)}` : ""}</>}
                          renderMoment={renderMoment}
                          renderEvidenceTime={(r) => {
                            const off = offsetOf(r.start);
                            return <button className="time-link" onClick={() => seek(off)}>{timecode(off)}</button>;
                          }}
                          empty={<p className="quiet pad">Questions are answered from the diary, only up to the moment on the timeline.</p>} />
          )}
        </aside>
      </div>

      <footer className="transport">
        <div className="transport-row">
          <button className="play" onClick={toggle} disabled={!src} aria-label={playing ? "Pause" : "Play"}>
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </button>
          <span className="tc"><b>{timecode(at)}</b> / {timecode(clip.seconds)}</span>
          <div className="rates">
            {RATES.map((r) => (
              <button key={r} className={rate === r ? "on" : ""} disabled={!src}
                      onClick={() => { setRate(r); if (video.current) video.current.playbackRate = r; }}>{r}×</button>
            ))}
          </div>
          <KindLegend />
        </div>
        <Timeline rows={rows} seconds={clip.seconds} processed={processed} t={at} onSeek={seek} />
      </footer>
    </div>
  );
}
