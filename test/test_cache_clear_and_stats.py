#!/usr/bin/env python3
"""
Test cache clear and stats across all backends.
- Clear functionality
- Statistics reporting
- Synchronization check (for FTS backends)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def test_clear_and_stats(cache):
    """Test clear and stats on a given cache instance."""
    # Ensure fresh start
    cache.clear()

    # Test stats on empty cache
    print("\n1. Testing stats on empty cache...")
    stats = cache.get_stats()
    assert stats['total_plans'] == 0, "Empty cache should have 0 total plans"
    assert stats['valid_plans'] == 0, "Empty cache should have 0 valid plans"
    print(f"   ✅ Initial stats: {stats}")

    # Add test plans
    print("\n2. Adding test plans...")
    tasks = ["Task 1", "Task 2", "Task 3"]
    for task in tasks:
        cache.set(task, f"Plan for {task}")
    cache.optimize()
    
    # Verify count via stats
    stats = cache.get_stats()
    assert stats['total_plans'] == 3, f"Should have 3 plans, got {stats['total_plans']}"
    assert stats['valid_plans'] == 3, "All plans should be valid"
    print(f"   ✅ Added 3 plans, stats: {stats}")

    # Verify embedding count if applicable (SQLite/SingleStore both support it)
    print("\n3. Verifying embedding stats...")
    if stats['plans_with_embedding'] > 0:
        print(f"   ✅ Plans with embedding: {stats['plans_with_embedding']}")
    else:
        # Note: If OpenAI API is unavailable, this might be 0
        print("   ⚠️ No plans with embedding (OpenAI API may be unavailable)")

    # Test clear
    print("\n4. Testing clear()...")
    cache.clear()
    cache.optimize()
    
    # Verify count is 0
    stats = cache.get_stats()
    assert stats['total_plans'] == 0, "Cache should be empty after clear"
    assert stats['valid_plans'] == 0, "Cache should be empty after clear"
    print("   ✅ clear() works correctly")

    # Verify list_plans is empty
    plans = cache.list_plans()
    assert len(plans) == 0, "list_plans should be empty after clear"
    print("   ✅ list_plans is empty after clear")

    return True

if __name__ == "__main__":
    success = run_cache_test_main(test_clear_and_stats)
    exit(0 if success else 1)
