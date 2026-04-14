#!/usr/bin/env python3
"""
Common types and exceptions used across the planner-shell project.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Custom exception
# ══════════════════════════════════════════════════════════════════

class QuitExecutionException(Exception):
    """Raised when the user requests to quit and return to the main prompt."""


class FinishExecutionException(Exception):
    """Raised when the user requests to finish the plan execution early (success)."""


class AbortExecutionException(Exception):
    """Raised when the execution is aborted via double Ctrl+C to kill zombie threads."""


# ══════════════════════════════════════════════════════════════════
# Execution log — records every command attempted during a run
# ══════════════════════════════════════════════════════════════════

class ExecutionStep:
    """A single command attempted during plan execution."""

    __slots__ = ("command", "exit_code", "output", "succeeded")

    def __init__(self, command: str, exit_code: int, output: str):
        self.command = command
        self.exit_code = exit_code
        self.output = output
        self.succeeded = exit_code == 0

    def __repr__(self) -> str:
        status = "✅" if self.succeeded else "❌"
        return f"ExecutionStep({status} exit={self.exit_code} cmd={self.command[:60]!r})"


# ══════════════════════════════════════════════════════════════════
# Cache candidate dataclass
# ══════════════════════════════════════════════════════════════════

class CacheCandidate:
    """A scored plan-cache candidate returned by hybrid_search()."""

    __slots__ = (
        "task_hash", "task_text", "plan", "score",
        "fts_score", "vec_score", "timestamp", "url", "markdown_file"
    )

    def __init__(
        self,
        task_hash: str,
        task_text: str,
        plan: str,
        score: float,
        fts_score: float,
        vec_score: float,
        timestamp: datetime,
        url: Optional[str] = None,
        markdown_file: Optional[str] = None,
    ):
        self.task_hash = task_hash
        self.task_text = task_text
        self.plan = plan
        self.score = score
        self.fts_score = fts_score
        self.vec_score = vec_score
        self.timestamp = timestamp
        self.url = url
        self.markdown_file = markdown_file

    def __repr__(self) -> str:
        return (f"CacheCandidate(score={self.score:.4f}, task_hash={self.task_hash[:8]}..., "
                f"task_text={self.task_text[:50]!r})")
