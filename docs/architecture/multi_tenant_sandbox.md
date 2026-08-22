# Multi-tenant, Multi-node Sandbox Architecture

## Status

This is the target architecture for ThinkDome production deployments. Docker
execution remains a local-development compatibility backend during the
migration; it is not the production isolation boundary.

## Design goals

- Treat sandbox code as hostile, including code produced by authenticated AI
  agents.
- Keep public API processes unprivileged and unable to control a host runtime.
- Support multiple tenants, projects, execution nodes, templates, and regions.
- Make lifecycle operations durable, idempotent, auditable, and safe to retry.
- Give each sandbox a hardware-isolated runtime, bounded resources, explicit
  egress policy, and independently revocable credentials.

## Target topology

```text
SDK / CLI / Browser
        |
        v
API gateway + Control plane  <----> PostgreSQL (durable tenant and sandbox state)
        |                                  |
        |                                  +--> Object storage (templates, snapshots, files)
        +------------------------------> Redis (node directory, leases, routing cache)
        |
        +-- mTLS gRPC --> Node orchestrator (one per execution node)
                                      |
                                      +--> Firecracker / Cloud Hypervisor microVM
                                      |       |
                                      |       +--> in-guest execution agent
                                      |
                                      +--> cgroups v2, network namespace, TAP/veth,
                                      |    nftables egress policy, local template cache
                                      |
                                      +--> telemetry and lifecycle events

Ingress proxy ---------------> routing cache ------------> node sandbox proxy
Egress proxy  <--------------- explicit per-sandbox policy <--- sandbox node
```

The API schedules and authorizes work; it must not mount a Docker socket, own
TAP devices, create cgroups, or start VM processes. The node orchestrator is
the only privileged component and accepts a narrow, authenticated RPC contract.

Node-agent transport uses two independent controls:

1. mTLS authenticates the control-plane and node identities on a private
   network. Production node listeners must provide `NODE_TLS_CERTFILE`,
   `NODE_TLS_KEYFILE`, and `NODE_TLS_CAFILE`.
2. Each request carries an HMAC-signed, short-lived authorization token bound
   to one organization, project, sandbox, operation, and request ID.

Compromise of a client certificate therefore does not grant unrestricted
sandbox control, and compromise of one operation token does not authorize a
different operation.

## Isolation model

Production sandboxes run one microVM per tenant sandbox. Each VM receives:

- a read-only, versioned template root filesystem;
- an ephemeral copy-on-write disk or a separately attached tenant volume;
- a distinct cgroup v2 subtree with CPU, memory, PIDs, IO, and wall-clock
  limits;
- a distinct network namespace and TAP/veth attachment;
- no inbound access except through an authenticated node proxy;
- default-deny egress enforced on the node, not merely through environment
  proxy variables;
- short-lived, audience-bound execution credentials delivered only to the
  in-guest agent when explicitly requested.

Docker is allowed only in a developer profile. It must never receive host
workspace bind mounts or become a production fallback for a failed microVM.

## Tenant and authorization model

Every mutable resource is scoped as:

```text
organization -> project -> sandbox -> execution / volume / snapshot
```

The control plane authenticates a principal, authorizes it against the project,
and mints a short-lived orchestration request token containing tenant, project,
sandbox, operation, resource limits, and expiration. The node orchestrator
validates that token and rejects requests outside its assigned sandbox.

No API key, database credential, Docker credential, or control-plane service
credential is injected into a sandbox.

## Durable lifecycle

PostgreSQL is the source of truth for desired lifecycle state. Redis holds
leased, reconstructible runtime routing state. Operations use an idempotency
key and an optimistic version so retries cannot create duplicate sandboxes.

```text
REQUESTED -> SCHEDULING -> PROVISIONING -> READY -> RUNNING
                                   |                 |
                                   v                 v
                                FAILED <--- PAUSED <-+-> TERMINATING -> TERMINATED
```

The orchestrator reports observed state. The control plane reconciles desired
and observed state; it does not keep a process-local sandbox registry.

## Node orchestration contract

The initial RPC surface is intentionally small:

- `RegisterNode` / `Heartbeat`
- `CreateSandbox`
- `Execute`
- `PauseSandbox` / `ResumeSandbox`
- `TerminateSandbox`
- `GetSandboxStatus`

Every request includes a sandbox ID, idempotency key, deadline, and signed
authorization context. The execution agent handles process, file, and stream
operations inside the VM; it is not a general host command channel.

## Migration stages

1. **Safety baseline:** eliminate host workspace binds and insecure runtime
   fallback; tighten deployment configuration; make execution failures typed.
2. **Control-plane contract:** persist tenant/project/sandbox records and add
   idempotent lifecycle operations plus node leases.
3. **Node orchestrator:** introduce an authenticated node service and move
   Docker/microVM privilege out of the API process.
4. **MicroVM data plane:** make the existing microVM implementation a
   node-local backend with cgroup, network, image/template, and agent support.
5. **Scale features:** placement, snapshots, durable volumes, ingress/egress
   routing, quotas, audit/event streams, and multi-region scheduling.

## Non-negotiable production invariants

- No public API or worker container mounts `/var/run/docker.sock`.
- No sandbox uses a host-path bind mount.
- No automatic fallback can reduce the requested isolation level.
- Production image references are immutable digests, not mutable tags.
- All node-control traffic uses mTLS and operation-scoped authorization.
- Tenant ownership is checked at every resource boundary.
- Every lifecycle transition, execution request, and policy decision is
  auditable with a request ID and tenant/project/sandbox identifiers.
