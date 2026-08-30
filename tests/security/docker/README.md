# Docker sandbox security tests

The suite is split into static regressions and opt-in live probes. Static
checks are safe for ordinary CI. Live checks require a disposable daemon and
`RUN_DOCKER_SECURITY_LIVE=1`; they use bounded containers and synthetic state.

The requested taxonomy is represented by these focused directories:

`escape/`, `capabilities/`, `filesystem/`, `process/`, `network/`,
`resources/`, `secrets/`, `containers/`, `docker-api/`, `lifecycle/`, and
`regression/`.

The current implementation keeps the executable probes small and centralized
to avoid accidentally duplicating cleanup logic. The report records static
findings and leaves live-only checks as `NOT_RUN` until explicitly enabled.
