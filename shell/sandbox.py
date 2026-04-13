#!/usr/bin/env python3
"""
Sandbox execution backends for isolated command execution.

This module provides multiple execution environments:
- HostBackend: Direct execution on host (default, existing behavior)
- DockerBackend: Docker container execution
- PodmanBackend: Podman container execution
- FirecrackerBackend: Firecracker MicroVM execution
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import config


class ExecutionBackend(ABC):
    """Abstract base class for execution backends."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the execution environment."""
        pass

    @abstractmethod
    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute a command and return (exit_code, output)."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Cleanup resources."""
        pass


class HostBackend(ExecutionBackend):
    """Direct host execution using PTY (existing behavior)."""

    def __init__(self) -> None:
        super().__init__("host")
        self.shell = None

    def initialize(self) -> None:
        """Initialize host execution (lazy-load PersistentShell)."""
        from shell.persistent import PersistentShell
        self.shell = PersistentShell()
        print("✓ Host execution backend ready")

    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute command on host using PersistentShell."""
        if self.shell is None:
            raise RuntimeError("Backend not initialized")
        return self.shell.execute(command, timeout=timeout, has_progress=has_progress, silent=silent)

    def cleanup(self) -> None:
        """Cleanup host resources."""
        if self.shell is not None:
            try:
                os.close(self.shell.master_fd)
                os.killpg(os.getpgid(self.shell.process), 9)
            except Exception:
                pass


class ContainerBackend(ExecutionBackend):
    """Base class for container-based backends (Docker, Podman)."""

    def __init__(self, name: str, runtime: str) -> None:
        super().__init__(name)
        self.runtime = runtime  # 'docker' or 'podman'
        self.container_id = None
        self.image_name = None
        self.base_image = None
        self.shell = None

    def _check_runtime_available(self) -> bool:
        """Check if the container runtime is available."""
        try:
            subprocess.run(
                ['sudo', self.runtime, '--version'],
                capture_output=True,
                timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _detect_shell(self) -> str:
        """Detect available shell in the container image."""
        # Infer shell based on image name
        image_lower = self.base_image.lower()
        if 'alpine' in image_lower:
            return '/bin/sh'
        elif 'busybox' in image_lower:
            return '/bin/sh'
        # Default to bash, will try sh as fallback
        return '/bin/bash'

    def _pull_image(self) -> bool:
        """Pull the base image."""
        try:
            print(f"📦 Pulling {self.base_image}...")
            result = subprocess.run(
                ['sudo', self.runtime, 'pull', self.base_image],
                capture_output=True,
                timeout=300,
                text=True
            )
            if result.returncode == 0:
                print(f"✓ Image {self.base_image} ready")
                # Detect shell for this image
                self.shell = self._detect_shell()
                print(f"  Using shell: {self.shell}")
                return True
            else:
                print(f"✗ Failed to pull image: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("✗ Image pull timeout")
            return False
        except Exception as e:
            print(f"✗ Error pulling image: {e}")
            return False

    def _create_container(self) -> bool:
        """Create and start a container."""
        try:
            print(f"🐳 Creating {self.runtime} container...")
            # Try the detected shell first
            shells_to_try = [self.shell]
            if self.shell != '/bin/sh':
                shells_to_try.append('/bin/sh')  # Fallback
            
            for shell in shells_to_try:
                result = subprocess.run(
                    [
                        'sudo', self.runtime, 'run',
                        '-d',  # detached
                        '--rm',  # auto-remove
                        '-i',  # stdin
                        '-e', 'PS1=',
                        '-e', 'PROMPT_COMMAND=',
                        '-e', 'SYSTEMD_PAGER=cat',
                        '-e', 'PAGER=cat',
                        '-e', 'LESS=-F',
                        self.base_image,
                        shell
                    ],
                    capture_output=True,
                    timeout=30,
                    text=True
                )
                if result.returncode == 0:
                    self.container_id = result.stdout.strip()
                    self.shell = shell  # Update to successful shell
                    print(f"✓ Container {self.container_id[:12]} created with {shell}")
                    return True
            
            # All shells failed
            print(f"✗ Failed to create container: {result.stderr}")
            return False
        except subprocess.TimeoutExpired:
            print("✗ Container creation timeout")
            return False
        except Exception as e:
            print(f"✗ Error creating container: {e}")
            return False

    def _execute_in_container(self, command: str) -> Tuple[int, str]:
        """Execute a command inside the container with real-time output."""
        try:
            # Use 'exec' to run command in existing container with real-time output
            process = subprocess.Popen(
                ['sudo', self.runtime, 'exec', self.container_id, self.shell, '-c', command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Collect output while streaming to stdout in real-time
            stdout_lines = []
            stderr_lines = []
            
            # Read stdout line by line
            while True:
                stdout_line = process.stdout.readline()
                if stdout_line == '' and process.poll() is not None:
                    break
                if stdout_line:
                    stdout_lines.append(stdout_line)
                    # Stream to stdout in real-time
                    sys.stdout.write(stdout_line)
                    sys.stdout.flush()
            
            # Read stderr line by line
            while True:
                stderr_line = process.stderr.readline()
                if stderr_line == '' and process.poll() is not None:
                    break
                if stderr_line:
                    stderr_lines.append(stderr_line)
                    # Stream to stderr in real-time
                    sys.stderr.write(stderr_line)
                    sys.stderr.flush()
            
            # Wait for process to complete and get return code
            return_code = process.wait()
            
            return return_code, ''.join(stdout_lines) + ''.join(stderr_lines)
        except subprocess.TimeoutExpired:
            # Kill the process if it times out
            try:
                process.kill()
            except:
                pass
            return -1, "Command execution timeout"
        except Exception as e:
            return -1, f"Error executing command: {e}"

    def initialize(self) -> None:
        """Initialize container backend."""
        if not self._check_runtime_available():
            raise RuntimeError(f"{self.runtime} is not available on this system")
        
        if not self._pull_image():
            raise RuntimeError(f"Failed to prepare {self.base_image}")
        
        if not self._create_container():
            raise RuntimeError("Failed to create container")

    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute command in container."""
        if self.container_id is None:
            raise RuntimeError("Container not initialized")
        
        return self._execute_in_container(command)

    def get_os_info(self) -> str:
        """Get OS information from inside the container."""
        if self.container_id is None:
            raise RuntimeError("Container not initialized")
        
        try:
            # Try to get detailed OS info from container
            result = subprocess.run(
                ['sudo', self.runtime, 'exec', self.container_id, self.shell, '-c',
                 'uname -a && cat /etc/os-release 2>/dev/null || echo "OS info unavailable"'],
                capture_output=True,
                timeout=10,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"{self.name.capitalize()} container ({self.base_image})"
        except Exception as e:
            return f"{self.name.capitalize()} container ({self.base_image}) - {str(e)}"

    def cleanup(self) -> None:
        """Cleanup container."""
        if self.container_id is not None:
            try:
                subprocess.run(
                    ['sudo', self.runtime, 'stop', self.container_id],
                    capture_output=True,
                    timeout=10
                )
            except Exception:
                pass


class DockerBackend(ContainerBackend):
    """Docker-based execution backend."""

    def __init__(self, image: Optional[str] = None) -> None:
        super().__init__("docker", "docker")
        self.base_image = image or "ubuntu:24.04"


class PodmanBackend(ContainerBackend):
    """Podman-based execution backend."""

    def __init__(self, image: Optional[str] = None) -> None:
        super().__init__("podman", "podman")
        self.base_image = image or "docker.io/library/ubuntu:24.04"


class FirecrackerBackend(ExecutionBackend):
    """Firecracker MicroVM-based execution backend."""

    def __init__(self) -> None:
        super().__init__("firecracker")
        self.vm_socket = None
        self.kernel_path = None
        self.rootfs_path = None

    def _check_firecracker_available(self) -> bool:
        """Check if Firecracker is available."""
        try:
            subprocess.run(
                ['firecracker', '--version'],
                capture_output=True,
                timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _prepare_vm_resources(self) -> bool:
        """Prepare VM kernel and rootfs."""
        # This is a placeholder for actual Firecracker setup
        # Real implementation would need kernel and rootfs images
        print("⚠️  Firecracker backend requires kernel and rootfs image setup")
        print("   See: https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md")
        return False

    def initialize(self) -> None:
        """Initialize Firecracker backend."""
        if not self._check_firecracker_available():
            raise RuntimeError("Firecracker is not available on this system")
        
        if not self._prepare_vm_resources():
            raise RuntimeError("Failed to prepare Firecracker resources")

    def execute(self, command: str, timeout: int = 600, has_progress: bool = False, silent: bool = False) -> Tuple[int, str]:
        """Execute command in MicroVM (not yet fully implemented)."""
        raise NotImplementedError("Firecracker backend execution not yet implemented")

    def cleanup(self) -> None:
        """Cleanup VM resources."""
        pass


def create_backend(sandbox_type: str, **kwargs) -> ExecutionBackend:
    """Factory function to create execution backend.
    
    Args:
        sandbox_type: One of 'host', 'docker', 'podman', 'firecracker'
        **kwargs: Additional options for the backend
    
    Returns:
        ExecutionBackend instance
    
    Raises:
        ValueError: If sandbox_type is not recognized
    """
    backends = {
        'host': HostBackend,
        'docker': DockerBackend,
        'podman': PodmanBackend,
        'firecracker': FirecrackerBackend,
    }
    
    if sandbox_type not in backends:
        raise ValueError(f"Unknown sandbox type: {sandbox_type}. Available: {', '.join(backends.keys())}")
    
    backend_class = backends[sandbox_type]
    
    if sandbox_type == 'host':
        backend = backend_class()
    elif sandbox_type == 'docker':
        backend = backend_class(image=kwargs.get('image'))
    elif sandbox_type == 'podman':
        backend = backend_class(image=kwargs.get('image'))
    elif sandbox_type == 'firecracker':
        backend = backend_class()
    
    return backend
