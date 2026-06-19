from __future__ import annotations
import asyncio
import json
import random
import string
import threading
import time
from typing import Any, Callable

import websockets
from supabase import create_client, Client

SUPABASE_URL = "https://fylderfkpxbsjdzpbcle.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5bGRlcmZrcHhic2pkenBiY2xlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE4MTU1MzQsImV4cCI6MjA5NzM5MTUzNH0.wnpCgZxQrtlIFtWXRcAkVRtJJ-84QjZcTWG1owjiHak"

REALTIME_URL = SUPABASE_URL.replace("https://", "wss://") + "/realtime/v1/websocket"


def _generate_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=6))


class TextBridge:
    def __init__(self):
        self._supabase: Client | None = None
        self._pairing_code: str | None = None
        self._session_id: int | None = None
        self._active = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_message_cb: Callable | None = None
        self._gemini_loop: asyncio.AbstractEventLoop | None = None
        self._gemini_session: Any = None
        self._log_cb: Callable | None = None
        self._pairing_cb: Callable | None = None
        self._ws_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._pending_messages: list[str] = []

    def set_callbacks(self, on_message=None, log=None, pairing=None):
        self._on_message_cb = on_message
        self._log_cb = log
        self._pairing_cb = pairing

    def set_gemini(self, loop, session, nova_client=None):
        self._gemini_loop = loop
        self._gemini_session = session
        self._nova_client = nova_client
        self._log("Connected to Nova.")
        pending = list(self._pending_messages)
        self._pending_messages.clear()
        for msg in pending:
            self._log(f"Sending: {msg[:40]}")
            if self._nova_client:
                self._nova_client._bridge_turn = True
            asyncio.run_coroutine_threadsafe(
                self._gemini_session.send_client_content(
                    turns={"parts": [{"text": "[MOBILE TEXT]: " + msg}]},
                    turn_complete=True
                ),
                self._gemini_loop
            )

    def start(self):
        def _run_loop():
            try:
                asyncio.run(self._arun())
            except Exception as e:
                self._log(f"Chat on site error: {e}")
                import traceback
                self._log(traceback.format_exc()[:500])
        threading.Thread(target=_run_loop, daemon=True, name="bridge").start()

    def stop(self):
        if self._supabase and self._session_id:
            try:
                resp = self._supabase.table("sessions").update({"active": False}).eq("id", self._session_id).execute()
            except Exception as e:
                self._log(f"Stop update failed: {e}")
        self._active = False
        if self._ws_task and self._loop and self._loop.is_running():
            self._ws_task.cancel()
        if self._keepalive_task and self._loop and self._loop.is_running():
            self._keepalive_task.cancel()

    def send_message(self, text: str):
        if not self._active or not self._session_id:
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._ainsert_message(text), self._loop
            )

    def _log(self, msg: str):
        if self._log_cb:
            self._log_cb(f"[Site] {msg}")

    async def _ainsert_message(self, text: str):
        if not self._supabase:
            return
        try:
            await asyncio.to_thread(
                lambda: self._supabase.table("messages").insert({
                    "session_id": self._session_id,
                    "sender": "nova",
                    "text": text,
                }).execute()
            )
        except Exception as e:
            self._log(f"Send failed: {e}")

    async def _arun(self):
        self._loop = asyncio.get_event_loop()

        self._supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

        code = _generate_code()
        self._pairing_code = code

        try:
            data = await asyncio.to_thread(
                lambda: self._supabase.table("sessions").insert(
                    {"pairing_code": code}
                ).execute()
            )
            self._session_id = data.data[0]["id"]
            self._active = True
            self._log(f"Session created: {code}")
            if self._pairing_cb:
                self._pairing_cb(code)
        except Exception as e:
            self._log(f"Session insert failed: {e}")
            return

        self._ws_task = asyncio.create_task(self._realtime_loop())
        self._keepalive_task = asyncio.create_task(self._akeepalive())

        while self._active:
            await asyncio.sleep(1)

    async def _realtime_loop(self):
        ws_url = f"{REALTIME_URL}?apikey={SUPABASE_KEY}&vsn=1.0.0"
        topic = f"realtime:public:messages:session_id=eq.{self._session_id}"
        ref = 0

        while self._active:
            try:
                async with websockets.connect(ws_url, ping_interval=20) as ws:
                    ref += 1
                    join_msg = json.dumps({
                        "topic": topic,
                        "event": "phx_join",
                        "payload": {
                            "config": {
                                "postgres_changes": [{
                                    "event": "INSERT",
                                    "schema": "public",
                                    "table": "messages",
                                    "filter": f"session_id=eq.{self._session_id}",
                                }],
                            }
                        },
                        "ref": str(ref),
                    })
                    await ws.send(join_msg)

                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    resp_data = json.loads(resp)
                    if resp_data.get("event") == "phx_reply":
                        status = resp_data.get("payload", {}).get("status")
                        if status != "ok":
                            self._log(f"Connection failed")

                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                            event = data.get("event", "")
                            if event == "postgres_changes":
                                payload = data.get("payload", {})
                                inner = payload.get("data", {})
                                record = inner.get("record", {})
                                sender = record.get("sender", "")
                                text = record.get("text", "")
                                if sender == "user" and text:
                                    if self._on_message_cb:
                                        self._on_message_cb(text)
                                    if self._gemini_loop and self._gemini_session:
                                        self._log("Sending to Nova...")
                                        if self._nova_client:
                                            self._nova_client._bridge_turn = True
                                        asyncio.run_coroutine_threadsafe(
                                            self._gemini_session.send_client_content(
                                                turns={"parts": [{"text": "[MOBILE TEXT]: " + text}]},
                                                turn_complete=True
                                            ),
                                            self._gemini_loop
                                        )
                                    else:
                                        self._log("Nova not ready — queuing")
                                        self._pending_messages.append(text)
                        except json.JSONDecodeError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Connection error")
                if self._active:
                    await asyncio.sleep(1)

    async def _akeepalive(self):
        while self._active:
            await asyncio.sleep(25)
            try:
                if self._supabase and self._session_id:
                    await asyncio.to_thread(
                        lambda: self._supabase.table("sessions").select("id").eq(
                            "id", self._session_id
                        ).execute()
                    )
            except Exception:
                pass

    @property
    def pairing_code(self) -> str | None:
        return self._pairing_code

    @property
    def active(self) -> bool:
        return self._active
