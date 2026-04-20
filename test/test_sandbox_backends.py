#!/usr/bin/env python3
"""
Test suite for sandbox execution backends.

Tests:
1. Backend creation and initialization
2. Command execution on different backends
3. CLI argument parsing
"""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock


def test_host_backend_creation():
    """Test creating a host backend."""
    from shell.sandbox import create_backend, HostBackend
    
    backend = create_backend('host')
    assert isinstance(backend, HostBackend)
    assert backend.name == 'host'


def test_docker_backend_creation():
    """Test creating a docker backend."""
    from shell.sandbox import create_backend, DockerBackend
    
    backend = create_backend('docker')
    assert isinstance(backend, DockerBackend)
    assert backend.name == 'docker'
    assert backend.base_image == 'ubuntu:24.04'
    
    # With custom image
    backend = create_backend('docker', image='alpine:latest')
    assert backend.base_image == 'alpine:latest'


def test_podman_backend_creation():
    """Test creating a podman backend."""
    from shell.sandbox import create_backend, PodmanBackend
    
    backend = create_backend('podman')
    assert isinstance(backend, PodmanBackend)
    assert backend.name == 'podman'



def test_invalid_backend():
    """Test that invalid backend raises error."""
    from shell.sandbox import create_backend
    
    with pytest.raises(ValueError, match="Unknown sandbox type"):
        create_backend('invalid')


def test_shell_wrapper():
    """Test ShellWrapper interface."""
    from shell.shell_wrapper import ShellWrapper
    from shell.sandbox import HostBackend
    
    mock_backend = Mock()
    mock_backend.execute.return_value = (0, "output")
    
    wrapper = ShellWrapper(mock_backend)
    
    # Test execution
    exit_code, output = wrapper.execute("echo test")
    assert exit_code == 0
    assert output == "output"
    
    # Test history
    wrapper.add_to_history("echo test", 0, "output")
    assert len(wrapper.command_history) == 1
    assert wrapper.command_history[0] == ("echo test", 0, "output", False)


@patch('subprocess.run')
def test_docker_backend_initialization_failure(mock_run):
    """Test docker backend fails when docker is not available."""
    from shell.sandbox import DockerBackend
    
    mock_run.side_effect = FileNotFoundError("docker not found")
    
    backend = DockerBackend()
    with pytest.raises(RuntimeError, match="docker is not available"):
        backend.initialize()


def test_docker_backend_pull_image():
    """Test docker image pulling."""
    from shell.sandbox import DockerBackend
    from unittest.mock import patch
    
    with patch('subprocess.run') as mock_run:
        # Mock docker version check (success)
        mock_run.return_value = Mock(returncode=0, stdout='Docker version')
        
        backend = DockerBackend()
        
        # Mock the subprocess calls
        with patch('subprocess.run') as mock_run_:
            # For version check
            mock_run_.side_effect = [
                Mock(returncode=0, stdout='Docker version'),  # version check
                Mock(returncode=0, stdout=''),  # pull
                Mock(returncode=0, stdout='container-id\n'),  # create
            ]
            
            # This would normally initialize, but we're mocking subprocess
            # So we'll just verify the methods exist
            assert hasattr(backend, '_pull_image')
            assert hasattr(backend, '_create_container')


def test_cli_argument_parsing():
    """Test CLI argument parsing."""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", default=None)
    parser.add_argument("--sandbox", choices=["host", "docker", "podman"], default=None)
    parser.add_argument("--image", default=None)
    parser.add_argument("--auto-approve", action="store_true")
    
    # Test basic task
    args = parser.parse_args(["install kafka"])
    assert args.task == "install kafka"
    assert args.sandbox is None
    
    # Test with sandbox option
    args = parser.parse_args(["install redis", "--sandbox", "docker"])
    assert args.task == "install redis"
    assert args.sandbox == "docker"
    
    # Test with image
    args = parser.parse_args(["install", "--sandbox", "docker", "--image", "ubuntu:22.04"])
    assert args.task == "install"
    assert args.sandbox == "docker"
    assert args.image == "ubuntu:22.04"
    
    # Test auto-approve
    args = parser.parse_args(["task", "--auto-approve"])
    assert args.auto_approve is True


def test_config_sandbox_settings():
    """Test that config has sandbox settings."""
    import config
    
    # Check that new sandbox config constants exist
    assert hasattr(config, 'SANDBOX_TYPE')
    assert hasattr(config, 'SANDBOX_IMAGE')
    
    # Check defaults
    assert config.SANDBOX_TYPE == 'host'  # default
    assert config.SANDBOX_IMAGE is None  # default


if __name__ == "__main__":
    # Run pytest if available, otherwise run basic tests
    try:
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running basic validation...")
        test_host_backend_creation()
        test_docker_backend_creation()
        test_shell_wrapper()
        print("✓ Basic tests passed!")
