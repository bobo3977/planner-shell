#!/usr/bin/env python3
"""
Thread management and custom SIGINT handling for agent execution.
"""

from __future__ import annotations

import signal
import threading
import time
import uuid
from typing import Any, Optional



# ══════════════════════════════════════════════════════════════════
# Global thread registry
# ══════════════════════════════════════════════════════════════════

_active_threads: list[threading.Thread] = []
_thread_lock = threading.Lock()


def register_thread(thread: threading.Thread) -> None:
    """Register a thread for coordinated cleanup."""
    with _thread_lock:
        _active_threads.append(thread)


def unregister_thread(thread: threading.Thread) -> None:
    """Unregister a thread after it finishes."""
    with _thread_lock:
        if thread in _active_threads:
            _active_threads.remove(thread)


def cleanup_all_threads() -> None:
    """Attempt to clean up any lingering threads (best effort)."""
    with _thread_lock:
        for thread in _active_threads[:]:
            if thread.is_alive():
                print(f"⚠️  Thread {thread.name} is still alive (will terminate on process exit)")


# ══════════════════════════════════════════════════════════════════
# Custom SIGINT handler  ← core Ctrl+C fix for Python 3.12+
# ══════════════════════════════════════════════════════════════════

# Global reference to the shell for SIGINT forwarding
_sigint_shell: Optional[Any] = None  # Forward reference to PersistentShell
_sigint_hit_count: int = 0
_sigint_last_time: float = 0.0


def _sigint_pty_forward(signum, frame) -> None:
    """Custom SIGINT handler installed during agent execution.

    Root cause of the "worker thread dies on Ctrl+C" bug (Python 3.12+):
      Python's C signal handler calls _PyEval_SignalReceived(), setting the
      eval_breaker flag for ALL threads. Every thread then raises
      KeyboardInterrupt on the next bytecode, killing the worker silently.

    Fix: replace the default handler with this Python function, which does NOT
    call PyErr_SetInterrupt() — so eval_breaker is never broadcast. Instead it
    writes \\x03 directly to the PTY master; the line discipline delivers SIGINT
    to the child process. The child exits with code 130; execute() remaps
    130 → 0; the agent continues to the next plan step.

    Single Ctrl+C  → \\x03 to PTY (interrupt current command, plan continues).
    Double Ctrl+C  → restore default handler + raise KeyboardInterrupt (abort).
    """
    global _sigint_hit_count, _sigint_last_time
    now = time.time()
    if now - _sigint_last_time < 2.0:
        _sigint_hit_count += 1
    else:
        _sigint_hit_count = 1
    _sigint_last_time = now

    if _sigint_hit_count >= 2:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        _sigint_hit_count = 0
        print("\n[!] Ctrl+C pressed twice — aborting.")
        raise KeyboardInterrupt

    print("\n[!] Ctrl+C: interrupting current command... (press again within 2s to abort)")
    if _sigint_shell is not None and _sigint_shell.master_fd >= 0:
        try:
            import os
            os.write(_sigint_shell.master_fd, b'\x03')
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════
# Agent thread runner
# ══════════════════════════════════════════════════════════════════

def _run_agent_in_thread(
    agent_with_history,
    input_dict: dict,
    session_id: str,
    shell: Any,  # PersistentShell or _NullShell
    timeout: Optional[float] = None,
) -> Any:
    """Invoke agent_with_history.invoke() in a worker thread.

    Installs _sigint_pty_forward so Ctrl+C writes \\x03 to the PTY instead of
    raising KeyboardInterrupt in the worker thread (Python 3.12+ eval_breaker fix).

    Returns the raw agent result, or None if the agent finished without a result
    (e.g. interrupted mid-plan). Raises on unhandled exception or timeout.
    Double Ctrl+C re-raises KeyboardInterrupt to the caller.
    """
    result_container: list = []
    exception_container: list[Exception] = []

    def _target() -> None:
        try:
            result = agent_with_history.invoke(
                input_dict,
                config={"configurable": {"session_id": session_id}, "recursion_limit": 500},
            )
            result_container.append(result)
        except Exception as exc:
            exception_container.append(exc)

    thread = threading.Thread(target=_target, name=f"Agent-{uuid.uuid4().hex[:8]}")
    thread.daemon = True

    global _sigint_shell, _sigint_hit_count
    _sigint_shell = shell
    _sigint_hit_count = 0
    old_handler = signal.signal(signal.SIGINT, _sigint_pty_forward)

    thread.start()
    register_thread(thread)
    try:
        thread.join(timeout=timeout)
    except KeyboardInterrupt:
        # Double Ctrl+C — abort execution
        print("\n\n[!] Aborting execution...")
        # Try to kill the shell process if it exists (PersistentShell only)
        if _sigint_shell is not None and hasattr(_sigint_shell, 'process') and _sigint_shell.process > 0:
            try:
                import signal as _sig
                os.kill(_sigint_shell.process, _sig.SIGKILL)
            except OSError:
                pass
        # Wait for worker thread to finish (with short timeouts to remain responsive)
        import time as _time
        end_time = _time.time() + 5.0  # Wait up to 5 seconds for thread to finish
        while thread.is_alive() and _time.time() < end_time:
            try:
                thread.join(timeout=0.5)
            except KeyboardInterrupt:
                # User pressed Ctrl+C again during wait — just continue waiting
                pass
        if thread.is_alive():
            print("[!] Worker thread did not exit cleanly; it will be terminated when the program exits.")
        raise
    finally:
        signal.signal(signal.SIGINT, old_handler)
        _sigint_shell = None
        unregister_thread(thread)

    if thread.is_alive():
        raise TimeoutError(f"Agent execution exceeded {timeout} seconds")
    if exception_container:
        raise exception_container[0]
    return result_container[0] if result_container else None
