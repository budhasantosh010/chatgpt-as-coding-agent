import {
  EFFORT_LEVELS, EFFORT_LABELS, ULTRA_OPTIONS, LOOPS_OPTIONS, TASK_TYPES,
  ULTRA_CUSTOM_MAX, LOOPS_CUSTOM_MAX,
} from "./contract-options.mjs?v=22";

const INSPECTOR_TABS = [
  ["activity", "Activity"], ["changes", "Changes"], ["terminal", "Terminal"],
  ["files", "Files"], ["approvals", "Approvals"],
];

export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

function timeAgo(iso) {
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function statusClass(status) {
  if (["completed", "cancelled", "failed"].includes(status)) return "done";
  if (status === "blocked") return "blocked";
  if (["implementing", "validating", "repairing", "discovering", "planning"].includes(status)) return "active";
  return "idle";
}

export function taskMatchesSearch(task, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return `${task.id} ${task.title || ""} ${task.goal || ""}`.toLowerCase().includes(needle);
}

function projectUpdatedAt(project, tasks) {
  return tasks.reduce((latest, task) => task.project_id === project.id && (task.updated || "") > latest ? task.updated : latest, project.created || "");
}

export function sortProjectsByActivity(projects, tasks) {
  return [...projects].sort((a, b) => Number(b.pinned) - Number(a.pinned)
    || projectUpdatedAt(b, tasks).localeCompare(projectUpdatedAt(a, tasks))
    || a.name.localeCompare(b.name));
}

function projectTree(state) {
  const query = state.search.trim().toLowerCase();
  const allTasks = state.data.tasks;
  const projectMatches = (project) => project.name.toLowerCase().includes(query);
  const matchingTasks = (project) => allTasks.filter((task) => task.project_id === project.id)
    .filter((task) => !query || projectMatches(project) || taskMatchesSearch(task, query))
    .sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));

  const pinnedTasks = allTasks.filter((task) => task.pinned)
    .filter((task) => taskMatchesSearch(task, query))
    .sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  const pinnedProjects = sortProjectsByActivity(state.data.projects.filter((project) => project.pinned), allTasks)
    .filter((project) => !query || projectMatches(project));
  const pinned = [...pinnedProjects.map((project) => `
    <button class="sidebar-row pinned-row" data-action="select-project" data-project="${esc(project.id)}" type="button">
      <span class="row-icon folder-icon" aria-hidden="true"></span><span class="row-label">${esc(project.name)}</span><span class="pin-mark">Pinned</span>
    </button>`), ...pinnedTasks.map((task) => `
    <button class="sidebar-row pinned-row ${task.id === state.selectedTask ? "selected" : ""}" data-action="select-task" data-task="${esc(task.id)}" type="button">
      <span class="status-dot ${statusClass(task.status)}"></span><span class="row-label">${esc(task.title || task.goal)}</span><span class="row-time">${timeAgo(task.updated)}</span>
    </button>`)].join("");

  const projects = sortProjectsByActivity(state.data.projects, allTasks)
    .filter((project) => !query || projectMatches(project) || matchingTasks(project).length)
    .map((project) => {
      const tasks = matchingTasks(project);
      const collapsed = state.collapsedProjects.has(project.id);
      return `<section class="project-group ${collapsed ? "collapsed" : ""}">
        <div class="project-row ${project.id === state.selectedProject ? "current" : ""}">
          <button class="disclosure" data-action="toggle-project" data-project="${esc(project.id)}" type="button" aria-label="Toggle ${esc(project.name)}">${collapsed ? ">" : "v"}</button>
          <button class="project-select" data-action="select-project" data-project="${esc(project.id)}" type="button"><span class="folder-icon" aria-hidden="true"></span><span>${esc(project.name)}</span></button>
          <button class="pin-button ${project.pinned ? "is-pinned" : ""}" data-action="pin-project" data-project="${esc(project.id)}" data-pinned="${String(!project.pinned)}" type="button" aria-label="${project.pinned ? "Unpin" : "Pin"} ${esc(project.name)}">Pin</button>
        </div>
        <div class="session-list">${tasks.length ? tasks.map((task) => `
          <div class="session-row ${task.id === state.selectedTask ? "selected" : ""}">
            <button class="session-select" data-action="select-task" data-task="${esc(task.id)}" type="button">
              <span class="status-dot ${statusClass(task.status)}"></span><span class="row-label">${esc(task.title || task.goal)}</span><span class="row-time">${timeAgo(task.updated)}</span>
            </button>
            <button class="pin-button ${task.pinned ? "is-pinned" : ""}" data-action="pin-task" data-task="${esc(task.id)}" data-pinned="${String(!task.pinned)}" type="button" aria-label="${task.pinned ? "Unpin" : "Pin"} session">Pin</button>
          </div>`).join("") : `<button class="empty-session" data-action="new-session" data-project="${esc(project.id)}" type="button">+ New session</button>`}</div>
      </section>`;
    }).join("");

  if (!state.data.projects.length) return `<div class="sidebar-empty"><p>No projects yet.</p><button class="text-button" data-action="add-project" type="button">Add a folder</button></div>`;
  return `${pinned ? `<section class="sidebar-section"><h2>Pinned</h2>${pinned}</section>` : ""}
    <section class="sidebar-section"><h2>Projects</h2>${projects || `<p class="no-results">No matches</p>`}</section>`;
}

function sessionTabs(state) {
  const tabs = state.openTabs.map((id) => state.data.tasks.find((task) => task.id === id)).filter(Boolean);
  if (!tabs.length) return `<span class="tabs-placeholder">No open sessions</span>`;
  return tabs.map((task) => `<div class="session-tab ${task.id === state.selectedTask ? "active" : ""}" role="presentation">
    <button role="tab" aria-selected="${String(task.id === state.selectedTask)}" data-action="select-task" data-task="${esc(task.id)}" type="button"><span class="status-dot ${statusClass(task.status)}"></span>${esc(task.title || task.goal)}</button>
    <button class="tab-close" data-action="close-task" data-task="${esc(task.id)}" type="button" aria-label="Close session tab">x</button>
  </div>`).join("");
}

function approvalRows(approvals) {
  if (!approvals.length) return `<div class="empty-panel">No approvals are waiting.</div>`;
  return approvals.map((approval) => `<div class="approval-row">
    <code>${esc(approval.detail || approval.action)}</code>
    <label class="remember-choice"><input type="checkbox" data-remember="${esc(approval.id)}"> Remember</label>
    <div class="row-actions"><button class="primary-button small" data-action="approval" data-id="${esc(approval.id)}" data-decision="approve" type="button">Approve</button><button class="quiet-button small danger" data-action="approval" data-id="${esc(approval.id)}" data-decision="deny" type="button">Deny</button></div>
  </div>`).join("");
}

function contractPanel(task) {
  const contract = task.contract;
  const profiles = window.COCKPIT?.effortProfiles || {};
  const radio = (name, value, label, checked, disabled) =>
    `<label><input type="radio" name="${name}" value="${value}"${checked ? " checked" : ""}${disabled ? " disabled" : ""}><span>${label}</span></label>`;
  const segmented = (name, values, labelFor, checkedValue, disabled = false) =>
    `<div class="segmented">${values.map((v) => radio(name, v, labelFor(v), v === checkedValue, disabled)).join("")}</div>`;
  const effortLabel = (level) => {
    const ceiling = level === "off" ? 0 : profiles[level];
    return ceiling ? `${EFFORT_LABELS[level]} · ${ceiling}` : EFFORT_LABELS[level];
  };
  const countLabel = (v) => (v === "0" ? "Off" : v === "custom" ? "Custom" : v);
  const typeLabel = (v) => v[0].toUpperCase() + v.slice(1);
  const frameworkLabel = (v) => (v === "none" ? "None" : "AOCS Omega");

  if (!contract) {
    if (["completed", "failed", "cancelled"].includes(task.status)) return "";
    const warning = task.contract_error
      ? `<p><strong>Run Contract integrity error:</strong> ${esc(task.contract_error)}</p>`
      : `<p>This chat-created session has no Run Contract yet.</p>`;
    return `<section class="contract-panel">
      <div class="contract-title"><div><span class="eyebrow">Operator setup</span><strong>${task.contract_error ? "Repair contract" : "Attach run contract"}</strong></div></div>
      ${warning}<div class="contract-setup">
        <fieldset class="contract-row"><legend>TASK TYPE</legend>${segmented("attachTaskType", TASK_TYPES, typeLabel, "build")}</fieldset>
        <fieldset class="contract-row"><legend>EFFORT <small>procedure credits</small></legend>${segmented("attachEffort", EFFORT_LEVELS, effortLabel, "off")}</fieldset>
        <fieldset class="contract-row"><legend>ULTRA WORKFLOW <small>sequential candidates</small></legend>${segmented("attachUltra", ULTRA_OPTIONS, countLabel, "0")}
          <input id="attachUltraCustom" class="attach-custom is-hidden" type="number" min="1" max="${ULTRA_CUSTOM_MAX}" value="10" aria-label="Maximum candidates"></fieldset>
        <fieldset class="contract-row"><legend>FRAMEWORK</legend>${segmented("attachFramework", ["none", "aocs_omega"], frameworkLabel, "none")}</fieldset>
        <fieldset class="contract-row"><legend>LOOPS <small>bounded refinement</small></legend>${segmented("attachLoops", LOOPS_OPTIONS, countLabel, "0")}
          <input id="attachLoopsCustom" class="attach-custom is-hidden" type="number" min="1" max="${LOOPS_CUSTOM_MAX}" value="12" aria-label="Maximum passes"></fieldset>
      </div>
      <div class="contract-estimate" id="attachEstimate">Estimate: no procedure credits</div>
      <p class="contract-warning">Confirming locks this contract permanently — it cannot be edited afterwards.</p>
      <button class="primary-button small" data-action="attach-contract" type="button">${task.contract_error ? "Repair and re-confirm" : "Confirm contract"}</button>
    </section>`;
  }

  // Locked: the SAME pill panel stays on the page permanently, read-only,
  // with live spend/pass meters — the operator sees the running contract at
  // every turn. Values are immutable by design (a contract you can quietly
  // edit isn't a contract); mid-run changes go through request_extension
  // approvals or a fork.
  const spent = task.effort?.spent || 0;
  const ceiling = task.effort?.ceiling || contract.credit_ceiling || 0;
  const percent = ceiling ? Math.min(100, Math.round((spent / ceiling) * 100)) : 0;
  const loops = task.loops || [];
  const countChoice = (options, n) => (n ? (options.includes(String(n)) ? String(n) : "custom") : "0");
  const ultraChoice = countChoice(ULTRA_OPTIONS, contract.candidate_count);
  const loopsChoice = countChoice(LOOPS_OPTIONS, contract.max_loops);
  return `<section class="contract-panel contract-locked">
    <div class="contract-title"><div><span class="eyebrow">Locked run contract</span><strong>${esc(contract.task_type)}</strong></div><code>${esc(String(contract.contract_hash).slice(0, 10))}</code></div>
    <div class="contract-setup">
      <fieldset class="contract-row"><legend>TASK TYPE</legend>${segmented("attachTaskType", TASK_TYPES, typeLabel, contract.task_type, true)}</fieldset>
      <fieldset class="contract-row"><legend>EFFORT <small>${ceiling ? `${spent}/${ceiling} credits spent` : "procedure credits"}</small></legend>
        ${segmented("attachEffort", EFFORT_LEVELS, effortLabel, contract.effort_level, true)}
        ${ceiling ? `<i class="locked-meter" style="--meter:${percent}%"></i>` : ""}</fieldset>
      <fieldset class="contract-row"><legend>ULTRA WORKFLOW <small>sequential candidates</small></legend>
        ${segmented("attachUltra", ULTRA_OPTIONS, countLabel, ultraChoice, true)}
        ${ultraChoice === "custom" ? `<input id="attachUltraCustom" class="attach-custom" type="number" value="${Number(contract.candidate_count)}" disabled aria-label="Maximum candidates">` : ""}</fieldset>
      <fieldset class="contract-row"><legend>FRAMEWORK</legend>${segmented("attachFramework", ["none", "aocs_omega"], frameworkLabel, contract.framework, true)}</fieldset>
      <fieldset class="contract-row"><legend>LOOPS <small>${contract.max_loops ? `${loops.length}/${contract.max_loops} passes used` : "bounded refinement"}</small></legend>
        ${segmented("attachLoops", LOOPS_OPTIONS, countLabel, loopsChoice, true)}
        ${loopsChoice === "custom" ? `<input id="attachLoopsCustom" class="attach-custom" type="number" value="${Number(contract.max_loops)}" disabled aria-label="Maximum passes">` : ""}</fieldset>
    </div>
    <p class="contract-hint">Locked · to change course mid-run, ask ChatGPT for <code>request_extension</code> (more credits/loops, one-shot approval) or fork a new session.</p>
  </section>`;
}

function gatesPanel(task) {
  if (!task.contract || !task.criteria_v2.length) return "";
  return `<section class="task-section"><div class="section-heading"><h2>Acceptance gates</h2><span>${task.criteria_v2.filter((item) => item.status === "satisfied").length}/${task.criteria_v2.length}</span></div>
    <ul class="gate-list">${task.criteria_v2.map((criterion) => `<li><span class="gate-state ${esc(criterion.status)}">${esc(criterion.status)}</span><div><strong>${esc(criterion.id)} · ${esc(criterion.text)}</strong><small>${esc(criterion.verification_kind)}${criterion.verified_at ? ` · ${esc(criterion.verified_at)}` : ""}</small>${criterion.evidence_refs?.length ? `<details><summary>Validated evidence</summary><pre>${esc(JSON.stringify(criterion.evidence_refs, null, 2))}</pre></details>` : ""}</div>${criterion.verification_kind === "operator" && criterion.status === "open" ? `<button class="quiet-button small" data-action="confirm-criterion" data-criterion="${esc(criterion.id)}" type="button">Confirm</button>` : ""}</li>`).join("")}</ul>
  </section>`;
}

function auditPanel(task) {
  if (!task.contract) return "";
  const receipts = task.receipts || [];
  const loops = task.loops || [];
  return `<section class="task-section audit-grid">
    <div><div class="section-heading"><h2>Receipts</h2><span>${receipts.length}</span></div>${receipts.length ? `<ul class="compact-list">${receipts.slice(-5).reverse().map((receipt) => `<li><details><summary><code>${esc(receipt.cycle_id)}</code> · ${esc(receipt.tier)}</summary><p><strong>Conclusion:</strong> ${esc(receipt.conclusion)}</p><p><strong>Decision:</strong> ${esc(receipt.decision)}</p><pre>${esc(JSON.stringify(receipt.evidence_refs || [], null, 2))}</pre></details></li>`).join("")}</ul>` : `<p>No credits spent.</p>`}</div>
    <div><div class="section-heading"><h2>Refinement</h2><span>${loops.length}</span></div>${loops.length ? `<ul class="compact-list">${loops.slice(-5).reverse().map((loop) => `<li class="loop-row"><span><code>${esc(loop.pass_id)}</code> · ${esc(loop.status)}<small>Outcome: ${esc(loop.proposed_outcome || loop.status)} · Weakness: ${esc(loop.target_weakness)} · Directive: ${esc(loop.directive)} · Delta: ${esc(loop.delta_summary || "none")}</small></span>${loop.status === "pending_operator" ? `<button class="quiet-button small" data-action="confirm-loop" data-pass="${esc(loop.pass_id)}" type="button">Confirm</button>` : ""}</li>`).join("")}</ul>` : `<p>No passes run.</p>`}</div>
  </section>`;
}

function workspace(state) {
  const task = state.data.tasks.find((item) => item.id === state.selectedTask);
  const project = state.data.projects.find((item) => item.id === (task?.project_id || state.selectedProject));
  if (!task) return `<div class="welcome">
    <div class="welcome-mark" aria-hidden="true">H</div><h1>What should we work on?</h1>
    <p>${project ? `Start a session in ${esc(project.name)}.` : "Choose or add a project to begin."}</p>
    <button class="primary-button" data-action="new-session" ${project ? "" : "disabled"} type="button">New session</button>
  </div>`;

  const prompt = `Resume harness task ${task.id}. Pass task_id="${task.id}" to every tool call.\nGoal: ${task.goal}`;
  const approvals = state.data.approvals.filter((item) => item.task_id === task.id);
  return `<div class="workspace-scroll">
    ${approvals.length ? `<section class="attention-banner"><strong>${approvals.length} action${approvals.length === 1 ? "" : "s"} need approval</strong><button class="text-button" data-action="inspector-tab" data-tab="approvals" type="button">Review</button></section>` : ""}
    <header class="task-header">
      <div><p class="breadcrumb">${esc(project?.name || "Project")}${task.parent_id ? " / fork" : ""}</p><h1>${esc(task.title || task.goal)}</h1></div>
      <div class="task-actions"><select id="modeSelect" class="mode-select" aria-label="Permission mode">${state.data.modes.map((mode) => `<option value="${esc(mode)}" ${mode === task.mode ? "selected" : ""}>${esc(mode)}</option>`).join("")}</select><button class="quiet-button" data-action="fork" type="button">Fork</button><button class="primary-button" data-action="open-chat" type="button">Open ChatGPT</button></div>
    </header>
    ${contractPanel(task)}
    <section class="resume-panel">
      <div class="eyebrow">Resume in ChatGPT</div>
      <textarea id="resumePrompt" readonly>${esc(prompt)}</textarea>
      <div class="row-actions"><button class="primary-button small" data-action="copy-prompt" type="button">Copy prompt</button><button class="quiet-button small" data-action="open-chat" type="button">Open ChatGPT</button></div>
    </section>
    <section class="details-grid">
      <div><span>State</span><strong class="state-chip ${statusClass(task.status)}">${esc(task.status)}</strong></div>
      <div><span>Isolation</span><strong>${task.worktree_path ? "Isolated worktree" : "Shared checkout"}</strong></div>
      <div><span>Changes</span><strong>${task.changed_files.length} files</strong></div>
      <div><span>Tests</span><strong>${task.test_results.length} runs</strong></div>
    </section>
    ${gatesPanel(task)}
    ${auditPanel(task)}
    <section class="task-section"><h2>Goal</h2><p>${esc(task.goal)}</p></section>
    <section class="task-section"><h2>Working path</h2><code class="path-code">${esc(task.worktree_path || task.workspace_path)}</code></section>
    ${task.checkpoints.length ? `<section class="task-section"><div class="section-heading"><h2>Checkpoints</h2><span>${task.checkpoints.length}</span></div>
      <ul class="compact-list">${task.checkpoints.slice(-8).reverse().map((checkpoint) => `<li class="checkpoint-row"><code>${esc(checkpoint)}</code><button class="quiet-button small" data-action="restore-checkpoint" data-checkpoint="${esc(checkpoint)}" type="button">Restore</button></li>`).join("")}</ul>
    </section>` : ""}
    <section class="task-section"><div class="section-heading"><h2>Attachments</h2><span>${task.pinned_files.length}</span></div>
      <div class="dropzone" id="dropzone">Drop files here to attach them to this session</div>
      ${task.pinned_files.length ? `<ul class="compact-list">${task.pinned_files.map((file) => `<li>${esc(file)}</li>`).join("")}</ul>` : ""}
    </section>
  </div>`;
}

function eventRows(events) {
  if (!events.length) return `<div class="empty-panel">No activity yet.</div>`;
  return `<div class="activity-list">${[...events].reverse().map((event) => `<div class="activity-row">
    <span class="activity-time">${esc((event.time || "").slice(11, 19))}</span>
    <span class="activity-type">${esc(event.tool || event.type || "event")}</span>
    <span class="activity-detail">${esc(event.detail || event.text || event.command || event.mode || "")}</span>
  </div>`).join("")}</div>`;
}

function terminalView(task, events) {
  const commands = task?.commands || [];
  const liveCommands = events.filter((event) => event.tool === "run_command" || event.command);
  const tests = task?.test_results || [];
  if (!commands.length && !liveCommands.length && !tests.length) return `<div class="terminal-empty"><span>&gt;_</span><p>Command and test output will appear here. Execution stays governed by the harness permission layer.</p></div>`;
  return `<div class="terminal-view"><div class="terminal-title">SESSION TELEMETRY / READ ONLY</div>
    ${commands.map((entry) => `<div class="command-line"><span><span class="prompt">$</span> ${esc(entry.command || "run_command")}</span><span class="exit-code ${entry.exit === 0 ? "passed" : "failed"}">exit ${esc(entry.exit ?? "?")}</span></div>`).join("")}
    ${liveCommands.filter((event) => !commands.some((entry) => entry.command === (event.detail || event.command))).map((event) => `<div class="command-line"><span><span class="prompt">$</span> ${esc(event.detail || event.command || "run_command")}</span><span class="exit-code">running</span></div>`).join("")}
    ${tests.map((test) => `<div class="test-line ${test.passed ? "passed" : "failed"}">${test.passed ? "PASS" : "FAIL"} ${esc(test.command || "test")}</div>`).join("")}</div>`;
}

function fileInventory(task, files) {
  const rows = [];
  const seen = new Set();
  const add = (name, kind, dir = false) => {
    const key = String(name).replaceAll("\\", "/").toLowerCase();
    if (!name || seen.has(key)) return;
    seen.add(key); rows.push({ name, kind, dir });
  };
  task.pinned_files.forEach((name) => add(name, "PIN"));
  task.changed_files.forEach((name) => add(name, "CHG"));
  (files || []).forEach((file) => add(file.name, file.dir ? "DIR" : "FILE", file.dir));
  return rows;
}

function inspector(state) {
  const task = state.data.tasks.find((item) => item.id === state.selectedTask);
  const approvals = state.data.approvals.filter((item) => !task || item.task_id === task.id);
  const events = task ? (state.taskEvents.get(task.id) || []) : [];
  const tabs = INSPECTOR_TABS.map(([id, label]) => `<button class="inspector-tab ${state.inspectorTab === id ? "active" : ""}" role="tab" aria-selected="${String(state.inspectorTab === id)}" data-action="inspector-tab" data-tab="${id}" type="button">${label}${id === "approvals" && approvals.length ? `<span>${approvals.length}</span>` : ""}</button>`).join("");
  if (!task && state.inspectorTab !== "approvals") return { tabs, body: `<div class="empty-panel">Open a session to inspect its work.</div>` };
  let body = "";
  if (state.inspectorTab === "activity") body = eventRows(events);
  if (state.inspectorTab === "changes") body = `<pre class="diff-view">${esc(task ? (state.taskDiffs.get(task.id) ?? "Loading changes...") : "")}</pre>`;
  if (state.inspectorTab === "terminal") body = terminalView(task, events);
  if (state.inspectorTab === "files") {
    const files = task ? state.taskFiles.get(task.id) : [];
    const inventory = files === undefined ? undefined : fileInventory(task, files);
    body = inventory === undefined ? `<div class="empty-panel">Loading files...</div>` : `<div class="file-tree">${inventory.map((file) => `<div class="file-row"><span class="file-kind ${file.kind.toLowerCase()}">${file.kind}</span><span>${esc(file.name)}</span></div>`).join("") || `<div class="empty-panel">No files found.</div>`}</div>`;
  }
  if (state.inspectorTab === "approvals") body = approvalRows(approvals);
  return { tabs, body };
}

export function mountRenderer(store, actions) {
  const tree = document.getElementById("tree");
  const tabs = document.getElementById("sessionTabs");
  const workspaceEl = document.getElementById("workspace");
  const inspectorTabs = document.getElementById("inspectorTabs");
  const inspectorBody = document.getElementById("inspectorBody");
  let previousSelectedTask = null;

  const render = (state) => {
    const previousWorkspaceScroll = previousSelectedTask === state.selectedTask
      ? (workspaceEl.querySelector(".workspace-scroll")?.scrollTop || 0)
      : 0;
    tree.innerHTML = projectTree(state);
    tabs.innerHTML = sessionTabs(state);
    workspaceEl.innerHTML = workspace(state);
    const workspaceScroll = workspaceEl.querySelector(".workspace-scroll");
    if (workspaceScroll) workspaceScroll.scrollTop = previousWorkspaceScroll;
    previousSelectedTask = state.selectedTask;
    const right = inspector(state);
    inspectorTabs.innerHTML = right.tabs;
    inspectorBody.innerHTML = right.body;
    const engine = state.data.engine || "unknown";
    document.getElementById("engineStatus").className = `engine-status ${esc(engine)}`;
    document.getElementById("engineText").textContent = `Engine ${engine}`;
    const count = state.data.approvals.length;
    document.getElementById("needsCount").textContent = String(count);
    document.getElementById("needsPill").classList.toggle("is-hidden", count === 0);
    actions.wireDropzone(workspaceEl.querySelector("#dropzone"));
  };

  document.getElementById("workbench").addEventListener("click", async (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    const action = control.dataset.action;
    if (action === "select-project") store.selectProject(control.dataset.project);
    if (action === "toggle-project") store.toggleProject(control.dataset.project);
    if (action === "select-task") store.selectTask(control.dataset.task);
    if (action === "close-task") store.closeTask(control.dataset.task);
    if (action === "inspector-tab") store.setInspectorTab(control.dataset.tab);
    if (action === "new-session") actions.openNewTask(control.dataset.project);
    if (action === "add-project") actions.addProject();
    if (action === "pin-project") await actions.pinProject(control.dataset.project, control.dataset.pinned === "true");
    if (action === "pin-task") await actions.pinTask(control.dataset.task, control.dataset.pinned === "true");
    if (action === "fork") await actions.fork();
    if (action === "open-chat") actions.openChat();
    if (action === "copy-prompt") actions.copyPrompt();
    if (action === "restore-checkpoint") await actions.restoreCheckpoint(control.dataset.checkpoint);
    if (action === "approval") await actions.decideApproval(control.dataset.id, control.dataset.decision);
    if (action === "confirm-criterion") await actions.confirmCriterion(control.dataset.criterion);
    if (action === "confirm-loop") await actions.confirmLoop(control.dataset.pass);
    if (action === "attach-contract") await actions.attachContract();
  });
  document.getElementById("sidebarSearch").addEventListener("input", (event) => store.setSearch(event.target.value));
  workspaceEl.addEventListener("change", (event) => { if (event.target.id === "modeSelect") actions.setMode(event.target.value); });
  return { render };
}
