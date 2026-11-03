from app.agent.router import LOAD_ALL_THRESHOLD, _keyword_route, route
from app.agent.skills import discover
from app.skills.memory import store


def test_discover_loads_phase1_skills():
    reg = discover()
    assert set(reg.names()) == {"memory", "email", "calendar", "daily_brief"}
    assert reg.get("memory").always_on
    assert reg.get("email").instructions.startswith("Gmail")
    # every tool definition is a valid strict schema
    for s in reg.all():
        for t in s.tools:
            api = t.to_api()
            assert api["strict"] and api["input_schema"]["additionalProperties"] is False
            assert set(api["input_schema"]["required"]) == set(api["input_schema"]["properties"])


def test_irreversible_tools_are_gated():
    reg = discover()
    gated = {t.name for s in reg.all() for t in s.tools if t.requires_approval}
    assert {"send_email", "trash_email", "delete_event", "create_event_with_guests"} <= gated


async def test_router_loads_all_when_few_skills():
    reg = discover()
    assert len([s for s in reg.all() if not s.always_on]) <= LOAD_ALL_THRESHOLD
    chosen = await route("anything", reg, client=None)
    assert {s.name for s in chosen} == set(reg.names())


def test_keyword_route():
    reg = discover()
    optional = [s for s in reg.all() if not s.always_on]
    assert {s.name for s in _keyword_route("check my gmail", optional)} == {"email"}


async def test_memory_roundtrip():
    assert (await store.remember("gym time", "5 am", "routine")).startswith("Saved")
    assert (await store.remember("gym_time", "5:30 am", "routine")).startswith("Updated")
    assert "gym_time" in await store.search("gym")
    assert "- gym_time: 5:30 am" in await store.snapshot()
    assert (await store.forget("gym_time")).startswith("Forgot")
    assert await store.search("gym") == "No matching memories."
