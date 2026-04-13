#!/usr/bin/env python3
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from main import _normalize_plan_for_container
from agents.executor import ExecutorAgent
from shell.tool import PersistentShellTool
from shell.persistent import PersistentShell

def test_plan_normalization():
    print("Testing _normalize_plan_for_container...")
    plan = """# Install SSH
## 1. Start SSH
sudo systemctl start ssh

## 2. Check status
systemctl status ssh

## 3. Enable service
sudo systemctl enable ssh
"""
    normalized = _normalize_plan_for_container(plan)
    print("Original Plan:")
    print(plan)
    print("\nNormalized Plan:")
    print(normalized)
    
    # Check assertions
    assert "service ssh start" in normalized
    assert "service ssh status" in normalized
    assert "service ssh start" in normalized # enable becomes start
    assert "sudo" not in normalized
    print("✅ _normalize_plan_for_container passed")

def test_executor_normalization():
    print("\nTesting ExecutorAgent._normalize_command...")
    # Mocking necessary objects
    class MockLLM: pass
    shell = None # Not used for _normalize_command
    
    executor = ExecutorAgent(llm=MockLLM(), shell=PersistentShell(), os_info="Linux")
    
    cmd1 = "sudo systemctl start nginx"
    cmd2 = "service nginx start"
    
    norm1 = executor._normalize_command(cmd1)
    norm2 = executor._normalize_command(cmd2)
    
    print(f"Original 1: {cmd1} -> Normalized: {norm1}")
    print(f"Original 2: {cmd2} -> Normalized: {norm2}")
    
    assert norm1 == norm2 == "service nginx" # Normalized keeps first 2 tokens after our conversion
    print("✅ ExecutorAgent._normalize_command passed")

if __name__ == "__main__":
    try:
        test_plan_normalization()
        test_executor_normalization()
        print("\nAll tests passed! 🎉")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
