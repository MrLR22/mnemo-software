// ENGRAM web app: talks only to the backend (/api/...). Works the same on a laptop and in a phone browser.
const $ = (id) => document.getElementById(id);
const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, options = {}) {
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

health(); loadDiary().catch(() => {}); loadAlerts().catch(() => {});
