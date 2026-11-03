from __future__ import annotations

import anthropic

from app.config import get_settings
from app.llm.base import Completion, Provider, Request, StopReason

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        s = get_settings()
        self.client = client or anthropic.AsyncAnthropic(api_key=s.llm_api_key or None)
        self.model = s.model
        self.router_model = s.router_model
        self.effort = s.effort

    async def complete(self, req: Request) -> Completion:
        tools = []
        for t in req.tools:
            schema = dict(t.input_schema)
            schema.setdefault("additionalProperties", False)
            schema.setdefault("required", list(schema.get("properties", {}).keys()))
            tools.append({"name": t.name, "description": t.description, "input_schema": schema, "strict": True})
        resp = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=max(req.max_tokens, 16000),
            system=[
                {"type": "text", "text": req.system_stable, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": req.system_volatile},
            ],
            tools=tools,
            messages=req.messages,
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        content = [b.model_dump(mode="json", exclude_none=True) for b in resp.content]
        stop: StopReason = resp.stop_reason if resp.stop_reason in ("end_turn", "tool_use", "max_tokens", "refusal", "pause_turn") else "end_turn"  # type: ignore[assignment]
        return Completion(content=content, stop_reason=stop, model=resp.model)

    async def quick(self, prompt: str, max_tokens: int = 256) -> str:
        resp = await self.client.messages.create(
            model=self.router_model,
            max_tokens=max_tokens,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")
