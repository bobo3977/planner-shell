#!/usr/bin/env python3
"""
Test list, edit, and delete shortcuts across all backends.
- list_plans index assignment
- delete by index
- edit by index (Note: edit functionality may depend on agents/planner.py)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def test_shortcuts(cache):
    """Test shortcuts on a given cache instance."""
    # Ensure fresh start
    cache.clear()

    # Add test plans
    print("\n1. Adding test plans...")
    tasks = ["Task 1: Install curl", "Task 2: Install nginx", "Task 3: Install python"]
    # Add with slight delay to ensure distinct timestamps for reliable indexing
    import time
    for task in tasks:
        cache.set(task, f"Plan for {task}")
        time.sleep(0.1) # Ensure ordering
    cache.optimize()
    
    # Test 1: List and verify indices
    print("\n2. Listing plans and verifying indices...")
    # Default is newest first (reversed order of addition)
    plans = cache.list_plans(limit=10)
    assert len(plans) == 3, f"Should have 3 plans, got {len(plans)}"
    
    # Verify 1-based indexing in list_plans output
    for i, p in enumerate(plans, 1):
        assert p['index'] == i, f"Index mismatch: expected {i}, got {p['index']}"
    
    assert plans[0]['task_text'] == "Task 3: Install python", "Index 1 should be the newest task"
    assert plans[1]['task_text'] == "Task 2: Install nginx", "Index 2 should be the second newest task"
    assert plans[2]['task_text'] == "Task 1: Install curl", "Index 3 should be the oldest task"
    print("   ✅ Indices correctly assigned (newest first)")

    # Test 2: Delete by index
    print("\n3. Testing delete by index...")
    # Delete the oldest task (Task 1, index 3)
    success = cache.delete("", index=3)
    cache.optimize()
    assert success, "Delete by index 3 should succeed"
    
    # Verify Task 1 is gone
    assert cache.get("Task 1: Install curl") is None, "Oldest task should be deleted"
    stats = cache.get_stats()
    assert stats['total_plans'] == 2, f"Should have 2 plans remaining, got {stats['total_plans']}"
    print("   ✅ Delete by index 3 (oldest) works")

    # Delete index 1 (Task 3)
    success = cache.delete("", index=1)
    cache.optimize()
    assert success, "Delete by index 1 should succeed"
    assert cache.get("Task 3: Install python") is None, "Newest task should be deleted"
    
    # Remaining should be Task 2
    stats = cache.get_stats()
    assert stats['total_plans'] == 1, "Should have 1 plan remaining"
    remaining = cache.list_plans()
    assert remaining[0]['task_text'] == "Task 2: Install nginx", "Remaining task should be Task 2"
    print("   ✅ Delete by index 1 (newest) works")

    return True

if __name__ == "__main__":
    success = run_cache_test_main(test_shortcuts)
    exit(0 if success else 1)
