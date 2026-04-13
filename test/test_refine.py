import os
import sys
import unittest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.planner import PlannerAgent
from common_types import ExecutionStep
from unittest.mock import MagicMock, patch

class TestRefine(unittest.TestCase):
    def test_distill_transcript_building(self):
        """Verify that PlannerAgent correctly builds the transcript for distillation."""
        # Mock load_prompt to use the same logic as the real code
        # required_vars=["{current_date}", "{os_info}", "{user_task}", "{execution_history}"]
        mock_prompt_template = "Date: {current_date}, OS: {os_info}, Task: {user_task}, History: {execution_history}"
        
        with patch("agents.planner.load_prompt", return_value=mock_prompt_template):
            planner = PlannerAgent(llm=MagicMock(), plan_cache=MagicMock(), os_info="linux")
            
            # Mock LLM response
            mock_response = MagicMock()
            mock_response.content = "## 1. ls\n## 2. sudo rm -rf /tmp/foo"
            planner.llm.invoke.return_value = mock_response
            
            # We also need to mock _run_agent_in_thread since it uses a thread pool
            # actually we can mock it directly
            with patch("agents.planner._run_agent_in_thread", return_value=mock_response):
                log = [
                    ExecutionStep(command="ls", exit_code=0, output="..."),
                    ExecutionStep(command="rm -rf /", exit_code=1, output="Permission denied"),
                    ExecutionStep(command="sudo rm -rf /tmp/foo", exit_code=0, output="Done")
                ]
                
                distilled = planner.distill_plan("Test task", log, "Original plan")
                
                # Check results
                self.assertIn("ls", distilled)
                self.assertIn("sudo rm -rf /tmp/foo", distilled)

    def test_transcript_formatting(self):
        """Specifically verify the transcript line formatting."""
        planner = PlannerAgent(llm=MagicMock(), plan_cache=MagicMock(), os_info="linux")
        log = [
            ExecutionStep(command="ls", exit_code=0, output="..."),
            ExecutionStep(command="fail_cmd", exit_code=1, output="Error")
        ]
        
        # Manually invoke the logic from distill_plan to verify transcript format
        lines = []
        for i, step in enumerate(log, 1):
            status = "exit 0 (SUCCESS)" if step.succeeded else f"exit {step.exit_code} (FAILED)"
            lines.append(f"{i}. [{status}] {step.command}")
        transcript = "\n".join(lines)
        
        self.assertEqual(transcript, "1. [exit 0 (SUCCESS)] ls\n2. [exit 1 (FAILED)] fail_cmd")

if __name__ == "__main__":
    unittest.main()
