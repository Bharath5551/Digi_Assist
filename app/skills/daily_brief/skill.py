from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app import approvals
from app.agent.skills import Skill, Tool
from app.config import get_settings
from app.db.base import session
from app.db.models import Reminder


async def reminders_due_today() -> str:
    tz = ZoneInfo(get_settings().timezone)
    now = datetime.now(tz)
    end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    async with session() as s:
        rows = (
            await s.execute(select(Reminder).where(Reminder.fired.is_(False), Reminder.due_at <= end).order_by(Reminder.due_at))
        ).scalars().all()
    if not rows:
        return "No reminders due today."
    return "\n".join(f"#{r.id} {r.due_at.astimezone(tz).strftime('%H:%M')}: {r.text}" for r in rows)


async def pending_approvals() -> str:
    rows = await approvals.pending()
    if not rows:
        return "Nothing waiting for approval."
    return "\n".join(f"#{a.id} {a.summary.splitlines()[0]}" for a in rows)


SKILL = Skill(
    name="daily_brief",
    description="Morning brief and evening wrap-up: today's plan, what needs him, reminders, pending approvals.",
    tools=[
        Tool(
            name="reminders_due_today",
            description="List reminders due by the end of today.",
            input_schema={"properties": {}},
            handler=reminders_due_today,
        ),
        Tool(
            name="pending_approvals",
            description="List actions still waiting for his yes.",
            input_schema={"properties": {}},
            handler=pending_approvals,
        ),
    ],
)
