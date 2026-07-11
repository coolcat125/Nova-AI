from __future__ import annotations

import asyncio
import re
import threading
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import sounddevice as sd
import websockets.exceptions
from google import genai
from google.genai import types

from config.paths import get_data_dir
from providers import call_llm
from ui import NovaUI
from memory.memory_manager import (
    load_memory,
    update_memory,
    format_memory_for_prompt,
    remember,
)
from actions.scheduler import get_scheduler
from version import __version__
from update import check_for_update_async

from actions.file_processor import file_processor
from actions.flight_finder import flight_finder
from actions.open_app import open_app
from actions.weather_report import weather_action
from actions.send_message import send_message
from actions.reminder import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video import youtube_video
from actions.desktop import desktop_control
from actions.browser_control import browser_control
from actions.file_controller import file_controller
from actions.code_helper import code_helper
from actions.dev_agent import dev_agent
from actions.web_search import web_search as web_search_action
from actions.computer_control import computer_control
from actions.game_updater import game_updater
from actions.web_search import _gemini_search


# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------

_env_path = get_data_dir() / ".env"

def _load_env():
    if _env_path.exists():
        for _ in range(2):
            try:
                _env_path.read_bytes()
                break
            except OSError:
                time.sleep(0.5)
        try:
            load_dotenv(_env_path, override=True)
        except OSError:
            print("[main] Warning: could not load .env")

_load_env()


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"

LIVE_MODEL = "models/gemini-2.5-flash-native-audio-latest"
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        try:
            for line in _env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY=") and "=" in line:
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        key = val
                        break
        except Exception:
            pass
    if not key:
        print("[Nova] [WARN] GEMINI_API_KEY not found in environment")
    return key


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Nova, an advanced AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results -- always call the appropriate tool."
        )


_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Tool declarations (Gemini function calling schema)
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool -- never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')",
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information. Use specific modes for targeted results.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) | compare | news | research | price"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."},
            },
            "required": ["receiver", "message_text", "platform"],
        },
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"},
            },
            "required": ["date", "time", "message"],
        },
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": [],
        },
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "Supports multi-monitor setups -- captures all connected displays. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT -- the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture all displays, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."},
            },
            "required": [],
        },
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "ARRAY", "items": {"type": "STRING"}, "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic -- use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": [],
        },
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"],
        },
    },
    {
        "name": "shutdown_nova",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Nova. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "file_processor",
        "description": (
            "Processes any file that the user has uploaded or dropped onto the interface. "
            "Use this when the user refers to an uploaded file and wants an action on it. "
            "Supports: images (describe/ocr/resize/compress/convert), "
            "PDFs (summarize/extract_text/to_word), "
            "Word docs & text files (summarize/fix/reformat/translate), "
            "CSV/Excel (analyze/stats/filter/sort/convert), "
            "JSON/XML (validate/format/analyze), "
            "code files (explain/review/fix/optimize/run/document/test), "
            "audio (transcribe/trim/convert/info), "
            "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
            "archives (list/extract), "
            "presentations (summarize/extract_text). "
            "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
            "If the user's command is ambiguous, pick the most logical action for that file type."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "file_path": {
                    "type": "STRING",
                    "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file.",
                },
                "action": {
                    "type": "STRING",
                    "description": (
                        "What to do with the file. Examples by type:\n"
                        "image: describe | ocr | resize | compress | convert | info\n"
                        "pdf: summarize | extract_text | to_word | info\n"
                        "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                        "csv/excel: analyze | stats | filter | sort | convert | info\n"
                        "json: validate | format | analyze | to_csv\n"
                        "code: explain | review | fix | optimize | run | document | test\n"
                        "audio: transcribe | trim | convert | info\n"
                        "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                        "archive: list | extract\n"
                        "pptx: summarize | extract_text | analyze"
                    ),
                },
                "instruction": {
                    "type": "STRING",
                    "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'",
                },
                "format": {
                    "type": "STRING",
                    "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'",
                },
                "width":      {"type": "INTEGER", "description": "Target width for image resize"},
                "height":     {"type": "INTEGER", "description": "Target height for image resize"},
                "scale":      {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
                "quality":    {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
                "start":      {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
                "end":        {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
                "timestamp":  {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
                "column":     {"type": "STRING",  "description": "Column name for CSV filter/sort"},
                "value":      {"type": "STRING",  "description": "Filter value for CSV filter"},
                "condition":  {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
                "ascending":  {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
                "save":       {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
                "destination": {"type": "STRING", "description": "Output folder for archive extract"},
            },
            "required": [],
        },
    },
    {
        "name": "recall_memory",
        "description": (
            "Retrieves everything Nova knows about the user from long-term memory. "
            "Call this when the user asks 'what do you remember about me?' or similar. "
            "Reads the saved memory and speaks it conversationally. "
            "Use this to answer memory questions instead of guessing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving -- just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity -- name, age, birthday, city, job, language, nationality | "
                        "preferences -- favorite food/color/music/film/game/sport, hobbies | "
                        "projects -- active projects, goals, things being built | "
                        "relationships -- friends, family, partner, colleagues | "
                        "wishes -- future plans, things to buy, travel dreams | "
                        "notes -- habits, schedule, anything else worth remembering"
                    ),
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Alex, pizza, older sister)"},
            },
            "required": ["category", "key", "value"],
        },
    },
]


# ---------------------------------------------------------------------------
# Standalone tool executor (for non-Gemini voice pipeline)
# ---------------------------------------------------------------------------

def _execute_tool_standalone(name: str, args: dict, speak_fn=None) -> str:
    """Execute a tool by name and return result string. Used by VoicePipeline."""
    try:
        if name == "recall_memory":
            memory = load_memory()
            mem_str = format_memory_for_prompt(memory)
            return mem_str if mem_str else "No memories stored."

        if name == "save_memory":
            category = args.get("category", "notes")
            key = args.get("key", "")
            value = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
            return "Saved."

        if name == "open_app":
            r = open_app(parameters=args)
            return r or f"Opened {args.get('app_name')}."

        if name == "weather_report":
            r = weather_action(parameters=args)
            return r or "Weather delivered."

        if name == "browser_control":
            r = browser_control(parameters=args)
            return r or "Done."

        if name == "file_controller":
            r = file_controller(parameters=args)
            return r or "Done."

        if name == "send_message":
            r = send_message(parameters=args)
            return r or f"Message sent to {args.get('receiver')}."

        if name == "reminder":
            r = reminder(parameters=args)
            return r or "Reminder set."

        if name == "youtube_video":
            r = youtube_video(parameters=args)
            return r or "Done."

        if name == "screen_process":
            threading.Thread(target=screen_process, kwargs={"parameters": args}, daemon=True).start()
            return "Vision module activated."

        if name == "computer_settings":
            r = computer_settings(parameters=args)
            return r or "Done."

        if name == "desktop_control":
            r = desktop_control(parameters=args)
            return r or "Done."

        if name == "code_helper":
            r = code_helper(parameters=args, speak=speak_fn)
            return r or "Done."

        if name == "dev_agent":
            r = dev_agent(parameters=args, speak=speak_fn)
            return r or "Done."

        if name == "agent_task":
            from agent.task_queue import get_queue, TaskPriority
            priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
            priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
            task_id = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=speak_fn)
            return f"Task started (ID: {task_id})."

        if name == "web_search":
            r = web_search_action(parameters=args)
            return r or "Done."

        if name == "file_processor":
            r = file_processor(parameters=args, speak=speak_fn)
            return r or "Done."

        if name == "computer_control":
            r = computer_control(parameters=args)
            return r or "Done."

        if name == "game_updater":
            r = game_updater(parameters=args, speak=speak_fn)
            return r or "Done."

        if name == "flight_finder":
            r = flight_finder(parameters=args)
            return r or "Done."

        if name == "shutdown_nova":
            import time as _time
            def _shutdown():
                _time.sleep(3)
                os._exit(0)
            threading.Thread(target=_shutdown, daemon=True).start()
            return "Shutting down."

        return f"Unknown tool: {name}"

    except Exception as e:
        traceback.print_exc()
        return f"Tool '{name}' failed: {e}"


# ---------------------------------------------------------------------------
# NovaLive -- Gemini Live audio session
# ---------------------------------------------------------------------------

class NovaLive:

    def __init__(self, ui: NovaUI):
        self.ui = ui
        self.session = None
        self.pipeline = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._turn_done_event: Optional[asyncio.Event] = None
        self._bridge_turn = False
        self._reset_requested = False
        self._language_detected = False
        self.ui.on_text_command = self._on_text_command

    def _redact_args(self, args: dict) -> dict:
        sensitive_keys = {"api_key", "password", "token", "secret", "key", "code", "content", "message"}
        redacted = {}
        for k, v in args.items():
            if any(s in k.lower() for s in sensitive_keys):
                redacted[k] = "***" if isinstance(v, str) and len(v) > 4 else v
            else:
                redacted[k] = v
        return redacted

    # -- public helpers -----------------------------------------------------

    def reset(self):
        self._reset_requested = True

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        self.ui.set_state("SPEAKING" if value else "LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        if self.ui.deafened:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True,
            ),
            self._loop,
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} -- {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    # -- text command from UI -----------------------------------------------

    def _on_text_command(self, text: str):
        if not self._language_detected:
            self._detect_and_save_language(text)

        provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

        if provider == "gemini":
            if not self._loop or not self.session:
                return
            asyncio.run_coroutine_threadsafe(
                self.session.send_client_content(
                    turns={"parts": [{"text": text}]},
                    turn_complete=True,
                ),
                self._loop,
            )
        else:
            if hasattr(self, 'pipeline') and self.pipeline and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.pipeline.process_text(text),
                    self._loop,
                )
            else:
                print("[Nova] Pipeline not ready yet.")

    def _detect_and_save_language(self, text: str):
        """Detect language from first spoken input and save to memory."""
        memory = load_memory()
        existing_lang = memory.get("identity", {}).get("language", {}).get("value", "")
        if existing_lang:
            self._language_detected = True
            return

        try:
            from langdetect import detect
            lang_code = detect(text)
            lang_map = {
                "en": "English", "es": "Spanish", "fr": "French",
                "de": "German", "it": "Italian", "pt": "Portuguese",
                "ru": "Russian", "ja": "Japanese", "ko": "Korean",
                "zh": "Chinese", "ar": "Arabic", "hi": "Hindi",
                "tr": "Turkish", "nl": "Dutch", "pl": "Polish",
                "sv": "Swedish", "da": "Danish", "no": "Norwegian",
                "fi": "Finnish", "uk": "Ukrainian", "cs": "Czech",
                "el": "Greek", "he": "Hebrew", "th": "Thai",
                "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay",
            }
            lang_name = lang_map.get(lang_code, lang_code)
            remember("language", lang_name, category="identity")
            print(f"[Nova] Detected language: {lang_name} ({lang_code})")
        except ImportError:
            print("[Nova] langdetect not installed, skipping language detection")
        except Exception as e:
            print(f"[Nova] Language detection failed: {e}")
        finally:
            self._language_detected = True

    # -- config -------------------------------------------------------------

    def _build_config(self, briefing: str = "") -> types.LiveConnectConfig:
        from datetime import datetime

        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y -- %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        if briefing:
            parts.append(f"[STARTUP BRIEFING]\n{briefing}\nSpeak this briefing to the user now as your first message. Do not ask questions.\n")
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=os.getenv("GEMINI_VOICE", "Aoede"),
                    )
                )
            ),
        )

    # -- morning briefing ----------------------------------------------------

    async def _build_briefing(self) -> str:
        """Build briefing string for every launch."""
        from datetime import datetime

        memory = load_memory()
        city = memory.get("identity", {}).get("city", {}).get("value", "")

        briefing_parts = []

        now = datetime.now()
        hour = now.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"
        briefing_parts.append(f"{greeting}. Here is your briefing.")

        try:
            time_str = now.strftime("%I:%M %p")
            date_str = now.strftime("%A, %B %d, %Y")
            briefing_parts.append(f"It is {time_str} on {date_str}.")
        except Exception:
            pass

        if city:
            try:
                weather_query = f"current weather in {city}"
                weather_result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _gemini_search(weather_query)
                )
                briefing_parts.append(f"Weather in {city}: {weather_result[:300]}")
            except Exception as e:
                print(f"[Briefing] Weather fetch failed: {e}")

        try:
            news_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _gemini_search("top news headlines today")
            )
            briefing_parts.append(f"Today's top news: {news_result[:400]}")
        except Exception as e:
            print(f"[Briefing] News fetch failed: {e}")

        return " ".join(briefing_parts)

    # -- tool execution -----------------------------------------------------

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[Nova] {name}  {self._redact_args(args)}")
        self.ui.set_state("EXECUTING")

        # tool confirmation dialog
        if getattr(self.ui._win, "_tool_confirm", False):
            if name not in ("recall_memory", "save_memory"):
                allowed = await self.ui._win._confirm_tool_dialog(name, args)
                if not allowed:
                    self.ui.write_log(f"[DENIED] {name}")
                    self.ui.set_state("LISTENING")
                    return types.FunctionResponse(
                        id=fc.id, name=name,
                        response={"result": "denied by user", "silent": True},
                    )

        # -- memory tools (handled inline) ----------------------------------

        if name == "recall_memory":
            memory = load_memory()
            mem_str = format_memory_for_prompt(memory)
            if mem_str:
                self.speak(
                    mem_str.replace(
                        "[WHAT YOU KNOW ABOUT THIS PERSON -- use naturally, never recite like a list]\n",
                        "",
                    )
                )
            else:
                self.speak("I don't have any stored memories about you yet.")
            self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "recalled", "silent": True},
            )

        if name == "save_memory":
            category = args.get("category", "notes")
            key = args.get("key", "")
            value = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] save_memory: {category}/{key} = {value}")
            self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True},
            )

        # -- action tools ---------------------------------------------------

        loop = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(parameters=args)
                )
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None, lambda: weather_action(parameters=args)
                )
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(parameters=args)
                )
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None, lambda: file_controller(parameters=args)
                )
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(
                    None, lambda: send_message(parameters=args)
                )
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(
                    None, lambda: reminder(parameters=args)
                )
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None, lambda: youtube_video(parameters=args)
                )
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args},
                    daemon=True,
                ).start()
                result = "Vision module activated."

            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None, lambda: computer_settings(parameters=args)
                )
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None, lambda: desktop_control(parameters=args)
                )
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None, lambda: code_helper(parameters=args, speak=self.speak)
                )
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None, lambda: dev_agent(parameters=args, speak=self.speak)
                )
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority

                priority_map = {
                    "low": TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high": TaskPriority.HIGH,
                }
                priority = priority_map.get(
                    args.get("priority", "normal").lower(), TaskPriority.NORMAL
                )
                task_id = get_queue().submit(
                    goal=args.get("goal", ""), priority=priority, speak=self.speak
                )
                result = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args)
                )
                result = r or "Done."
                if len(result) > 120:
                    query = args.get("query", "Search Results")
                    self.ui._win.update_dynamic_content(result, title=query)

            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None, lambda: file_processor(parameters=args, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=args)
                )
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(
                    None, lambda: game_updater(parameters=args, speak=self.speak)
                )
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None, lambda: flight_finder(parameters=args)
                )
                result = r or "Done."

            elif name == "shutdown_nova":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")

                def _shutdown():
                    time.sleep(3)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        summary = str(result)[:120].replace("\n", " ").replace("\r", "")
        self.ui.write_log(f"[OK] {name}: {summary}")
        self.ui.set_state("DONE")
        asyncio.create_task(self._delayed_idle())

        print(f"[Nova] {name}  ->  {summary[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result},
        )

    async def _delayed_idle(self, delay: float = 2.5):
        await asyncio.sleep(delay)
        self.ui.set_state("LISTENING")

    # -- audio I/O ----------------------------------------------------------

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[Nova] Mic started")
        self.ui.write_log("[Nova] Mic started")
        loop = asyncio.get_event_loop()
        stream = None

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                nova_speaking = self._is_speaking
            if not nova_speaking and not self.ui.muted:
                data = indata.tobytes()

                def _put():
                    try:
                        self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
                    except asyncio.QueueFull:
                        pass

                loop.call_soon_threadsafe(_put)

        try:
            while True:
                if self.ui.muted:
                    if stream is not None:
                        stream.close()
                        stream = None
                    await asyncio.sleep(0.5)
                    continue
                if stream is None:
                    stream = sd.InputStream(
                        samplerate=SEND_SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype="int16",
                        blocksize=CHUNK_SIZE,
                        callback=callback,
                    )
                    stream.start()
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[Nova] Mic error: {e}")
            if stream is not None:
                stream.close()
            raise

    async def _receive_audio(self):
        print("[Nova] Recv started")
        self.ui.write_log("[Nova] Recv started")
        out_buf: list[str] = []
        in_buf: list[str] = []
        spoken_buf: list[str] = []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        if not self._bridge_turn:
                            self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        txt = None
                        spoken = False
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            spoken = True
                        elif sc.model_turn and sc.model_turn.parts:
                            txt = "".join(
                                p.text
                                for p in sc.model_turn.parts
                                if hasattr(p, "text") and p.text
                            )
                            txt = _clean_transcript(txt)

                        if txt:
                            out_buf.append(txt)
                            if spoken:
                                spoken_buf.append(txt)
                                full_spoken = " ".join(spoken_buf).strip()
                                if full_spoken:
                                    self.ui.write_nova(full_spoken)
                                    bridge = getattr(self.ui._win, "_bridge", None)
                                    if bridge and self.ui._win._bridge_active:
                                        try:
                                            bridge.send_message(full_spoken)
                                        except Exception:
                                            pass

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            self.ui.finish_nova()

                            full_out = " ".join(out_buf).strip()
                            self._bridge_turn = False
                            if spoken_buf or out_buf:
                                bridge = getattr(self.ui._win, "_bridge", None)
                                if bridge and self.ui._win._bridge_active:
                                    try:
                                        site_text = (
                                            " ".join(spoken_buf).strip()
                                            if spoken_buf
                                            else full_out
                                        )
                                        bridge.send_message(site_text)
                                    except Exception:
                                        pass
                            out_buf = []
                            spoken_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[Nova] {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[Nova] Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[Nova] Play started")
        self.ui.write_log("[Nova] Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                if self.ui.deafened or self._bridge_turn:
                    continue
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[Nova] Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # -- reset watcher ------------------------------------------------------

    async def _watch_reset(self):
        try:
            while True:
                await asyncio.sleep(0.3)
                if self._reset_requested:
                    self._reset_requested = False
                    self.ui.write_log("SYS: Resetting session...")
                    if self.session:
                        await self.session.close()
                    return
        except asyncio.CancelledError:
            pass

    # -- non-Gemini pipeline ------------------------------------------------

    async def _run_pipeline(self, provider: str):
        """Run with Whisper STT + Piper TTS + any LLM provider."""
        from voice.pipeline import VoicePipeline

        print(f"[Nova] Starting voice pipeline: {provider}")
        self.ui.write_log(f"SYS: Starting {provider.upper()} voice pipeline...")

        memory = load_memory()
        mem_str = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        from datetime import datetime
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y -- %I:%M %p")
        time_ctx = f"[CURRENT DATE & TIME]\nRight now it is: {time_str}\nUse this to calculate exact times for reminders.\n\n"

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)
        full_prompt = "\n".join(parts)

        def tool_executor(name: str, args: dict) -> str:
            return _execute_tool_standalone(name, args, speak_fn=None)

        pipeline = VoicePipeline(
            system_prompt=full_prompt,
            tool_declarations=TOOL_DECLARATIONS,
            execute_tool_fn=tool_executor,
            ui=self.ui,
        )
        self.pipeline = pipeline
        self._loop = asyncio.get_event_loop()

        self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Nova {__version__} online ({provider}).")
        self.ui.write_log("SYS: Say something to begin...")
        get_scheduler().start()

        bridge = getattr(self.ui._win, "_bridge", None)
        if bridge:
            bridge.set_provider(full_prompt)
            self.ui.write_log("SYS: Chat on site ready.")

        try:
            await pipeline.start_listening()
        except Exception as e:
            print(f"[Nova] Pipeline error: {e}")
            traceback.print_exc()

    # -- main loop ----------------------------------------------------------

    async def run(self):
        provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

        if provider != "gemini":
            await self._run_pipeline(provider)
            return

        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"},
        )

        while True:
            try:
                print("[Nova] Connecting...")
                self.ui.write_log("[Nova] Connecting...")
                self.ui.set_state("THINKING")

                briefing = await self._build_briefing()
                config = self._build_config(briefing=briefing)

                async with client.aio.live.connect(
                    model=LIVE_MODEL, config=config
                ) as session:
                    self.session = session
                    self._loop = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    print("[Nova] Connected.")
                    self.ui.write_log("[Nova] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log(f"SYS: Nova {__version__} online.")
                    get_scheduler().start()

                    self.ui._win._gemini_loop = self._loop
                    self.ui._win._gemini_session = session
                    self.ui._win._nova_client = self

                    bridge = getattr(self.ui._win, "_bridge", None)
                    if bridge and self.ui._win._bridge_active:
                        bridge.set_gemini(self._loop, session, self)
                        self.ui.write_log("SYS: Chat on site ready.")

                    await asyncio.gather(
                        self._send_realtime(),
                        self._listen_audio(),
                        self._receive_audio(),
                        self._play_audio(),
                        self._watch_reset(),
                    )

            except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                print("[Nova] Session reset")
            except Exception as e:
                print(f"[Nova] ERROR: {e}")
                traceback.print_exc()

            self._reset_requested = False
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[Nova] Reconnecting in 3s...")
            await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ui = NovaUI()

    ui._win._log.append_log("SYS: Checking for updates...")
    check_for_update_async(callback=lambda r: ui._win._update_sig.emit(r))

    def runner():
        ui.wait_for_api_key()
        nova_app = NovaLive(ui)
        try:
            asyncio.run(nova_app.run())
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
