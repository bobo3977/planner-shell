#!/usr/bin/env python3
"""
Integration test for Auditor Agent with main system
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from config import ENABLE_AUDITOR
from agents.auditor import AuditorAgent

def test_integration():
    print("=== Integration Test ===")
    print(f"ENABLE_AUDITOR from config: {ENABLE_AUDITOR}")
    
    # Test Auditor Agent creation
    auditor = AuditorAgent()
    print(f"Auditor Agent created: {auditor is not None}")
    print(f"Patterns loaded: {len(auditor.compiled_patterns)}")
    
    # Test with a dangerous command
    test_plan = "rm -rf /tmp/test"
    dangerous = auditor.audit_plan(test_plan)
    print(f"Dangerous commands found: {len(dangerous)}")
    if dangerous:
        print(f"First dangerous command: {dangerous[0][2]}")
        print(f"Command: {dangerous[0][1]}")
    
    # Test with safe command
    safe_plan = "ls -la"
    safe = auditor.audit_plan(safe_plan)
    print(f"Safe plan dangerous commands: {len(safe)}")

if __name__ == '__main__':
    test_integration()