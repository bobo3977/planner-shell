#!/usr/bin/env python3
"""Debug list_plans output to check for duplicate hashes."""

import sqlite3
from pathlib import Path
from datetime import datetime

db_path = Path(".plan_cache.db")

if not db_path.exists():
    print("Database not found")
    exit(1)

from cache.sqlite import SQLitePlanCache
cache = SQLitePlanCache(str(db_path), ttl_days=30)

# Get the list
plans_list = cache.list_plans(limit=50)

print("list_plans() output:\n")
print(f"{'Index':<6} {'Hash':<32} {'Task Text':<40} {'Timestamp'}")
print("-" * 100)

for p in plans_list:
    print(f"{p['index']:<6} {p['task_hash']:<32} {p['task_text'][:40]:<40} {p['timestamp']}")

# Check for duplicate hashes
print("\n\nChecking for duplicate hashes in list output:")
hash_counts = {}
for p in plans_list:
    h = p['task_hash']
    hash_counts[h] = hash_counts.get(h, 0) + 1

duplicates = {h: c for h, c in hash_counts.items() if c > 1}
if duplicates:
    print(f"Found duplicate hashes: {duplicates}")
else:
    print("No duplicate hashes in list output.")
