import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

import { ask, get, type Clip, type DiaryRow, type Moment, type Overview, type QuestionRecord } from "../lib/api";
import { clock, dateTime, localIso, suggestions, timecode } from "../lib/format";
import { useData } from "../lib/hooks";
import { Conversation, type Turn } from "../components/Conversation";
import { Failure } from "../components/ui";

interface Ctx { clips: Clip[]; last: string | null; rows: DiaryRow[] }

async function loadCtx(): Promise<Ctx> {
  const [{ clips }, o, days] = await Promise.all([
    get<{ clips: Clip[] }>("/api/clips"), get<Overview>("/api/overview"), get<{ days: { day: string }[] }>("/api/days"),
  ]);
  const rows = days.days[0] ? (await get<{ rows: DiaryRow[] }>(`/api/diary?day=${days.days[0].day}`)).rows : [];
  return { clips, last: o.last_activity, rows };
}

export function AskScreen() {
  const [params, setParams] = useSearchParams();
  const { data: ctx, error, reload } = useData(loadCtx, []);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  // "Today" in a question means the last day with recordings, so an older recording can still be asked about.
  const asOf = useMemo(() => {
    if (!ctx?.last) return null;
    const last = new Date(ctx.last);
    return last.toDateString() === new Date().toDateString() ? null : new Date(last.getTime() + 1000);
  }, [ctx]);

  useEffect(() => {
    void get<{ questions: QuestionRecord[] }>("/api/questions?limit=30").then((d) =>
      setTurns((now) => [...d.questions.slice().reverse().map((q) => ({
        key: `h${q.id}`, question: q.question,
        result: { answer: q.answer, kind: q.kind ?? "search", moment: null, evidence: q.evidence, latency_ms: q.latency_ms ?? 0, degraded: false },
      })), ...now])).catch(() => undefined);
  }, []);

  async function onAsk(q: string) {
    const key = `n${Date.now()}`;
    setBusy(true);
    setTurns((x) => [...x, { key, question: q }]);
    try {
      const result = await ask(q, asOf ? localIso(asOf) : null);
      setTurns((x) => x.map((m) => (m.key === key ? { ...m, result } : m)));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not answer";
      setTurns((x) => x.map((m) => (m.key === key ? { ...m, error: message } : m)));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {                                // arrived from the Overview box
    const q = params.get("q");
    if (q && ctx && !started.current) {
      started.current = true;
      setParams({}, { replace: true });
      void onAsk(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx]);

  const clipAt = (iso: string) => {
    const when = new Date(iso).getTime();
    const c = ctx?.clips.find((x) => when >= new Date(x.start).getTime() && when <= new Date(x.start).getTime() + (x.seconds + 5) * 1000);
    return c ? { clip: c, offset: (when - new Date(c.start).getTime()) / 1000 } : null;
  };

  const renderMoment = (m: Moment) => {
    const hit = clipAt(m.start);
    if (!hit) return <p className="turn-note">{clock(m.start)} · {m.what}</p>;
    return <Link className="jump" to={`/recordings/${hit.clip.id}?t=${Math.floor(hit.offset)}`}>Go to {timecode(hit.offset)} in {hit.clip.name} · {m.what} <ArrowUpRight size={12} /></Link>;
  };

  return (
    <div className="ask-page">
      <header className="page-head narrow">
        <div>
          <h1>Ask</h1>
          <p className="page-sub">Answers come from your diary, with the lines they used.</p>
        </div>
      </header>
      {error && <div className="narrow"><Failure message={error} retry={reload} /></div>}
      <div className="ask-body">
        <Conversation turns={turns} onAsk={(q) => void onAsk(q)} busy={busy}
                      suggestions={turns.length ? [] : suggestions(ctx?.rows ?? [], 4)}
                      placeholder="Did I close the fridge? How many times did I pick up the glass?"
                      context={asOf ? <>Answering as of your last recording, <b>{dateTime(asOf.toISOString())}</b></> : undefined}
                      renderMoment={renderMoment}
                      empty={<div className="ask-empty"><h3>Ask about anything you recorded</h3><p>Mnemo counts, checks what was left open, and finds moments.</p></div>} />
      </div>
    </div>
  );
}
