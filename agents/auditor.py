#!/usr/bin/env python3
"""
Auditor Agent: reviews plans for dangerous commands and warns users.
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple
from common_types import ExecutionStep


class AuditorAgent:
    """Reviews execution plans for potentially dangerous commands."""

    def __init__(self, patterns_file: str = "config/dangerous_patterns.txt"):
        """Initialize the Auditor Agent with patterns from file.
        
        Args:
            patterns_file: Path to the file containing dangerous command patterns
        """
        self.patterns_file = patterns_file
        self.compiled_patterns = self._load_patterns()
    
    def _load_patterns(self) -> List[Tuple[re.Pattern, str]]:
        """Load dangerous command patterns from file.
        
        Returns:
            List of tuples (compiled_pattern, description)
        """
        patterns = []
        
        # Default patterns if file doesn't exist
        default_patterns = [
            # File system destruction
            (r'\brm\s+.*-[rf]', "Recursive force delete (rm -rf)"),
            (r'\brm\s+/\s*', "Delete root directory"),
            (r'\brm\s+-\*', "Delete with wildcard"),
            (r'>\s*/dev/(sda|hda|vda|xvd)', "Overwrite disk device"),
            (r'dd\s+.*of=/dev/(sda|hda|vda|xvd)', "DD to disk device"),
            (r'>\s*/dev/(sda|hda|vda|xvd)', "Redirect to disk device"),
            (r'mkfs\.', "Format filesystem"),
            (r'fdisk\s+', "Disk partitioning"),
            (r'parted\s+', "Disk partitioning"),

            # System destruction
            (r'>\s*/etc/passwd', "Overwrite password file"),
            (r'>\s*/etc/shadow', "Overwrite shadow file"),
            (r'>\s*/etc/group', "Overwrite group file"),
            (r'>\s*/etc/sudoers', "Overwrite sudoers file"),
            (r'>\s*/boot/', "Overwrite boot directory"),
            (r'>\s*/lib/', "Overwrite lib directory"),
            (r'>\s*/usr/', "Overwrite usr directory"),
            (r'>\s*/var/', "Overwrite var directory"),

            # Dangerous permissions
            (r'chmod\s+.*777', "World-writable permissions"),
            (r'chmod\s+.*-R\s+.*777', "Recursive world-writable"),
            (r'chown\s+.*-R\s+.*:/', "Recursive chown to root"),

            # Fork bombs and resource exhaustion
            (r':\(\)\{.*\}|:\(\)\{.*\};', "Fork bomb pattern"),
            (r'while\s+true;', "Infinite loop"),
            (r'for\s+.*;.*;.*do', "Potential infinite loop"),

            # Network dangers
            (r'wget\s+.*\|\s*sh', "Download and execute script"),
            (r'curl\s+.*\|\s*sh', "Download and execute script"),
            (r'wget\s+.*\|\s*bash', "Download and execute bash script"),
            (r'curl\s+.*\|\s*bash', "Download and execute bash script"),

            # Privilege escalation risks
            (r'echo\s+.*>>\s*/etc/sudoers', "Modify sudoers"),
            (r'echo\s+.*>>\s*/etc/passwd', "Modify password file"),

            # Service disruption
            (r'systemctl\s+stop\s+.*', "Stop system service"),
            (r'service\s+.*\s+stop', "Stop service"),
            (r'killall\s+', "Kill all processes"),
            (r'pkill\s+', "Kill processes by name"),
            (r'kill\s+-9\s+', "SIGKILL"),
        ]
        
        try:
            if os.path.exists(self.patterns_file):
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        # Skip empty lines and comments
                        if not line or line.startswith('#'):
                            continue
                        
                        # Split by first '###' to separate pattern and description
                        if '###' in line:
                            pattern, description = line.split('###', 1)
                            pattern = pattern.strip()
                            description = description.strip()
                            if pattern and description:
                                try:
                                    compiled_pattern = re.compile(pattern, re.IGNORECASE)
                                    patterns.append((compiled_pattern, description))
                                except re.error as e:
                                    print(f"Warning: Invalid regex pattern on line {line_num}: {pattern} - {e}")
                                    # Use default pattern as fallback
                                    if len(patterns) < len(default_patterns):
                                        patterns.append((re.compile(default_patterns[len(patterns)][0], re.IGNORECASE),
                                                       default_patterns[len(patterns)][1]))
                        else:
                            print(f"Warning: Invalid format on line {line_num}: {line}")
            else:
                print(f"Warning: Patterns file {self.patterns_file} not found, using default patterns")
                patterns = [(re.compile(pattern, re.IGNORECASE), description) 
                           for pattern, description in default_patterns]
        except Exception as e:
            print(f"Warning: Failed to load patterns from {self.patterns_file}: {e}")
            print("Using default patterns")
            patterns = [(re.compile(pattern, re.IGNORECASE), description) 
                       for pattern, description in default_patterns]
        
        return patterns

    def audit_plan(self, plan: str) -> List[Tuple[int, str, str]]:
        """
        Audit a plan for dangerous commands.

        Args:
            plan: The execution plan text to audit

        Returns:
            List of tuples (line_number, command, danger_description) for dangerous commands found
        """
        dangerous_commands = []
        lines = plan.split('\n')

        for i, line in enumerate(lines, 1):
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Extract command from plan line (handle format like "## 1. Description\ncommand")
            command = self._extract_command(stripped)
            if not command:
                continue

            # Check against dangerous patterns
            for pattern_re, description in self.compiled_patterns:
                if pattern_re.search(command):
                    dangerous_commands.append((i, command, description))
                    break  # Only flag once per command

        return dangerous_commands

    def _extract_command(self, line: str) -> str:
        """
        Extract the actual command from a plan line.

        Handles formats like:
        - "sudo apt-get update"
        - "## 1. Update packages\nsudo apt-get update"
        - "1. sudo apt-get update"
        """
        # Remove leading numbers and dots (e.g., "1. ", "## 1. ")
        line = re.sub(r'^[#\d\.]+\s*', '', line)

        # If there's a description before the command (separated by newline or spaces),
        # we want the actual command part
        # For now, return the whole line as it's likely the command
        return line.strip()

    def format_warnings(self, dangerous_commands: List[Tuple[int, str, str]]) -> str:
        """
        Format dangerous commands into a user-friendly warning message.

        Args:
            dangerous_commands: List of (line_number, command, description) tuples

        Returns:
            Formatted warning string
        """
        if not dangerous_commands:
            return ""

        warning = "\n" + "=" * 60
        warning += "\n⚠️  SECURITY AUDIT WARNING: POTENTIALLY DANGEROUS COMMANDS DETECTED"
        warning += "\n" + "=" * 60

        for line_num, command, description in dangerous_commands:
            warning += f"\n\n📍 Line {line_num}: {description}"
            warning += f"\n   Command: {command}"

        warning += "\n\n🛡️  RECOMMENDATION:"
        warning += "\n   Please review these commands carefully."
        warning += "\n   They could cause data loss, system damage, or security risks."
        warning += "\n   Consider modifying the plan or proceeding with extreme caution."
        warning += "\n" + "=" * 60

        return warning