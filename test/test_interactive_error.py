"""Tests for InteractiveRetryChatOpenAI — LLM error retry behaviour.

All patching is scoped to individual test functions using pytest monkeypatch
so that the mutations do NOT leak into other tests in the session.
"""

import pytest
from unittest.mock import patch, MagicMock
from utils.threads import _run_agent_in_thread


def _make_mock_agent(call_count_holder: list, fail_on_first: bool = True):
    """Return a simple callable that simulates an AgentExecutor with an LLM inside."""
    from llm.setup import InteractiveRetryChatOpenAI

    class MockAgent:
        def __init__(self):
            self.llm = InteractiveRetryChatOpenAI(
                api_key="sk-test",
                model="gpt-4",
                max_retries=0,
            )

        def invoke(self, *args, **kwargs):
            call_count_holder[0] += 1
            if fail_on_first and call_count_holder[0] == 1:
                raise ValueError("Simulated 429 Provider Error")
            return "SUCCESS"

    return MockAgent()


def test_interactive_retry_succeeds_on_second_attempt(monkeypatch):
    """InteractiveRetryChatOpenAI should retry when the user answers 'y'."""
    call_count = [0]

    # Patch safe_prompt to always return 'y' (simulate user pressing Enter/Y)
    monkeypatch.setattr("utils.terminal.safe_prompt", lambda msg, **kw: "y")
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: True))

    agent = _make_mock_agent(call_count, fail_on_first=True)

    # Override the LLM's invoke to use our agent's invoke tracking
    from langchain_openai import ChatOpenAI

    def fake_base_invoke(self_obj, *a, **k):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ValueError("Simulated 429 Provider Error")
        return "SUCCESS"

    monkeypatch.setattr(ChatOpenAI, "invoke", fake_base_invoke)

    class SimpleAgent:
        def __init__(self):
            from llm.setup import InteractiveRetryChatOpenAI
            self.llm = InteractiveRetryChatOpenAI(
                api_key="sk-test", model="gpt-4", max_retries=0
            )

        def invoke(self, *args, **kwargs):
            return self.llm.invoke("Hi")

    result = _run_agent_in_thread(SimpleAgent(), {}, "session", None, timeout=5)
    assert result == "SUCCESS"
    assert call_count[0] == 2, f"Expected 2 calls, got {call_count[0]}"


def test_interactive_retry_aborts_on_n(monkeypatch):
    """InteractiveRetryChatOpenAI should propagate the error when user answers 'n'."""
    call_count = [0]

    monkeypatch.setattr("utils.terminal.safe_prompt", lambda msg, **kw: "n")
    monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: True))

    from langchain_openai import ChatOpenAI

    def fake_base_invoke(self_obj, *a, **k):
        call_count[0] += 1
        raise ValueError("Simulated 429 Provider Error")

    monkeypatch.setattr(ChatOpenAI, "invoke", fake_base_invoke)

    class SimpleAgent:
        def __init__(self):
            from llm.setup import InteractiveRetryChatOpenAI
            self.llm = InteractiveRetryChatOpenAI(
                api_key="sk-test", model="gpt-4", max_retries=0
            )

        def invoke(self, *args, **kwargs):
            return self.llm.invoke("Hi")

    with pytest.raises(ValueError, match="Simulated 429 Provider Error"):
        _run_agent_in_thread(SimpleAgent(), {}, "session", None, timeout=5)

    assert call_count[0] == 1, f"Expected exactly 1 call, got {call_count[0]}"
