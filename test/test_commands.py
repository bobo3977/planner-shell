#!/usr/bin/env python3
"""
Test suite for command interface functionality across all backends.
Tests cache management commands: clear, cleanup, list, delete, edit.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def create_test_plan_in_cache(plan_cache, task_text: str = "Test task for command testing", plan_content: str = None) -> dict:
    """Helper to create a test plan in cache and return its metadata."""
    if plan_content is None:
        plan_content = """# Test Plan
## 1. First step
echo "Hello World"
## 2. Second step
ls -la
"""
    
    task_for_cache = f"{task_text} test"
    plan_cache.set(
        task_for_cache,
        plan_content,
        skip_embedding=False,
        embedding_text=task_text,
        url=None,
        markdown_file=None,
        task_text=task_text[:200],
    )
    
    # Get the metadata
    plans = plan_cache.list_plans(limit=100)
    matching = [p for p in plans if task_text.lower() in p["task_text"].lower()]
    return matching[0] if matching else None

def test_cache_clear(cache):
    print("\n=== Testing cache clear ===")
    # Add some plans
    for i in range(3):
        create_test_plan_in_cache(
            cache,
            task_text=f"Clear test {i}",
            plan_content=f"# Plan {i}\necho 'test'"
        )
    
    stats_before = cache.get_stats()
    assert stats_before['total_plans'] > 0, "Should have plans before clear"
    
    # Clear the cache
    cache.clear()
    
    stats_after = cache.get_stats()
    assert stats_after['total_plans'] == 0, "Cache should be empty after clear"
    print("✅ Cache clear: PASSED")
    return True

def test_cache_cleanup(cache):
    print("\n=== Testing cache cleanup ===")
    # Add plans
    for i in range(3):
        create_test_plan_in_cache(
            cache,
            task_text=f"Cleanup test {i}",
            plan_content=f"# Plan\necho 'test'"
        )
    
    stats_before = cache.get_stats()
    assert stats_before['total_plans'] > 0, "Should have plans before cleanup"
    
    # Run cleanup (should not delete anything since plans are fresh)
    deleted = cache.cleanup_expired()
    
    stats_after = cache.get_stats()
    assert stats_after['total_plans'] == stats_before['total_plans'], "No plans should be deleted yet"
    print(f"✅ Cache cleanup: PASSED (deleted {deleted} expired entries)")
    return True

def test_cache_list(cache):
    print("\n=== Testing cache list ===")
    # Add plans
    for i in range(5):
        create_test_plan_in_cache(
            cache,
            task_text=f"List test task {i}",
            plan_content=f"# Plan {i}\necho 'List test {i}'"
        )
    
    # List all plans
    plans = cache.list_plans(limit=100)
    assert len(plans) >= 5, f"Should list at least 5 plans, got {len(plans)}"
    
    # Check plan structure
    for plan in plans:
        assert 'index' in plan, "Plan should have index"
        assert 'task_text' in plan, "Plan should have task_text"
        assert 'task_hash' in plan, "Plan should have task_hash"
    
    print(f"✅ Cache list: PASSED (listed {len(plans)} plans)")
    return True

def test_cache_delete_by_index(cache):
    print("\n=== Testing cache delete by index ===")
    meta = create_test_plan_in_cache(
        cache,
        task_text="Delete test task",
        plan_content="# Delete test\necho 'delete me'"
    )
    assert meta is not None, "Should create test plan"
    index = meta['index']
    
    stats_before = cache.get_stats()
    deleted = cache.delete("", index=index)
    assert deleted, "Delete should return True on success"
    
    stats_after = cache.get_stats()
    assert stats_after['total_plans'] < stats_before['total_plans'], "Should have fewer plans"
    assert cache.get_by_hash(meta['task_hash']) is None, "Deleted plan should not be retrievable"
    print("✅ Cache delete by index: PASSED")
    return True

def test_cache_delete_by_text(cache):
    print("\n=== Testing cache delete by text ===")
    for i in range(3):
        create_test_plan_in_cache(
            cache,
            task_text=f"Unique delete test {i}",
            plan_content=f"# Plan\necho 'test {i}'"
        )
    
    stats_before = cache.get_stats()
    deleted_count = cache.delete("Unique delete test")
    assert deleted_count > 0, "Should delete at least one plan"
    stats_after = cache.get_stats()
    assert stats_after['total_plans'] < stats_before['total_plans'], "Should have fewer plans"
    print(f"✅ Cache delete by text: PASSED (deleted {deleted_count} plans)")
    return True

def test_cache_edit(cache):
    print("\n=== Testing cache edit ===")
    original_plan = "# Original Plan\necho 'original'"
    meta = create_test_plan_in_cache(
        cache,
        task_text="Edit test task",
        plan_content=original_plan
    )
    
    retrieved_plan = cache.get_by_hash(meta['task_hash'])
    assert retrieved_plan == original_plan, "Retrieved plan should match original"
    
    edited_plan = "# Edited Plan\necho 'edited'"
    task_for_cache = f"{meta['task_text']} test"
    cache.set(
        task_for_cache,
        edited_plan,
        skip_embedding=False,
        embedding_text=meta['task_text'],
        url=None,
        markdown_file=None,
        task_text=meta['task_text'][:200],
        task_hash=meta['task_hash']
    )
    
    new_retrieved = cache.get_by_hash(meta['task_hash'])
    assert new_retrieved == edited_plan, "Edited plan should be saved"
    print("✅ Cache edit: PASSED")
    return True

def run_all_command_tests(cache):
    """Run all command interface tests on the given cache."""
    cache.clear()
    success = True
    test_functions = [
        test_cache_clear,
        test_cache_cleanup,
        test_cache_list,
        test_cache_delete_by_index,
        test_cache_delete_by_text,
        test_cache_edit,
    ]
    
    for test_func in test_functions:
        try:
            if not test_func(cache):
                success = False
        except Exception as e:
            print(f"❌ {test_func.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            success = False
            
    return success

if __name__ == "__main__":
    success = run_cache_test_main(run_all_command_tests)
    exit(0 if success else 1)
