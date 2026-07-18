import { getJSON, postJSON } from "./api.mjs?v=17";
import { initResizableLayout } from "./layout.mjs?v=17";
import { mountRenderer } from "./render.mjs?v=17";
import { createStore } from "./state.mjs?v=17";

const store = createStore();
const loadingEvents = new Set();
const loadingDiffs = new Set();
const loadingFiles = new Set();
let refreshTimer = null;

function toast(message, isError = false) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.className = "toast"; }, 2800);
}

function currentTask() {
  return store.state.data.tasks.find((task) => task.id === store.state.selectedTask);
}

async function refresh() {
  try {
    const [state, approvals] = await Promise.all([getJSON("/api/state"), getJSON("/api/approvals")]);
    store.hydrate({ ...state, approvals: approvals.approvals });
  } catch (error) { toast(`Refresh failed: ${error.message}`, true); }
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 700);
}

async function loadTaskData(state) {
  const id = state.selectedTask;
  if (!id) return;
  if (!state.taskEvents.has(id) && !loadingEvents.has(id)) {
    loadingEvents.add(id);
    try {
      const result = await getJSON(`/api/task/events?task_id=${encodeURIComponent(id)}&limit=200`);
      store.setEvents(id, result.events);
    } catch (error) { toast(`Activity failed: ${error.message}`, true); }
    finally { loadingEvents.delete(id); }
  }
  if (state.inspectorTab === "changes" && !state.taskDiffs.has(id) && !loadingDiffs.has(id)) {
    loadingDiffs.add(id);
    try {
      const result = await getJSON(`/api/diff?task_id=${encodeURIComponent(id)}`);
      store.setDiff(id, result.diff || "No changes");
    } catch (error) { store.setDiff(id, `Unable to load changes: ${error.message}`); }
    finally { loadingDiffs.delete(id); }
  }
  if (state.inspectorTab === "files" && !state.taskFiles.has(id) && !loadingFiles.has(id)) {
    loadingFiles.add(id);
    const task = currentTask();
    try {
      const result = await getJSON(`/api/files?path=${encodeURIComponent(task.workspace_path)}`);
      store.setFiles(id, result.entries);
    } catch (error) { store.setFiles(id, []); toast(`Files failed: ${error.message}`, true); }
    finally { loadingFiles.delete(id); }
  }
}

function openNewTask(projectId) {
  if (projectId) store.selectProject(projectId);
  const project = store.state.data.projects.find((item) => item.id === store.state.selectedProject);
  if (!project) { toast("Choose a project first", true); return; }
  document.getElementById("ntProjName").textContent = `In ${project.name}`;
  updateContractEstimate();
  document.getElementById("newTaskDlg").showModal();
}

async function addProject() {
  try {
    const picked = await postJSON("/api/pick_folder");
    if (!picked.path) return;
    const result = await postJSON("/api/root/add", { path: picked.path });
    try {
      await postJSON("/api/project/create", { path: picked.path });
    } catch (error) {
      toast(`Folder approved as a root, but registering failed: ${error.message} — restart the harness and click Add again.`, true);
      return;
    }
    toast("Project added");
    if (result.needs_restart) await restartEngine();
    await refresh();
  } catch (error) { toast(error.message, true); }
}

async function restartEngine() {
  try {
    let result = await postJSON("/api/engine/restart");
    if (result.needs_confirm) {
      const active = result.busy?.active_tasks?.join(", ") || "active sessions";
      if (!window.confirm(`Restart will interrupt ${active}. Continue?`)) return;
      result = await postJSON("/api/engine/restart", { force: true });
    }
    toast("Engine restarted and ready");
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

const actions = {
  openNewTask,
  addProject,
  async pinProject(projectId, pinned) {
    try { await postJSON("/api/project/pinned", { project_id: projectId, pinned }); await refresh(); }
    catch (error) { toast(error.message, true); }
  },
  async pinTask(taskId, pinned) {
    try { await postJSON("/api/task/pinned", { task_id: taskId, pinned }); await refresh(); }
    catch (error) { toast(error.message, true); }
  },
  async fork() {
    const task = currentTask(); if (!task) return;
    try { await postJSON("/api/task/fork", { task_id: task.id }); toast("Session forked"); await refresh(); }
    catch (error) { toast(error.message, true); }
  },
  openChat() {
    const task = currentTask();
    window.open(task?.chat_url || "https://chatgpt.com/", "_blank", "noopener,noreferrer");
  },
  async copyPrompt() {
    const prompt = document.getElementById("resumePrompt")?.value || "";
    try { await navigator.clipboard.writeText(prompt); toast("Resume prompt copied"); }
    catch { toast("Clipboard access was blocked", true); }
  },
  async setMode(mode) {
    const task = currentTask(); if (!task) return;
    try { await postJSON("/api/task/mode", { task_id: task.id, mode }); toast(`Mode set to ${mode}`); await refresh(); }
    catch (error) { toast(error.message, true); }
  },
  async restoreCheckpoint(checkpointId) {
    const task = currentTask(); if (!task) return;
    try {
      await postJSON("/api/restore", { task_id: task.id, checkpoint_id: checkpointId });
      toast(`Restored ${checkpointId}`);
      store.state.taskDiffs.delete(task.id);
      await refresh();
    } catch (error) { toast(error.message, true); }
  },
  async decideApproval(id, decision) {
    const remember = document.querySelector(`[data-remember="${CSS.escape(id)}"]`)?.checked || false;
    try { await postJSON("/api/approval/decide", { id, decision, remember }); toast(decision === "approve" ? "Approved" : "Denied"); await refresh(); }
    catch (error) { toast(error.message, true); }
  },
  async confirmCriterion(criterionId) {
    const task = currentTask(); if (!task) return;
    try {
      await postJSON("/api/task/criterion/operator-satisfy", { task_id: task.id, criterion_id: criterionId });
      toast("Criterion confirmed"); await refresh();
    } catch (error) { toast(error.message, true); }
  },
  async confirmLoop(passId) {
    const task = currentTask(); if (!task) return;
    try {
      await postJSON("/api/task/loop/operator-confirm", { task_id: task.id, pass_id: passId });
      toast("Refinement pass confirmed"); await refresh();
    } catch (error) { toast(error.message, true); }
  },
  async attachContract() {
    const task = currentTask(); if (!task) return;
    const value = (id) => document.getElementById(id)?.value || "";
    try {
      await postJSON("/api/task/contract", {
        task_id: task.id, task_type: value("attachTaskType") || "build",
        effort_level: value("attachEffort") || "off",
        candidate_count: Number(value("attachUltra") || 0),
        machine_concurrency: window.COCKPIT.machineConcurrency,
        framework: value("attachFramework") || "none",
        max_loops: Number(value("attachLoops") || 0),
      });
      toast(task.contract_error ? "Run Contract repaired" : "Run Contract confirmed");
      await refresh();
    } catch (error) { toast(error.message, true); }
  },
  wireDropzone(zone) {
    if (!zone) return;
    zone.ondragover = (event) => { event.preventDefault(); zone.classList.add("over"); };
    zone.ondragleave = () => zone.classList.remove("over");
    zone.ondrop = async (event) => {
      event.preventDefault(); zone.classList.remove("over");
      const task = currentTask(); if (!task) return;
      for (const file of event.dataTransfer.files) {
        try {
          await postJSON("/api/task/upload", { task_id: task.id, name: file.name, b64: await fileAsBase64(file) });
          toast(`Attached ${file.name}`);
        } catch (error) { toast(error.message, true); }
      }
      await refresh();
    };
  },
};

const renderer = mountRenderer(store, actions);
store.subscribe((state) => { renderer.render(state); void loadTaskData(state); });
initResizableLayout();

document.getElementById("newSession").addEventListener("click", () => openNewTask());
document.getElementById("addProject").addEventListener("click", addProject);
document.getElementById("addProjectTop").addEventListener("click", addProject);
document.getElementById("restart").addEventListener("click", restartEngine);
document.getElementById("needsPill").addEventListener("click", () => store.setInspectorTab("approvals"));
document.getElementById("themeToggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("cockpit-theme", theme);
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault(); document.getElementById("sidebarSearch").focus();
  }
});

const effortCeilings = { off: 0, ...(window.COCKPIT.effortProfiles || {}) };
const selectedContractValue = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value || "";
function contractCount(name, customId, maximum) {
  const selected = selectedContractValue(name) || "0";
  if (selected !== "custom") return Number(selected);
  const raw = Number(document.getElementById(customId)?.value || 1);
  return Math.max(1, Math.min(maximum, Math.trunc(raw)));
}
function updateContractEstimate() {
  const effort = selectedContractValue("ntEffort") || "off";
  const candidates = contractCount("ntUltra", "ntUltraCustom", 64);
  const loops = contractCount("ntLoops", "ntLoopsCustom", 100);
  const total = effortCeilings[effort] * (1 + candidates) * (1 + loops);
  const nudge = total > 30 ? " · expect several continue nudges" : "";
  document.getElementById("ntEstimate").textContent = total
    ? `Estimate: ≤ ${total} procedure credits · model streams 1 · machine parallel 2${nudge}`
    : `Estimate: no procedure credits · model streams 1 · machine parallel 2${nudge}`;
  const estimate = document.getElementById("ntEstimate");
  estimate.textContent = estimate.textContent
    .replace("model streams 1", `model streams ${window.COCKPIT.modelConcurrency}`)
    .replace("machine parallel 2", `machine parallel ${window.COCKPIT.machineConcurrency}`);
}
document.getElementById("newTaskDlg").addEventListener("change", updateContractEstimate);
document.getElementById("ntCreate").addEventListener("click", async (event) => {
  event.preventDefault();
  const project = store.state.data.projects.find((item) => item.id === store.state.selectedProject);
  const goal = document.getElementById("ntGoal").value.trim();
  const mode = document.getElementById("ntMode").value;
  const isoEl = document.getElementById("ntIsolation");
  const isolation = isoEl ? isoEl.value : "";  // "" => server's configured default
  const effort_level = selectedContractValue("ntEffort") || "off";
  const candidate_count = contractCount("ntUltra", "ntUltraCustom", 64);
  const framework = selectedContractValue("ntFramework") || "none";
  const max_loops = contractCount("ntLoops", "ntLoopsCustom", 100);
  const task_type = selectedContractValue("ntTaskType") || "build";
  if (!project || !goal) { toast("Choose a project and enter a goal", true); return; }
  try {
    const result = await postJSON("/api/task/new", {
      project_path: project.path, goal, mode, isolation, effort_level,
      credit_ceiling: effortCeilings[effort_level], candidate_count,
      machine_concurrency: window.COCKPIT.machineConcurrency, framework, max_loops, task_type,
    });
    document.getElementById("newTaskDlg").close();
    document.getElementById("ntGoal").value = "";
    await refresh();
    if (result.task_id) store.selectTask(result.task_id);
    toast(result.needs_approval ? "Session needs approval" : "Session created");
  } catch (error) { toast(error.message, true); }
});

const eventSource = new EventSource("/events");
eventSource.addEventListener("tool_call", (event) => {
  try {
    const payload = JSON.parse(event.data);
    store.appendEvent({ event_id: `live:${payload.event_id}`, task_id: payload.task_id, time: payload.time, type: payload.type, ...(payload.data || {}) });
    scheduleRefresh();
  } catch { /* malformed engine telemetry is ignored */ }
});

await refresh();
setInterval(refresh, 5000);
