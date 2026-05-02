#!/usr/bin/env python3
"""
LLM setup and helper functions for LangChain agents.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import config
from langchain.agents.factory import create_agent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama


def extract_agent_output(result: Any) -> str:
    """Extract string output from a LangChain agent result dict or AIMessage."""
    def _extract_string(val: Any, _seen: set = None, _depth: int = 0) -> str:
        """Recursively extract string content from various structures.

        The function tracks visited objects and recursion depth to avoid infinite recursion
        when encountering nested objects that reference each other via a ``content``
        attribute (which caused the original RecursionError).
        """
        if _seen is None:
            _seen = set()
        
        # Prevent infinite recursion by limiting depth
        if _depth > 10:
            return ""
        
        # Prevent infinite recursion by tracking visited object IDs
        obj_id = id(val)
        if obj_id in _seen:
            return ""
        _seen.add(obj_id)

        if isinstance(val, str):
            return val

        # Handle MagicMock objects - they have a content attribute that is also a MagicMock
        # which would cause infinite recursion
        if 'unittest.mock' in str(type(val)) or hasattr(val, '_mock_return_value'):
            # This is a MagicMock, return empty string to avoid recursion
            return ""

        # Handle content attribute safely using getattr to avoid __getattr__ issues
        content = getattr(val, "content", None)
        if content is not None:
            return _extract_string(content, _seen, _depth + 1)

        if isinstance(val, list):
            return "".join(_extract_string(v, _seen, _depth + 1) for v in val)

        if isinstance(val, dict):
            # Prefer explicit "text" key if present
            if "text" in val:
                return str(val["text"])
            # Fallback: concatenate string representations of values
            return "".join(_extract_string(v, _seen, _depth + 1) for v in val.values())

        return str(val)

    if hasattr(result, "content") and result.content:
        return _extract_string(result.content, _seen=set(), _depth=0)
    if isinstance(result, dict):
        if "output" in result:
            return _extract_string(result["output"], _seen=set(), _depth=0)
        if "messages" in result:
            # Look for the last message with content
            for msg in reversed(result["messages"]):
                if hasattr(msg, "content") and msg.content:
                    return _extract_string(msg.content, _seen=set(), _depth=0)
        # If no message content found, but it's a dict, don't fall back to JSON
        # unless it's a very simple result. Returning empty string is safer than raw JSON.
        return ""
    return _extract_string(result, _seen=set(), _depth=0)


def create_agent_with_tools(
    llm,
    tools: list,
    system_prompt_text: str,
    max_iterations: int = 10,
    recursion_limit: int = 500,
):
    """Create a LangChain agent, falling back for older versions."""
    try:
        return create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt_text,
            agent_executor_kwargs={
                "max_iterations": max_iterations,
                "early_stopping_method": "generate",
                "recursion_limit": recursion_limit,
            },
        )
    except TypeError:
        # Fallback for LangChain versions that don't support agent_executor_kwargs
        return create_agent(model=llm, tools=tools, system_prompt=system_prompt_text)


def _make_agent_with_history(llm, tools: list, system_prompt_text: str, **agent_kwargs):
    """Build an agent wrapped in RunnableWithMessageHistory."""
    agent = create_agent_with_tools(llm, tools, system_prompt_text, **agent_kwargs)
    memory = ChatMessageHistory()
    return RunnableWithMessageHistory(
        agent,
        lambda session_id: memory,
        input_messages_key="input",
        history_messages_key="chat_history",
    )


class InteractiveRetryMixin:
    """Mixin that adds interactive retry logic to any LangChain chat model."""
    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        while True:
            try:
                return super().invoke(input, config, **kwargs)
            except NotImplementedError:
                print("\n❌ Error: The selected LLM does not support tool calling (bind_tools).")
                print("   If you are using Ollama, try using llama3.1 or llama3.2 instead of llama3.")
                print("   Alternatively, ensure you have the latest langchain-ollama package installed.")
                raise
            except Exception as e:
                import sys
                error_str = str(e) or e.__class__.__name__
                print(f"\n❌ Provider API Error: {error_str}")
                if not sys.stdin.isatty():
                    raise e
                from utils.terminal import safe_prompt
                while True:
                    try:
                        print("You can retry the request to resume execution exactly where it left off.")
                        ans = safe_prompt("✅ Retry LLM request? [Y/n/q]: ").strip().lower()
                        if ans in ('y', 'yes', ''):
                            print("🔄 Retrying LLM request...")
                            break
                        if ans in ('n', 'no', 'q', 'quit'):
                            raise e
                    except (KeyboardInterrupt, EOFError):
                        raise e

class InteractiveRetryChatOpenAI(InteractiveRetryMixin, ChatOpenAI):
    """ChatOpenAI with interactive retry."""
    pass

class InteractiveRetryChatOllama(InteractiveRetryMixin, ChatOllama):
    """ChatOllama with interactive retry."""
    pass

def setup_llm():
    """Construct and return the LLM based on provider configuration.
    
    Priority:
    1. config.LLM_PROVIDER (if set)
    2. OPENROUTER_API_KEY
    3. OPENAI_API_KEY
    4. OLLAMA_BASE_URL (implicit discovery)
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    provider = config.LLM_PROVIDER.lower() if config.LLM_PROVIDER else None

    if not tavily_key:
        print("⚠️  Warning: TAVILY_API_KEY is not set.")
        print("   Web search via Tavily will be unavailable.")
        print("   Set TAVILY_API_KEY in .env or environment to enable search.")
        print("   Running in search-degraded mode (LLM-only planning).")
        print()

    # --- 1. Explicit Provider (if set) ---
    if provider == "ollama":
        print(f"🤖 LLM Provider: Ollama ({config.OLLAMA_MODEL})")
        # Use ChatOpenAI wrapper for Ollama to enable native bind_tools support
        # Ollama provides an OpenAI-compatible /v1/ endpoint
        base_url = config.OLLAMA_BASE_URL.rstrip('/')
        if not base_url.endswith('/v1'):
            base_url += '/v1'
            
        return InteractiveRetryChatOpenAI(
            base_url=base_url,
            api_key="ollama", # placeholder
            model=config.OLLAMA_MODEL,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_REQUEST_TIMEOUT,
            max_retries=1,
        )
    
    if provider == "openrouter":
        if not openrouter_key:
            print("❌ Error: OPENROUTER_API_KEY is required for OpenRouter provider.")
            sys.exit(1)
        print(f"🤖 LLM Provider: OpenRouter ({config.OPENROUTER_MODEL})")
        return InteractiveRetryChatOpenAI(
            model=config.OPENROUTER_MODEL,
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_REQUEST_TIMEOUT,
            max_retries=1,
        )

    if provider == "openai":
        if not openai_key:
            print("❌ Error: OPENAI_API_KEY is required for OpenAI provider.")
            sys.exit(1)
        print(f"🤖 LLM Provider: OpenAI ({config.OPENAI_MODEL})")
        return InteractiveRetryChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=openai_key,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_REQUEST_TIMEOUT,
            max_retries=1,
        )

    # --- 2. Auto-Discovery (Implicit) ---
    if openrouter_key:
        print("🤖 LLM Provider (discovered): OpenRouter")
        return InteractiveRetryChatOpenAI(
            model=config.OPENROUTER_MODEL,
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_REQUEST_TIMEOUT,
            max_retries=1,
        )

    if openai_key:
        print("🤖 LLM Provider (discovered): OpenAI")
        return InteractiveRetryChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=openai_key,
            temperature=config.LLM_TEMPERATURE,
            timeout=config.LLM_REQUEST_TIMEOUT,
            max_retries=1,
        )

    # Fallback to local Ollama if everything else fails
    print("🤖 LLM Provider (fallback): Ollama")
    return InteractiveRetryChatOllama(
        base_url=config.OLLAMA_BASE_URL,
        model=config.OLLAMA_MODEL,
        temperature=config.LLM_TEMPERATURE,
        timeout=config.LLM_REQUEST_TIMEOUT,
        max_retries=1,
    )
