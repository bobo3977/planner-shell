#!/usr/bin/env python3
"""
LangChain tool wrapper for PersistentShell.
"""

from __future__ import annotations

import base64
import os
import shlex
from typing import Any, Optional

from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

from common_types import ExecutionStep, FinishExecutionException, QuitExecutionException, AbortExecutionException
from config import MAX_CONSECUTIVE_FAILURES as CONFIG_MAX_CONSECUTIVE_FAILURES


class ShellInput(BaseModel):
    """Input schema for the shell tool."""
    command: str = Field(description="The bash command to execute in the persistent shell.")


class PersistentShellTool(BaseTool):
    """Execute a bash command in a persistent shell. State (cd, export) is maintained.

    CRITICAL: You MUST use non-interactive flags
    (e.g., DEBIAN_FRONTEND=noninteractive apt-get install -y).
    If a command prompts for human input, it will hang indefinitely.
    """
    name: str = "execute_shell_command"
    description: str = (
        "Execute a bash command in a persistent shell. State (cd, export) is maintained. "
        "CRITICAL: You MUST use non-interactive flags "
        "(e.g., DEBIAN_FRONTEND=noninteractive apt-get install -y). "
        "If a command prompts for human input, it will hang indefinitely."
    )
    args_schema: type[BaseModel] = ShellInput
    shell: Any = Field(exclude=True)  # PersistentShell instance
    # Optional list to collect execution steps for post-run plan refinement.
    execution_log: Optional[list] = Field(default=None, exclude=True)
    # Status of sandbox/container mode
    is_sandbox: bool = Field(default=False)
    # Consecutive failed command counter — reset to 0 on any successful command.
    # When it reaches MAX_CONSECUTIVE_FAILURES the agent is told to stop.
    _consecutive_failures: int = 0
    MAX_CONSECUTIVE_FAILURES: int = CONFIG_MAX_CONSECUTIVE_FAILURES
    # Reference to the Tavily tool so its search counter can be reset on success.
    _tavily_ref: Optional[Any] = None
    # History navigation state: tracks position when using back command
    _history_position: int = -1

    def _stop_spinner(self) -> None:
        """Stop the background spinner thread if it is running and clear the line."""
        from utils.spinner import stop_spinner
        stop_spinner()

    def _start_spinner(self, message: str = "Agent is thinking...") -> None:
        """Start a background spinner that runs until _stop_spinner() is called."""
        from utils.spinner import start_spinner
        start_spinner(message)

    def _run(self, command: str) -> str:
        # Check for immediate abort
        if self.shell.abort_event and self.shell.abort_event.is_set():
            raise AbortExecutionException("Execution aborted by user.")

        # Stop any active spinner (Agent is thinking... or Executing plan...)
        from utils.spinner import stop_spinner
        stop_spinner()
        print("\n" + "=" * 60)
        print("🤖 AI Proposes Command:")
        print("-" * 60)
        print(command.strip())
        print("=" * 60)
        # Store the AI-proposed command for restoration after back/skip
        self._ai_command = command

        # Check for newgrp command - show warning and return to prompt
        if command.strip().startswith('newgrp'):
            print("\n" + "=" * 60)
            print("⚠️  WARNING: 'newgrp' command detected!")
            print("=" * 60)
            print("The 'newgrp' command starts a new shell session which can")
            print("cause terminal display issues and break PTY control.")
            print("")
            print("Recommended alternative:")
            print("  - Use 'sg <group> -c \"<command>\"' to run a command in a new group")
            print("=" * 60)
            print("")
            print("Please edit the command (option 'e') to use the suggested alternative.")
            print("=" * 60)
            print("")

        # ── Prompt loop ───────────────────────────────────────────
        self.shell.forward_stdin = False
        while True:
            # In automated test mode (PLANNER_SHELL_TEST) we bypass the interactive
            # prompt and assume the user accepts the command. This prevents the
            # test suite from hanging on stdin reads.
            if os.getenv("PLANNER_SHELL_TEST"):
                choice = "y"
            else:
                try:
                    from utils.terminal import safe_prompt
                    choice = safe_prompt(
                        "\nExecute this?[Y/y!/n/edit/back/skip/finish/quit] (default: Y): ",
                        default='y',
                        abort_event=self.shell.abort_event
                    ).strip().lower()
                except KeyboardInterrupt:
                    from utils.terminal import restore_terminal
                    restore_terminal()
                    if self.shell.abort_event and self.shell.abort_event.is_set():
                        raise AbortExecutionException("Execution aborted by user.")
                    print("\n\n[!] Interrupted. Returning to prompt...")
                    continue
                except OSError:
                    # When pytest captures stdout/stderr it replaces stdin with a
                    # dummy that raises OSError on read. In that case we assume
                    # the user would accept the command.
                    choice = "y"

            if choice in ('y', 'yes', ''):
                # Reset history navigation when executing a command
                self._history_position = -1
                final_command = command
                break
            if choice in ('e', 'edit'):
                from utils.terminal import edit_in_vim
                final_command = edit_in_vim(command)
                print(f"\n📝 Edited Command:\n{final_command}\n")
                # Reset history navigation when editing a command
                self._history_position = -1
                # Note: the edited command will be executed and recorded in history via execute()
                break
            if choice in ('s', 'skip'):
                print("\n⏭️  Skipping this command (treated as success).")
                if self._history_position == -1:
                    # Normal skip: add to history and return (proceed to next command)
                    self.shell.add_to_history(command, 0, "Command skipped by user.", skipped=False)
                    if self.execution_log is not None:
                        self.execution_log.append(
                            ExecutionStep(command=command, exit_code=0, output="Command skipped by user.")
                        )
                    return ("Exit Code: 0\nSummary: Command skipped by user.\n\n"
                            "NOTE: This command was not executed. Proceeding to next step.")
                else:
                    # Skipping a historical command: mark it as skipped and move to the next non-skipped entry
                    history = self.shell.command_history
                    # Update the skipped flag for this entry
                    cmd, exit_code, output, _ = history[self._history_position]
                    history[self._history_position] = (cmd, exit_code, output, True)
                    
                    # Move to the next (newer) entry: current position + 1
                    self._history_position += 1
                    
                    # Skip over any entries that are already marked as skipped
                    while self._history_position < len(history):
                        _, _, _, skipped = history[self._history_position]
                        if not skipped:
                            break
                        self._history_position += 1
                    
                    # Check where we ended up
                    if self._history_position >= len(history):
                        # All newer entries are skipped (or we were at the end), go back to AI command
                        self._history_position = -1
                        command = self._ai_command
                        print(f"\n[Skipped: {cmd}]\n")
                        print(f"→ No more non-skipped commands. Back to AI command: {command}\n")
                    else:
                        # Get the command at the new position
                        command, _, _, _ = history[self._history_position]
                        print(f"\n[Skipped: {cmd}]\n")
                        print(f"→ Now viewing: {command}\n")
                    
                    # Continue the loop to re-prompt with the new command
                    continue
            if choice in ('b', 'back'):
                # Navigate backwards through command history
                history = self.shell.command_history
                if not history:
                    print("\n⚠️  No command history available to go back to.")
                    continue
                
                # Initialize or decrement history position
                if self._history_position == -1:
                    # First back: start from the most recent command
                    self._history_position = len(history) - 1
                else:
                    # Subsequent back: move to older command
                    self._history_position -= 1
                
                # Check if we've reached the beginning of history
                if self._history_position < 0:
                    print("\n⚠️  Already at the beginning of history.")
                    self._history_position = 0
                    continue
                
                # Get the command at current history position (including skipped ones)
                prev_command, prev_exit_code, prev_output, skipped = history[self._history_position]
                print("\n" + "=" * 60)
                print(f"🔙 History [{self._history_position + 1}/{len(history)}]:")
                print("-" * 60)
                print(prev_command.strip())
                print("=" * 60)
                print(f"Exit code: {prev_exit_code}")
                if skipped:
                    print("⚠️  This command was previously skipped.")
                # Replace the current command with the historical command and re-prompt
                command = prev_command
                print("\n[Review this command. Choose action.]")
                # Continue the loop to show the prompt again with the historical command
                continue
            if choice in ('f', 'finish'):
                print("\n✅ Finishing plan execution (remaining steps will be marked as done).")
                raise FinishExecutionException()
            if choice in ('q', 'quit'):
                print("\n👋 Quitting current execution and returning to task prompt.")
                raise QuitExecutionException()
            if choice in ('n', 'no'):
                from utils.terminal import safe_prompt
                feedback = safe_prompt(
                    "Provide feedback to AI (Why denied? What should it do instead?): "
                )
                # Reset history navigation when denying
                self._history_position = -1
                return (f"Execution DENIED by human. Reason/Feedback: {feedback}. "
                        "Adjust your approach based on this feedback.")
            print("Invalid choice. Please enter y, n, edit, back, skip, finish, or quit.")

        # ── Execute ───────────────────────────────────────────────
        if self.is_sandbox:
            import re
            # Convert systemctl to service for container compatibility
            # Handle start|stop|restart|status|reload
            final_command = re.sub(
                r"systemctl(?:\s+-[a-zA-Z0-9-]+)?\s+(start|stop|restart|status|reload)\s+([a-zA-Z0-9._-]+)",
                r"service \2 \1",
                final_command
            )
            # Handle enable|disable
            final_command = re.sub(
                r"systemctl(?:\s+-[a-zA-Z0-9-]+)?\s+(enable|disable)\s+([a-zA-Z0-9._-]+)",
                r"service \2 start",
                final_command
            )

        final_command = self._add_no_pager_flag(final_command)
        print("\n🚀 Executing...\n")
        self.shell.forward_stdin = True

        try:
            # Detect if command likely shows a progress bar (e.g., ollama pull, docker pull, wget, curl --progress-bar)
            # These use \r to update the same line, which conflicts with PTY output recording.
            has_progress = self._command_has_progress(final_command)
            exit_code, output = self.shell.execute(final_command, has_progress=has_progress)
        except KeyboardInterrupt:
            from utils.terminal import restore_terminal
            restore_terminal()
            print("\n\n[!] Command interrupted. Proceeding to next step...")
            return "Exit Code: 0\nSummary: Command interrupted by user. Proceeding to next step."

        # Record this step in the execution log when logging is enabled
        if self.execution_log is not None:
            self.execution_log.append(
                ExecutionStep(command=final_command, exit_code=exit_code, output=output)
            )

        # NOTE: The raw output and exit code were previously printed here,
        # which caused duplicate display because the surrounding framework
        # also shows the returned `result_str` (which includes a summary of
        # the output). The explicit prints have been removed to avoid the
        # duplication after the "🚀 Executing..." banner.

        summarized = self._summarize_output(output, exit_code)
        # Return a result string that includes both the explicit exit code line and the
        # bracketed form used by the UI. This satisfies callers that look for the plain
        # "Exit Code: X" line while still providing the familiar "[Exit Code: X]" suffix.
        # Return a result string that includes only the summary and a single bracketed
        # exit‑code line. This satisfies the requirement to show "[Exit Code: X]" once.
        result_str = f"Summary:\n{summarized}\n[Exit Code: {exit_code}]"

        if exit_code != 0:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                msg = (
                    f"\n⛔ Consecutive failure limit reached "
                    f"({self.MAX_CONSECUTIVE_FAILURES} commands failed in a row). "
                    "Stop execution and report the unresolved issue."
                )
                print(msg)
                result_str += msg
            else:
                result_str += (
                    f"\n\nCRITICAL: Command failed! "
                    f"(consecutive failures: {self._consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES}) "
                    "Analyze the error output above. "
                    "Use the Tavily Search tool if needed, then propose a fix."
                )
        else:
            # Success — reset both counters
            self._consecutive_failures = 0
            if self._tavily_ref is not None:
                self._tavily_ref.reset_search_count()

        print(f"[Exit {exit_code}]")
        # Start a background spinner that keeps running until the next command is proposed.
        self._start_spinner("Agent is thinking...")
        return result_str

    def _add_no_pager_flag(self, command: str) -> str:
        """Prepend --no-pager to systemd commands that invoke a pager by default."""
        PAGER_CMDS = {
            'systemctl', 'journalctl', 'loginctl', 'coredumpctl', 'machinectl',
            'busctl', 'networkctl', 'resolvectl', 'timedatectl', 'hostnamectl',
            'localectl', 'userctl',
        }
        PREFIXES = {'sudo', 'doas'}
        OPTS_WITH_ARG = {'-u', '--user', '-g', '--group', '-h', '--host', '-p', '--prompt'}

        parts = command.split()
        if not parts:
            return command

        i = 0
        while i < len(parts):
            p = parts[i].lower()
            if p in PREFIXES:
                i += 1
            elif p.startswith('-'):
                i += 1
                if p in OPTS_WITH_ARG:
                    i += 1
            else:
                break

        if i >= len(parts):
            return command

        base_cmd = parts[i].split('/')[-1].lower()
        if base_cmd in PAGER_CMDS and '--no-pager' not in parts:
            parts.insert(i + 1, '--no-pager')
            return ' '.join(parts)
        return command

    def _command_has_progress(self, command: str) -> bool:
        """Check if the command likely displays a progress bar that uses \\r for updates."""
        # Normalize command for case-insensitive matching
        cmd_lower = command.lower().strip()
        
        # Direct command matches that show progress bars
        PROGRESS_COMMANDS = {
            'ollama pull', 'ollama push',
            'docker pull', 'docker push', 'docker build',
            'wget', 'curl --progress-bar', 'curl -#',
            'rsync --progress', 'rsync -p',
            'apt-get install', 'apt install', 'apt upgrade', 'apt update',
            'yum install', 'yum update',
            'pip install', 'pip download',
            'npm install', 'yarn install', 'pnpm install',
            'cargo install', 'cargo build',
            'go get', 'go mod download',
            'make -j', 'make --jobs',
            'git clone', 'git fetch', 'git pull',
            'kubectl apply -f', 'kubectl create -f',
            'helm install', 'helm upgrade',
        }
        
        # Check for exact prefix matches
        for prog_cmd in PROGRESS_COMMANDS:
            if cmd_lower.startswith(prog_cmd):
                return True
        
        # Check for progress-related flags (all lowercase for case-insensitive matching)
        PROGRESS_FLAGS = {'--progress', '--progress-bar', '-p', '--show-progress', '-#', '--verbose'}
        if any(flag in cmd_lower for flag in PROGRESS_FLAGS):
            return True
        
        return False

    def _summarize_output(self, output: str, exit_code: int, max_lines: int = 10) -> str:
        """Truncate long output, keeping head and tail, to limit LLM token usage."""
        if not output:
            return "(No output)"
        lines = output.split('\n')
        if len(lines) <= max_lines * 2:
            return output
        keep = max_lines // 2
        summary = '\n'.join(lines[:keep])
        summary += f"\n...[truncated {len(lines) - max_lines} lines] ...\n"
        summary += '\n'.join(lines[-keep:])
        prefix = "SUCCESS (exit 0)" if exit_code == 0 else f"FAILED (exit {exit_code})"
        return f"{prefix}. Output:\n{summary}"


class VerifyStateInput(BaseModel):
    """Input schema for the verify_state tool."""
    command: str = Field(description="The read-only bash command to execute to verify the state (e.g., 'dpkg -l | grep nginx', 'systemctl is-active redis').")


class VerifyStateTool(BaseTool):
    """Silently run a read-only command to check if a step's goal is already met."""
    name: str = "verify_state"
    description: str = (
        "Silently execute a read-only bash command to check the current system state "
        "(e.g., check if a package is installed, a file exists, or a service is running). "
        "Returns the exit code and output. This command does NOT ask the user for permission, "
        "so it MUST be strictly read-only and free of side-effects."
    )
    args_schema: type[BaseModel] = VerifyStateInput
    shell: Any = Field(exclude=True)  # PersistentShell instance

    def _run(self, command: str) -> str:
        if self.shell.abort_event and self.shell.abort_event.is_set():
            raise AbortExecutionException("Execution aborted by user.")
        print(f"\n🔍 [State Verification] Running: {command.strip()}", flush=True)
        # Disable stdin forwarding for silent background execution
        original_forward = self.shell.forward_stdin
        self.shell.forward_stdin = False
        try:
            exit_code, output = self.shell.execute(command, silent=True)
            if exit_code == 0:
                print(f"✅ State verified (Exit 0): Condition already met.")
            else:
                print(f"❌ State pending (Exit {exit_code}).")
        finally:
            self.shell.forward_stdin = original_forward

        summary = (
            f"Exit Code: {exit_code}\nOutput:\n{output}\n\n"
            f"If Exit Code is 0, the state is satisfied. If you decide to skip the next plan step based on this, "
            f"you MUST output a message explaining it."
        )
        return summary


# ─────────────────────────────────────────────────────────────────────────────
# FileEditorTool — safe file read/write/append/str_replace
# ─────────────────────────────────────────────────────────────────────────────

class FileEditorInput(BaseModel):
    """Input schema for the file_editor tool."""
    action: str = Field(
        description=(
            "The file operation to perform. Must be one of:\n"
            "  'read'        — Read and return the entire file content.\n"
            "  'write'       — Overwrite the file with 'content' (creates if not exists).\n"
            "  'append'      — Append 'content' to the end of the file.\n"
            "  'str_replace' — Replace the first occurrence of 'old_str' with 'new_str' in the file."
        )
    )
    path: str = Field(
        description=(
            "Path to the target file. Use the SAME path you use in shell commands: "
            "'~/project/file' expands to $HOME, or an absolute path. "
            "Do not use placeholder homes like '/home/user/...' unless that is literally your HOME."
        )
    )
    content: Optional[str] = Field(
        default=None,
        description="File content to write or append. Required for 'write' and 'append' actions."
    )
    old_str: Optional[str] = Field(
        default=None,
        description="The exact string to find and replace. Required for 'str_replace' action."
    )
    new_str: Optional[str] = Field(
        default=None,
        description="The replacement string. Required for 'str_replace' action."
    )
    use_sudo: bool = Field(
        default=False,
        description="Set to true if the file requires root permissions (e.g., /etc/... files)."
    )


class FileEditorTool(BaseTool):
    """Safely read, write, append, or str_replace content in a file.

    Modification actions (write/append/str_replace) show a clear human-readable
    preview and require explicit user approval before execution, just like
    execute_shell_command. Use this instead of sed/awk/cat<<EOF for file edits.
    """
    name: str = "file_editor"
    description: str = (
        "Safely read, write, append, or replace content in a file. "
        "PREFER this over shell commands like sed/awk/cat<<EOF for file modifications, "
        "as it handles quoting and escaping correctly. "
        "Actions: 'read', 'write', 'append', 'str_replace'. "
        "Modification actions require human approval before execution."
    )
    args_schema: type[BaseModel] = FileEditorInput
    shell: Any = Field(exclude=True)  # PersistentShell instance

    def _run(
        self,
        action: str,
        path: str,
        content: Optional[str] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        use_sudo: bool = False,
    ) -> str:
        if self.shell.abort_event and self.shell.abort_event.is_set():
            raise AbortExecutionException("Execution aborted by user.")
        action = action.strip().lower()
        VALID_ACTIONS = ("read", "write", "append", "str_replace")
        if action not in VALID_ACTIONS:
            return f"Error: Unknown action '{action}'. Must be one of: {', '.join(VALID_ACTIONS)}."

        # ── READ (no approval needed) ──────────────────────────────
        if action == "read":
            prefix = "sudo " if use_sudo else ""
            path = os.path.normpath(os.path.expanduser(path.strip()))
            cmd = f"{prefix}cat {shlex.quote(path)}"
            exit_code, output = self.shell.execute(cmd, silent=True)
            if exit_code != 0:
                return f"Error reading '{path}' (exit {exit_code}):\n{output}"
            return f"Content of '{path}':\n{output}"

        # ── Validate inputs for write/append/str_replace ───────────
        if action in ("write", "append") and content is None:
            return f"Error: 'content' is required for '{action}' action."
        if action == "str_replace" and (old_str is None or new_str is None):
            return "Error: 'old_str' and 'new_str' are required for 'str_replace' action."

        # ── Build preview for human approval ──────────────────────
        print("\n" + "=" * 60)
        print("📝 AI Proposes File Edit:")
        print("-" * 60)
        print(f"Action : {action}")
        print(f"Path   : {path}")
        if action in ("write", "append"):
            print(f"Content:\n{content}")
        elif action == "str_replace":
            print(f"Find   :\n{old_str}")
            print(f"Replace:\n{new_str}")
        print("=" * 60)

        # ── Approval prompt + execute (restore tty / stdin forwarding after) ──
        from utils.terminal import restore_terminal

        self.shell.forward_stdin = False
        try:
            while True:
                try:
                    from utils.terminal import safe_prompt
                    choice = safe_prompt(
                        "\nExecute this file edit?[Y/y!/n/skip/quit] (default: Y): ",
                        default="y",
                        abort_event=self.shell.abort_event
                    ).strip().lower()
                except KeyboardInterrupt:
                    restore_terminal()
                    if self.shell.abort_event and self.shell.abort_event.is_set():
                        raise AbortExecutionException("Execution aborted by user.")
                    print("\n\n[!] Interrupted. Returning to prompt...")
                    continue

                if choice in ("y", "yes", ""):
                    break
                if choice in ("s", "skip"):
                    return "File edit skipped by user."
                if choice in ("n", "no"):
                    from utils.terminal import safe_prompt as _sp
                    feedback = _sp("Provide feedback (why denied?): ")
                    return f"File edit DENIED by human. Reason: {feedback}. Adjust your approach."
                if choice in ("q", "quit"):
                    from common_types import QuitExecutionException
                    raise QuitExecutionException()
                print("Invalid choice. Enter y, n, skip, or quit.")

            # ── Execute the file operation ─────────────────────────────
            prefix = "sudo " if use_sudo else ""
            resolved = os.path.normpath(os.path.expanduser(path.strip()))

            def _write_or_append_cmd(target: str, body: str, append: bool) -> str:
                """Create a command that writes *body* to *target*.

                The original implementation relied on ``python3`` being available
                inside the sandbox container. In sandbox mode the container may
                lack a Python interpreter, causing the file edit to fail with
                ``sudo: python3: command not found``. To make the tool robust we
                now detect whether ``python3`` exists and fall back to a pure
                shell solution that uses ``base64`` and ``tee`` – tools that are
                guaranteed to be present in minimal Linux images.

                The fallback works by base64‑encoding the content, echoing the
                encoded string, decoding it with ``base64 -d`` and writing the
                result via ``tee`` (or ``tee -a`` for append). ``tee`` creates the
                parent directories when combined with ``mkdir -p``.
                """
                # First, check if python3 is available in the container.
                check_cmd = f"{prefix}command -v python3"
                exit_code, _ = self.shell.execute(check_cmd, silent=True)
                if exit_code == 0:
                    # Python is available – keep the original fast path.
                    b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
                    mode = "a" if append else "w"
                    script = (
                        "import base64,os;"
                        f"p={repr(target)};"
                        "d=os.path.dirname(p);"
                        "(os.makedirs(d, exist_ok=True) if d else None);"
                        f"open(p,{repr(mode)},encoding='utf-8').write(base64.b64decode({repr(b64)}).decode('utf-8'))"
                    )
                    return f"{prefix}python3 -c {shlex.quote(script)}"
                else:
                    # Python not present – use base64 + tee.
                    b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
                    tee_flag = "-a" if append else ""
                    # Ensure parent directory exists.
                    dir_cmd = f"{prefix}mkdir -p $(dirname {shlex.quote(target)})"
                    # The actual write command.
                    write_cmd = (
                        f"echo {shlex.quote(b64)} | base64 -d | {prefix}tee {tee_flag} {shlex.quote(target)} > /dev/null"
                    )
                    # Chain the two commands with && so the directory is created first.
                    return f"{dir_cmd} && {write_cmd}"

            if action == "write":
                cmd = _write_or_append_cmd(resolved, content or "", append=False)
            elif action == "append":
                cmd = _write_or_append_cmd(resolved, content or "", append=True)
            elif action == "str_replace":
                py_script = (
                    "import sys\n"
                    "path = sys.argv[1]\n"
                    "old = sys.argv[2]\n"
                    "new = sys.argv[3]\n"
                    "text = open(path, encoding='utf-8').read()\n"
                    "if old not in text:\n"
                    "    print(f'Error: old_str not found in {path}', file=sys.stderr)\n"
                    "    sys.exit(1)\n"
                    "open(path, 'w', encoding='utf-8').write(text.replace(old, new, 1))\n"
                    "print('str_replace OK')\n"
                )
                py_cmd = (
                    f"python3 -c {shlex.quote(py_script)} "
                    f"{shlex.quote(resolved)} {shlex.quote(old_str)} {shlex.quote(new_str)}"
                )
                cmd = f"{prefix}{py_cmd}" if use_sudo else py_cmd

            print("\n✏️  Applying file edit...\n")
            exit_code, output = self.shell.execute(cmd, silent=True)
            if exit_code == 0:
                print(f"✅ File edit applied: {action} → {resolved}")
                return f"Success: '{action}' on '{resolved}' completed."
            print(f"❌ File edit failed (exit {exit_code})")
            err = output.strip()
            if err:
                print(err)
            return (
                f"Error: '{action}' on '{resolved}' failed (exit {exit_code}):\n{output}"
            )
        finally:
            restore_terminal()
            self.shell.forward_stdin = True
