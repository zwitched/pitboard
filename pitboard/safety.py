"""Hazardous game commands stay off until the owner arms them on this PC."""

from __future__ import annotations

import re

# Patterns come from the kinds of commands the local API is publicly described
# as accepting without an in-game confirmation: self-destruct, eject, killing
# main power, and opening or unlocking doors, ports, and cargo.
_DANGEROUS = (
    re.compile(r"self[\s_\-]?destruct", re.I),
    re.compile(r"(^|[\s_\-./])eject($|[\s_\-./])", re.I),
    re.compile(r"power[\s_\-.]*(set[\s_\-.]*)?(off|down|shutdown)\b", re.I),
    re.compile(r"(main|master)[\s_\-.]*power[\s_\-.]*(off|down|shutdown)\b", re.I),
    re.compile(r"(door|doors|port|ports|ramp|cargo|hatch|airlock|bay)[\s_\-.]*(open|unlock)", re.I),
    re.compile(r"(open|unlock)[\s_\-.]*(door|doors|port|ports|ramp|cargo|hatch|airlock|bay)", re.I),
    re.compile(r"jettison", re.I),
    re.compile(r"scuttle", re.I),
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def is_dangerous(action_name: str) -> bool:
    text = action_name.replace("-", "_")
    return any(pattern.search(text) for pattern in _DANGEROUS)


def acceptable_action_name(action_name: str) -> bool:
    if not isinstance(action_name, str):
        return False
    if not action_name or len(action_name) > 96:
        return False
    if _CONTROL.search(action_name):
        return False
    return True


def classify_action(action_name: str, category: str | None = None) -> str:
    if category:
        lowered = category.strip().lower()
        if lowered in {"character", "actor", "player", "emote", "emotes", "ship", "vehicle"}:
            return "emote" if lowered.startswith("emote") else ("character" if lowered in {"character", "actor", "player"} else "ship")
    name = action_name.lower()
    if "emote" in name:
        return "emote"
    if name.startswith(("v_", "ship", "vehicle")):
        return "ship"
    return "character"


def prettify_action(action_name: str) -> str:
    text = action_name
    for prefix in ("v_", "emote_", "actor_"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.replace("_", " ").replace(".", " ").strip()
    return " ".join(word.capitalize() for word in text.split()) or action_name
