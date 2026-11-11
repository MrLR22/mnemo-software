import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { get, type ObjectRecord } from "../lib/api";
import { capital, dateTime } from "../lib/format";
import { useData } from "../lib/hooks";
import { Empty, Failure, Page, SkeletonRows, StatePill } from "../components/ui";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "open", label: "Still open" },
  { id: "located", label: "With a location" },
] as const;

export function ObjectsScreen() {
  const { data, error, loading, reload } = useData(() => get<{ objects: ObjectRecord[] }>("/api/objects"), [], 10000);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");

  const list = useMemo(() => (data?.objects ?? []).filter((o) =>
    o.object.includes(q.trim().toLowerCase())
    && (filter === "all" || (filter === "open" ? o.state === "open" || o.state === "on" : !!o.where))), [data, q, filter]);

  return (
    <Page title="Objects" sub="Everything your hands touched, and the last thing that happened to it.">
      <div className="toolbar">
        <label className="search"><Search size={14} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an object" /></label>
        <div className="seg">
          {FILTERS.map((f) => <button key={f.id} className={filter === f.id ? "on" : ""} onClick={() => setFilter(f.id)}>{f.label}</button>)}
        </div>
        {data && <span className="quiet small push">{list.length} of {data.objects.length}</span>}
      </div>
      {error && <Failure message={error} retry={reload} />}
      {loading && !data && <SkeletonRows n={8} />}
      {data && list.length === 0 && <Empty title={data.objects.length ? "No object matches" : "No objects yet"}>{data.objects.length ? "Try another name or filter." : "Objects appear once a recording has been analysed."}</Empty>}
      {list.length > 0 && (
        <table className="table">
          <thead><tr><th>Object</th><th>State</th><th>Last action</th><th>Last seen at</th><th>When</th><th className="num">Handled</th></tr></thead>
          <tbody className="no-link">
            {list.map((o) => (
              <tr key={o.object}>
                <td className="strong">{capital(o.object)}</td>
                <td>{o.state ? <StatePill state={o.state} /> : <span className="quiet">–</span>}</td>
                <td>{o.last_action}</td>
                <td>{o.where ?? <span className="quiet">–</span>}</td>
                <td className="mono">{dateTime(o.last)}</td>
                <td className="num">{o.count}×</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Page>
  );
}
