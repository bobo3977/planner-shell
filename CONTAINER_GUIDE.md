# Container & Sandbox Execution - Quick Start Guide

## Overview

planner-shell now supports isolated **containerized execution** through multiple backends:
- **Host** (default) - Direct execution on your machine
- **Docker** - Isolated Docker containers
- **Podman** - Rootless container alternative  
- **Firecracker** (experimental) - Lightweight MicroVM isolation

This guide shows how to use and test each mode.

## Installation

### 1. Install Docker (Optional - for Docker backend)

```bash
# Ubuntu/Debian
sudo apt-get install docker.io

# Start Docker daemon
sudo systemctl start docker
sudo usermod -aG docker $USER  # Run without sudo (requires re-login)

# Verify installation
docker --version
```

### 2. Install Podman (Optional - for Podman backend)

```bash
# Ubuntu/Debian
sudo apt-get install podman

# Verify installation
podman --version
```

### 3. Install Firecracker (Optional - for MicroVM backend)

```bash
# Ubuntu/Debian (complex setup, see official docs)
# https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md
```

## Environment Configuration

### Set Default Backend

```bash
# In .env file or shell before running planner-shell

# Use Docker by default
export SANDBOX_TYPE=docker

# Use Podman by default
export SANDBOX_TYPE=podman

# Use host execution (default)
export SANDBOX_TYPE=host

# Custom base image for containers
export SANDBOX_IMAGE=ubuntu:22.04
```

### Example .env File

```env
# Required: LLM configuration
OPENAI_API_KEY=your_key_here

# Optional: Default sandbox mode
SANDBOX_TYPE=host  # or docker, podman, firecracker

# Optional: Container image
SANDBOX_IMAGE=ubuntu:24.04
```

## Usage Examples

### 1. Host Execution (No Isolation)

```bash
# Default behavior - runs directly on host
planner-shell "install nginx"

# Explicitly specify host
planner-shell "install nginx" --sandbox host

# ⚠️ WARNING: Can modify your system
```

### 2. Docker Execution (Isolated & Safe)

```bash
# Run in Ubuntu 24.04 container (default)
planner-shell "install nginx" --sandbox docker

# Use custom image
planner-shell "install node" --sandbox docker --image node:18

# Alpine image (lighter)
planner-shell "install python3" --sandbox docker --image alpine:latest

# Example: Safely test destructive commands
planner-shell "rm -rf /*" --sandbox docker  # ← Safe! Only destroys container
```

### 3. Podman Execution (Rootless Alternative)

```bash
# Run in Podman container (no daemon, rootless)
planner-shell "install postgresql" --sandbox podman

# Custom image
planner-shell "setup database" --sandbox podman --image alpine:latest
```

### 4. Firecracker Execution (MicroVM - Experimental)

```bash
# Run in Firecracker MicroVM (requires kernel/rootfs setup)
planner-shell "install redis" --sandbox firecracker

# ⚠️ Note: Not fully implemented - requires manual preparation
```

## Architecture

### Backend System

```
CLI Arguments
    ↓
--sandbox {host|docker|podman|firecracker}
--image ubuntu:24.04
    ↓
ExecutionBackend Factory (create_backend)
    ↓
┌────────────────────────────────────────┐
│  ExecutionBackend (Abstract Base)      │
│  ├─ initialize()                       │
│  ├─ execute(command, timeout, ...)     │
│  └─ cleanup()                          │
└────────────────────────────────────────┘
    ↓
┌──────────────┬──────────────┬──────────────┬─────────────────┐
│ HostBackend  │ DockerBackend│ PodmanBackend│ FirecrackerBack │
└──────────────┴──────────────┴──────────────┴─────────────────┘
    ↓
ShellWrapper (for non-host backends)
    ↓
PersistentShell Interface
    ↓
ExecutorAgent
```

### File Structure

```
shell/
├── sandbox.py              # Execution backends
│   ├── ExecutionBackend (abstract)
│   ├── HostBackend
│   ├── ContainerBackend (base)
│   ├── DockerBackend
│   ├── PodmanBackend
│   ├── FirecrackerBackend
│   └── create_backend(type, **kwargs)
├── shell_wrapper.py        # Container backend wrapper
│   └── ShellWrapper
└── persistent.py           # Original host execution

config/
└── config.py
    ├── SANDBOX_TYPE = "host"
    └── SANDBOX_IMAGE = "ubuntu:24.04"

main.py
└── --sandbox argument handling
```

## Implementation Details

### How HostBackend Works

```python
# Uses existing PersistentShell
backend = create_backend('host')
backend.initialize()
exit_code, output = backend.execute("echo test")
backend.cleanup()
```

### How DockerBackend Works

```python
# Creates isolated container for each session
backend = create_backend('docker', image='ubuntu:24.04')
backend.initialize()  # Pulls image, creates container

# Commands execute in same container
exit_code, output = backend.execute("apt-get update")
exit_code, output = backend.execute("apt-get install nginx")

backend.cleanup()  # Removes container
```

### How PodmanBackend Works

```python
# Identical to Docker, uses podman binary instead
backend = create_backend('podman', image='ubuntu:24.04')
backend.initialize()  # Creates container (rootless)
exit_code, output = backend.execute("echo test")
backend.cleanup()
```

## Testing

### Run Backend Tests

```bash
cd /home/bobo/planner-shell
python3 test_sandbox_modes.py
```

Expected output:
```
✓ HOST: Backend created successfully
✓ DOCKER: Backend created successfully
✓ PODMAN: Backend created successfully
✓ Host backend initialized
✓ Command executed: exit_code=0
✓ Invalid backend error handling works
```

## Benefits of Each Mode

| Feature | Host | Docker | Podman | Firecracker |
|---------|------|--------|--------|-------------|
| Host Protection | ❌ | ✅ | ✅ | ✅ |
| Performance | ✅ | ⚠️ | ⚠️ | ✅ |
| Setup Effort | ✅ | ⚠️ | ⚠️ | ❌ |
| Container Source | N/A | Docker Hub | Registries | Custom |
| Root Required | ❌ | ⚠️* | ✅ | ✅ |

*Docker requires root or user in docker group

## Troubleshooting

### Docker: Permission Denied

```bash
# Solution 1: Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Solution 2: Use sudo
sudo planner-shell "task" --sandbox docker
```

### Podman: Image Not Found

```bash
# Ensure podman image is available
podman pull docker.io/library/ubuntu:24.04

# Custom registry
planner-shell "task" --sandbox podman --image quay.io/fedora/fedora
```

### Docker/Podman: Slow First Run

```bash
# First run pulls the image - this is slow (5-30 seconds)
# Subsequent runs reuse the image (fast)

# Pre-pull image to avoid delay
docker pull ubuntu:24.04
```

## Future Enhancements

- [ ] Persistent container mode (reuse container across commands)
- [ ] Container volume mounting for code injection
- [ ] Multi-container networking (service dependencies)
- [ ] Firecracker full implementation (kernel/rootfs)
- [ ] Health checks and automatic restart
- [ ] Resource limits (CPU, memory, disk)

## References

- [Docker Documentation](https://docs.docker.com/)
- [Podman Documentation](https://podman.io/)
- [Firecracker Documentation](https://github.com/firecracker-microvm/firecracker/blob/main/docs/index.md)
- [planner-shell README](../README.md)
- [SANDBOX.md Implementation Guide](./SANDBOX.md)
