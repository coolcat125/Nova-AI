from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from config.paths import get_data_dir

SESSIONS_DIR = get_data_dir() / "memory" / "sessions"
INDEX_FILE = SESSIONS_DIR / "index.json"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _fmt_date(iso: str) -> str:
    try:
        t = time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        return time.strftime("%b %d  %H:%M", t)
    except Exception:
        return iso[:10]


def _title_from_messages(messages: list) -> str:
    return "New session"


class SessionManager:
    def __init__(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._current_id: Optional[str] = None

    # -- index helpers --

    def _read_index(self) -> dict:
        if INDEX_FILE.exists():
            try:
                return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"sessions": []}

    def _write_index(self, data: dict):
        INDEX_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- session CRUD --

    def create_session(self, title: Optional[str] = None) -> str:
        sid = uuid.uuid4().hex[:12]
        now = _now_iso()
        entry = {
            "id": sid,
            "title": title or "New session",
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        self._write_session_file(sid, {"messages": []})
        self._current_id = sid
        idx = self._read_index()
        idx["sessions"].insert(0, entry)
        self._write_index(idx)
        return sid

    def save_messages(self, sid: str, messages: list, title: Optional[str] = None):
        self._write_session_file(sid, {"messages": messages})
        now = _now_iso()
        idx = self._read_index()
        for e in idx["sessions"]:
            if e["id"] == sid:
                e["updated_at"] = now
                e["message_count"] = len(messages)
                if title is not None:
                    e["title"] = title
                elif messages and e.get("title", "").startswith("New session"):
                    e["title"] = _title_from_messages(messages)
                break
        self._write_index(idx)

    def load_messages(self, sid: str) -> list:
        path = SESSIONS_DIR / f"{sid}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", [])
        except Exception:
            return []

    def delete_session(self, sid: str):
        path = SESSIONS_DIR / f"{sid}.json"
        if path.exists():
            path.unlink()
        idx = self._read_index()
        idx["sessions"] = [e for e in idx["sessions"] if e["id"] != sid]
        self._write_index(idx)
        if self._current_id == sid:
            self._current_id = None

    def list_sessions(self) -> list[dict]:
        return self._read_index().get("sessions", [])

    def rename_session(self, sid: str, title: str):
        idx = self._read_index()
        for e in idx["sessions"]:
            if e["id"] == sid:
                e["title"] = title
                break
        self._write_index(idx)

    # -- current session --

    def get_current_id(self) -> Optional[str]:
        return self._current_id

    def set_current_id(self, sid: str):
        self._current_id = sid

    # -- file I/O --

    def _write_session_file(self, sid: str, data: dict):
        (SESSIONS_DIR / f"{sid}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
