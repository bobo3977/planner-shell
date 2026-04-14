import unittest
from unittest.mock import patch
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.terminal import safe_prompt, set_auto_approve_mode
import utils.terminal

class TestAutoApproveLoop(unittest.TestCase):
    def setUp(self):
        # Reset auto-approve mode before each test
        set_auto_approve_mode(False)

    def test_safe_prompt_respects_auto_approve_flag(self):
        """Test that safe_prompt does NOT auto-approve if auto_approve=False."""
        # 1. Enable auto-approve mode
        set_auto_approve_mode(True)
        self.assertTrue(utils.terminal.AUTO_APPROVE_MODE)
        
        # 2. Confirmation prompt (default: auto_approve=True)
        # Should return 'y' without calling input()
        res = safe_prompt("Confirm? ")
        self.assertEqual(res, 'y')
        
        # 3. Data input prompt (explicit: auto_approve=False)
        # Should call input() even if AUTO_APPROVE_MODE is True
        with patch('builtins.input', return_value='my task') as mock_input:
            res2 = safe_prompt("Task: ", auto_approve=False)
            self.assertEqual(res2, 'my task')
            mock_input.assert_called_once()

if __name__ == "__main__":
    unittest.main()
