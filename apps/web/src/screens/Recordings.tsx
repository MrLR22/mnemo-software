import { useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Trash2, Upload } from "lucide-react";

import { deleteClip, get, upload, type Clip, type Job } from "../lib/api";
import { dateTime, duration } from "../lib/format";
import { useData } from "../lib/hooks";
import { forgetVideo, saveVideo } from "../lib/localVideo";
import { ClipStatusTag, Empty, Failure, Page, SkeletonRows } from "../components/ui";

type Stage = { kind: "idle" } | { kind: "upload"; name: string; fraction: number } | { kind: "prepare"; name: string } | { kind: "error"; message: string };

const sleep = (ms: number) => new Promise((ok) => setTimeout(ok, ms));

export function RecordingsScreen() {
  const nav = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [over, setOver] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const { data, error, loading, reload } = useData(() => get<{ clips: Clip[] }>("/api/clips"), [], 3000);
  const clips = data?.clips ?? [];

  async function add(file: File) {
    if (!file.type.startsWith("video/") && !/\.(mp4|mov|webm|mkv|avi)$/i.test(file.name)) {
      setStage({ kind: "error", message: `${file.name} is not a video file.` });
      return;
    }
    setStage({ kind: "upload", name: file.name, fraction: 0 });
    try {
      const id = await upload(file, (fraction) => setStage({ kind: "upload", name: file.name, fraction }));
      await saveVideo(id, file);                  // replay on this device: the backend deletes its copy
      setStage({ kind: "prepare", name: file.name });
      for (;;) {                                  // the recording is listed as soon as processing starts
        const job = await get<Job>(`/api/jobs/${id}`);
        if (job.status === "failed") throw new Error(job.error ?? "Processing failed");
        if (job.progress || job.status === "done") break;
        await sleep(800);
      }
      nav(`/recordings/${id}`);
    } catch (e) {
      setStage({ kind: "error", message: e instanceof Error ? e.message : "Upload failed" });
    }
  }

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files[0];
    if (f) void add(f);
  };

  async function remove(id: string) {
    setConfirming(null);
    await deleteClip(id).catch(() => undefined);
    await forgetVideo(id);
    void reload();
  }

  const busy = stage.kind === "upload" || stage.kind === "prepare";

  return (
    <Page title="Recordings" sub="Each video becomes a diary. The video itself is deleted from the server after processing."
          actions={<button className="btn primary" disabled={busy} onClick={() => input.current?.click()}><Upload size={14} />Add recording</button>}>
      <input ref={input} type="file" accept="video/*" hidden data-testid="file-input"
             onChange={(e) => { const f = e.target.files?.[0]; if (f) void add(f); e.target.value = ""; }} />

      <div className={`drop${over ? " over" : ""}`}
           onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
        {stage.kind === "upload" && (
          <div className="drop-progress">
            <span>Uploading {stage.name}</span><b>{Math.round(stage.fraction * 100)}%</b>
            <div className="bar"><i style={{ width: `${stage.fraction * 100}%` }} /></div>
          </div>
        )}
        {stage.kind === "prepare" && <div className="drop-progress"><span>Starting analysis of {stage.name}</span><div className="bar bar-busy"><i /></div></div>}
        {(stage.kind === "idle" || stage.kind === "error") && <span>Drop a first-person video here, or use <em>Add recording</em></span>}
      </div>
      {stage.kind === "error" && <Failure message={stage.message} />}
      {error && <Failure message={error} retry={reload} />}
      {loading && !data && <SkeletonRows />}

      {data && clips.length === 0 && <Empty title="No recordings yet">Add a video above to create your first diary.</Empty>}

      {clips.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Recording</th><th>Recorded</th><th className="num">Length</th><th className="num">Actions</th><th className="num">Objects</th><th>Analysis</th><th /></tr>
          </thead>
          <tbody>
            {clips.map((c) => {
              const share = c.status === "done" ? 1 : (c.processed_s ?? 0) / c.seconds;
              return (
                <tr key={c.id} onClick={() => nav(`/recordings/${c.id}`)}>
                  <td className="strong"><Link to={`/recordings/${c.id}`} onClick={(e) => e.stopPropagation()}>{c.name ?? "Recording"}</Link></td>
                  <td>{dateTime(c.start)}</td>
                  <td className="num">{duration(c.seconds)}</td>
                  <td className="num">{c.actions ?? "–"}</td>
                  <td className="num">{c.objects ?? "–"}</td>
                  <td>
                    <div className="status-cell">
                      <ClipStatusTag clip={c} />
                      {c.status === "processing" && <div className="bar slim"><i style={{ width: `${share * 100}%` }} /></div>}
                      {c.status === "done" && c.windows ? <span className="quiet small">{c.described} of {c.windows} windows described</span> : null}
                    </div>
                  </td>
                  <td className="row-end" onClick={(e) => e.stopPropagation()}>
                    {confirming === c.id
                      ? <span className="confirm"><button className="btn small danger" onClick={() => void remove(c.id)}>Delete</button><button className="btn small" onClick={() => setConfirming(null)}>Keep</button></span>
                      : <button className="icon-btn" title="Delete this recording and its diary" aria-label="Delete" onClick={() => setConfirming(c.id)}><Trash2 size={14} /></button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Page>
  );
}
