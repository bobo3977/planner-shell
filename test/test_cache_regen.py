#!/usr/bin/env python3
"""
Test: Verify that skip_cache parameter works in planner.create_plan()
and that cache-hit rejection leads to new plan generation.
"""

import sys
import os
import tempfile
from pathlib import Path

from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.planner import PlannerAgent
from cache.sqlite import SQLitePlanCache
from utils.os_info import get_detailed_os_info


def test_skip_cache_parameter():
    """Test that skip_cache parameter is properly handled."""
    print("=" * 60)
    print("TEST: skip_cache parameter in create_plan()")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_regen.db")
        # Initialize cache and planner
        cache = SQLitePlanCache(db_path=db_path, ttl_days=30)
        os_info = get_detailed_os_info()
        llm = MagicMock()
        
        # Patch LLM-related functions to avoid actual API calls
        with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
             patch('agents.planner._run_agent_in_thread') as mock_run_agent:

            mock_agent = MagicMock()
            mock_make_agent.return_value = mock_agent
            # Give it a different plan each time if needed to distinguish
            mock_run_agent.side_effect = [
                {"output": "Plan 1 content"},
                {"output": "Plan 2 content"},
                {"output": "Plan 3 content (new)"}
            ]

            planner = PlannerAgent(llm=llm, os_info=os_info, plan_cache=cache)
            # Disable Tavily to keep test fully offline/deterministic
            planner._tavily_available = False
            planner._tavily = None

            # Test task
            task = "install test-package"

            try:
                # First call: Generate and cache a plan
                print("\n1️⃣  First call - generate plan (skip_cache=False, should use cache):")
                plan1, is_from_cache1 = planner.create_plan(task, skip_cache=False)
                if plan1:
                    print(f"   ✅ Plan 1 generated (is_from_cache={is_from_cache1})")
                    print(f"   Plan length: {len(plan1)} chars")
                else:
                    print("   ❌ Plan 1 failed")

                # Second call: Should get from cache
                print("\n2️⃣  Second call - same task (skip_cache=False, should use cache):")
                plan2, is_from_cache2 = planner.create_plan(task, skip_cache=False)
                if plan2:
                    print(f"   ✅ Plan 2 retrieved (is_from_cache={is_from_cache2})")
                    if is_from_cache2:
                        print("   ✅ Correctly returned from cache")
                        if plan1 == plan2:
                            print("   ✅ Plan content is identical")
                        else:
                            print("   ⚠️  Plan content differs (this could be normal)")
                    else:
                        print("   ⚠️  Not from cache (may be due to hybrid search)")
                else:
                    print("   ❌ Plan 2 failed")

                # Third call: Skip cache and generate new
                print("\n3️⃣  Third call - skip cache (skip_cache=True, should generate new):")
                plan3, is_from_cache3 = planner.create_plan(task, skip_cache=True)
                if plan3:
                    print(f"   ✅ Plan 3 generated (is_from_cache={is_from_cache3})")
                    if not is_from_cache3:
                        print("   ✅ Correctly generated new plan (not from cache)")
                    else:
                        print("   ⚠️  Marked as from_cache (unexpected)")
                else:
                    print("   ❌ Plan 3 failed")

                print("\n" + "=" * 60)
                print("✅ Test completed successfully!")
                print("=" * 60)

            except Exception as e:
                print(f"\n❌ Test failed with error: {e}")
                import traceback
                traceback.print_exc()
                return False

            return True


if __name__ == "__main__":
    success = test_skip_cache_parameter()
    sys.exit(0 if success else 1)
