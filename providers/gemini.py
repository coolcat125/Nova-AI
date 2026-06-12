import os
from google import genai
from google.genai import types
from .base import BaseLLM


def _get_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        from dotenv import load_dotenv; load_dotenv()
        key = os.environ.get("GEMINI_API_KEY")
    if not key:
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key or ""


class GeminiProvider(BaseLLM):
    def __init__(self):
        key = _get_api_key()
        self.client = genai.Client(api_key=key)

    def _build_config(self, system_instruction, tools):
        kwargs = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        if tools:
            kwargs["tools"] = tools
        return types.GenerateContentConfig(**kwargs) if kwargs else None

    def _messages_to_contents(self, messages):
        if not messages:
            return None
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(types.Content(role="user", parts=[types.Part(text=content)]))
            elif role == "assistant":
                parts.append(types.Content(role="model", parts=[types.Part(text=content)]))
            elif role == "system":
                pass
        return parts

    def generate(self, model: str, system_instruction=None, messages=None, contents=None, tools=None, **kwargs):
        config = self._build_config(system_instruction, tools)
        model_path = model if model.startswith("models/") else f"models/{model}"

        if messages:
            contents_list = self._messages_to_contents(messages)
        elif contents:
            contents_list = contents
        else:
            contents_list = ""

        try:
            if config:
                resp = self.client.models.generate_content(model=model_path, contents=contents_list, config=config)
            else:
                resp = self.client.models.generate_content(model=model_path, contents=contents_list)
        except Exception as e:
            return {"content": f"Error: {e}", "tool_calls": [], "finish_reason": "error"}

        result = {"content": "", "tool_calls": [], "finish_reason": "stop"}

        if resp.text:
            result["content"] = resp.text

        if hasattr(resp, "candidates") and resp.candidates:
            cand = resp.candidates[0]
            if cand.finish_reason:
                result["finish_reason"] = str(cand.finish_reason)
            if hasattr(cand, "content") and cand.content and cand.content.parts:
                for part in cand.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        result["tool_calls"].append({
                            "name": fc.name,
                            "args": dict(fc.args) if fc.args else {},
                            "id": fc.id if hasattr(fc, "id") else None,
                        })

        return result
