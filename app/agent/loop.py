"""The agent loop: one user message in, one reply out, tools in between.

Hand-written over the Messages API so the approval gate, persistence and
audit log sit exactly where we want them.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from sqlalchemy import select

from app import approvals
from app.agent.prompts import build_system
from app.agent.router import route
from app.agent.skills import Registry, Skill
from app.approvals import Notifier
from app.audit import record
from app.config import get_settings
from app.db.base import session
from app.db.models import Conversation, Message
from app.skills.memory.store import snapshot as memory_snapshot

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Agent:
    def __init__(self, registry: Registry, client: anthropic.AsyncAnthropic | None = None) -> None:
        self.registry = registry
        self.client = client or anthropic.AsyncAnthropic()
        self.settings = get_settings()

    async def run_turn(self, text: str, *, channel: str = "telegram", notifier: Notifier | None = None) -> str:
        skills = await route(text, self.registry, self.client)
        conv_id, history = await self._load_history(channel)
        system = build_system(skills, await memory_snapshot(), self.settings.timezone)
        tools = [t.to_api() for s in skills for t in s.tools]

        messages: list[dict[str, Any]] = history + [{"role": "user", "content": text}]
        await self._save(conv_id, "user", text)

        reply_parts: list[str] = []
        for _ in range(self.settings.max_tool_iterations):
            response = await self.client.beta.messages.create(
                model=self.settings.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": self.settings.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            content = [b.model_dump(mode="json", exclude_none=True) for b in response.content]
            messages.append({"role": "assistant", "content": content})
            await self._save(conv_id, "assistant", content)
            reply_parts.extend(b.text for b in response.content if b.type == "text")

            if response.stop_reason == "refusal":
                reply_parts.append("I can't help with that one.")
                break
            if response.stop_reason == "max_tokens":
                reply_parts.append("(cut off: response too long)")
                break
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result, is_error = await self._call_tool(block.name, dict(block.input), skills, notifier)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})
            await self._save(conv_id, "user", results)
        else:
            reply_parts.append("(stopped: too many steps in one turn)")

        reply = "\n".join(p.strip() for p in reply_parts if p.strip())
        return reply or "(no reply)"

    async def _call_tool(
        self, name: str, args: dict[str, Any], skills: list[Skill], notifier: Notifier | None
    ) -> tuple[str, bool]:
        found = self.registry.find_tool(name, skills)
        if not found:
            return f"Unknown tool {name}", True
        skill, tool = found
        if tool.requires_approval:
            a = await approvals.queue(skill, tool, args, notifier)
            return (
                f"Queued for approval #{a.id}: {a.summary}. It will run only after the user taps yes. "
                "Tell the user it is waiting for approval and do not call this tool again for the same action."
            ), False
        try:
            out = await tool.handler(**args)
            await record(skill.name, tool.name, args, ok=True, result=out)
            return out, False
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", name)
            await record(skill.name, tool.name, args, ok=False, result=str(e))
            return f"{type(e).__name__}: {e}", True

    async def _load_history(self, channel: str) -> tuple[int, list[dict[str, Any]]]:
        async with session() as s:
            conv = (await s.execute(select(Conversation).where(Conversation.channel == channel))).scalar_one_or_none()
            if conv is None:
                conv = Conversation(channel=channel)
                s.add(conv)
                await s.commit()
                await s.refresh(conv)
            rows = (
                await s.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.id.desc())
                    .limit(self.settings.max_history_messages)
                )
            ).scalars().all()
        history = [{"role": m.role, "content": m.content} for m in reversed(rows)]
        return conv.id, _trim_to_user_start(history)

    async def _save(self, conv_id: int, role: str, content: Any) -> None:
        async with session() as s:
            s.add(Message(conversation_id=conv_id, role=role, content=content))
            await s.commit()


def _trim_to_user_start(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """History must start with a plain user message, not a tool_result block,
    or the API rejects it. Drop leading turns until that holds."""
    for i, m in enumerate(history):
        if m["role"] == "user" and isinstance(m["content"], str):
            return history[i:]
    return []


def pretty_args(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False)[:500]
