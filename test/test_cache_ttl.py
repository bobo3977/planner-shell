#!/usr/bin/env python3
"""
Test TTL (time to live) and cleanup functionality for all backends.
- Automatic exclusion of expired entries
- Operation verification of cleanup_expired()
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.base import BasePlanCache
from cache.sqlite import SQLitePlanCache

def run_ttl_test(cache: BasePlanCache, name: str):
    """Run TTL expiration and cleanup tests on a given cache instance."""
    print("\n" + "=" * 60)
    print(f"Testing TTL and Cleanup: {name}")
    print("=" * 60)

    # Add some plans
    print("\n1. Adding test plans...")
    task1 = f"[{name}] Task A: Python script"
    plan1 = "print('A')"
    task2 = f"[{name}] Task B: JavaScript code"
    plan2 = "console.log('B');"
    task3 = f"[{name}] Task C: Java code"
    plan3 = "class C {}"

    cache.set(task1, plan1)
    cache.set(task2, plan2)
    cache.set(task3, plan3)

    stats_initial = cache.get_stats()
    print(f"   Added {stats_initial['total_plans']} plans")
    assert stats_initial['total_plans'] >= 3, f"Should have at least 3 plans, got {stats_initial['total_plans']}"

    # Verify all are retrievable immediately
    print("\n2. Verifying plans are retrievable...")
    assert cache.get(task1) == plan1, f"Task1 should be retrievable for {name}"
    assert cache.get(task2) == plan2, f"Task2 should be retrievable for {name}"
    assert cache.get(task3) == plan3, f"Task3 should be retrievable for {name}"
    print(f"   ✅ All plans retrievable for {name}")

    # Wait for TTL to expire (TTL in these tests is set to be very short)
    wait_time = 20
    print(f"\n3. Waiting for TTL to expire ({wait_time} seconds)...")
    time.sleep(wait_time)

    # Check that plans are now expired
    print(f"\n4. Checking that plans are expired for {name}...")
    stats_after_wait = cache.get_stats()
    print(f"   Total: {stats_after_wait['total_plans']}, Valid: {stats_after_wait['valid_plans']}, Expired: {stats_after_wait['expired_plans']}")

    # After TTL, get() should return None for expired entries
    assert cache.get(task1) is None, f"Expired task1 should not be retrievable for {name}"
    assert cache.get(task2) is None, f"Expired task2 should not be retrievable for {name}"
    assert cache.get(task3) is None, f"Expired task3 should not be retrievable for {name}"
    print(f"   ✅ Expired plans correctly not retrievable via get() for {name}")

    # get_meta should also return None for expired
    assert cache.get_meta(task1) is None, f"Expired meta should be None for {name}"
    print(f"   ✅ Expired plans correctly not retrievable via get_meta() for {name}")

    # hybrid_search should not return expired entries
    print(f"\n5. Testing hybrid_search with expired entries for {name}...")
    candidates = cache.hybrid_search(f"[{name}] Python")
    assert len(candidates) == 0, f"Should not return expired candidates for {name}"
    print(f"   ✅ hybrid_search correctly excludes expired entries for {name}")

    # Test cleanup_expired
    print(f"\n6. Testing cleanup_expired() for {name}...")
    deleted = cache.cleanup_expired()
    print(f"   Deleted {deleted} expired entries")
    assert deleted >= 3, f"Should delete at least 3 expired entries for {name}, got {deleted}"

    stats_after_cleanup = cache.get_stats()
    print(f"   After cleanup - Total: {stats_after_cleanup['total_plans']}, Valid: {stats_after_cleanup['valid_plans']}")
    # For SQLite we expect 0 if it was fresh, but for shared SingleStore table it might be different
    # However, if it's a test-specific table, it should be 0 or small.
    print(f"   ✅ cleanup_expired completed for {name}")

    # Add new plans and verify they work normally
    print(f"\n7. Adding fresh plans after cleanup for {name}...")
    task4 = f"[{name}] Fresh task: Go programming"
    plan4 = "package main\nfunc main() {}"
    cache.set(task4, plan4)

    assert cache.get(task4) == plan4, f"Fresh plan should be retrievable for {name}"
    print(f"   ✅ Fresh plans work correctly after cleanup for {name}")

    print(f"\n✅ All TTL tests passed for {name}!")
    return True

def main():
    """Run TTL tests for all configured backends."""
    # 1. Test SQLite
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache_ttl.db"
        # Short TTL (~17.3s)
        cache_sqlite = SQLitePlanCache(str(db_path), ttl_days=0.0002)
        try:
            run_ttl_test(cache_sqlite, "SQLite")
        except Exception as e:
            print(f"❌ SQLite TTL test failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    # 2. Test SingleStore if configured
    host = os.getenv("SINGLESTORE_HOST", "localhost")
    password = os.getenv("SINGLESTORE_PASSWORD", "")
    
    # Check if SingleStore is configured
    if password or host == "localhost":
        try:
            from cache.singlestore import SingleStorePlanCache
            # Short TTL (~17.3s)
            cache_s2 = SingleStorePlanCache(
                host=host,
                port=int(os.getenv("SINGLESTORE_PORT", "3306")),
                user=os.getenv("SINGLESTORE_USER", "root"),
                password=password,
                database=os.getenv("SINGLESTORE_DATABASE", "inst_agent_test"),
                table="test_ttl_cache",
                ttl_days=0.0002
            )
            cache_s2.clear()  # Ensure fresh start
            run_ttl_test(cache_s2, "SingleStore")
        except (ImportError, Exception) as e:
            if isinstance(e, ImportError):
                print("\n⚠️  SingleStore package not available - skipping TTL test")
            else:
                print(f"\n❌ SingleStore TTL test failed: {e}")
                import traceback
                traceback.print_exc()
                return False
    else:
        print("\n⚠️  SingleStore not configured - skipping TTL test")

    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
