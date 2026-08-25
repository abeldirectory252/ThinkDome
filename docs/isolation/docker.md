# Docker Isolation Validation Runbook

This runbook validates the local Docker executor against the three primary
boundaries: filesystem, process/resource, and network isolation. Run these
commands only against a disposable local Docker daemon and the dedicated
`thinkdome-executor:latest` image. No host files are mounted by the probes.

## 1. Establish the runtime contract

```bash
grep -E '^(EXECUTOR_BACKEND|EXECUTOR_BACKEND_USE_FALLBACK|SECURE_RUNTIME_TYPE|DOCKER_RUNTIME)' .env
docker version
docker info --format 'Driver={{.Driver}} Security={{json .SecurityOptions}} Cgroup={{.CgroupVersion}}'
docker info --format 'Runtimes={{json .Runtimes}} Default={{.DefaultRuntime}}'
docker image inspect thinkdome-executor:latest \
  --format 'Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}} User={{.Config.User}} Workdir={{.Config.WorkingDir}}'
```

Meaning:

- The executor must use Docker, not the subprocess fallback.
- cgroup v2, seccomp, and AppArmor should be enabled.
- A hardened runtime (`runsc` or `kata-runtime`) must be installed and selected
  explicitly for untrusted production workloads. Docker's default runtime is
  not sufficient evidence that every container uses the hardened runtime.

## 2. Canonical hardened container flags

The probes below mirror the executor configuration:

```bash
--network none
--read-only
--tmpfs /tmp:size=67108864,noexec,nosuid,nodev,mode=1777
--tmpfs /workspace:size=67108864,noexec,nosuid,nodev,mode=1777
--user 1000:1000
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 64
--memory 128m --memory-swap 128m
--cpus 1
--workdir /workspace
```

Do not remove a flag during a security test without recording that the test is
testing a different configuration.

## 3. Filesystem and PID probe

```bash
docker run --rm --network none --entrypoint python3 \
  --read-only \
  --tmpfs /tmp:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --tmpfs /workspace:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 \
  --memory 128m --memory-swap 128m --cpus 1 --workdir /workspace \
  thinkdome-executor:latest -c \
  'import os,json; print(json.dumps({"uid":os.getuid(),"pid1":open("/proc/1/cmdline","rb").read().replace(b"\\0",b" ").decode(errors="replace"),"host_files":[p for p in ["/home/sandbox/ThinkDome/.env","/var/run/docker.sock"] if os.path.exists(p)]}))'
```

Expected:

- UID is `1000`, not root.
- PID 1 is the sandbox interpreter, not the host init process.
- Dedicated host paths and the Docker socket are absent.

This verifies namespace and mount visibility. It does not prove that every
possible kernel interface is safe; inspect `/proc/self/mountinfo`, `/proc`,
`/sys`, and `/dev` when changing the image or runtime.

## 4. Network namespace and host-IP test

First identify the Docker bridge gateway:

```bash
docker network inspect bridge --format '{{json .IPAM.Config}}'
```

Then probe only loopback, the identified gateway, and one external address:

```bash
docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --tmpfs /workspace:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 64 --memory 128m --memory-swap 128m --cpus 1 \
  --workdir /workspace thinkdome-executor:latest -c \
  "import socket; r=[]; ips=['127.0.0.1','172.17.0.1','1.1.1.1']; exec('for ip in ips:\\n try:\\n  s=socket.create_connection((ip,9),timeout=.5); r.append((ip,\\\"CONNECTED\\\")); s.close()\\n except Exception as e: r.append((ip,type(e).__name__,str(e)))'); print(r)"
```

The approved proxy network must be provisioned as an **internal** network with
an explicit identity label:

```bash
docker network create --driver bridge --internal \
  --label thinkdome.network=egress-proxy thinkbox-egress
```

The backend rejects an unlabelled, non-bridge, or ambiguous network even if it
has the expected name. It also rejects a non-internal network, preventing the
sandbox from receiving a direct Docker bridge route.

The development Compose stack now provisions the labeled network and Squid
service from `docker/proxy/squid.conf`:

```bash
docker compose -f docker/docker-compose.yml up -d thinkbox-proxy
docker network inspect thinkbox-egress \
  --format 'driver={{.Driver}} internal={{.Internal}} labels={{json .Labels}}'
docker inspect thinkbox-proxy \
  --format '{{json .NetworkSettings.Networks}}'
```

The proxy must be attached to both `thinkbox-egress` and
`thinkbox-upstream`; sandboxes attach only to the internal network. The
production Compose file uses a separate Docker-in-Docker daemon, so this
outer-network service is not automatically visible to sandbox containers. In
production, provision the same labeled network and proxy inside the DinD
daemon before enabling networked sandboxes.

Expected under `network_mode=none`:

- `127.0.0.1` refers to the sandbox namespace; a refused connection means no
  service is listening there.
- The bridge gateway (commonly `172.17.0.1`) is unreachable.
- External addresses are unreachable.

ICMP reachability alone is not proof of escape. A TCP connection to a dedicated
host listener is the meaningful boundary test. If a connection succeeds,
record the destination, source address, NAT behavior, and whether the service
was intentionally exposed.

## 5. Process-count isolation

```bash
docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --tmpfs /workspace:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 16 --memory 64m --memory-swap 64m --cpus .5 \
  --workdir /workspace thinkdome-executor:latest -c \
  "import subprocess; ps=[]; failed=0; exec('for i in range(100):\\n try: ps.append(subprocess.Popen([\\\"sleep\\\",\\\"2\\\"]))\\n except Exception: failed+=1'); print('spawned',len(ps),'failed',failed); [p.wait() for p in ps]"
```

Expected: the process count stops near the configured limit, descendants are
rejected, and the container exits without leaving host processes behind.

## 6. Memory isolation

```bash
docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --tmpfs /workspace:size=67108864,noexec,nosuid,nodev,mode=1777 \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 64 --memory 64m --memory-swap 64m --cpus .5 \
  --workdir /workspace thinkdome-executor:latest -c \
  "a=[]; exec('for i in range(30):\\n a.append(bytearray(4*1024*1024)); print(i)')"
```

Expected: the container is OOM-terminated or the allocation fails, and a
second independent container remains runnable. Always perform the recovery
check after this probe.

## 7. Two-sandbox filesystem test

Create two containers with separate tmpfs workspaces, write a marker in A, and
attempt to read it from B. The marker must be absent. Repeat in reverse and
run the pair concurrently. Do not use host bind mounts for this test.

## 8. Host listener test (dedicated port only)

Start a listener on a randomly allocated high port bound to the host loopback.
From a `network_mode=none` sandbox, connect only to that port. The connection
must fail. Stop the listener immediately after the test. Never scan arbitrary
host ports or external networks.

## 9. Interpreting the current local results

The local campaign observed:

- Host files and `/var/run/docker.sock`: not visible.
- PID 1: sandbox Python process.
- `172.17.0.1` and `1.1.1.1`: `Network is unreachable`.
- PID limit 16: 15 children spawned, 85 rejected.
- 64 MiB memory limit: allocation probe was terminated.

The reported ability to ping a host IP should therefore be investigated by
first identifying whether that address is the Docker bridge gateway. It is not
a confirmed escape unless a dedicated unauthorized TCP service is reachable or
the sandbox can cross a filesystem, process, or control-plane boundary.

## 10. Evidence and cleanup

For every run record:

- image digest and runtime (`docker inspect <id>`)
- exact flags
- seed/marker values
- stdout, stderr, exit code, and timeout state
- cgroup limits and network mode
- cleanup result (`docker ps -a` must show no probe containers)

The tests in `tests/test_docker_isolation_live.py` and
`tests/test_isolation_validation.py` provide the automated equivalents. They
require Docker SDK access and should be skipped, not silently replaced by the
insecure subprocess executor.

## 11. Differential bridge versus isolated-network evidence

This is the most important network-isolation proof. Run the same gateway probe
once on Docker's default bridge and once with `network_mode=none`.

```bash
# Baseline: deliberately unsafe comparison, never use for untrusted workloads.
docker run --rm --network bridge --entrypoint python3 \
  --read-only --tmpfs /tmp:size=8m,noexec,nosuid,nodev \
  --tmpfs /workspace:size=8m,noexec,nosuid,nodev \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  thinkdome-executor:latest -c \
  "import socket; r=[]; exec('for p in [22,80,3128]:\\n try:\\n  s=socket.create_connection((\\\"172.17.0.1\\\",p),timeout=.5); r.append((p,\\\"CONNECTED\\\")); s.close()\\n except Exception as e: r.append((p,type(e).__name__,str(e)))'); print(r)"

# Required isolation path.
docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=8m,noexec,nosuid,nodev \
  --tmpfs /workspace:size=8m,nosuid,nodev \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  thinkdome-executor:latest -c \
  "import socket; r=[]; exec('for p in [22,80,3128]:\\n try:\\n  s=socket.create_connection((\\\"172.17.0.1\\\",p),timeout=.5); r.append((p,\\\"CONNECTED\\\")); s.close()\\n except Exception as e: r.append((p,type(e).__name__,str(e)))'); print(r)"
```

Interpretation:

- `ConnectionRefusedError` on the bridge probe means the gateway is reachable;
  the service simply is not listening on that port.
- `OSError: [Errno 101] Network is unreachable` on the isolated probe means
  there is no route to the gateway.
- The bridge result is evidence of why direct bridge networking is forbidden,
  not evidence that the isolated configuration is broken.

## 12. Combined filesystem, PID, and process-limit probe

```bash
docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=64m,noexec,nosuid,nodev \
  --tmpfs /workspace:size=64m,noexec,nosuid,nodev \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 16 --memory 64m --memory-swap 64m --cpus .5 \
  --workdir /workspace thinkdome-executor:latest -c \
  "import os,subprocess,json; out={'uid':os.getuid(),'pid1':open('/proc/1/cmdline','rb').read().replace(b'\\0',b' ').decode(errors='replace'),'host_files':[p for p in ['/home/sandbox/ThinkDome/.env','/var/run/docker.sock'] if os.path.exists(p)]}; ps=[]; failed=0; exec('for i in range(100):\\n try: ps.append(subprocess.Popen([\\\"sleep\\\",\\\"1\\\"]))\\n except Exception: failed+=1'); out['spawned']=len(ps); out['spawn_failed']=failed; [p.wait() for p in ps]; print(json.dumps(out))"
```

Observed in the local campaign: UID `1000`, no host files, sandbox Python as
PID 1, 15 children spawned, and 85 rejected by the PID limit.

## 13. Memory termination probe

```bash
set +e
timeout 15s docker run --rm --network none --entrypoint python3 \
  --read-only --tmpfs /tmp:size=64m,noexec,nosuid,nodev \
  --tmpfs /workspace:size=64m,noexec,nosuid,nodev \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 64 --memory 64m --memory-swap 64m --cpus .5 \
  --workdir /workspace thinkdome-executor:latest -c \
  "a=[]; exec('for i in range(32):\\n a.append(bytearray(4*1024*1024)); print(i)' )"
echo "MEMORY_PROBE_EXIT=$?"
```

Exit code `137` indicates cgroup OOM termination. Verify a separate sandbox
still executes normally after this test.

## 14. Runtime and cleanup evidence

```bash
docker network ls --format '{{.Name}} {{.Driver}} {{.Labels}}'
docker ps -a --filter ancestor=thinkdome-executor:latest \
  --format '{{.ID}} {{.Status}} {{.Names}}'
docker network inspect thinkbox-egress >/dev/null 2>&1
echo "EGRESS_NETWORK_STATUS=$?"
```

Before provisioning, the local campaign confirmed no `thinkbox-egress` network
or proxy container was present. The two temporary probe containers created
during failed SDK-based attempts were explicitly removed. The development
stack now provides a real proxy deployment; production DinD still requires
equivalent provisioning inside the DinD daemon.

## 15. Provisioned local proxy verification

The development Compose stack provisions the proxy with only `SETUID` and
`SETGID` added back after dropping all capabilities. Squid requires those two
capabilities during startup to drop from its initial root process to the
unprivileged `proxy` user. Without them, the proxy crash-loops with
`setgid: Operation not permitted`.

```bash
docker compose -f docker/docker-compose.yml up -d --force-recreate thinkbox-proxy
docker inspect thinkbox-proxy --format 'status={{.State.Status}} restart={{.RestartCount}}'
docker network inspect thinkbox-egress \
  --format 'driver={{.Driver}} internal={{.Internal}} labels={{json .Labels}}'
```

The proxy is healthy only when its status is `running`, restart count is stable,
and the network reports `internal=true` plus
`thinkdome.network=egress-proxy`.

Verify allowlisting through the proxy:

```bash
# Allowed domain: expected HTTP 200.
docker run --rm --network thinkbox-egress \
  -e HTTP_PROXY=http://thinkbox-proxy:3128 \
  -e HTTPS_PROXY=http://thinkbox-proxy:3128 \
  python:3.12-slim python -c \
  "import urllib.request; print(urllib.request.urlopen('https://pypi.org/simple/', timeout=5).status)"

# Denied domain: expected 403/tunnel failure.
docker run --rm --network thinkbox-egress \
  -e HTTP_PROXY=http://thinkbox-proxy:3128 \
  -e HTTPS_PROXY=http://thinkbox-proxy:3128 \
  python:3.12-slim python -c \
  "import urllib.request; urllib.request.urlopen('https://example.com/', timeout=5)"

# Host gateway: expected 403 or failure through the proxy.
docker run --rm --network thinkbox-egress \
  -e HTTP_PROXY=http://thinkbox-proxy:3128 \
  -e HTTPS_PROXY=http://thinkbox-proxy:3128 \
  python:3.12-slim python -c \
  "import urllib.request; urllib.request.urlopen('http://172.17.0.1/', timeout=5)"

# Raw-socket bypass: expected Network is unreachable.
docker run --rm --network thinkbox-egress --entrypoint python3 \
  python:3.12-slim -c \
  "import socket; socket.create_connection(('172.17.0.1',80), timeout=2)"
```

The local verification produced `200` for PyPI, `403 Forbidden` for
`example.com`, `403 Forbidden` for the host gateway through Squid, and
`Network is unreachable` for the raw-socket bypass.

The Compose proxy image is pinned to digest
`ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029`.
Do not replace it with a floating `:latest` tag in production.

### Production DinD caveat

`docker/docker-compose.prod.yml` points the application at a separate
Docker-in-Docker daemon (`DOCKER_HOST=tcp://dind:2376`). Networks created by
the outer Docker daemon are not visible inside that DinD daemon. Before
enabling networked production sandboxes, provision **inside the DinD daemon**:

1. the pinned Squid proxy image and configuration;
2. an internal `thinkbox-egress` network with the security label;
3. a separate upstream network attached only to `thinkbox-proxy`;
4. health checks and allowlist verification from a sandbox container.

If those objects are absent from the daemon referenced by `DOCKER_HOST`, the
backend must reject network-enabled sandbox creation. Never point production
sandboxes at the outer host bridge as a workaround.
