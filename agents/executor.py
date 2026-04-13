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
        try:
            with spinning("Executing plan..."):
                result = _run_agent_in_thread(
                    agent_with_history,
                    input_dict={"input": "Execute the plan"},
                    session_id="executor_session",
                    shell=self.shell,
                    timeout=float(EXECUTE_TIMEOUT),
                )
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

            # If the agent stopped early, attempt to continue remaining steps.
            max_passes = 3
            passes = 1
            remaining = self._remaining_plan_commands(plan, execution_log)
            while remaining and passes < max_passes:
                print("\n⚠️  Detected unfinished plan steps. Continuing execution...")
                remaining_plan = self._build_remaining_plan(remaining)
                output = self.execute_plan(remaining_plan, user_task)
                remaining = self._remaining_plan_commands(remaining_plan, execution_log)
                passes += 1

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

    def _extract_plan_commands(self, plan: str) -> list[str]:
        """Extract one command per numbered step (## N.) in the plan."""
        import re

        commands: list[str] = []
        expect_command = False
        for raw_line in plan.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("```"):
                continue
            if re.match(r"^##\s+\d+\.?", line):
                expect_command = True
                continue
            if expect_command:
                if line.startswith(("#", "-", "*")):
                    continue
                commands.append(line)
                expect_command = False
        return commands

    def _normalize_command(self, command: str) -> str:
        """Normalize commands for loose matching (strip sudo/env, collapse spaces)."""
        import re

        # Split the command into tokens while preserving quoted arguments.
        # The goal is to obtain a *canonical* representation that identifies the
        # logical operation of the step, ignoring variations that do not affect
        # its outcome (environment assignments, sudo, non‑interactive flags, and
        # pager suppression). This enables the executor to recognise that an
        # edited or alternative command still satisfies the original plan step.
        tokens = command.strip().split()

        # Drop leading environment variable assignments like FOO=bar.
        while tokens and re.match(r"^[A-Z_][A-Z0-9_]*=.+$", tokens[0]):
            tokens.pop(0)

        # Drop leading sudo/doas prefixes.
        if tokens and tokens[0] in {"sudo", "doas"}:
            tokens.pop(0)

        # Remove flags that do not affect the core operation for comparison.
        # These include the pager suppression flag and common non‑interactive
        # confirmation flags that users may add to make a command succeed.
        FLAGS_TO_IGNORE = {
            "--no-pager",
            "-y",
            "--yes",
            "--assume-yes",
            "-q",
            "--quiet",
        }
        tokens = [t for t in tokens if t not in FLAGS_TO_IGNORE]

        # Handle systemctl to service conversion for canonical matching
        if tokens and tokens[0] == "systemctl":
            # Basic conversion: systemctl [action] [service] -> service [service] [action]
            # We skip flags for normalization anyway, so just look at the next two tokens.
            if len(tokens) >= 3:
                action = tokens[1]
                service = tokens[2]
                # Filter out flags if tokens[1] starts with -
                if action.startswith("-") and len(tokens) >= 4:
                    action = tokens[2]
                    service = tokens[3]
                
                if action in {"start", "stop", "restart", "status", "reload"}:
                    tokens = ["service", service, action]
                elif action in {"enable", "disable"}:
                    tokens = ["service", service, "start"]

        # For idempotency we only need the primary executable and its first
        # argument (e.g., the package manager command). Keeping the first two
        # tokens prevents false positives while still treating edited commands
        # like "apt-get install -y nginx" and "apt-get install nginx" as the same.
        core_tokens = tokens[:2]
        normalized = " ".join(core_tokens)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized

    def _remaining_plan_commands(
        self, plan: str, execution_log: list[ExecutionStep]
    ) -> list[str]:
        planned = self._extract_plan_commands(plan)
        if not planned:
            return []

        executed = [self._normalize_command(s.command) for s in execution_log]
        remaining: list[str] = []
        for cmd in planned:
            norm = self._normalize_command(cmd)
            if norm and norm in executed:
                continue
            remaining.append(cmd)
        return remaining

    def _build_remaining_plan(self, remaining: list[str]) -> str:
        """Build a minimal plan from remaining commands to continue execution."""
        lines: list[str] = []
        for i, cmd in enumerate(remaining, 1):
            lines.append(f"## {i}. Remaining step")
            lines.append(cmd)
            lines.append("")
        return "\n".join(lines).strip()
