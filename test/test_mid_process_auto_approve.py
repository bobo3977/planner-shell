import unittest
from unittest.mock import patch
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.terminal import safe_prompt, set_auto_approve_mode
import utils.terminal

class TestMidProcessAutoApprove(unittest.TestCase):
    def setUp(self):
        # Reset auto-approve mode before each test
        set_auto_approve_mode(False)

    def test_y_trigger_enables_auto_approve(self):
        """Test that entering 'y!' at a prompt enables auto-approve mode for subsequent calls."""
        # 1. Initial state: auto-approve is off
        self.assertFalse(utils.terminal.AUTO_APPROVE_MODE)
        
        # 2. First prompt: user enters 'y!'
        with patch('builtins.input', return_value='y!'):
            res = safe_prompt("First prompt: ")
            self.assertEqual(res, 'y')
        
        # 3. Check that it triggered auto-approve mode
        self.assertTrue(utils.terminal.AUTO_APPROVE_MODE)
        
        # 4. Subsequent prompt: should be automatically approved without input
        # Note: if it tries to call input(), it will fail because we are NOT patching it here
        # (Actually, safe_prompt checks AUTO_APPROVE_MODE before calling input())
        res2 = safe_prompt("Second prompt: ")
        self.assertEqual(res2, 'y')

    def test_case_insensitivity(self):
        """Test that 'Y!' also works."""
        with patch('builtins.input', return_value='Y!'):
            res = safe_prompt("Prompt: ")
            self.assertEqual(res, 'y')
        self.assertTrue(utils.terminal.AUTO_APPROVE_MODE)

    def test_trailing_spaces(self):
        """Test that ' y! ' also works."""
        with patch('builtins.input', return_value=' y! '):
            res = safe_prompt("Prompt: ")
            self.assertEqual(res, 'y')
        self.assertTrue(utils.terminal.AUTO_APPROVE_MODE)

if __name__ == "__main__":
    unittest.main()
