import json
from types import SimpleNamespace

from app.llm.base import ToolSpec
from app.llm.openai_compat import from_openai_response, to_openai_messages, to_openai_tool


def test_canonical_history_converts_to_openai_shape():
    history = [
        {"role": "user", "content": "find my gym mail"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "secret"},
                {"type": "text", "text": "Looking."},
                {"type": "tool_use", "id": "c1", "name": "search_email", "input": {"query": "gym", "max_results": 5}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "[1] gym", "is_error": False}]},
        {"role": "assistant", "content": [{"type": "text", "text": "One mail."}]},
    ]
    out = to_openai_messages("SYS", history)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "find my gym mail"}
    assistant = out[2]
    assert assistant["content"] == "Looking." and "thinking" not in json.dumps(assistant)
    assert assistant["tool_calls"][0]["function"] == {"name": "search_email", "arguments": '{"query": "gym", "max_results": 5}'}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "[1] gym"}
    assert out[4] == {"role": "assistant", "content": "One mail."}


def test_error_results_are_marked():
    out = to_openai_messages("S", [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c", "content": "boom", "is_error": True}]}])
    assert out[1]["content"] == "ERROR: boom"


def test_tool_spec_to_function():
    t = to_openai_tool(ToolSpec("echo", "say it", {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}))
    assert t["type"] == "function" and t["function"]["name"] == "echo"
    assert t["function"]["parameters"]["required"] == ["word"]


def _resp(content=None, tool_calls=None, finish="stop"):
    calls = None
    if tool_calls:
        calls = [SimpleNamespace(id=i, function=SimpleNamespace(name=n, arguments=a)) for i, n, a in tool_calls]
    return SimpleNamespace(model="m", choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content, tool_calls=calls))])


def test_response_with_tool_calls_becomes_tool_use():
    c = from_openai_response(_resp("thinking out loud", [("x1", "echo", '{"word": "hi"}')], finish="tool_calls"))
    assert c.stop_reason == "tool_use"
    assert c.content[0] == {"type": "text", "text": "thinking out loud"}
    assert c.content[1] == {"type": "tool_use", "id": "x1", "name": "echo", "input": {"word": "hi"}}


def test_invalid_json_arguments_are_flagged_not_crashed():
    c = from_openai_response(_resp(None, [("x1", "echo", "{not json")], finish="tool_calls"))
    assert c.tool_uses[0]["input"] == {"__invalid_json__": "{not json"}


def test_finish_reasons():
    assert from_openai_response(_resp("a", finish="length")).stop_reason == "max_tokens"
    assert from_openai_response(_resp("a", finish="content_filter")).stop_reason == "refusal"
    assert from_openai_response(_resp("a")).stop_reason == "end_turn"
