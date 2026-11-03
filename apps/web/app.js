// ENGRAM web app: talks only to the backend (/api/...). Works the same on a laptop and in a phone browser.
const $ = (id) => document.getElementById(id);
const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// App token (set when the backend is reachable from the internet): opened once as ...?token=XYZ, then remembered.
const urlToken = new URLSearchParams(location.search).get("token");
try { if (urlToken) localStorage.setItem("engram_token", urlToken); } catch (e) {}
const TOKEN = urlToken || (() => { try { return localStorage.getItem("engram_token") || ""; } catch (e) { return ""; } })();

async function api(path, options = {}) {
  options.headers = Object.assign({}, options.headers || {}, TOKEN ? { "X-Engram-Token": TOKEN } : {});
  const r = await fetch(path, options);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

async function health() {
  try {
    const h = await api("/api/health");
    const big = typeof h.big_model === "object" ? `big model: ${h.big_model.model}` : `big model: ${h.big_model}`;
    const small = typeof h.small_model === "object" ? "small model: ready" : `small model: ${h.small_model}`;
    $("health").textContent = `${big} · ${small}`;
  } catch (e) { $("health").textContent = `backend unreachable: ${e.message}`; }
}

async function loadDiary() {
  const d = await api("/api/diary");
  $("diary").innerHTML = d.rows.length
    ? d.rows.map((r) => `<li><span class="time">${time(r.start)}</span>${esc(r.verb)} ${esc(r.object)}`
        + `${r.where ? ` <span class="empty">→ ${esc(r.where)}</span>` : ""}</li>`).join("")
    : '<li class="empty">No entries yet.</li>';
}

async function loadAlerts() {
  const a = (await api("/api/alerts")).alerts;
  $("alerts").innerHTML = a.length
    ? a.map((x) => `<li class="alert">The ${esc(x.object)} was last seen ${x.state.toUpperCase()} at ${time(x.since)}</li>`).join("")
    : '<li class="empty">Nothing left open.</li>';
}

async function watch(job) {
  for (;;) {
    const j = await api(`/api/jobs/${job}`);
    if (j.status === "done") {
      const r = j.result;
      $("job").textContent = `Done: ${Math.round(r.video_seconds)} s of video, big model on ${r.big_model_calls} of ${r.windows} windows, ${r.rows} diary lines. Video deleted.`;
      await Promise.all([loadDiary(), loadAlerts()]);
      return;
    }
    if (j.status === "failed") { $("job").textContent = `Failed: ${j.error}`; return; }
    $("job").textContent = `${j.status}: ${j.step}…`;
    await new Promise((ok) => setTimeout(ok, 2000));
  }
}

$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $("job").textContent = `Uploading ${f.name} (${(f.size / 1e6).toFixed(1)} MB)…`;
  const body = new FormData();
  body.append("file", f);
  try { watch((await api("/api/clips", { method: "POST", body })).job); }
  catch (err) { $("job").textContent = `Upload failed: ${err.message}`; }
  e.target.value = "";
});

$("ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = $("answer");
  box.hidden = false;
  box.textContent = "Thinking…";
  try {
    const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ question: $("question").value }) });
    box.innerHTML = `<div>${esc(r.answer)}</div>`
      + (r.moment ? `<div class="moment">Best moment: ${time(r.moment.start)}–${time(r.moment.end)} · ${esc(r.moment.what)}</div>` : "")
      + (r.evidence.length ? `<div class="evidence">From the diary: ${r.evidence.map((x) => esc(x.line)).join("<br>")}</div>` : "");
  } catch (err) { box.textContent = `Could not answer: ${err.message}`; }
});

$("refresh").addEventListener("click", () => { loadDiary(); loadAlerts(); });
$("delete").addEventListener("click", async () => {
  if (!confirm("Delete the whole diary? This cannot be undone.")) return;
  await api("/api/diary", { method: "DELETE" });
  loadDiary(); loadAlerts();
});

// ── live: a new 4-s recording every 4 s, each sent as soon as it is finished ──
const PIECE_MS = 4000;
let live = null;

function recorderType() {
  for (const t of ["video/webm;codecs=vp8", "video/webm", "video/mp4"]) if (MediaRecorder.isTypeSupported(t)) return t;
  return "";
}

function recordPiece() {
  if (!live) return;
  const offset = (performance.now() - live.t0) / 1000;
  const type = recorderType();
  const rec = new MediaRecorder(live.stream, type ? { mimeType: type, videoBitsPerSecond: 800000 } : {});
  const parts = [];
  rec.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
  rec.onstop = async () => {
    const body = new FormData();
    body.append("file", new Blob(parts, { type: rec.mimeType }), rec.mimeType.includes("mp4") ? "piece.mp4" : "piece.webm");
    body.append("offset", offset.toFixed(2));
    try { await api(`/api/live/${live.sid}/piece`, { method: "POST", body }); } catch (e) { $("livestat").textContent = `upload failed: ${e.message}`; }
  };
  rec.start();
  setTimeout(() => { if (rec.state !== "inactive") rec.stop(); recordPiece(); }, PIECE_MS);
}

async function liveStatus() {
  if (!live) return;
  const s = await api(`/api/live/${live.sid}`);
  const lag = s.lag_last_s == null ? "–" : `${Math.round(s.lag_last_s)} s`;
  const cls = s.lag_last_s != null && s.lag_last_s > s.max_lag_limit_s * 0.8 ? "lag-warn" : "lag-ok";
  $("livestat").innerHTML = `<span class="${cls}">lag ${lag}</span> (max ${s.lag_max_s ?? "–"} s, limit ${s.max_lag_limit_s} s) · `
    + `described ${s.described} · nothing happening ${s.skipped_no_action} · skipped to keep the lag ${s.skipped_lag}`;
  $("liverecent").innerHTML = s.recent.slice().reverse().map((r) => `<li><span class="time">${time(r.start)}</span>${esc(r.verb)} ${esc(r.object)}</li>`).join("");
}

$("live").addEventListener("click", async () => {
  if (live) {                                            // stop
    const sid = live.sid;
    live.stream.getTracks().forEach((t) => t.stop());
    clearInterval(live.poll);
    live = null;
    $("live").textContent = "Start live";
    $("preview").hidden = true;
    await api(`/api/live/${sid}/stop`, { method: "POST" });
    setTimeout(() => { loadDiary(); loadAlerts(); }, 3000);
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    $("livestat").textContent = "This browser cannot record here (on a phone: open the https link the backend printed).";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    const { session } = await api("/api/live/start", { method: "POST" });
    live = { sid: session, stream, t0: performance.now() };
    $("preview").srcObject = stream; $("preview").hidden = false; $("preview").play();
    $("live").textContent = "Stop live";
    $("livestat").textContent = "recording…";
    recordPiece();
    live.poll = setInterval(() => { liveStatus().catch(() => {}); loadDiary().catch(() => {}); loadAlerts().catch(() => {}); }, 3000);
  } catch (e) { $("livestat").textContent = `Could not start the camera: ${e.message}`; }
});

health(); loadDiary().catch(() => {}); loadAlerts().catch(() => {});
