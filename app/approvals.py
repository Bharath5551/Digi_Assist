"""Approval gate.

A tool marked requires_approval never runs directly. The loop queues an
Approval row, the notifier shows the owner a card with yes/no, and only a
yes runs the handler. Everything is written to the audit log either way.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select, update

from app.agent.skills import Registry, Skill, Tool
from app.audit import record
from app.db.base import session
from app.db.models import Approval

log = logging.getLogger(__name__)

EXPIRES_AFTER = timedelta(hours=24)


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...
    async def send_approval(self, approval_id: int, summary: str) -> None: ...


async def queue(skill: Skill, tool: Tool, args: dict[str, Any], notifier: Notifier | None) -> Approval:
    async with session() as s:
        a = Approval(skill=skill.name, tool=tool.name, args=args, summary=tool.summary(args))
        s.add(a)
        await s.commit()
        await s.refresh(a)
    await record(skill.name, tool.name, args, ok=True, result=f"queued for approval #{a.id}", approval_id=a.id)
    if notifier:
        await notifier.send_approval(a.id, a.summary)
    return a


async def resolve(approval_id: int, approved: bool, registry: Registry, notifier: Notifier | None) -> str:
    """Called when the owner taps yes or no. Returns the text to show them."""
    async with session() as s:
        a = await s.get(Approval, approval_id)
        if a is None:
            return "That approval no longer exists."
        if a.status != "pending":
            return f"Already {a.status}."
        if datetime.now(timezone.utc) - a.created_at.replace(tzinfo=timezone.utc) > EXPIRES_AFTER:
            a.status = "expired"
            a.resolved_at = datetime.now(timezone.utc)
            await s.commit()
            return "That request expired (older than 24 hours). Ask again if you still want it."
        a.status = "approved" if approved else "denied"
        a.resolved_at = datetime.now(timezone.utc)
        await s.commit()
        skill_name, tool_name, args = a.skill, a.tool, dict(a.args)

    if not approved:
        await record(skill_name, tool_name, args, ok=True, result="denied by owner", approval_id=approval_id)
        return "Denied. Nothing was sent."

    found = registry.find_tool(tool_name, [registry.get(skill_name)])
    if not found:
        await _set_status(approval_id, "failed", "tool no longer exists")
        return f"Could not run {tool_name}: the tool no longer exists."
    _, tool = found
    try:
        result = await tool.handler(**args)
        await _set_status(approval_id, "done", result)
        await record(skill_name, tool_name, args, ok=True, result=result, approval_id=approval_id)
        return f"Done. {result}"
    except Exception as e:  # noqa: BLE001 - we want every failure reported, not crashed on
        log.exception("approved tool failed")
        await _set_status(approval_id, "failed", str(e))
        await record(skill_name, tool_name, args, ok=False, result=str(e), approval_id=approval_id)
        return f"Approved, but it failed: {e}"


async def _set_status(approval_id: int, status: str, result: str) -> None:
    async with session() as s:
        await s.execute(update(Approval).where(Approval.id == approval_id).values(status=status, result=result[:4000]))
        await s.commit()


async def pending() -> list[Approval]:
    async with session() as s:
        rows = await s.execute(select(Approval).where(Approval.status == "pending").order_by(Approval.created_at))
        return list(rows.scalars())
