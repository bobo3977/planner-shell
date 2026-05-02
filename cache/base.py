#!/usr/bin/env python3
"""
Base plan cache interface and common utilities.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

from common_types import CacheCandidate
from config import DISABLE_EMBEDDINGS


# ══════════════════════════════════════════════════════════════════
# Lightweight cosine similarity (no numpy required)
# ══════════════════════════════════════════════════════════════════

def _cosine(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between two equal-length float vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ══════════════════════════════════════════════════════════════════
# Embedding helper (lazy import to avoid hard dependency)
# ══════════════════════════════════════════════════════════════════

def _get_embedding(text: str, model: str = None) -> Optional[list[float]]:
    """Call the Embeddings API and return a float vector, or None on error.

    Backend selection mirrors setup_llm() priority.
    """
    if DISABLE_EMBEDDINGS:
        return None

    import config
    provider = config.LLM_PROVIDER.lower() if config.LLM_PROVIDER else None
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    api_key = None
    endpoint = None
    payload = {}
    is_ollama = False

    # 1. Explicit Provider
    if provider == "ollama":
        endpoint = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
        model = model or config.OLLAMA_EMBEDDING_MODEL
        payload = {"model": model, "prompt": text}
        is_ollama = True

    elif provider == "openrouter":
        if not openrouter_key:
            return None
        api_key = openrouter_key
        endpoint = "https://openrouter.ai/api/v1/embeddings"
        model = model or config.EMBEDDING_MODEL
        payload = {"model": model, "input": text}
    elif provider == "openai":
        if not openai_key:
            return None
        api_key = openai_key
        endpoint = "https://api.openai.com/v1/embeddings"
        model = model or config.EMBEDDING_MODEL
        payload = {"model": model, "input": text}
    
    # 2. Implicit Discovery (only if no explicit provider set)
    elif openrouter_key:
        api_key = openrouter_key
        endpoint = "https://openrouter.ai/api/v1/embeddings"
        model = model or config.EMBEDDING_MODEL
        payload = {"model": model, "input": text}
    elif openai_key:
        api_key = openai_key
        endpoint = "https://api.openai.com/v1/embeddings"
        model = model or config.EMBEDDING_MODEL
        payload = {"model": model, "input": text}
    else:
        # Fallback to local Ollama if everything else fails
        endpoint = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
        model = model or config.OLLAMA_EMBEDDING_MODEL
        payload = {"model": model, "prompt": text}
        is_ollama = True

    try:
        data_encoded = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        req = urllib.request.Request(endpoint, data=data_encoded, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        
        # Ollama returns {"embedding": [...]}, others return {"data": [{"embedding": [...]}]}
        if is_ollama:
            return data.get("embedding")
        return data["data"][0]["embedding"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


# ══════════════════════════════════════════════════════════════════
# SQLite datetime adapters (Python 3.12+ compatibility)
# ══════════════════════════════════════════════════════════════════

def _adapt_datetime(dt: datetime) -> str:
    return dt.isoformat()

def _convert_datetime(s: bytes) -> datetime:
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("DATETIME", _convert_datetime)


# ══════════════════════════════════════════════════════════════════
# Base cache class
# ══════════════════════════════════════════════════════════════════

class BasePlanCache(ABC):
    """Abstract base class for plan cache implementations."""

    ALPHA: float = 0.6
    SCORE_THRESHOLD: float = 0.0
    MAX_CANDIDATES: int = 3

    # ── Shared helpers (identical in every backend) ───────────────
    def _hash_task(self, task: str) -> str:
        return hashlib.sha256(task.strip().lower().encode()).hexdigest()[:32]

    def _cutoff(self) -> datetime:
        return datetime.now() - timedelta(days=self.ttl_days)

    @abstractmethod
    def get(self, task: str) -> Optional[str]:
        """Fast O(1) exact-match lookup. Returns plan text or None."""
        pass

    @abstractmethod
    def get_by_hash(self, task_hash: str) -> Optional[str]:
        """Retrieve a plan by its exact task hash."""
        pass

    @abstractmethod
    def get_meta(self, task: str) -> Optional[dict]:
        """Return metadata dict {task_hash, task_text, url, markdown_file} for *task*, or None."""
        pass

    @abstractmethod
    def set(self, task: str, plan: str, skip_embedding: bool = False,
            embedding_text: Optional[str] = None, url: Optional[str] = None,
            markdown_file: Optional[str] = None, task_text: Optional[str] = None,
            task_hash: Optional[str] = None) -> None:
        """Store plan with optional embedding."""
        pass

    @abstractmethod
    def hybrid_search(self, task: str) -> list[CacheCandidate]:
        """Return up to MAX_CANDIDATES scored candidates for *task*."""
        pass

    def optimize(self) -> None:
        """Perform backend-specific optimizations."""
        pass  # Default: no-op

    @abstractmethod
    def clear(self) -> None:
        pass

    @abstractmethod
    def cleanup_expired(self, batch_size: int = 1000) -> int:
        pass

    @abstractmethod
    def get_stats(self) -> dict:
        pass

    @abstractmethod
    def list_plans(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List recent plans with metadata.

        Args:
            limit: Maximum number of plans to return
            offset: Number of plans to skip (for pagination)

        Returns:
            list of dicts with keys: index, task_hash, task_text, timestamp, url, markdown_file
            index is 1-based and represents position in the list (1 = newest)
        """
        pass

    @abstractmethod
    def delete(self, task_text: str, index: Optional[int] = None) -> bool:
        """Delete a specific plan by task text (partial match) or by index.

        Args:
            task_text: Task text to match (partial)
            index: Optional 1-based index from list_plans() output (newest first)

        Returns:
            True if a plan was deleted, False if no match found
        """
        pass
