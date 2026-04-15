#!/usr/bin/env python3
"""
Persistent shell via PTY — maintains a single bash session with state.
"""

from __future__ import annotations

import base64
import os
import re
import select
import signal
import sys
import time
import threading
from typing import Tuple, Optional

import config


class PersistentShell:
    """Maintains a persistent bash process via PTY so cd/export state persists."""
    abort_event: Optional[threading.Event] = None
    command_history: list[tuple[str, int, str, bool]] = []

    def __init__(self) -> None:
        self.process = None
        self.master_fd = None
        self.slave_fd = None
        self.initialize()

    def initialize(self) -> None:
        """Initialize or restart the persistent bash shell."""
        if self.process:
            self.close()

        self.master_fd, self.slave_fd = os.openpty()

        self.process = os.fork()
        if self.process == 0:
            # Child process
            os.close(self.master_fd)
            os.setsid()
            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)
            # Start bash in clean mode to avoid loading .bashrc/.profile which print banners
            os.execvp('/bin/bash', ['/bin/bash', '--norc', '--noprofile', '--noediting'])
            os._exit(1)

        # Parent process
        os.close(self.slave_fd)
        self.slave_fd = None
        self._set_pty_echo(False)

        try:
            # Set up the shell environment silently
            os.write(self.master_fd,
                     b"export PS1=''\nexport PS2=''\nexport PROMPT_COMMAND=''\n"
                     b"export SYSTEMD_PAGER=cat\nexport PAGER=cat\n"
                     b"export LESS=-F\nstty -echo\n")
            # Wait briefly and drain the initial PTY buffer
            time.sleep(0.2)
            self._flush_output(timeout=0.1)
        except OSError:
            pass

        self.forward_stdin = True
        self.abort_event: Optional[threading.Event] = None
        # Command execution history for back functionality
        self.command_history: list[tuple[str, int, str, bool]] = []

    def add_to_history(self, command: str, exit_code: int, output: str, skipped: bool = False) -> None:
        """Add an execution record to history (used for skip and normal execution)."""
        self.command_history.append((command, exit_code, output, skipped))

    # ── internal helpers ──────────────────────────────────────────

    def _set_pty_echo(self, enable: bool) -> None:
        """Toggle echo on the PTY master fd."""
        try:
            import termios as _t
            attrs = _t.tcgetattr(self.master_fd)
            if enable:
                attrs[3] |= _t.ECHO
            else:
                attrs[3] &= ~_t.ECHO
            _t.tcsetattr(self.master_fd, _t.TCSANOW, attrs)
        except (AttributeError, ValueError):
            pass

    def _flush_output(self, timeout: float = 0.05) -> None:
        """Drain any buffered output from the PTY."""
        while True:
            rlist, _, _ = select.select([self.master_fd], [], [], timeout)
            if self.master_fd not in rlist:
                break
            try:
                data = os.read(self.master_fd, 4096)
                if not data:
                    break
            except OSError:
                break

    def interrupt(self) -> None:
        """Send SIGINT (Ctrl+C) to the shell process."""
        if self.master_fd >= 0:
            try:
                os.write(self.master_fd, b'\x03')
            except OSError:
                pass

    # ── public interface ──────────────────────────────────────────

    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute *command* and return (exit_code, output)."""
        if self.abort_event and self.abort_event.is_set():
             return 1, "Execution aborted by user."
        # Check if child process has exited using waitpid with WNOHANG
        try:
            pid, status = os.waitpid(self.process, os.WNOHANG)
            if pid == self.process:
                # Child has exited, restart
                self.restart()
        except ChildProcessError:
            # No child process exists, restart
            self.restart()

        self._flush_output(timeout=0.0)

        # Inject DPkg::Lock::Timeout for apt commands
        original = command
        for apt_cmd in ('apt-get', 'apt install', 'apt update', 'apt upgrade'):
            if apt_cmd in command and 'DPkg::Lock::Timeout' not in command:
                command = command.replace(apt_cmd, f"{apt_cmd} -o DPkg::Lock::Timeout=60", 1)
        if command != original:
            print("\n🔧 Adjusted apt command lock timeout (60s)")

        marker = f"__MARKER_{os.urandom(16).hex()}__"
        eof_marker = f"EOF_{os.urandom(16).hex()}"
        encoded = base64.encodebytes(command.encode()).decode()

        # Payload: run command with echo on, capture exit code, then echo off
        full_cmd = (
            f"export PS1=''; export PROMPT_COMMAND=''; "
            f"stty echo; eval \"$(cat << '{eof_marker}' | base64 --decode\n"
            f"{encoded}{eof_marker}\n"
            f")\"; RET=$?; stty -echo; echo {marker}_$RET\n"
        )
        self._set_pty_echo(False)
        try:
            os.write(self.master_fd, full_cmd.encode())
        except OSError:
            return -1, "Error: Shell process has died."

        output_lines: list[str] = []
        last_line: str = ""  # For progress mode: track the current line being updated
        marker_search_buffer = ""
        exit_code = -1
        start_time = time.time()
        total_output_bytes = 0
        MAX_OUTPUT_BYTES = config.MAX_OUTPUT_BYTES  # Configurable output limit

        # Put stdin into raw/cbreak mode for interactive forwarding
        import termios as _t
        old_tty = None
        input_fd = None
        if self.forward_stdin:
            try:
                input_fd = sys.stdin.fileno()
                if os.isatty(input_fd):
                    old_tty = _t.tcgetattr(input_fd)
                    new_tty = _t.tcgetattr(input_fd)
                    new_tty[3] &= ~(_t.ECHO | _t.ICANON)
                    new_tty[6][_t.VMIN] = 1
                    new_tty[6][_t.VTIME] = 0
                    _t.tcsetattr(input_fd, _t.TCSADRAIN, new_tty)
            except (AttributeError, ValueError, _t.error):
                input_fd = None

        try:
            while True:
                if time.time() - start_time > timeout:
                    self._set_pty_echo(False)
                    self.restart()
                    return -1, f"Execution timed out after {timeout}s. Shell restarted."

                fds = [self.master_fd] + ([input_fd] if input_fd is not None else [])
                rlist, _, _ = select.select(fds, [], [], 0.5)
                marker_found = False

                for fd in rlist:
                    if fd == self.master_fd:
                        try:
                            data = os.read(self.master_fd, 4096)
                        except OSError:
                            break
                        if not data:
                            break

                        data_str = data.decode('utf-8', errors='replace')

                        # Output buffer cap: prevent OOM from runaway commands (find /, yes, dd…)
                        total_output_bytes += len(data)
                        if total_output_bytes > MAX_OUTPUT_BYTES:
                            sys.stdout.buffer.write(
                                b"\n[Output truncated: exceeded 10 MB limit. "
                                b"Sending SIGINT to command.]\n"
                            )
                            sys.stdout.flush()
                            try:
                                os.write(self.master_fd, b'\x03')
                            except OSError:
                                pass
                            output_lines.append(
                                "\n[Output truncated: exceeded 10 MB limit.]\n"
                            )
                            exit_code = 0
                            marker_found = True
                            break

                        # Track a small recent buffer for marker detection across chunks.
                        marker_search_buffer += data_str
                        if len(marker_search_buffer) > 8192:
                            marker_search_buffer = marker_search_buffer[-8192:]

                        # Stream to terminal, hiding the marker line
                        if not silent:
                            if marker in data_str:
                                before = data_str.split(marker)[0]
                                if before:
                                    sys.stdout.buffer.write(before.encode())
                            else:
                                sys.stdout.buffer.write(data)
                            sys.stdout.flush()

                        # Progress mode: track last line without accumulating full output
                        if has_progress:
                            # Normalize CRLF before interpreting bare CR as overwrite.
                            if '\r\n' in data_str:
                                data_str = data_str.replace('\r\n', '\n')
                            # Handle carriage returns: \r returns cursor to line start
                            # Split by \r to get the most recent line content
                            if '\r' in data_str:
                                # Take the last segment after the final \r
                                last_line = data_str.split('\r')[-1]
                            else:
                                # No \r, append to current last_line
                                last_line += data_str
                        else:
                            # Normal mode: accumulate all output (strip \r for clean lines)
                            output_lines.append(data_str.replace('\r', ''))

                        if marker in marker_search_buffer:
                            m = re.search(f"{re.escape(marker)}_([0-9]+)", marker_search_buffer)
                            if m:
                                exit_code = int(m.group(1))
                            if exit_code != -1:
                                # Ctrl+C causes the child to exit with 130 or 131.
                                # Remap to 0 so the agent continues to the next step.
                                if exit_code in (130, 131):
                                    message = (
                                        "\n[Command interrupted by Ctrl+C. "
                                        "Treating as success — proceeding to next step.]\n"
                                    )
                                    if has_progress:
                                        last_line += message
                                    else:
                                        output_lines.append(message)
                                    exit_code = 0
                                if has_progress and marker in last_line:
                                    last_line = re.sub(
                                        f"{re.escape(marker)}_[0-9]+",
                                        "",
                                        last_line,
                                    )
                                marker_found = True
                                break

                    elif fd == input_fd:
                        try:
                            user_input = os.read(input_fd, 1024)
                            if user_input:
                                os.write(self.master_fd, user_input)
                        except OSError:
                            pass

                if marker_found:
                    break

        except KeyboardInterrupt:
            # Safety net: should not normally reach here when _sigint_pty_forward
            # is installed, but provides a fallback in case it isn't.
            try:
                os.write(self.master_fd, b'\x03')
            except OSError:
                pass
            self._flush_output()
            self._set_pty_echo(False)
            return 0, "Command interrupted."

        finally:
            if old_tty is not None and input_fd is not None:
                try:
                    _t.tcsetattr(input_fd, _t.TCSADRAIN, old_tty)
                except _t.error:
                    pass

        if has_progress:
            # Progress mode: return only the last line (stripped of marker and newlines)
            clean = re.sub(
                f"{re.escape(marker)}_[0-9]+",
                "",
                last_line,
            ).replace(marker, '').strip()
        else:
            clean = "\n".join(
                line for line in "".join(output_lines).split('\n') if marker not in line
            )
        # Record this execution in history (not skipped)
        self.command_history.append((command, exit_code, clean.strip(), False))
        return exit_code, clean.strip()

    def close(self) -> None:
        """Close the shell session and terminate the process."""
        if not self.process or self.process <= 0:
            return

        try:
            # 1. Send SIGTERM
            os.kill(self.process, signal.SIGTERM)
            
            # 2. Wait briefly (max 0.5s) for the process to exit
            import time
            start_wait = time.time()
            reaped = False
            while time.time() - start_wait < 0.5:
                try:
                    pid, status = os.waitpid(self.process, os.WNOHANG)
                    if pid == self.process:
                        reaped = True
                        break
                except ChildProcessError:
                    reaped = True
                    break
                time.sleep(0.05)
            
            # 3. Force kill if still alive
            if not reaped:
                try:
                    os.kill(self.process, signal.SIGKILL)
                    # Poll for termination after SIGKILL (should be quick)
                    for _ in range(20):  # max 0.2s
                        try:
                            pid, status = os.waitpid(self.process, os.WNOHANG)
                            if pid == self.process:
                                break
                        except ChildProcessError:
                            break
                        time.sleep(0.01)
                except (OSError, ChildProcessError):
                    pass
        except OSError:
            pass
        finally:
            self.process = None
            # Note: intentionally not closing self.master_fd here to avoid
            # interfering with stdin. The OS will close it when the process exits.

    def restart(self) -> None:
        """Restart the shell after a crash or timeout."""
        self.close()
        self.__init__()
