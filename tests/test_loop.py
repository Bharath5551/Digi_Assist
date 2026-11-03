from sqlalchemy import select

from app import approvals
from app.agent.loop import Agent
from app.agent.skills import Registry, Skill, Tool
from app.db.base import session
from app.db.models import Approval, AuditLog, Message
from tests.fakes import FakeClient, RecordingNotifier, end_turn, text, tool_use, wants_tool


def make_registry(sent: list[str]) -> Registry:
    async def echo(word: str) -> str:
        return f"echo:{word}"

    async def send(to: str, body: str) -> str:
        sent.append(f"{to}:{body}")
        return f"sent to {to}"

    reg = Registry()
    reg.register(
        Skill(
            name="demo",
            description="demo skill",
            tools=[
                Tool("echo", "echo a word", {"properties": {"word": {"type": "string"}}}, echo),
                Tool(
                    "send",
                    "send something",
                    {"properties": {"to": {"type": "string"}, "body": {"type": "string"}}},
                    send,
                    requires_approval=True,
                    summarize=lambda a: f"send to {a['to']}",
                ),
            ],
        )
    )
    return reg


async def test_plain_reply_is_persisted():
    reg = make_registry([])
    agent = Agent(reg, client=FakeClient([end_turn(text("hi back"))]))
    reply = await agent.run_turn("hi")
    assert reply == "hi back"
    async with session() as s:
        rows = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
    assert [m.role for m in rows] == ["user", "assistant"]


async def test_tool_call_runs_and_is_audited():
    reg = make_registry([])
    client = FakeClient([wants_tool(tool_use("echo", {"word": "x"})), end_turn(text("done"))])
    agent = Agent(reg, client=client)
    reply = await agent.run_turn("echo x")
    assert reply == "done"
    # the tool result went back to the model
    second_call = client.beta.messages.calls[1]
    results = second_call["messages"][-1]["content"]
    assert results[0]["type"] == "tool_result" and results[0]["content"] == "echo:x"
    async with session() as s:
        log = (await s.execute(select(AuditLog))).scalars().all()
    assert len(log) == 1 and log[0].ok and log[0].tool == "echo"


async def test_approval_gate_blocks_until_yes():
    sent: list[str] = []
    reg = make_registry(sent)
    notifier = RecordingNotifier()
    client = FakeClient([wants_tool(tool_use("send", {"to": "a@b.c", "body": "yo"})), end_turn(text("waiting for you"))])
    agent = Agent(reg, client=client)
    await agent.run_turn("send yo to a@b.c", notifier=notifier)

    assert sent == [], "nothing may be sent before approval"
    assert len(notifier.approvals) == 1
    approval_id, summary = notifier.approvals[0]
    assert summary == "send to a@b.c"
    tool_result = client.beta.messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert "Queued for approval" in tool_result

    msg = await approvals.resolve(approval_id, True, reg, notifier)
    assert sent == ["a@b.c:yo"]
    assert msg.startswith("Done.")
    async with session() as s:
        a = await s.get(Approval, approval_id)
    assert a.status == "done"


async def test_denied_approval_never_runs():
    sent: list[str] = []
    reg = make_registry(sent)
    notifier = RecordingNotifier()
    client = FakeClient([wants_tool(tool_use("send", {"to": "a@b.c", "body": "yo"})), end_turn(text("ok"))])
    await Agent(reg, client=client).run_turn("send", notifier=notifier)
    approval_id = notifier.approvals[0][0]
    msg = await approvals.resolve(approval_id, False, reg, notifier)
    assert sent == [] and msg.startswith("Denied")
    assert (await approvals.resolve(approval_id, True, reg, notifier)) == "Already denied."


async def test_tool_error_is_reported_not_raised():
    async def boom() -> str:
        raise RuntimeError("nope")

    reg = Registry()
    reg.register(Skill("x", "x", tools=[Tool("boom", "boom", {"properties": {}}, boom)]))
    client = FakeClient([wants_tool(tool_use("boom", {})), end_turn(text("it failed"))])
    reply = await Agent(reg, client=client).run_turn("go")
    assert reply == "it failed"
    result = client.beta.messages.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "nope" in result["content"]


async def test_request_shape():
    reg = make_registry([])
    client = FakeClient([end_turn(text("ok"))])
    await Agent(reg, client=client).run_turn("hi")
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    tool = next(t for t in call["tools"] if t["name"] == "echo")
    assert tool["strict"] is True and tool["input_schema"]["required"] == ["word"]
