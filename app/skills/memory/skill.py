from app.agent.skills import Skill, Tool
from app.skills.memory import store

SKILL = Skill(
    name="memory",
    description="Remember and recall facts, preferences, people and routines the user has told you.",
    always_on=True,
    tools=[
        Tool(
            name="remember",
            description="Save or update one fact about the user under a short stable key.",
            input_schema={
                "properties": {
                    "key": {"type": "string", "description": "snake_case key, e.g. gym_time"},
                    "value": {"type": "string"},
                    "category": {"type": "string", "enum": ["fact", "preference", "person", "routine"]},
                    "source": {"type": "string", "enum": ["user", "inferred"]},
                }
            },
            handler=store.remember,
        ),
        Tool(
            name="forget",
            description="Delete a saved fact by key.",
            input_schema={"properties": {"key": {"type": "string"}}},
            handler=store.forget,
        ),
        Tool(
            name="recall",
            description="Search saved memories by keyword.",
            input_schema={"properties": {"query": {"type": "string"}}},
            handler=lambda query: store.search(query),
        ),
    ],
)
