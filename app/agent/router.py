"""Pick which skills to load for a message.

With few skills, load everything (cheaper than a routing call). With many,
ask a small model to choose from the skill descriptions; fall back to
keyword hits, then to everything, if that call fails or returns nonsense.
"""

from __future__ import annotations

import logging
import re

import anthropic

from app.agent.skills import Registry, Skill
from app.config import get_settings

log = logging.getLogger(__name__)

LOAD_ALL_THRESHOLD = 5


async def route(text: str, registry: Registry, client: anthropic.AsyncAnthropic | None) -> list[Skill]:
    skills = registry.all()
    always = [s for s in skills if s.always_on]
    optional = [s for s in skills if not s.always_on]

    if len(optional) <= LOAD_ALL_THRESHOLD or client is None:
        return always + optional

    chosen = await _llm_route(text, optional, client)
    if chosen is None:
        chosen = _keyword_route(text, optional) or optional
    return always + chosen


def _keyword_route(text: str, optional: list[Skill]) -> list[Skill]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = []
    for s in optional:
        desc_words = set(re.findall(r"[a-z]+", (s.name + " " + s.description).lower()))
        if words & desc_words:
            hits.append(s)
    return hits


async def _llm_route(text: str, optional: list[Skill], client: anthropic.AsyncAnthropic) -> list[Skill] | None:
    menu = "\n".join(f"- {s.name}: {s.description}" for s in optional)
    prompt = (
        "You pick which skills an assistant needs to handle a message. "
        "Reply with the skill names only, comma-separated, nothing else. "
        "Pick every skill that could plausibly be needed; when unsure include it.\n\n"
        f"Skills:\n{menu}\n\nMessage:\n{text}"
    )
    try:
        resp = await client.messages.create(
            model=get_settings().router_model,
            max_tokens=256,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        log.warning("router call failed: %s", e)
        return None
    if resp.stop_reason != "end_turn":
        return None
    raw = "".join(b.text for b in resp.content if b.type == "text")
    names = {n.strip().lower() for n in raw.split(",")}
    chosen = [s for s in optional if s.name.lower() in names]
    return chosen or None
