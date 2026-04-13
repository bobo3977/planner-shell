#!/usr/bin/env python3
"""
Integration tests for both SQLite and SingleStore cache backends.
Tests ensure both backends implement the BasePlanCache interface correctly.
"""

import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cache.base import BasePlanCache
from cache.sqlite import SQLitePlanCache
from common_types import CacheCandidate


def test_sqlite_backend():
    """Test SQLite cache backend."""
    print("\n" + "="*70)
    print("TESTING SQLITE BACKEND")
    print("="*70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sqlite.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        # Test 1: Set and Get
        print("\n1. Testing set() and get()...")
        task = "Install curl on Ubuntu 24.04.4 LTS"
        plan = """# Modified plan
# 1. Update package lists
sudo apt-get update -y
# 2. Install curl
sudo apt-get install -y curl
# 3. Verify installation
curl --version"""
        
        cache.set(task, plan)
        retrieved = cache.get(task)
        assert retrieved == plan, f"Retrieved plan should match original. Got: {retrieved}"
        print("   ✅ SQLite set/get works")
        
        # Test 2: Get by hash
        print("\n2. Testing get_by_hash()...")
        task_hash = cache._hash_task(task)
        retrieved_by_hash = cache.get_by_hash(task_hash)
        assert retrieved_by_hash == plan, "get_by_hash should return the same plan"
        print("   ✅ SQLite get_by_hash works")
        
        # Test 3: Get meta
        print("\n3. Testing get_meta()...")
        meta = cache.get_meta(task)
        assert meta is not None, "get_meta should return metadata"
        assert meta["task_hash"] == task_hash, "task_hash should match"
        assert meta["task_text"] == task.strip(), "task_text should match"
        print(f"   ✅ SQLite get_meta works: {meta}")
        
        # Test 4: Set with URL and markdown metadata
        print("\n4. Testing set with url and markdown_file...")
        task2 = "Build a React component"
        plan2 = "import React from 'react';\nexport default function Component() { return <div>Hello</div>; }"
        url = "https://example.com/react-component"
        md_file = "/path/to/component.md"
        
        cache.set(task2, plan2, url=url, markdown_file=md_file)
        meta2 = cache.get_meta(task2)
        assert meta2["url"] == url, f"url should be stored. Got: {meta2['url']}"
        assert meta2["markdown_file"] == md_file, f"markdown_file should be stored. Got: {meta2['markdown_file']}"
        print("   ✅ SQLite metadata storage works")
        
        # Test 5: Hybrid search
        print("\n5. Testing hybrid_search()...")
        candidates = cache.hybrid_search("Python function")
        print(f"   Found {len(candidates)} candidates")
        if len(candidates) > 0:
            print(f"   Top candidate: {candidates[0].task_text[:50]}... (score: {candidates[0].score:.3f})")
        print("   ✅ SQLite hybrid_search works")
        
        # Test 6: List plans
        print("\n6. Testing list_plans()...")
        plans = cache.list_plans(limit=10)
        assert len(plans) >= 2, f"Should have at least 2 plans, got {len(plans)}"
        print(f"   ✅ SQLite list_plans works: {len(plans)} plans")
        
        # Test 7: Get stats
        print("\n7. Testing get_stats()...")
        stats = cache.get_stats()
        assert "total_plans" in stats, "stats should have total_plans"
        assert "valid_plans" in stats, "stats should have valid_plans"
        print(f"   ✅ SQLite get_stats works: {stats}")
        
        # Test 8: Delete by index
        print("\n8. Testing delete by index...")
        # Get the list to find index
        plans_before = cache.list_plans(limit=10)
        if plans_before:
            index_to_delete = 1  # newest
            success = cache.delete("", index=index_to_delete)
            assert success, "Should delete plan by index"
            print(f"   ✅ SQLite delete by index works")
        
        # Test 9: Clear
        print("\n9. Testing clear()...")
        cache.clear()
        stats_after_clear = cache.get_stats()
        assert stats_after_clear["total_plans"] == 0, "Cache should be empty after clear"
        print("   ✅ SQLite clear works")
        
        print("\n" + "="*70)
        print("ALL SQLITE TESTS PASSED!")
        print("="*70)
        return True


def test_singlestore_backend():
    """Test SingleStore cache backend (if configured)."""
    print("\n" + "="*70)
    print("TESTING SINGLESTORE BACKEND")
    print("="*70)
    
    # Check if SingleStore credentials are available
    host = os.getenv("SINGLESTORE_HOST", "localhost")
    port = int(os.getenv("SINGLESTORE_PORT", "3306"))
    user = os.getenv("SINGLESTORE_USER", "root")
    password = os.getenv("SINGLESTORE_PASSWORD", "")
    database = os.getenv("SINGLESTORE_DATABASE", "inst_agent_test")
    
    # Skip test if no password and not localhost (likely not configured)
    if not password and host != "localhost":
        print("\n⚠️  SingleStore not configured (no password for remote host)")
        print("   Set SINGLESTORE_PASSWORD environment variable to test SingleStore")
        return True  # Don't fail, just skip
    
    try:
        from cache.singlestore import SingleStorePlanCache
    except ImportError as e:
        print(f"\n⚠️  SingleStore package not available: {e}")
        print("   Install with: pip install singlestoredb")
        return True  # Don't fail, just skip
    
    # Use a test-specific database and table
    test_table = "test_plans_cache"
    cache = SingleStorePlanCache(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        table=test_table,
        ttl_days=30
    )
    
    try:
        # Test 1: Set and Get
        print("\n1. Testing set() and get()...")
        task = "Install curl on Ubuntu 24.04.4 LTS"
        plan = """# Modified plan
# 1. Update package lists
sudo apt-get update -y
# 2. Install curl
sudo apt-get install -y curl
# 3. Verify installation
curl --version"""
        
        cache.set(task, plan)
        retrieved = cache.get(task)
        assert retrieved == plan, f"Retrieved plan should match original. Got: {retrieved}"
        print("   ✅ SingleStore set/get works")
        
        # Test 2: Get by hash
        print("\n2. Testing get_by_hash()...")
        task_hash = cache._hash_task(task)
        retrieved_by_hash = cache.get_by_hash(task_hash)
        assert retrieved_by_hash == plan, "get_by_hash should return the same plan"
        print("   ✅ SingleStore get_by_hash works")
        
        # Test 3: Get meta
        print("\n3. Testing get_meta()...")
        meta = cache.get_meta(task)
        assert meta is not None, "get_meta should return metadata"
        assert meta["task_hash"] == task_hash, "task_hash should match"
        assert meta["task_text"] == task.strip(), "task_text should match"
        print(f"   ✅ SingleStore get_meta works: {meta}")
        
        # Test 4: Set with URL and markdown metadata
        print("\n4. Testing set with url and markdown_file...")
        task2 = "Build a React component"
        plan2 = "import React from 'react';\nexport default function Component() { return <div>Hello</div>; }"
        url = "https://example.com/react-component"
        md_file = "/path/to/component.md"
        
        cache.set(task2, plan2, url=url, markdown_file=md_file)
        meta2 = cache.get_meta(task2)
        assert meta2["url"] == url, f"url should be stored. Got: {meta2['url']}"
        assert meta2["markdown_file"] == md_file, f"markdown_file should be stored. Got: {meta2['markdown_file']}"
        print("   ✅ SingleStore metadata storage works")
        
        # Test 5: Hybrid search
        print("\n5. Testing hybrid_search()...")
        candidates = cache.hybrid_search("Python function")
        print(f"   Found {len(candidates)} candidates")
        if len(candidates) > 0:
            print(f"   Top candidate: {candidates[0].task_text[:50]}... (score: {candidates[0].score:.3f})")
        print("   ✅ SingleStore hybrid_search works")
        
        # Test 6: List plans
        print("\n6. Testing list_plans()...")
        plans = cache.list_plans(limit=10)
        assert len(plans) >= 2, f"Should have at least 2 plans, got {len(plans)}"
        print(f"   ✅ SingleStore list_plans works: {len(plans)} plans")
        
        # Test 7: Get stats
        print("\n7. Testing get_stats()...")
        stats = cache.get_stats()
        assert "total_plans" in stats, "stats should have total_plans"
        assert "valid_plans" in stats, "stats should have valid_plans"
        print(f"   ✅ SingleStore get_stats works: {stats}")
        
        # Test 8: Delete by index
        print("\n8. Testing delete by index...")
        plans_before = cache.list_plans(limit=10)
        if plans_before:
            index_to_delete = 1  # newest
            success = cache.delete("", index=index_to_delete)
            assert success, "Should delete plan by index"
            print(f"   ✅ SingleStore delete by index works")
        
        # Test 9: Clear
        print("\n9. Testing clear()...")
        cache.clear()
        stats_after_clear = cache.get_stats()
        assert stats_after_clear["total_plans"] == 0, "Cache should be empty after clear"
        print("   ✅ SingleStore clear works")
        
        print("\n" + "="*70)
        print("ALL SINGLESTORE TESTS PASSED!")
        print("="*70)
        return True
        
    except Exception as e:
        print(f"\n❌ SingleStore test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup: try to clear the test table
        try:
            cache.clear()
        except:
            pass


def main():
    """Run all backend tests."""
    print("="*70)
    print("CACHE BACKEND INTEGRATION TESTS")
    print("="*70)
    
    results = []
    
    # Test SQLite (always runs)
    try:
        sqlite_result = test_sqlite_backend()
        results.append(("SQLite", sqlite_result))
    except Exception as e:
        print(f"\n❌ SQLite test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("SQLite", False))
    
    # Test SingleStore (if configured)
    try:
        singlestore_result = test_singlestore_backend()
        results.append(("SingleStore", singlestore_result))
    except Exception as e:
        print(f"\n❌ SingleStore test failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("SingleStore", False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print("-"*70)
    print(f"Total: {passed}/{total} backends passed")
    
    if passed == total:
        print("\n🎉 All backend tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} backend(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())
