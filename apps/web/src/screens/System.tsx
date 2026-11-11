import { useEffect, useState, type ReactNode } from "react";

import { get, type ServiceHealth, type SystemInfo, type TablePage } from "../lib/api";
import { bytes, duration } from "../lib/format";
import { useData } from "../lib/hooks";
import { isUp } from "../components/Shell";
import { Failure, Page, SkeletonRows } from "../components/ui";

function Node({ title, tech, up, status, children, style }: { title: string; tech: string; up: boolean; status: string; children?: ReactNode; style: React.CSSProperties }) {
  return (
    <div className="node" style={style}>
      <div className="node-top"><strong>{title}</strong><span className={`dot ${up ? "up" : "down"}`} title={status} /></div>
      <div className="node-tech">{tech}</div>
      <div className="node-detail">{children}</div>
    </div>
  );
}

const statusWord = (s: ServiceHealth) => (isUp(s) ? "online" : s === "off" ? "turned off" : "offline");

/** The parts of the system and how they connect. Column and row positions match the connecting lines. */
function Architecture({ sys }: { sys: SystemInfo }) {
  const dbUp = sys.database.engine !== "unreachable";
  const rows = sys.database.tables.reduce((n, t) => n + t.rows, 0);
  const leftW = "21%", midL = "29%", midW = "23%", rightL = "62%", rightW = "38%";
  return (
    <div className="arch">
      <svg viewBox="0 0 1000 348" preserveAspectRatio="none" aria-hidden="true">
        <g fill="none" stroke="var(--line-strong)" vectorEffect="non-scaling-stroke">
          <path d="M210 174H290" /><path d="M520 174H620" />
          <path d="M570 174V54H620" /><path d="M570 174V294H620" />
        </g>
      </svg>
      <span className="flow" style={{ left: "25%", top: 150 }}>REST</span>
      <span className="flow" style={{ left: "59.5%", top: 30 }}>SQL</span>
      <span className="flow" style={{ left: "59.5%", top: 150 }}>video</span>
      <span className="flow" style={{ left: "59.5%", top: 270 }}>frames</span>
      <Node title="Web app" tech="React · Vite" up status="running" style={{ left: 0, width: leftW, top: 120, height: 108 }}>
        This screen, in your browser
      </Node>
      <Node title="Backend API" tech="FastAPI · port 8000" up={sys.backend.status === "ok"} status={sys.backend.status} style={{ left: midL, width: midW, top: 96, height: 156 }}>
        <div>Up {duration(sys.backend.uptime_s)}</div>
        <div>Jobs {sys.backend.jobs.done} done · {sys.backend.jobs.running + sys.backend.jobs.queued} active · {sys.backend.jobs.failed} failed</div>
        <div>Search: {sys.backend.search === "hybrid" ? "words + meaning + images" : "words only"}</div>
      </Node>
      <Node title="Database" tech={sys.database.engine} up={dbUp} status={dbUp ? "online" : "offline"} style={{ left: rightL, width: rightW, top: 0, height: 108 }}>
        {dbUp ? <>{sys.database.database} · {bytes(sys.database.bytes)} · {sys.database.tables.length} tables · {rows.toLocaleString()} rows</> : sys.database.error}
      </Node>
      <Node title="Small model service" tech="HOI-TCN interaction trigger (ours) · port 8001" up={isUp(sys.small_model.status)} status={statusWord(sys.small_model.status)} style={{ left: rightL, width: rightW, top: 120, height: 108 }}>
        {capitalStatus(sys.small_model.status)} · decides which moments are worth describing
      </Node>
      <Node title="Big model service" tech="Qwen3-VL-4B · remote GPU" up={isUp(sys.big_model.status)} status={statusWord(sys.big_model.status)} style={{ left: rightL, width: rightW, top: 240, height: 108 }}>
        {capitalStatus(sys.big_model.status)} · {isUp(sys.big_model.status) ? "describes moments, words answers" : "counts and open/closed answers still work"}
      </Node>
    </div>
  );
}

const capitalStatus = (s: ServiceHealth) => { const w = statusWord(s); return w[0].toUpperCase() + w.slice(1); };

function TableBrowser({ name }: { name: string }) {
  const { data, error, loading } = useData(() => get<TablePage>(`/api/system/tables/${name}?limit=50`), [name]);
  if (error) return <Failure message={error} />;
  if (loading || !data) return <SkeletonRows n={6} h={26} />;
  if (data.rows.length === 0) return <p className="quiet pad">This table is empty.</p>;
  return (
    <div className="grid-scroll">
      <table className="grid">
        <thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => <td key={j} className={v === null ? "null" : ""} title={typeof v === "string" ? v : undefined}>{v === null ? "NULL" : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {data.total > data.rows.length && <p className="quiet small pad">Newest {data.rows.length} of {data.total.toLocaleString()} rows</p>}
    </div>
  );
}

export function SystemScreen() {
  const { data, error, loading, reload } = useData(() => get<SystemInfo>("/api/system"), [], 6000);
  const [table, setTable] = useState<string | null>(null);

  useEffect(() => {
    if (!table && data?.database.tables.length) setTable(data.database.tables.find((t) => t.table === "activities")?.table ?? data.database.tables[0].table);
  }, [data, table]);

  return (
    <Page title="System" sub="The separate parts of Mnemo, checked live.">
      {error && <Failure message={error} retry={reload} />}
      {loading && !data && <SkeletonRows n={6} h={48} />}
      {data && (
        <>
          <Architecture sys={data} />
          <div className="section-head spaced"><h2>Database contents</h2><span className="quiet small">{data.database.engine}</span></div>
          <div className="db">
            <ul className="db-tables">
              {data.database.tables.map((t) => (
                <li key={t.table}>
                  <button className={table === t.table ? "on" : ""} onClick={() => setTable(t.table)}>
                    <span>{t.table}</span><b>{t.rows.toLocaleString()}</b><i>{bytes(t.bytes)}</i>
                  </button>
                </li>
              ))}
              {(data.database.views ?? []).map((v) => (
                <li key={v}><button className={table === v ? "on" : ""} onClick={() => setTable(v)}><span>{v}</span><b>view</b></button></li>
              ))}
            </ul>
            <div className="db-view">{table && <TableBrowser name={table} />}</div>
          </div>
        </>
      )}
    </Page>
  );
}
