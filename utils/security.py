#!/usr/bin/env python3
"""
Security utilities: prompt injection detection, SSRF protection, content wrapping.
"""

from __future__ import annotations

import re
import socket
import ipaddress


# Prompt injection patterns — content containing these triggers a warning.
# We do NOT silently drop the content; we warn the user and let them decide.
_INJECTION_PATTERNS = [
    r'ignore\s+(previous|all|prior|above)\s+(instructions?|prompts?|rules?)',
    r'disregard\s+(previous|all|prior)',
    r'new\s+role\s*[:：]',
    r'act\s+as\s+(a\s+)?(?:new|different|another)',
    r'you\s+are\s+now\s+(?!an?\s+elite)',   # allow our own "You are now an Elite..."
    r'system\s*prompt\s*[:：]',
    r'<\s*system\s*>',
    r'<<<.*?>>>',
    r'\[\[.*?INST.*?\]\]',
]
_INJECTION_RE = re.compile('|'.join(_INJECTION_PATTERNS), re.IGNORECASE | re.DOTALL)


def _check_injection(content: str, source: str) -> bool:
    """Warn if *content* contains prompt-injection patterns. Returns True if detected."""
    if _INJECTION_RE.search(content):
        print(f"\n⚠️  WARNING: Possible prompt injection pattern detected in {source}.")
        print("   The content may attempt to override AI instructions.")
        print("   Review the content carefully before proceeding.")
        return True
    return False


def _wrap_external_content(content: str, label: str) -> str:
    """Wrap external content in XML-style delimiters so the LLM treats it as data,
    not as instructions.  This is the primary prompt injection mitigation.
    """
    return (
        f"<external_reference label=\"{label}\">\n"
        f"{content}\n"
        "</external_reference>"
    )


def _is_private_ip(ip_str: str) -> bool:
    """Return True if *ip_str* is a private/internal address."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (ip.is_private or ip.is_loopback or
                ip.is_link_local or ip.is_reserved or ip.is_unspecified)
    except ValueError:
        return True


def _is_private_url(url: str) -> bool:
    """Return True if *url* resolves to a private/internal address (SSRF guard).
    Note: For robust SSRF protection, use SafeHTTPHandlers to prevent DNS rebinding.
    """
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
        if not host:
            return True
        ip = socket.gethostbyname(host)
        return _is_private_ip(ip)
    except (OSError, ValueError):
        return True
