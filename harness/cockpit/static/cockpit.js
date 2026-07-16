"use strict";
const TOKEN = window.COCKPIT.token;
let STATE = { projects: [], tasks: [], roots: [], modes: [], approvals: [] };
let selProject = null, selTask = null, activeTab = "overview";
let collapsed = new Set();          // collapsed project ids
let FEED = [];                       // live activity rows (newest last)

/* ---------- API ---------- */
async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}
async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Cockpit-Token": TOKEN },
    body: JSON.stringify(body || {}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}
function toast(msg, err) {
  const t = document.getElementById("toast");
  t.innerHTML = `<span class="tdot">${err ? "✕" : "✓"}</span> ${esc(msg)}`;
  t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), 2800);
}
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

/* ---------- top bar ---------- */
function renderTop() {
  const es = document.getElementById("engineStatus");
  es.className = "engine-status " + (STATE.engine || "");
  document.getElementById("engineText").textContent = "engine " + (STATE.engine || "?");
  const n = (STATE.approvals || []).length;
  const pill = document.getElementById("needsPill");
  pill.classList.toggle("hidden", n === 0);
  document.getElementById("needsCount").textContent = n;
}

/* ---------- sidebar tree ---------- */
function statusDot(s) {
  if (["completed","cancelled","failed"].includes(s)) return "done";
  if (s === "blocked") return "blocked";
  if (["implementing","validating","repairing","discovering","planning"].includes(s)) return "active";
  return "";
}
function renderTree() {
  const tree = document.getElementById("tree");
  if (!STATE.projects.length) {
    tree.innerHTML = `<div class="empty-hint">No projects yet.<br>Click “Add project” below to pick a folder.</div>`;
    return;
  }
  tree.innerHTML = "";
  for (const p of STATE.projects) {
    const tasks = STATE.tasks.filter(t => t.project_id === p.id);
    const isCol = collapsed.has(p.id);
    const proj = document.createElement("div");
    proj.className = "proj" + (isCol ? " collapsed" : "");
    proj.innerHTML = `
      <div class="proj-row" data-pid="${p.id}">
        <span class="chev">▾</span>
        <span class="pname">${esc(p.name)}</span>
        <span class="pcount">${tasks.length}</span>
      </div>
      <div class="sessions"></div>`;
    const row = proj.querySelector(".proj-row");
    row.onclick = () => {
      selProject = p.id;
      if (isCol) collapsed.delete(p.id); else if (selProject === p.id && tasks.length) { /* keep open */ }
      render();
    };
    row.querySelector(".chev").onclick = (e) => {
      e.stopPropagation();
      if (collapsed.has(p.id)) collapsed.delete(p.id); else collapsed.add(p.id);
      render();
    };
    // drag files onto a project row → upload to that project's newest/only task
    row.ondragover = e => { e.preventDefault(); row.classList.add("drop-target"); };
    row.ondragleave = () => row.classList.remove("drop-target");
    row.ondrop = e => { e.preventDefault(); row.classList.remove("drop-target"); onDropFiles(e, tasks[0]); };

    const sc = proj.querySelector(".sessions");
    if (!tasks.length) {
      sc.innerHTML = `<div class="empty-hint" style="padding:6px 9px">No sessions. <a href="#" data-new="${p.id}" style="color:var(--accent)">+ New</a></div>`;
      sc.querySelector("[data-new]").onclick = (e) => { e.preventDefault(); selProject = p.id; openNewTask(); };
    } else {
      for (const t of tasks) {
        const el = document.createElement("div");
        el.className = "session" + (selTask === t.id ? " sel" : "");
        el.innerHTML = `<span class="sdot ${statusDot(t.status)}"></span>
          <span class="stitle">${esc(t.title || t.goal)}</span>`;
        el.onclick = () => { if (selTask !== t.id) activeTab = "overview"; selTask = t.id; selProject = p.id; render(); };
        sc.appendChild(el);
      }
    }
    tree.appendChild(proj);
  }
}

/* ---------- workspace ---------- */
function currentTask() { return STATE.tasks.find(t => t.id === selTask); }

function render() {
  renderTop();
  renderTree();
  const ws = document.getElementById("workspace");
  const t = currentTask();
  if (!t) {
    ws.innerHTML = `<div class="ws-empty"><div>
      <div class="big">◆</div><h2>Pick a session to get started</h2>
      <div>Choose a project on the left, or create one, then start a session under it.</div>
      </div></div>` + approvalsBannerHTML();
    wireApprovals(ws);
    return;
  }
  const proj = STATE.projects.find(p => p.id === t.project_id);
  const modeOpts = STATE.modes.map(m => `<option ${m===t.mode?"selected":""}>${m}</option>`).join("");
  ws.innerHTML = `
    ${approvalsBannerHTML()}
    <div class="ws-header">
      <div>
        <div class="ws-crumb">${esc(proj ? proj.name : "")} ${t.parent_id ? "· fork" : ""}</div>
        <h1 class="ws-title">${esc(t.title || t.goal)}</h1>
      </div>
      <div class="ws-actions">
        <select class="mode" id="modeSel" title="Permission mode">${modeOpts}</select>
        <button class="btn ghost sm" id="forkBtn">⑂ Fork</button>
        <button class="btn ghost sm" id="openChat">↗ ChatGPT</button>
      </div>
    </div>
    <div class="tabs">
      <button class="tab ${activeTab==='overview'?'active':''}" data-tab="overview">Overview</button>
      <button class="tab ${activeTab==='diff'?'active':''}" data-tab="diff">Diff${t.changed_files.length?`<span class="tab-badge">${t.changed_files.length}</span>`:""}</button>
      <button class="tab ${activeTab==='activity'?'active':''}" data-tab="activity">Activity${FEED.length?`<span class="tab-badge">${FEED.length}</span>`:""}</button>
    </div>
    <div class="tab-body" id="tabBody"></div>`;
  wireApprovals(ws);
  ws.querySelector("#modeSel").onchange = async e => {
    try { await post("/api/task/mode", { task_id: t.id, mode: e.target.value }); toast("mode → " + e.target.value); refresh(); }
    catch (err) { toast(err.message, true); }
  };
  ws.querySelector("#forkBtn").onclick = async () => {
    try { await post("/api/task/fork", { task_id: t.id }); toast("session forked"); refresh(); }
    catch (err) { toast(err.message, true); }
  };
  ws.querySelector("#openChat").onclick = () => window.open(t.chat_url || "https://chatgpt.com/", "_blank");
  ws.querySelectorAll(".tab").forEach(b => b.onclick = () => { activeTab = b.dataset.tab; renderTabBody(); syncTabs(); });
  renderTabBody();
}

function syncTabs() {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === activeTab));
}

function renderTabBody() {
  const t = currentTask(); if (!t) return;
  const body = document.getElementById("tabBody"); if (!body) return;
  if (activeTab === "overview") body.innerHTML = overviewHTML(t), wireOverview(body, t);
  else if (activeTab === "diff") { body.innerHTML = `<div class="diff" id="diffArea">Loading diff…</div>`; loadDiff(t.id); }
  else body.innerHTML = feedHTML();
}

function overviewHTML(t) {
  const prompt = `Resume harness task ${t.id}. Pass task_id="${t.id}" to every tool call.\nGoal: ${t.goal}`;
  const isoChip = t.worktree_path
    ? `<span class="chip accent"><span class="cdot"></span>isolated worktree</span>`
    : `<span class="chip warn"><span class="cdot"></span>shared checkout</span>`;
  return `
    <div class="card">
      <div class="meta">
        <dt>Goal</dt><dd>${esc(t.goal)}</dd>
        <dt>Task ID</dt><dd><code>${t.id}</code></dd>
        <dt>State</dt><dd><span class="chip ${["completed","cancelled","failed"].includes(t.status)?"done":"info"}">${t.status}</span></dd>
        <dt>Isolation</dt><dd>${isoChip}</dd>
        <dt>Working path</dt><dd><code>${esc(t.worktree_path || t.workspace_path)}</code></dd>
      </div>
    </div>
    <div class="card">
      <h3>Resume in ChatGPT</h3>
      <div class="prompt-box"><textarea readonly id="promptBox">${esc(prompt)}</textarea></div>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn sm" id="copyBtn">Copy prompt</button>
        <button class="btn ghost sm" id="openChat2">↗ Open ChatGPT</button>
      </div>
    </div>
    ${t.changed_files.length ? `<div class="card"><h3>Changed files (${t.changed_files.length})</h3>
      <div class="filelist">${t.changed_files.map(f=>`<div class="f"><span class="ic">✎</span>${esc(f)}</div>`).join("")}</div></div>`:""}
    ${t.test_results.length ? `<div class="card"><h3>Test runs</h3>${t.test_results.slice(-6).map(r=>
      `<div class="testrow">${r.passed?"✅":"❌"} ${esc(r.command||"")}</div>`).join("")}</div>`:""}
    ${t.checkpoints.length ? `<div class="card"><h3>Checkpoints</h3><div class="filelist">${t.checkpoints.slice(-6).map(c=>
      `<div class="f"><span class="ic">◷</span>${esc(c)} <button class="btn ghost sm" data-cp="${esc(c)}" style="margin-left:auto">restore</button></div>`).join("")}</div></div>`:""}
    <div class="card"><h3>Attach files</h3>
      <div class="dropzone" id="dropzone">Drag &amp; drop files here to copy them into this session’s folder</div>
      ${t.pinned_files.length?`<div class="filelist" style="margin-top:10px">${t.pinned_files.map(f=>`<div class="f"><span class="ic">📎</span>${esc(f)}</div>`).join("")}</div>`:""}
    </div>`;
}
function wireOverview(body, t) {
  const prompt = document.getElementById("promptBox")?.value || "";
  body.querySelector("#copyBtn").onclick = () => navigator.clipboard.writeText(prompt).then(()=>toast("prompt copied"));
  body.querySelector("#openChat2").onclick = () => window.open(t.chat_url || "https://chatgpt.com/", "_blank");
  body.querySelectorAll("[data-cp]").forEach(b => b.onclick = async () => {
    try { await post("/api/restore", { task_id: t.id, checkpoint_id: b.dataset.cp }); toast("restored to "+b.dataset.cp); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  const dz = body.querySelector("#dropzone");
  dz.ondragover = e => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = e => { e.preventDefault(); dz.classList.remove("over"); onDropFiles(e, t); };
}

async function onDropFiles(e, t) {
  if (!t) { toast("drop onto a session, not an empty project", true); return; }
  for (const f of [...e.dataTransfer.files]) {
    const buf = await f.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
    try { await post("/api/task/upload", { task_id: t.id, name: f.name, b64 }); toast("attached " + f.name); }
    catch (err) { toast(err.message, true); }
  }
  refresh();
}

async function loadDiff(tid) {
  const area = document.getElementById("diffArea");
  try {
    const r = await getJSON("/api/diff?task_id=" + encodeURIComponent(tid));
    const html = esc(r.diff || "(no changes)").split("\n").map(l =>
      l.startsWith("+") ? `<span class="add">${l}</span>` :
      l.startsWith("-") ? `<span class="del">${l}</span>` :
      (l.startsWith("@@")||l.startsWith("diff ")||l.startsWith("#")) ? `<span class="hdr">${l}</span>` : l
    ).join("\n");
    if (area) area.innerHTML = html;
  } catch (err) { if (area) area.textContent = err.message; }
}

function feedHTML() {
  if (!FEED.length) return `<div class="empty-hint">No activity yet. When ChatGPT works on a session, its tool calls stream here live.</div>`;
  return `<div class="feed">${FEED.slice(-200).map(e=>{
    const d = e.data || {};
    return `<div class="row ${d.capability||"read"}">
      <span class="t">${(e.time||"").slice(11,19)}</span>
      <span class="tool">${esc(d.tool||"")}</span>
      <span class="detail">${esc(d.detail||"")}</span>
      <span class="tag">${esc(d.task_id||"")}</span></div>`;
  }).reverse().join("")}</div>`;
}

/* ---------- approvals ---------- */
function approvalsBannerHTML() {
  const a = STATE.approvals || [];
  if (!a.length) return "";
  return `<div class="appr-banner">
    <div class="ab-head">⏸ ${a.length} action${a.length>1?"s":""} need your approval</div>
    ${a.map(x => `<div class="appr-item" data-aid="${x.id}">
      <span class="ac">${esc(x.detail || x.action)}</span>
      ${x.action==="command_arbitrary"?`<label class="rem"><input type="checkbox" class="remck"> remember</label>`:""}
      <button class="btn good sm" data-dec="approve">Approve</button>
      <button class="btn danger sm" data-dec="deny">Deny</button>
    </div>`).join("")}
  </div>`;
}
function wireApprovals(scope) {
  scope.querySelectorAll(".appr-item").forEach(item => {
    const aid = item.dataset.aid;
    item.querySelectorAll("[data-dec]").forEach(b => b.onclick = async () => {
      const remember = item.querySelector(".remck")?.checked || false;
      try { await post("/api/approval/decide", { id: aid, decision: b.dataset.dec, remember }); toast(b.dataset.dec === "approve" ? "approved" : "denied"); refresh(); }
      catch (err) { toast(err.message, true); }
    });
  });
}

/* ---------- actions ---------- */
async function addProject() {
  try {
    const r = await post("/api/pick_folder", {});
    if (!r.path) return;
    const add = await post("/api/root/add", { path: r.path });
    toast("folder added — restart engine to use it");
    if (add.needs_restart) await maybeRestart();
    refresh();
  } catch (err) { toast(err.message, true); }
}
document.getElementById("addProject").onclick = addProject;
document.getElementById("addProjectTop").onclick = addProject;

function openNewTask() {
  const proj = STATE.projects.find(p => p.id === selProject);
  document.getElementById("ntProjName").textContent = proj ? "in " + proj.name : "pick a project first";
  document.getElementById("newTaskDlg").showModal();
}
document.getElementById("ntCreate").onclick = async e => {
  e.preventDefault();
  const proj = STATE.projects.find(p => p.id === selProject);
  const goal = document.getElementById("ntGoal").value.trim();
  const mode = document.getElementById("ntMode").value;
  if (!goal || !proj) { toast("need a goal and a project", true); return; }
  try {
    const r = await post("/api/task/new", { project_path: proj.path, goal, mode });
    document.getElementById("newTaskDlg").close();
    document.getElementById("ntGoal").value = "";
    if (r.needs_approval) toast("shared-checkout needs approval — see the banner");
    else { toast("session created"); selTask = r.task_id; activeTab = "overview"; }
    refresh();
  } catch (err) { toast(err.message, true); }
};

document.getElementById("restart").onclick = maybeRestart;
document.getElementById("needsPill").onclick = () => { selTask = null; render(); };
async function maybeRestart() {
  try {
    const r = await post("/api/engine/restart", {});
    if (r.needs_confirm) {
      if (confirm("Restart interrupts active sessions: " + r.busy.active_tasks.join(", ") + ". Continue?"))
        { await post("/api/engine/restart", { force: true }); toast("engine restarting"); }
    } else toast("engine restarting");
  } catch (err) { toast(err.message, true); }
}

/* ---------- live feed (SSE) ---------- */
function connectFeed() {
  const es = new EventSource("/events");
  es.addEventListener("tool_call", ev => {
    try {
      FEED.push(JSON.parse(ev.data));
      if (FEED.length > 400) FEED = FEED.slice(-400);
      if (activeTab === "activity" && currentTask()) renderTabBody();
      const b = document.querySelector('.tab[data-tab="activity"] .tab-badge, .tab[data-tab="activity"]');
      scheduleRefresh();
    } catch {}
  });
  es.onerror = () => {}; // browser auto-reconnects with Last-Event-ID
}
let rt = null;
function scheduleRefresh(){ clearTimeout(rt); rt = setTimeout(refresh, 900); }

/* ---------- boot ---------- */
async function refresh() {
  try {
    const [state, appr] = await Promise.all([getJSON("/api/state"), getJSON("/api/approvals")]);
    STATE = { ...state, approvals: appr.approvals };
    if (!selProject && STATE.projects.length) selProject = STATE.projects[0].id;
    if (selTask && !STATE.tasks.find(t => t.id === selTask)) selTask = null;
    render();
  } catch (err) { toast("refresh failed: " + err.message, true); }
}
refresh();
connectFeed();
setInterval(refresh, 5000);
