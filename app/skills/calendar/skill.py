from app.agent.skills import Skill, Tool
from app.skills.calendar import gcal

ISO = {"type": "string", "description": "ISO 8601 local datetime, e.g. 2026-11-04T18:30"}

SKILL = Skill(
    name="calendar",
    description="Google Calendar: what's on, free slots, create/move/delete events, and one-off reminders.",
    tools=[
        Tool(
            name="list_events",
            description="List calendar events between two datetimes.",
            input_schema={"properties": {"start": ISO, "end": ISO}},
            handler=gcal.list_events,
        ),
        Tool(
            name="free_slots",
            description="Find free slots on a date (07:00-22:00) of at least duration_minutes.",
            input_schema={"properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}, "duration_minutes": {"type": "integer", "minimum": 15}}},
            handler=gcal.free_slots,
        ),
        Tool(
            name="create_event",
            description="Create a calendar event for him only (no guests). No approval needed.",
            input_schema={"properties": {"title": {"type": "string"}, "start": ISO, "end": ISO, "description": {"type": "string"}}},
            handler=lambda title, start, end, description: gcal.create_event(title, start, end, description),
        ),
        Tool(
            name="create_event_with_guests",
            description="Create a calendar event that invites other people by email. Goes through the approval gate.",
            input_schema={
                "properties": {
                    "title": {"type": "string"},
                    "start": ISO,
                    "end": ISO,
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                }
            },
            handler=gcal.create_event_with_guests,
            requires_approval=True,
            summarize=lambda a: f"Invite {', '.join(a['attendees'])} to '{a['title']}' at {a['start']}",
        ),
        Tool(
            name="move_event",
            description="Change the start and end of an existing event.",
            input_schema={"properties": {"event_id": {"type": "string"}, "start": ISO, "end": ISO}},
            handler=gcal.move_event,
        ),
        Tool(
            name="delete_event",
            description="Delete an event. Goes through the approval gate.",
            input_schema={"properties": {"event_id": {"type": "string"}}},
            handler=gcal.delete_event,
            requires_approval=True,
            summarize=lambda a: f"Delete calendar event {a['event_id']}",
        ),
        Tool(
            name="set_reminder",
            description="Send him a Telegram nudge with this text at the given time.",
            input_schema={"properties": {"text": {"type": "string"}, "at": ISO}},
            handler=gcal.set_reminder,
        ),
    ],
)
