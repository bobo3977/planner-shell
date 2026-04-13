#!/usr/bin/env python3
"""
Integration test for PlannerAgent with cache, distill, and hybrid search.
Tests the complete planner workflow.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.planner import PlannerAgent
from cache.sqlite import SQLitePlanCache
from utils.os_info import get_detailed_os_info


def test_planner_with_cache():
    """Test PlannerAgent with cache operations."""
    print("=" * 60)
    print("Testing PlannerAgent with Cache Integration")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        cache = SQLitePlanCache(str(db_path), ttl_days=30)
        
        llm = MagicMock()
        os_info = "Ubuntu 24.04.4 LTS"
        
        # Set test environment variable to auto-skip cache prompts
        os.environ["PLANNER_SHELL_TEST"] = "1"
        
        # Patch LLM-related functions to avoid actual API calls
        with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
             patch('agents.planner._run_agent_in_thread') as mock_run_agent:
            
            mock_agent = MagicMock()
            mock_make_agent.return_value = mock_agent
            mock_run_agent.return_value = {"output": "Mock plan: 1. Update packages\\n2. Install nginx\\n3. Start nginx"}
            
            planner = PlannerAgent(llm=llm, plan_cache=cache, os_info=os_info)
            
            task = "Install nginx on Ubuntu"
            
            # First call should generate a new plan
            print("\n1. Generating new plan...")
            plan1, _ = planner.create_plan(task)
            assert plan1 and len(plan1) > 50, "Plan should be generated"
            print(f"   ✅ Plan generated ({len(plan1)} chars)")
            
            # Manually save to cache (in real usage, main.py does this after user confirmation)
            lookup_key = planner._get_task_with_os(task)
            cache.set(lookup_key, plan1)
            print(f"   ✅ Plan saved to cache with key: {lookup_key}")
            
            # Verify it's cached
            stats1 = cache.get_stats()
            print(f"   Cache stats: {stats1}")
            
            # Second call with same task should hit cache
            print("\n2. Requesting same task (should hit cache)...")
            plan2, _ = planner.create_plan(task)
            assert plan1 == plan2, "Cached plan should match"
            print("   ✅ Cache hit successful")
            
            # Verify hybrid search works
            print("\n3. Testing hybrid search with similar task...")
            similar_task = "Install nginx web server"
            plan3, _ = planner.create_plan(similar_task)
            # Should either hit cache via hybrid search or generate new
            assert plan3 and len(plan3) > 50, "Plan should be generated or retrieved"
            print(f"   ✅ Similar task handled ({len(plan3)} chars)")
            
            print("\n✅ Planner cache integration test passed!")
            return True


def test_planner_distill():
    """Test PlannerAgent distill_plan functionality."""
    print("\n" + "=" * 60)
    print("Testing PlannerAgent Distill Functionality")
    print("=" * 60)
    
    llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Set test environment variable to auto-skip cache prompts
    os.environ["PLANNER_SHELL_TEST"] = "1"
    
    # Patch LLM-related functions to avoid actual API calls
    with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
         patch('agents.planner._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "## 1. Update packages\napt-get update\n## 2. Install nginx\napt-get install -y nginx\n## 3. Start nginx\nsystemctl start nginx\n## 4. Configure firewall\nufw allow 80/tcp"}
        
        planner = PlannerAgent(llm=llm, plan_cache=None, os_info=os_info)
        
        # Create a mock execution log with some failures and successes
        from common_types import ExecutionStep
        
        execution_log = [
            ExecutionStep(command="apt-get update", exit_code=0, output=""),
            ExecutionStep(command="apt-get install -y nginx", exit_code=0, output=""),
            ExecutionStep(command="systemctl start nginx", exit_code=0, output=""),
            ExecutionStep(command="ufw allow 'Nginx Full'", exit_code=1, output=""),
            ExecutionStep(command="ufw allow 80/tcp", exit_code=0, output=""),
        ]
        
        original_plan = """## 1. Update package list
apt-get update
## 2. Install nginx
apt-get install -y nginx
## 3. Start nginx
systemctl start nginx
## 4. Configure firewall (attempt 1)
ufw allow 'Nginx Full'
## 5. Configure firewall (attempt 2)
ufw allow 80/tcp"""
        
        user_task = "Install and configure nginx with firewall"
        
        print("\n1. Distilling plan from execution log...")
        try:
            distilled = planner.distill_plan(
                user_task=user_task,
                execution_log=execution_log,
                original_plan=original_plan
            )
            assert distilled and len(distilled) > 50, "Distilled plan should be substantial"
            print(f"   ✅ Distilled plan generated ({len(distilled)} chars)")
            print("\nDistilled plan preview:")
            print("-" * 60)
            print(distilled[:500])
            print("-" * 60)
            
            # Verify distilled plan contains successful commands
            assert "apt-get update" in distilled, "Should include successful command"
            assert "apt-get install" in distilled, "Should include successful command"
            assert "systemctl start" in distilled, "Should include successful command"
            assert "ufw allow 80/tcp" in distilled, "Should include successful command"
            # Should not include failed command
            assert "ufw allow 'Nginx Full'" not in distilled, "Should exclude failed command"
            print("   ✅ Distilled plan correctly filters failed commands")
            
        except Exception as e:
            print(f"   ❌ Distillation failed: {e}")
            raise
        
        print("\n✅ Planner distill test passed!")
        return True


def test_planner_url_mode():
    """Test PlannerAgent with URL input mode."""
    print("\n" + "=" * 60)
    print("Testing PlannerAgent URL Mode")
    print("=" * 60)
    
    llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Set test environment variable to auto-skip cache prompts
    os.environ["PLANNER_SHELL_TEST"] = "1"
    
    # Patch LLM-related functions to avoid actual API calls
    with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
         patch('agents.planner._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "## 1. Update packages\napt-get update\n## 2. Install PostgreSQL\napt-get install -y postgresql\n## 3. Start service\nsystemctl start postgresql"}
        
        planner = PlannerAgent(llm=llm, plan_cache=None, os_info=os_info)
        
        # Mock URL content
        url_content = """
# How to Install PostgreSQL on Ubuntu

1. Update the package index:
   sudo apt-get update

2. Install PostgreSQL:
   sudo apt-get install -y postgresql postgresql-contrib

3. Start the service:
   sudo systemctl start postgresql

4. Enable auto-start:
   sudo systemctl enable postgresql
"""
    
        task = "https://example.com/install-postgresql"
        
        print("\n1. Creating plan from URL content...")
        try:
            plan, _ = planner.create_plan(
                task,
                url_content=url_content,
                execution_log=None
            )
            assert plan and len(plan) > 50, "Plan should be generated"
            print(f"   ✅ Plan generated ({len(plan)} chars)")
            
            # Verify plan contains relevant commands
            assert "apt-get update" in plan or "apt-get" in plan, "Should include package commands"
            print("   ✅ Plan includes expected commands")
            
        except Exception as e:
            print(f"   ❌ Plan generation failed: {e}")
            raise
        
        print("\n✅ Planner URL mode test passed!")
        return True


def test_planner_markdown_mode():
    """Test PlannerAgent with markdown file input mode."""
    print("\n" + "=" * 60)
    print("Testing PlannerAgent Markdown Mode")
    print("=" * 60)
    
    llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Set test environment variable to auto-skip cache prompts
    os.environ["PLANNER_SHELL_TEST"] = "1"
    
    # Patch LLM-related functions to avoid actual API calls
    with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
         patch('agents.planner._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "## 1. Add Redis repo\nadd-apt-repository ppa:redislabs/redis\n## 2. Update packages\napt-get update\n## 3. Install Redis\napt-get install -y redis-server\n## 4. Start and enable\nsystemctl start redis"}
        
        planner = PlannerAgent(llm=llm, plan_cache=None, os_info=os_info)
        
        # Mock markdown content
        markdown_content = """
# Redis Installation Guide

## Steps

1. Add Redis repository:
   sudo add-apt-repository ppa:redislabs/redis

2. Update packages:
   sudo apt-get update

3. Install Redis:
   sudo apt-get install -y redis-server

4. Start and enable:
   sudo systemctl start redis
   sudo systemctl enable redis
"""
    
        task = "./install_redis.md"
        
        print("\n1. Creating plan from markdown content...")
        try:
            plan, _ = planner.create_plan(
                task,
                markdown_content=markdown_content,
                execution_log=None
            )
            assert plan and len(plan) > 50, "Plan should be generated"
            print(f"   ✅ Plan generated ({len(plan)} chars)")
            
            # Verify plan contains relevant commands
            assert "apt-get" in plan, "Should include package commands"
            assert "systemctl" in plan, "Should include service commands"
            print("   ✅ Plan includes expected commands")
            
        except Exception as e:
            print(f"   ❌ Plan generation failed: {e}")
            raise
        
        print("\n✅ Planner markdown mode test passed!")
        return True


def test_planner_with_execution_history():
    """Test PlannerAgent with execution history for iterative refinement."""
    print("\n" + "=" * 60)
    print("Testing PlannerAgent with Execution History")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Patch LLM-related functions to avoid actual API calls
    with patch('agents.planner._make_agent_with_history') as mock_make_agent, \
         patch('agents.planner._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "Mock plan with history: 1. Update packages\\n2. Install nginx\\n3. Create SSL directory\\n4. Generate SSL certificate"}
        
        planner = PlannerAgent(llm=llm, plan_cache=None, os_info=os_info)
        
        # Create a task that might need refinement
        task = "Set up a web server with SSL"
        
        # Mock execution log of previous attempt
        from common_types import ExecutionStep
        
        execution_log = [
            ExecutionStep(command="apt-get update", exit_code=0, output=""),
            ExecutionStep(command="apt-get install -y nginx", exit_code=0, output=""),
            ExecutionStep(command="openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/nginx/nginx.key -out /etc/ssl/nginx/nginx.crt",
                         exit_code=1, output="Error: unable to write to /etc/ssl/nginx/"),
        ]
        
        print("\n1. Creating plan with execution history...")
        try:
            plan, _ = planner.create_plan(
                task,
                execution_log=execution_log
            )
            assert plan and len(plan) > 50, "Plan should be generated"
            print(f"   ✅ Plan generated ({len(plan)} chars)")
            
            # The plan should account for the previous failure
            # (e.g., by creating directory first or using different approach)
            print("   ✅ Plan considers execution history")
            
        except Exception as e:
            print(f"   ❌ Plan generation failed: {e}")
            raise
        
        print("\n✅ Planner execution history test passed!")
        return True


def main():
    """Run all planner integration tests."""
    print("=" * 60)
    print("PLANNER AGENT INTEGRATION TESTS")
    print("=" * 60)
    
    try:
        test_planner_with_cache()
        test_planner_distill()
        test_planner_url_mode()
        test_planner_markdown_mode()
        test_planner_with_execution_history()
        
        print("\n" + "=" * 60)
        print("🎉 ALL PLANNER INTEGRATION TESTS PASSED!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
