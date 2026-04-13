#!/usr/bin/env python3
"""
Test script for prompt loading functionality.
This script verifies that:
1. Prompts can be loaded from default location
2. Prompts can be loaded from external location (when PROMPT_DIR is set)
3. Required variable validation works correctly
4. Integration with PlannerAgent and ExecutorAgent works
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Set up test environment
def setup_test_env():
    """Set up test environment variables."""
    # Clear any existing PROMPT_DIR to start clean
    if 'PROMPT_DIR' in os.environ:
        del os.environ['PROMPT_DIR']

def test_default_prompt_loading():
    """Test loading prompts from default location."""
    print("Testing default prompt loading...")
    setup_test_env()
    
    from config import load_prompt
    
    # Test planner prompt
    planner_prompt = load_prompt('planner', required_vars=['{task}', '{os_info}', '{current_date}'])
    assert isinstance(planner_prompt, str)
    assert len(planner_prompt) > 1000  # Should be substantial
    assert '{task}' in planner_prompt
    assert '{os_info}' in planner_prompt
    assert '{current_date}' in planner_prompt
    print("  ✅ Planner prompt loaded successfully")
    
    # Test executor prompt
    executor_prompt = load_prompt('executor', required_vars=['{os_info}', '{user_task}', '{plan}'])
    assert isinstance(executor_prompt, str)
    assert len(executor_prompt) > 500
    assert '{os_info}' in executor_prompt
    assert '{user_task}' in executor_prompt
    assert '{plan}' in executor_prompt
    print("  ✅ Executor prompt loaded successfully")
    
    # Test distill prompt
    distill_prompt = load_prompt('distill', required_vars=['{current_date}', '{os_info}', '{user_task}', '{execution_history}'])
    assert isinstance(distill_prompt, str)
    assert len(distill_prompt) > 1000
    assert '{current_date}' in distill_prompt
    assert '{os_info}' in distill_prompt
    assert '{user_task}' in distill_prompt
    assert '{execution_history}' in distill_prompt
    print("  ✅ Distill prompt loaded successfully")

def test_external_prompt_loading():
    """Test loading prompts from external location."""
    print("Testing external prompt loading...")
    setup_test_env()
    
    # Create temporary directory for test prompts
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_dir = Path(tmpdir) / "test_prompts"
        prompt_dir.mkdir()
        
        # Create test prompt files
        (prompt_dir / "planner.md").write_text("""# Test Planner Prompt
Required variables:
  {task} - User's task
  {os_info} - Target system information

Test planner prompt for {task} on {os_info}.""")
        
        (prompt_dir / "executor.md").write_text("""# Test Executor Prompt
Required variables:
  {os_info} - Target system information
  {user_task} - User's task
  {plan} - Plan to execute

Test executor prompt for {user_task} on {os_info} with plan: {plan}.""")
        
        (prompt_dir / "distill.md").write_text("""# Test Distill Prompt
Required variables:
  {current_date} - Current date
  {os_info} - Target system information
  {user_task} - User's original task
  {execution_history} - Execution history

Test distill prompt for {user_task} on {os_info} dated {current_date}.
Execution history: {execution_history}""")
        
        # Set PROMPT_DIR to our test directory
        os.environ['PROMPT_DIR'] = str(prompt_dir)
        
        from config import load_prompt
        
        # Test loading from external location
        planner_prompt = load_prompt('planner', required_vars=['{task}', '{os_info}'])
        assert "Test planner prompt" in planner_prompt
        assert "{task}" in planner_prompt
        assert "{os_info}" in planner_prompt
        print("  ✅ External planner prompt loaded successfully")
        
        executor_prompt = load_prompt('executor', required_vars=['{os_info}', '{user_task}', '{plan}'])
        assert "Test executor prompt" in executor_prompt
        assert "{os_info}" in executor_prompt
        assert "{user_task}" in executor_prompt
        assert "{plan}" in executor_prompt
        print("  ✅ External executor prompt loaded successfully")
        
        distill_prompt = load_prompt('distill', required_vars=['{current_date}', '{os_info}', '{user_task}', '{execution_history}'])
        assert "Test distill prompt" in distill_prompt
        assert "{current_date}" in distill_prompt
        assert "{os_info}" in distill_prompt
        assert "{user_task}" in distill_prompt
        assert "{execution_history}" in distill_prompt
        print("  ✅ External distill prompt loaded successfully")

def test_variable_validation():
    """Test that required variable validation works."""
    print("Testing variable validation...")
    setup_test_env()
    
    from config import load_prompt
    
    # Test missing variable detection
    try:
        load_prompt('planner', required_vars=['{task}', '{missing_var}'])
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "missing_var" in str(e)
        assert "planner" in str(e)
        print("  ✅ Missing variable detection works correctly")
    
    # Test that valid variables don't raise error
    try:
        prompt = load_prompt('planner', required_vars=['{task}', '{os_info}'])
        assert isinstance(prompt, str)
        print("  ✅ Valid variables pass validation")
    except ValueError:
        assert False, "Should not have raised ValueError for valid variables"

def test_agent_integration():
    """Test that agents work with the prompt loading system."""
    print("Testing agent integration...")
    setup_test_env()
    
    from agents.planner import PlannerAgent
    from agents.executor import ExecutorAgent
    
    # Test PlannerAgent
    mock_llm = MagicMock()
    planner_agent = PlannerAgent(
        llm=mock_llm,
        plan_cache=None,
        os_info='Ubuntu 22.04 (test)',
        allow_llm_query_generation=False
    )
    
    # This should work without errors
    prompt = planner_agent._build_system_prompt(
        task='test task',
        search_query='test search',
        search_results='test results',
        execution_log=None
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert 'test task' in prompt
    assert 'Ubuntu 22.04 (test)' in prompt
    print("  ✅ PlannerAgent integration works")
    
    # Test ExecutorAgent creation
    mock_shell = MagicMock()
    executor_agent = ExecutorAgent(
        llm=mock_llm,
        shell=mock_shell,
        os_info='Ubuntu 22.04 (test)'
    )
    assert executor_agent is not None
    print("  ✅ ExecutorAgent creation works")

def test_fallback_behavior():
    """Test that fallback to default prompts works when external files missing."""
    print("Testing fallback behavior...")
    setup_test_env()
    
    # Point to empty directory (no prompt files)
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['PROMPT_DIR'] = tmpdir
        
        from config import load_prompt
        
        # Should fall back to default prompts
        planner_prompt = load_prompt('planner', required_vars=['{task}', '{os_info}', '{current_date}'])
        assert isinstance(planner_prompt, str)
        assert len(planner_prompt) > 1000  # Default prompt is substantial
        assert 'Elite Senior Linux System Administrator' in planner_prompt  # From default
        print("  ✅ Fallback to default prompts works")

def main():
    """Run all tests."""
    print("=" * 60)
    print("PROMPT LOADING FUNCTIONALITY TEST")
    print("=" * 60)
    
    try:
        test_default_prompt_loading()
        test_external_prompt_loading()
        test_variable_validation()
        test_agent_integration()
        test_fallback_behavior()
        
        print("=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)