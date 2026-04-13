#!/usr/bin/env python3
"""Test host mode output capture."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shell.sandbox import HostBackend

def test_host_output():
    """Test that host backend captures output correctly."""
    print("Testing Host backend output capture...")
    
    try:
        backend = HostBackend()
        backend.initialize()
        print("✓ Host backend initialized")
        
        # Test 1: Simple echo command
        exit_code, output = backend.execute("echo 'Hello from host'")
        print(f"\nTest 1: echo command")
        print(f"  Exit code: {exit_code}")
        print(f"  Output: {repr(output)}")
        assert output.strip() == "Hello from host", f"Expected 'Hello from host', got: {repr(output)}"
        print("  ✓ Pass")
        
        # Test 2: cat /etc/os-release
        exit_code, output = backend.execute("cat /etc/os-release | head -3")
        print(f"\nTest 2: cat /etc/os-release")
        print(f"  Exit code: {exit_code}")
        print(f"  Output length: {len(output)} chars")
        print(f"  Output:\n{output}")
        assert len(output) > 0, "Expected output from cat /etc/os-release"
        print("  ✓ Pass")
        
        print("\n✅ Host mode tests passed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_host_output()
