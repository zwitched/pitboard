const HOLD_MS = 900;
const TOGGLE_LABELS = {
  landing_gear: "Gear",
  lights: "Lights",
  vtol: "VTOL",
  decoupled: "Decoupled",
  g_safe: "G-Safe",
  cruise_control: "Cruise",
  proximity_assist: "Prox assist",
  esp: "ESP",
  night_vision: "Night vision",
  doors_open: "Doors open",
  doors_locked: "Doors locked",
  boost_active: "Boost",
  main_power: "Main power",
};
const FACE_LABELS = {
  front: "Bow",
  rear: "Aft",
  left: "Port",
  right: "Stbd",
  top: "Dorsal",
  bottom: "Belly",
  all: "Shields",
};


const COCKPIT_PANELS = [
  {
    id: "flight",
    title: "Flight",
    tone: "ice",
    buttons: [
      { name: "v_flightready", label: "Flight ready", color: "amber" },
      { name: "v_toggle_landing_system", label: "Landing gear", color: "ice", toggle: "landing_gear" },
      { name: "v_vtol_toggle", label: "VTOL", color: "ice", toggle: "vtol" },
      { name: "v_ifcs_vector_decoupling_toggle", label: "Decoupled", color: "amber", toggle: "decoupled" },
      { name: "v_ifcs_toggle_gforce_safety", label: "G-Safe", color: "ok", toggle: "g_safe" },
      { name: "v_ifcs_proximity_assist_toggle", label: "Prox assist", color: "ok", toggle: "proximity_assist" },
      { name: "v_ifcs_toggle_esp", label: "ESP", color: "ok", toggle: "esp" },
      { name: "v_master_mode_set_nav", label: "NAV", color: "ice", mode: "NAV" },
      { name: "v_master_mode_set_scm", label: "SCM", color: "amber", mode: "SCM" },
      { name: "v_master_mode_cycle", label: "NAV/SCM", color: "ice", fallbackFor: ["v_master_mode_set_nav", "v_master_mode_set_scm"] },
      { name: "v_toggle_qdrive_engagement", label: "Quantum", color: "amber" },
      { name: "v_atc_request", label: "ATC", color: "ice" },
      { name: "v_toggle_docking_request", label: "Docking", color: "ice" },
    ],
  },
  {
    id: "power",
    title: "Power",
    tone: "amber",
    buttons: [
      { name: "v_power_toggle", label: "Main power", color: "amber", toggle: "main_power" },
      { name: "v_power_toggle_thrusters", label: "Thrusters", color: "ice", power: "engines" },
      { name: "v_power_toggle_shields", label: "Shields", color: "ice", power: "shields" },
      { name: "v_power_toggle_weapons", label: "Weapons", color: "amber", power: "weapons" },
    ],
  },
  {
    id: "systems",
    title: "Systems",
    tone: "ice",
    buttons: [
      { name: "v_lights", label: "Lights", color: "amber", toggle: "lights" },
      { name: "v_light_amplification_toggle", label: "Night vision", color: "ok", toggle: "night_vision" },
      { name: "v_flight_advanced_hud_toggle", label: "Adv HUD", color: "ice" },
      { name: "v_invoke_ping", label: "Ping", color: "ice", holdable: true },
      { name: "v_target_hail", label: "Hail", color: "ice" },
      { name: "v_toggle_all_doors", label: "Doors", color: "amber", toggle: "doors_open" },
      { name: "v_toggle_all_doorlocks", label: "Door locks", color: "ok", toggle: "doors_locked" },
    ],
  },
  {
    id: "modes",
    title: "Modes",
    tone: "ice",
    buttons: [
      { name: "v_set_flight_mode", label: "Flight", color: "ice" },
      { name: "v_set_guns_mode", label: "Guns", color: "amber" },
      { name: "v_set_scan_mode", label: "Scan", color: "ice" },
      { name: "v_set_mining_mode", label: "Mining", color: "amber" },
      { name: "v_set_salvage_mode", label: "Salvage", color: "ice" },
      { name: "v_set_quantum_mode", label: "Quantum", color: "amber" },
      { name: "v_set_refuel_mode", label: "Refuel", color: "ok" },
    ],
  },
  {
    id: "danger",
    title: "Danger",
    tone: "bad",
    buttons: [
      { name: "v_self_destruct", label: "Self destruct", color: "bad", guarded: true },
      { name: "v_eject", label: "Eject", color: "bad", guarded: true },
      { name: "v_emergency_exit", label: "Emergency exit", color: "bad", guarded: true },
      { name: "v_power_set_off", label: "Power off", color: "bad", guarded: true },
    ],
  },
];

let token = "";
let localControl = false;
let snapshot = null;
let actionSig = "";
let cockpitSig = "";
let built = false;
let toastTimer = 0;
let settingsLock = false;
let shareKey = "";

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("on"), 2800);
}

function authHeaders() {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return data;
}

function queryToken() {
  const params = new URLSearchParams(location.search);
  const found = params.get("token");
  if (!found) return "";
  params.delete("token");
  const next = params.toString();
  history.replaceState({}, "", location.pathname + (next ? `?${next}` : ""));
  sessionStorage.setItem("pitboard-token", found);
  return found;
}

async function boot() {
  token = queryToken() || sessionStorage.getItem("pitboard-token") || "";
  if (!token) {
    try {
      const data = await fetch("/api/bootstrap").then((response) => {
        if (!response.ok) throw new Error("bootstrap");
        return response.json();
      });
      token = data.token;
      sessionStorage.setItem("pitboard-token", token);
    } catch (_err) {
      toast("This page needs the access link from the PC running Pitboard.");
      return;
    }
  }
  try {
    const who = await api("/api/whoami");
    localControl = Boolean(who.local_control);
  } catch (_err) {
    localControl = false;
  }
  connect();
  bindChrome();
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ op: "auth", token }));
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.snapshot) applySnapshot(message.snapshot);
  });
  socket.addEventListener("close", () => {
    setTimeout(connect, 1000);
  });
}

function applySnapshot(next) {
  snapshot = next;
  document.body.dataset.link = next.link || "idle";
  document.title = `Pitboard · ${(next.link || "idle").replaceAll("_", " ")}`;
  $("pilot").textContent = next.pilot || "LighterBurrito";
  $("link-label").textContent = linkLabel(next.link);
  $("link-detail").textContent = next.detail || "";
  $("fps").textContent = next.link === "live" ? `${next.fps || 0} fps` : "";
  $("practice").hidden = !next.mock;
  $("lanwarn").hidden = !(next.settings && next.settings.lan_active);
  showGuide(next);
  if (!built) {
    buildCharacter();
    buildShip();
    built = true;
  }
  paintCharacter(next);
  paintShip(next);
  paintCockpit(next);
  paintActions(next);
  paintSettings(next);
}

function linkLabel(link) {
  return {
    live: "Live",
    connecting: "Linking",
    offline: "No link",
    no_schema: "No schema",
    refused: "Refused",
    schema_mismatch: "Schema",
    idle: "Idle",
  }[link] || link;
}

function showGuide(next) {
  const guide = $("guide");
  const blocks = ["offline", "schema", "refused", "mismatch"];
  for (const name of blocks) $(`guide-${name}`).hidden = true;
  if (next.link === "live") {
    guide.hidden = true;
    return;
  }
  guide.hidden = false;
  if (next.link === "no_schema") $("guide-schema").hidden = false;
  else if (next.link === "refused") {
    $("guide-refused").hidden = false;
    $("guide-refused-detail").textContent = next.detail || "";
  } else if (next.link === "schema_mismatch") {
    $("guide-mismatch").hidden = false;
    $("guide-mismatch-detail").textContent = next.detail || "";
  } else {
    $("guide-offline").hidden = false;
    if (next.detail) $("guide-offline-detail").textContent = next.detail;
  }
}

function metricNode(metric, key) {
  const featured = ["health", "oxygen", "speed", "g_force"].includes(key) ? " featured" : "";
  const node = el("article", { class: `metric${featured}`, "data-metric": key });
  node.append(
    el("h3", { class: "name" }, [metric.label || key]),
    el("p", { class: "val" }, ["—"]),
    el("div", { class: "bar" }, [el("i")]),
    el("p", { class: "unit" }, [""]),
  );
  return node;
}

function buildCharacter() {
  const root = $("panel-character");
  const metrics = snapshot.character.metrics;
  root.replaceChildren(
    el("div", { class: "identity" }, [
      el("div", {}, [
        el("p", { class: "meta", id: "posture" }, ["—"]),
        el("h2", { id: "location" }, ["—"]),
        el("p", { class: "meta", id: "role" }, [""]),
      ]),
      el("p", { class: "meta", id: "position" }, ["—"]),
    ]),
    el("div", { class: "hero", id: "hero" }),
    el("div", { class: "stat-grid", id: "vitals" }),
    el("div", { class: "env-grid", id: "env" }),
  );
  const heroKeys = ["health", "oxygen", "heart_rate"];
  const vitalKeys = ["hunger", "thirst", "balance", "radiation", "intoxication"];
  const envKeys = ["body_temperature", "outside_temperature", "gravity", "pressure", "breathable"];
  for (const key of heroKeys) $("hero").append(metricNode(metrics[key], key));
  for (const key of vitalKeys) if (metrics[key]) $("vitals").append(metricNode(metrics[key], key));
  for (const key of envKeys) if (metrics[key]) $("env").append(metricNode(metrics[key], key));
}

function paintMetric(key, metric) {
  const node = document.querySelector(`[data-metric="${key}"]`);
  if (!node || !metric) return;
  node.dataset.tone = metric.tone || "idle";
  node.querySelector(".val").textContent = metric.display || "—";
  node.querySelector(".unit").textContent = metric.unit || "";
  const bar = node.querySelector(".bar");
  const fill = bar.querySelector("i");
  if (metric.bar && metric.ratio != null) {
    bar.hidden = false;
    fill.style.transform = `scaleX(${Math.max(0, Math.min(1, metric.ratio))})`;
  } else {
    bar.hidden = true;
  }
  if (metric.path) node.title = metric.path;
}

function paintCharacter(next) {
  const character = next.character;
  $("posture").textContent = character.posture_label || "No posture yet";
  $("location").textContent = character.location || "Location unknown";
  $("role").textContent = character.crew_role || "";
  const pos = character.position;
  $("position").textContent = pos
    ? `X ${Math.round(pos.x)}   Y ${Math.round(pos.y)}   Z ${Math.round(pos.z)}`
    : "Position not in this frame";
  for (const [key, metric] of Object.entries(character.metrics || {})) paintMetric(key, metric);
}

function buildShip() {
  const root = $("panel-ship");
  root.replaceChildren(
    el("div", { class: "identity" }, [
      el("div", {}, [
        el("p", { class: "meta", id: "ship-maker" }, [""]),
        el("h2", { id: "ship-name" }, ["No ship"]),
        el("p", { class: "meta", id: "ship-mode" }, [""]),
      ]),
      el("p", { class: "meta", id: "aboard" }, [""]),
    ]),
    el("div", { class: "ship-stats", id: "ship-stats" }),
    el("div", { id: "rose" }),
    el("div", { class: "split" }, [
      el("article", { class: "card", id: "power-card" }, [el("h3", {}, ["Power"])]),
      el("article", { class: "card", id: "cm-card" }, [el("h3", {}, ["Countermeasures"])]),
      el("article", { class: "card", id: "weap-card" }, [el("h3", {}, ["Weapons"])]),
    ]),
    el("div", { class: "toggles", id: "toggles" }),
    el("article", { class: "card", id: "extra-card" }),
    el("h3", { class: "group-title" }, ["Recent events"]),
    el("ul", { class: "events", id: "events" }),
    el("details", {}, [
      el("summary", {}, ["Unmapped fields"]),
      el("ul", { class: "events", id: "unmapped" }),
    ]),
  );
  const stats = $("ship-stats");
  for (const key of ["speed", "g_force", "radar_altitude"]) {
    stats.append(metricNode(snapshot.ship.metrics[key], key));
  }
  for (const key of ["hull", "boost", "hydrogen", "vertical_speed"]) {
    if (snapshot.ship.metrics[key]) stats.append(metricNode(snapshot.ship.metrics[key], key));
  }
}

function paintShip(next) {
  const ship = next.ship;
  const name = ship.name || ship.model || "No ship yet";
  $("ship-name").textContent = name;
  $("ship-maker").textContent = [ship.manufacturer, ship.role].filter(Boolean).join(" · ");
  const bits = [ship.mode, ship.flying ? "Airborne" : null, ship.landed ? "Landed" : null].filter(Boolean);
  $("ship-mode").textContent = bits.join(" · ");
  $("aboard").textContent = ship.aboard === false ? "Not aboard — last ship snapshot" : ship.aboard ? "Aboard" : "";
  for (const [key, metric] of Object.entries(ship.metrics || {})) paintMetric(key, metric);
  paintShields(ship.shields, ship.metrics.hull);
  paintPower(ship.power);
  paintCm(ship.countermeasures);
  paintWeapons(ship.weapons);
  paintToggles(ship.toggles);
  paintExtra(ship);
  paintEvents(next.events || []);
  paintUnmapped(next.unmapped || []);
}

function paintShields(shields, hull) {
  const rose = $("rose");
  const faces = (shields && shields.faces) || {};
  const keys = Object.keys(faces);
  const signature = keys.slice().sort().join(",");
  if (rose.dataset.sig !== signature) {
    rose.dataset.sig = signature;
    rose.replaceChildren();
    if (keys.length === 1 && keys[0] === "all") {
      rose.append(faceNode("all"));
    } else {
      rose.className = "rose";
      for (const key of ["top", "left", "right", "front", "rear", "bottom"]) {
        if (faces[key]) rose.append(faceNode(key));
      }
      const core = el("div", { class: "core", id: "hull-core" }, [el("div", {}, [])]);
      rose.append(core);
    }
  }
  for (const [key, face] of Object.entries(faces)) {
    const node = rose.querySelector(`[data-face="${key}"]`);
    if (!node) continue;
    const ratio = face.ratio == null ? 0 : face.ratio;
    node.dataset.tone = face.tone || "idle";
    node.querySelector(".val").textContent = face.ratio == null ? String(face.raw) : `${Math.round(ratio * 100)}%`;
    node.querySelector("i").style.transform = `scaleX(${Math.max(0, Math.min(1, ratio))})`;
  }
  const core = $("hull-core");
  if (core) {
    const display = hull && hull.display ? hull.display : "—";
    core.replaceChildren(el("div", {}, [el("h3", {}, ["Hull"]), el("p", { class: "val" }, [display])]));
  }
}

function faceNode(key) {
  return el("article", { class: `face ${key}`, "data-face": key }, [
    el("h3", { class: "name" }, [FACE_LABELS[key] || key]),
    el("p", { class: "val" }, ["—"]),
    el("div", { class: "bar" }, [el("i")]),
  ]);
}

function paintPower(power) {
  const card = $("power-card");
  const rows = [
    ["engines", "Engines"],
    ["weapons", "Weapons"],
    ["shields", "Shields"],
  ];
  const keep = card.querySelector("h3");
  card.replaceChildren(keep);
  for (const [key, label] of rows) {
    const value = power[key];
    const ratio = typeof value === "number" && value <= 1 ? value : null;
    const text = value == null ? "—" : ratio == null ? String(value) : `${Math.round(ratio * 100)}%`;
    const bar = el("div", { class: "bar" }, [el("i")]);
    if (ratio != null) bar.querySelector("i").style.transform = `scaleX(${ratio})`;
    card.append(el("div", { class: "power-row" }, [el("span", {}, [label]), bar, el("span", {}, [text])]));
  }
  card.append(el("p", { class: "meta" }, [`Main power ${power.main == null ? "—" : power.main ? "on" : "off"}`]));
}

function paintCm(cm) {
  const card = $("cm-card");
  const title = card.querySelector("h3");
  card.replaceChildren(
    title,
    el("p", { class: "big" }, [cm.decoys == null ? "—" : String(cm.decoys)]),
    el("p", { class: "meta" }, ["Decoys"]),
    el("p", { class: "big" }, [cm.noise == null ? "—" : String(cm.noise)]),
    el("p", { class: "meta" }, ["Noise"]),
  );
}

function paintWeapons(weapons) {
  const card = $("weap-card");
  const title = card.querySelector("h3");
  const ready = weapons.ready == null ? "—" : weapons.total == null ? String(weapons.ready) : `${weapons.ready} / ${weapons.total}`;
  const gimbals = weapons.gimbals_locked == null ? "Gimbals —" : weapons.gimbals_locked ? "Gimbals locked" : "Gimbals free";
  card.replaceChildren(
    title,
    el("p", { class: "big" }, [ready]),
    el("p", { class: "meta" }, ["Ready"]),
    el("p", { class: "meta" }, [`Group ${weapons.group == null ? "—" : weapons.group}`]),
    el("p", { class: "meta" }, [gimbals]),
  );
}

function paintToggles(toggles) {
  const root = $("toggles");
  root.replaceChildren();
  for (const [key, label] of Object.entries(TOGGLE_LABELS)) {
    const value = toggles[key];
    const node = el("div", { class: "lamp-toggle", "data-on": value == null ? "unknown" : String(value) }, [
      label,
      value == null ? " —" : value ? " on" : " off",
    ]);
    root.append(node);
  }
}

function paintExtra(ship) {
  const card = $("extra-card");
  const turret = ship.turret || {};
  const bits = [];
  if (turret.occupied != null || turret.yaw_deg || turret.pitch_deg) {
    bits.push(`Turret ${turret.occupied ? "occupied" : "empty"}  yaw ${fmt(turret.yaw_deg)}  pitch ${fmt(turret.pitch_deg)}`);
  }
  if (ship.force_feedback != null) bits.push(`Force feedback ${ship.force_feedback.toFixed(2)}`);
  card.hidden = bits.length === 0;
  card.replaceChildren(el("h3", {}, ["Turret and feedback"]), el("p", {}, [bits.join(" · ")]));
}

function fmt(value) {
  return value == null ? "—" : Number(value).toFixed(1);
}

function paintEvents(events) {
  const list = $("events");
  list.replaceChildren();
  const rows = events.slice().reverse().slice(0, 8);
  if (!rows.length) {
    list.append(el("li", {}, [el("span", {}, ["No events in this session yet."])]));
    return;
  }
  for (const event of rows) {
    list.append(el("li", {}, [el("strong", {}, [event.name || "Event"]), " ", el("span", {}, [event.detail || ""])]));
  }
}

function paintUnmapped(items) {
  const list = $("unmapped");
  list.replaceChildren();
  if (!items.length) {
    list.append(el("li", {}, [el("span", {}, ["Every recognized field is on the board."])]));
    return;
  }
  for (const item of items) {
    list.append(el("li", {}, [el("strong", {}, [item.path]), " ", el("span", {}, [String(item.value)])]));
  }
}


function actionMap(next) {
  const map = new Map();
  for (const action of next.actions || []) map.set(action.name, action);
  return map;
}

function cockpitVisible(spec, listed) {
  if (spec.fallbackFor && spec.fallbackFor.some((name) => listed.has(name))) return false;
  return listed.has(spec.name);
}

function bindHold(button, startMs, onFire, { touchNone = false } = {}) {
  let timer = 0;
  let frame = 0;
  let started = 0;
  const bar = button.querySelector(".ck-hold, .hold");
  const cancel = () => {
    clearTimeout(timer);
    cancelAnimationFrame(frame);
    timer = 0;
    button.classList.remove("is-down");
    if (bar) bar.style.transform = "scaleX(0)";
  };
  const tick = () => {
    const ratio = Math.min(1, (performance.now() - started) / startMs);
    if (bar) bar.style.transform = `scaleX(${ratio})`;
    if (ratio < 1) frame = requestAnimationFrame(tick);
  };
  const start = (event) => {
    if (button.disabled) return;
    event.preventDefault();
    started = performance.now();
    button.classList.add("is-down");
    tick();
    timer = setTimeout(() => {
      cancel();
      onFire(startMs);
    }, startMs);
  };
  if (touchNone) button.style.touchAction = "none";
  button.addEventListener("pointerdown", start);
  button.addEventListener("pointerup", cancel);
  button.addEventListener("pointerleave", cancel);
  button.addEventListener("pointercancel", cancel);
  button.addEventListener("contextmenu", (event) => event.preventDefault());
  button.addEventListener("keydown", (event) => {
    if ((event.key === " " || event.key === "Enter") && !timer) start(event);
  });
  button.addEventListener("keyup", cancel);
}

function bindHoldable(button, action) {
  let started = 0;
  const bar = button.querySelector(".ck-hold");
  const cancel = (event) => {
    if (!started) return;
    button.classList.remove("is-down");
    const held = performance.now() - started;
    started = 0;
    if (bar) bar.style.transform = "scaleX(0)";
    if (event && event.type === "pointerleave") return;
    if (held < 40) return;
    sendAction(action.name, false, Math.min(held, 10000));
  };
  const start = (event) => {
    if (button.disabled) return;
    event.preventDefault();
    started = performance.now();
    button.classList.add("is-down");
    const tick = () => {
      if (!started) return;
      if (bar) bar.style.transform = `scaleX(${Math.min(1, (performance.now() - started) / 1500)})`;
      requestAnimationFrame(tick);
    };
    tick();
  };
  button.style.touchAction = "none";
  button.addEventListener("pointerdown", start);
  button.addEventListener("pointerup", cancel);
  button.addEventListener("pointerleave", (event) => {
    if (!started) return;
    started = 0;
    button.classList.remove("is-down");
    if (bar) bar.style.transform = "scaleX(0)";
  });
  button.addEventListener("pointercancel", (event) => {
    started = 0;
    button.classList.remove("is-down");
    if (bar) bar.style.transform = "scaleX(0)";
  });
  button.addEventListener("contextmenu", (event) => event.preventDefault());
}

function cockpitButton(spec, action, armed) {
  const dangerous = Boolean(action.dangerous);
  const guarded = Boolean(spec.guarded) || dangerous;
  const kids = [];
  if (guarded) kids.push(el("span", { class: "ck-stripes" }, []));
  const capKids = [
    el("span", { class: "ck-led", "aria-hidden": "true" }, []),
    el("span", { class: "ck-name" }, [spec.label]),
  ];
  if (spec.holdable || guarded) capKids.push(el("span", { class: "ck-hold" }, []));
  if (guarded) capKids.push(el("span", { class: "ck-hint" }, [dangerous && !armed ? "Covered" : "Hold"]));
  else if (spec.holdable) capKids.push(el("span", { class: "ck-hint" }, ["Hold"]));
  kids.push(el("span", { class: "ck-cap" }, capKids));
  const button = el("button", {
    class: guarded ? "ck-btn danger" : "ck-btn",
    type: "button",
    "data-name": spec.name,
    "data-color": spec.color || "ice",
  }, kids);
  if (spec.toggle) button.dataset.toggle = spec.toggle;
  if (spec.mode) button.dataset.mode = spec.mode;
  if (spec.power) button.dataset.power = spec.power;
  if (action.available === false) button.disabled = true;
  if (dangerous && !armed) button.disabled = true;
  if (dangerous) {
    bindHold(button, HOLD_MS, () => sendAction(action.name, true), { touchNone: true });
  } else if (spec.holdable) {
    bindHoldable(button, action);
  } else if (guarded) {
    bindHold(button, HOLD_MS, () => sendAction(action.name, false), { touchNone: true });
  } else {
    button.addEventListener("click", () => sendAction(action.name, false));
  }
  return button;
}

function paintCockpit(next) {
  const listed = actionMap(next);
  const armed = Boolean(next.settings && next.settings.allow_dangerous_actions && localControl);
  const signature = JSON.stringify([
    localControl,
    armed,
    next.actions_supported,
    next.actions_error,
    [...listed.keys()],
    [...listed.values()].map((action) => [action.name, action.dangerous, action.available]),
  ]);
  if (signature !== cockpitSig) {
    cockpitSig = signature;
    const root = $("panel-cockpit");
    root.replaceChildren();
    if (!next.actions_supported) {
      root.append(el("p", { class: "note cockpit-note" }, [next.actions_error || "This game build is not offering commands."]));
    } else {
      const stack = el("div", { class: "cockpit-stack" });
      let shown = 0;
      for (const panel of COCKPIT_PANELS) {
        const buttons = panel.buttons.filter((spec) => cockpitVisible(spec, listed));
        if (!buttons.length) continue;
        const bay = el("section", { class: "cockpit-bay", "data-tone": panel.tone, "data-bay": panel.id }, [
          el("h3", { class: "cockpit-bay-label" }, [panel.title]),
        ]);
        if (panel.id === "danger") {
          const why = !buttons.some((spec) => (listed.get(spec.name) || {}).dangerous)
            ? null
            : !armed
              ? (localControl
                ? "Arm in Settings, then hold. Phones cannot send these."
                : "Hazardous commands can only be sent from the PC running Pitboard.")
              : "Hold a striped button to confirm. These cannot be sent from a phone.";
          if (why) bay.append(el("p", { class: "note cockpit-danger-note" }, [why]));
        }
        const grid = el("div", { class: "cockpit-grid" });
        for (const spec of buttons) {
          grid.append(cockpitButton(spec, listed.get(spec.name), armed));
          shown += 1;
        }
        bay.append(grid);
        stack.append(bay);
      }
      if (!shown) {
        root.append(el("p", { class: "note cockpit-note" }, ["None of the cockpit commands are in the game’s current list."]));
      } else {
        root.append(stack);
      }
    }
  }
  const toggles = (next.ship && next.ship.toggles) || {};
  const power = (next.ship && next.ship.power) || {};
  const mode = ((next.ship && next.ship.mode) || "").toUpperCase();
  for (const button of document.querySelectorAll("#panel-cockpit .ck-btn")) {
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

function paintActions(next) {
  const signature = JSON.stringify([
    localControl,
    next.settings && next.settings.allow_dangerous_actions,
    (next.actions || []).map((action) => [action.name, action.label, action.group, action.dangerous, action.available]),
    next.actions_error,
    next.actions_supported,
  ]);
  if (signature === actionSig) return;
  actionSig = signature;
  const root = $("panel-actions");
  root.replaceChildren();
  const search = el("input", { class: "search", id: "action-search", placeholder: "Filter commands", type: "search" });
  search.addEventListener("input", () => filterActions(search.value));
  root.append(search);
  if (!next.actions_supported) {
    root.append(el("p", { class: "note" }, [next.actions_error || "This game build is not offering commands."]));
  }
  const groups = [
    ["character", "Character"],
    ["emote", "Emotes"],
    ["ship", "Ship"],
    ["other", "Other"],
  ];
  const actions = next.actions || [];
  for (const [group, label] of groups) {
    const members = actions.filter((action) => (action.group || "other") === group && !action.dangerous);
    if (!members.length) continue;
    root.append(el("h3", { class: "group-title" }, [label]));
    const wrap = el("div", { class: "actions" });
    for (const action of members) wrap.append(actionButton(action, false));
    root.append(wrap);
  }
  const dangerous = actions.filter((action) => action.dangerous);
  root.append(el("h3", { class: "group-title" }, ["Hazardous"]));
  if (!dangerous.length) {
    root.append(el("p", { class: "note" }, ["No hazardous commands in the current list."]));
    return;
  }
  const armed = Boolean(next.settings && next.settings.allow_dangerous_actions && localControl);
  const wrap = el("div", { class: "actions" });
  for (const action of dangerous) wrap.append(actionButton(action, true, armed));
  root.append(wrap);
  if (!armed) {
    const why = localControl
      ? "Hazardous commands are off. Enable them in Settings, then hold the button."
      : "Hazardous commands can only be sent from the PC running Pitboard.";
    root.append(el("p", { class: "note" }, [why]));
  }
}

function actionButton(action, dangerous, armed) {
  const button = el("button", { class: dangerous ? "act danger" : "act", type: "button" }, [action.label || action.name]);
  button.dataset.name = action.name;
  if (action.available === false) button.disabled = true;
  if (dangerous && !armed) button.disabled = true;
  if (!dangerous) {
    button.addEventListener("click", () => sendAction(action.name, false));
    return button;
  }
  const bar = el("span", { class: "hold" });
  button.append(bar);
  let timer = 0;
  let frame = 0;
  let started = 0;
  const cancel = () => {
    clearTimeout(timer);
    cancelAnimationFrame(frame);
    timer = 0;
    bar.style.transform = "scaleX(0)";
  };
  const tick = () => {
    const ratio = Math.min(1, (performance.now() - started) / HOLD_MS);
    bar.style.transform = `scaleX(${ratio})`;
    if (ratio < 1) frame = requestAnimationFrame(tick);
  };
  const start = (event) => {
    if (button.disabled) return;
    event.preventDefault();
    started = performance.now();
    tick();
    timer = setTimeout(() => {
      cancel();
      sendAction(action.name, true);
    }, HOLD_MS);
  };
  button.addEventListener("pointerdown", start);
  button.addEventListener("pointerup", cancel);
  button.addEventListener("pointerleave", cancel);
  button.addEventListener("pointercancel", cancel);
  button.addEventListener("contextmenu", (event) => event.preventDefault());
  button.addEventListener("keydown", (event) => {
    if ((event.key === " " || event.key === "Enter") && !timer) start(event);
  });
  button.addEventListener("keyup", cancel);
  return button;
}

function filterActions(query) {
  const needle = query.trim().toLowerCase();
  for (const button of document.querySelectorAll("#panel-actions .act")) {
    button.hidden = needle && !button.textContent.toLowerCase().includes(needle);
  }
}

async function sendAction(name, dangerous, holdMs = 0) {
  try {
    let nonce = null;
    if (dangerous) {
      const armed = await api("/api/actions/arm", { name });
      nonce = armed.nonce;
    }
    const body = { name, nonce };
    if (holdMs) body.hold_ms = Math.round(holdMs);
    const result = await api("/api/actions/trigger", body);
    toast(result.message || (result.ok ? "Sent" : "Rejected"));
    if (result.snapshot) applySnapshot(result.snapshot);
  } catch (err) {
    toast(err.message);
  }
}

function bindChrome() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      for (const other of document.querySelectorAll(".tab")) other.classList.toggle("on", other === tab);
      for (const panel of document.querySelectorAll("main > .panel")) {
        panel.hidden = panel.id !== `panel-${name}`;
      }
    });
  }
  $("open-settings").addEventListener("click", () => $("settings").showModal());
  $("set-danger").addEventListener("change", () => saveSetting({ allow_dangerous_actions: $("set-danger").checked }));
  $("set-lan").addEventListener("change", () => saveSetting({ lan_enabled: $("set-lan").checked }));
  $("set-record").addEventListener("change", () => saveSetting({ record: $("set-record").checked }));
  $("regen-token").addEventListener("click", regenerate);
  $("copy-link").addEventListener("click", copyLink);
}

async function saveSetting(patch) {
  if (settingsLock || !localControl) return;
  try {
    await api("/api/settings", patch);
    if (patch.regenerate_token) return;
    toast("Saved");
  } catch (err) {
    toast(err.message);
  }
}

function paintSettings(next) {
  const settings = next.settings || {};
  settingsLock = true;
  $("set-danger").checked = Boolean(settings.allow_dangerous_actions);
  $("set-lan").checked = Boolean(settings.lan_enabled);
  $("set-record").checked = Boolean(settings.record);
  for (const id of ["set-danger", "set-lan", "set-record", "regen-token"]) {
    $(id).disabled = !localControl;
  }
  $("settings-scope").textContent = localControl
    ? "These switches apply on this PC."
    : "Open settings on the PC that runs Pitboard to change them.";
  $("restart-note").hidden = !settings.restart_required;
  $("record-path").textContent = settings.record_path ? `Log: ${settings.record_path}` : "";
  const source = next.schema_source ? `Schema: ${next.schema_source}` : "Schema: none";
  const methods = (next.schema_methods || []).join(", ");
  $("schema-note").textContent = `${source}. ${next.grpc_target || ""} ${methods ? "· " + methods : ""}`;
  settingsLock = false;
  const key = localControl && settings.lan_active ? "on" : "off";
  if (key !== shareKey) {
    shareKey = key;
    if (key === "on") loadShare();
    else $("share-block").hidden = true;
  }
}

async function loadShare() {
  try {
    const share = await api("/api/share");
    if (!share.share_url) {
      $("share-block").hidden = true;
      return;
    }
    $("share-block").hidden = false;
    $("share-url").value = share.share_url;
    const image = await fetch("/api/share/qr.svg", { headers: authHeaders() });
    if (image.ok) {
      const blob = await image.blob();
      const previous = $("share-qr").src;
      if (previous.startsWith("blob:")) URL.revokeObjectURL(previous);
      $("share-qr").src = URL.createObjectURL(blob);
    }
  } catch (_err) {
    $("share-block").hidden = true;
  }
}

async function copyLink() {
  const value = $("share-url").value;
  try {
    await navigator.clipboard.writeText(value);
    toast("Link copied");
  } catch (_err) {
    $("share-url").focus();
    $("share-url").select();
    toast("Select the link and copy it");
  }
}

async function regenerate() {
  if (!localControl) return;
  if (!confirm("Replace the access token? Other devices will need the new link.")) return;
  try {
    const view = await api("/api/settings", { regenerate_token: true });
    if (view.access_token) {
      token = view.access_token;
      sessionStorage.setItem("pitboard-token", token);
    }
    toast("New token saved. Reconnect this page if the stream drops.");
    if (snapshot && snapshot.settings && snapshot.settings.lan_active) loadShare();
  } catch (err) {
    toast(err.message);
  }
}

boot();
