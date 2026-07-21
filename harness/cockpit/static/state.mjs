const OPEN_TABS_KEY = "harness.open-tabs.v1";
const INSPECTOR_TAB_KEY = "harness.inspector-tab.v1";

function storedJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}

export function mergeTaskEvents(existing, incoming) {
  const merged = new Map();
  for (const event of [...existing, ...incoming]) {
    const key = event.event_id || `${event.time || ""}|${event.type || ""}|${JSON.stringify(event)}`;
    merged.set(key, event);
  }
  return [...merged.values()]
    .sort((a, b) => (a.time || "").localeCompare(b.time || ""))
    .slice(-400);
}

// Same ordering the sidebar renders with (render.mjs sortProjectsByActivity):
// pinned first, then most recent task activity, then name.
export function defaultProjectId(projects, tasks) {
  const updatedAt = (project) => tasks.reduce(
    (latest, task) => (task.project_id === project.id && (task.updated || "") > latest ? task.updated : latest),
    project.created || "");
  return [...projects].sort((a, b) => Number(b.pinned) - Number(a.pinned)
    || updatedAt(b).localeCompare(updatedAt(a))
    || a.name.localeCompare(b.name))[0]?.id || null;
}

export function createStore() {
  const listeners = new Set();
  const state = {
    data: { projects: [], tasks: [], approvals: [], roots: [], modes: [] },
    selectedProject: null,
    selectedTask: null,
    openTabs: storedJSON(OPEN_TABS_KEY, []),
    inspectorTab: localStorage.getItem(INSPECTOR_TAB_KEY) || "activity",
    search: "",
    showArchived: false,
    collapsedProjects: new Set(),
    taskEvents: new Map(),
    taskDiffs: new Map(),
    taskFiles: new Map(),
  };

  const emit = () => listeners.forEach((listener) => listener(state));
  const persistTabs = () => localStorage.setItem(OPEN_TABS_KEY, JSON.stringify(state.openTabs));

  return {
    state,
    subscribe(listener) { listeners.add(listener); listener(state); return () => listeners.delete(listener); },
    hydrate(data) {
      const validTasks = new Set(data.tasks.map((task) => task.id));
      state.data = data;
      state.openTabs = state.openTabs.filter((id) => validTasks.has(id));
      if (state.selectedTask && !validTasks.has(state.selectedTask)) state.selectedTask = null;
      if (!state.selectedTask && state.openTabs.length) {
        state.selectedTask = state.openTabs[state.openTabs.length - 1];
        state.selectedProject = data.tasks.find((task) => task.id === state.selectedTask)?.project_id || null;
      }
      // Default to the project the operator actually sees at the top of the
      // sidebar (pinned, then most recently active) — NOT data.projects[0],
      // which is the oldest folder ever added. New Session names its target
      // but offers no picker, so a stale default silently starts work (and
      // writes files) in the wrong folder.
      if (!state.selectedProject && data.projects.length) {
        state.selectedProject = defaultProjectId(data.projects, data.tasks);
      }
      persistTabs(); emit();
    },
    selectProject(id) { state.selectedProject = id; emit(); },
    selectTask(id) {
      const task = state.data.tasks.find((item) => item.id === id);
      if (!task) return;
      state.selectedTask = id;
      state.selectedProject = task.project_id;
      state.openTabs = [...state.openTabs.filter((tab) => tab !== id), id];
      persistTabs(); emit();
    },
    closeTask(id) {
      const index = state.openTabs.indexOf(id);
      state.openTabs = state.openTabs.filter((tab) => tab !== id);
      if (state.selectedTask === id) {
        state.selectedTask = state.openTabs[Math.min(index, state.openTabs.length - 1)] || null;
      }
      persistTabs(); emit();
    },
    setInspectorTab(tab) { state.inspectorTab = tab; localStorage.setItem(INSPECTOR_TAB_KEY, tab); emit(); },
    setSearch(value) { state.search = value; emit(); },
    toggleArchived() { state.showArchived = !state.showArchived; emit(); },
    toggleProject(id) {
      state.collapsedProjects.has(id) ? state.collapsedProjects.delete(id) : state.collapsedProjects.add(id);
      emit();
    },
    setEvents(id, events) {
      state.taskEvents.set(id, mergeTaskEvents(state.taskEvents.get(id) || [], events));
      emit();
    },
    appendEvent(event) {
      if (!event.task_id) return;
      const events = mergeTaskEvents(state.taskEvents.get(event.task_id) || [], [event]);
      state.taskEvents.set(event.task_id, events);
      emit();
    },
    setDiff(id, diff) { state.taskDiffs.set(id, diff); emit(); },
    setFiles(id, files) { state.taskFiles.set(id, files); emit(); },
  };
}
