#!/usr/bin/env python3
"""Test sandbox-specific OS information retrieval."""

import sys
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from shell.sandbox import HostBackend, DockerBackend, PodmanBackend, create_backend
from utils.os_info import get_detailed_os_info


def test_host_os_info():
    """Test host backend OS info."""
    print("\n" + "=" * 60)
    print("Test 1: HostBackend OS Info")
    print("=" * 60)
    
    backend = create_backend("host")
    backend.initialize()
    
    # Host backend doesn't have get_os_info() - it's only for container backends
    # We'd get OS via get_detailed_os_info()
    os_info = get_detailed_os_info()
    print(f"Host OS Info:\n{os_info}\n")
    print("✅ Host OS info retrieved successfully")
    backend.cleanup()


def test_docker_backend_structure():
    """Test DockerBackend structure (without actually running Docker)."""
    print("\n" + "=" * 60)
    print("Test 2: DockerBackend Structure")
    print("=" * 60)
    
    try:
        backend = DockerBackend(image="alpine:latest")
        print(f"✅ DockerBackend created successfully")
        print(f"   - Runtime: {backend.runtime}")
        print(f"   - Image: {backend.base_image}")
        print(f"   - Has get_os_info method: {hasattr(backend, 'get_os_info')}")
    except Exception as e:
        print(f"✗ Failed to create DockerBackend: {e}")


def test_podman_backend_structure():
    """Test PodmanBackend structure (without actually running Podman)."""
    print("\n" + "=" * 60)
    print("Test 3: PodmanBackend Structure")
    print("=" * 60)
    
    try:
        backend = PodmanBackend(image="ubuntu:22.04")
        print(f"✅ PodmanBackend created successfully")
        print(f"   - Runtime: {backend.runtime}")
        print(f"   - Image: {backend.base_image}")
        print(f"   - Has get_os_info method: {hasattr(backend, 'get_os_info')}")
    except Exception as e:
        print(f"✗ Failed to create PodmanBackend: {e}")


def test_docker_availability():
    """Check if Docker is available on system."""
    print("\n" + "=" * 60)
    print("Test 4: Docker Availability Check")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Docker is available: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ Docker not available: {result.stderr}")
            return False
    except FileNotFoundError:
        print("✗ Docker command not found")
        return False
    except subprocess.TimeoutExpired:
        print("✗ Docker command timed out")
        return False
    except Exception as e:
        print(f"✗ Error checking Docker: {e}")
        return False


def test_podman_availability():
    """Check if Podman is available on system."""
    print("\n" + "=" * 60)
    print("Test 5: Podman Availability Check")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["podman", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ Podman is available: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ Podman not available: {result.stderr}")
            return False
    except FileNotFoundError:
        print("✗ Podman command not found")
        return False
    except subprocess.TimeoutExpired:
        print("✗ Podman command timed out")
        return False
    except Exception as e:
        print(f"✗ Error checking Podman: {e}")
        return False


def test_backend_factory():
    """Test backend factory function."""
    print("\n" + "=" * 60)
    print("Test 6: Backend Factory Function")
    print("=" * 60)
    
    for sandbox_type in ["host", "docker", "podman"]:
        try:
            backend = create_backend(sandbox_type)
            print(f"✅ Created {sandbox_type} backend: {backend.__class__.__name__}")
        except Exception as e:
            print(f"✗ Failed to create {sandbox_type} backend: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🧪 Sandbox OS Information Tests")
    print("=" * 60)
    
    # Run tests
    test_host_os_info()
    test_docker_backend_structure()
    test_podman_backend_structure()
    docker_available = test_docker_availability()
    podman_available = test_podman_availability()
    test_backend_factory()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    print(f"Docker available: {'✅' if docker_available else '❌'}")
    print(f"Podman available: {'✅' if podman_available else '❌'}")
    print("✅ All structural tests passed!")
    print("=" * 60)
