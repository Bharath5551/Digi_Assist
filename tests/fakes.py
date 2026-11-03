"""A fake provider that replays scripted completions, so the loop, approval
gate and persistence can be tested without the network."""

from __future__ import annotations

import copy
from typing import Any

from app.llm.base import Block, Completion, Request


def text(t: str) -> Block:
    return {"type": "text", "text": t}


def tool_use(name: str, input: dict[str, Any], id: str = "tu_1") -> Block:
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def end_turn(*blocks: Block) -> Completion:
    return Completion(content=list(blocks), stop_reason="end_turn")


def wants_tool(*blocks: Block) -> Completion:
    return Completion(content=list(blocks), stop_reason="tool_use")


class FakeProvider:
    name = "fake"

    def __init__(self, script: list[Completion]) -> None:
        self.script = list(script)
        self.calls: list[Request] = []

    async def complete(self, req: Request) -> Completion:
        self.calls.append(copy.deepcopy(req))  # the loop mutates its messages list afterwards
        if not self.script:
            raise AssertionError("fake provider ran out of scripted completions")
        return self.script.pop(0)

    async def quick(self, prompt: str, max_tokens: int = 256) -> str:
        return ""


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.approvals: list[tuple[int, str]] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def send_approval(self, approval_id: int, summary: str) -> None:
        self.approvals.append((approval_id, summary))
