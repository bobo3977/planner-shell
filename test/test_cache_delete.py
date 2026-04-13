#!/usr/bin/env python3
"""
Test cache delete operations across all backends.
- Delete by index (newest first)
- Delete by partial task text match
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def test_delete_operations(cache):
    """Test delete operations on a given cache instance."""
    # Ensure fresh start
    cache.clear()

    # Add test plans
    print("\n1. Adding test plans...")
    tasks = ["Task Alpha: Python script", "Task Beta: JavaScript code", 
             "Task Gamma: Java class", "Task Delta: C++ program", 
             "Task Epsilon: Go function"]
    for task in tasks:
        cache.set(task, f"Plan for {task}")
    cache.optimize()
    
    # Verify count
    stats = cache.get_stats()
    assert stats['total_plans'] == 5, f"Should have 5 plans, got {stats['total_plans']}"
    print(f"   Added {len(tasks)} plans")
    
    # Test 2: Delete by index (newest first, 1-based)
    print("\n2. Testing delete by index...")
    # Get current list to identify what's at index 1
    plans = cache.list_plans(limit=10)
    newest_task = plans[0]['task_text']
    
    success = cache.delete("", index=1)
    cache.optimize()
    assert success, "Delete by index should succeed"
    
    # Verify it's gone
    assert cache.get(newest_task) is None, f"Plan '{newest_task}' should be deleted"
    stats = cache.get_stats()
    assert stats['total_plans'] == 4, f"Should have 4 plans remaining, got {stats['total_plans']}"
    print("   ✅ Delete by index works")

    # Test 3: Delete by partial task text
    print("\n3. Testing delete by partial task text...")
    success = cache.delete("JavaScript")
    cache.optimize()
    assert success, "Delete by partial text should succeed"
    
    # Verify Task Beta is gone
    assert cache.get("Task Beta: JavaScript code") is None, "JavaScript task should be deleted"
    stats = cache.get_stats()
    assert stats['total_plans'] == 3, f"Should have 3 plans remaining, got {stats['total_plans']}"
    print("   ✅ Delete by partial task text works")

    # Test 4: Delete with multiple matches (if applicable)
    # Adding another Python task
    cache.set("Another Python task", "More Python") 
    cache.optimize()
    print("\n4. Testing delete with multiple matches...")
    success = cache.delete("Python")
    cache.optimize()
    assert success, "Delete with multiple matches should succeed"
    
    # Verify both Python tasks are gone
    assert cache.get("Task Alpha: Python script") is None, "Alpha Python task should be deleted"
    assert cache.get("Another Python task") is None, "Another Python task should be deleted"
    stats = cache.get_stats()
    assert stats['total_plans'] == 2, f"Should have 2 plans remaining, got {stats['total_plans']}"
    print("   ✅ Delete with multiple matches works")

    # Test 5: Delete non-existent
    print("\n5. Testing delete non-existent...")
    success = cache.delete("Non-existent task text")
    assert not success, "Delete should return False for no matches"
    print("   ✅ Non-existent delete returns False")

    # Test 6: Delete with invalid index
    print("\n6. Testing delete with invalid index...")
    success = cache.delete("", index=999)
    assert not success, "Delete should return False for invalid index"
    print("   ✅ Invalid index returns False")

    return True

if __name__ == "__main__":
    success = run_cache_test_main(test_delete_operations)
    exit(0 if success else 1)
