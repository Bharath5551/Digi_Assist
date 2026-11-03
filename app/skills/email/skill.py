from app.agent.skills import Skill, Tool
from app.skills.email import gmail

SKILL = Skill(
    name="email",
    description="Gmail: search, read, triage, archive, draft and send email (sending needs approval).",
    tools=[
        Tool(
            name="search_email",
            description="Search Gmail with normal Gmail query syntax (e.g. 'is:unread newer_than:1d', 'from:amazon'). Returns ids, sender, subject, date, snippet.",
            input_schema={
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                }
            },
            handler=gmail.search,
        ),
        Tool(
            name="read_email",
            description="Read the full text of one email by id.",
            input_schema={"properties": {"message_id": {"type": "string"}}},
            handler=gmail.read,
        ),
        Tool(
            name="send_email",
            description="Send an email, or reply in a thread when reply_to_message_id is given (empty string for a new mail). Goes through the approval gate.",
            input_schema={
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "reply_to_message_id": {"type": "string"},
                }
            },
            handler=gmail.send,
            requires_approval=True,
            summarize=lambda a: f"Send email to {a['to']}\nSubject: {a['subject']}\n\n{a['body'][:800]}",
        ),
        Tool(
            name="archive_email",
            description="Archive an email (remove from inbox, mark read).",
            input_schema={"properties": {"message_id": {"type": "string"}}},
            handler=gmail.archive,
        ),
        Tool(
            name="trash_email",
            description="Move an email to trash. Goes through the approval gate.",
            input_schema={"properties": {"message_id": {"type": "string"}}},
            handler=gmail.trash,
            requires_approval=True,
            summarize=lambda a: f"Trash email {a['message_id']}",
        ),
    ],
)
