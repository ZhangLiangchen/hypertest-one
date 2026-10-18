# ADR-012: Controlled Python and isolated ASGI execution environments

**Status:** Accepted  
**Date:** 2026-10-18  
**Deciders:** HyperTest One implementation, within the existing single-operator MVP

## Context

The whitepaper §20/25 requires Backend/API functional tests in an identifiable
environment. The original Docker Runner has pytest only and does not start an
application. Configuration text is an immutable input artifact; interpreting
arbitrary existing text as commands would change historical semantics.

## Decision

Provide two platform-approved versioned profiles, `python-pytest-v1` and
`python-api-v1`. The latter adds locked FastAPI, uvicorn and httpx dependencies
and a platform-owned service launcher. Build complete SHA-256-locked binary
wheelhouses before execution, then install offline in digest-pinned images.
[pip documents hash checking for all pinned dependencies and binary-only installs](https://pip.pypa.io/en/stable/topics/secure-installs/).

Bootstrap accepts a typed profile/service request. The platform resolves and
freezes the actual image ID, platform, dependency manifest and launcher identity
in nullable `SourceSnapshot.environment_definition`. The original PRD/configuration
bytes stay separate. New non-null bindings enter the Source fingerprint and Gate
state; old NULL bindings retain the exact original fingerprint/hash semantics.
No historical snapshot or execution is backfilled or rebound. An idempotent replay
returns its original binding before resolving a mutable image tag again.

The API service and pytest share one short-lived container with `--network none`.
Docker's none driver retains only loopback, enabling real HTTP without exposing a
host port or granting outside network access. [Docker network isolation](https://docs.docker.com/engine/network/drivers/none/).
The Runner owns startup, bounded HTTP readiness, test invocation, service exit
observation, log collection and cleanup. The fixed address is injected through
`HYPERTEST_BASE_URL`; it is not a browser or remote SIT URL. Only a typed ASGI
`module:attribute` entry point, local health path and bounded startup timeout are
accepted. There is no submitted shell, package-install command or image reference.

## Options considered

| Option | Complexity / resources | Trade-off |
|---|---|---|
| One isolated container, service plus HTTP tests | Small, fits the 2CPU/4GB deployment | Tests and application share a namespace; all workloads remain untrusted code inside the existing Docker boundary |
| Internal network with separate service/client containers | More lifecycle and recovery state | Better process separation; unnecessary for the first single-service path |
| Install repository requirements during each Run | Unbounded dependency/network behavior | Does not satisfy reproducible, approved-environment execution |
| External SIT URL | Needs network/identity/secret policy | Separate capability; it cannot inherit the isolated container's safety claim |

## Consequences

- Agent produces HTTP test proposals; Runner produces the actual service and
  execution facts; HyperTest still owns acceptance, evidence and decisions.
- Readiness is an environment fact, never a passing Case or quality verdict.
  Startup/early-exit/collector failures are inconclusive execution errors.
- Execution revalidates the frozen image ID and records dependency/launcher and
  service identities. Missing or altered environments fail closed; no pull,
  installation, fallback or automatic replay occurs.
- New snapshots need migration0011; old FINAL verdict hashes remain stable.
- External databases, multi-service composition, arbitrary dependencies, secrets,
  remote SIT and other language/framework profiles need explicit later contracts.

## Action items

Implementation, meaningful regressions, real Web/model/Docker success and business
failure diagnosis, preservation, and exact release identities are recorded in
`docs/CONTROLLED_ENVIRONMENT_ACCEPTANCE.md`. Production synchronization remains a
separate merge/deployment step.
