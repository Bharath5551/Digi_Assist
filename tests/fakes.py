"""A fake Anthropic client that replays scripted responses, so the loop,
approval gate and persistence can be tested without the network."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any


class Block(SimpleNamespace):
    def model_dump(self, mode: str = "json", exclude_none: bool = True) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def text(t: str) -> Block:
    return Block(type="text", text=t)


def tool_use(name: str, input: dict[str, Any], id: str = "tu_1") -> Block:
    return Block(type="tool_use", id=id, name=name, input=input)


class Response(SimpleNamespace):
    pass


class FakeMessages:
    def __init__(self, script: list[Response]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Response:
        # the loop mutates its messages list after the call; snapshot it
        self.calls.append({**kwargs, "messages": copy.deepcopy(kwargs.get("messages"))})
        if not self.script:
            raise AssertionError("fake client ran out of scripted responses")
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script: list[Response]) -> None:
        self.beta = SimpleNamespace(messages=FakeMessages(script))
        self.messages = self.beta.messages


def end_turn(*blocks: Block) -> Response:
    return Response(content=list(blocks), stop_reason="end_turn")


def wants_tool(*blocks: Block) -> Response:
    return Response(content=list(blocks), stop_reason="tool_use")


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.approvals: list[tuple[int, str]] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def send_approval(self, approval_id: int, summary: str) -> None:
        self.approvals.append((approval_id, summary))
