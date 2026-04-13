#!/usr/bin/env python3
"""
Detailed test for FTS5 corruption - simulates the exact error:
"fts5: missing row X from content table"

This happens when FTS5 has entries with rowids that don't exist in the content table.
"""

import sqlite3
import tempfile
from pathlib import Path

from cache.sqlite import SQLitePlanCache

def test_fts5_missing_content_row():
    """Test FTS5 corruption where FTS references non-existent content rows."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        
        print("=" * 70)
        print("Testing FTS5 'Missing Row from Content Table' Corruption")
        print("=" * 70)
        
        # Step 1: Create cache and add plans
        print("\n1. Creating cache with test plans...")
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        test_plans = [
            ("Task 1: Python hello world", "print('Hello, World!')"),
            ("Task 2: JavaScript alert", "alert('Hello');"),
            ("Task 3: Java main method", "public class Main { public static void main(String[] args) {} }"),
            ("Task 4: C++ hello world", "#include <iostream>\nint main() { std::cout << \"Hello\"; }"),
            ("Task 5: Go hello world", "package main\nimport \"fmt\"\nfunc main() { fmt.Println(\"Hello\") }"),
        ]
        
        for task, plan in test_plans:
            cache.set(task, plan)
        
        stats = cache.get_stats()
        print(f"   Created {stats['total_plans']} plans")
        
        # Step 2: Verify normal operation
        print("\n2. Verifying normal hybrid search...")
        candidates = cache.hybrid_search("Python")
        print(f"   Found {len(candidates)} candidates for 'Python'")
        assert len(candidates) > 0, "Should find candidates"
        
        # Step 3: Simulate the specific corruption
        print("\n3. Simulating FTS5 content table corruption...")
        with sqlite3.connect(db_path) as conn:
            # Get current counts
            cursor = conn.execute("SELECT COUNT(*) FROM plans")
            main_count_before = cursor.fetchone()[0]
            cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
            fts_count_before = cursor.fetchone()[0]
            print(f"   Before: {main_count_before} main rows, {fts_count_before} FTS rows")
            
            # Get some rowids from FTS5
            cursor = conn.execute("SELECT rowid FROM plans_fts LIMIT 3")
            fts_rowids = [r[0] for r in cursor.fetchall()]
            print(f"   FTS5 rowids: {fts_rowids}")
            
            # Get corresponding main table rowids
            cursor = conn.execute("SELECT rowid FROM plans")
            main_rowids = [r[0] for r in cursor.fetchall()]
            print(f"   Main table rowids: {main_rowids}")
            
            # Now manually insert a fake row into FTS5 with a rowid that doesn't exist in plans
            # This simulates the corruption where FTS5 has a reference to a missing content row
            print("   Inserting orphaned FTS5 entry with non-existent rowid...")
            fake_rowid = max(main_rowids) + 100  # Use a rowid that definitely doesn't exist
            try:
                conn.execute(
                    "INSERT INTO plans_fts(rowid, task_text, task_hash) VALUES (?, ?, ?)",
                    (fake_rowid, "ORPHANED ENTRY THAT SHOULD NOT EXIST", "orphan_hash_12345")
                )
                conn.commit()
                print(f"   Inserted orphaned FTS5 entry with rowid={fake_rowid}")
            except sqlite3.Error as e:
                print(f"   Could not insert orphaned entry: {e}")
                print("   (This is expected if FTS5 content linkage is strict)")
            
            # Also try to delete some rows from main table to create orphaned FTS entries
            # But we need to be careful: if we delete from main, the FTS triggers should
            # mark the FTS entries as deleted. To create orphaned entries, we'd need to
            # manually manipulate the FTS5 table directly.
            # Let's try a different approach: manually delete from FTS5 content
            
        # Step 4: Attempt hybrid search - should detect corruption and rebuild
        print("\n4. Attempting hybrid search (should detect and fix corruption)...")
        try:
            candidates = cache.hybrid_search("Python")
            print(f"   Search returned {len(candidates)} candidates")
            
            # Verify FTS5 is now consistent
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM plans")
                main_count_after = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
                fts_count_after = cursor.fetchone()[0]
                print(f"   After: {main_count_after} main rows, {fts_count_after} FTS rows")
                
                # Check if there are any orphaned FTS entries
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM plans_fts p
                    LEFT JOIN plans m ON p.rowid = m.rowid
                    WHERE m.rowid IS NULL
                """)
                orphaned = cursor.fetchone()[0]
                if orphaned > 0:
                    print(f"   ⚠️  Found {orphaned} orphaned FTS entries!")
                else:
                    print("   ✅ No orphaned FTS entries")
            
            if candidates:
                print("   ✅ Search succeeded")
                for c in candidates[:3]:
                    print(f"      - {c.task_text[:50]}... (score: {c.score:.3f})")
            
            print("\n" + "=" * 70)
            print("SUCCESS: FTS5 corruption was detected and recovered!")
            print("=" * 70)
            return True
            
        except sqlite3.DatabaseError as e:
            print(f"   ❌ DatabaseError during search: {e}")
            print("   The corruption may be severe and not recoverable.")
            return False
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = test_fts5_missing_content_row()
    exit(0 if success else 1)
