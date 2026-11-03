from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "pause_turn"]

# Canonical content blocks, shared by every provider:
#   {"type": "text", "text": str}
#   {"type": "tool_use", "id": str, "name": str, "input": dict}
#   {"type": "tool_result", "tool_use_id": str, "content": str, "is_error": bool}
#   {"type": "thinking", ...}   Anthropic only; other providers drop it on the way out
Block = dict[str, Any]
Message = dict[str, Any]  # {"role": "user"|"assistant", "content": str | list[Block]}


@dataclass
class Completion:
    content: list[Block]
    stop_reason: StopReason
    model: str = ""

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[Block]:
        return [b for b in self.content if b.get("type") == "tool_use"]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Request:
    system_stable: str  # cacheable prefix: identity + skill instructions
    system_volatile: str  # time, memory snapshot
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    max_tokens: int = 4096


class Provider(Protocol):
    name: str

    async def complete(self, req: Request) -> Completion: ...

    async def quick(self, prompt: str, max_tokens: int = 256) -> str:
        """One cheap text-only call (used by the router)."""
        ...
