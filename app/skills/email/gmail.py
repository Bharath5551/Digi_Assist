from __future__ import annotations

import base64
from email.message import EmailMessage

from app.integrations import google

MAX_BODY = 4000


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _body(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []) or []:
        text = _body(part)
        if text:
            return text
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    return ""


async def search(query: str, max_results: int = 15) -> str:
    svc = await google.service("gmail", "v1")
    res = await google.call(svc.users().messages().list(userId="me", q=query, maxResults=max_results))
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return "No messages match."
    lines = []
    for mid in ids:
        m = await google.call(svc.users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject", "Date"]))
        unread = "UNREAD" in m.get("labelIds", [])
        lines.append(f"[{mid}] {'* ' if unread else ''}{_header(m, 'From')} | {_header(m, 'Subject')} | {_header(m, 'Date')}\n    {m.get('snippet', '')[:160]}")
    return "\n".join(lines)


async def read(message_id: str) -> str:
    svc = await google.service("gmail", "v1")
    m = await google.call(svc.users().messages().get(userId="me", id=message_id, format="full"))
    body = _body(m.get("payload", {})).strip()
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n[truncated]"
    return (
        f"From: {_header(m, 'From')}\nTo: {_header(m, 'To')}\nDate: {_header(m, 'Date')}\n"
        f"Subject: {_header(m, 'Subject')}\nThread: {m.get('threadId')}\n\n{body}"
    )


async def send(to: str, subject: str, body: str, reply_to_message_id: str = "") -> str:
    svc = await google.service("gmail", "v1")
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    payload: dict = {}
    if reply_to_message_id:
        orig = await google.call(svc.users().messages().get(userId="me", id=reply_to_message_id, format="metadata", metadataHeaders=["Message-ID"]))
        mid = _header(orig, "Message-ID")
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = mid
        payload["threadId"] = orig.get("threadId")
    payload["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = await google.call(svc.users().messages().send(userId="me", body=payload))
    return f"Sent to {to} (id {sent.get('id')})"


async def modify_labels(message_id: str, add: list[str], remove: list[str]) -> str:
    svc = await google.service("gmail", "v1")
    await google.call(svc.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": add, "removeLabelIds": remove}))
    return f"Labels updated on {message_id}"


async def archive(message_id: str) -> str:
    return await modify_labels(message_id, add=[], remove=["INBOX", "UNREAD"])


async def trash(message_id: str) -> str:
    svc = await google.service("gmail", "v1")
    await google.call(svc.users().messages().trash(userId="me", id=message_id))
    return f"Moved {message_id} to trash"
