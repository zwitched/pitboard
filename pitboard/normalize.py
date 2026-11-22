"""Map whatever the stream sends onto a stable dashboard model.

The real game schema is extracted on the owner's machine and is not known
here. Matching is by field name, with an optional data/field_map.json that
wins over the guesses. Paths in that file look like "vehicle.speed_mps".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_DROP = {"value", "current", "amount", "data", "the"}

_FACE = {
    "front": "front",
    "forward": "front",
    "fore": "front",
    "bow": "front",
    "rear": "rear",
    "back": "rear",
    "aft": "rear",
    "left": "left",
    "port": "left",
    "right": "right",
    "starboard": "right",
    "stbd": "right",
    "top": "top",
    "dorsal": "top",
    "bottom": "bottom",
    "ventral": "bottom",
    "belly": "bottom",
}


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    kind: str
    aliases: tuple[tuple[str, ...], ...]
    prefer: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    bar: bool = False


CHARACTER_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("health", "Health", "ratio", (("health",), ("hp",), ("hitpoints",)), ("character", "actor", "player", "vital"), ("vehicle", "ship", "shield", "hull"), True),
    MetricSpec("oxygen", "Oxygen", "ratio", (("oxygen",), ("o2",)), ("character", "actor", "player", "vital"), ("vehicle", "ship"), True),
    MetricSpec("hunger", "Hunger", "ratio", (("hunger",), ("food",)), ("character", "actor", "player"), ("vehicle",), True),
    MetricSpec("thirst", "Thirst", "ratio", (("thirst",), ("hydration",), ("water",)), ("character", "actor", "player"), ("vehicle", "coolant"), True),
    MetricSpec("body_temperature", "Body temp", "temperature", (("body", "temp"), ("body", "temperature"), ("suit", "temp"), ("core", "temp")), ("character", "actor"), ("outside", "ambient", "external")),
    MetricSpec("outside_temperature", "Outside temp", "temperature", (("outside", "temp"), ("outside", "temperature"), ("ambient", "temp"), ("external", "temp"), ("env", "temp")), ("world", "environment"), ("body", "suit")),
    MetricSpec("heart_rate", "Heart rate", "bpm", (("heart", "rate"), ("heartrate",), ("pulse",), ("bpm",)), ("character", "actor"), ("engine",)),
    MetricSpec("balance", "Balance", "ratio", (("balance",),), ("character", "actor"), (), True),
    MetricSpec("radiation", "Radiation", "ratio", (("radiation",),), ("character", "actor"), (), True),
    MetricSpec("intoxication", "Intoxication", "ratio", (("intoxication",), ("toxicity",)), ("character", "actor"), (), True),
    MetricSpec("gravity", "Gravity", "gravity", (("gravity",),), ("character", "actor", "world"), ()),
    MetricSpec("pressure", "Pressure", "pressure", (("pressure",),), ("character", "actor", "world"), ("shield",)),
    MetricSpec("breathable", "Breathable air", "bool", (("breathable",), ("atmosphere",)), ("character", "actor"), ()),
)

SHIP_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("speed", "Speed", "speed", (("speed",), ("velocity",)), ("vehicle", "ship"), ("vertical", "climb", "angular")),
    MetricSpec("vertical_speed", "Vertical speed", "speed", (("vertical", "speed"), ("vertical", "velocity"), ("climb",)), ("vehicle", "ship"), ()),
    MetricSpec("radar_altitude", "Radar altitude", "distance", (("radar", "altitude"), ("altitude",), ("agl",)), ("vehicle", "ship"), ()),
    MetricSpec("g_force", "G-force", "g", (("gforce",), ("g", "force"), ("gload",), ("gee",)), ("vehicle", "ship"), ()),
    MetricSpec("hull", "Hull", "ratio", (("hull",),), ("vehicle", "ship"), ("character", "health"), True),
    MetricSpec("boost", "Boost reserve", "ratio", (("boost",),), ("vehicle", "ship"), ("active",), True),
    MetricSpec("hydrogen", "Hydrogen", "ratio", (("hydrogen",), ("fuel",)), ("vehicle", "ship"), (), True),
)

TOGGLE_SPECS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("landing_gear", (("landing", "gear"), ("gear", "down"), ("gear",))),
    ("lights", (("lights",), ("lamps",), ("headlight",), ("headlights",))),
    ("vtol", (("vtol",),)),
    ("decoupled", (("decoupled",), ("decouple",))),
    ("g_safe", (("gsafe",), ("g", "safe"))),
    ("cruise_control", (("cruise",),)),
    ("proximity_assist", (("proximity",),)),
    ("esp", (("esp",),)),
    ("night_vision", (("night", "vision"), ("nightvision",), ("nvg",))),
    ("doors_open", (("doors", "open"), ("door", "open"), ("hatch", "open"))),
    ("doors_locked", (("doors", "locked"), ("door", "locked"), ("doors", "lock"), ("door", "lock"))),
    ("boost_active", (("boost", "active"), ("boosting",))),
    ("main_power", (("main", "power"), ("master", "power"))),
)


def tokenize(path: str) -> set[str]:
    raw = _CAMEL.sub(r"\1_\2", path).lower()
    parts = {part for part in _SPLIT.split(raw) if part and part not in _DROP and not part.isdigit()}
    if "temperature" in parts:
        parts.add("temp")
    if "temp" in parts:
        parts.add("temperature")
    return parts


def load_field_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.]+", key) or not re.fullmatch(r"[A-Za-z0-9_.]+", value):
            continue
        cleaned[key] = value
    return cleaned


def dig(node, path: str):
    current = node
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


@dataclass
class Leaf:
    path: str
    tokens: set[str]
    value: object


def collect_leaves(node, path: str = "") -> list[Leaf]:
    leaves: list[Leaf] = []

    def walk(item, item_path: str) -> None:
        if isinstance(item, dict):
            for key, value in item.items():
                if "event" in tokenize(key):
                    continue
                child = f"{item_path}.{key}" if item_path else str(key)
                walk(value, child)
            return
        if isinstance(item, list):
            return
        leaves.append(Leaf(item_path, tokenize(item_path), item))

    walk(node, path)
    return leaves


def _as_ratio(value: float) -> float | None:
    if value < 0:
        return None
    if value <= 1.0001:
        return max(0.0, min(1.0, value))
    if value <= 100:
        return max(0.0, min(1.0, value / 100))
    return None


def _tone(kind: str, ratio: float | None, raw, key: str = "") -> str:
    if key in {"radiation", "intoxication"} and ratio is not None:
        if ratio < 0.25:
            return "ok"
        if ratio < 0.5:
            return "warn"
        return "bad"
    if kind == "g" and isinstance(raw, (int, float)):
        if raw < 2:
            return "ok"
        if raw < 5:
            return "warn"
        return "bad"
    if kind == "bpm" and isinstance(raw, (int, float)):
        if raw > 140:
            return "bad"
        if raw > 110:
            return "warn"
        return "ok"
    if ratio is None:
        return "neutral"
    if ratio >= 0.5:
        return "ok"
    if ratio >= 0.25:
        return "warn"
    return "bad"


def _format_metric(spec: MetricSpec, value, path: str) -> dict:
    tokens = tokenize(path)
    ratio = None
    unit = ""
    display = "—"
    raw = value
    if spec.kind == "bool":
        if isinstance(value, bool):
            display = "Yes" if value else "No"
        else:
            raw = None
            display = "—"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if spec.kind == "ratio":
            ratio = _as_ratio(number)
            display = f"{round(ratio * 100)}%" if ratio is not None else _trim(number)
        elif spec.kind == "temperature":
            unit = "°F" if "f" in tokens or "fahrenheit" in tokens else "°C"
            display = f"{number:.1f}"
        elif spec.kind == "bpm":
            unit = "bpm"
            display = str(int(round(number)))
            raw = int(round(number))
        elif spec.kind == "speed":
            if "kmh" in tokens or "kph" in tokens:
                unit = "km/h"
                display = f"{number:.0f}"
            else:
                unit = "m/s" if ("mps" in tokens or "ms" in tokens or "velocity" in tokens or "speed" in tokens) else ""
                display = f"{number:.1f}"
        elif spec.kind == "g":
            unit = "G"
            display = f"{number:.1f}"
        elif spec.kind == "distance":
            unit = "m"
            display = f"{number:.0f}" if abs(number) >= 20 else f"{number:.1f}"
        elif spec.kind == "gravity":
            unit = "G" if "g" in tokens or "gee" in tokens else ""
            display = f"{number:.2f}"
        elif spec.kind == "pressure":
            unit = "kPa" if "kpa" in tokens else "psi" if "psi" in tokens else ""
            display = f"{number:.1f}"
        else:
            display = _trim(number)
    elif isinstance(value, str):
        display = value[:80]
        raw = value
    placeholder = raw is None or (spec.kind != "bool" and display == "—")
    return {
        "label": spec.label,
        "kind": spec.kind,
        "raw": raw,
        "ratio": ratio,
        "display": display,
        "unit": unit,
        "path": path,
        "tone": "idle" if placeholder else _tone(spec.kind, ratio, raw, spec.key),
        "bar": spec.bar and ratio is not None,
    }


def _trim(number: float) -> str:
    if float(number).is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _blank(spec: MetricSpec) -> dict:
    return {
        "label": spec.label,
        "kind": spec.kind,
        "raw": None,
        "ratio": None,
        "display": "—",
        "unit": "",
        "path": None,
        "tone": "idle",
        "bar": False,
    }


def _score(spec: MetricSpec, leaf: Leaf) -> int:
    best = 0
    for alias in spec.aliases:
        if all(part in leaf.tokens for part in alias):
            best = max(best, 10 + 3 * len(alias))
    if best == 0:
        return 0
    if spec.kind == "bool" and not isinstance(leaf.value, bool):
        return 0
    if spec.kind != "bool" and not isinstance(leaf.value, (int, float)):
        return 0
    if isinstance(leaf.value, bool) and spec.kind != "bool":
        return 0
    lowered = leaf.path.lower()
    for hint in spec.prefer:
        if hint in lowered:
            best += 5
    for hint in spec.avoid:
        if hint in lowered:
            best -= 8
    best -= min(len(leaf.path), 80) // 40
    return best


def _assign(leaves: list[Leaf], specs: tuple[MetricSpec, ...], used: set[str], field_map: dict[str, str], root: dict) -> dict[str, dict]:
    assigned: dict[str, dict] = {spec.key: _blank(spec) for spec in specs}
    taken: set[str] = set()
    for spec in specs:
        override = field_map.get(f"{'character' if spec in CHARACTER_SPECS else 'ship'}.{spec.key}")
        if not override:
            continue
        value = dig(root, override)
        if not isinstance(value, (int, float, bool, str)):
            continue
        if spec.kind == "bool" and not isinstance(value, bool):
            continue
        if spec.kind != "bool" and isinstance(value, str):
            continue
        assigned[spec.key] = _format_metric(spec, value, override)
        taken.add(override)
        used.add(override)
    pairs = []
    for spec in specs:
        if assigned[spec.key]["path"]:
            continue
        for leaf in leaves:
            if leaf.path in taken:
                continue
            score = _score(spec, leaf)
            if score >= 10:
                pairs.append((score, spec.key, leaf))
    pairs.sort(key=lambda item: item[0], reverse=True)
    claimed_specs: set[str] = set()
    for _score_value, key, leaf in pairs:
        if key in claimed_specs or leaf.path in taken:
            continue
        spec = next(item for item in specs if item.key == key)
        assigned[key] = _format_metric(spec, leaf.value, leaf.path)
        claimed_specs.add(key)
        taken.add(leaf.path)
        used.add(leaf.path)
    return assigned


def _numeric_leaves(leaves: list[Leaf], used: set[str]) -> list[Leaf]:
    return [
        leaf
        for leaf in leaves
        if leaf.path not in used and isinstance(leaf.value, (int, float)) and not isinstance(leaf.value, bool)
    ]


def _shields(leaves: list[Leaf], used: set[str]) -> dict:
    best: dict[str, tuple[int, float, str]] = {}
    for leaf in _numeric_leaves(leaves, used):
        if "shield" not in leaf.tokens or "power" in leaf.tokens or "weapon" in leaf.tokens:
            continue
        face = "all"
        for token in leaf.tokens:
            if token in _FACE:
                face = _FACE[token]
                break
        score = 2 + (3 if face != "all" else 0)
        ratio = _as_ratio(float(leaf.value))
        current = best.get(face)
        if current is None or score > current[0]:
            best[face] = (score, float(leaf.value) if ratio is None else ratio, leaf.path)
    faces = {}
    ratios = []
    for face, (_score_value, value, path) in best.items():
        used.add(path)
        ratio = value if value <= 1 else _as_ratio(value)
        if face == "all":
            faces["all"] = {"ratio": ratio, "raw": value, "tone": _tone("ratio", ratio, value), "path": path}
        else:
            faces[face] = {"ratio": ratio, "raw": value, "tone": _tone("ratio", ratio, value), "path": path}
        if ratio is not None:
            ratios.append(ratio)
    return {"average": (sum(ratios) / len(ratios)) if ratios else None, "faces": faces}


def _power(leaves: list[Leaf], used: set[str]) -> dict:
    result = {"engines": None, "weapons": None, "shields": None, "main": None, "paths": {}}
    buckets = {
        "engines": (("engine",), ("engines",), ("thrust",)),
        "weapons": (("weapon",), ("weapons",)),
        "shields": (("shield",), ("shields",)),
    }
    for leaf in leaves:
        if leaf.path in used:
            continue
        if "power" not in leaf.tokens and "pwr" not in leaf.tokens:
            continue
        if isinstance(leaf.value, bool) and ({"main", "master"} & leaf.tokens):
            result["main"] = leaf.value
            result["paths"]["main"] = leaf.path
            used.add(leaf.path)
            continue
        if not isinstance(leaf.value, (int, float)) or isinstance(leaf.value, bool):
            continue
        for name, aliases in buckets.items():
            if any(all(part in leaf.tokens for part in alias) for alias in aliases):
                ratio = _as_ratio(float(leaf.value))
                result[name] = ratio if ratio is not None else float(leaf.value)
                result["paths"][name] = leaf.path
                used.add(leaf.path)
                break
    return result


def _toggles(leaves: list[Leaf], used: set[str]) -> dict[str, bool | None]:
    found: dict[str, bool | None] = {key: None for key, _aliases in TOGGLE_SPECS}
    best: dict[str, tuple[int, Leaf]] = {}
    for key, aliases in TOGGLE_SPECS:
        for leaf in leaves:
            if leaf.path in used or not isinstance(leaf.value, bool):
                continue
            score = 0
            for alias in aliases:
                if all(part in leaf.tokens for part in alias):
                    score = max(score, 10 + 3 * len(alias))
            if "night" in leaf.tokens and key == "lights":
                score = 0
            if score >= 10 and (key not in best or score > best[key][0]):
                best[key] = (score, leaf)
    for key, (_score_value, leaf) in best.items():
        value = leaf.value
        if key == "decoupled" and "coupled" in leaf.tokens and "decoupled" not in leaf.tokens:
            value = not value
        found[key] = bool(value)
        used.add(leaf.path)
    return found


def _match_text(leaves: list[Leaf], aliases: tuple[tuple[str, ...], ...], prefer: tuple[str, ...], avoid: tuple[str, ...], used: set[str]) -> tuple[str, str] | None:
    best = None
    for leaf in leaves:
        if leaf.path in used or not isinstance(leaf.value, str) or not leaf.value.strip():
            continue
        score = 0
        for alias in aliases:
            if all(part in leaf.tokens for part in alias):
                score = max(score, 10 + 3 * len(alias))
        if score == 0:
            continue
        lowered = leaf.path.lower()
        for hint in prefer:
            if hint in lowered:
                score += 5
        for hint in avoid:
            if hint in lowered:
                score -= 6
        if best is None or score > best[0]:
            best = (score, leaf)
    if best is None or best[0] < 10:
        return None
    used.add(best[1].path)
    return best[1].value.strip()[:80], best[1].path


def _posture(leaves: list[Leaf], used: set[str]) -> str | None:
    matched = _match_text(
        leaves,
        (("posture",), ("stance",)),
        ("character", "actor", "player"),
        ("vehicle", "ship"),
        used,
    )
    if matched:
        return _normalize_posture(matched[0])
    for leaf in leaves:
        if leaf.path in used or not isinstance(leaf.value, bool):
            continue
        if "eva" in leaf.tokens and leaf.value:
            used.add(leaf.path)
            return "eva"
        if "seated" in leaf.tokens or ({"in", "seat"} <= leaf.tokens):
            used.add(leaf.path)
            return "seated" if leaf.value else "on_foot"
    return None


def _normalize_posture(text: str) -> str:
    lowered = text.lower()
    if "eva" in lowered:
        return "eva"
    if "seat" in lowered or "cockpit" in lowered:
        return "seated"
    if "foot" in lowered or "ground" in lowered or "walk" in lowered:
        return "on_foot"
    return text[:40]


def _position(node, path: str = "") -> dict | None:
    best = None

    def walk(item, item_path: str) -> None:
        nonlocal best
        if isinstance(item, dict):
            lowered = {str(key).lower(): key for key in item}
            if {"x", "y", "z"} <= set(lowered):
                coords = {}
                ok = True
                for axis in ("x", "y", "z"):
                    raw = item[lowered[axis]]
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                        coords[axis] = float(raw)
                    else:
                        ok = False
                if ok:
                    score = 1
                    haystack = item_path.lower()
                    if any(hint in haystack for hint in ("character", "actor", "player", "pos")):
                        score += 5
                    if any(hint in haystack for hint in ("vehicle", "ship")):
                        score -= 4
                    if best is None or score > best[0]:
                        best = (score, coords)
            for key, value in item.items():
                if "event" in tokenize(str(key)):
                    continue
                child = f"{item_path}.{key}" if item_path else str(key)
                walk(value, child)

    walk(node, path)
    return None if best is None else best[1]


def _weapons(leaves: list[Leaf], used: set[str]) -> dict:
    result = {"ready": None, "total": None, "group": None, "gimbals_locked": None, "paths": {}}

    def take_int(key: str, aliases: tuple[tuple[str, ...], ...]) -> None:
        best = None
        for leaf in leaves:
            if leaf.path in used or isinstance(leaf.value, bool) or not isinstance(leaf.value, (int, float)):
                continue
            score = 0
            for alias in aliases:
                if all(part in leaf.tokens for part in alias):
                    score = max(score, 10 + 3 * len(alias))
            if "weapon" in leaf.tokens or "weapons" in leaf.tokens or "gimbal" in leaf.tokens:
                score += 4
            if score >= 10 and (best is None or score > best[0]):
                best = (score, leaf)
        if best:
            result[key] = int(best[1].value)
            result["paths"][key] = best[1].path
            used.add(best[1].path)

    take_int("ready", (("ready",),))
    take_int("total", (("total",), ("count",)))
    take_int("group", (("group",),))
    for leaf in leaves:
        if leaf.path in used or not isinstance(leaf.value, bool):
            continue
        if "gimbal" in leaf.tokens or "gimbals" in leaf.tokens:
            locked = leaf.value
            if "free" in leaf.tokens or "unlocked" in leaf.tokens:
                locked = not leaf.value
            result["gimbals_locked"] = locked
            result["paths"]["gimbals"] = leaf.path
            used.add(leaf.path)
            break
    return result


def _countermeasures(leaves: list[Leaf], used: set[str]) -> dict:
    found = {"decoys": None, "noise": None}
    aliases = {"decoys": (("decoy",), ("decoys",), ("flare",), ("flares",)), "noise": (("noise",), ("chaff",))}
    for key, options in aliases.items():
        for leaf in leaves:
            if leaf.path in used or isinstance(leaf.value, bool) or not isinstance(leaf.value, (int, float)):
                continue
            if any(all(part in leaf.tokens for part in alias) for alias in options):
                found[key] = int(leaf.value)
                used.add(leaf.path)
                break
    return found


def normalize(raw: dict, *, field_map: dict[str, str] | None = None, events: list | None = None) -> dict:
    field_map = field_map or {}
    root = raw or {}
    leaves = collect_leaves(root)
    used: set[str] = set()
    character_metrics = _assign(leaves, CHARACTER_SPECS, used, field_map, root)
    ship_metrics = _assign(leaves, SHIP_SPECS, used, field_map, root)
    shields = _shields(leaves, used)
    power = _power(leaves, used)
    toggles = _toggles(leaves, used)
    if toggles.get("main_power") is None and power.get("main") is not None:
        toggles["main_power"] = power["main"]
    weapons = _weapons(leaves, used)
    countermeasures = _countermeasures(leaves, used)
    posture = _posture(leaves, used)
    role = _match_text(leaves, (("crew", "role"), ("role",)), ("character", "actor", "player"), ("vehicle", "ship"), used)
    location = _match_text(
        leaves,
        (("location",), ("location", "name"), ("zone",), ("place",)),
        ("character", "actor", "player"),
        ("vehicle", "ship"),
        used,
    )
    manufacturer = _match_text(leaves, (("manufacturer",), ("maker",)), ("vehicle", "ship"), ("character",), used)
    model = _match_text(leaves, (("model",),), ("vehicle", "ship"), ("character",), used)
    ship_name = _match_text(
        leaves,
        (("ship", "name"), ("vehicle", "name"), ("shipname",)),
        ("vehicle", "ship"),
        ("character", "location"),
        used,
    )
    flight_mode = _match_text(
        leaves,
        (("flight", "mode"), ("master", "mode"), ("mode",)),
        ("vehicle", "ship"),
        ("character",),
        used,
    )
    ship_role = _match_text(leaves, (("role",),), ("vehicle", "ship"), ("character", "crew"), used)
    seated_leaf = None
    for leaf in leaves:
        if leaf.path in used or not isinstance(leaf.value, bool):
            continue
        if "seated" in leaf.tokens or leaf.tokens == {"seat"}:
            seated_leaf = leaf
            used.add(leaf.path)
            break
    if posture is None and seated_leaf is not None:
        posture = "seated" if seated_leaf.value else "on_foot"
    flying = None
    landed = None
    for leaf in leaves:
        if leaf.path in used or not isinstance(leaf.value, bool):
            continue
        if flying is None and "flying" in leaf.tokens and "time" not in leaf.tokens:
            flying = leaf.value
            used.add(leaf.path)
        elif landed is None and "landed" in leaf.tokens:
            landed = leaf.value
            used.add(leaf.path)

    if posture == "seated":
        aboard = True
    elif posture in {"on_foot", "eva"}:
        aboard = False
    elif seated_leaf is not None:
        aboard = bool(seated_leaf.value)
    else:
        aboard = None

    identified = any(
        value
        for value in (
            ship_name[0] if ship_name else None,
            model[0] if model else None,
            manufacturer[0] if manufacturer else None,
            ship_metrics["hull"]["raw"],
            ship_metrics["speed"]["raw"],
            shields["average"],
        )
    )
    turret = {"occupied": None, "yaw_deg": None, "pitch_deg": None}
    for leaf in leaves:
        if leaf.path in used:
            continue
        if "yaw" in leaf.tokens and isinstance(leaf.value, (int, float)) and not isinstance(leaf.value, bool):
            turret["yaw_deg"] = float(leaf.value)
            used.add(leaf.path)
        elif "pitch" in leaf.tokens and isinstance(leaf.value, (int, float)) and not isinstance(leaf.value, bool):
            turret["pitch_deg"] = float(leaf.value)
            used.add(leaf.path)
        elif "occupied" in leaf.tokens and isinstance(leaf.value, bool):
            turret["occupied"] = leaf.value
            used.add(leaf.path)
    feedback = None
    for leaf in leaves:
        if leaf.path in used:
            continue
        if "intensity" in leaf.tokens and ("force" in leaf.tokens or "feedback" in leaf.tokens):
            if isinstance(leaf.value, (int, float)) and not isinstance(leaf.value, bool):
                feedback = float(leaf.value)
                used.add(leaf.path)
                break

    unmapped = []
    for leaf in leaves:
        if leaf.path in used:
            continue
        if leaf.tokens & {"frame", "index", "timestamp", "unix", "sequence"}:
            continue
        if isinstance(leaf.value, (dict, list)) or leaf.value in (None, "", 0, 0.0, False):
            continue
        shown = leaf.value
        if isinstance(shown, float):
            shown = round(shown, 3)
        unmapped.append({"path": leaf.path, "value": shown if not isinstance(shown, str) else shown[:80]})
        if len(unmapped) >= 40:
            break

    posture_label = {"seated": "Seated", "on_foot": "On foot", "eva": "EVA"}.get(posture or "", posture)
    return {
        "character": {
            "posture": posture,
            "posture_label": posture_label,
            "crew_role": None if role is None else role[0],
            "location": None if location is None else location[0],
            "position": _position(root),
            "metrics": character_metrics,
        },
        "ship": {
            "identified": bool(identified),
            "aboard": aboard,
            "name": None if ship_name is None else ship_name[0],
            "manufacturer": None if manufacturer is None else manufacturer[0],
            "model": None if model is None else model[0],
            "role": None if ship_role is None else ship_role[0],
            "mode": None if flight_mode is None else flight_mode[0],
            "flying": flying,
            "landed": landed,
            "metrics": ship_metrics,
            "shields": shields,
            "power": {key: power[key] for key in ("engines", "weapons", "shields", "main")},
            "countermeasures": countermeasures,
            "weapons": {key: weapons[key] for key in ("ready", "total", "group", "gimbals_locked")},
            "toggles": toggles,
            "turret": turret,
            "force_feedback": feedback,
        },
        "events": list(events or []),
        "unmapped": unmapped,
    }


def extract_events(frame: dict) -> list[dict]:
    found: list[dict] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else key
                if "event" in tokenize(key):
                    if isinstance(value, list):
                        for item in value:
                            event = _event_from(item)
                            if event:
                                found.append(event)
                    else:
                        event = _event_from(value)
                        if event:
                            found.append(event)
                else:
                    walk(value, child)
        elif isinstance(node, list) and "event" in tokenize(path):
            for item in node:
                event = _event_from(item)
                if event:
                    found.append(event)

    walk(frame or {}, "")
    return found[-20:]


def _event_from(item) -> dict | None:
    if isinstance(item, str) and item.strip():
        return {"name": item.strip()[:80], "detail": "", "at": None}
    if not isinstance(item, dict):
        return None
    name = ""
    for key in ("name", "event", "type", "id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()[:80]
            break
    if not name:
        return None
    detail = ""
    for key in ("detail", "message", "description", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            detail = value.strip()[:160]
            break
    at = None
    for key in ("timestamp_unix_ms", "timestamp", "time", "at"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            at = int(value)
            break
    return {"name": name, "detail": detail, "at": at}
