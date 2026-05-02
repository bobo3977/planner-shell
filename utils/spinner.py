#!/usr/bin/env python3
"""
Shared background-spinner utility.

Usage (context manager):
    from utils.spinner import spinning
    with spinning("Generating plan..."):
        result = long_running_call()

Usage (explicit):
    from utils.spinner import start_spinner, stop_spinner
    start_spinner("Processing...")
    ...
    stop_spinner()
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from contextlib import contextmanager
from typing import Generator, Optional

# Module-level reference to the active spinner's state.
_active_stop_event: Optional[threading.Event] = None
_active_spinner_thread: Optional[threading.Thread] = None
_active_lock = threading.Lock()


def stop_active_spinner() -> None:
    """Stop the currently active background spinner (context-managed or explicit).
    
    This call is synchronous and waits for the spinner thread to finish clearing the line.
    """
    global _active_stop_event, _active_spinner_thread
    with _active_lock:
        ev = _active_stop_event
        t = _active_spinner_thread
        
    if ev is not None:
        ev.set()
    
    if t is not None:
        # Wait for the thread to finish its final line-clear
        t.join(timeout=2.0)

# Alias for backward compatibility and explicit usage
stop_spinner = stop_active_spinner


def start_spinner(message: str = "Processing...") -> None:
    """Start a background spinner that runs until stop_spinner() is called.
    
    If a spinner is already running, it is stopped first.
    """
    global _active_stop_event, _active_spinner_thread
    
    # Ensure any existing spinner is stopped
    stop_spinner()
    
    stop_event = threading.Event()
    
    def _spin() -> None:
        frames = itertools.cycle(['|', '/', '-', '\\'])
        while not stop_event.is_set():
            # \r moves to start, \033[K clears from cursor to end of line
            sys.stdout.write(f"\r{next(frames)} {message}\033[K")
            sys.stdout.flush()
            time.sleep(0.1)
        # Final clear: \r moves to start, \033[2K clears entire line, \r resets cursor
        sys.stdout.write('\r\033[2K\r')
        sys.stdout.flush()

    t = threading.Thread(target=_spin, daemon=True)
    with _active_lock:
        _active_stop_event = stop_event
        _active_spinner_thread = t
        
    t.start()


@contextmanager
def spinning(message: str = "Processing...") -> Generator[None, None, None]:
    """Context manager that shows a spinner in a background thread."""
    start_spinner(message)
    try:
        yield
    finally:
        stop_spinner()
