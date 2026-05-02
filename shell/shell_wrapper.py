#!/usr/bin/env python3
"""
Shell wrapper for non-host backends (Docker, Podman).

Provides a PersistentShell-compatible interface for container backends.
"""

from __future__ import annotations

import time
from typing import Tuple, Any

from shell.sandbox import ExecutionBackend


class ShellWrapper:
    """Wraps a non-host ExecutionBackend to provide PersistentShell-compatible interface."""

    def __init__(self, backend: ExecutionBackend) -> None:
        """Initialize wrapper around execution backend.
        
        Args:
            backend: ExecutionBackend instance (docker, podman, etc.)
        """
        self.backend = backend
        self.forward_stdin = True
        self.command_history: list[tuple[str, int, str, bool]] = []
        self.abort_event: Optional[Any] = None

    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute command via backend."""
        if self.abort_event and self.abort_event.is_set():
            return 1, "Execution aborted by user."
        return self.backend.execute(command, timeout=timeout, has_progress=has_progress, silent=silent)

    def interrupt(self) -> None:
        """Interrupt the currently running command via the backend."""
        self.backend.interrupt()

    def add_to_history(self, command: str, exit_code: int, output: str, skipped: bool = False) -> None:
        """Add an execution record to history."""
        self.command_history.append((command, exit_code, output, skipped))

    def close(self) -> None:
        """Cleanup backend resources."""
        self.backend.cleanup()

    def restart(self) -> None:
        """Restart the backend (if supported)."""
        # For container backends, restart would mean creating a new container
        # For now, this is a no-op since containers are stateless per command
        pass
