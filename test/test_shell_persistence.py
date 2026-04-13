import os
import sys
import unittest
import tempfile

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shell.persistent import PersistentShell

class TestShellPersistence(unittest.TestCase):
    def setUp(self):
        self.shell = PersistentShell()
        
    def tearDown(self):
        self.shell.close()
        
    def test_directory_persistence(self):
        """Verify that 'cd' changes persist across multiple executions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Need realpath because /tmp can be a symlink or have different paths on some systems
            real_tmpdir = os.path.realpath(tmpdir)
            
            # 1. cd into the temp directory
            exit_code, output = self.shell.execute(f"cd {real_tmpdir}")
            self.assertEqual(exit_code, 0)
            
            # 2. In a separate execute call, verify we are still there
            exit_code, output = self.shell.execute("pwd")
            self.assertEqual(exit_code, 0)
            self.assertEqual(output.strip(), real_tmpdir)
            
    def test_env_var_persistence(self):
        """Verify that 'export' changes persist across multiple executions."""
        # 1. Export a variable
        var_name = "PLANNER_SHELL_TEST_VAR"
        var_value = "persistence_works"
        exit_code, output = self.shell.execute(f"export {var_name}={var_value}")
        self.assertEqual(exit_code, 0)
        
        # 2. In a separate execute call, verify it's still set
        exit_code, output = self.shell.execute(f"echo ${var_name}")
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), var_value)

    def test_alias_persistence(self):
        """Verify that aliases persist if set in the shell session."""
        # 1. Define an alias
        exit_code, output = self.shell.execute("alias myecho='echo ALIAS_WORKS'")
        self.assertEqual(exit_code, 0)
        
        # 2. Use the alias
        exit_code, output = self.shell.execute("myecho")
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "ALIAS_WORKS")

    def test_execute_progress_mode_detects_marker(self):
        """Verify progress-mode execution still detects shell markers."""
        progress_cmd = (
            "python3 -c 'import sys; "
            "sys.stdout.write(\"progress 0\\r\"); sys.stdout.flush(); "
            "sys.stdout.write(\"done\\n\")'"
        )
        exit_code, output = self.shell.execute(progress_cmd, timeout=5, has_progress=True)
        self.assertEqual(exit_code, 0)
        self.assertIn("done", output)

if __name__ == "__main__":
    unittest.main()
