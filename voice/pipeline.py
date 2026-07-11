"""Voice pipeline: Vosk STT -> LLM -> Piper TTS."""

import asyncio
import json
import os
import re
import struct
import threading
from typing import Optional, Callable

import numpy as np
import sounddevice as sd

from voice.vosk_stt import transcribe, SAMPLE_RATE as STT_RATE, preload as preload_stt
from voice.kokoro_tts import synthesize, preload as preload_tts

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U00010000-\U0010ffff"
    "\u200d"
    "\u2640-\u2642"
    "\ufe0f"
    "]+",
    flags=re.UNICODE,
)
_MD_FORMAT_RE = re.compile(r"[*_`~\[\]()>#|{}]")
_MULTILINE_RE = re.compile(r"```[\s\S]*?```")


def _clean_for_tts(text: str) -> str:
    """Strip emojis, markdown formatting, and code blocks for TTS."""
    text = _MULTILINE_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _MD_FORMAT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


class VoicePipeline:
    """Non-Gemini voice pipeline: Whisper STT + call_llm + Piper TTS."""

    def __init__(self, system_prompt: str, tool_declarations: list,
                 execute_tool_fn: Callable, ui=None):
        self.system_prompt = system_prompt
        self.tool_declarations = tool_declarations
        self.execute_tool_fn = execute_tool_fn
        self.ui = ui
        self.conversation: list[dict] = []
        self._speaking = False
        self._speaking_lock = threading.Lock()
        self._audio_out_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._processing = False
        preload_stt()
        preload_tts()

    @property
    def is_speaking(self) -> bool:
        with self._speaking_lock:
            return self._speaking

    def _set_speaking(self, val: bool):
        with self._speaking_lock:
            self._speaking = val

    def _get_model_name(self) -> str:
        from providers import _DEFAULT_MODELS, _current_provider_name
        prov = _current_provider_name()
        return os.environ.get("LLM_MODEL", "") or _DEFAULT_MODELS.get(prov, "gemini-2.5-flash")

    def _build_system_prompt(self) -> str:
        from datetime import datetime
        now = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y -- %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )
        return time_ctx + self.system_prompt

    async def process_audio(self, audio_bytes: bytes):
        """Full pipeline: STT -> LLM -> TTS -> speaker."""
        if self._processing:
            print("[Pipeline] Still processing previous turn, skipping.", flush=True)
            return
        self._processing = True
        try:
            await self._process_audio_inner(audio_bytes)
        finally:
            self._processing = False

    async def process_text(self, text: str) -> str:
        """Process text input: LLM -> response (no TTS)."""
        if self._processing:
            print("[Pipeline] Still processing previous turn, skipping.", flush=True)
            return ""
        self._processing = True
        try:
            print(f"[Pipeline] User (text): {text}")
            self.conversation.append({"role": "user", "content": text})

            response_text = await self._call_llm_with_tools(text)
            print(f"[Pipeline] LLM response: {response_text[:100] if response_text else '(empty)'}")

            if response_text:
                print(f"[Pipeline] Nova: {response_text}")
                if self.ui:
                    self.ui.write_nova(response_text)

                tts_text = _clean_for_tts(response_text)
                audio_data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: synthesize(tts_text)
                )
                if audio_data:
                    await self._play_pcm(audio_data)

                if self.ui:
                    self.ui.finish_nova()

                self.conversation.append({"role": "assistant", "content": response_text})

            return response_text or ""
        finally:
            self._processing = False

    async def _process_audio_inner(self, audio_bytes: bytes):
        loop = asyncio.get_event_loop()

        print(f"[Pipeline] Processing {len(audio_bytes)} bytes of audio...")
        user_text = await loop.run_in_executor(None, lambda: transcribe(audio_bytes))
        if not user_text or len(user_text.strip()) < 2:
            print("[Pipeline] No speech detected.")
            return

        print(f"[Pipeline] User: {user_text}")
        if self.ui:
            self.ui.write_log(f"You: {user_text}")

        self.conversation.append({"role": "user", "content": user_text})

        print("[Pipeline] Calling LLM...")
        response_text = await self._call_llm_with_tools(user_text)
        print(f"[Pipeline] LLM response: {response_text[:100] if response_text else '(empty)'}")

        if response_text:
            print(f"[Pipeline] Nova: {response_text}")
            if self.ui:
                self.ui.write_nova(response_text)

            tts_text = _clean_for_tts(response_text)
            audio_data = await loop.run_in_executor(None, lambda: synthesize(tts_text))
            if audio_data:
                await self._play_pcm(audio_data)

            if self.ui:
                self.ui.finish_nova()

            self.conversation.append({"role": "assistant", "content": response_text})

    async def _call_llm_with_tools(self, user_text: str) -> str:
        """Call LLM and handle tool calls in a loop."""
        from providers import call_llm

        sys_prompt = self._build_system_prompt()
        messages = list(self.conversation)
        tools = [{"function_declarations": self.tool_declarations}] if self.tool_declarations else None

        max_tool_rounds = 5
        for _ in range(max_tool_rounds):
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: call_llm(
                        model=self._get_model_name(),
                        system_instruction=sys_prompt,
                        messages=messages,
                        tools=tools,
                    ),
                )
            except Exception as e:
                print(f"[Pipeline] LLM error: {e}")
                return f"Error calling LLM: {e}"

            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])

            if not tool_calls:
                return content

            if content:
                messages.append({"role": "assistant", "content": content})

            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                tc_id = tc.get("id")

                print(f"[Pipeline] Tool: {name}")
                if self.ui:
                    self.ui.set_state("EXECUTING")

                try:
                    tool_result = await self._execute_tool_call(name, args)
                except Exception as e:
                    tool_result = f"Error: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id or "",
                    "content": json.dumps({"result": tool_result}),
                })

        return content if content else "I wasn't able to complete that."

    async def _execute_tool_call(self, name: str, args: dict) -> str:
        """Execute a tool call and return the result string."""
        if self.ui:
            self.ui.set_state("EXECUTING")

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: self.execute_tool_fn(name=name, args=args)
            )
            return result or "Done."
        except Exception as e:
            return f"Error: {e}"
        finally:
            if self.ui:
                self.ui.set_state("LISTENING")

    async def _play_pcm(self, pcm_bytes: bytes):
        """Play raw PCM int16 audio through speakers."""
        self._set_speaking(True)
        if self.ui:
            self.ui.set_state("SPEAKING")

        loop = asyncio.get_event_loop()

        sample_rate = 24000
        stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=1024,
        )

        try:
            await loop.run_in_executor(None, stream.start)

            chunk_size = 4096
            for i in range(0, len(pcm_bytes), chunk_size):
                chunk = pcm_bytes[i:i + chunk_size]
                if self.ui and self.ui.deafened:
                    continue
                await loop.run_in_executor(None, lambda c=chunk: stream.write(c))
                await asyncio.sleep(0.001)
        finally:
            await loop.run_in_executor(None, stream.stop)
            await loop.run_in_executor(None, stream.close)
            self._set_speaking(False)
            if self.ui:
                self.ui.set_state("LISTENING")

    async def start_listening(self):
        """Start mic capture loop. Runs until cancelled."""
        import sounddevice as sd

        print("[Pipeline] Starting voice pipeline...", flush=True)
        if self.ui:
            self.ui.write_log("SYS: Ready. Say something.")

        loop = asyncio.get_event_loop()
        stream = None

        _cb_count = 0

        def callback(indata, frames, time_info, status):
            nonlocal _cb_count
            _cb_count += 1
            if _cb_count == 1:
                print(f"[Pipeline] Mic callback firing. muted={self.ui.muted if self.ui else 'no ui'}", flush=True)
            with self._speaking_lock:
                speaking = self._speaking
            muted = self.ui.muted if self.ui else False
            if not speaking and not muted:
                data = indata.tobytes()
                def _enqueue():
                    try:
                        self._audio_out_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        pass
                loop.call_soon_threadsafe(_enqueue)

        try:
            stream = sd.InputStream(
                samplerate=STT_RATE,
                channels=1,
                dtype="int16",
                blocksize=1024,
                callback=callback,
            )
            stream.start()

            silence_threshold = STT_RATE * 2
            silence_chunks = 0
            is_speaking = False
            audio_buffer = bytearray()

            while True:
                try:
                    chunk = await asyncio.wait_for(self._audio_out_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if is_speaking and silence_chunks > silence_threshold // 1024:
                        print(f"[Pipeline] Silence after timeout. Buffer: {len(audio_buffer)} bytes", flush=True)
                        audio_data = bytes(audio_buffer)
                        audio_buffer = bytearray()
                        is_speaking = False
                        silence_chunks = 0
                        if len(audio_data) > STT_RATE:
                            print(f"[Pipeline] Sending {len(audio_data)} bytes to STT", flush=True)
                            asyncio.create_task(self.process_audio(audio_data))
                        else:
                            print(f"[Pipeline] Audio too short: {len(audio_data)} bytes", flush=True)
                    continue

                audio_buffer.extend(chunk)

                level = np.abs(np.frombuffer(chunk, dtype=np.int16)).mean()
                if level > 300:
                    if not is_speaking:
                        print(f"[Pipeline] Speech detected! Level: {level:.0f}", flush=True)
                    is_speaking = True
                    silence_chunks = 0
                else:
                    silence_chunks += 1
                    if is_speaking and silence_chunks > silence_threshold // 1024:
                        print(f"[Pipeline] Silence detected. Buffer: {len(audio_buffer)} bytes", flush=True)
                        audio_data = bytes(audio_buffer)
                        audio_buffer = bytearray()
                        is_speaking = False
                        silence_chunks = 0
                        if len(audio_data) > STT_RATE:
                            print(f"[Pipeline] Sending {len(audio_data)} bytes to STT", flush=True)
                            asyncio.create_task(self.process_audio(audio_data))
                        else:
                            print(f"[Pipeline] Audio too short: {len(audio_data)} bytes", flush=True)

        except Exception as e:
            print(f"[Pipeline] Listen error: {e}")
        finally:
            if stream:
                stream.stop()
                stream.close()
