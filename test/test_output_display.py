#!/usr/bin/env python3
"""Test that command output is displayed correctly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shell.persistent import PersistentShell
from shell.tool import PersistentShellTool

def test_output_display():
    """Test that command outputs are displayed to user."""
    print("Testing output display...")
    
    shell = PersistentShell()
    tool = PersistentShellTool(shell=shell)
    
    # Test 1: Simple echo
    print("\n" + "="*60)
    print("Test 1: echo command")
    print("="*60)
    result = tool._run("echo 'Hello World'")
    print(f"\nTool returned:\n{result}\n")
    
    # Test 2: cat /etc/os-release (partial)
    print("\n" + "="*60)
    print("Test 2: cat /etc/os-release (first 2 lines)")
    print("="*60)
    result = tool._run("head -2 /etc/os-release")
    print(f"\nTool returned:\n{result}\n")
    
    print("✅ Output display test complete")

if __name__ == "__main__":
    test_output_display()
