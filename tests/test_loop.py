from sqlalchemy import select

from app import approvals
from app.agent.loop import Agent
from app.agent.skills import Registry, Skill, Tool
from app.db.base import session
from app.db.models import Approval, AuditLog, Message
from tests.fakes import FakeProvider, RecordingNotifier, end_turn, text, tool_use, wants_tool


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


def last_tool_result(provider: FakeProvider, call_index: int) -> dict:
    return provider.calls[call_index].messages[-1]["content"][0]


async def test_plain_reply_is_persisted():
    agent = Agent(make_registry([]), provider=FakeProvider([end_turn(text("hi back"))]))
    assert await agent.run_turn("hi") == "hi back"
    async with session() as s:
        rows = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
    assert [m.role for m in rows] == ["user", "assistant"]


async def test_tool_call_runs_and_is_audited():
    provider = FakeProvider([wants_tool(tool_use("echo", {"word": "x"})), end_turn(text("done"))])
    assert await Agent(make_registry([]), provider=provider).run_turn("echo x") == "done"
    result = last_tool_result(provider, 1)
    assert result["type"] == "tool_result" and result["content"] == "echo:x"
    async with session() as s:
        log = (await s.execute(select(AuditLog))).scalars().all()
    assert len(log) == 1 and log[0].ok and log[0].tool == "echo"


async def test_approval_gate_blocks_until_yes():
    sent: list[str] = []
    reg = make_registry(sent)
    notifier = RecordingNotifier()
    provider = FakeProvider([wants_tool(tool_use("send", {"to": "a@b.c", "body": "yo"})), end_turn(text("waiting for you"))])
    await Agent(reg, provider=provider).run_turn("send yo to a@b.c", notifier=notifier)

    assert sent == [], "nothing may be sent before approval"
    assert len(notifier.approvals) == 1
    approval_id, summary = notifier.approvals[0]
    assert summary == "send to a@b.c"
    assert "Queued for approval" in last_tool_result(provider, 1)["content"]

    msg = await approvals.resolve(approval_id, True, reg, notifier)
    assert sent == ["a@b.c:yo"] and msg.startswith("Done.")
    async with session() as s:
        assert (await s.get(Approval, approval_id)).status == "done"


async def test_denied_approval_never_runs():
    sent: list[str] = []
    reg = make_registry(sent)
    notifier = RecordingNotifier()
    provider = FakeProvider([wants_tool(tool_use("send", {"to": "a@b.c", "body": "yo"})), end_turn(text("ok"))])
    await Agent(reg, provider=provider).run_turn("send", notifier=notifier)
    approval_id = notifier.approvals[0][0]
    msg = await approvals.resolve(approval_id, False, reg, notifier)
    assert sent == [] and msg.startswith("Denied")
    assert (await approvals.resolve(approval_id, True, reg, notifier)) == "Already denied."


async def test_tool_error_is_reported_not_raised():
    async def boom() -> str:
        raise RuntimeError("nope")

    reg = Registry()
    reg.register(Skill("x", "x", tools=[Tool("boom", "boom", {"properties": {}}, boom)]))
    provider = FakeProvider([wants_tool(tool_use("boom", {})), end_turn(text("it failed"))])
    assert await Agent(reg, provider=provider).run_turn("go") == "it failed"
    result = last_tool_result(provider, 1)
    assert result["is_error"] is True and "nope" in result["content"]


async def test_bad_arguments_from_model_are_rejected_before_handler():
    """Open models mistype arguments; the handler must never see them."""
    provider = FakeProvider(
        [
            wants_tool(tool_use("echo", {"wrod": "x"})),
            wants_tool(tool_use("echo", {"word": 5}, id="tu_2")),
            wants_tool(tool_use("echo", {"__invalid_json__": "{bad"}, id="tu_3")),
            end_turn(text("gave up")),
        ]
    )
    await Agent(make_registry([]), provider=provider).run_turn("echo")
    r1, r2, r3 = (last_tool_result(provider, i) for i in (1, 2, 3))
    assert r1["is_error"] and "unknown fields" in r1["content"]
    assert r2["is_error"] and "must be a string" in r2["content"]
    assert r3["is_error"] and "valid JSON" in r3["content"]
    async with session() as s:
        assert (await s.execute(select(AuditLog))).scalars().all() == []


async def test_request_shape():
    provider = FakeProvider([end_turn(text("ok"))])
    await Agent(make_registry([]), provider=provider).run_turn("hi")
    req = provider.calls[0]
    assert req.system_stable.startswith("You are Bharath's personal assistant")
    assert "Current time" in req.system_volatile
    echo = next(t for t in req.tools if t.name == "echo")
    assert echo.input_schema["required"] == ["word"] and echo.input_schema["additionalProperties"] is False
