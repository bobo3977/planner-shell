#!/usr/bin/env python3
"""
Terminal and user interaction utilities.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import contextlib

from config import AUTO_APPROVE

# Initialize auto-approve mode globally
AUTO_APPROVE_MODE = False

# ANSI color codes for terminal output
BOLD = "\033[1m"
CYAN = "\033[36m"
RESET = "\033[0m"


def restore_terminal() -> None:
    """Restore terminal echo and canonical mode after PTY manipulation.

    Also resets common visual modes left by vim/nano/curses (hidden cursor,
    SGR attributes) so the prompt displays normally again.
    """
    import termios as _t
    try:
        fd = sys.stdin.fileno()
        if os.isatty(fd):
            attrs = _t.tcgetattr(fd)
            attrs[3] |= _t.ECHO | _t.ICANON
            _t.tcsetattr(fd, _t.TCSADRAIN, attrs)
    except (AttributeError, ValueError, _t.error):
        pass
    try:
        if sys.stdout.isatty():
            sys.stdout.write("\033[0m\033[?25h")
            sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        pass


def init_auto_approve_mode() -> None:
    """Initialize AUTO_APPROVE_MODE based on configuration."""
    set_auto_approve_mode(AUTO_APPROVE, silent=True)
    if AUTO_APPROVE_MODE:
        print(f"\n{BOLD}🤖 Auto-approve mode ENABLED (AUTO_APPROVE=1){RESET}")


def set_auto_approve_mode(enabled: bool, silent: bool = False) -> None:
    """Explicitly enable or disable auto-approve mode."""
    global AUTO_APPROVE_MODE
    AUTO_APPROVE_MODE = enabled
    if enabled and not silent:
        print(f"\n{BOLD}🤖 Auto-approve mode ENABLED for the current task.{RESET}")


def reset_auto_approve_mode() -> None:
    """Reset auto-approve mode to its configured default state."""
    global AUTO_APPROVE_MODE
    AUTO_APPROVE_MODE = AUTO_APPROVE


def safe_prompt(message: str, default: str | None = None, auto_approve: bool = True, abort_event: Optional[Any] = None) -> str:
    """Prompt for input, or return 'y' automatically in AUTO_APPROVE_MODE.
    
    If abort_event is provided and set, raises AbortExecutionException.
    If PLANNER_SHELL_TEST is set, returns 'default' if it's not None, otherwise 'n'.
    Handles EOFError for piped/redirected input.
    """
    if abort_event and abort_event.is_set():
        from common_types import AbortExecutionException
        raise AbortExecutionException("Execution aborted by user.")

    if AUTO_APPROVE_MODE and auto_approve:
        return 'y'
    # For testing: if PLANNER_SHELL_TEST env var is set, use provided default or 'n'
    if os.getenv("PLANNER_SHELL_TEST") == "1":
        return default if default is not None else 'n'
    try:
        user_input = input(message)
        if user_input.strip().lower() == 'y!':
            set_auto_approve_mode(True)
            return 'y'
        return user_input
    except (KeyboardInterrupt, EOFError) as e:
        # Handle Ctrl+C and EOF (piped input) gracefully
        if isinstance(e, KeyboardInterrupt):
            restore_terminal()
            if abort_event and abort_event.is_set():
                from common_types import AbortExecutionException
                raise AbortExecutionException("Execution aborted by user.")
            print("\n\n[!] Interrupted by user.")
            raise
        # For EOFError (piped input), return default or 'n' for consistency with test mode
        return default if default is not None else 'n'


def edit_in_vim(command: str) -> str:
    """Open *command* in $EDITOR (default: vim) and return the edited text.

    Security: uses shell=False to prevent shell injection via $EDITOR.
    The editor binary is validated to contain only safe characters.
    The temp file is always cleaned up even if an exception occurs.
    """
    # Shell injection guard: extract the first token only and whitelist characters.
    raw_editor = os.environ.get('EDITOR', 'vim').split()[0]
    if not re.fullmatch(r'[A-Za-z0-9/_.-]+', raw_editor):
        raw_editor = 'vim'
    editor = raw_editor

    fd, path = tempfile.mkstemp(suffix=".sh")
    edited = ""
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(command)
        # shell=False prevents $EDITOR value from being interpreted as shell syntax
        subprocess.run([editor, path])
        with open(path, 'r', encoding='utf-8') as f:
            edited = f.read()
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)
        restore_terminal()
    return edited.strip()
