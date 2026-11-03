"""Model providers. The loop speaks one canonical message format (Anthropic-style
content blocks); each provider converts to and from its own API.

Pick with LLM_PROVIDER: nvidia (default, free Nemotron via build.nvidia.com),
openrouter, openai_compat (any OpenAI-style endpoint), anthropic.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import Provider


@lru_cache
def get_provider() -> Provider:
    s = get_settings()
    if s.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    from app.llm.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider()
