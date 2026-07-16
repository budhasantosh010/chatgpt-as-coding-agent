export const LEFT_MIN = 220;
export const LEFT_MAX = 480;
export const RIGHT_MIN = 320;
export const RIGHT_MAX = 720;
export const CENTER_MIN = 520;
const COMPACT_CENTER_MIN = 420;
const LEFT_DEFAULT = 272;
const RIGHT_DEFAULT = 420;
const LEFT_KEY = "harness.left-pane-width.v1";
const RIGHT_KEY = "harness.right-pane-width.v1";
const INSPECTOR_OPEN_KEY = "harness.inspector-open.v1";

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const storedNumber = (key, fallback) => {
  const value = Number(localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};

export function nextPaneWidth(startWidth, pointerDelta, side) {
  if (side === "left") return clamp(startWidth + pointerDelta, LEFT_MIN, LEFT_MAX);
  if (side === "right") return clamp(startWidth - pointerDelta, RIGHT_MIN, RIGHT_MAX);
  throw new TypeError(`Unknown pane side: ${side}`);
}

export function fitPaneWidths(viewportWidth, requestedLeft, requestedRight) {
  let left = clamp(requestedLeft, LEFT_MIN, LEFT_MAX);
  let right = clamp(requestedRight, RIGHT_MIN, RIGHT_MAX);
  const paneBudget = viewportWidth - CENTER_MIN - 18;
  let excess = Math.max(0, left + right - paneBudget);
  const rightReduction = Math.min(excess, right - RIGHT_MIN);
  right -= rightReduction;
  excess -= rightReduction;
  left -= Math.min(excess, left - LEFT_MIN);
  return { left, right };
}

export function initResizableLayout() {
  const root = document.getElementById("workbench");
  const left = document.getElementById("leftResizeHandle");
  const right = document.getElementById("rightResizeHandle");
  const sidebarToggle = document.getElementById("sidebarToggle");
  const sidebarClose = document.getElementById("sidebarClose");
  const navBackdrop = document.getElementById("navBackdrop");
  const inspectorToggle = document.getElementById("inspectorToggle");
  const narrowNav = window.matchMedia("(max-width: 759px)");
  const compactInspector = window.matchMedia("(max-width: 1099px)");
  let leftWidth = clamp(storedNumber(LEFT_KEY, LEFT_DEFAULT), LEFT_MIN, LEFT_MAX);
  let rightWidth = clamp(storedNumber(RIGHT_KEY, RIGHT_DEFAULT), RIGHT_MIN, RIGHT_MAX);

  const apply = () => {
    if (!compactInspector.matches) {
      ({ left: leftWidth, right: rightWidth } = fitPaneWidths(root.clientWidth, leftWidth, rightWidth));
    } else if (!narrowNav.matches) {
      leftWidth = clamp(Math.min(leftWidth, root.clientWidth - COMPACT_CENTER_MIN - 9), LEFT_MIN, LEFT_MAX);
    }
    root.style.setProperty("--left-pane", `${leftWidth}px`);
    root.style.setProperty("--right-pane", `${rightWidth}px`);
    left.setAttribute("aria-valuenow", String(Math.round(leftWidth)));
    right.setAttribute("aria-valuenow", String(Math.round(rightWidth)));
  };

  function bind(handle, side) {
    const fallback = side === "left" ? LEFT_DEFAULT : RIGHT_DEFAULT;
    const storageKey = side === "left" ? LEFT_KEY : RIGHT_KEY;
    const get = () => side === "left" ? leftWidth : rightWidth;
    const set = (value) => { side === "left" ? (leftWidth = value) : (rightWidth = value); apply(); };

    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = get();
      handle.setPointerCapture(event.pointerId);
      root.classList.add("is-resizing");
      const move = (moveEvent) => set(nextPaneWidth(startWidth, moveEvent.clientX - startX, side));
      const finish = (finishEvent) => {
        localStorage.setItem(storageKey, String(Math.round(get())));
        root.classList.remove("is-resizing");
        if (finishEvent?.pointerId != null && handle.hasPointerCapture(finishEvent.pointerId)) {
          handle.releasePointerCapture(finishEvent.pointerId);
        }
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", finish);
        handle.removeEventListener("pointercancel", finish);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", finish);
      handle.addEventListener("pointercancel", finish);
    });

    handle.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Home") set(fallback);
      else set(nextPaneWidth(get(), event.key === "ArrowRight" ? 16 : -16, side));
      localStorage.setItem(storageKey, String(Math.round(get())));
    });
    handle.addEventListener("dblclick", () => { set(fallback); localStorage.setItem(storageKey, String(fallback)); });
  }

  function setNavigationOpen(open, returnFocus = false) {
    if (narrowNav.matches) {
      root.classList.toggle("nav-open", open);
      root.classList.remove("nav-closed");
    } else {
      root.classList.toggle("nav-closed", !open);
      root.classList.remove("nav-open");
    }
    sidebarToggle.setAttribute("aria-expanded", String(open));
    if (!open && returnFocus) sidebarToggle.focus();
  }

  function setInspectorOpen(open, persist = true) {
    root.classList.toggle("inspector-closed", !open);
    inspectorToggle.setAttribute("aria-expanded", String(open));
    if (persist) localStorage.setItem(INSPECTOR_OPEN_KEY, String(open));
  }

  sidebarToggle.addEventListener("click", () => {
    const open = narrowNav.matches ? !root.classList.contains("nav-open") : root.classList.contains("nav-closed");
    setNavigationOpen(open);
  });
  sidebarClose.addEventListener("click", () => setNavigationOpen(false, true));
  navBackdrop.addEventListener("click", () => setNavigationOpen(false, true));
  inspectorToggle.addEventListener("click", () => setInspectorOpen(root.classList.contains("inspector-closed")));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (root.classList.contains("nav-open")) setNavigationOpen(false, true);
      else if (compactInspector.matches && !root.classList.contains("inspector-closed")) setInspectorOpen(false);
    }
  });

  narrowNav.addEventListener("change", () => setNavigationOpen(!narrowNav.matches));
  window.addEventListener("resize", apply);
  const storedInspector = localStorage.getItem(INSPECTOR_OPEN_KEY);
  setNavigationOpen(!narrowNav.matches);
  setInspectorOpen(storedInspector == null ? !compactInspector.matches : storedInspector === "true", false);
  bind(left, "left");
  bind(right, "right");
  apply();

  return {
    toggleInspector: () => setInspectorOpen(root.classList.contains("inspector-closed")),
    toggleNavigation: () => setNavigationOpen(root.classList.contains("nav-closed")),
  };
}
