#!/usr/bin/env python3
"""
Test suite runner
Executes each test module in sequence and aggregates results.
"""

import sys
import subprocess
from pathlib import Path

def run_test(test_file: str) -> tuple[bool, str]:
    """Run a single test file and return (success, output)."""
    print(f"\n{'='*70}")
    print(f"Running: {test_file}")
    print('='*70)
    
    import os
    test_dir = Path(__file__).parent
    test_path = test_dir / test_file
    
    env = os.environ.copy()
    project_root = str(test_dir.parent)
    # prepend root to PYTHONPATH
    if 'PYTHONPATH' in env:
        env['PYTHONPATH'] = f"{project_root}:{env['PYTHONPATH']}"
    else:
        env['PYTHONPATH'] = project_root

    result = subprocess.run(
        [sys.executable, str(test_path)],
        capture_output=True,
        text=True,
        cwd=test_dir,
        env=env
    )
    
    output = result.stdout + result.stderr
    print(output)
    
    success = result.returncode == 0
    return success, output

def main():
    """Run all tests and report results."""
    test_dir = Path(__file__).parent
    
    test_files = [
        "test_auditor_simple.py",
        "test_auditor_file.py",
        "test_auditor.py",
        "test_prompt_loading.py",
        "test_config.py",
        "test_security.py",
        "test_planner_integration.py",
        "test_executor_integration.py",
        "test_main_workflow.py",
        "test_cache_basic.py",
        "test_cache_ttl.py",
        "test_cache_hybrid_search.py",
        "test_cache_delete.py",
        "test_hash_consistency.py",
        "test_cache_clear_and_stats.py",
        "test_fts5_integration.py",
        "test_fts5_corruption.py",
        "test_fts5_corruption_detailed.py",
        "test_cache_backends.py",
        "test_list_edit_delete_shortcuts.py",
        "test_integration.py",
        "test_comprehensive.py",
        "test_commands.py",
        "test_shell_back_command.py",
        "test_shell_persistence.py",
        "test_refine.py",
        "test_auto_approve.py",
        "test_markdown_mode.py",
        "test_alpine_detection.py",
        "test_cache_regen.py",
        "test_container_output.py",
        "test_docker_os_info.py",
        "test_interactive_error.py",
        "test_newgrp_warning.py",
        "test_output_display.py",
        "test_output_host.py",
        "test_sandbox_backends.py",
        "test_sandbox_integration.py",
        "test_sandbox_os_info.py",
        "test_shell_detection.py",
    ]
    
    print("="*70)
    print("RUNNING ALL TESTS")
    print("="*70)
    
    results = []
    for test_file in test_files:
        test_path = test_dir / test_file
        if not test_path.exists():
            print(f"⚠️  Test file not found: {test_file}")
            results.append((False, f"File not found: {test_file}"))
            continue
        
        success, output = run_test(test_file)
        results.append((success, output))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for success, _ in results if success)
    total = len(results)
    
    for (test_file), (success, _) in zip(test_files, results):
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_file}")
    
    print("-"*70)
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed successfully!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    exit(main())
