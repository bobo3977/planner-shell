#!/usr/bin/env python3
"""Test Alpine Linux detection in PlannerAgent."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.planner import PlannerAgent
from cache.base import BasePlanCache

class DummyCache(BasePlanCache):
    def get(self, key):
        return None
    def get_meta(self, key):
        return None
    def add(self, task_text, plan, **kwargs):
        pass
    def hybrid_search(self, query):
        return []
    def get_stats(self):
        return "dummy"
    def clear(self, pattern=None):
        pass
    def list_plans(self):
        return []
    def cleanup_expired(self):
        pass
    def delete(self, key):
        pass
    def get_by_hash(self, hash_val):
        return None
    def set(self, key, value):
        pass

# Test different OS info strings
test_cases = [
    ("Linux alpine-container 6.6.87.2-microsoft", "Alpine"),
    ("Linux ubuntu-server 5.15.0", "Ubuntu"),
    ("Linux debian-box 5.10.0", "Debian"),
    ("Linux busybox-test 5.15.0", "BusyBox"),
    ("Alpine Linux v3.18.0", "Alpine"),
    ("Linux unknown-distro", "Ubuntu"),  # Default
]

print("🧪 Testing OS Distribution Detection\n")
print("=" * 70)

for os_info, expected in test_cases:
    agent = PlannerAgent(None, DummyCache(), os_info)
    detected = agent._detect_os_distribution()
    status = "✅" if detected == expected else "❌"
    print(f"{status} Input: {os_info:<45} → {detected} (expected: {expected})")

print("=" * 70)
print("\n🧪 Testing Task with OS Generation\n")
print("=" * 70)

# Test that task gets OS appended correctly
for os_info, distro_name in [("Alpine Linux v3.18", "Alpine"), ("Ubuntu 22.04", "Ubuntu")]:
    agent = PlannerAgent(None, DummyCache(), os_info)
    task = "install mysql"
    result = agent._get_task_with_os(task)
    expected_result = f"{task} {distro_name}"
    status = "✅" if result == expected_result else "❌"
    print(f"{status} Task: '{task}' + {distro_name}")
    print(f"   → '{result}' (expected: '{expected_result}')")

print("=" * 70)
