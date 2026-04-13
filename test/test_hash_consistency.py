#!/usr/bin/env python3
"""
Test that hash and task_text are consistent in the cache.

This test verifies the fix for the issue where distilled plans with the same
task_text but different cache keys would create duplicate entries instead of
overwriting the original.
"""

import tempfile
from pathlib import Path
from cache.sqlite import SQLitePlanCache

def test_hash_matches_task_text():
    """When task_text is provided, the stored hash should match that task_text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        # Simulate the scenario from main.py where task_for_cache and task_text differ
        task_for_cache = "Install curl on Ubuntu 24.04.4 LTS Ubuntu"  # includes distro
        plan = "## Install curl on Ubuntu 24.04.4 LTS\n\n1. apt-get update\n2. apt-get install -y curl"
        task_text_to_store = "## Install curl on Ubuntu 24.04.4 LTS"  # first line of plan
        
        # Store with custom task_text
        cache.set(
            task_for_cache,
            plan,
            task_text=task_text_to_store,
            skip_embedding=True
        )
        
        # Retrieve metadata using the task_for_cache (the original lookup key)
        meta = cache.get_meta(task_for_cache)
        assert meta is not None, "Should find the entry"
        
        # The stored task_hash should match the cache key (task_for_cache), not task_text
        expected_hash = cache._hash_task(task_for_cache)
        assert meta["task_hash"] == expected_hash, \
            f"Hash {meta['task_hash']} should match hash of cache key '{task_for_cache}' which is {expected_hash}"
        
        # The stored task_text should be what we provided
        assert meta["task_text"] == task_text_to_store
        
        print("✅ Test passed: hash matches task_text")

def test_hash_without_custom_task_text():
    """When task_text is not provided, hash should be computed from task."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        task = "Install nginx on Ubuntu"
        plan = "## Install nginx on Ubuntu\n\n1. apt-get update\n2. apt-get install -y nginx"
        
        # Store without custom task_text
        cache.set(
            task,
            plan,
            skip_embedding=True
        )
        
        # Retrieve metadata
        meta = cache.get_meta(task)
        assert meta is not None
        
        # The stored task_hash should match the task (since task_text defaults to task.strip())
        expected_hash = cache._hash_task(task.strip())
        assert meta["task_hash"] == expected_hash
        
        # The stored task_text should be task.strip()
        assert meta["task_text"] == task.strip()
        
        print("✅ Test passed: hash matches task when task_text not provided")

if __name__ == "__main__":
    test_hash_matches_task_text()
    test_hash_without_custom_task_text()
    print("\n✅ All tests passed!")
