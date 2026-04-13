#!/usr/bin/env python3
"""Test OS information retrieval from Docker containers."""

import sys
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from shell.sandbox import DockerBackend


def test_alpine_os_info():
    """Test OS info retrieval from Alpine container."""
    print("\n" + "=" * 60)
    print("Test 1: Alpine Container OS Info")
    print("=" * 60)
    
    backend = DockerBackend(image="alpine:latest")
    try:
        backend.initialize()
        os_info = backend.get_os_info()
        print(f"Alpine OS Info:\n{os_info}\n")
        print("✅ Alpine OS info retrieved successfully")
    except Exception as e:
        print(f"✗ Failed to get Alpine OS info: {e}")
    finally:
        backend.cleanup()


def test_ubuntu_os_info():
    """Test OS info retrieval from Ubuntu container."""
    print("\n" + "=" * 60)
    print("Test 2: Ubuntu Container OS Info")
    print("=" * 60)
    
    backend = DockerBackend(image="ubuntu:24.04")
    try:
        backend.initialize()
        os_info = backend.get_os_info()
        print(f"Ubuntu OS Info:\n{os_info}\n")
        print("✅ Ubuntu OS info retrieved successfully")
    except Exception as e:
        print(f"✗ Failed to get Ubuntu OS info: {e}")
    finally:
        backend.cleanup()


def test_centos_os_info():
    """Test OS info retrieval from CentOS container."""
    print("\n" + "=" * 60)
    print("Test 3: CentOS Container OS Info")
    print("=" * 60)
    
    backend = DockerBackend(image="centos:7")
    try:
        backend.initialize()
        os_info = backend.get_os_info()
        print(f"CentOS OS Info:\n{os_info}\n")
        print("✅ CentOS OS info retrieved successfully")
    except Exception as e:
        print(f"✗ Failed to get CentOS OS info: {e}")
    finally:
        backend.cleanup()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🐳 Docker Container OS Information Tests")
    print("=" * 60)
    
    # Run tests
    test_alpine_os_info()
    test_ubuntu_os_info()
    test_centos_os_info()
    
    print("\n" + "=" * 60)
    print("✅ All container OS info tests completed!")
    print("=" * 60)
