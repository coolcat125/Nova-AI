"""Nova LLM provider abstraction. Usage:
    from providers import call_llm, reconfigure
    resp = call_llm(model="gpt-4o", system_instruction="...", messages=[...])
    # resp = {"content": "...", "tool_calls": [...]}

Live reconfiguration:
    reconfigure(provider="openai", api_key="...")  # hot-swap without restart
"""

import os
from .gemini import GeminiProvider
from .openai_provider import OpenAIProvider
from .ollama import OllamaProvider


_PROVIDER_INSTANCES = {}
_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "ollama": "llama3.2",
}


def _current_provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", "gemini").strip().lower()


def _get_provider(name: str = None):
    name = (name or _current_provider_name()).strip().lower()
    if name in _PROVIDER_INSTANCES:
        return _PROVIDER_INSTANCES[name]
    if name == "gemini":
        _PROVIDER_INSTANCES[name] = GeminiProvider()
    elif name == "openai":
        _PROVIDER_INSTANCES[name] = OpenAIProvider()
    elif name == "ollama":
        _PROVIDER_INSTANCES[name] = OllamaProvider()
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {name}. Use: gemini, openai, ollama")
    return _PROVIDER_INSTANCES[name]


def call_llm(model=None, system_instruction=None, messages=None, contents=None, tools=None, **kwargs):
    """Unified LLM call. Returns {"content": str, "tool_calls": [...], "finish_reason": str}.

    Args:
        model: Model name (defaults to provider default)
        system_instruction: System prompt
        messages: List of {"role": "user"/"assistant", "content": "..."} (preferred)
        contents: Raw content string (fallback if no messages)
        tools: List of tool definitions (varies by provider)
    """
    provider_name = _current_provider_name()
    provider = _get_provider(provider_name)
    model = model or _DEFAULT_MODELS.get(provider_name, "gemini-2.5-flash")
    return provider.generate(model=model, system_instruction=system_instruction, messages=messages, contents=contents, tools=tools, **kwargs)


def reconfigure(provider: str = None, api_key: str = None, base_url: str = None, os_system: str = None):
    """Hot-swap providers at runtime without restart.

    Args:
        provider: "gemini", "openai", or "ollama"
        api_key: API key for the provider
        base_url: Base URL (OpenAI or Ollama)
        os_system: OS override
    """
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    if api_key:
        prov = provider or _current_provider_name()
        if prov == "gemini":
            os.environ["GEMINI_API_KEY"] = api_key
        elif prov == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        prov = provider or _current_provider_name()
        if prov == "openai":
            os.environ["OPENAI_BASE_URL"] = base_url
        elif prov == "ollama":
            os.environ["OLLAMA_BASE_URL"] = base_url
    if os_system:
        os.environ["OS_SYSTEM"] = os_system

    provider_name = _current_provider_name()
    if provider_name in _PROVIDER_INSTANCES:
        del _PROVIDER_INSTANCES[provider_name]
    return _get_provider(provider_name)


def get_current_model() -> str:
    name = _current_provider_name()
    return _DEFAULT_MODELS.get(name, "gemini-2.5-flash")
