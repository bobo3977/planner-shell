#!/usr/bin/env python3
"""
Test for newgrp command warning detection in PersistentShellTool.
"""

import pytest
from unittest.mock import patch, MagicMock
from shell.persistent import PersistentShell
from shell.tool import PersistentShellTool


def _mock_persistent_shell_init(self):
    self.master_fd = 999
    self.slave_fd = 998
    self.process = 12345
    self.forward_stdin = False
    self.command_history = []


def test_newgrp_warning_displayed(capsys):
    """Test that newgrp command triggers a warning message in PersistentShellTool."""
    # Mock PersistentShell to avoid actual execution
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "test output")
        mock_prompt.return_value = 'y'  # Simulate user pressing Y
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "newgrp docker"
        
        result = tool._run(command)
        
        captured = capsys.readouterr()
        
        # Verify warning is displayed
        assert "⚠️  WARNING: 'newgrp' command detected!" in captured.out
        assert "terminal display issues" in captured.out
        assert "break PTY control" in captured.out
        assert "sg" in captured.out
        assert "Recommended alternative:" in captured.out
        assert "Please edit the command" in captured.out


def test_non_newgrp_no_warning(capsys):
    """Test that non-newgrp commands do not trigger the warning."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "test output")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "echo 'hello'"
        result = tool._run(command)
        
        captured = capsys.readouterr()
        assert "newgrp" not in captured.out


def test_newgrp_with_leading_spaces(capsys):
    """Test that newgrp with leading spaces still triggers warning."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "test output")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "   newgrp docker"
        result = tool._run(command)
        
        captured = capsys.readouterr()
        assert "⚠️  WARNING: 'newgrp' command detected!" in captured.out


def test_newgrp_with_sudo(capsys):
    """Test that sudo newgrp does NOT trigger warning (current behavior)."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "test output")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "sudo newgrp docker"
        result = tool._run(command)
        
        captured = capsys.readouterr()
        # The command itself contains "newgrp" but the warning should NOT be displayed
        # Check for the specific warning message, not just the word "newgrp"
        assert "WARNING: 'newgrp' command detected!" not in captured.out
        assert "terminal display issues" not in captured.out


def test_ollama_pull_progress_detection(capsys):
    """Test that ollama pull command triggers has_progress mode."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "pulling manifest")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "ollama pull llama2"
        result = tool._run(command)
        
        # Verify execute was called with has_progress=True
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert call_args[1].get('has_progress') is True
        
        # Verify normal output is still shown (not suppressed)
        captured = capsys.readouterr()
        assert "ollama pull" in captured.out or "Executing" in captured.out


def test_docker_pull_progress_detection(capsys):
    """Test that docker pull command triggers has_progress mode."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "Download complete")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "docker pull ubuntu:latest"
        result = tool._run(command)
        
        # Verify execute was called with has_progress=True
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert call_args[1].get('has_progress') is True


def test_normal_command_no_progress(capsys):
    """Test that normal commands do not trigger has_progress mode."""
    with patch.object(PersistentShell, '__init__', _mock_persistent_shell_init), \
         patch.object(PersistentShell, 'execute') as mock_execute, \
         patch('utils.terminal.safe_prompt') as mock_prompt:
        
        mock_execute.return_value = (0, "test output")
        mock_prompt.return_value = 'y'
        
        shell = PersistentShell()
        tool = PersistentShellTool(shell=shell)
        command = "ls -la"
        result = tool._run(command)
        
        # Verify execute was called with has_progress=False (default)
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        assert call_args[1].get('has_progress') is False


def test_command_has_progress_detection():
    """Test _command_has_progress correctly identifies progress bar commands."""
    from shell.tool import PersistentShellTool
    
    # Create a mock shell (we only need the method)
    class MockShell:
        pass
    
    tool = PersistentShellTool(shell=MockShell())
    
    # Test commands that should be detected
    progress_commands = [
        "ollama pull llama2",
        "ollama push codellama",
        "docker pull ubuntu:latest",
        "docker push myimage:tag",
        "docker build -t myapp .",
        "wget https://example.com/file.zip",
        "curl --progress-bar https://example.com",
        "curl -# https://example.com",
        "rsync --progress /src /dst",
        "rsync -P /src /dst",
        "apt-get install python3",
        "apt install vim",
        "apt upgrade",
        "apt update",
        "yum install httpd",
        "yum update",
        "pip install requests",
        "pip download numpy",
        "npm install express",
        "yarn install",
        "pnpm install",
        "cargo install ripgrep",
        "cargo build --release",
        "go get github.com/some/pkg",
        "go mod download",
        "make -j4",
        "make --jobs=8",
        "git clone https://github.com/user/repo.git",
        "git fetch origin",
        "git pull",
        "kubectl apply -f deployment.yaml",
        "kubectl create -f pod.yaml",
        "helm install myapp ./chart",
        "helm upgrade myapp ./chart",
    ]
    
    for cmd in progress_commands:
        assert tool._command_has_progress(cmd), f"Should detect progress: {cmd}"
    
    # Test commands that should NOT be detected
    normal_commands = [
        "ls -la",
        "echo 'hello'",
        "pwd",
        "cat file.txt",
        "grep 'pattern' file.txt",
        "find . -name '*.py'",
        "ps aux",
        "df -h",
        "free -m",
        "top -n1",
    ]
    
    for cmd in normal_commands:
        assert not tool._command_has_progress(cmd), f"Should NOT detect progress: {cmd}"
    
    # Test flag-based detection
    assert tool._command_has_progress("somecommand --progress")
    assert tool._command_has_progress("somecommand --progress-bar")
    assert tool._command_has_progress("somecommand -P")
    assert tool._command_has_progress("somecommand --show-progress")
    assert tool._command_has_progress("somecommand -#")
    assert tool._command_has_progress("somecommand --verbose")
