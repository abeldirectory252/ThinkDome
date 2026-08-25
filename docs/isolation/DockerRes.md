Current safe state:

  - network_enabled=False: sandbox uses network_mode=none.
  - network_enabled=True: backend now fails closed unless thinkbox-egress exists
    and is labeled correctly.

  - It will not fall back to Docker’s default bridge.

  Before enabling networked sandboxes, you need all of these:

  1. A real proxy service named thinkbox-proxy.
  4. Docker network label:

  thinkdome.network=egress-proxy

  5. A live TCP test proving:
      - sandbox → proxy succeeds only for allowed destinations;

The full local Docker campaign produced these results.

  Filesystem isolation: PASS

  - Sandbox UID: 1000
  - Host .env: not visible
  - Docker socket: not visible
  - Read-only root filesystem and isolated tmpfs workspace were enforced.

  Process isolation: PASS

  - PID 1 was the sandbox Python process, not the host.
  - No host processes were visible.
  - With pids_limit=16, 15 children started and 85 were rejected.

  Memory isolation: PASS for enforcement

  - A 64 MiB container allocating beyond its limit exited with code 137,
    indicating cgroup OOM termination.

  - Cross-sandbox recovery still requires two simultaneously running production
    sandboxes.

  Network isolation: PASS for network_mode=none

  - Docker gateway 172.17.0.1: Network is unreachable
  - External address 1.1.1.1: Network is unreachable
  - Loopback remained sandbox-local.

  Confirmed bridge exposure:

  - With network_mode=bridge, connections to 172.17.0.1 returned Connection
    refused, proving the gateway was reachable.

  - With network_mode=none, the same probes returned Network is unreachable.

  That confirms the original bridge fallback was a real isolation weakness. It
  has been fixed so network-enabled sandboxes require a validated thinkbox-

  Proxy path status: NOT VERIFIED

  - No thinkbox-egress network exists locally.
    suggest secure egress.

  - Network-enabled sandbox creation now fails closed until the real proxy and
    firewall are provisioned.

  Cleanup:

  - Probe containers were removed.
  - No thinkbox-egress network was created.
  - No test containers remain.


For a networked sandbox isolated from the host, use this topology:

  Sandbox
     │
     │ internal Docker network only
     ▼
  thinkbox-proxy
     │
     │ separate upstream network
     ▼
  Internet / approved services

  Do not attach sandboxes directly to Docker’s default bridge.

  Required setup:

  1. Create an internal, labeled network:

  docker network create \
    --driver bridge \
    --internal \
    --label thinkdome.network=egress-proxy \
    thinkbox-egress

  2. Run a real forward proxy named thinkbox-proxy attached to:

  - thinkbox-egress
  - a separate upstream network

  3. Configure the proxy with:

  - explicit domain allowlist;
  - blocked private/loopback/link-local destinations;
  - blocked Docker gateway and metadata addresses;
  - no transparent arbitrary forwarding;
  - request and connection limits;
  - audit logging;
  - non-root user;
  - no privileged mode;
  - no Docker socket mount.

  4. Attach only the proxy to the upstream network.
  5. Test from a sandbox:

  - allowed HTTPS destination succeeds;
  - disallowed domain fails;
  - 127.0.0.1, 172.17.0.1, RFC1918, link-local, and metadata addresses fail;
  - raw TCP bypass fails;
  - altered proxy environment variables cannot bypass policy.

  The backend now requires the egress network to be:

  - uniquely named;
  - bridge driver;
  - Docker Internal=true;
  - labeled thinkdome.network=egress-proxy.

  A plain bridge network is rejected. Compilation and diff checks pass.

────────────────────────────────────────────────────────────────────────────────
 
 
  Environment: local
 
  Reason: May I inspect local Docker images and repository deployment files
  before provisioning the networked sandbox proxy?
 
  $ docker images --format '{{.Repository}}:{{.Tag}}' | sort; find . -maxdepth
  3 -type f \( -iname '*squid*' -o -iname '*tinyproxy*' -o -iname '*proxy*' -o
  [… 13 lines] ctrl + a view all
 
Squid is a proxy server. The ubuntu/squid Docker image packages Squid so
  ThinkDome can run it as a dedicated network gateway.

  In this setup:

  Sandbox → thinkbox-egress → Squid proxy → thinkbox-upstream → Internet

  Squid:

  - receives HTTP/HTTPS requests from sandboxes;
  - allows only configured domains;
  - blocks unauthorized domains and host/private addresses;
  - logs requests;
  - provides connection and timeout controls;
  - prevents sandboxes from directly using Docker’s bridge network.

  It is not a sandbox and does not isolate processes itself. Docker namespaces
  and capabilities provide sandbox isolation; Squid provides controlled outbound
  network access.
 


