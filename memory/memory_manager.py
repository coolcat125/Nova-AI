from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

from config.paths import get_data_dir

_MEMORY_FILE = get_data_dir() / "memory" / "long_term.json"
_write_lock = Lock()

MAX_ENTRY_LEN = 380
MAX_MEMORY_BYTES = 2200

_VALID_CATEGORIES = frozenset({
    "identity",
    "preferences",
    "projects",
    "relationships",
    "wishes",
    "notes",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _blank() -> dict:
    return {cat: {} for cat in _VALID_CATEGORIES}


def _collect_entries(mem: dict) -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for category, items in mem.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                out.append((category, key, entry))
    return out


def _cap_entry(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_ENTRY_LEN:
        return val[:MAX_ENTRY_LEN].rstrip() + "..."
    return val


def _merge(target: dict, patch: dict) -> bool:
    dirty = False
    for k, v in patch.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue

        if isinstance(v, dict) and "value" not in v:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
                dirty = True
            if _merge(target[k], v):
                dirty = True
        else:
            raw = v["value"] if isinstance(v, dict) else v
            capped = _cap_entry(str(raw))
            stamp = datetime.now().strftime("%Y-%m-%d")
            prev = target.get(k, {})
            if not isinstance(prev, dict) or prev.get("value") != capped:
                target[k] = {"value": capped, "updated": stamp}
                dirty = True
    return dirty


def _shrink(mem: dict) -> dict:
    blob = json.dumps(mem, ensure_ascii=False)
    if len(blob) <= MAX_MEMORY_BYTES:
        return mem

    entries = _collect_entries(mem)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))

    for cat, key, _ in entries:
        if len(json.dumps(mem, ensure_ascii=False)) <= MAX_MEMORY_BYTES:
            break
        del mem[cat][key]
        print(f"[Memory] [trash]  Trimmed {cat}/{key}")
    return mem


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_memory() -> dict:
    if not _MEMORY_FILE.exists():
        return _blank()

    with _write_lock:
        try:
            raw = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                template = _blank()
                for cat in template:
                    raw.setdefault(cat, {})
                return raw
            return _blank()
        except Exception as exc:
            print(f"[Memory] [WARN] Load error: {exc}")
            return _blank()


def save_memory(mem: dict) -> None:
    if not isinstance(mem, dict):
        return
    mem = _shrink(mem)
    _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        _MEMORY_FILE.write_text(
            json.dumps(mem, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_memory(patch: dict) -> dict:
    if not isinstance(patch, dict) or not patch:
        return load_memory()
    mem = load_memory()
    if _merge(mem, patch):
        save_memory(mem)
        print(f"[Memory] Saved: {list(patch.keys())}")
    return mem


def remember(key: str, value: str, category: str = "notes") -> str:
    if category not in _VALID_CATEGORIES:
        category = "notes"
    key = str(key).strip()[:100]
    value = str(value).strip()[:MAX_ENTRY_LEN]
    if not key:
        return "Key cannot be empty."
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    key = str(key).strip()[:100]
    if not key:
        return "Key cannot be empty."
    mem = load_memory()
    bucket = mem.get(category, {})
    if key in bucket:
        del bucket[key]
        mem[category] = bucket
        save_memory(mem)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_memory_for_prompt(mem: Optional[dict]) -> str:
    if not mem:
        return ""

    lines: list[str] = []

    identity = mem.get("identity", {})
    id_order = [
        "name", "age", "birthday", "city", "job",
        "language", "school", "nationality",
    ]
    for field in id_order:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for field, entry in identity.items():
        if field in id_order:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{field.replace('_', ' ').title()}: {val}")

    prefs = mem.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for k, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {k.replace('_', ' ').title()}: {val}")

    projects = mem.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for k, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {k.replace('_', ' ').title()}: {val}")

    rels = mem.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for k, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {k.replace('_', ' ').title()}: {val}")

    wishes = mem.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for k, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {k.replace('_', ' ').title()}: {val}")

    notes = mem.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for k, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {k}: {val}")

    if not lines:
        return ""

    body = "\n".join(lines)
    header = "[WHAT YOU KNOW ABOUT THIS PERSON  --  use naturally, never recite like a list]\n"
    result = header + body
    if len(result) > 2000:
        result = result[:1997] + "..."
    return result + "\n"
