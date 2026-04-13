#!/usr/bin/env python3
"""
Utility functions for cache testing across multiple backends.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.base import BasePlanCache

class ResilientCacheWrapper:
    """Wrapper that adds small delays for eventual consistency backends during tests."""
    def __init__(self, cache: BasePlanCache, name: str):
        self._cache = cache
        self._name = name

    def __getattr__(self, name):
        attr = getattr(self._cache, name)
        # Add delay after set() specifically for SingleStore to ensure visibility in tests
        if name == 'set' and self._name == 'SingleStore' and callable(attr):
            def wrapped_set(*args, **kwargs):
                import time
                res = attr(*args, **kwargs)
                time.sleep(0.5)  # 500ms for distributed consistency
                return res
            return wrapped_set
        return attr

def get_test_backends() -> Generator[Tuple[BasePlanCache, str], None, None]:
    """Yields (cache_instance, name) for each configured backend."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        from cache.sqlite import SQLitePlanCache
        db_path = Path(tmpdir) / "test_cache.db"
        # Most tests use standard 30 days TTL
        cache_sqlite = SQLitePlanCache(str(db_path), ttl_days=30)
        yield cache_sqlite, "SQLite"

    # 2. SingleStore (if configured)
    host = os.getenv("SINGLESTORE_HOST", "localhost")
    password = os.getenv("SINGLESTORE_PASSWORD", "")
    
    # Check if SingleStore is configured
    if password or host == "localhost":
        try:
            from cache.singlestore import SingleStorePlanCache
            cache_s2 = SingleStorePlanCache(
                host=host,
                port=int(os.getenv("SINGLESTORE_PORT", "3306")),
                user=os.getenv("SINGLESTORE_USER", "root"),
                password=password,
                database=os.getenv("SINGLESTORE_DATABASE", "inst_agent_test"),
                table="test_cache_table",
                ttl_days=30
            )
            # Ensure fresh start for the test
            try:
                import time
                # Ensure fresh start for the test
                cache_s2.clear()
                cache_s2.optimize()
                # Give SingleStore a moment to reflect the cleared state across its distributed nodes
                time.sleep(2)
                
                # Wrap for resilience
                wrapped_s2 = ResilientCacheWrapper(cache_s2, "SingleStore")
                yield wrapped_s2, "SingleStore"
            finally:
                # Cleanup after test
                try:
                    cache_s2.clear()
                    cache_s2.optimize()
                except:
                    pass
        except (ImportError, Exception):
            # Skip if not available/working
            pass

def run_cache_test_main(test_func):
    """Common main entry point for cache tests that runs against all backends."""
    all_success = True
    for cache, name in get_test_backends():
        print("\n" + "=" * 60)
        print(f"RUNNING TEST ON BACKEND: {name}")
        print("=" * 60)
        try:
            success = test_func(cache)
            if not success:
                all_success = False
                print(f"❌ Test FAILED on {name}")
            else:
                print(f"✅ Test PASSED on {name}")
        except AssertionError as e:
            all_success = False
            print(f"❌ Assertion failed on {name}: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            all_success = False
            print(f"❌ Unexpected error on {name}: {e}")
            import traceback
            traceback.print_exc()
            
    return all_success
