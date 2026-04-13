#!/usr/bin/env python3
"""Test shell detection logic."""

from shell.sandbox import DockerBackend, PodmanBackend

# Test Alpine image
print("Testing Alpine image shell detection...")
backend_alpine = DockerBackend(image="alpine:latest")
shell_alpine = backend_alpine._detect_shell()
print(f"  Alpine shell: {shell_alpine}")
assert shell_alpine == "/bin/sh", f"Expected /bin/sh, got {shell_alpine}"
print("  ✓ Alpine shell detection correct")

# Test Ubuntu image
print("\nTesting Ubuntu image shell detection...")
backend_ubuntu = DockerBackend(image="ubuntu:24.04")
shell_ubuntu = backend_ubuntu._detect_shell()
print(f"  Ubuntu shell: {shell_ubuntu}")
assert shell_ubuntu == "/bin/bash", f"Expected /bin/bash, got {shell_ubuntu}"
print("  ✓ Ubuntu shell detection correct")

# Test BusyBox image
print("\nTesting BusyBox image shell detection...")
backend_busybox = DockerBackend(image="busybox:latest")
shell_busybox = backend_busybox._detect_shell()
print(f"  BusyBox shell: {shell_busybox}")
assert shell_busybox == "/bin/sh", f"Expected /bin/sh, got {shell_busybox}"
print("  ✓ BusyBox shell detection correct")

# Test Podman with Alpine
print("\nTesting Podman with Alpine image...")
backend_podman = PodmanBackend(image="alpine:latest")
shell_podman = backend_podman._detect_shell()
print(f"  Podman Alpine shell: {shell_podman}")
assert shell_podman == "/bin/sh", f"Expected /bin/sh, got {shell_podman}"
print("  ✓ Podman Alpine shell detection correct")

print("\n✓ All shell detection tests passed!")
