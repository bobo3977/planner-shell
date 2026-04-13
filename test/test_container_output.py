#!/usr/bin/env python3
"""Test container output capture."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shell.sandbox import DockerBackend

def test_docker_output():
    """Test that Docker backend captures output correctly."""
    print("Testing Docker backend output capture...")
    
    try:
        backend = DockerBackend(image="alpine:latest")
        backend.initialize()
        print("✓ Docker container initialized")
        
        # Test 1: Simple echo command
        exit_code, output = backend.execute("echo 'Hello from Docker'")
        print(f"\nTest 1: echo command")
        print(f"  Exit code: {exit_code}")
        print(f"  Output: {repr(output)}")
        print(f"  Output length: {len(output)}")
        assert output.strip() == "Hello from Docker", f"Expected 'Hello from Docker', got: {repr(output)}"
        print("  ✓ Pass")
        
        # Test 2: cat /etc/os-release
        exit_code, output = backend.execute("cat /etc/os-release")
        print(f"\nTest 2: cat /etc/os-release")
        print(f"  Exit code: {exit_code}")
        print(f"  Output length: {len(output)} chars")
        print(f"  First 200 chars: {output[:200]}")
        assert len(output) > 0, "Expected output, got empty"
        assert "NAME=" in output or "ID=" in output, f"Expected OS release info, got: {repr(output[:100])}"
        print("  ✓ Pass")
        
        # Test 3: Multiple commands
        exit_code, output = backend.execute("echo 'line1'; echo 'line2'; echo 'line3'")
        print(f"\nTest 3: Multiple echo commands")
        print(f"  Exit code: {exit_code}")
        print(f"  Output:\n{output}")
        lines = [l.strip() for l in output.strip().split('\n') if l.strip()]
        assert len(lines) >= 3, f"Expected at least 3 lines, got: {lines}"
        print("  ✓ Pass")
        
        print("\n✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_docker_output()
