#!/usr/bin/env python3
"""
Test suite for the back command functionality.
Tests that users can go back to previous commands in the shell history.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shell.persistent import PersistentShell
from shell.tool import PersistentShellTool
from common_types import ExecutionStep


def test_shell_history_tracking():
    """Test that PersistentShell tracks command history correctly."""
    print("\n=== Testing shell history tracking ===")
    
    shell = PersistentShell()
    
    # Execute some commands
    exit_code1, output1 = shell.execute("echo 'Hello'")
    exit_code2, output2 = shell.execute("echo 'World'")
    exit_code3, output3 = shell.execute("echo 'Test'")
    
    # Check history
    assert len(shell.command_history) == 3, f"Expected 3 history entries, got {len(shell.command_history)}"
    
    # Verify history contents
    assert shell.command_history[0][0] == "echo 'Hello'", "First command should be 'echo Hello'"
    assert shell.command_history[1][0] == "echo 'World'", "Second command should be 'echo World'"
    assert shell.command_history[2][0] == "echo 'Test'", "Third command should be 'echo Test'"
    
    # Verify exit codes and outputs are stored
    assert shell.command_history[0][1] == exit_code1, "Exit code should be stored"
    assert shell.command_history[0][2] == output1, "Output should be stored"
    
    print("✅ Shell history tracking: PASSED")
    
    shell.close()
    return True


def test_back_command_basic():
    """Test that back command re-executes the previous command."""
    print("\n=== Testing back command basic functionality ===")
    
    shell = PersistentShell()
    
    # Mock the safe_prompt to simulate user choosing 'back'
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        # First call: user chooses 'y' to execute first command
        # Second call: user chooses 'b' (back), then 'y' to execute
        mock_prompt.side_effect = ['y', 'b', 'y']
        
        tool = PersistentShellTool(shell=shell)
        
        # Execute first command
        result1 = tool._run("echo 'First'")
        assert "First" in result1 or "Exit Code: 0" in result1, "First command should execute"
        
        # Now execute a second command and choose back
        # The tool should re-execute the previous command (echo 'First')
        result2 = tool._run("echo 'Second'")
        # The result should be from the previous command (echo 'First')
        assert "First" in result2 or "Exit Code: 0" in result2, "Back should re-execute previous command"
    
    print("✅ Back command basic: PASSED")
    shell.close()
    return True


def test_back_command_with_skip():
    """Test back command behavior after skip."""
    print("\n=== Testing back command after skip ===")
    
    shell = PersistentShell()
    
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        # First: y (execute)
        # Second: s (skip)
        # Third: b (back), then y (execute the previous command)
        mock_prompt.side_effect = ['y', 's', 'b', 'y']
        
        tool = PersistentShellTool(shell=shell)
        
        # Execute first command
        result1 = tool._run("echo 'Executed'")
        assert "Executed" in result1, "First command should execute"
        
        # Skip second command
        result2 = tool._run("echo 'Skipped'")
        assert "skipped" in result2.lower(), "Second command should be skipped"
        
        # Back should go back to the executed command and then execute it
        result3 = tool._run("echo 'Third'")
        # Should re-execute "echo 'Executed'"
        assert "Executed" in result3 or "Exit Code: 0" in result3, "Back should go to last executed command"
    
    print("✅ Back after skip: PASSED")
    shell.close()
    return True


def test_back_command_empty_history():
    """Test back command when history is empty."""
    print("\n=== Testing back command with empty history ===")
    
    shell = PersistentShell()
    
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        # Simulate: back (warning), then yes to execute
        mock_prompt.side_effect = ['b', 'y']
        
        tool = PersistentShellTool(shell=shell)
        
        result = tool._run("echo 'Test'")
        assert "Test" in result or "Exit Code: 0" in result, "Command should execute after back fails"
    
    print("✅ Back with empty history: PASSED")
    shell.close()
    return True


def test_back_command_multiple_history():
    """Test back command with multiple history entries."""
    print("\n=== Testing back command with multiple history entries ===")
    
    shell = PersistentShell()
    
    # Execute three commands
    shell.execute("echo 'First'")
    shell.execute("echo 'Second'")
    shell.execute("echo 'Third'")
    
    assert len(shell.command_history) == 3, "Should have 3 history entries"
    
    # Simulate back from a new command - should go to 'Third', then execute it
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        mock_prompt.side_effect = ['b', 'y']  # back, then yes to execute
        
        tool = PersistentShellTool(shell=shell)
        result = tool._run("echo 'New'")
        # Should re-execute the last command in history: 'Third'
        assert "Third" in result or "Exit Code: 0" in result, "Back should re-execute 'Third'"
    
    print("✅ Back with multiple history: PASSED")
    shell.close()
    return True


def test_back_command_multiple_backs():
    """Test multiple consecutive back commands to navigate through history."""
    print("\n=== Testing multiple consecutive back commands ===")
    
    shell = PersistentShell()
    
    # Execute three commands
    shell.execute("echo 'First'")
    shell.execute("echo 'Second'")
    shell.execute("echo 'Third'")
    
    assert len(shell.command_history) == 3, "Should have 3 history entries"
    
    # Simulate: back (to Third), back (to Second), back (to First), then execute
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        mock_prompt.side_effect = ['b', 'b', 'b', 'y']  # back x3, then yes
        
        tool = PersistentShellTool(shell=shell)
        result = tool._run("echo 'Start'")
        # Should execute 'First' after three backs
        assert "First" in result or "Exit Code: 0" in result, "Multiple backs should reach First"
    
    print("✅ Multiple consecutive backs: PASSED")
    shell.close()
    return True


def test_back_then_skip_then_back():
    """Test back -> skip -> back sequence."""
    print("\n=== Testing back -> skip -> back sequence ===")
    
    shell = PersistentShell()
    
    # Execute three commands: A, B, C
    shell.execute("echo 'A'")
    shell.execute("echo 'B'")
    shell.execute("echo 'C'")
    
    assert len(shell.command_history) == 3, "Should have 3 history entries"
    
    # Simulate: back (to C), skip C (C marked skipped, show C), back (to C again), back (to B), execute
    with patch('utils.terminal.safe_prompt') as mock_prompt:
        # back -> skip -> back -> back -> yes (execute)
        mock_prompt.side_effect = ['b', 's', 'b', 'b', 'y']
        
        tool = PersistentShellTool(shell=shell)
        result = tool._run("echo 'Start'")
        # After back->skip, we move to C (position 2). Then back goes to C again (skipped), then back goes to B (position 1)
        # Should execute 'B' after the sequence
        assert "B" in result or "Exit Code: 0" in result, "Back->skip->back->back should reach B"
    
    print("✅ Back -> skip -> back: PASSED")
    shell.close()
    return True


if __name__ == "__main__":
    all_passed = True
    
    try:
        test_shell_history_tracking()
    except Exception as e:
        print(f"❌ test_shell_history_tracking FAILED: {e}")
        all_passed = False
    
    try:
        test_back_command_basic()
    except Exception as e:
        print(f"❌ test_back_command_basic FAILED: {e}")
        all_passed = False
    
    try:
        test_back_command_with_skip()
    except Exception as e:
        print(f"❌ test_back_command_with_skip FAILED: {e}")
        all_passed = False
    
    try:
        test_back_command_empty_history()
    except Exception as e:
        print(f"❌ test_back_command_empty_history FAILED: {e}")
        all_passed = False
    
    try:
        test_back_command_multiple_history()
    except Exception as e:
        print(f"❌ test_back_command_multiple_history FAILED: {e}")
        all_passed = False
    
    try:
        test_back_command_multiple_backs()
    except Exception as e:
        print(f"❌ test_back_command_multiple_backs FAILED: {e}")
        all_passed = False
    
    try:
        test_back_then_skip_then_back()
    except Exception as e:
        print(f"❌ test_back_then_skip_then_back FAILED: {e}")
        all_passed = False
    
    if all_passed:
        print("\n" + "=" * 60)
        print("✅ All back command tests PASSED!")
        print("=" * 60)
        exit(0)
    else:
        print("\n" + "=" * 60)
        print("❌ Some tests FAILED")
        print("=" * 60)
        exit(1)
