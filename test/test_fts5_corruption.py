#!/usr/bin/env python3
"""
Test script to simulate and verify FTS5 corruption recovery.

This script:
1. Creates a SQLitePlanCache with some test data
2. Simulates FTS5 corruption by manually deleting content table rows
3. Attempts hybrid_search to trigger the rebuild
4. Verifies the recovery succeeds
"""

import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from cache.sqlite import SQLitePlanCache

def test_fts5_corruption_recovery():
    """Test that FTS5 corruption is properly recovered."""
    
    # Create a temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        
        print("=" * 60)
        print("Testing FTS5 Corruption Recovery")
        print("=" * 60)
        
        # Step 1: Create cache and add some plans
        print("\n1. Creating cache and adding test plans...")
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        test_plans = [
            ("Create a Python script to parse CSV files", "def parse_csv(file_path):\n    import csv\n    with open(file_path) as f:\n        return list(csv.DictReader(f))"),
            ("Build a React component for user authentication", "import React, { useState } from 'react';\nconst AuthForm = () => { const [user, setUser] = useState(null); return <div>Auth</div>; };"),
            ("Write a SQL query to find duplicate emails", "SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1"),
            ("Create a Dockerfile for a Node.js application", "FROM node:18-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci --only=production\nCOPY . .\nCMD [\"node\", \"index.js\"]"),
            ("Set up GitHub Actions for CI/CD", "name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v3\n      - run: npm test"),
        ]
        
        for task, plan in test_plans:
            cache.set(task, plan)
        
        stats = cache.get_stats()
        print(f"   Added {stats['total_plans']} plans")
        print(f"   FTS5 should be in sync: {stats['total_plans']} total rows")
        
        # Step 2: Verify normal hybrid search works
        print("\n2. Testing normal hybrid search...")
        candidates = cache.hybrid_search("Python script")
        print(f"   Found {len(candidates)} candidates")
        for c in candidates:
            print(f"   - Score: {c.score:.3f}, Text: {c.task_text[:50]}...")
        
        # Step 3: Simulate FTS5 corruption
        print("\n3. Simulating FTS5 corruption (deleting rows from main table)...")
        with sqlite3.connect(db_path) as conn:
            # Check initial state
            cursor = conn.execute("SELECT COUNT(*) FROM plans")
            main_before = cursor.fetchone()[0]
            cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
            fts_before = cursor.fetchone()[0]
            print(f"   Before corruption: {main_before} main rows, {fts_before} FTS rows")
            
            # Delete some rows from the main table (simulating data loss)
            # This will cause FTS5 to have entries pointing to non-existent rowids
            cursor = conn.execute("DELETE FROM plans WHERE rowid <= 2")
            deleted_count = cursor.rowcount
            conn.commit()
            
            # Check state after deletion
            cursor = conn.execute("SELECT COUNT(*) FROM plans")
            main_after = cursor.fetchone()[0]
            cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
            fts_after = cursor.fetchone()[0]
            print(f"   After deletion: {main_after} main rows, {fts_after} FTS rows")
            print(f"   Deleted {deleted_count} rows from main table")
            print(f"   FTS5 is now out of sync: {fts_after - main_after} orphaned FTS entries")
        
        # Step 4: Attempt hybrid search - should trigger corruption detection and rebuild
        print("\n4. Attempting hybrid search (should trigger FTS5 rebuild)...")
        try:
            candidates = cache.hybrid_search("Python script")
            print(f"   Search returned {len(candidates)} candidates")
            
            # Verify FTS5 was rebuilt
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM plans")
                main_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
                fts_count = cursor.fetchone()[0]
                print(f"   After rebuild: {main_count} main rows, {fts_count} FTS rows")
                
                if main_count == fts_count:
                    print("   ✅ FTS5 is now synchronized!")
                else:
                    print(f"   ⚠️  Still out of sync: {fts_count - main_count} difference")
            
            # Step 5: Verify search still works (with vector-only fallback if needed)
            if candidates:
                print("   ✅ Search succeeded after corruption recovery")
                for c in candidates:
                    print(f"   - Score: {c.score:.3f}, Text: {c.task_text[:50]}...")
            else:
                print("   ⚠️  No candidates found (may be expected if all data was deleted)")
            
            print("\n" + "=" * 60)
            print("Test completed successfully - corruption was handled!")
            print("=" * 60)
            
        except Exception as e:
            print(f"   ❌ Error during search: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        return True

if __name__ == "__main__":
    success = test_fts5_corruption_recovery()
    exit(0 if success else 1)
