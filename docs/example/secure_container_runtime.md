# Secure Container Runtime & Isolation Guide

ThinkDome supports hardware-level isolation for untrusted AI-generated code using Google gVisor, Kata Containers, and Firecracker MicroVMs.

> 📘 **Installation & Download Guide**: For step-by-step download links, installation commands, Docker daemon registration (`/etc/docker/daemon.json`), and kernel/rootfs asset configuration, see the [Hypervisor & Secure Container Setup Guide](file:///home/sandbox/ThinkDome/docs/example/hypervisor_setup_guide.md).


---

## 🏰 Supported Isolation Runtimes

| Runtime | Isolation Mechanism | Best For | Server Settings |
|---|---|---|---|
| **gVisor (`runsc`)** | User-space syscall interception kernel | Low overhead, multi-tenant safety | `SECURE_RUNTIME_TYPE="gvisor"`, `DOCKER_RUNTIME="runsc"` |
| **Kata Containers** | QEMU / Cloud Hypervisor MicroVM | Maximum isolation & Linux kernel compatibility | `SECURE_RUNTIME_TYPE="kata"`, `DOCKER_RUNTIME="kata-runtime"` |
| **Firecracker MicroVM** | KVM-accelerated MicroVM | High density, minimal memory footprint | `EXECUTOR_BACKEND="microvm"`, `MICROVM_BINARY="firecracker"` |

---

## ⚙️ Server Configuration (`.env` or `config.py`)

### gVisor in Docker Mode:
```ini
EXECUTOR_BACKEND=docker
SECURE_RUNTIME_TYPE=gvisor
DOCKER_RUNTIME=runsc
```

### Kata Containers in Kubernetes Mode:
```ini
EXECUTOR_BACKEND=kubernetes
SECURE_RUNTIME_TYPE=kata
K8S_RUNTIME_CLASS=kata-qemu
```

### Direct KVM MicroVM Mode:
```ini
EXECUTOR_BACKEND=microvm
SECURE_RUNTIME_TYPE=microvm
MICROVM_BINARY=cloud-hypervisor
```

---

## 🛡️ Startup Guard Validation

When ThinkDome starts up, it automatically validates the configured secure runtime:

```bash
# Server startup diagnostic output:
INFO  Validating secure container runtime 'gvisor' for backend 'docker'...
INFO  ✅ Docker secure OCI runtime 'runsc' is available in Docker daemon.
```

If the requested secure runtime is missing or misconfigured in `/etc/docker/daemon.json`, the server refuses startup with a clear error message:

```text
RuntimeError: Configured Docker runtime 'runsc' is not registered with Docker daemon.
Available runtimes: [runc]. Please install 'runsc' and configure /etc/docker/daemon.json.
```
