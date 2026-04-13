#!/usr/bin/env python3
"""
I/O utilities: reading files, fetching URLs, extracting titles.
"""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Optional
import ssl

from utils.security import _is_private_url, _is_private_ip


import urllib.error
from typing import Any
import socket
import http.client

class SafeHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        try:
            ip = socket.gethostbyname(self.host)
        except OSError as e:
            raise urllib.error.URLError(f"DNS resolution failed: {e}")
        
        if _is_private_ip(ip):
            raise urllib.error.URLError(f"SSRF blocked: Host {self.host} resolved to internal IP {ip}")
            
        self.sock = socket.create_connection((ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()

class SafeHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        try:
            ip = socket.gethostbyname(self.host)
        except OSError as e:
            raise urllib.error.URLError(f"DNS resolution failed: {e}")
            
        if _is_private_ip(ip):
            raise urllib.error.URLError(f"SSRF blocked: Host {self.host} resolved to internal IP {ip}")
            
        self.sock = socket.create_connection((ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
            
        server_hostname = self.host if not self._tunnel_host else self._tunnel_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)

class SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(SafeHTTPConnection, req)

class SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(SafeHTTPSConnection, req, context=self._context)

class SSRFHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Optional[urllib.request.Request]:
        if _is_private_url(newurl):
            raise urllib.error.URLError(f"SSRF blocked: Redirect to private URL {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_markdown_file(filepath: str) -> str:
    """Read a markdown file and return its contents."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading markdown file: {e}"


def extract_url_title(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch URL and extract the page title from HTML.

    Uses urllib to fetch the page and HTMLParser to extract <title>.
    Returns the title text (stripped) or None on error/timeout.
    """
    if _is_private_url(url):
        return None

    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; planner-shell/1.0)'}
        )
        ctx = ssl.create_default_context()
        opener = urllib.request.build_opener(
            SafeHTTPHandler(),
            SafeHTTPSHandler(context=ctx),
            SSRFHTTPRedirectHandler()
        )
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'html' not in content_type:
                return None  # Not HTML

            html = resp.read().decode('utf-8', errors='replace')

        # Extract title using HTMLParser
        class TitleParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_title = False
                self.title = []

            def handle_starttag(self, tag, attrs):
                if tag.lower() == 'title':
                    self.in_title = True

            def handle_endtag(self, tag):
                if tag.lower() == 'title':
                    self.in_title = False

            def handle_data(self, data):
                if self.in_title:
                    self.title.append(data.strip())

        parser = TitleParser()
        parser.feed(html)
        if parser.title:
            title = ' '.join(parser.title).strip()
            # Limit to 200 chars (same as other task_text fields)
            return title[:200] if title else None
        return None
    except Exception:
        return None


def fetch_url_content(url: str) -> str:
    """Fetch URL and return plain text (HTML stripped).

    Blocks access to private/internal addresses (SSRF protection).
    """
    if _is_private_url(url):
        return f"Error fetching URL content: SSRF blocked for URL {url}"

    try:
        ctx = ssl.create_default_context()  # proper cert validation
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
        )
        opener = urllib.request.build_opener(
            SafeHTTPHandler(),
            SafeHTTPSHandler(context=ctx),
            SSRFHTTPRedirectHandler()
        )
        with opener.open(req, timeout=30) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                html = resp.read().decode('utf-8', errors='replace')

                class _Extractor(HTMLParser):
                    SKIP = {'script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'iframe'}

                    def __init__(self):
                        super().__init__()
                        self.parts: list[str] = []
                        self._depth = {t: 0 for t in self.SKIP}

                    def _skipping(self) -> bool:
                        return any(v > 0 for v in self._depth.values())

                    def handle_starttag(self, tag, attrs):
                        if tag.lower() in self.SKIP:
                            self._depth[tag.lower()] += 1

                    def handle_endtag(self, tag):
                        lower = tag.lower()
                        if lower in self.SKIP and self._depth[lower] > 0:
                            self._depth[lower] -= 1

                    def handle_data(self, data):
                        if not self._skipping():
                            cleaned = ' '.join(data.split())
                            if cleaned:
                                self.parts.append(cleaned)

                parser = _Extractor()
                parser.feed(html)
                return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()[:20000]
            else:
                return resp.read().decode('utf-8', errors='replace')[:5000]
    except Exception as e:
        return f"Error fetching URL content: {e}"
