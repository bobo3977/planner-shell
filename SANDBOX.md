# Container & Sandbox Execution - Implementation Guide

## Overview

このドキュメントでは、planner-shell の新しいコンテナ実行モード（Sandbox機能）について説明します。

## Architecture

### Execution Backend System

```
┌─────────────────────────────────────────────┐
│         CLI Entry Point (main.py)           │
│  --sandbox {host|docker|podman|firecracker} │
└──────────────────┬──────────────────────────┘
                   │
                   │ Backend Factory
                   ▼
        ┌──────────────────────┐
        │ ExecutionBackend     │
        │  (Abstract Base)     │
        └──────────────────────┘
                   ▲
        ┌──────────┼──────────┬───────────┐
        │          │          │           │
        ▼          ▼          ▼           ▼
    ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
    │ Host   │ │ Docker │ │ Podman │ │Firecracker   │
    │Backend │ │Backend │ │Backend │ │Backend       │
    │(PTY)   │ │        │ │        │ │(MicroVM)     │
    └────────┘ └────────┘ └────────┘ └──────────────┘
        │          │          │           │
        └──────────┼──────────┴───────────┘
                   │
         ┌─────────▼──────────┐
         │  ShellWrapper      │
         │(Interface Bridge)  │
         └────────┬───────────┘
                  │
         ┌────────▼──────────┐
         │ ExecutorAgent     │
         │ PersistentShellTool
         └───────────────────┘
```

### Core Components

#### 1. **ExecutionBackend** (Abstract Base Class)
- **Location**: `shell/sandbox.py`
- **Interface**:
  - `initialize()`: Set up execution environment
  - `execute(command, timeout, has_progress, silent)`: Run command
  - `cleanup()`: Clean up resources

#### 2. **HostBackend** (Existing Behavior)
```python
# Direct PTY-based execution on host
backend = create_backend('host')
backend.initialize()
exit_code, output = backend.execute("echo test")
```
- Uses existing `PersistentShell` implementation
- Maintains state across commands (cd, export, etc.)
- **Warning**: Executes directly on host, can modify system

#### 3. **ContainerBackend** (Base for Docker/Podman)
```python
# Abstract base for container-based execution
# Implements common container lifecycle:
#   1. Check runtime availability (docker/podman --version)
#   2. Pull base image
#   3. Create and run container
#   4. Execute commands via 'docker/podman exec'
```

#### 4. **DockerBackend**
```python
backend = create_backend('docker', image='ubuntu:24.04')
backend.initialize()  # Pulls image, creates container
exit_code, output = backend.execute("apt-get update")
backend.cleanup()     # Stops container
```
- Creates isolated Docker container
- Each command executes in same container (preserves working directory)
- Automatic cleanup with `--rm` flag

#### 5. **PodmanBackend**
```python
backend = create_backend('podman', image='ubuntu:24.04')
```
- Rootless alternative to Docker
- Compatible API with DockerBackend
- No daemon required

#### 6. **FirecrackerBackend** (Experimental)
```python
backend = create_backend('firecracker')
```
- Lightweight MicroVM for ultimate isolation
- Currently placeholder implementation
- Requires kernel and rootfs image preparation

#### 7. **ShellWrapper** (Interface Adapter)
```python
from shell.shell_wrapper import ShellWrapper

wrapper = ShellWrapper(backend)
exit_code, output = wrapper.execute("ls")
wrapper.add_to_history("ls", 0, "output")
wrapper.close()
```
- Provides `PersistentShell`-compatible interface
- Allows `ExecutorAgent` to work with any backend
- No changes needed to existing tools

## Usage Examples

### 1. Direct Backend Usage
```python
from shell.sandbox import create_backend

# Create and initialize
backend = create_backend('docker', image='ubuntu:24.04')
backend.initialize()

# Execute commands
exit_code, output = backend.execute("apt-get update")
print(f"Exit code: {exit_code}")
print(f"Output: {output}")

# Cleanup
backend.cleanup()
```

### 2. Via CLI
```bash
# Host execution (default)
planner-shell "install redis"

# Docker execution
planner-shell "install redis" --sandbox docker

# With custom image
planner-shell "install" --sandbox docker --image alpine:3.18

# Podman execution (rootless)
planner-shell "setup" --sandbox podman

# Auto-approve commands
planner-shell "task" --sandbox docker --auto-approve
```

### 3. Via Environment Variables
```bash
export SANDBOX_TYPE=docker
export SANDBOX_IMAGE=ubuntu:22.04

planner-shell "install nginx"
```

## Implementation Details

### Container Lifecycle (Docker/Podman)

1. **Runtime Check**
   ```python
   def _check_runtime_available(self) -> bool:
       subprocess.run([self.runtime, '--version'], timeout=5)
   ```

2. **Image Pull**
   ```python
   def _pull_image(self) -> bool:
       subprocess.run([self.runtime, 'pull', self.base_image], timeout=300)
   ```

3. **Container Creation**
   ```python
   subprocess.run([
       self.runtime, 'run', '-d', '--rm', '-i',
       '-e', 'PS1=', '-e', 'SYSTEMD_PAGER=cat',
       self.base_image, '/bin/bash'
   ])
   ```

4. **Command Execution**
   ```python
   subprocess.run([
       self.runtime, 'exec', container_id,
       '/bin/bash', '-c', command
   ], timeout=timeout)
   ```

## Configuration

### Environment Variables

```env
# Execution backend (default: 'host')
SANDBOX_TYPE=host|docker|podman|firecracker

# Container image (for docker/podman)
SANDBOX_IMAGE=ubuntu:24.04
```

### Programmatic Configuration

```python
import config
from shell.sandbox import create_backend

# Override defaults
config.SANDBOX_TYPE = 'docker'
config.SANDBOX_IMAGE = 'alpine:3.18'

backend = create_backend(config.SANDBOX_TYPE, image=config.SANDBOX_IMAGE)
```

## Security Considerations

### Container Backend Benefits
- ✅ **Filesystem Isolation**: Container has its own rootfs
- ✅ **Network Isolation**: Can use `--network none` if needed
- ✅ **Process Isolation**: Only container processes run
- ✅ **Resource Limits**: Can set memory/CPU limits via subprocess

### Remaining Risks
- ⚠️ Container can still access Docker socket (if mounted)
- ⚠️ Privileged container can escape to host
- ⚠️ Host kernel is shared with container

### Best Practices
1. **Never run with `--privileged` flag**
2. **Use restrictive base images** (alpine instead of ubuntu)
3. **Drop capabilities** when needed
4. **Run as non-root** inside container
5. **Use read-only roots** for immutable commands

## Testing

### Unit Tests
```bash
# Run sandbox backend tests
uv run python -m pytest test/test_sandbox_backends.py -v

# Specific test
uv run python -m pytest test/test_sandbox_backends.py::test_docker_backend_creation -v
```

### Integration Tests

#### Test Host Backend
```python
from shell.sandbox import HostBackend

backend = HostBackend()
backend.initialize()
exit_code, output = backend.execute("echo 'Hello, Host!'")
assert exit_code == 0
assert "Hello, Host!" in output
```

#### Test Docker Backend (requires Docker)
```python
from shell.sandbox import DockerBackend

backend = DockerBackend()
try:
    backend.initialize()
    exit_code, output = backend.execute("uname -a")
    assert exit_code == 0
    print(f"Running in: {output}")
    backend.cleanup()
except RuntimeError as e:
    print(f"Docker not available: {e}")
```

## Troubleshooting

### Docker Not Available
```
Error: docker is not available on this system
Solution: Install Docker Desktop or Docker Engine
```

### Image Pull Timeout
```
Error: Image pull timeout
Solution: Check internet connection, try smaller image or --image flag
```

### Container Creation Fails
```
Error: Failed to create container
Solution: Check `docker ps`, free disk space, and Docker daemon status
```

### Command Timeout
```
Error: Command execution timeout (600s default)
Solution: Increase timeout via config or CLI
```

## Future Enhancements

1. **Kubernetes Backend**: Execute in K8s pods
2. **SSH Backend**: Execute on remote hosts
3. **Lambda Backend**: Execute in AWS Lambda
4. **Resource Limits**: --memory, --cpu options
5. **Volume Mounting**: --volume for data persistence
6. **Network Config**: --network none/bridge options
7. **Firecracker Full Implementation**: Complete MicroVM support

## Design Decisions

### Why Abstract Base Class?
- Allows multiple backend implementations
- Easy to add new backends without modifying core logic
- Clear interface contract

### Why ShellWrapper?
- Avoids modifying ExecutorAgent
- Maintains backward compatibility
- Easy testing with mock objects

### Why subprocess.run over Docker SDK?
- No additional dependency required
- Works with both Docker and Podman
- Clear and predictable behavior
- Easy to debug and understand

### Why Container over PTY for Docker/Podman?
- Docker/Podman don't support PTY in the same way as bare systemsContainer execution is stateless by design, matching containerization principles

## Related Files

- [shell/sandbox.py](./shell/sandbox.py) - Backend implementations
- [shell/shell_wrapper.py](./shell/shell_wrapper.py) - Interface adapter
- [config/config.py](./config/config.py) - Configuration
- [main.py](./main.py) - CLI entry point
- [test/test_sandbox_backends.py](./test/test_sandbox_backends.py) - Test suite

## References

- [Docker Python API](https://docker-py.readthedocs.io/)
- [Podman Documentation](https://podman.io/documentation.html)
- [Firecracker Documentation](https://github.com/firecracker-microvm/firecracker)
- [Container Security](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
