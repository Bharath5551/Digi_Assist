"""Scheduled work: the 5 am brief and firing reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.agent.loop import Agent
from app.approvals import Notifier
from app.config import get_settings
from app.db.base import session
from app.db.models import Reminder

log = logging.getLogger(__name__)


def build(agent: Agent, notifier: Notifier) -> AsyncIOScheduler:
    s = get_settings()
    hour, minute = s.brief_hour_minute
    sched = AsyncIOScheduler(timezone=s.timezone)

    async def morning_brief() -> None:
        try:
            reply = await agent.run_turn("Morning brief.", notifier=notifier)
            await notifier.send(reply)
        except Exception:  # noqa: BLE001
            log.exception("morning brief failed")
            await notifier.send("Morning brief failed. Check the logs.")

    async def fire_reminders() -> None:
        now = datetime.now(timezone.utc)
        async with session() as db:
            due = (await db.execute(select(Reminder).where(Reminder.fired.is_(False), Reminder.due_at <= now))).scalars().all()
            for r in due:
                await notifier.send(f"Reminder: {r.text}")
                r.fired = True
            await db.commit()

    sched.add_job(morning_brief, CronTrigger(hour=hour, minute=minute), id="morning_brief", misfire_grace_time=600)
    sched.add_job(fire_reminders, IntervalTrigger(seconds=30), id="reminders", misfire_grace_time=60)
    return sched
