// contract-motion.mjs — Category A "Prototype 14" motion layer for the Run
// Contract controls (reference: Category_A_Prototype_14_Master_Motion.html,
// handoff doc of 2026-07-20). Design laws, in order:
//   1. This layer OBSERVES the real form state — it never owns it. Whether a
//      selection or a contract lock succeeded is decided by the DOM radios
//      and the API result, never by an animation finishing.
//   2. settle() rebuilds every persistent visual with NO transition, so live
//      rerenders rehydrate the scene instead of replaying cinematics.
//   3. play() runs one-shot transitions guarded by stale-cancel tokens.
//   4. Every requestAnimationFrame loop dies when its DOM detaches.
//   5. prefers-reduced-motion ⇒ settled states only; zero cinematics.
import { boundedCount, ULTRA_CUSTOM_MAX, LOOPS_CUSTOM_MAX } from "./contract-options.mjs?v=26";

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const dprCap = () => Math.min(1.5, window.devicePixelRatio || 1);
const isDark = () => document.documentElement.dataset.theme === "dark";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const SVG_NS = "http://www.w3.org/2000/svg";
// Ceiling on how long a launch cinematic may claim to be working. Comfortably
// longer than a healthy contract POST, shorter than a human's patience.
const LAUNCH_WATCHDOG_MS = 12000;

const KIND_BY_SUFFIX = {
  tasktype: "task", effort: "effort", ultra: "ultra",
  framework: "framework", loops: "loops",
};
const EFFORT_TIER = { off: "", low: "fx-tier-low", medium: "fx-tier-med", high: "fx-tier-high", xhigh: "fx-tier-xhigh", max: "fx-tier-max" };
const TASK_ICONS = {
  build: '<svg viewBox="0 0 24 24"><path d="M4 8l8-4 8 4-8 4-8-4zm0 0v9l8 4 8-4V8"/></svg>',
  review: '<svg viewBox="0 0 24 24"><circle cx="10" cy="10" r="6"/><line x1="15" y1="15" x2="21" y2="21"/><line class="fx-scan" x1="4" y1="10" x2="16" y2="10"/></svg>',
  plan: '<svg viewBox="0 0 24 24"><path class="fx-route" d="M4 19C7 8 14 16 18 5M16 5h4v4"/><circle cx="4" cy="19" r="1.5"/></svg>',
  research: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><circle class="fx-radar" cx="12" cy="12" r="7"/><circle class="fx-radar fx-r2" cx="12" cy="12" r="10"/></svg>',
};

// Monotonic token: each new burst on a canvas supersedes the previous one,
// so rapid re-selections never leave two loops drawing interleaved frames.
let tokenCounter = 0;

export function groupKindOf(group) {
  const radio = group.querySelector('input[type="radio"]');
  if (!radio) return "";
  return KIND_BY_SUFFIX[radio.name.replace(/^nt|^attach/, "").toLowerCase()] || "";
}
function groupValue(group) {
  return group.querySelector("input:checked")?.value ?? "";
}
function hostOf(group) {
  return group.closest(".contract-panel") || group.closest("dialog form") || group.parentElement;
}
function customInput(group, kind) {
  const prefix = group.querySelector('input[type="radio"]').name.startsWith("nt") ? "nt" : "attach";
  return document.getElementById(prefix + (kind === "ultra" ? "UltraCustom" : "LoopsCustom"));
}
function countOf(group, kind) {
  const maximum = kind === "ultra" ? ULTRA_CUSTOM_MAX : LOOPS_CUSTOM_MAX;
  return boundedCount(groupValue(group), customInput(group, kind)?.value, maximum);
}
function thumbCenter(group, host) {
  const label = group.querySelector("input:checked")?.closest("label");
  const box = (label || group).getBoundingClientRect();
  const anchor = host.getBoundingClientRect();
  return { x: box.left - anchor.left + box.width / 2, y: box.top - anchor.top + box.height / 2 };
}

// ---- palette (light theme stays restrained; dark is full Category A) ------
function pal() {
  return isDark()
    ? { ribbon: (a) => `rgba(190,94,255,${a})`, bar: (a) => `rgba(220,148,255,${a})`,
        core: (a) => `rgba(255,245,255,${a})`, halo: (a) => `rgba(199,135,255,${a})` }
    : { ribbon: (a) => `rgba(118,58,196,${a * 0.55})`, bar: (a) => `rgba(139,82,215,${a * 0.55})`,
        core: (a) => `rgba(96,42,180,${a * 0.4})`, halo: (a) => `rgba(126,70,205,${a * 0.4})` };
}

// ---- canvas field bursts (one-shot; DPR-capped; die with their DOM) -------
function fieldBurst(canvas, { intensity = 7, duration = 1350 } = {}) {
  if (reduced() || !canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const d = dprCap();
  canvas.width = Math.max(1, Math.floor(rect.width * d));
  canvas.height = Math.max(1, Math.floor(rect.height * d));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(d, 0, 0, d, 0, 0);
  const w = rect.width, h = rect.height, colors = pal(), start = performance.now();
  const token = String(++tokenCounter);
  canvas.dataset.fxToken = token;
  canvas.classList.add("fx-live");
  function frame(now) {
    if (!canvas.isConnected || canvas.dataset.fxToken !== token) return;  // teardown / superseded
    const p = Math.min(1, (now - start) / duration);
    const fade = Math.sin(Math.PI * p);
    const build = Math.min(1, p * 2.4);
    ctx.clearRect(0, 0, w, h);
    for (let row = 0; row < 14; row++) {
      const base = h * (row + 1) / 15;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 6) {
        const env = Math.exp(-(((x / w - 0.72) * 2.6) ** 2));
        const y = base + Math.sin(x * 0.043 - now * 0.0082 + row * 0.42) * (4 + intensity) * fade * env;
        if (x) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
      ctx.strokeStyle = colors.ribbon(0.06 + fade * 0.2);
      ctx.stroke();
    }
    for (let i = 0; i < 40; i++) {
      const x = w * 0.5 + (i / 40) * w * 0.5;
      const seed = Math.abs(Math.sin(i * 5.71 + 2.4));
      const barH = (8 + seed * (16 + intensity * 4)) * build * fade;
      ctx.fillStyle = colors.bar((0.04 + seed * 0.16) * fade);
      ctx.fillRect(x, h / 2 - barH / 2, 1 + (i % 3), barH);
    }
    const gx = w * (0.82 + 0.08 * Math.sin(p * Math.PI)), gy = h / 2;
    const glow = ctx.createRadialGradient(gx, gy, 0, gx, gy, 40 + intensity * 2);
    glow.addColorStop(0, colors.core(0.5 * fade));
    glow.addColorStop(0.2, colors.halo(0.36 * fade));
    glow.addColorStop(1, "rgba(120,60,220,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, h);
    if (p < 1) requestAnimationFrame(frame);
    else { ctx.clearRect(0, 0, w, h); canvas.classList.remove("fx-live"); }
  }
  requestAnimationFrame(frame);
}

// ---- event telemetry badge -------------------------------------------------
function eventBadge(host, label) {
  if (reduced()) return;
  let badge = host.querySelector(":scope > .fx-badge");
  if (!badge) { badge = document.createElement("div"); badge.className = "fx-badge"; badge.setAttribute("aria-hidden", "true"); host.append(badge); }
  badge.textContent = label;
  badge.classList.remove("fx-show");
  void badge.offsetWidth;
  badge.classList.add("fx-show");
}

// ---- per-kind decorations (idempotent) -------------------------------------
function ensureDecorated(group, kind) {
  if (group.dataset.fxDecorated) return;
  group.dataset.fxDecorated = "1";
  group.dataset.kind = kind;
  const host = hostOf(group);
  if (host && !host.classList.contains("fx-host")) {
    host.classList.add("fx-host");
    const global = document.createElement("canvas");
    global.className = "fx-global";
    global.setAttribute("aria-hidden", "true");
    host.prepend(global);
  }
  if (kind === "task") {
    for (const label of group.querySelectorAll("label")) {
      const span = label.querySelector("span:last-child");
      const value = label.querySelector("input")?.value;
      if (span && TASK_ICONS[value] && !span.querySelector(".fx-ico")) {
        const icon = document.createElement("i");
        icon.className = "fx-ico";
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = TASK_ICONS[value];
        span.prepend(icon);
      }
    }
  }
  if (kind === "effort" || kind === "ultra") {
    const canvas = document.createElement("canvas");
    canvas.className = "fx-field";
    canvas.setAttribute("aria-hidden", "true");
    group.append(canvas);
  }
  if (kind === "effort") {
    const settleOverlay = document.createElement("i");
    settleOverlay.className = "fx-settle";
    const ring = document.createElement("i");
    ring.className = "fx-ring";
    group.append(settleOverlay, ring);
  }
  if (kind === "ultra" || kind === "framework") {
    const strip = document.createElementNS(SVG_NS, "svg");
    strip.setAttribute("class", "fx-strip");
    strip.setAttribute("preserveAspectRatio", "none");
    strip.setAttribute("aria-hidden", "true");
    group.append(strip);
    if (kind === "ultra") {
      const zoneLabel = document.createElement("span");
      zoneLabel.className = "fx-zone-label";
      zoneLabel.setAttribute("aria-hidden", "true");
      group.append(zoneLabel);
    }
  }
  if (kind === "loops") {
    const orbit = document.createElement("i");
    orbit.className = "fx-orbit";
    orbit.setAttribute("aria-hidden", "true");
    group.append(orbit);
  }
}

// ---- ULTRA candidate constellation ----------------------------------------
function renderLanes(group, animate) {
  const svg = group.querySelector(":scope > .fx-strip");
  const zoneLabel = group.querySelector(":scope > .fx-zone-label");
  const count = countOf(group, "ultra");
  const shown = Math.min(8, count);
  group.classList.toggle("fx-lanes-on", count > 0);
  group.classList.toggle("fx-strong", count >= 5);
  if (zoneLabel) zoneLabel.textContent = count ? `${count} CANDIDATES` : "";
  if (!svg) return;
  svg.innerHTML = "";
  if (!count) return;
  const W = 760, H = 40;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const label = group.querySelector("input:checked")?.closest("label");
  const groupBox = group.getBoundingClientRect();
  const originX = label && groupBox.width
    ? ((label.getBoundingClientRect().left - groupBox.left + label.getBoundingClientRect().width / 2) / groupBox.width) * W
    : W * 0.1;
  const targetX = W - 34;
  const ys = Array.from({ length: shown }, (_, i) => shown === 1 ? H / 2 : 6 + i * ((H - 12) / (shown - 1)));
  ys.forEach((ty, i) => {
    const fan = (i - (shown - 1) / 2) * 6;
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", `M${originX} ${H - 4} C${originX + 60} ${H - 6 + fan * 0.2},${targetX - 90} ${ty - fan * 0.1},${targetX} ${ty}`);
    if (animate && !reduced()) { path.classList.add("fx-draw"); path.style.animationDelay = `${i * 54}ms`; }
    svg.append(path);
    const lane = document.createElementNS(SVG_NS, "line");
    lane.setAttribute("x1", String(W * 0.62)); lane.setAttribute("x2", String(targetX));
    lane.setAttribute("y1", String(ty)); lane.setAttribute("y2", String(ty));
    lane.classList.add("fx-lane");
    svg.append(lane);
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", String(targetX)); dot.setAttribute("cy", String(ty)); dot.setAttribute("r", "3");
    if (animate && !reduced()) { dot.classList.add("fx-node"); dot.style.animationDelay = `${270 + i * 56}ms`; }
    svg.append(dot);
  });
}

// ---- FRAMEWORK reasoning network -------------------------------------------
const networkFrames = new WeakMap();
function renderNetwork(group, animate) {
  const svg = group.querySelector(":scope > .fx-strip");
  const active = groupValue(group) === "aocs_omega";
  group.classList.toggle("fx-net-on", active);
  if (!svg) return;
  cancelAnimationFrame(networkFrames.get(group) || 0);
  svg.innerHTML = "";
  if (!active) return;
  const W = 430, H = 36;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const spec = [
    { d: `M8 9 C72 2 112 15 162 8 S270 16 324 6 S400 16 424 9`, y: 9 },
    { d: `M8 28 C68 34 118 22 166 29 S272 21 326 30 S398 22 424 28`, y: 28 },
  ];
  const paths = spec.map(({ d }) => {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    if (animate && !reduced()) path.classList.add("fx-draw");
    svg.append(path);
    return path;
  });
  for (const cx of [8, 162, 324, 424]) {
    const node = document.createElementNS(SVG_NS, "circle");
    node.setAttribute("cx", String(cx)); node.setAttribute("cy", "9"); node.setAttribute("r", "2.6");
    node.classList.add("fx-net-node");
    svg.append(node);
  }
  if (reduced()) return;
  const pulses = paths.map(() => {
    const pulse = document.createElementNS(SVG_NS, "circle");
    pulse.setAttribute("r", "3");
    pulse.classList.add("fx-net-pulse");
    svg.append(pulse);
    return pulse;
  });
  const lengths = paths.map((p) => p.getTotalLength());
  const start = performance.now(), duration = 2050;
  function frame(now) {
    if (!svg.isConnected || document.hidden) {           // teardown + hidden-tab guard
      if (!svg.isConnected) return;
      networkFrames.set(group, requestAnimationFrame(frame));
      return;
    }
    const p = ((now - start) % duration) / duration;
    pulses.forEach((pulse, i) => {
      const along = (p + i * 0.43) % 1;
      const pt = paths[i].getPointAtLength(lengths[i] * along);
      pulse.setAttribute("cx", String(pt.x));
      pulse.setAttribute("cy", String(pt.y));
      pulse.style.opacity = String(0.35 + 0.5 * Math.sin(Math.PI * along));
    });
    networkFrames.set(group, requestAnimationFrame(frame));
  }
  networkFrames.set(group, requestAnimationFrame(frame));
}

// ---- LOOPS countable orbit --------------------------------------------------
function renderOrbit(group, animate) {
  const orbit = group.querySelector(":scope > .fx-orbit");
  if (!orbit) return;
  const count = countOf(group, "loops");
  group.classList.toggle("fx-loops-on", count > 0);
  orbit.innerHTML = "";
  if (!count) return;
  const label = group.querySelector("input:checked")?.closest("label");
  if (label) {
    orbit.style.left = `${label.offsetLeft + label.offsetWidth / 2}px`;
    orbit.style.top = `${label.offsetTop + label.offsetHeight / 2}px`;
  }
  if (animate && !reduced()) { orbit.classList.remove("fx-spin"); void orbit.offsetWidth; orbit.classList.add("fx-spin"); }
  const total = Math.min(10, count);
  for (let i = 0; i < total; i++) {
    const marker = document.createElement("i");
    const angle = (Math.PI * 2 * i) / total;
    marker.className = "fx-marker";
    marker.style.left = `${50 + Math.cos(angle) * 42}%`;
    marker.style.top = `${50 + Math.sin(angle) * 42}%`;
    if (animate && !reduced()) marker.style.animationDelay = `${i * 55}ms`;
    orbit.append(marker);
  }
}

// ---- settle: rebuild persistent state, no transitions -----------------------
function settleGroup(group) {
  const kind = groupKindOf(group);
  if (!kind) return;
  ensureDecorated(group, kind);
  const value = groupValue(group);
  group.dataset.fxVal = value;
  const host = hostOf(group);
  if (kind === "effort") {
    const thumb = group.querySelector(".seg-thumb");
    if (thumb) {
      thumb.classList.remove(...Object.values(EFFORT_TIER).filter(Boolean));
      if (EFFORT_TIER[value]) thumb.classList.add(EFFORT_TIER[value]);
    }
    group.classList.toggle("fx-xhigh", value === "xhigh");
    group.classList.toggle("fx-max", value === "max");
    host?.querySelector(".contract-estimate")?.classList.toggle("fx-hot", value === "xhigh" || value === "max");
  }
  if (kind === "ultra") renderLanes(group, false);
  if (kind === "framework") renderNetwork(group, false);
  if (kind === "loops") renderOrbit(group, false);
  if (host) {
    const groups = [...host.querySelectorAll(".segmented")];
    const effortValue = groups.filter((g) => groupKindOf(g) === "effort").map(groupValue)[0] || "off";
    const ultraCount = groups.filter((g) => groupKindOf(g) === "ultra").map((g) => countOf(g, "ultra"))[0] || 0;
    host.classList.toggle("fx-awake", effortValue === "xhigh" || effortValue === "max" || ultraCount >= 5);
  }
}

export function settleContractMotion(root = document) {
  for (const group of root.querySelectorAll(".segmented")) settleGroup(group);
}

// ---- play: one-shot transition on a real user change ------------------------
export function playContractMotion(changedInput) {
  const group = changedInput.closest(".segmented");
  if (!group) return;
  const kind = groupKindOf(group);
  if (!kind) return;
  const previous = group.dataset.fxVal;
  const value = changedInput.value ?? groupValue(group);
  settleGroup(group);
  if (reduced() || previous === value) return;
  const host = hostOf(group);
  group.classList.remove("fx-flash"); void group.offsetWidth; group.classList.add("fx-flash");
  if (kind === "task") {
    const label = changedInput.closest("label");
    label?.classList.remove("fx-fire"); void label?.offsetWidth; label?.classList.add("fx-fire");
  }
  if (kind === "effort") {
    const index = ["off", "low", "medium", "high", "xhigh", "max"].indexOf(value);
    if (index >= 3) fieldBurst(group.querySelector(":scope > .fx-field"), { intensity: index === 5 ? 13 : index === 4 ? 10 : 6 });
    if (index >= 4) {
      const ring = group.querySelector(":scope > .fx-ring");
      if (ring) { ring.classList.remove("fx-pulse"); void ring.offsetWidth; ring.classList.add("fx-pulse"); }
      if (host) {
        fieldBurst(host.querySelector(":scope > .fx-global"), { intensity: index === 5 ? 13 : 9, duration: index === 5 ? 1900 : 1300 });
        eventBadge(host, index === 5 ? "MAX EFFORT FIELD ONLINE" : "XHIGH THRESHOLD");
      }
    }
  }
  if (kind === "ultra") {
    renderLanes(group, true);
    const count = countOf(group, "ultra");
    if (count) fieldBurst(group.querySelector(":scope > .fx-field"), { intensity: count >= 5 ? 11 : 7 });
    if (count >= 5 && host) {
      fieldBurst(host.querySelector(":scope > .fx-global"), { intensity: 11, duration: 1700 });
      eventBadge(host, count === 8 ? "EIGHT CANDIDATE FIELD" : count === 5 ? "FIVE CANDIDATE FIELD" : `${count} CANDIDATE FIELD`);
    }
  }
  if (kind === "framework") renderNetwork(group, true);
  if (kind === "loops") renderOrbit(group, true);
}

// Custom count inputs (ntUltraCustom / attachUltraCustom / …Loops…) reshape
// the settled constellation/orbit without any cinematic replay.
export function refreshCustomCounts(input) {
  const id = input.id || "";
  if (!id.endsWith("UltraCustom") && !id.endsWith("LoopsCustom")) return;
  const kind = id.endsWith("UltraCustom") ? "ultra" : "loops";
  for (const group of document.querySelectorAll(".segmented")) {
    if (groupKindOf(group) === kind && customInput(group, kind) === input) {
      if (kind === "ultra") renderLanes(group, false); else renderOrbit(group, false);
    }
  }
}

// ---- Confirm: multi-system energy transfer ----------------------------------
// The animation runs ALONGSIDE the real API call. success()/fail() are driven
// by the actual result; the visuals never decide the outcome.
export function playLaunch(host, button) {
  const original = button.textContent;
  button.classList.add("fx-busy");
  button.textContent = "Synchronizing systems…";
  let overlay = null;
  let phaseTimer = 0;
  if (!reduced() && host) {
    host.classList.add("fx-launching");
    host.dataset.fxLaunchStart = String(Date.now());  // render-skip watchdog anchor
    button.classList.add("fx-absorb");
    eventBadge(host, "CONTRACT SYNCHRONIZATION");
    fieldBurst(host.querySelector(":scope > .fx-global"), { intensity: 11, duration: 1900 });
    overlay = document.createElementNS(SVG_NS, "svg");
    overlay.setAttribute("class", "fx-beams");
    overlay.setAttribute("aria-hidden", "true");
    const hostBox = host.getBoundingClientRect();
    overlay.setAttribute("viewBox", `0 0 ${hostBox.width} ${hostBox.height}`);
    const buttonBox = button.getBoundingClientRect();
    const ex = buttonBox.left - hostBox.left + buttonBox.width / 2;
    const ey = buttonBox.top - hostBox.top + buttonBox.height / 2;
    const colors = ["#eeeef4", "#817dff", "#df63ff", "#bda3ff", "#65d9ff"];
    [...host.querySelectorAll(".segmented")].forEach((group, i) => {
      const { x, y } = thumbCenter(group, host);
      const d = `M${x} ${y} C${x + 44 + i * 7} ${y + 44},${ex - 98 + i * 8} ${ey - 90 + i * 9},${ex} ${ey}`;
      const glow = document.createElementNS(SVG_NS, "path");
      glow.setAttribute("d", d);
      glow.setAttribute("class", "fx-beam-glow");
      glow.style.stroke = colors[i % colors.length];
      glow.style.animationDelay = `${i * 90}ms`;
      overlay.append(glow);
      const core = document.createElementNS(SVG_NS, "path");
      core.setAttribute("d", d);
      core.setAttribute("class", "fx-beam-core");
      core.style.stroke = colors[i % colors.length];
      core.style.animationDelay = `${i * 90}ms`;
      overlay.append(core);
    });
    host.append(overlay);
    phaseTimer = setTimeout(() => { if (button.isConnected) button.textContent = "Locking contract…"; }, 620);
  }
  const cleanup = () => {
    clearTimeout(phaseTimer);
    clearTimeout(watchdog);
    overlay?.remove();
    host?.classList.remove("fx-launching");
    button.classList.remove("fx-busy", "fx-absorb", "fx-success");
  };
  // A request that never settles (engine hung, machine asleep) must never leave
  // the cinematic running: "Locking contract…" forever reads as work in
  // progress when nothing is happening. The animation stands itself down and
  // hands the button back; the caller's own error path still owns the message.
  let settled = false;
  const settle = () => (settled ? false : (settled = true));
  const watchdog = setTimeout(() => {
    if (settle()) { cleanup(); button.textContent = original; }
  }, LAUNCH_WATCHDOG_MS);
  return {
    async success(message = "Contract locked ✓") {
      if (!settle()) return;
      clearTimeout(phaseTimer);
      clearTimeout(watchdog);
      button.classList.remove("fx-absorb");
      button.classList.add("fx-success");
      button.textContent = message;
      await sleep(reduced() ? 350 : 900);
      cleanup();
      button.textContent = original;
    },
    fail() {
      if (!settle()) return;
      cleanup();
      button.textContent = original;
    },
  };
}
