import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { deleteDiary, get, type DiaryRow } from "../lib/api";
import { clock, dayLabel } from "../lib/format";
import { useData } from "../lib/hooks";
import { Action, Empty, Failure, KindLegend, Page, SkeletonRows } from "../components/ui";

export function DiaryScreen() {
  const days = useData(() => get<{ days: { day: string; lines: number }[] }>("/api/days"), []);
  const [day, setDay] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState(false);

  useEffect(() => { if (!day && days.data?.days[0]) setDay(days.data.days[0].day); }, [days.data, day]);

  const diary = useData(() => (day ? get<{ rows: DiaryRow[] }>(`/api/diary?day=${day}`) : Promise.resolve({ rows: [] })), [day]);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (diary.data?.rows ?? []).filter((r) => !s || `${r.verb} ${r.object} ${r.where ?? ""}`.toLowerCase().includes(s));
  }, [diary.data, q]);

  async function wipe() {
    setConfirm(false);
    await deleteDiary();
    setDay(null);
    await days.reload();
    await diary.reload();
  }

  const none = days.data && days.data.days.length === 0;

  return (
    <Page title="Diary" sub="The written record of what you did. No video and no images are kept."
          actions={confirm
            ? <span className="confirm"><span className="quiet small">This cannot be undone.</span><button className="btn small danger" onClick={() => void wipe()}>Delete everything</button><button className="btn small" onClick={() => setConfirm(false)}>Keep</button></span>
            : !none && <button className="btn small ghost" onClick={() => setConfirm(true)}>Delete my diary</button>}>
      {days.error && <Failure message={days.error} retry={days.reload} />}
      {none && <Empty title="The diary is empty">It fills up when you add a recording.</Empty>}

      {days.data && !none && (
        <>
          <div className="toolbar">
            <div className="seg">
              {days.data.days.slice(0, 7).map((d) => <button key={d.day} className={d.day === day ? "on" : ""} onClick={() => setDay(d.day)}>{dayLabel(d.day)}</button>)}
            </div>
            <label className="search"><Search size={14} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by action or object" /></label>
            <span className="push"><KindLegend /></span>
          </div>
          {diary.error && <Failure message={diary.error} retry={diary.reload} />}
          {diary.loading && !diary.data && <SkeletonRows n={10} h={30} />}
          {diary.data && rows.length === 0 && <Empty title="No lines match">Try another word.</Empty>}
          {rows.length > 0 && (
            <ol className="diary-list">
              {rows.map((r, i) => (
                <li key={i}>
                  <time>{clock(r.start)}</time>
                  <Action row={r} />
                  <span className="quiet small">{r.place}</span>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </Page>
  );
}
