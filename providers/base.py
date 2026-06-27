from abc import ABC, abstractmethod
from typing import Optional


class BaseLLM(ABC):
    """Abstract LLM provider. All providers return normalized dicts."""

    @abstractmethod
    def generate(self, model: str, system_instruction: Optional[str] = None,
                 messages: Optional[list] = None, contents: Optional[str] = None,
                 tools: Optional[list] = None, **kwargs) -> dict:
        """Returns {"content": str, "tool_calls": [{"name": str, "args": dict}], "finish_reason": str}."""
        pass
