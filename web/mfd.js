// MFD: a Star Citizen style multi-function display page for Pitboard.
// Uses globals from app.js (el, $, sendAction, cockpitButton, actionMap, COCKPIT_PANELS, localControl, toast).
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const MFD_PAGES = ["MENU", "FLT", "PWR", "WPN", "SHD", "CM", "SCN", "COM", "PLT", "NET", "CFG"];
const G_MAX = 10;
const BOOST_SEGMENTS = 22;
const FUEL_SEGMENTS = 20;

// Soft keys. Each one sends a real game action through /api/actions/trigger.
const MFD_LEFT_KEYS = [
  { id: "L1", label: "CPLD", action: "v_ifcs_vector_decoupling_toggle",
    state: (s) => s.t.decoupled == null ? null : [s.t.decoupled ? "DECOUPLED" : "COUPLED", !s.t.decoupled] },
  { id: "L2", label: "ESP", action: "v_ifcs_toggle_esp",
    state: (s) => s.t.esp == null ? null : [s.t.esp ? "ON" : "OFF", s.t.esp] },
  { id: "L3", label: "G-SAFE", action: "v_ifcs_toggle_gforce_safety",
    state: (s) => s.t.g_safe == null ? null : [s.t.g_safe ? "ON" : "OFF", s.t.g_safe] },
  { id: "L4", label: "PROX", action: "v_ifcs_proximity_assist_toggle",
    state: (s) => s.t.proximity_assist == null ? null : [s.t.proximity_assist ? "ON" : "OFF", s.t.proximity_assist] },
  { id: "L5", label: "MODE", action: "mode",
    state: (s) => s.mode ? [s.mode, s.mode === "SCM"] : null },
];
const MFD_RIGHT_KEYS = [
  { id: "R1", label: "GEAR", action: "v_toggle_landing_system",
    state: (s) => s.t.landing_gear == null ? null : [s.t.landing_gear ? "DOWN" : "UP", Boolean(s.t.landing_gear)] },
  { id: "R2", label: "VTOL", action: "v_vtol_toggle",
    state: (s) => s.t.vtol == null ? null : [s.t.vtol ? "ON" : "OFF", s.t.vtol] },
  { id: "R3", label: "QT", action: "v_toggle_qdrive_engagement",
    state: (s) => s.mode ? [s.mode === "NAV" ? "NAV · ENGAGE" : "NEEDS NAV", false] : null },
  { id: "R4", label: "ATC", action: "v_atc_request", state: () => ["REQUEST", false] },
  { id: "R5", label: "MENU", prefix: "◀ ", action: "page:MENU", state: () => [mfd.page === "MENU" ? "OPEN" : "STATUS", false] },
];

// Toggle lights shown in the IFCS grid. Every entry is a real telemetry toggle.
const MFD_IFCS = [
  ["COUPLED", (t) => t.decoupled == null ? null : !t.decoupled],
  ["ESP", (t) => t.esp],
  ["G-SAFE", (t) => t.g_safe],
  ["PROX", (t) => t.proximity_assist],
  ["CRUISE", (t) => t.cruise_control],
  ["VTOL", (t) => t.vtol],
  ["BOOST", (t) => t.boost_active],
  ["MAIN PWR", (t) => t.main_power],
  ["LIGHTS", (t) => t.lights],
  ["NIGHT VIS", (t) => t.night_vision],
  ["DOOR LOCK", (t) => t.doors_locked],
  ["GEAR DN", (t) => t.landing_gear],
];

// Which existing cockpit buttons each secondary page shows.
const MFD_PAGE_BUTTONS = {
  PWR: ["v_power_toggle", "v_power_toggle_thrusters", "v_power_toggle_shields", "v_power_toggle_weapons", "v_flightready"],
  WPN: ["v_set_guns_mode", "v_set_flight_mode", "v_power_toggle_weapons", "v_set_mining_mode", "v_set_salvage_mode"],
  SHD: ["v_power_toggle_shields"],
  CM: [],
  SCN: ["v_invoke_ping", "v_set_scan_mode", "v_flight_advanced_hud_toggle", "v_light_amplification_toggle"],
  COM: ["v_atc_request", "v_toggle_docking_request", "v_target_hail"],
  PLT: ["v_flightready", "v_toggle_landing_system", "v_vtol_toggle", "v_ifcs_vector_decoupling_toggle",
    "v_master_mode_set_nav", "v_master_mode_set_scm", "v_master_mode_cycle", "v_toggle_qdrive_engagement",
    "v_set_quantum_mode", "v_set_refuel_mode", "v_lights", "v_toggle_all_doors", "v_toggle_all_doorlocks"],
  CFG: ["v_ifcs_reset_gmeter_max", "v_self_destruct", "v_eject", "v_emergency_exit", "v_power_set_off"],
};
const MFD_EXTRA_SPECS = {
  v_ifcs_reset_gmeter_max: { name: "v_ifcs_reset_gmeter_max", label: "Reset G peak", color: "amber" },
};

const mfd = {
  built: false,
  page: localStorage.getItem("pitboard-mfd-page") || "FLT",
  pageSig: "",
  peak: 0,
  lastLog: "",
  battery: null,
};
if (!MFD_PAGES.includes(mfd.page)) mfd.page = "FLT";

function svgEl(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) if (value != null) node.setAttribute(key, value);
  for (const child of children) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

function specFor(name) {
  if (MFD_EXTRA_SPECS[name]) return MFD_EXTRA_SPECS[name];
  for (const panel of COCKPIT_PANELS) {
    const found = panel.buttons.find((spec) => spec.name === name);
    if (found) return panel.id === "danger" ? { ...found, guarded: true } : found;
  }
  return { name, label: name.replace(/^v_/, "").replaceAll("_", " "), color: "ice" };
}

function num(metric) {
  return metric && typeof metric.raw === "number" && Number.isFinite(metric.raw) ? metric.raw : null;
}

function chip(label, cls = "") {
  return el("span", { class: `mfd-chip ${cls}`.trim(), "data-chip": label }, [label]);
}

function sectionHead(text, extra) {
  const kids = [el("span", {}, [text]), el("i", {}, [])];
  if (extra) kids.push(extra);
  return el("h4", { class: "mfd-sec" }, kids);
}

function buildMfd() {
  const root = $("panel-mfd");
  const softKey = (key, side) => {
    const button = el("button", { type: "button", class: `mfd-sk ${side}`, "data-sk": key.id }, [
      el("span", { class: "mfd-sk-id" }, [key.id]),
      el("span", { class: "mfd-sk-label" }, [(key.prefix || "") + key.label]),
      el("span", { class: "mfd-sk-state" }, ["--"]),
    ]);
    button.addEventListener("click", () => pressSoftKey(key));
    return button;
  };
  const tabs = el("nav", { class: "mfd-tabs", "aria-label": "MFD pages" });
  for (const page of MFD_PAGES) {
    const tab = el("button", { type: "button", class: "mfd-tab", "data-page": page }, [page]);
    tab.addEventListener("click", () => setPage(page));
    tabs.append(tab);
  }
  const full = el("button", { type: "button", class: "mfd-mini", id: "mfd-full", title: "Full screen" }, ["⛶ FULL"]);
  full.addEventListener("click", toggleFullscreen);
  const exit = el("button", { type: "button", class: "mfd-mini", id: "mfd-exit", title: "Back to the board" }, ["BOARD"]);
  exit.addEventListener("click", () => showBoardTab("cockpit"));

  root.replaceChildren(
    el("div", { class: "mfd-rotate" }, [el("p", {}, ["ROTATE TO LANDSCAPE"])]),
    el("div", { class: "mfd", id: "mfd" }, [
      el("header", { class: "mfd-top" }, [
        el("div", { class: "mfd-ship" }, [
          el("p", { class: "mfd-ship-name", id: "mfd-ship" }, ["--"]),
          el("p", { class: "mfd-seat", id: "mfd-seat" }, ["--"]),
        ]),
        el("span", { class: "mfd-chip on", id: "mfd-mode" }, ["--"]),
        el("div", { class: "mfd-chips", id: "mfd-pwr" }, ["PWR", "WPN", "THR", "SHLD", "COOL"].map((label) => chip(label))),
        el("div", { class: "mfd-chips mfd-chips-2", id: "mfd-sys" }, ["QDRV", "RADR", "PROX", "MIT", "MISL"].map((label) => chip(label))),
        el("div", { class: "mfd-status" }, [
          el("span", { class: "mfd-bars", id: "mfd-bars" }, [el("i"), el("i"), el("i"), el("i")]),
          el("span", { class: "mfd-dot", id: "mfd-game" }, ["GAME"]),
          el("span", { class: "mfd-dot", id: "mfd-hud" }, ["HUD"]),
          el("span", { class: "mfd-lan", id: "mfd-lan", title: "LAN access is on and unencrypted", hidden: "hidden" }, ["LAN"]),
          el("span", { class: "mfd-batt", id: "mfd-batt" }, ["--%"]),
          full,
          exit,
        ]),
      ]),
      el("div", { class: "mfd-hdg", id: "mfd-hdg" }, [
        el("div", { class: "mfd-hdg-tape", id: "mfd-hdg-tape" }),
        el("div", { class: "mfd-hdg-caret" }, [el("span", { id: "mfd-hdg-val" }, ["---°"])]),
      ]),
      el("aside", { class: "mfd-keys left" }, MFD_LEFT_KEYS.map((key) => softKey(key, "left"))),
      el("section", { class: "mfd-body", id: "mfd-body" }),
      el("aside", { class: "mfd-keys right" }, MFD_RIGHT_KEYS.map((key) => softKey(key, "right"))),
      el("footer", { class: "mfd-foot" }, [
        el("p", { class: "mfd-log", id: "mfd-log" }, ["READY"]),
        tabs,
        el("p", { class: "mfd-fw", id: "mfd-fw" }, ["FLIGHT · FW 0.9.3"]),
      ]),
    ]),
  );
  document.addEventListener("fullscreenchange", () => {
    $("mfd-full").textContent = document.fullscreenElement ? "✕ EXIT" : "⛶ FULL";
  });
  document.addEventListener("pitboard:action", (event) => {
    const { ok, name } = event.detail || {};
    mfd.lastLog = `${ok ? "OK" : "REJ"} • ${name}`;
    const log = $("mfd-log");
    if (log) {
      log.textContent = mfd.lastLog;
      log.dataset.ok = String(Boolean(ok));
    }
  });
  if (navigator.getBattery) {
    navigator.getBattery().then((battery) => {
      const update = () => { mfd.battery = Math.round(battery.level * 100); };
      update();
      battery.addEventListener("levelchange", update);
    }).catch(() => {});
  }
  mfd.built = true;
}

function buildFlightPage() {
  const body = $("mfd-body");
  const gauge = svgEl("svg", { class: "mfd-gauge", viewBox: "0 -4 200 186", id: "mfd-gauge" });
  const peak = el("button", { type: "button", class: "mfd-peak", id: "mfd-peak", title: "Tap to reset the peak" }, ["PEAK -- G"]);
  peak.addEventListener("click", resetPeak);
  const boost = el("div", { class: "mfd-seg boost", id: "mfd-boost" });
  for (let i = 0; i < BOOST_SEGMENTS; i += 1) boost.append(el("i"));
  const fuelRow = (id, label) => {
    const bar = el("div", { class: "mfd-seg fuel", id: `mfd-${id}-bar` });
    for (let i = 0; i < FUEL_SEGMENTS; i += 1) bar.append(el("i"));
    return el("div", { class: "mfd-fuel-row" }, [el("span", { class: "k" }, [label]), bar, el("span", { class: "v", id: `mfd-${id}` }, ["--"])]);
  };
  const stateRow = (key, id) => el("div", { class: "mfd-kv" }, [el("span", { class: "k" }, [key]), el("span", { class: "v", id }, ["--"])]);
  const ifcs = el("div", { class: "mfd-ifcs-grid", id: "mfd-ifcs" });
  for (const [label] of MFD_IFCS) {
    ifcs.append(el("span", { class: "mfd-ifcs-item", "data-ifcs": label }, [el("b"), label]));
  }
  body.replaceChildren(
    el("div", { class: "mfd-flt" }, [
      el("div", { class: "mfd-cell mfd-spd" }, [
        el("p", { class: "mfd-label" }, ["SPEED ", el("small", {}, ["M/S"])]),
        el("div", { class: "mfd-readout-row" }, [
          el("div", { class: "mfd-big-wrap" }, [
            el("p", { class: "mfd-big", id: "mfd-speed" }, ["--"]),
            el("p", { class: "mfd-cap", id: "mfd-speed-cap" }, ["--"]),
          ]),
          el("span", { class: "mfd-pointer" }, ["▶"]),
          el("div", { class: "mfd-vtape", id: "mfd-speed-tape" }),
        ]),
      ]),
      el("div", { class: "mfd-cell mfd-g" }, [
        el("div", { class: "mfd-gauge-wrap" }, [
          gauge,
          el("div", { class: "mfd-g-center" }, [
            el("p", { class: "mfd-g-val" }, [el("span", { id: "mfd-g" }, ["--"]), el("small", {}, [" G"])]),
            peak,
          ]),
        ]),
        el("div", { class: "mfd-boost-row" }, [
          el("span", { class: "k" }, ["BOOST"]), boost, el("span", { class: "v", id: "mfd-boost-cap" }, ["--"]),
        ]),
      ]),
      el("div", { class: "mfd-cell mfd-alt" }, [
        el("p", { class: "mfd-label right", id: "mfd-alt-label" }, ["ALTITUDE"]),
        el("div", { class: "mfd-readout-row" }, [
          el("div", { class: "mfd-vtape alt", id: "mfd-alt-tape" }),
          el("span", { class: "mfd-pointer" }, ["◀"]),
          el("div", { class: "mfd-big-wrap right" }, [el("p", { class: "mfd-big", id: "mfd-alt" }, ["--"])]),
        ]),
        el("div", { class: "mfd-alt-rows" }, [
          el("div", { class: "mfd-kv" }, [el("span", { class: "k" }, ["R-ALT"]), el("span", { class: "v", id: "mfd-ralt" }, ["--"])]),
          el("div", { class: "mfd-kv" }, [el("span", { class: "k" }, ["VSI"]), el("span", { class: "v", id: "mfd-vsi" }, ["--"])]),
        ]),
      ]),
      el("div", { class: "mfd-cell mfd-fuel" }, [
        sectionHead("FUEL"),
        fuelRow("hyd", "HYD"),
        fuelRow("qnt", "QNT"),
        sectionHead("STATE"),
        el("div", { class: "mfd-state-grid" }, [
          stateRow("STATE", "mfd-st-state"),
          stateRow("GEAR", "mfd-st-gear"),
          stateRow("FLIGHT", "mfd-st-flight"),
          stateRow("HULL", "mfd-st-hull"),
        ]),
      ]),
      el("div", { class: "mfd-cell mfd-ifcs" }, [
        sectionHead("IFCS", el("span", { class: "mfd-count", id: "mfd-ifcs-count" }, ["-- ACTIVE"])),
        ifcs,
      ]),
    ]),
  );
}

function buildButtonsPage(page, next) {
  const body = $("mfd-body");
  const listed = actionMap(next);
  const armed = Boolean(next.settings && next.settings.allow_dangerous_actions && localControl);
  const wrap = el("div", { class: "mfd-page" }, [sectionHead(pageTitle(page))]);
  const info = pageInfo(page);
  if (info) wrap.append(info);
  const names = MFD_PAGE_BUTTONS[page] || [];
  const grid = el("div", { class: "mfd-btn-grid" });
  let shown = 0;
  if (!next.actions_supported) {
    wrap.append(el("p", { class: "mfd-note" }, [next.actions_error || "THIS GAME BUILD IS NOT OFFERING COMMANDS."]));
  } else {
    for (const name of names) {
      const spec = specFor(name);
      if (!listed.has(name)) continue;
      if (spec.fallbackFor && spec.fallbackFor.some((other) => listed.has(other))) continue;
      grid.append(cockpitButton(spec, listed.get(name), armed));
      shown += 1;
    }
    if (page === "CFG") {
      const dangerous = names.some((name) => (listed.get(name) || {}).dangerous);
      if (dangerous) {
        wrap.append(el("p", { class: "mfd-note" }, [armed
          ? "HOLD A STRIPED KEY TO CONFIRM. PHONES CANNOT SEND THESE."
          : localControl ? "ARM HAZARDOUS COMMANDS IN SETTINGS, THEN HOLD." : "HAZARDOUS COMMANDS ONLY FROM THE PC RUNNING PITBOARD."]));
      }
      const settings = el("button", { type: "button", class: "mfd-wide" }, ["OPEN SETTINGS"]);
      settings.addEventListener("click", () => $("settings").showModal());
      wrap.append(settings);
    }
    if (names.length && !shown) wrap.append(el("p", { class: "mfd-note" }, ["NONE OF THESE COMMANDS ARE IN THE GAME’S CURRENT LIST."]));
  }
  if (shown) wrap.append(grid);
  body.replaceChildren(wrap);
}

function pageTitle(page) {
  return {
    MENU: "MENU", FLT: "FLIGHT", PWR: "POWER", WPN: "WEAPONS", SHD: "SHIELDS", CM: "COUNTERMEASURES", SCN: "SCAN",
    COM: "COMMS", PLT: "PILOT", NET: "LINK", CFG: "CONFIG",
  }[page] || page;
}

function pageInfo(page) {
  if (page === "PWR") {
    const rows = el("div", { class: "mfd-bars-list", id: "mfd-pwr-rows" });
    for (const [key, label] of [["engines", "THR"], ["weapons", "WPN"], ["shields", "SHLD"]]) rows.append(barRow(`pwr-${key}`, label));
    rows.append(el("div", { class: "mfd-kv" }, [el("span", { class: "k" }, ["MAIN"]), el("span", { class: "v", id: "mfd-pwr-main" }, ["--"])]));
    return rows;
  }
  if (page === "SHD") {
    const rows = el("div", { class: "mfd-bars-list", id: "mfd-shd-rows" });
    for (const [key, label] of [["front", "BOW"], ["rear", "AFT"], ["left", "PORT"], ["right", "STBD"], ["top", "DORSAL"], ["bottom", "BELLY"], ["all", "ALL"]]) {
      rows.append(barRow(`shd-${key}`, label));
    }
    rows.append(barRow("shd-hull", "HULL"));
    return rows;
  }
  if (page === "WPN" || page === "CM") {
    const keys = page === "WPN"
      ? [["READY", "mfd-w-ready"], ["GROUP", "mfd-w-group"], ["GIMBALS", "mfd-w-gimbal"]]
      : [["DECOYS", "mfd-cm-decoys"], ["NOISE", "mfd-cm-noise"]];
    return el("div", { class: "mfd-big-list" }, keys.map(([k, id]) => el("div", { class: "mfd-bigkv" }, [el("span", { class: "k" }, [k]), el("span", { class: "v", id }, ["--"])])));
  }
  if (page === "NET") {
    const keys = [["LINK", "mfd-n-link"], ["RATE", "mfd-n-fps"], ["FRAMES", "mfd-n-frames"], ["SCHEMA", "mfd-n-schema"], ["TARGET", "mfd-n-target"], ["LAN", "mfd-n-lan"], ["CONTROL", "mfd-n-ctl"]];
    return el("div", { class: "mfd-state-grid wide" }, keys.map(([k, id]) => el("div", { class: "mfd-kv" }, [el("span", { class: "k" }, [k]), el("span", { class: "v", id }, ["--"])])));
  }
  if (page === "MENU") {
    const grid = el("div", { class: "mfd-btn-grid menu" });
    for (const target of MFD_PAGES.filter((item) => item !== "MENU")) {
      const button = el("button", { type: "button", class: "mfd-wide" }, [`${target} · ${pageTitle(target)}`]);
      button.addEventListener("click", () => setPage(target));
      grid.append(button);
    }
    for (const [tab, label] of [["character", "CHARACTER"], ["ship", "SHIP"], ["cockpit", "COCKPIT"], ["actions", "ALL ACTIONS"]]) {
      const button = el("button", { type: "button", class: "mfd-wide board" }, [`BOARD · ${label}`]);
      button.addEventListener("click", () => showBoardTab(tab));
      grid.append(button);
    }
    return grid;
  }
  return null;
}

function barRow(id, label) {
  const bar = el("div", { class: "mfd-seg fuel", id: `mfd-${id}-bar` });
  for (let i = 0; i < FUEL_SEGMENTS; i += 1) bar.append(el("i"));
  return el("div", { class: "mfd-fuel-row" }, [el("span", { class: "k" }, [label]), bar, el("span", { class: "v", id: `mfd-${id}` }, ["--"])]);
}

function setPage(page) {
  mfd.page = page;
  localStorage.setItem("pitboard-mfd-page", page);
  mfd.pageSig = "";
  if (snapshot) paintMfd(snapshot);
}

function showBoardTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.click();
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    const target = document.documentElement;
    if (target.requestFullscreen) await target.requestFullscreen({ navigationUI: "hide" });
    else if (target.webkitRequestFullscreen) target.webkitRequestFullscreen();
    else {
      toast("Full screen is not available here. On iPhone, use Share › Add to Home Screen.");
      return;
    }
    if (screen.orientation && screen.orientation.lock) screen.orientation.lock("landscape").catch(() => {});
  } catch (_err) {
    toast("Full screen was blocked by the browser.");
  }
}

function resetPeak() {
  mfd.peak = 0;
  const listed = snapshot ? actionMap(snapshot) : new Map();
  if (listed.has("v_ifcs_reset_gmeter_max")) sendAction("v_ifcs_reset_gmeter_max", false);
  else toast("Peak reset on this screen");
}

function pressSoftKey(key) {
  if (!snapshot) return;
  if (key.action.startsWith("page:")) {
    const target = key.action.slice(5);
    setPage(mfd.page === target ? "FLT" : target);
    return;
  }
  const name = resolveKeyAction(key, snapshot);
  if (!name) {
    toast(`${key.label} is not in the game’s current command list`);
    return;
  }
  const action = actionMap(snapshot).get(name);
  if (action && action.dangerous) {
    toast("Hazardous command. Use CFG on the PC and hold to confirm.");
    return;
  }
  sendAction(name, false);
}

function resolveKeyAction(key, next) {
  const listed = actionMap(next);
  if (key.action === "mode") {
    const mode = ((next.ship && next.ship.mode) || "").toUpperCase();
    const want = mode.includes("NAV") ? "v_master_mode_set_scm" : "v_master_mode_set_nav";
    if (mode && listed.has(want)) return want;
    if (listed.has("v_master_mode_cycle")) return "v_master_mode_cycle";
    return listed.has(want) ? want : null;
  }
  return listed.has(key.action) && listed.get(key.action).available !== false ? key.action : null;
}

function setText(id, text) {
  const node = $(id);
  if (node && node.textContent !== text) node.textContent = text;
}

function fillSegments(id, ratio, tone) {
  const bar = $(id);
  if (!bar) return;
  const cells = bar.children;
  const lit = ratio == null ? 0 : Math.round(Math.max(0, Math.min(1, ratio)) * cells.length);
  for (let i = 0; i < cells.length; i += 1) cells[i].className = i < lit ? "on" : "";
  bar.dataset.tone = ratio == null ? "none" : tone;
}

function pct(ratio) {
  return ratio == null ? "--" : `${Math.round(ratio * 100)}%`;
}

function ratioOf(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value <= 1.0001) return Math.max(0, Math.min(1, value));
  if (value <= 100) return value / 100;
  return null;
}

function paintVTape(id, value, span, step, labelEvery, format) {
  const tape = $(id);
  if (!tape) return;
  tape.dataset.empty = String(value == null);
  const center = value == null ? 0 : value;
  const kids = [];
  const low = Math.ceil((center - span) / step) * step;
  for (let mark = low; mark <= center + span; mark += step) {
    const top = 50 - ((mark - center) / span) * 50;
    if (top < 0 || top > 100) continue;
    const major = Math.round(mark / step) % Math.round(labelEvery / step) === 0;
    const tick = el("i", { class: major ? "major" : "" });
    tick.style.top = `${top}%`;
    kids.push(tick);
    if (major && value != null) {
      const label = el("span", {}, [format(mark)]);
      label.style.top = `${top}%`;
      kids.push(label);
    }
  }
  tape.replaceChildren(...kids);
}

function paintHeading(value) {
  const tape = $("mfd-hdg-tape");
  if (!tape) return;
  const span = 36;
  const center = value == null ? 0 : value;
  const kids = [];
  const low = Math.ceil((center - span) / 5) * 5;
  for (let mark = low; mark <= center + span; mark += 5) {
    const left = 50 + ((mark - center) / span) * 50;
    const major = mark % 10 === 0;
    const tick = el("i", { class: major ? "major" : "" });
    tick.style.left = `${left}%`;
    kids.push(tick);
    if (major && value != null) {
      const deg = ((mark % 360) + 360) % 360;
      const label = el("span", {}, [String(deg).padStart(3, "0")]);
      label.style.left = `${left}%`;
      kids.push(label);
    }
  }
  tape.replaceChildren(...kids);
  tape.dataset.empty = String(value == null);
  setText("mfd-hdg-val", value == null ? "---°" : `${String(Math.round(value) % 360).padStart(3, "0")}°`);
}

function gaugePoint(value, radius) {
  const angle = (-135 + (270 * Math.max(0, Math.min(G_MAX, value))) / G_MAX) * (Math.PI / 180);
  return [100 + radius * Math.sin(angle), 100 - radius * Math.cos(angle)];
}

function arcPath(from, to, radius) {
  const [x0, y0] = gaugePoint(from, radius);
  const [x1, y1] = gaugePoint(to, radius);
  const large = ((to - from) / G_MAX) * 270 > 180 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${radius} ${radius} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function paintGauge(g, peak) {
  const svg = $("mfd-gauge");
  if (!svg) return;
  const r = 78;
  const kids = [
    svgEl("path", { d: arcPath(0, G_MAX, r), class: "g-track" }),
    svgEl("path", { d: arcPath(8.5, G_MAX, r), class: "g-red" }),
  ];
  for (let v = 0; v <= G_MAX; v += 0.5) {
    const major = v % 2 === 0;
    const minor = v % 1 === 0;
    const [x0, y0] = gaugePoint(v, r + 6);
    const [x1, y1] = gaugePoint(v, r + (major ? 14 : minor ? 11 : 9));
    kids.push(svgEl("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: major ? "g-tick major" : "g-tick" }));
    if (major) {
      const [tx, ty] = gaugePoint(v, r + 24);
      kids.push(svgEl("text", { x: tx, y: ty, class: "g-num", "text-anchor": "middle", "dominant-baseline": "central" }, [String(v)]));
    }
  }
  if (g != null && g > 0.01) {
    kids.push(svgEl("path", { d: arcPath(0, Math.min(G_MAX, g), r), class: g >= 8.5 ? "g-fill hot" : "g-fill" }));
    const [nx0, ny0] = gaugePoint(g, r - 10);
    const [nx1, ny1] = gaugePoint(g, r + 4);
    kids.push(svgEl("line", { x1: nx0, y1: ny0, x2: nx1, y2: ny1, class: "g-cursor" }));
  }
  if (peak != null && peak > 0.01) {
    const [px0, py0] = gaugePoint(peak, r - 6);
    const [px1, py1] = gaugePoint(peak, r + 8);
    kids.push(svgEl("line", { x1: px0, y1: py0, x2: px1, y2: py1, class: "g-peak" }));
  }
  svg.replaceChildren(...kids);
}

function paintFlight(next) {
  const ship = next.ship || {};
  const m = ship.metrics || {};
  const t = ship.toggles || {};
  const speed = num(m.speed);
  setText("mfd-speed", speed == null ? "--" : String(Math.round(speed)));
  setText("mfd-speed-cap", t.cruise_control ? "CRUISE ON" : t.boost_active ? "BOOSTING" : speed == null ? "--" : ship.mode ? `${ship.mode.toUpperCase()} MODE` : "--");
  paintVTape("mfd-speed-tape", speed == null ? null : speed, 60, 10, 20, (v) => String(Math.round(v)));

  const g = num(m.g_force);
  const gamePeak = num(m.g_force_peak);
  if (g != null) mfd.peak = Math.max(mfd.peak, g);
  const peak = gamePeak != null ? gamePeak : g != null ? mfd.peak : null;
  setText("mfd-g", g == null ? "--" : g.toFixed(1));
  setText("mfd-peak", peak == null ? "PEAK -- G" : `PEAK ${peak.toFixed(1)} G`);
  paintGauge(g, peak);

  const boost = m.boost && m.boost.ratio != null ? m.boost.ratio : null;
  fillSegments("mfd-boost", boost, "amber");
  setText("mfd-boost-cap", boost == null ? "--" : t.boost_active ? `ACTIVE · ${pct(boost)}` : boost >= 0.99 ? "READY · 100%" : `CHARGING · ${pct(boost)}`);

  const msl = num(m.altitude);
  const radar = num(m.radar_altitude);
  const alt = msl != null ? msl : radar;
  setText("mfd-alt-label", msl != null ? "ALTITUDE" : radar != null ? "RADAR ALT" : "ALTITUDE");
  setText("mfd-alt", alt == null ? "--" : String(Math.round(alt)));
  paintVTape("mfd-alt-tape", alt, 600, 50, 200, (v) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}K` : String(Math.round(v))));
  setText("mfd-ralt", radar == null ? "--" : `${Math.round(radar)} M`);
  const vsi = num(m.vertical_speed);
  setText("mfd-vsi", vsi == null ? "--" : `${vsi >= 0 ? "▲" : "▼"} ${Math.abs(Math.round(vsi))} M/S`);

  const hyd = m.hydrogen && m.hydrogen.ratio != null ? m.hydrogen.ratio : null;
  const qnt = m.quantum_fuel && m.quantum_fuel.ratio != null ? m.quantum_fuel.ratio : null;
  fillSegments("mfd-hyd-bar", hyd, hyd != null && hyd < 0.25 ? "red" : "amber");
  fillSegments("mfd-qnt-bar", qnt, qnt != null && qnt < 0.25 ? "red" : "amber");
  setText("mfd-hyd", pct(hyd));
  setText("mfd-qnt", pct(qnt));
  $("mfd-hyd").dataset.tone = hyd != null && hyd < 0.25 ? "red" : "";
  $("mfd-qnt").dataset.tone = qnt != null && qnt < 0.25 ? "red" : "";

  setText("mfd-st-state", ship.flying ? "AIRBORNE" : ship.landed ? "LANDED" : "--");
  setText("mfd-st-gear", t.landing_gear == null ? "--" : t.landing_gear ? "DEPLOYED" : "RETRACTED");
  const flight = [t.vtol ? "VTOL" : null, t.decoupled == null ? null : t.decoupled ? "DECOUPLED" : "COUPLED"].filter(Boolean).join(" · ");
  setText("mfd-st-flight", flight || "--");
  setText("mfd-st-hull", m.hull && m.hull.ratio != null ? pct(m.hull.ratio) : "--");

  let active = 0;
  let known = 0;
  for (const [label, read] of MFD_IFCS) {
    const node = document.querySelector(`[data-ifcs="${label}"]`);
    if (!node) continue;
    const value = read(t);
    node.dataset.on = value == null ? "unknown" : String(Boolean(value));
    if (value != null) known += 1;
    if (value) active += 1;
  }
  setText("mfd-ifcs-count", known ? `${active} ACTIVE` : "-- ACTIVE");
}

function paintPages(next) {
  const ship = next.ship || {};
  const m = ship.metrics || {};
  if (mfd.page === "PWR") {
    const power = ship.power || {};
    for (const key of ["engines", "weapons", "shields"]) {
      const value = power[key];
      const ratio = typeof value === "boolean" ? (value ? 1 : 0) : ratioOf(value);
      fillSegments(`mfd-pwr-${key}-bar`, ratio, "amber");
      setText(`mfd-pwr-${key}`, value == null ? "--" : typeof value === "boolean" ? (value ? "ON" : "OFF") : pct(ratio));
    }
    setText("mfd-pwr-main", power.main == null ? "--" : power.main ? "ON" : "OFF");
  } else if (mfd.page === "SHD") {
    const faces = (ship.shields && ship.shields.faces) || {};
    for (const key of ["front", "rear", "left", "right", "top", "bottom", "all"]) {
      const face = faces[key];
      const row = $(`mfd-shd-${key}`);
      if (row) row.parentElement.hidden = !face && key === "all";
      const ratio = face ? face.ratio : null;
      fillSegments(`mfd-shd-${key}-bar`, ratio, ratio != null && ratio < 0.25 ? "red" : "amber");
      setText(`mfd-shd-${key}`, pct(ratio));
    }
    const hull = m.hull && m.hull.ratio != null ? m.hull.ratio : null;
    fillSegments("mfd-shd-hull-bar", hull, hull != null && hull < 0.25 ? "red" : "amber");
    setText("mfd-shd-hull", pct(hull));
  } else if (mfd.page === "WPN") {
    const w = ship.weapons || {};
    setText("mfd-w-ready", w.ready == null ? "--" : w.total == null ? String(w.ready) : `${w.ready}/${w.total}`);
    setText("mfd-w-group", w.group == null ? "--" : String(w.group));
    setText("mfd-w-gimbal", w.gimbals_locked == null ? "--" : w.gimbals_locked ? "LOCKED" : "FREE");
  } else if (mfd.page === "CM") {
    const cm = ship.countermeasures || {};
    setText("mfd-cm-decoys", cm.decoys == null ? "--" : String(cm.decoys));
    setText("mfd-cm-noise", cm.noise == null ? "--" : String(cm.noise));
  } else if (mfd.page === "NET") {
    setText("mfd-n-link", (next.link || "--").toUpperCase().replaceAll("_", " "));
    setText("mfd-n-fps", next.link === "live" ? `${next.fps || 0} FPS` : "--");
    setText("mfd-n-frames", next.frames == null ? "--" : String(next.frames));
    setText("mfd-n-schema", (next.schema_source || "--").toUpperCase());
    setText("mfd-n-target", next.grpc_target || "--");
    setText("mfd-n-lan", next.settings && next.settings.lan_active ? "ON · UNENCRYPTED" : "OFF");
    setText("mfd-n-ctl", localControl ? "THIS PC" : "REMOTE");
  }
  if (MFD_PAGE_BUTTONS[mfd.page]) paintMfdButtonLights(next);
}

function paintMfdButtonLights(next) {
  const toggles = (next.ship && next.ship.toggles) || {};
  const power = (next.ship && next.ship.power) || {};
  const mode = ((next.ship && next.ship.mode) || "").toUpperCase();
  for (const button of document.querySelectorAll("#panel-mfd .ck-btn")) {
    let on = null;
    if (button.dataset.toggle) {
      const value = toggles[button.dataset.toggle];
      if (value != null) on = Boolean(value);
    } else if (button.dataset.power) {
      const value = power[button.dataset.power];
      if (typeof value === "number") on = value > 0.01;
      else if (value != null) on = Boolean(value);
    } else if (button.dataset.mode) {
      on = mode.includes(button.dataset.mode.toUpperCase());
    }
    if (on == null) delete button.dataset.on;
    else button.dataset.on = String(on);
  }
}

function paintChrome(next) {
  const ship = next.ship || {};
  const t = ship.toggles || {};
  const power = ship.power || {};
  const mode = (ship.mode || "").toUpperCase();
  setText("mfd-ship", (ship.name || ship.model || "NO SHIP").toUpperCase());
  const role = next.character && next.character.crew_role;
  const seat = role ? role.toUpperCase() : ship.aboard ? "ABOARD" : ship.aboard === false ? "NOT ABOARD" : "--";
  setText("mfd-seat", next.mock ? `${seat} · PRACTICE SIM` : seat);
  setText("mfd-mode", mode || "--");
  $("mfd-mode").classList.toggle("on", Boolean(mode));

  // Power chips: the highest allocation is filled; zero is dim; missing is dim.
  const alloc = { WPN: power.weapons, THR: power.engines, SHLD: power.shields };
  const numeric = Object.entries(alloc).filter(([, v]) => typeof v === "number");
  const top = numeric.length ? numeric.reduce((a, b) => (b[1] > a[1] ? b : a))[0] : null;
  for (const node of document.querySelectorAll("#mfd-pwr .mfd-chip")) {
    const label = node.dataset.chip;
    let state = "off";
    if (label === "PWR") state = power.main == null ? "off" : power.main ? "" : "bad";
    else if (label === "COOL") state = "off";
    else {
      const v = alloc[label];
      state = v == null ? "off" : label === top ? "on" : (v === false || v === 0) ? "off" : "";
    }
    node.className = `mfd-chip ${state}`.trim();
  }
  const sys = { QDRV: mode ? mode.includes("NAV") : null, RADR: null, PROX: t.proximity_assist, MIT: null, MISL: null };
  for (const node of document.querySelectorAll("#mfd-sys .mfd-chip")) {
    const v = sys[node.dataset.chip];
    node.className = `mfd-chip ${v == null ? "off" : v ? "lit" : ""}`.trim();
  }

  const live = next.link === "live";
  const fps = live ? next.fps || 0 : 0;
  const bars = fps >= 12 ? 4 : fps >= 8 ? 3 : fps >= 4 ? 2 : fps > 0 ? 1 : 0;
  [...$("mfd-bars").children].forEach((bar, index) => bar.classList.toggle("on", index < bars));
  $("mfd-game").dataset.on = String(live);
  $("mfd-hud").dataset.on = String(Boolean(live && ship.aboard));
  $("mfd-lan").hidden = !(next.settings && next.settings.lan_active);
  setText("mfd-batt", mfd.battery == null ? "--%" : `${mfd.battery}%`);
  setText("mfd-fw", `${pageTitle(mfd.page === "FLT" ? "FLIGHT" : mfd.page)} · ${next.mock ? "SIM" : (next.schema_source || "--").toUpperCase()}`);

  const state = { t, mode };
  const listed = actionMap(next);
  for (const key of [...MFD_LEFT_KEYS, ...MFD_RIGHT_KEYS]) {
    const node = document.querySelector(`[data-sk="${key.id}"]`);
    if (!node) continue;
    const readout = key.state(state);
    const available = key.action.startsWith("page:") || Boolean(resolveKeyAction(key, next));
    node.dataset.on = String(Boolean(readout && readout[1]));
    node.dataset.na = String(!available);
    node.querySelector(".mfd-sk-state").textContent = !available ? "N/A" : readout ? readout[0] : "--";
    node.title = available ? (key.action.startsWith("page:") ? "Open the menu page" : resolveKeyAction(key, next)) : "Not offered by this game build";
  }
  for (const tab of document.querySelectorAll(".mfd-tab")) tab.classList.toggle("on", tab.dataset.page === mfd.page);
  if (!live) {
    setText("mfd-log", (next.link ? next.link.replaceAll("_", " ").toUpperCase() : "IDLE") + (next.detail ? ` • ${next.detail}` : ""));
  } else if (mfd.lastLog) setText("mfd-log", mfd.lastLog);
  else setText("mfd-log", "LINK OK");
}

function paintMfd(next) {
  if (!$("panel-mfd")) return;
  if (!mfd.built) buildMfd();
  const listed = actionMap(next);
  const sig = JSON.stringify([
    mfd.page, localControl, Boolean(next.settings && next.settings.allow_dangerous_actions),
    next.actions_supported, next.actions_error,
    [...listed.values()].map((a) => [a.name, a.dangerous, a.available]),
  ]);
  if (sig !== mfd.pageSig) {
    mfd.pageSig = sig;
    if (mfd.page === "FLT") buildFlightPage();
    else buildButtonsPage(mfd.page, next);
    $("mfd").dataset.page = mfd.page;
  }
  paintChrome(next);
  const ship = next.ship || {};
  paintHeading(num((ship.metrics || {}).heading));
  if (mfd.page === "FLT") paintFlight(next);
  else paintPages(next);
}
