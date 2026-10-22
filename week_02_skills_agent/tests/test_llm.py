from skills_agent.llm import FakeClient, LLMResponse, check_ollama, parse_ollama_message


def test_parse_tool_calls_with_string_arguments():
    r = parse_ollama_message({"content": "", "tool_calls": [
        {"function": {"name": "load_skill", "arguments": '{"name": "team-glossary"}'}},
        {"function": {"name": "load_skill", "arguments": "not json"}}]})
    assert r.tool_calls[0].arguments == {"name": "team-glossary"}
    assert r.tool_calls[1].arguments == {"_raw": "not json"}


def test_fake_client_runs_out_politely():
    assert "no more" in FakeClient([]).chat([], []).content
    assert FakeClient([LLMResponse(content="a")]).chat([], []).content == "a"


def test_check_ollama_model_pulled_and_missing():
    ok, _ = check_ollama("qwen3:4b", fetch=lambda u, t: {"models": [{"name": "qwen3:4b"}]})
    assert ok
    ok, msg = check_ollama("qwen3:4b", fetch=lambda u, t: {"models": []})
    assert not ok and "ollama pull qwen3:4b" in msg


def test_check_ollama_unreachable():
    def boom(u, t):
        raise OSError("refused")
    ok, msg = check_ollama(fetch=boom)
    assert not ok and "ollama serve" in msg
