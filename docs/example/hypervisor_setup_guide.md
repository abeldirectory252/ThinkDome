# Hypervisor & Secure Container Runtime Setup Guide

This guide provides step-by-step instructions for downloading, installing, and integrating **Cloud Hypervisor**, **Firecracker**, **gVisor (`runsc`)**, and **Kata Containers** with ThinkDome.

---

## 🩺 0. Host System Readiness Check (`thinkdome check`)

Before configuring your environment, run the built-in diagnostic tool to inspect your host's hypervisor capabilities, `/dev/kvm` state, binary paths, and Docker OCI runtimes:

```bash
# Run host readiness check as standard user:
./venv/bin/python -m thinkdome.cli check

# Run host readiness check with root / sudo privileges (to test TAP/bridge creation):
sudo ./venv/bin/python -m thinkdome.cli check
# Or using alias:
sudo ./venv/bin/python -m thinkdome.cli doctor
```

> 💡 **Sudo Tips**:
> - **Preserve Environment (`sudo -E`)**: Pass `-E` if you configured custom environment variables (e.g. `MICROVM_KERNEL_PATH`): `sudo -E ./venv/bin/python -m thinkdome.cli check`.
> - **Global Binary Path**: Ensure hypervisor binaries are in system PATH so `sudo` can access them (`sudo cp ~/.local/bin/cloud-hypervisor /usr/local/bin/cloud-hypervisor`).

The diagnostic tool evaluates:
1. **User Privileges**: Checks root (UID 0) / `CAP_NET_ADMIN` permissions for TAP bridging.
2. **KVM Acceleration**: Verifies `/dev/kvm` presence and read/write permissions.
3. **Hypervisor Binaries**: Checks `cloud-hypervisor` and `firecracker` installation across system `PATH` and user local paths (`~/.local/bin`, `/home/*/.local/bin`, `/usr/local/bin`), automatically detecting binaries even when invoked under `sudo`.
4. **Guest OS Images**: Checks kernel (`vmlinux`) and ext4 rootfs (`rootfs.ext4`) in `/var/lib/thinkdome/`.
5. **Docker & OCI Runtimes**: Validates Docker daemon connectivity, gVisor (`runsc`), and Kata Containers.
6. **Suggestive Remediation**: Recommends the exact backend and environment flags suitable for your host.



---


## ⚡ 1. Cloud Hypervisor & Firecracker MicroVM Setup

### Step 1.1: Download Hypervisor Binary

#### Option A: Cloud Hypervisor (Default)
```bash
mkdir -p ~/.local/bin
curl -L https://github.com/cloud-hypervisor/cloud-hypervisor/releases/download/v40.0/cloud-hypervisor -o ~/.local/bin/cloud-hypervisor
chmod +x ~/.local/bin/cloud-hypervisor
```
Or install system-wide:
```bash
sudo cp ~/.local/bin/cloud-hypervisor /usr/local/bin/cloud-hypervisor
```

#### Option B: Firecracker
```bash
release_url="https://github.com/firecracker-microvm/firecracker/releases/download/v1.7.0/firecracker-v1.7.0-x86_64.tgz"
curl -L ${release_url} | tar -xz
sudo mv release-v1.7.0-x86_64/firecracker-v1.7.0-x86_64 /usr/local/bin/firecracker
sudo chmod +x /usr/local/bin/firecracker
```

### Step 1.2: Enable KVM Hardware Acceleration
Ensure `/dev/kvm` is accessible:
```bash
sudo chmod 666 /dev/kvm
# Or add your user to the kvm group:
sudo usermod -aG kvm $USER
```

### Step 1.3: Download Kernel & Rootfs Images
Create asset directory and download guest kernel and ext4 filesystem:
```bash
sudo mkdir -p /var/lib/thinkdome
sudo chown -R $USER:$USER /var/lib/thinkdome

# Download minimal vmlinux kernel
curl -L https://cloud-images.ubuntu.com/minimal/releases/jammy/release/ubuntu-22.04-minimal-cloudimg-amd64-vmlinuz-generic -o /var/lib/thinkdome/vmlinux

# Download ext4 rootfs disk image
curl -L https://cloud-images.ubuntu.com/minimal/releases/jammy/release/ubuntu-22.04-minimal-cloudimg-amd64-root.tar.xz | tar -xJ -C /var/lib/thinkdome/
```

### Step 1.4: ThinkDome Configuration (`.env`)
```ini
EXECUTOR_BACKEND=microvm
MICROVM_BINARY=cloud-hypervisor   # or "firecracker"
MICROVM_KERNEL_PATH=/var/lib/thinkdome/vmlinux
MICROVM_ROOTFS_PATH=/var/lib/thinkdome/rootfs.ext4
```

---

## 🛡️ 2. Google gVisor (`runsc`) Setup & Docker Integration

gVisor provides user-space kernel isolation with minimal overhead (~50ms cold start).

### Step 2.1: Download `runsc` Binary
```bash
(
  set -e
  ARCH=$(uname -m)
  URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}
  curl -O ${URL}/runsc
  curl -O ${URL}/runsc.sha512
  sha512sum -c runsc.sha512
  chmod +x runsc
  sudo mv runsc /usr/local/bin/
)
```

### Step 2.2: Register `runsc` with Docker
Edit `/etc/docker/daemon.json` (create if it does not exist):
```json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/local/bin/runsc"
    }
  }
}
```

Restart Docker daemon:
```bash
sudo systemctl restart docker
```

Verify installation:
```bash
docker run --rm --runtime=runsc alpine dmesg | head -n 1
# Expected output mentions: gVisor / runsc
```

### Step 2.3: ThinkDome Configuration (`.env`)
```ini
EXECUTOR_BACKEND=docker
SECURE_RUNTIME_TYPE=gvisor
DOCKER_RUNTIME=runsc
```

---

## 🏎️ 3. Kata Containers Setup & Integration

Kata Containers provides lightweight hardware VM isolation with standard Docker image compatibility.

### Step 3.1: Install Kata Containers
On Ubuntu / Debian:
```bash
sudo snap install kata-containers --classic
```

### Step 3.2: Register `kata-runtime` with Docker
Edit `/etc/docker/daemon.json`:
```json
{
  "runtimes": {
    "kata-runtime": {
      "path": "/snap/bin/kata-containers.runtime"
    }
  }
}
```

Restart Docker daemon:
```bash
sudo systemctl restart docker
```

### Step 3.3: ThinkDome Configuration (`.env`)
```ini
EXECUTOR_BACKEND=docker
SECURE_RUNTIME_TYPE=kata
DOCKER_RUNTIME=kata-runtime
```

---

## 🔄 4. Dev / Non-Root Fallback Mode

In non-root or dev environments where `/dev/kvm` or TAP device permissions (`ioctl(TUNSETIFF)`) are missing, enable automatic fallback:

```ini
EXECUTOR_BACKEND_USE_FALLBACK=True
```

Run server:
```bash
EXECUTOR_BACKEND_USE_FALLBACK=True ./venv/bin/python -m thinkdome.cli serve --host 127.0.0.1 --port 8000
```
