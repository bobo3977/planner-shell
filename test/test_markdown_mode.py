import os
import unittest
import tempfile
from agents.planner import PlannerAgent
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

class TestMarkdownMode(unittest.TestCase):
    def test_markdown_file_input(self):
        """Verify that giving a markdown file as task works."""
        from utils.os_info import is_markdown_file
        
        # Create temp file in CURRENT directory to pass the safety check in is_markdown_file
        # (which rejects files outside the current working directory)
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", dir=".", delete=False) as f:
            f.write("# Test Plan\necho hello")
            tmp_path = f.name
            
        try:
            # Check is_markdown_file logic
            self.assertTrue(is_markdown_file(tmp_path), f"File {tmp_path} should be recognized as markdown")
            
            # Mocking the content loading
            from utils.io import read_markdown_file
            content = read_markdown_file(tmp_path)
            self.assertIn("echo hello", content)
            
            # Now test PlannerAgent behavior with markdown
            mock_cache = MagicMock()
            mock_cache.get.return_value = None  # Force a cache miss
            planner = PlannerAgent(llm=MagicMock(), plan_cache=mock_cache, os_info="linux")
            
            # Mock agent for planning
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [AIMessage(content="## 1. echo hello")]}
            
            with patch('agents.planner._make_agent_with_history', return_value=mock_agent):
                # create_plan(task, markdown_content=...)
                plan, _ = planner.create_plan(tmp_path, markdown_content=content)
            
            self.assertIn("echo hello", plan)
            # Check if last_cache_meta correctly recorded the markdown source
            self.assertIsNotNone(planner.last_cache_meta)
            self.assertEqual(planner.last_cache_meta.get("markdown_file"), tmp_path)
            
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

if __name__ == "__main__":
    unittest.main()
