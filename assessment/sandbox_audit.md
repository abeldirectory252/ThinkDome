# 🧪 Karpathy Sandbox Environment Audit

**Date:** July 5, 2026
**Auditor:** Andrej Karpathy (System Persona)
**Target Benchmark:** OpenAI / Google DeepMind / Anthropic Internal Sandboxes
**Scope:** Infrastructure, Isolation, Security, API Layer, Observability — NOT AI models

---

## 📊 Executive Summary
- **Sandbox Readiness Score:** 3.5/10 (Adjusted: Local shell executions now sandboxed, but critical architectural and scaling gaps remain)
- **Verdict:** **Needs Major Work**
- **Biggest Strength:** The **Pre-warmed Container Pool Manager** (`pool_manager.py`) is exceptionally well-conceived, achieving near-instantaneous container acquisition latency (<60ms) using lazy eviction and workspace reset patterns.
- **Biggest Weakness:** **State fragmentation and host-level vulnerabilities**. The scheduling architecture is in-memory and stateful, and the database relies on local pod SQLite storage, which makes horizontal scaling impossible. Docker socket mounting in Kubernetes also creates node-compromise vulnerabilities.
- **One-Sentence Takeaway:** While recent fixes successfully routed shell commands inside the container sandbox, the backend orchestration, state persistence, and container socket architecture must be re-engineered from the ground up to survive production scale.

---

## 🔍 Detailed Environment Evaluation

### 1. Isolation & Security Boundaries
- **Status:** ❌ **Fail**
- **Karpathy's Critique:** 
  You've got a classic docker-in-docker security pattern here, and it’s a time bomb. By mounting the host's `/var/run/docker.sock` into the `thinkdome-api` Kubernetes deployment (`k8s/thinkdome-all.yaml`), you have effectively given the API pod root-level control over the host Kubernetes node. If an attacker compromises the FastAPI orchestrator, they can talk to the Docker socket, spin up a privileged container, mount the host's root filesystem, and fully compromise the VM node.
  Furthermore, although your deployment specifies `runtimeClassName: gvisor`, that only protects the API pod itself. The sandbox containers spawned by your Python client talk directly to the host Docker daemon, meaning they run as *siblings* on the host node, outside gVisor isolation (using standard, unconfined `runc` by default). 
- **What OpenAI/Google Does:** 
  We treat untrusted user code as highly hostile. Sandbox runs never share host kernels or sockets. They run inside hardware-virtualized microVMs (like AWS Firecracker or Kata Containers) with strict SDN network policies (such as Calico/Cilium) blocking access to internal cluster components, APIs, databases, or cloud provider instance metadata endpoints (`169.254.169.254`).
- **Action Required:** 
  Remove the `/var/run/docker.sock` mount immediately. Migrate to a dynamic Kubernetes pod runner that creates sandboxed pods (under gVisor or Kata) via the Kubernetes API, or use a dedicated microVM service (e.g., AWS Firecracker/Fly.io-style VMs) for executing sandbox scripts. Implement strict NetworkPolicies to segment sandbox networks completely.

---

### 2. User Code Execution Safeguards
- **Status:** ⚠️ **Partial** (Improved: `shell_exec` is now fully sandboxed, but blocklist seccomp rules persist)
- **Karpathy's Critique:** 
  We successfully patched `shell_exec` to execute inside the sandbox container rather than directly on the host API system in Python. However, the rest of the file tools (such as `read_file`, `write_file`, and `grep_search`) still resolve directories and access files directly on the host API filesystem using standard Python libraries. This opens the door for symlink traversal attacks or TOCTOU (Time of Check to Time of Use) races where an active container swaps a file for a symlink to host configurations like `/etc/passwd`.
  Second, your seccomp profile (`security/seccomp.json`) is configured with `"defaultAction": "SCMP_ACT_ALLOW"`. This is a blocklist, not an allowlist. Blocklists are fragile; any new kernel syscall introduced in future OS updates will be allowed by default, leaving you open to zero-day container escape exploits.
- **What OpenAI/Google Does:** 
  All execution (including filesystem tools and shell tools) MUST run inside the sandboxed VM/container. The orchestrator API should merely act as a control proxy, sending execution requests across an isolated RPC barrier (like gRPC or a minimal Agent runner inside the VM). Seccomp profiles must be default-deny (`SCMP_ACT_ERRNO` or `SCMP_ACT_KILL`), whitelisting only the basic syscalls necessary for running Python.
- **Action Required:** 
  Rewrite `seccomp.json` as a default-deny allowlist. Route all tool filesystem operations (like reading, writing, and directory listings) to execute inside the container workspace context rather than accessing the host bind-mounted workspace folder via Python.

---

### 3. Resource Governance
- **Status:** ⚠️ **Partial**
- **Karpathy's Critique:** 
  You have cgroups memory limits (256MB/512MB/1GB) and CPU capping enforced. OOM kills (exit code 137) are monitored correctly. 
  But there is **zero GPU scheduling or limits**. There are no device mapping constraints in the docker configuration, meaning user code has no GPU access, or if they do (via host configurations), they can hog VRAM and cause GPU OOMs across the system. Furthermore, there is no job preemption, mixed-precision memory configuration, or active idle detectors for running interactive sessions.
- **What OpenAI/Google Does:** 
  Production GPU clusters employ advanced schedulers (Slurm, Ray, or custom Kubernetes device plugins) to binpack workloads, manage VRAM quotas, and preempt lower-priority training or inference runs. Sandboxes automatically self-terminate if no new commands are processed within a short period (e.g., 5-10 minutes).
- **Action Required:** 
  Add GPU limit parameters to `RESOURCE_PROFILES` and pass GPU allocations (e.g., `device_requests`) to the Docker API. Implement active command monitoring to terminate running containers that are idle.

---

### 4. API & Request Handling
- **Status:** ❌ **Fail**
- **Karpathy's Critique:** 
  Your `Scheduler` (`scheduler.py`) is an **in-memory** scheduler using `asyncio` queues and `deque` buffers. Since you deploy this with `replicas: 3` in Kubernetes, your queue state is completely fragmented across 3 different pods. If a pod crashes, all its queued jobs disappear. Your consistent hashing assigner is local to each pod, defeating the purpose of a global request router.
  Furthermore, you have no dynamic request batching to group executions, and no circuit breakers or retry backoffs.
- **What OpenAI/Google Does:** 
  API gateways route requests to a distributed message broker (RabbitMQ, Kafka, or SQS). The API servers themselves are stateless; workers pull tasks from the queue and coordinate state via a shared high-availability database or key-value store (Redis/PostgreSQL).
- **Action Required:** 
  Replace the local in-memory scheduler with a distributed queue worker system (like Celery, RabbitMQ, or Redis-based task queues). Make the API layer entirely stateless.

---

### 5. Observability & Infrastructure
- **Status:** ❌ **Fail**
- **Karpathy's Critique:** 
  You're running blind here. The `/metrics` endpoint is a simplified uptime tracker with a note: *"Full Prometheus metrics coming soon"*. The `/logs/executions` and `/audit/files` endpoints are placeholders returning empty arrays. There is no distributed tracing (like OpenTelemetry or Jaeger) to follow a request from API → Scheduler → Worker → Container.
- **What OpenAI/Google Does:** 
  Every API endpoint and worker node emits structured JSON logs with context-propagated `trace_id` and `span_id`. Prometheus is hooked up to collect granular metrics (CPU, RSS memory, GPU vRAM utilization, I/O rates) from every microVM, visualised in real-time Grafana dashboards.
- **Action Required:** 
  Implement OpenTelemetry SDK for tracing request spans. Replace the placeholder metrics endpoint with a real Prometheus scraping interface using `prometheus_client`. Connect execution audit logs to a persistent storage backend.

---

### 6. Dependency Management
- **Status:** ⚠️ **Partial**
- **Karpathy's Critique:** 
  You package standard scientific libraries (pandas, numpy, etc.) in the docker executor image. You also try to support user package installation by setting `PYTHONUSERBASE` to `/workspace/.pip` and linking it to a workspace.
  However, this has a massive logic flaw: since LLM sandboxes run with network access disabled (`network_mode="none"`), running `pip install` inside them will fail immediately with connection errors. If they are in `ADMIN` mode, pip downloads on the fly will take minutes, crushing execution latency.
- **What OpenAI/Google Does:** 
  We use pre-baked container layers or virtual environments cached on shared network storage. Packages are installed instantly from local PyPI mirrors or pre-fetched Nix caches without exposing the sandbox to the open internet.
- **Action Required:** 
  Set up a local PyPI caching proxy (or private package registry) within the cluster. Allow the egress proxy (`Squid`) to route to PyPI domains for all execution profiles when building environments, or use declarative environments (like Nix) to pre-cache dependencies.

---

### 7. Data Handling & Storage
- **Status:** ⚠️ **Partial** (Improved: `FILE_STORAGE_DIR` now mapped to `/tmp` in K8s, but SQLite remains stateful)
- **Karpathy's Critique:** 
  Mapping `FILE_STORAGE_DIR` to the `/tmp/thinkdome-files` `emptyDir` mount prevents pod startup crashes under read-only rootfilesystems, which is good. But the database remains a local SQLite file (`thinkbox.db`).
  Since the database is local, your 3 Kubernetes API replicas still do not share database state. Users load-balanced between different pods will face session misses, "user not found" errors, and logs will be fragmented. If a pod is rescheduled, all database records (sandboxes, API keys, request logs) are deleted forever.
- **What OpenAI/Google Does:** 
  State is stored in a centralized, clustered database (like PostgreSQL or CockroachDB). Sandboxed workspaces are mounted via shared, encrypted network volumes (e.g., AWS EFS or Ceph) using Kubernetes PVCs.
- **Action Required:** 
  Migrate `DatabaseService` from SQLite to PostgreSQL. Mount workspace directories via a shared network volume using Kubernetes PersistentVolumeClaims (PVCs).

---

### 8. User Experience & Researcher Velocity
- **Status:** ⚠️ **Partial**
- **Karpathy's Critique:** 
  Your pre-warmed pool manager is awesome. Booting containers in <60ms is a win for iteration speed. But you lack integrations with experiment trackers (Weights & Biases, MLflow) by default, and there is no hot-reloading capability. Researchers have to run their code blocks entirely from scratch on each run.
- **What OpenAI/Google Does:** 
  Provide standard Jupyter/VSCode server integrations inside the sandbox. Cell-by-cell execution allows researchers to preserve model state in memory while hot-reloading code.
- **Action Required:** 
  Add support for persistent execution kernels (e.g., Jupyter kernels) that can accept code snippets interactively without restarting the container, and inject W&B API keys automatically from the credentials vault.

---

## ⚠️ Critical Gaps (Must Fix Before Launch)
1. **Docker Socket Mount in Kubernetes:** Mounting `/var/run/docker.sock` violates fundamental container isolation rules.
2. **Local SQLite Database & Stateful Design:** Pods are stateful and cannot scale horizontally due to local SQLite and local in-memory queues.
3. **Seccomp Blocklist:** The seccomp filter uses a blocklist (default Action SCMP_ACT_ALLOW), which leaves nodes open to kernel exploits.

---

## 📋 Sandbox Environment Scorecard

| Criterion | Score (1-10) | Status |
|-----------|--------------|--------|
| Isolation & Security | 2/10 | ❌ Fail |
| Code Execution Safeguards | 5/10 | ⚠️ Partial |
| Resource Governance | 4/10 | ⚠️ Partial |
| API & Request Handling | 3/10 | ❌ Fail |
| Observability | 2/10 | ❌ Fail |
| Dependency Management | 5/10 | ⚠️ Partial |
| Data Handling | 4/10 | ⚠️ Partial |
| User Experience | 6/10 | ⚠️ Partial |
| **TOTAL** | **31/80** | **Needs Major Work** |
