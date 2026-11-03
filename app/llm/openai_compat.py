"""Any OpenAI-style chat-completions endpoint: NVIDIA NIM (free Nemotron),
OpenRouter, or a self-hosted server.

Converts the canonical Anthropic-style blocks to OpenAI messages and back.
Thinking blocks are dropped on the way out; open models do not take them back.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.base import Block, Completion, Message, Provider, Request, StopReason, ToolSpec

log = logging.getLogger(__name__)

PRESETS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class OpenAICompatProvider(Provider):
    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        s = get_settings()
        self.name = s.llm_provider
        base_url = s.llm_base_url or PRESETS.get(s.llm_provider)
        if client is None and not base_url:
            raise RuntimeError("LLM_BASE_URL is required for LLM_PROVIDER=openai_compat")
        self.client = client or AsyncOpenAI(base_url=base_url, api_key=s.llm_api_key or "missing", timeout=120, max_retries=2)
        self.model = s.model
        self.router_model = s.router_model or s.model
        # NVIDIA's Nemotron 3.x templates take enable_thinking via chat_template_kwargs.
        self.extra_body: dict[str, Any] = (
            {"chat_template_kwargs": {"enable_thinking": True}}
            if s.llm_provider == "nvidia" and s.nemotron_thinking and "nemotron" in s.model
            else {}
        )

    async def complete(self, req: Request) -> Completion:
        messages = to_openai_messages(req.system_stable + "\n\n" + req.system_volatile, req.messages)
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, max_tokens=req.max_tokens)
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        if req.tools:
            kwargs["tools"] = [to_openai_tool(t) for t in req.tools]
            kwargs["tool_choice"] = "auto"
        resp = await self.client.chat.completions.create(**kwargs)
        return from_openai_response(resp)

    async def quick(self, prompt: str, max_tokens: int = 256) -> str:
        resp = await self.client.chat.completions.create(
            model=self.router_model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens
        )  # no thinking for the router: it only needs a list of names
        return resp.choices[0].message.content or ""


def to_openai_tool(t: ToolSpec) -> dict[str, Any]:
    schema = dict(t.input_schema)
    schema.setdefault("type", "object")
    return {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": schema}}


def to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "\n".join(b["text"] for b in content if b.get("type") == "text").strip()
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))},
                }
                for b in content
                if b.get("type") == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            # user turn made of tool results (and possibly text)
            for b in content:
                if b.get("type") == "tool_result":
                    body = b.get("content", "")
                    if b.get("is_error"):
                        body = f"ERROR: {body}"
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": body})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


def from_openai_response(resp: Any) -> Completion:
    choice = resp.choices[0]
    msg = choice.message
    content: list[Block] = []
    if msg.content:
        content.append({"type": "text", "text": msg.content})
    for i, call in enumerate(msg.tool_calls or []):
        raw = call.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("model returned invalid JSON for tool %s: %r", call.function.name, raw[:200])
            args = {"__invalid_json__": raw}
        content.append({"type": "tool_use", "id": call.id or f"call_{i}", "name": call.function.name, "input": args})
    finish = choice.finish_reason
    stop: StopReason
    if msg.tool_calls:
        stop = "tool_use"
    elif finish == "length":
        stop = "max_tokens"
    elif finish == "content_filter":
        stop = "refusal"
    else:
        stop = "end_turn"
    return Completion(content=content, stop_reason=stop, model=getattr(resp, "model", "") or "")
