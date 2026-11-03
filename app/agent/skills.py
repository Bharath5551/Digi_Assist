"""Skill framework.

A skill is a folder under app/skills/<name>/ with:
  SKILL.md   instructions the agent reads when the skill is loaded
  skill.py   exports SKILL: a Skill with its tools

The router picks which skills to load for a message; only their tools and
instructions go to the model. Adding a capability means adding a folder.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ToolHandler = Callable[..., Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    requires_approval: bool = False
    # Human-readable one-liner shown on the approval card. Receives the tool args.
    summarize: Callable[[dict[str, Any]], str] | None = None

    def to_api(self) -> dict[str, Any]:
        schema = dict(self.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("additionalProperties", False)
        schema.setdefault("required", list(schema["properties"].keys()))
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            "strict": True,
        }

    def summary(self, args: dict[str, Any]) -> str:
        if self.summarize:
            return self.summarize(args)
        return f"{self.name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"


@dataclass
class Skill:
    name: str
    description: str  # one line, used by the router to decide when to load it
    tools: list[Tool] = field(default_factory=list)
    always_on: bool = False
    instructions: str = ""

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)


class Registry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"duplicate skill {skill.name}")
        names = [t.name for t in skill.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names in skill {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        return self._skills[name]

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills)

    def find_tool(self, tool_name: str, loaded: list[Skill]) -> tuple[Skill, Tool] | None:
        for s in loaded:
            t = s.tool(tool_name)
            if t:
                return s, t
        return None


def discover(package: str = "app.skills") -> Registry:
    """Import every app/skills/<name>/skill.py and read its SKILL.md."""
    reg = Registry()
    pkg = importlib.import_module(package)
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg:
            continue
        mod = importlib.import_module(f"{package}.{info.name}.skill")
        skill: Skill = getattr(mod, "SKILL")
        md = Path(mod.__file__).parent / "SKILL.md"
        if md.exists() and not skill.instructions:
            skill.instructions = md.read_text(encoding="utf-8").strip()
        reg.register(skill)
    return reg
