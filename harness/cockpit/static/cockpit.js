"use strict";
const TOKEN = window.COCKPIT.token;
let STATE = { projects: [], tasks: [], roots: [], modes: [] };
let selProject = null, selTask = null;

// ---- API helpers ----------------------------------------------------------
async function getJSON(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}
async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Cockpit-Token": TOKEN },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 2600);
}

// ---- rendering ------------------------------------------------------------
function render() {
  const engine = document.getElementById("engine");
  engine.textContent = STATE.engine || "?"; engine.className = STATE.engine || "";

  // Projects
  const pl = document.getElementById("projectList");
  pl.innerHTML = STATE.projects.length ? "" : '<li class="empty">No projects. Click + Add.</li>';
  STATE.projects.forEach(p => {
    const n = STATE.tasks.filter(t => t.project_id === p.id).length;
    const li = document.createElement("li");
    li.className = "item" + (selProject === p.id ? " sel" : "");
    li.innerHTML = `<div class="t1">📁 ${esc(p.name)}</div>
      <div class="t2">${n} session${n === 1 ? "" : "s"}</div>`;
    li.onclick = () => { selProject = p.id; selTask = null; render(); };
    pl.appendChild(li);
  });

  // Sessions under selected project
  const proj = STATE.projects.find(p => p.id === selProject);
  document.getElementById("projName").textContent = proj ? "· " + proj.name : "";
  document.getElementById("newTask").disabled = !proj;
  const tl = document.getElementById("taskList");
  const tasks = STATE.tasks.filter(t => t.project_id === selProject);
  tl.innerHTML = proj ? (tasks.length ? "" : '<li class="empty">No sessions yet. Click + New.</li>')
                      : '<li class="empty">Select a project.</li>';
  tasks.forEach(t => {
    const li = document.createElement("li");
    li.className = "item" + (selTask === t.id ? " sel" : "");
    const done = ["completed", "cancelled", "failed"].includes(t.status);
    const iso = t.worktree_path ? '<span class="badge wt">worktree</span>' : '<span class="badge shared">shared</span>';
    li.innerHTML = `<div class="t1">💬 ${esc(t.title || t.goal)}</div>
      <div class="t2"><span class="badge mode">${t.effective_mode}</span>${iso}
      <span class="badge ${done ? "done" : ""}">${t.status}</span></div>`;
    li.onclick = () => { selTask = t.id; render(); };
    tl.appendChild(li);
  });

  renderDetail(proj);
  renderApprovals();
}

function renderDetail(proj) {
  const d = document.getElementById("detail");
  const t = STATE.tasks.find(x => x.id === selTask);
  if (!t) { d.innerHTML = '<div class="empty">Select a session.</div>'; return; }
  const modeOpts = STATE.modes.map(m =>
    `<option ${m === t.mode ? "selected" : ""}>${m}</option>`).join("");
  const prompt = `Resume harness task ${t.id}. Pass task_id="${t.id}" to every tool call.\nGoal: ${t.goal}`;
  d.innerHTML = `
    <h2>${esc(t.title || t.goal)}</h2>
    <div class="goal">${esc(t.goal)}</div>
    <div class="grid">
      <b>task id</b><span>${t.id}</span>
      <b>state</b><span>${t.status}</span>
      <b>mode</b><span><select id="modeSel">${modeOpts}</select>
        ${t.operator_elevated ? '<span class="badge">operator-elevated</span>' : ""}</span>
      <b>isolation</b><span>${t.worktree_path ? "worktree ✓" : "shared checkout ⚠"}</span>
      <b>working path</b><span><code>${esc(t.worktree_path || t.workspace_path)}</code></span>
    </div>
    <div class="row" style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small" id="forkBtn">⑂ Fork</button>
      <button class="btn small ghost" id="diffBtn">📊 Show diff</button>
      <button class="btn small ghost" id="openChat">↗ Open ChatGPT</button>
    </div>
    <div class="copyprompt">
      <div class="section-title">Resume prompt (paste into ChatGPT)</div>
      <textarea readonly id="promptBox">${esc(prompt)}</textarea>
      <button class="btn small" id="copyBtn" style="margin-top:6px">Copy prompt</button>
    </div>
    ${t.changed_files.length ? `<div class="section-title">Changed files</div>
      <div class="changed">${t.changed_files.map(f => `<code>${esc(f)}</code>`).join("")}</div>` : ""}
    ${t.test_results.length ? `<div class="section-title">Test runs</div>
      <div class="changed">${t.test_results.slice(-5).map(r =>
        `<code>${r.passed ? "✅" : "❌"} ${esc(r.command || "")}</code>`).join("")}</div>` : ""}
    ${t.checkpoints.length ? `<div class="section-title">Checkpoints</div>
      <div class="changed">${t.checkpoints.slice(-5).map(c =>
        `<code>${esc(c)} <button class="btn small ghost" data-cp="${esc(c)}">restore</button></code>`).join("")}</div>` : ""}
    <div id="diffArea"></div>
    <div class="section-title">Attach files (drag &amp; drop)</div>
    <div class="dropzone" id="dropzone">Drop files here to copy them into this session's folder</div>
    ${t.pinned_files.length ? `<div class="files">${t.pinned_files.map(f => `<code>📎 ${esc(f)}</code>`).join("")}</div>` : ""}
  `;
  document.getElementById("modeSel").onchange = async e => {
    try { await post("/api/task/mode", { task_id: t.id, mode: e.target.value }); toast("mode → " + e.target.value); refresh(); }
    catch (err) { toast(err.message, true); }
  };
  document.getElementById("forkBtn").onclick = async () => {
    try { const r = await post("/api/task/fork", { task_id: t.id }); toast("forked"); refresh(); }
    catch (err) { toast(err.message, true); }
  };
  document.getElementById("diffBtn").onclick = () => showDiff(t.id);
  document.getElementById("copyBtn").onclick = () => {
    navigator.clipboard.writeText(prompt).then(() => toast("prompt copied"));
  };
  document.getElementById("openChat").onclick = () => window.open(t.chat_url || "https://chatgpt.com/", "_blank");
  d.querySelectorAll("[data-cp]").forEach(b => b.onclick = async () => {
    try { await post("/api/restore", { task_id: t.id, checkpoint_id: b.dataset.cp }); toast("restored"); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  setupDropzone(t);
}

async function showDiff(tid) {
  const area = document.getElementById("diffArea");
  area.innerHTML = '<div class="section-title">Diff</div><div class="diff">loading…</div>';
  try {
    const r = await getJSON("/api/diff?task_id=" + encodeURIComponent(tid));
    const html = esc(r.diff || "(no changes)").split("\n").map(l => {
      if (l.startsWith("+")) return `<span class="add">${l}</span>`;
      if (l.startsWith("-")) return `<span class="del">${l}</span>`;
      if (l.startsWith("@@") || l.startsWith("diff ")) return `<span class="hdr">${l}</span>`;
      return l;
    }).join("\n");
    area.innerHTML = '<div class="section-title">Diff</div><div class="diff">' + html + '</div>';
  } catch (err) { area.innerHTML = '<div class="diff">' + esc(err.message) + '</div>'; }
}

function renderApprovals() {
  const ul = document.getElementById("approvals");
  const items = STATE.approvals || [];
  ul.innerHTML = items.length ? "" : '<li class="empty">Nothing waiting.</li>';
  items.forEach(a => {
    const li = document.createElement("li");
    const isCmd = a.action === "command_arbitrary";
    li.innerHTML = `<div class="cmd">${esc(a.detail || a.action)}</div>
      <div class="row">
        <button class="btn small good" data-ap="approve">Approve</button>
        <button class="btn small bad" data-ap="deny">Deny</button>
        ${isCmd ? '<label style="margin:0;color:var(--dim);font-size:11px"><input type="checkbox" class="rem" style="width:auto"> remember</label>' : ""}
      </div>`;
    li.querySelectorAll("[data-ap]").forEach(b => b.onclick = async () => {
      const remember = li.querySelector(".rem")?.checked || false;
      try { await post("/api/approval/decide", { id: a.id, decision: b.dataset.ap, remember }); toast(b.dataset.ap + "d"); refresh(); }
      catch (err) { toast(err.message, true); }
    });
    ul.appendChild(li);
  });
}

// ---- drag & drop files ----------------------------------------------------
function setupDropzone(task) {
  const dz = document.getElementById("dropzone");
  if (!dz) return;
  dz.ondragover = e => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = async e => {
    e.preventDefault(); dz.classList.remove("over");
    const files = [...e.dataTransfer.files];
    for (const f of files) {
      const buf = await f.arrayBuffer();
      const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
      try {
        await post("/api/task/upload", { task_id: task.id, name: f.name, b64 });
        toast("attached " + f.name);
      } catch (err) { toast(err.message, true); }
    }
    refresh();
  };
}

// ---- actions --------------------------------------------------------------
document.getElementById("addProject").onclick = async () => {
  try {
    const r = await post("/api/pick_folder", {});
    if (!r.path) return;
    const add = await post("/api/root/add", { path: r.path });
    toast("root added — restart engine to use it");
    if (add.needs_restart) await maybeRestart();
    refresh();
  } catch (err) { toast(err.message, true); }
};

document.getElementById("newTask").onclick = () => {
  document.getElementById("newTaskDlg").showModal();
};
document.getElementById("ntCreate").onclick = async e => {
  e.preventDefault();
  const proj = STATE.projects.find(p => p.id === selProject);
  const goal = document.getElementById("ntGoal").value.trim();
  const mode = document.getElementById("ntMode").value;
  if (!goal || !proj) return;
  try {
    const r = await post("/api/task/new", { project_path: proj.path, goal, mode });
    document.getElementById("newTaskDlg").close();
    document.getElementById("ntGoal").value = "";
    if (r.needs_approval) { toast("needs approval (shared checkout) — check NEEDS YOU"); }
    else { toast("session created"); selTask = r.task_id; }
    refresh();
  } catch (err) { toast(err.message, true); }
};

document.getElementById("restart").onclick = maybeRestart;
async function maybeRestart() {
  try {
    const r = await post("/api/engine/restart", {});
    if (r.needs_confirm) {
      if (confirm("Restart will interrupt active tasks: " + r.busy.active_tasks.join(", ") + ". Continue?")) {
        await post("/api/engine/restart", { force: true }); toast("engine restarting");
      }
    } else toast("engine restarting");
  } catch (err) { toast(err.message, true); }
}
document.getElementById("clearFeed").onclick = () => document.getElementById("feed").innerHTML = "";

// ---- live feed (SSE) ------------------------------------------------------
function connectFeed() {
  const es = new EventSource("/events");
  es.addEventListener("tool_call", ev => {
    const d = JSON.parse(ev.data);
    const data = d.data || {};
    const li = document.createElement("li");
    li.className = "cap-" + (data.capability || "read");
    const time = (d.time || "").slice(11, 19);
    li.innerHTML = `${time} <b>${esc((data.tool || "").padEnd(14))}</b> ${esc(data.detail || "")} <span style="color:var(--dim)">${data.task_id || ""}</span>`;
    const feed = document.getElementById("feed");
    feed.appendChild(li);
    while (feed.children.length > 200) feed.removeChild(feed.firstChild);
    feed.scrollTop = feed.scrollHeight;
    // A tool call may have changed task state; refresh soon (debounced).
    scheduleRefresh();
  });
  es.onerror = () => { /* browser auto-reconnects with Last-Event-ID */ };
}

let refreshTimer = null;
function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 800); }

// ---- boot -----------------------------------------------------------------
async function refresh() {
  try {
    const [state, appr] = await Promise.all([getJSON("/api/state"), getJSON("/api/approvals")]);
    STATE = { ...state, approvals: appr.approvals };
    if (!selProject && STATE.projects.length) selProject = STATE.projects[0].id;
    render();
  } catch (err) { toast("refresh failed: " + err.message, true); }
}
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

refresh();
connectFeed();
setInterval(refresh, 5000);
