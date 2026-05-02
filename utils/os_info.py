#!/usr/bin/env python3
"""
OS information utilities and URL/markdown detection.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def get_detailed_os_info() -> str:
    """Return OS details for LLM context."""
    try:
        return subprocess.check_output(
            "uname -a && cat /etc/os-release 2>/dev/null", shell=True, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        import platform
        return f"{platform.system()} {platform.release()}"


_URL_RE = re.compile(
    r'^https?://'
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+'
    r'(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|localhost|\d{1,3}(?:\.\d{1,3}){3})'
    r'(?::\d+)?(?:/?|[/?]\S+)$',
    re.IGNORECASE,
)


def is_url(text: str) -> bool:
    """Check if text is a valid URL."""
    return bool(_URL_RE.match(text))


def is_markdown_file(text: str) -> bool:
    """Return True if *text* is a path to an existing markdown file.

    Security: resolves symlinks and restricts access to the current working
    directory to prevent path traversal (../../etc/passwd etc.).
    """
    try:
        if len(text) > 255 or not os.path.isfile(text):
            return False
        # Path traversal guard: reject anything outside cwd
        resolved = Path(text).resolve()
        resolved.relative_to(Path.cwd())
    except (OSError, ValueError):
        return False
    lower = text.lower()
    if lower.endswith('.md') or lower.endswith('.markdown'):
        return True
    # Fallback: peek for markdown headers
    try:
        with open(resolved, 'r', encoding='utf-8') as f:
            if re.search(r'^#{1,6}\s+', f.read(1024), re.MULTILINE):
                return True
    except OSError:
        pass
    return False
