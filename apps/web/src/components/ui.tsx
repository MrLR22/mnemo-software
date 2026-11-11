import type { ReactNode } from "react";
import { CircleAlert } from "lucide-react";

import type { Clip, DiaryRow } from "../lib/api";
import { actionKind, capital, groupByMoment, timecode } from "../lib/format";

export function Page({ title, sub, actions, children }: { title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <p className="page-sub">{sub}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {children}
    </div>
  );
}

export const Skeleton = ({ h = 16, w = "100%" }: { h?: number; w?: number | string }) =>
  <div className="skeleton" style={{ height: h, width: w }} />;

export const SkeletonRows = ({ n = 5, h = 40 }: { n?: number; h?: number }) => (
  <div className="skeleton-rows">{Array.from({ length: n }, (_, i) => <Skeleton key={i} h={h} />)}</div>
);

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Failure({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="failure" role="alert">
      <CircleAlert size={16} />
      <span>{message}</span>
      {retry && <button className="btn small" onClick={retry}>Try again</button>}
    </div>
  );
}

export function StatePill({ state }: { state: string }) {
  const live = state === "open" || state === "on";
  return <span className={`pill ${live ? "pill-live" : "pill-quiet"}`}>{state}</span>;
}

export function ClipStatusTag({ clip }: { clip: Clip }) {
  if (clip.status === "done") return <span className="pill pill-quiet">Ready</span>;
  if (clip.status === "processing") return <span className="pill pill-accent">Processing</span>;
  return clip.processed_s
    ? <span className="pill pill-live">Stopped at {timecode(clip.processed_s)}</span>
    : <span className="pill pill-bad">Failed</span>;
}

export function Action({ row }: { row: DiaryRow }) {
  return (
    <span className="action">
      <i className={`kind kind-${actionKind(row.verb)}`} />
      <span className="action-verb">{capital(row.verb ?? "")}</span>{" "}
      <span className="action-object">{row.object}</span>
      {row.where && row.where !== row.place && <span className="action-where"> → {row.where}</span>}
    </span>
  );
}

/** A thin strip showing when things happened in a recording. */
export function ActivityStrip({ rows, seconds, processed }: { rows: DiaryRow[]; seconds: number; processed: number }) {
  return (
    <div className="strip" aria-hidden="true">
      {processed < seconds && <div className="strip-rest" style={{ left: `${(100 * processed) / seconds}%` }} />}
      {groupByMoment(rows).map((m) => (
        <i key={m.offset} className={`kind-${actionKind(m.rows[0].verb)}`}
           style={{ left: `${(100 * m.offset) / seconds}%`, width: `${(100 * m.length) / seconds}%`,
                    opacity: Math.min(1, 0.45 + 0.2 * m.rows.length) }} />
      ))}
    </div>
  );
}

export const KindLegend = () => (
  <div className="legend">
    <span><i className="kind kind-state" />Open / close / on / off</span>
    <span><i className="kind kind-handle" />Picked up / put down</span>
    <span><i className="kind kind-use" />Other actions</span>
  </div>
);
