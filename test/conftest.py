#!/usr/bin/env python3
"""
Pytest fixtures for cache tests.
Provides a cache fixture that overrides pytest's built-in cache fixture.
"""

import pytest
import tempfile
from pathlib import Path
from cache.sqlite import SQLitePlanCache


@pytest.fixture
def cache():
    """Provide a SQLitePlanCache instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        yield cache
