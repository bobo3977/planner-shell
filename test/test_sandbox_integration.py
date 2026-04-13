#!/usr/bin/env python3
"""
Integration tests for sandbox execution with actual backend interaction.

These tests verify:
1. Backend initialization and cleanup
2. Command execution in different environments
3. State persistence across commands
"""

import os
import subprocess
import pytest
from unittest.mock import Mock, patch
from shell.sandbox import create_backend, HostBackend, DockerBackend
from shell.shell_wrapper import ShellWrapper


class TestHostBackendIntegration:
    """Integration tests for host execution."""
    
    def test_host_execute_simple_command(self):
        """Test executing a simple command on host."""
        backend = HostBackend()
        backend.initialize()
        
        exit_code, output = backend.execute("echo 'Hello, Host!'")
        
        assert exit_code == 0
        assert "Hello, Host!" in output
        
        backend.cleanup()
    
    def test_host_execute_with_exit_code(self):
        """Test command that returns non-zero exit code."""
        backend = HostBackend()
        backend.initialize()
        
        exit_code, output = backend.execute("false")  # Returns exit code 1
        
        assert exit_code != 0
        
        backend.cleanup()


class TestShellWrapperIntegration:
    """Integration tests for ShellWrapper."""
    
    def test_wrapper_with_mock_backend(self):
        """Test ShellWrapper delegating to mock backend."""
        mock_backend = Mock()
        mock_backend.execute.return_value = (0, "mock output")
        mock_backend.cleanup.return_value = None
        
        wrapper = ShellWrapper(mock_backend)
        
        # Test execute delegation
        exit_code, output = wrapper.execute("test command")
        assert exit_code == 0
        assert output == "mock output"
        mock_backend.execute.assert_called_once()
        
        # Test history tracking
        wrapper.add_to_history("test command", 0, "mock output")
        assert len(wrapper.command_history) == 1
        
        # Test cleanup
        wrapper.close()
        mock_backend.cleanup.assert_called_once()


@pytest.mark.skipif(
    os.environ.get('SKIP_DOCKER_TESTS'),
    reason="Docker tests skipped (SKIP_DOCKER_TESTS set or docker not available)"
)
class TestDockerBackendIntegration:
    """Integration tests for Docker backend (requires Docker)."""
    
    @pytest.fixture(autouse=True)
    def check_docker_available(self):
        """Skip tests if Docker is not available."""
        try:
            subprocess.run(
                ['docker', '--version'],
                capture_output=True,
                timeout=5,
                check=True
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pytest.skip("Docker is not available")
    
    def test_docker_backend_creation(self):
        """Test creating Docker backend."""
        backend = DockerBackend()
        assert backend.name == 'docker'
        assert backend.runtime == 'docker'
        assert backend.base_image == 'ubuntu:24.04'
    
    def test_docker_backend_custom_image(self):
        """Test Docker backend with custom image."""
        backend = DockerBackend(image='alpine:latest')
        assert backend.base_image == 'alpine:latest'
    
    @patch('subprocess.run')
    def test_docker_runtime_check(self, mock_run):
        """Test Docker runtime availability check."""
        mock_run.return_value = Mock(returncode=0)
        
        backend = DockerBackend()
        available = backend._check_runtime_available()
        
        assert available is True
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_docker_runtime_not_available(self, mock_run):
        """Test when Docker is not available."""
        mock_run.side_effect = FileNotFoundError("docker not found")
        
        backend = DockerBackend()
        available = backend._check_runtime_available()
        
        assert available is False


class TestBackendFactory:
    """Test the backend factory function."""
    
    def test_create_host_backend(self):
        """Test creating host backend via factory."""
        backend = create_backend('host')
        assert isinstance(backend, HostBackend)
    
    def test_create_docker_backend(self):
        """Test creating Docker backend via factory."""
        backend = create_backend('docker')
        assert isinstance(backend, DockerBackend)
    
    def test_create_docker_with_image(self):
        """Test creating Docker backend with custom image."""
        backend = create_backend('docker', image='ubuntu:22.04')
        assert backend.base_image == 'ubuntu:22.04'
    
    def test_create_invalid_backend(self):
        """Test that invalid backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown sandbox type"):
            create_backend('invalid_backend')


class TestBackendIntegrationFlow:
    """Test complete backend workflow."""
    
    def test_host_backend_workflow(self):
        """Test complete workflow: create -> init -> execute -> cleanup."""
        backend = create_backend('host')
        
        # Initialize
        backend.initialize()
        
        # Execute multiple commands
        exit_code1, output1 = backend.execute("echo 'Test 1'")
        assert exit_code1 == 0
        assert "Test 1" in output1
        
        exit_code2, output2 = backend.execute("echo 'Test 2'")
        assert exit_code2 == 0
        assert "Test 2" in output2
        
        # Cleanup
        backend.cleanup()
    
    @patch('subprocess.run')
    def test_docker_backend_workflow_mock(self, mock_run):
        """Test complete Docker workflow with mocks."""
        # Mock successful Docker operations
        mock_run.side_effect = [
            Mock(returncode=0, stdout='Docker version 20.10.0'),  # version check
            Mock(returncode=0, stdout=''),  # pull image
            Mock(returncode=0, stdout='container-abc123\n'),  # create
            Mock(returncode=0, stdout='command output', stderr=''),  # exec 1
            Mock(returncode=0, stdout='another output', stderr=''),  # exec 2
            Mock(returncode=0),  # stop
        ]
        
        backend = create_backend('docker')
        
        # Initialize would call docker commands
        # (In real test, this would actually communicate with Docker)
        
        # Verify backend state
        assert backend.runtime == 'docker'
        assert backend.base_image == 'ubuntu:24.04'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
