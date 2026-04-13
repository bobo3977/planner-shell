#!/usr/bin/env python3
"""
Test basic cache operations across all backends.
- Basic functionality: set, get, get_by_hash, get_meta
- Basic hybrid search behavior
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test.cache_test_utils import run_cache_test_main

def test_basic_cache_operations(cache):
    """Test basic cache operations on a given cache instance."""
    print("\n1. Testing set() and get()...")
    task = "Create a Python function to calculate factorial"
    plan = "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)"

    cache.set(task, plan)

    retrieved = cache.get(task)
    assert retrieved == plan, "Retrieved plan should match the original"
    print("   ✅ set/get works correctly")

    # Test 2: get_by_hash
    print("\n2. Testing get_by_hash()...")
    task_hash = cache._hash_task(task)
    retrieved_by_hash = cache.get_by_hash(task_hash)
    assert retrieved_by_hash == plan, "get_by_hash should return the same plan"
    print("   ✅ get_by_hash works correctly")

    # Test 3: get_meta
    print("\n3. Testing get_meta()...")
    meta = cache.get_meta(task)
    assert meta is not None, "get_meta should return metadata"
    assert meta["task_hash"] == task_hash, "task_hash should match"
    assert meta["task_text"] == task.strip(), "task_text should match"
    print(f"   ✅ get_meta works: {meta}")

    # Test 4: Set with additional metadata
    print("\n4. Testing set with url and markdown_file...")
    task2 = "Build a React component"
    plan2 = "import React from 'react';\nexport default function Component() { return <div>Hello</div>; }"
    url = "https://example.com/react-component"
    md_file = "/path/to/component.md"

    cache.set(task2, plan2, url=url, markdown_file=md_file)
    meta2 = cache.get_meta(task2)
    assert meta2["url"] == url, "url should be stored"
    assert meta2["markdown_file"] == md_file, "markdown_file should be stored"
    print("   ✅ Metadata storage works correctly")

    # Test 5: Hybrid search
    print("\n5. Testing hybrid_search()...")
    candidates = cache.hybrid_search("Python function")
    assert len(candidates) > 0, "Should find candidates"
    # Note: search rankings might differ between backends, but it should be high score
    print(f"   ✅ hybrid_search works: found {len(candidates)} candidates")
    print(f"      Top candidate score: {candidates[0].score:.3f}")

    # Test 6: Non-existent task
    print("\n6. Testing non-existent task...")
    assert cache.get("Non-existent task") is None, "Should return None for missing task"
    assert cache.get_by_hash("invalid_hash") is None, "Should return None for invalid hash"
    assert cache.get_meta("Non-existent task") is None, "Should return None for missing meta"
    # Note: hybrid_search may return results if FTS5 partial matches or vector similarity > 0
    # So we just check that it doesn't raise an error
    empty_candidates = cache.hybrid_search("xyz123nonexistent")
    print(f"   Non-existent search returned {len(empty_candidates)} candidates (may be 0 or >0)")
    print("   ✅ Non-existent task handling works correctly")

    return True

if __name__ == "__main__":
    success = run_cache_test_main(test_basic_cache_operations)
    exit(0 if success else 1)
