#!/usr/bin/env python3
"""Debug duplicate plans with same hash."""

import sqlite3
from pathlib import Path

db_path = Path(".plan_cache.db")

if not db_path.exists():
    print("Database not found")
    exit(1)

conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
conn.row_factory = sqlite3.Row

# Check for duplicates by task_hash
print("Checking for duplicate task_hash entries...")
rows = conn.execute("""
    SELECT task_hash, task_text, COUNT(*) as count
    FROM plans
    GROUP BY task_hash
    HAVING count > 1
    ORDER BY count DESC
""").fetchall()

if rows:
    print(f"\nFound {len(rows)} task_hash values with duplicates:\n")
    for row in rows:
        print(f"Hash: {row['task_hash']}")
        print(f"  Count: {row['count']}")
        # Show all entries with this hash
        entries = conn.execute("""
            SELECT rowid, task_text, timestamp, url, markdown_file
            FROM plans WHERE task_hash = ?
            ORDER BY timestamp
        """, (row['task_hash'],)).fetchall()
        for entry in entries:
            print(f"    RowID {entry['rowid']}: {entry['task_text'][:50]}")
            print(f"      Timestamp: {entry['timestamp']}")
            print(f"      URL: {entry['url']}")
            print(f"      Markdown: {entry['markdown_file']}")
        print()
else:
    print("No duplicate task_hash entries found.")

# Check table schema
print("\nTable schema:")
schema = conn.execute("PRAGMA table_info(plans)").fetchall()
for col in schema:
    print(f"  {col['name']}: {col['type']} (pk={col['pk']})")

# Check if there's a unique constraint on task_hash
print("\nIndexes:")
indexes = conn.execute("PRAGMA index_list(plans)").fetchall()
for idx in indexes:
    print(f"  {idx['name']}: unique={idx['unique']}")

conn.close()
