import { getJSON, postJSON } from "./api.mjs?v=21";
import { initResizableLayout } from "./layout.mjs?v=21";
import { mountRenderer } from "./render.mjs?v=21";
import { createStore } from "./state.mjs?v=21";
import {
  EFFORT_LABELS, ULTRA_CUSTOM_MAX, LOOPS_CUSTOM_MAX,
  boundedCount, contractEstimate,
} from "./contract-options.mjs?v=21";
import {
  settleContractMotion, playContractMotion, refreshCustomCounts, playLaunch,
} from "./contract-motion.mjs?v=21";

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
  settleContractMotion(document.getElementById("newTaskDlg"));  // icons first (widths settle)
  wireSegmented(document.getElementById("newTaskDlg"));         // then position thumbs
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
    const custom = (id) => document.getElementById(id)?.value;
    const button = document.querySelector('[data-action="attach-contract"]');
    // The energy-transfer animation runs alongside the API call; the REAL
    // result decides success/fail — never the animation.
    const fx = button ? playLaunch(button.closest(".contract-panel"), button) : null;
    try {
      await postJSON("/api/task/contract", {
        task_id: task.id, task_type: checkedValue("attachTaskType") || "build",
        effort_level: checkedValue("attachEffort") || "off",
        candidate_count: boundedCount(checkedValue("attachUltra") || "0", custom("attachUltraCustom"), ULTRA_CUSTOM_MAX),
        machine_concurrency: window.COCKPIT.machineConcurrency,
        framework: checkedValue("attachFramework") || "none",
        max_loops: boundedCount(checkedValue("attachLoops") || "0", custom("attachLoopsCustom"), LOOPS_CUSTOM_MAX),
      });
      await fx?.success("Contract locked ✓");
      toast(task.contract_error ? "Run Contract repaired" : "Run Contract confirmed");
      await refresh();
    } catch (error) { fx?.fail(); toast(error.message, true); }
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
store.subscribe((state) => {
  // Never chop the contract-lock cinematic mid-flight: skip this rebuild and
  // let the explicit refresh() after success (or the next poll) render. The
  // 8s watchdog means a hung confirm request can never freeze the workspace.
  const launching = document.querySelector(".fx-launching");
  if (launching && Date.now() - Number(launching.dataset.fxLaunchStart || 0) < 8000) {
    void loadTaskData(state);
    return;
  }
  // Live events re-render the workspace; without capture/restore that would
  // silently reset the operator's un-confirmed contract choices to Off.
  const saved = captureAttachChoices();
  renderer.render(state);
  restoreAttachChoices(saved);
  settleContractMotion();   // rehydrate settled visuals (may grow labels via icons)
  wireSegmented();          // then measure + position thumbs against final widths
  updateAttachEstimate();
  void loadTaskData(state);
});
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
const concurrency = {
  modelStreams: window.COCKPIT.modelConcurrency,
  machineParallel: window.COCKPIT.machineConcurrency,
};
const selectedContractValue = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value || "";
function contractCount(name, customId, maximum) {
  return boundedCount(selectedContractValue(name) || "0",
    document.getElementById(customId)?.value, maximum);
}
function updateContractEstimate() {
  const effort = selectedContractValue("ntEffort") || "off";
  animateEstimate(document.getElementById("ntEstimate"), contractEstimate({
    ceiling: effortCeilings[effort],
    candidates: contractCount("ntUltra", "ntUltraCustom", ULTRA_CUSTOM_MAX),
    loops: contractCount("ntLoops", "ntLoopsCustom", LOOPS_CUSTOM_MAX),
    ...concurrency,
  }));
}
// The New Session dialog's static EFFORT labels carry the ceiling numbers;
// sync them from the server-configured profiles so they can never lie.
function syncDialogEffortLabels() {
  for (const input of document.querySelectorAll('input[name="ntEffort"]')) {
    const ceiling = input.value === "off" ? 0 : effortCeilings[input.value];
    const span = input.nextElementSibling;
    if (span) span.textContent = ceiling ? `${EFFORT_LABELS[input.value]} · ${ceiling}` : EFFORT_LABELS[input.value];
  }
}
syncDialogEffortLabels();
document.getElementById("newTaskDlg").addEventListener("change", updateContractEstimate);

// ---- attach-contract panel (chat-created sessions) ----
// The panel is re-rendered HTML, so wire it by delegation and refresh the
// estimate after every render.
function checkedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value || "";
}
function captureAttachChoices() {
  if (!document.getElementById("attachEstimate")) return null;
  return {
    taskId: store.state.selectedTask,
    radios: Object.fromEntries(["attachTaskType", "attachEffort", "attachUltra", "attachFramework", "attachLoops"]
      .map((name) => [name, checkedValue(name)])),
    ultraCustom: document.getElementById("attachUltraCustom")?.value,
    loopsCustom: document.getElementById("attachLoopsCustom")?.value,
  };
}
function restoreAttachChoices(saved) {
  if (!saved || !document.getElementById("attachEstimate")) return;
  if (saved.taskId !== store.state.selectedTask) return;  // never leak picks across sessions
  for (const [name, value] of Object.entries(saved.radios)) {
    const input = value && document.querySelector(`input[name="${name}"][value="${CSS.escape(value)}"]`);
    if (input) input.checked = true;
  }
  if (saved.ultraCustom) document.getElementById("attachUltraCustom").value = saved.ultraCustom;
  if (saved.loopsCustom) document.getElementById("attachLoopsCustom").value = saved.loopsCustom;
}
function updateAttachEstimate() {
  const estimate = document.getElementById("attachEstimate");
  if (!estimate) return;
  const custom = (id) => document.getElementById(id)?.value;
  for (const [name, customId] of [["attachUltra", "attachUltraCustom"], ["attachLoops", "attachLoopsCustom"]]) {
    document.getElementById(customId)?.classList.toggle("is-hidden", checkedValue(name) !== "custom");
  }
  animateEstimate(estimate, contractEstimate({
    ceiling: effortCeilings[checkedValue("attachEffort") || "off"],
    candidates: boundedCount(checkedValue("attachUltra") || "0", custom("attachUltraCustom"), ULTRA_CUSTOM_MAX),
    loops: boundedCount(checkedValue("attachLoops") || "0", custom("attachLoopsCustom"), LOOPS_CUSTOM_MAX),
    ...concurrency,
  }));
}

// ---- motion: sliding segmented thumb + credit count-up -------------------
// One physical thumb glides between pills (the "model picker" feel). Pure
// enhancement: without JS the checked-pill CSS styling still works.
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function positionThumb(group) {
  const thumb = group.querySelector(".seg-thumb");
  const label = group.querySelector("input:checked")?.closest("label");
  if (!thumb) return;
  if (!label || !label.offsetWidth) { thumb.style.opacity = "0"; return; }
  thumb.style.opacity = "1";
  thumb.style.width = `${label.offsetWidth}px`;
  thumb.style.height = `${label.offsetHeight}px`;
  thumb.style.transform = `translate(${label.offsetLeft}px, ${label.offsetTop}px)`;
}
function wireSegmented(root = document) {
  for (const group of root.querySelectorAll(".segmented")) {
    if (!group.querySelector(".seg-thumb")) {
      const thumb = document.createElement("i");
      thumb.className = "seg-thumb";
      thumb.setAttribute("aria-hidden", "true");
      group.prepend(thumb);
      group.classList.add("has-thumb");
    }
    positionThumb(group);
  }
}
// Estimate count-up state lives at MODULE level, keyed by element id, so it
// survives the innerHTML rebuilds that replace the element itself. That is
// what prevents (a) replaying the count-up on every rerender, (b) overlapping
// loops fighting over the text, (c) counting up from 0 after each rebuild.
const estimateState = {};
function animateEstimate(element, text) {
  const state = estimateState[element.id] || (estimateState[element.id] = { text: "", total: 0, token: 0 });
  const next = Number(text.match(/≤ (\d+)/)?.[1] || 0);
  const token = ++state.token;             // supersedes any in-flight count-up
  const previous = state.total;
  const unchanged = state.text === text;
  state.text = text;
  state.total = next;
  if (unchanged || !next || previous === next || reducedMotion()) { element.textContent = text; return; }
  const start = performance.now();
  const step = (now) => {
    if (!element.isConnected || state.token !== token) return;
    const t = Math.min(1, (now - start) / 340);
    const eased = 1 - (1 - t) ** 3;
    element.textContent = text.replace(`≤ ${next}`, `≤ ${Math.round(previous + (next - previous) * eased)}`);
    if (t < 1) requestAnimationFrame(step); else element.textContent = text;
  };
  requestAnimationFrame(step);
  element.classList.remove("pop");
  void element.offsetWidth;
  element.classList.add("pop");
}
document.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.matches(".segmented input")) {
    positionThumb(target.closest(".segmented"));
    playContractMotion(target);
  }
  refreshCustomCounts(target);
  if ((target.getAttribute("name") || target.id || "").startsWith("attach")) updateAttachEstimate();
});
window.addEventListener("resize", () => {
  for (const group of document.querySelectorAll(".segmented")) positionThumb(group);
  settleContractMotion();
});
wireSegmented();
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
  // Energy transfer plays alongside the request; the REAL result decides.
  const fx = playLaunch(document.querySelector("#newTaskDlg form"), event.currentTarget);
  try {
    const result = await postJSON("/api/task/new", {
      project_path: project.path, goal, mode, isolation, effort_level,
      credit_ceiling: effortCeilings[effort_level], candidate_count,
      machine_concurrency: window.COCKPIT.machineConcurrency, framework, max_loops, task_type,
    });
    await fx.success("Contract locked ✓");
    document.getElementById("newTaskDlg").close();
    document.getElementById("ntGoal").value = "";
    await refresh();
    if (result.task_id) store.selectTask(result.task_id);
    toast(result.needs_approval ? "Session needs approval" : "Session created");
  } catch (error) { fx.fail(); toast(error.message, true); }
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
