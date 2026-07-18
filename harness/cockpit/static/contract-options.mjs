// Single source of truth for the four locked Run Contract controls.
// Every UI that renders EFFORT / ULTRA / FRAMEWORK / LOOPS / TASK TYPE
// must read these lists — the numbers are never typed anywhere else.
// (tests/test_cockpit.py has a drift guard comparing index.html to this file.)

export const EFFORT_LEVELS = ["off", "low", "medium", "high", "xhigh", "max"];
export const EFFORT_LABELS = {
  off: "Off", low: "Low", medium: "Med", high: "High", xhigh: "XHigh", max: "Max",
};
export const ULTRA_OPTIONS = ["0", "2", "3", "5", "8", "custom"];
export const LOOPS_OPTIONS = ["0", "2", "5", "10", "custom"];
export const TASK_TYPES = ["build", "review", "plan", "research"];
export const ULTRA_CUSTOM_MAX = 64;
export const LOOPS_CUSTOM_MAX = 100;

// Resolve a segmented/select choice to a bounded integer ("custom" reads the
// paired number input; everything else is the literal value).
export function boundedCount(selected, customRaw, maximum) {
  if (selected !== "custom") return Number(selected || 0);
  const raw = Number(customRaw || 1);
  return Math.max(1, Math.min(maximum, Math.trunc(raw)));
}

// The one honest estimate line, shared by the New Session dialog and the
// attach-contract panel so they can never disagree.
export function contractEstimate({ ceiling, candidates, loops, modelStreams, machineParallel }) {
  const total = (ceiling || 0) * (1 + candidates) * (1 + loops);
  const nudge = total > 30 ? " · expect several continue nudges" : "";
  const head = total
    ? `Estimate: ≤ ${total} procedure credits`
    : "Estimate: no procedure credits";
  return `${head} · model streams ${modelStreams} · machine parallel ${machineParallel}${nudge}`;
}
