from evidence_agent.llm import FakeClient, LLMResponse, check_ollama, parse_ollama_message


def test_parse_string_arguments():
    r = parse_ollama_message({"tool_calls": [{"function": {"name": "conclude", "arguments": '{"a": 1}'}}]})
    assert r.tool_calls[0].arguments == {"a": 1}
    bad = parse_ollama_message({"tool_calls": [{"function": {"name": "x", "arguments": "{"}}]})
    assert bad.tool_calls[0].arguments == {"_raw": "{"}


def test_check_ollama_model_match():
    ok, _ = check_ollama("qwen3:4b", fetch=lambda u, t: {"models": [{"name": "qwen3:4b"}]})
    assert ok
    ok, msg = check_ollama("qwen3:4b", fetch=lambda u, t: {"models": [{"name": "llama3.2:latest"}]})
    assert not ok and "ollama pull qwen3:4b" in msg


def test_fake_client_runs_out():
    f = FakeClient([LLMResponse(content="a")])
    assert f.chat([], []).content == "a"
    assert "no more responses" in f.chat([], []).content
