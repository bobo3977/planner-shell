#!/usr/bin/env python3
"""Show all entries in the plans table."""

import sqlite3
from pathlib import Path

db_path = Path(".plan_cache.db")

if not db_path.exists():
    print("Database not found")
    exit(1)

conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
conn.row_factory = sqlite3.Row

# Get all entries
print("All entries in plans table:\n")
rows = conn.execute("""
    SELECT rowid, task_hash, task_text, timestamp, url, markdown_file
    FROM plans
    ORDER BY timestamp DESC
""").fetchall()

print(f"Total entries: {len(rows)}\n")

for row in rows:
    print(f"RowID {row['rowid']}:")
    print(f"  Hash: {row['task_hash']}")
    print(f"  Task: {row['task_text']}")
    print(f"  Timestamp: {row['timestamp']}")
    print(f"  URL: {row['url']}")
    print(f"  Markdown: {row['markdown_file']}")
    print()

conn.close()
