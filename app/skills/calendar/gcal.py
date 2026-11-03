from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.base import session
from app.db.models import Reminder
from app.integrations import google


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def _parse(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz())
    return dt


def _fmt_event(e: dict) -> str:
    start = e.get("start", {})
    when = start.get("dateTime") or start.get("date", "")
    if "T" in when:
        when = _parse(when).astimezone(_tz()).strftime("%a %d %b %H:%M")
    else:
        when = f"{when} (all day)"
    who = ", ".join(a.get("email", "") for a in e.get("attendees", []) if not a.get("self"))
    return f"[{e.get('id')}] {when} | {e.get('summary', '(no title)')}" + (f" | with {who}" if who else "")


async def list_events(start: str, end: str) -> str:
    svc = await google.service("calendar", "v3")
    res = await google.call(
        svc.events().list(
            calendarId="primary",
            timeMin=_parse(start).isoformat(),
            timeMax=_parse(end).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
    )
    items = res.get("items", [])
    return "\n".join(_fmt_event(e) for e in items) if items else "Nothing scheduled."


async def create_event(title: str, start: str, end: str, description: str = "", attendees: list[str] | None = None) -> str:
    svc = await google.service("calendar", "v3")
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": _parse(start).isoformat()},
        "end": {"dateTime": _parse(end).isoformat()},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    e = await google.call(svc.events().insert(calendarId="primary", body=body, sendUpdates="all" if attendees else "none"))
    return f"Created: {_fmt_event(e)}"


async def create_event_with_guests(title: str, start: str, end: str, attendees: list[str], description: str = "") -> str:
    return await create_event(title, start, end, description, attendees)


async def delete_event(event_id: str) -> str:
    svc = await google.service("calendar", "v3")
    await google.call(svc.events().delete(calendarId="primary", eventId=event_id))
    return f"Deleted event {event_id}"


async def move_event(event_id: str, start: str, end: str) -> str:
    svc = await google.service("calendar", "v3")
    e = await google.call(svc.events().get(calendarId="primary", eventId=event_id))
    e["start"] = {"dateTime": _parse(start).isoformat()}
    e["end"] = {"dateTime": _parse(end).isoformat()}
    e = await google.call(svc.events().update(calendarId="primary", eventId=event_id, body=e))
    return f"Moved: {_fmt_event(e)}"


async def free_slots(date: str, duration_minutes: int = 60) -> str:
    day = _parse(date).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=_tz()).replace(hour=7)
    end = start.replace(hour=22)
    svc = await google.service("calendar", "v3")
    res = await google.call(
        svc.events().list(calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True, orderBy="startTime")
    )
    busy = []
    for e in res.get("items", []):
        s, t = e.get("start", {}).get("dateTime"), e.get("end", {}).get("dateTime")
        if s and t:
            busy.append((_parse(s), _parse(t)))
    slots, cursor = [], start
    for s, t in sorted(busy):
        if s - cursor >= timedelta(minutes=duration_minutes):
            slots.append(f"{cursor.strftime('%H:%M')}-{s.strftime('%H:%M')}")
        cursor = max(cursor, t)
    if end - cursor >= timedelta(minutes=duration_minutes):
        slots.append(f"{cursor.strftime('%H:%M')}-{end.strftime('%H:%M')}")
    return f"Free on {day} (07:00-22:00, {duration_minutes}+ min): " + (", ".join(slots) if slots else "nothing")


async def set_reminder(text: str, at: str) -> str:
    due = _parse(at)
    async with session() as s:
        r = Reminder(text=text, due_at=due)
        s.add(r)
        await s.commit()
        await s.refresh(r)
    return f"Reminder #{r.id} set for {due.astimezone(_tz()).strftime('%a %d %b %H:%M')}: {text}"
