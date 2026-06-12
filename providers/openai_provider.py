import os
import json
from openai import OpenAI
from .base import BaseLLM


class OpenAIProvider(BaseLLM):
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY", "") or "sk-placeholder"
        base_url = os.environ.get("OPENAI_BASE_URL", "") or None
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _build_messages(self, system_instruction, messages, contents):
        msgs = []
        if system_instruction:
            msgs.append({"role": "system", "content": system_instruction})
        if messages:
            msgs.extend(messages)
        elif contents:
            msgs.append({"role": "user", "content": contents})
        return msgs

    def generate(self, model, system_instruction=None, messages=None, contents=None, tools=None, **kwargs):
        msgs = self._build_messages(system_instruction, messages, contents)
        kwargs = {"model": model, "messages": msgs}

        if tools:
            openai_tools = []
            for t in tools:
                if "function_declarations" in t:
                    for fd in t["function_declarations"]:
                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": fd.get("name", ""),
                                "description": fd.get("description", ""),
                                "parameters": fd.get("parameters", fd),
                            }
                        })
                elif isinstance(t, dict) and t.get("type") == "function":
                    openai_tools.append(t)
                elif isinstance(t, dict) and "name" in t:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", t),
                        }
                    })
            if openai_tools:
                kwargs["tools"] = openai_tools

        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            return {"content": f"Error: {e}", "tool_calls": [], "finish_reason": "error"}

        result = {"content": "", "tool_calls": [], "finish_reason": "stop"}
        choice = resp.choices[0] if resp.choices else None
        if not choice:
            return result

        result["finish_reason"] = choice.finish_reason or "stop"

        if choice.message.content:
            result["content"] = choice.message.content

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"raw": tc.function.arguments}
                result["tool_calls"].append({
                    "name": tc.function.name,
                    "args": args,
                    "id": tc.id,
                })

        return result
