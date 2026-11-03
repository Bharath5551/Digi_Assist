"""Pick which skills to load for a message.

With few skills, load everything (cheaper than a routing call). With many,
ask the model to choose from the skill descriptions; fall back to keyword
hits, then to everything, if that call fails or returns nonsense.
"""

from __future__ import annotations

import logging
import re

from app.agent.skills import Registry, Skill
from app.llm.base import Provider

log = logging.getLogger(__name__)

LOAD_ALL_THRESHOLD = 5


async def route(text: str, registry: Registry, provider: Provider | None) -> list[Skill]:
    skills = registry.all()
    always = [s for s in skills if s.always_on]
    optional = [s for s in skills if not s.always_on]

    if len(optional) <= LOAD_ALL_THRESHOLD or provider is None:
        return always + optional

    chosen = await _llm_route(text, optional, provider)
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


async def _llm_route(text: str, optional: list[Skill], provider: Provider) -> list[Skill] | None:
    menu = "\n".join(f"- {s.name}: {s.description}" for s in optional)
    prompt = (
        "You pick which skills an assistant needs to handle a message. "
        "Reply with the skill names only, comma-separated, nothing else. "
        "Pick every skill that could plausibly be needed; when unsure include it.\n\n"
        f"Skills:\n{menu}\n\nMessage:\n{text}"
    )
    try:
        raw = await provider.quick(prompt)
    except Exception as e:  # noqa: BLE001 - any provider error means fall back, not crash
        log.warning("router call failed: %s", e)
        return None
    names = {n.strip().lower().strip("-* ") for n in re.split(r"[,\n]", raw)}
    chosen = [s for s in optional if s.name.lower() in names]
    return chosen or None
