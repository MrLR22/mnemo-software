import { useMemo, useRef } from "react";

import type { DiaryRow } from "../lib/api";
import { actionKind, capital, groupByMoment, timecode } from "../lib/format";

interface Span { from: number; to: number; state: string; closed: boolean }

/** One lane per object that has a state: bars from open/on to closed/off; a bar never closed runs to the end. */
function stateLanes(rows: DiaryRow[], processed: number): [string, Span[]][] {
  const lanes = new Map<string, Span[]>();
  const open = new Map<string, { from: number; state: string }>();
  for (const r of rows) {
    for (const s of r.state ?? []) {
      if (!lanes.has(s.object)) lanes.set(s.object, []);
      const at = r.offset_s ?? 0;
      if (s.state === "open" || s.state === "on") {
        if (!open.has(s.object)) open.set(s.object, { from: at, state: s.state });
      } else {
        const o = open.get(s.object);
        if (o) { lanes.get(s.object)!.push({ from: o.from, to: at, state: o.state, closed: true }); open.delete(s.object); }
      }
    }
  }
  open.forEach((o, name) => lanes.get(name)!.push({ from: o.from, to: processed, state: o.state, closed: false }));
  return [...lanes.entries()].filter(([, spans]) => spans.length > 0);
}

function ticks(total: number): number[] {
  const step = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].find((s) => total / s <= 12) ?? 7200;
  return Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step).filter((x) => x < total * 0.97);  // the last label would be cut off
}

interface Props {
  rows: DiaryRow[];
  seconds: number;
  processed: number;
  t: number;
  onSeek: (t: number) => void;
}

export function Timeline({ rows, seconds, processed, t, onSeek }: Props) {
  const track = useRef<HTMLDivElement>(null);
  const moments = useMemo(() => groupByMoment(rows), [rows]);
  const lanes = useMemo(() => stateLanes(rows, processed), [rows, processed]);
  const pct = (x: number) => `${(100 * Math.min(x, seconds)) / seconds}%`;

  const seekTo = (clientX: number) => {
    const box = track.current!.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(1, (clientX - box.left) / box.width)) * seconds);
  };

  return (
    <div className="tl">
      <div className="tl-labels">
        <div className="tl-ruler-gap" />
        <div className="tl-label tl-activity">Activity</div>
        {lanes.map(([name]) => <div key={name} className="tl-label">{capital(name)}</div>)}
      </div>
      <div className="tl-track" ref={track}
           onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seekTo(e.clientX); }}
           onPointerMove={(e) => { if (e.buttons === 1) seekTo(e.clientX); }}>
        <div className="tl-ruler">
          {ticks(seconds).map((x) => <span key={x} style={{ left: pct(x) }}>{timecode(x)}</span>)}
        </div>
        <div className="tl-lane tl-activity">
          {moments.map((m) => (
            <div key={m.offset} className="tl-moment" style={{ left: pct(m.offset), width: pct(m.length) }}
                 title={`${timecode(m.offset)}  ${m.rows.map((r) => `${r.verb} ${r.object}`).join(", ")}`}>
              {m.rows.map((r, i) => <i key={i} className={`kind-${actionKind(r.verb)}`} />)}
            </div>
          ))}
        </div>
        {lanes.map(([name, spans]) => (
          <div key={name} className="tl-lane">
            {spans.map((s, i) => (
              <div key={i} className={`tl-span${s.closed ? "" : " tl-span-open"}`}
                   style={{ left: pct(s.from), width: pct(s.to - s.from) }}
                   title={`${capital(name)} ${s.state} ${timecode(s.from)}${s.closed ? ` to ${timecode(s.to)}` : ", never seen closing"}`} />
            ))}
          </div>
        ))}
        {processed < seconds && <div className="tl-unprocessed" style={{ left: pct(processed) }} />}
        <div className="tl-playhead" style={{ left: pct(t) }} />
      </div>
    </div>
  );
}
