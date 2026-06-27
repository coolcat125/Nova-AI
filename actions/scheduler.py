import json
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from agent.task_queue import get_queue, TaskPriority
from typing import Optional


from config.paths import get_data_dir

TASKS_FILE: Path = get_data_dir() / "memory" / "scheduled_tasks.json"
POLL_INTERVAL: float = 30.0


def _load_tasks() -> list[dict]:
    try:
        data = TASKS_FILE.read_text(encoding="utf-8")
        return json.loads(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_tasks(tasks: list[dict]) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def _should_run(task: dict) -> bool:
    if not task.get("enabled", True):
        return False

    now = datetime.now()
    schedule = task["schedule"]

    if schedule.startswith("daily:"):
        parts = schedule.split(":")
        if len(parts) < 3:
            return False
        hour, minute = int(parts[1]), int(parts[2])
        if now.hour != hour or now.minute != minute:
            return False
        last_run = task.get("last_run")
        if last_run is None:
            return True
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.date() != now.date()

    elif schedule.startswith("hourly:"):
        parts = schedule.split(":")
        if len(parts) < 2:
            return False
        minute = int(parts[1])
        if now.minute != minute:
            return False
        last_run = task.get("last_run")
        if last_run is None:
            return True
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.hour != now.hour or last_dt.date() != now.date()

    elif schedule.startswith("interval:"):
        parts = schedule.split(":")
        if len(parts) < 2:
            return False
        minutes = int(parts[1])
        last_run = task.get("last_run")
        if last_run is None:
            return True
        last_dt = datetime.fromisoformat(last_run)
        return (now - last_dt).total_seconds() >= minutes * 60

    elif schedule.startswith("at:"):
        target_str = schedule[3:].strip()
        try:
            target_dt = datetime.fromisoformat(target_str)
        except ValueError:
            return False
        if now < target_dt:
            return False
        last_run = task.get("last_run")
        if last_run is not None:
            return False
        return True

    return False


class Scheduler:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock: threading.Lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="Scheduler",
            )
            self._thread.start()
            print("[Scheduler] [OK] Started")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        print("[Scheduler] Stopped")

    def add_task(self, goal: str, schedule: str) -> str:
        task = {
            "id": str(uuid.uuid4())[:8],
            "goal": goal,
            "schedule": schedule,
            "enabled": True,
            "last_run": None,
        }
        tasks = _load_tasks()
        tasks.append(task)
        _save_tasks(tasks)
        print(f"[Scheduler] Task added: [{task['id']}] {goal[:60]}")
        return task["id"]

    def remove_task(self, task_id: str) -> bool:
        tasks = _load_tasks()
        before = len(tasks)
        tasks = [t for t in tasks if t["id"] != task_id]
        if len(tasks) == before:
            return False
        _save_tasks(tasks)
        print(f"[Scheduler] Task removed: [{task_id}]")
        return True

    def list_tasks(self) -> list[dict]:
        return _load_tasks()

    def enable_task(self, task_id: str) -> bool:
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["enabled"] = True
                _save_tasks(tasks)
                print(f"[Scheduler] Task enabled: [{task_id}]")
                return True
        return False

    def disable_task(self, task_id: str) -> bool:
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["enabled"] = False
                _save_tasks(tasks)
                print(f"[Scheduler] Task disabled: [{task_id}]")
                return True
        return False

    def _loop(self) -> None:
        while self._running:
            try:
                tasks = _load_tasks()
                for task in tasks:
                    if _should_run(task):
                        now_iso = datetime.now().isoformat()
                        task["last_run"] = now_iso
                        get_queue().submit(
                            goal=task["goal"],
                            priority=TaskPriority.NORMAL,
                            speak=None,
                        )
                        print(
                            f"[Scheduler] [OK] Dispatched: [{task['id']}] "
                            f"{task['goal'][:60]}"
                        )
                        if task["schedule"].startswith("at:"):
                            task["enabled"] = False
                _save_tasks(tasks)
            except Exception as e:
                print(f"[Scheduler] [WARN] Loop error: {e}")
            time.sleep(POLL_INTERVAL)


_scheduler: Optional[Scheduler] = None
_scheduler_lock: threading.Lock = threading.Lock()


def get_scheduler() -> Scheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = Scheduler()
    return _scheduler
