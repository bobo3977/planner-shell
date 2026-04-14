#!/usr/bin/env python3
"""
Executor agent: executes a pre-built plan step by step using the shell tool.
"""

from __future__ import annotations

import config
from config import EXECUTE_TIMEOUT, load_prompt
from common_types import ExecutionStep, FinishExecutionException
from llm.setup import _make_agent_with_history, extract_agent_output
from utils.threads import _run_agent_in_thread
from shell.persistent import PersistentShell
from shell.tool import PersistentShellTool, VerifyStateTool, FileEditorTool


class ExecutorAgent:
    """Executes a pre-built plan step by step using the shell tool."""

    def __init__(self, llm, shell: PersistentShell, os_info: str, is_sandbox: bool = False):
        self.llm = llm
        self.shell = shell
        self.os_info = os_info
        self.is_sandbox = is_sandbox
        self._shell_tool = PersistentShellTool(shell=shell, is_sandbox=is_sandbox)
        self._verify_tool = VerifyStateTool(shell=shell)
        self._file_editor_tool = FileEditorTool(shell=shell)
        # Initialize Tavily search tool if API key is available (for error recovery)
        import os
        tavily_key = os.getenv("TAVILY_API_KEY")
        if tavily_key:
            try:
                # Use TavilySearchWithIndicator from agents.planner (same as PlannerAgent)
                from agents.planner import TavilySearchWithIndicator
                self._tavily = TavilySearchWithIndicator(max_results=3)
                self._tavily_available = True
            except Exception:
                # Any error (ImportError, missing dependencies, etc.) → disable Tavily
                self._tavily = None
                self._tavily_available = False
        else:
            self._tavily = None
            self._tavily_available = False
        # Give the shell tool a reference to Tavily so it can reset the search
        # counter whenever a command succeeds.
        self._shell_tool._tavily_ref = self._tavily

    def execute_plan(self, plan: str, user_task: str) -> str:
        print("\n🚀 Starting plan execution...")

        # Build tools list: always include shell tool, conditionally include verification tool, optionally include Tavily
        tools = [self._shell_tool]
        
        from config import ENABLE_IDEMPOTENCY_CHECK, ENABLE_FILE_EDITOR
        if ENABLE_IDEMPOTENCY_CHECK:
            tools.append(self._verify_tool)
            idempotency_rules = (
                "- IDEMPOTENCY CHECK: Before executing the primary command for a step, use the `verify_state` tool exactly ONCE to run a silent, read-only check to see if the step's goal is already met.\n"
                "- EXCEPTIONS: For unconditionally necessary operations like fetching remote updates (e.g., 'apt-get update', 'yum makecache'), DO NOT use verify_state. Proceed directly to execute_shell_command.\n"
                "- If `verify_state` shows the goal is already met (returns Exit Code 0), you MUST IMMEDIATELY proceed to the NEXT step in the plan. DO NOT call `verify_state` again for the same step, and DO NOT call `execute_shell_command` for that step.\n"
                "- If the goal is not met (returns non-zero), use `execute_shell_command(command='...')` to run the main command. This tool will ask the human for approval."
            )
            start_instruction = "Begin by verifying the state for the first step using verify_state."
        else:
            idempotency_rules = "- For EACH command, call execute_shell_command(command='...')"
            start_instruction = "Call execute_shell_command for the first command."

        if ENABLE_FILE_EDITOR:
            tools.append(self._file_editor_tool)
            file_editor_rule = (
                "- FILE EDITS: When a step involves creating or modifying a file (e.g., writing a config, "
                "appending lines, replacing a value), use the `file_editor` tool instead of shell commands "
                "like sed, awk, or cat<<EOF. Use actions: 'write', 'append', 'str_replace', or 'read'."
            )
        else:
            file_editor_rule = ""

        if self._tavily_available:
            tools.append(self._tavily)

        # Load base prompt
        system_prompt = load_prompt(
            "executor",
            required_vars=["{os_info}", "{user_task}", "{plan}"]
        )

        # Format dynamic variables
        system_prompt = system_prompt.format(
            os_info=self.os_info,
            user_task=user_task,
            plan=plan,
            idempotency_rules=idempotency_rules,
            start_instruction=start_instruction,
            file_editor_rule=file_editor_rule,
        )

        agent_with_history = _make_agent_with_history(
            self.llm, tools, system_prompt,
            max_iterations=100, recursion_limit=100,
        )

        print("\n⏳ Executing plan (real-time monitoring)...")
        from utils.spinner import spinning
        if self._tavily_available and self._tavily:
            self._tavily.abort_event = None # Reset
            
        try:
            with spinning("Executing plan..."):
                result = _run_agent_in_thread(
                    agent_with_history,
                    input_dict={"input": "Execute the plan"},
                    session_id="executor_session",
                    shell=self.shell,
                    timeout=float(EXECUTE_TIMEOUT),
                )
                # After start, the shell.abort_event is populated.
                if self._tavily_available and self._tavily:
                    self._tavily.abort_event = getattr(self.shell, 'abort_event', None)
        except FinishExecutionException:
            # Propagate early finish signal
            raise
        except Exception:
            # Other exceptions from _run_agent_in_thread
            raise
        finally:
            # Always stop the spinner that was started after the last command.
            self._shell_tool._stop_spinner()

        if result is None:
            return "Plan execution was interrupted. The agent stopped after the interrupted command."
        
        output = extract_agent_output(result)
        if not output and config.LLM_PROVIDER == "ollama":
             return (
                 "⚠️  The local LLM returned an empty result without executing any commands.\n"
                 "   This usually happens when the model is overwhelmed by the prompt complexity.\n"
                 "   Suggestion: Try using a more capable model like `qwen2.5:7b-instruct` or `llama3.1:70b` if resources allow."
             )
        return output

    def execute_plan_with_log(
        self, plan: str, user_task: str
    ) -> tuple[str, list[ExecutionStep]]:
        """Execute a plan and return (output_text, execution_log).

        Identical to execute_plan() but also collects every command that was
        run—together with its exit code and output—into a list of ExecutionStep
        objects.  The caller can pass this log to PlannerAgent.distill_plan()
        to generate a clean, idempotent plan from the successful path.
        """
        execution_log: list[ExecutionStep] = []
        # Enable logging on the shell tool for the duration of this execution
        original_log = self._shell_tool.execution_log
        self._shell_tool.execution_log = execution_log
        try:
            output = self.execute_plan(plan, user_task)

            return output, execution_log
        except FinishExecutionException:
            # Early finish requested — return partial log instead of propagating
            output = "Plan execution finished early by user."
            return output, execution_log
        finally:
            # Always stop the spinner that was started after the last command.
            self._shell_tool._stop_spinner()
            # Always restore the original log reference (None if it wasn't set)
            if self._shell_tool.execution_log == execution_log:
                self._shell_tool.execution_log = original_log
