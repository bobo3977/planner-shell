#!/usr/bin/env python3
"""
Configuration loader for the AI DevOps Agent.

Loads settings from environment variables with sensible defaults.
All settings can be overridden via .env file or environment variables.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def load_prompt(name: str, required_vars: list[str] = None) -> str:
    """Load a prompt template.

    Args:
        name: Prompt name (without extension)
        required_vars: List of required variables (e.g., ['{task}', '{os_info}'])

    Returns:
        Prompt string

    Raises:
        ValueError: If required variables are missing
    """
    # Get prompt directory from environment variable, default is ~/.config/planner-shell/prompts
    prompt_dir = os.getenv(
        "PROMPT_DIR",
        os.path.join(os.path.expanduser("~"), ".config", "planner-shell", "prompts")
    )
    prompt_path = Path(prompt_dir) / f"{name}.md"

    # Load user-defined prompt file if it exists
    if prompt_path.is_file():
        try:
            content = prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"Warning: Failed to load prompt file '{prompt_path}': {e}")
            content = None
    else:
        content = None

    # Use default if user file not found
    if content is None:
        try:
            from agents.prompts.default import DEFAULT_PROMPTS
            content = DEFAULT_PROMPTS.get(name, "")
        except ImportError:
            content = ""

    # Required variables validation
    if required_vars:
        missing = [var for var in required_vars if var not in content]
        if missing:
            raise ValueError(
                f"Prompt '{name}' is missing required variables: {missing}\n"
                f"File: {prompt_path if prompt_path.is_file() else 'default'}\n"
                "You can specify a directory using the PROMPT_DIR environment variable."
            )

    return content


def get_int(key: str, default: int) -> int:
    """Get an integer value from environment variable, or return default."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float) -> float:
    """Get a float value from environment variable, or return default."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool) -> bool:
    """Get a boolean value from environment variable, or return default."""
    val = os.getenv(key, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


# ══════════════════════════════════════════════════════════════════
# Agent Configuration
# ══════════════════════════════════════════════════════════════════

# Maximum consecutive failures before stopping execution
MAX_CONSECUTIVE_FAILURES = get_int("MAX_CONSECUTIVE_FAILURES", 10)

# Maximum number of Tavily searches allowed per command execution
MAX_SEARCHES_PER_COMMAND = get_int("MAX_SEARCHES_PER_COMMAND", 3)

# Tavily API Key for web search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


# ══════════════════════════════════════════════════════════════════
# Cache Configuration
# ══════════════════════════════════════════════════════════════════

# Cache backend: "sqlite" or "singlestore"
CACHE_BACKEND = os.getenv("PLAN_CACHE_BACKEND", "sqlite").lower().strip()

# SQLite database path (default: .plan_cache.db)
PLAN_CACHE_DB_PATH = os.getenv("PLAN_CACHE_DB_PATH", ".plan_cache.db")

# Alpha parameter for hybrid search (0 = pure FTS, 1 = pure vector)
PLAN_CACHE_ALPHA = get_float("PLAN_CACHE_ALPHA", 0.6)

# Maximum number of candidates to return from hybrid search
PLAN_CACHE_MAX_CANDIDATES = get_int("PLAN_CACHE_MAX_CANDIDATES", 3)

# Minimum hybrid score threshold (0.0 = no threshold)
PLAN_CACHE_SCORE_THRESHOLD = get_float("PLAN_CACHE_SCORE_THRESHOLD", 0.0)

# Cache TTL in days (default: 30 days)
PLAN_CACHE_TTL_DAYS = get_int("PLAN_CACHE_TTL_DAYS", 30)


# ══════════════════════════════════════════════════════════════════
# SingleStore Configuration
# ══════════════════════════════════════════════════════════════════

# SingleStore connection settings (only used if CACHE_BACKEND=singlestore)
SINGLESTORE_HOST = os.getenv("SINGLESTORE_HOST", "localhost")
SINGLESTORE_PORT = get_int("SINGLESTORE_PORT", 3306)
SINGLESTORE_USER = os.getenv("SINGLESTORE_USER", "root")
SINGLESTORE_PASSWORD = os.getenv("SINGLESTORE_PASSWORD", "")
SINGLESTORE_DATABASE = os.getenv("SINGLESTORE_DATABASE", "inst_agent")


# ══════════════════════════════════════════════════════════════════
# LLM Configuration
# ══════════════════════════════════════════════════════════════════

# OpenAI model name (used when OPENAI_API_KEY is set)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-nano")

# OpenRouter model name (used when OPENROUTER_API_KEY is set)
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5-nano")

# LLM provider: "openai", "openrouter", "ollama" (optional)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", None)

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")

# LLM temperature (0 = deterministic, higher = more creative)
LLM_TEMPERATURE = get_float("LLM_TEMPERATURE", 0)

# Timeout for individual LLM API requests in seconds (default: 120)
LLM_REQUEST_TIMEOUT = get_float("LLM_REQUEST_TIMEOUT", 120.0)


# ══════════════════════════════════════════════════════════════════
# Embedding Configuration
# ══════════════════════════════════════════════════════════════════

# Embedding model to use for vector search
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Embedding dimension (default: 1536 for OpenAI, 1024 for Ollama mxbai-embed-large)
EMBEDDING_DIMENSION = get_int("EMBEDDING_DIMENSION", 1536)


# ══════════════════════════════════════════════════════════════════
# Timeout Configuration (seconds)
# ══════════════════════════════════════════════════════════════════

# Timeout for plan generation (default: 180 seconds)
PLAN_TIMEOUT = get_int("PLAN_TIMEOUT", 180)

# Timeout for plan execution (default: 3600 seconds = 60 minutes)
EXECUTE_TIMEOUT = get_int("EXECUTE_TIMEOUT", 3600)


# ══════════════════════════════════════════════════════════════════
# Shell Configuration
# ══════════════════════════════════════════════════════════════════

# Maximum output bytes before truncation (default: 10 MB)
MAX_OUTPUT_BYTES = get_int("MAX_OUTPUT_BYTES", 10 * 1024 * 1024)

# Periodic cleanup interval in seconds (default: 3600 = 1 hour)
CLEANUP_INTERVAL = get_int("CLEANUP_INTERVAL", 3600)


# ══════════════════════════════════════════════════════════════════
# Privacy & Features
# ══════════════════════════════════════════════════════════════════

# Set to 1 to disable embeddings API (skip vector search)
DISABLE_EMBEDDINGS = get_bool("DISABLE_EMBEDDINGS", False)

# Set to 1 to enable the Auditor Agent for security review of plans
ENABLE_AUDITOR = get_bool("ENABLE_AUDITOR", True)


# Set to 1 to enable FileEditorTool for safe file read/write/append/str_replace
ENABLE_FILE_EDITOR = get_bool("ENABLE_FILE_EDITOR", False)


# ══════════════════════════════════════════════════════════════════
# Sandbox/Container Configuration
# ══════════════════════════════════════════════════════════════════

# Sandbox backend: "host" (direct execution), "docker" or "podman"
# Default: "host" for backward compatibility with existing behavior
SANDBOX_TYPE = os.getenv("SANDBOX_TYPE", "host").lower().strip()

# For container backends (docker, podman), specify the base image
# Default: ubuntu:24.04 for Docker, docker.io/library/ubuntu:24.04 for Podman
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", None)

# List of port mappings for sandbox (e.g., ["8088:8088", "3000:3000"])
SANDBOX_PORTS = os.getenv("SANDBOX_PORTS", "").split(",") if os.getenv("SANDBOX_PORTS") else []



# ══════════════════════════════════════════════════════════════════
# Auto-approve Mode
# ══════════════════════════════════════════════════════════════════

# Set to 1 to auto-approve all commands (no interactive prompts)
AUTO_APPROVE = get_bool("AUTO_APPROVE", False)
