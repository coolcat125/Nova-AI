import os
from .openai_provider import OpenAIProvider

OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"


class OpenCodeProvider(OpenAIProvider):
    def __init__(self):
        api_key = os.environ.get("OPENCODE_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENCODE_API_KEY environment variable is required.")
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = OPENCODE_BASE_URL
        super().__init__()
