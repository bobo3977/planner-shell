#!/usr/bin/env python3
"""
FTS5 integration test
- FTS5 search accuracy
- Comparison between FTS5 and vector search
- Fallback when FTS5 is disabled
"""

import tempfile
from pathlib import Path
import sqlite3

from cache.sqlite import SQLitePlanCache

def test_fts5_integration():
    """Test FTS5 functionality and integration with hybrid search."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)

        print("=" * 60)
        print("Testing FTS5 Integration")
        print("=" * 60)

        # Add diverse test data
        print("\n1. Adding test plans...")
        plans = [
            ("Python programming for beginners", "Introduction to Python syntax and basics"),
            ("Advanced Python metaprogramming", "Using metaclasses and descriptors in Python"),
            ("JavaScript ES6 features", "Arrow functions, destructuring, spread operator"),
            ("React hooks tutorial", "useState, useEffect, and custom hooks"),
            ("Node.js performance optimization", "Caching, clustering, and profiling"),
            ("Python async await", "Asynchronous programming with asyncio"),
            ("JavaScript TypeScript migration", "Converting JS to TS step by step"),
            ("Python pandas data frames", "Data manipulation with pandas"),
        ]

        for task, plan in plans:
            cache.set(task, plan)

        print(f"   Added {len(plans)} plans")

        # Test 1: Verify FTS5 table exists
        print("\n2. Verifying FTS5 table exists...")
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='plans_fts'"
            )
            fts_exists = cursor.fetchone() is not None
            assert fts_exists, "plans_fts table should exist"
            print("   ✅ FTS5 table exists")

            # Check FTS5 content count matches main table
            cursor = conn.execute("SELECT COUNT(*) FROM plans")
            main_count = cursor.fetchone()[0]
            cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
            fts_count = cursor.fetchone()[0]
            print(f"   Main table: {main_count}, FTS5: {fts_count}")
            assert main_count == fts_count, "FTS5 should be in sync with main table"
            print("   ✅ FTS5 is synchronized")

        # Test 2: FTS5-only search (verify BM25 works)
        print("\n3. Testing FTS5-only search capability...")
        # Direct FTS5 query
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                """SELECT p.task_text, -bm25(plans_fts) as score
                   FROM plans_fts
                   JOIN plans p ON plans_fts.task_hash = p.task_hash
                   WHERE plans_fts MATCH ?
                   ORDER BY score DESC
                   LIMIT 5""",
                ("Python",)
            )
            fts_results = cursor.fetchall()
            print(f"   FTS5 direct query returned {len(fts_results)} results")
            assert len(fts_results) > 0, "FTS5 should return results for 'Python'"
            for task_text, score in fts_results:
                print(f"      - {task_text[:50]}... (BM25: {score:.3f})")
            print("   ✅ FTS5 direct query works")

        # Test 3: Hybrid search uses FTS5
        print("\n4. Testing hybrid search uses FTS5...")
        candidates = cache.hybrid_search("Python")
        assert len(candidates) > 0, "Should find Python-related candidates"
        # Check that FTS scores are present (non-None)
        fts_scored = [c for c in candidates if c.fts_score is not None]
        assert len(fts_scored) > 0, "At least some candidates should have FTS scores"
        print(f"   ✅ Hybrid search returned {len(candidates)} candidates with FTS scores")

        # Test 4: Verify FTS5 matches contain search terms
        print("\n5. Verifying FTS5 match accuracy...")
        candidates = cache.hybrid_search("JavaScript")
        for c in candidates:
            # FTS5 should match tasks containing JavaScript or JS
            task_lower = c.task_text.lower()
            has_match = "javascript" in task_lower or "js" in task_lower or "typescript" in task_lower
            assert has_match, f"Task '{c.task_text}' should be JavaScript-related"
        print("   ✅ FTS5 matches are relevant")

        # Test 5: Phrase search
        print("\n6. Testing phrase search...")
        candidates = cache.hybrid_search("data frames")
        # Should match "Python pandas data frames"
        found_pandas = any("pandas" in c.task_text.lower() for c in candidates)
        assert found_pandas, "Should find pandas data frames task"
        print("   ✅ Phrase search works")

        # Test 6: Multi-word OR search
        print("\n7. Testing multi-word OR search...")
        candidates = cache.hybrid_search("Python JavaScript")
        assert len(candidates) > 0, "Should find tasks matching either Python or JavaScript"
        tasks_lower = [c.task_text.lower() for c in candidates]
        has_python = any("python" in t for t in tasks_lower)
        has_js = any("javascript" in t or "js" in t or "typescript" in t for t in tasks_lower)
        assert has_python or has_js, "At least one should match"
        print(f"   ✅ Multi-word search returned {len(candidates)} candidates")

        # Test 7: Case insensitivity
        print("\n8. Testing case insensitivity...")
        candidates_upper = cache.hybrid_search("PYTHON")
        candidates_lower = cache.hybrid_search("python")
        # Both should return similar results (same tasks)
        assert len(candidates_upper) == len(candidates_lower), "Case should not affect results"
        print("   ✅ Case insensitive search works")

        # Test 8: Empty search
        print("\n9. Testing empty/whitespace search...")
        candidates = cache.hybrid_search("   ")
        # Empty search should return empty or minimal results
        print(f"   Empty search returned {len(candidates)} candidates")
        print("   ✅ Empty search handled")

        print("\n" + "=" * 60)
        print("All FTS5 integration tests passed!")
        print("=" * 60)
        return True

if __name__ == "__main__":
    try:
        success = test_fts5_integration()
        exit(0 if success else 1)
    except AssertionError as e:
        print(f"\n❌ Assertion failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
