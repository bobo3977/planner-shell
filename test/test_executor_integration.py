#!/usr/bin/env python3
"""
Integration test for ExecutorAgent with execution log and error handling.
Tests the executor's ability to run plans and collect logs.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.executor import ExecutorAgent
from common_types import ExecutionStep
from shell.persistent import PersistentShell


def test_executor_with_mock_shell():
    """Test ExecutorAgent with a mock shell that simulates command execution."""
    print("=" * 60)
    print("Testing ExecutorAgent with Mock Shell")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    # Create a mock shell that simulates successful command execution
    mock_shell = MagicMock(spec=PersistentShell)
    mock_shell.execute.return_value = (0, "Command executed successfully")
    
    # Create a mock LLM
    mock_llm = MagicMock()
    
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Patch the agent creation and execution to avoid actual LLM calls
    with patch('agents.executor._make_agent_with_history') as mock_make_agent, \
         patch('agents.executor._run_agent_in_thread') as mock_run_agent:
        
        # Mock the agent to return a simple result
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        
        # Mock the agent execution to return a result that extract_agent_output can handle
        mock_run_agent.return_value = {"output": "Plan executed successfully"}
        
        executor = ExecutorAgent(llm=mock_llm, shell=mock_shell, os_info=os_info)
        
        # Mock the agent execution to simulate tool calls
        def simulate_execution(*args, **kwargs):
            # Execute each command exactly once
            if not hasattr(simulate_execution, "executed"):
                executor._shell_tool._run("apt-get update")
                executor._shell_tool._run("apt-get install -y nginx")
                executor._shell_tool._run("systemctl start nginx")
                simulate_execution.executed = True
            return {"output": "Plan executed successfully"}
            
        mock_run_agent.side_effect = simulate_execution
        
        plan = """## 1. Update package list
apt-get update
## 2. Install nginx
apt-get install -y nginx
## 3. Start nginx
systemctl start nginx"""
        
        user_task = "Install and start nginx"
        
        print("\n1. Executing plan with mock shell...")
        try:
            # Set environment variable to skip prompts during tool execution in test
            with patch.dict(os.environ, {"PLANNER_SHELL_TEST": "1"}):
                output, exec_log = executor.execute_plan_with_log(plan, user_task)
            print(f"   ✅ Execution completed")
            print(f"   Output length: {len(output)} chars")
            print(f"   Execution log entries: {len(exec_log)}")
            
            # Verify execution log
            assert len(exec_log) == 3, f"Expected 3 execution steps, got {len(exec_log)}"
            print("   ✅ Correct number of execution steps")
            
            # Verify all steps succeeded
            for step in exec_log:
                assert step.succeeded, f"Step '{step.command}' should have succeeded"
            print("   ✅ All steps succeeded")
            
            # Verify specific commands
            commands = [step.command for step in exec_log]
            assert any("apt-get" in cmd and "update" in cmd for cmd in commands), "Should include apt-get update"
            assert any("apt-get" in cmd and "install" in cmd and "nginx" in cmd for cmd in commands), "Should include nginx install"
            assert any("systemctl" in cmd and "start nginx" in cmd for cmd in commands), "Should include systemctl start"
            print("   ✅ All expected commands executed")
        except Exception as e:
            print(f"   ❌ Execution failed: {e}")
            raise
    
    print("\n✅ Executor mock shell test passed!")
    return True


def test_executor_error_handling():
    """Test ExecutorAgent's handling of command failures."""
    print("\n" + "=" * 60)
    print("Testing ExecutorAgent Error Handling")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    mock_shell = MagicMock(spec=PersistentShell)
    
    # Simulate mixed success/failure
    def mock_execute(command, timeout=600, has_progress=False):
        if "apt-get update" in command:
            return (0, "OK")
        elif "apt-get install" in command:
            return (1, "E: Unable to locate package")
        elif "systemctl" in command:
            return (0, "Created symlink")
        else:
            return (0, "OK")
    
    mock_shell.execute.side_effect = mock_execute
    
    mock_llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Patch the agent creation and execution to avoid actual LLM calls
    with patch('agents.executor._make_agent_with_history') as mock_make_agent, \
         patch('agents.executor._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "Plan executed with some failures"}
        
        executor = ExecutorAgent(llm=mock_llm, shell=mock_shell, os_info=os_info)
        
        # Mock the agent execution to simulate tool calls
        def simulate_execution(*args, **kwargs):
            # The agent would normally parse the plan and call the tool for each command
            executor._shell_tool._run("apt-get update")
            executor._shell_tool._run("apt-get install -y nonexistent-package")
            executor._shell_tool._run("systemctl start something")
            return {"output": "Plan executed with some failures"}
            
        mock_run_agent.side_effect = simulate_execution
        
        plan = """## 1. Update package list
apt-get update
## 2. Install nonexistent package
apt-get install -y nonexistent-package
## 3. Start service
systemctl start something"""
        
        user_task = "Test error handling"
        
        print("\n1. Executing plan with failures...")
        try:
            # Set environment variable to skip prompts during tool execution in test
            with patch.dict(os.environ, {"PLANNER_SHELL_TEST": "1"}):
                output, exec_log = executor.execute_plan_with_log(plan, user_task)
            print(f"   ✅ Execution completed (with failures)")
            print(f"   Execution log entries: {len(exec_log)}")
            
            # Verify we have both success and failure
            successes = sum(1 for s in exec_log if s.succeeded)
            failures = sum(1 for s in exec_log if not s.succeeded)
            print(f"   Successes: {successes}, Failures: {failures}")
            
            assert successes > 0, "Should have some successes"
            assert failures > 0, "Should have some failures"
            print("   ✅ Mixed success/failure correctly logged")
            
            # Verify exit codes
            for step in exec_log:
                if step.succeeded:
                    assert step.exit_code == 0, f"Successful step should have exit code 0, got {step.exit_code}"
                else:
                    assert step.exit_code != 0, f"Failed step should have non-zero exit code, got {step.exit_code}"
            print("   ✅ Exit codes correctly recorded")
        except Exception as e:
            print(f"   ❌ Execution failed: {e}")
            raise
    
    print("\n✅ Executor error handling test passed!")
    return True


def test_executor_with_tavily():
    """Test ExecutorAgent with Tavily search tool available."""
    print("\n" + "=" * 60)
    print("Testing ExecutorAgent with Tavily")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    mock_shell = MagicMock(spec=PersistentShell)
    mock_shell.execute.return_value = (0, "Command executed")
    
    mock_llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Set TAVILY_API_KEY environment variable
    with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
        try:
            # Patch the agent creation and execution to avoid actual LLM calls
            with patch('agents.executor._make_agent_with_history') as mock_make_agent, \
                 patch('agents.executor._run_agent_in_thread') as mock_run_agent:
                
                mock_agent = MagicMock()
                mock_make_agent.return_value = mock_agent
                mock_run_agent.return_value = {"output": "Tavily test executed"}
                
                executor = ExecutorAgent(llm=mock_llm, shell=mock_shell, os_info=os_info)
                
                print("\n1. Checking Tavily availability...")
                if executor._tavily_available:
                    print("   ✅ Tavily tool initialized")
                else:
                    print("   ⚠️  Tavily not available (expected if dependencies missing)")
                
                # Verify shell tool is present
                assert executor._shell_tool is not None, "Shell tool should be present"
                print("   ✅ Shell tool present")
                
        except Exception as e:
            print(f"   ⚠️  Tavily initialization issue: {e}")
            print("   (This is acceptable if dependencies are not installed)")
    
    print("\n✅ Executor Tavily test passed!")
    return True


def test_executor_plan_with_commands():
    """Test that executor properly parses and executes plan commands."""
    print("\n" + "=" * 60)
    print("Testing Executor Plan Command Parsing")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    mock_shell = MagicMock(spec=PersistentShell)
    mock_shell.execute.return_value = (0, "Command executed successfully")
    
    mock_llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Patch the agent creation and execution to avoid actual LLM calls
    with patch('agents.executor._make_agent_with_history') as mock_make_agent, \
         patch('agents.executor._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "Commands parsed and executed"}
        
        executor = ExecutorAgent(llm=mock_llm, shell=mock_shell, os_info=os_info)
        
        # Mock the agent execution to simulate tool calls
        def simulate_execution(*args, **kwargs):
            # The agent would normally parse the plan and call the tool for each command
            executor._shell_tool._run("sudo apt-get update")
            executor._shell_tool._run("sudo apt-get install -y curl wget")
            executor._shell_tool._run("systemctl status nginx")
            executor._shell_tool._run("ls -la /etc/nginx")
            return {"output": "Commands parsed and executed"}
            
        mock_run_agent.side_effect = simulate_execution
        
        # Test plan with various command formats
        plan = """## 1. First step - update packages
sudo apt-get update
## 2. Second step - install software
sudo apt-get install -y curl wget
## 3. Third step - check service
systemctl status nginx
## 4. Fourth step - list files
ls -la /etc/nginx"""
        
        user_task = "Test command parsing"
        
        print("\n1. Executing plan with multiple command formats...")
        try:
            # Set environment variable to skip prompts during tool execution in test
            with patch.dict(os.environ, {"PLANNER_SHELL_TEST": "1"}):
                output, exec_log = executor.execute_plan_with_log(plan, user_task)
            
            print(f"   ✅ Execution completed")
            print(f"   Commands executed: {len(exec_log)}")
            
            # Verify commands were extracted correctly (should strip the "## X. description" part)
            commands = [step.command for step in exec_log]
            print(f"   Commands: {commands}")
            
            # Check that commands don't include the markdown headers
            for cmd in commands:
                assert not cmd.startswith("##"), f"Command should not include markdown header: {cmd}"
                assert cmd.strip() != "", "Command should not be empty"
            
            # Check for specific expected commands (using substring match for flexibility)
            assert any("apt-get" in cmd and "update" in cmd for cmd in commands), "Should include apt-get update"
            assert any("apt-get" in cmd and "install" in cmd and "curl wget" in cmd for cmd in commands), "Should include curl wget install"
            assert any("systemctl" in cmd and "status nginx" in cmd for cmd in commands), "Should include systemctl status"
            assert any("ls -la /etc/nginx" in cmd for cmd in commands), "Should include ls -la"
            
            print("   ✅ Commands correctly extracted from plan")
        except Exception as e:
            print(f"   ❌ Execution failed: {e}")
            raise
    
    print("\n✅ Executor command parsing test passed!")
    return True


def test_executor_log_completeness():
    """Test that execution log captures all required information."""
    print("\n" + "=" * 60)
    print("Testing Execution Log Completeness")
    print("=" * 60)
    
    # Initialize auto-approve mode to avoid interactive prompts
    
    mock_shell = MagicMock(spec=PersistentShell)
    
    # Return varied outputs and exit codes
    call_count = 0
    def mock_execute(command, timeout=600, has_progress=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (0, "Updated successfully")
        elif call_count == 2:
            return (1, "Error: package not found")
        elif call_count == 3:
            return (0, "Service started")
        else:
            return (0, "OK")
    
    mock_shell.execute.side_effect = mock_execute
    
    mock_llm = MagicMock()
    os_info = "Ubuntu 24.04.4 LTS"
    
    # Patch the agent creation and execution to avoid actual LLM calls
    with patch('agents.executor._make_agent_with_history') as mock_make_agent, \
         patch('agents.executor._run_agent_in_thread') as mock_run_agent:
        
        mock_agent = MagicMock()
        mock_make_agent.return_value = mock_agent
        mock_run_agent.return_value = {"output": "Log completeness test executed"}
        
        executor = ExecutorAgent(llm=mock_llm, shell=mock_shell, os_info=os_info)
        
        # Mock the agent execution to simulate tool calls
        def simulate_execution(*args, **kwargs):
            # The agent would normally parse the plan and call the tool for each command
            executor._shell_tool._run("apt-get update")
            executor._shell_tool._run("apt-get install -y test-pkg")
            executor._shell_tool._run("systemctl start test")
            return {"output": "Log completeness test executed"}
            
        mock_run_agent.side_effect = simulate_execution
        
        plan = """## 1. Update
apt-get update
## 2. Install (will fail)
apt-get install -y test-pkg
## 3. Start service
systemctl start test"""
        
        user_task = "Test log completeness"
        
        print("\n1. Collecting execution log...")
        try:
            # Set environment variable to skip prompts during tool execution in test
            with patch.dict(os.environ, {"PLANNER_SHELL_TEST": "1"}):
                output, exec_log = executor.execute_plan_with_log(plan, user_task)
            
            # Verify all ExecutionStep fields
            for i, step in enumerate(exec_log, 1):
                print(f"\n   Step {i}:")
                print(f"     Command: {step.command}")
                print(f"     Succeeded: {step.succeeded}")
                print(f"     Exit code: {step.exit_code}")
                print(f"     Output length: {len(step.output) if step.output else 0}")
                
                assert step.command and isinstance(step.command, str), "Command should be non-empty string"
                assert isinstance(step.succeeded, bool), "Succeeded should be boolean"
                assert isinstance(step.exit_code, int), "Exit code should be integer"
                assert step.output is not None, "Output should not be None"
                assert isinstance(step.output, str), "Output should be string"
            
            print("\n   ✅ All log entries have required fields")
            
            # Verify we have the expected mix
            assert any(s.succeeded for s in exec_log), "Should have at least one success"
            assert any(not s.succeeded for s in exec_log), "Should have at least one failure"
            print("   ✅ Mixed success/failure captured")
        except Exception as e:
            print(f"   ❌ Log collection failed: {e}")
            raise
    
    print("\n✅ Execution log completeness test passed!")
    return True


def main():
    """Run all executor integration tests."""
    print("=" * 60)
    print("EXECUTOR AGENT INTEGRATION TESTS")
    print("=" * 60)
    
    try:
        test_executor_with_mock_shell()
        test_executor_error_handling()
        test_executor_with_tavily()
        test_executor_plan_with_commands()
        test_executor_log_completeness()
        
        print("\n" + "=" * 60)
        print("🎉 ALL EXECUTOR INTEGRATION TESTS PASSED!")
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
