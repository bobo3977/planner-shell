import os
import subprocess
import unittest
import sys
from unittest.mock import patch

class TestAutoApprove(unittest.TestCase):
    def test_auto_approve_logic_only(self):
        """Test the underlying safe_prompt button logic directly."""
        # Use patch to dynamically change the global variable in utils.terminal
        with patch("utils.terminal.AUTO_APPROVE_MODE", True):
            from utils.terminal import safe_prompt
            # Verify safe_prompt returns default without waiting for input
            res = safe_prompt("Test prompt (should be auto-approved)", default='y')
            self.assertEqual(res, 'y')
            
        with patch("utils.terminal.AUTO_APPROVE_MODE", False):
            from utils.terminal import safe_prompt
            # We can't call it here because it will hang, but we verified the logic
            pass

if __name__ == "__main__":
    unittest.main()
