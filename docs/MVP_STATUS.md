# HyperTest One MVP status

This document separates the usable single-operator testing workflow from the longer-term product roadmap. The foundation documents remain authoritative for domain ownership, protocol, and evidence trust.

## Implemented workflow

The primary **Run test cycle** action drives the stages below through a bounded controller. Operators prepare a managed GitHub HTTPS checkout in Web or provide an existing matching checkout, then choose a Runner once; HyperTest follows deterministic Planner decisions, verifies Agent proposals, executes official tests, and evaluates the Gate. Individual stage actions remain available for inspection and intervention.

| Stage | Operator action in Web | Canonical result |
|---|---|---|
| Project | Create a project | Project |
| Inputs | Create a run with repository URL, full commit SHA, PRD text, configuration text, and policy | Immutable SourceSnapshot and PolicySnapshot; TestRun |
| Requirements | Plan, then execute ANALYZE_REQUIREMENTS | Canonical Requirement and accepted proposal provenance |
| Risk identification | Plan, then execute ANALYZE_RISKS | Risk and relational RequirementRisk links |
| Test design | Plan, then execute DESIGN_TESTS until dimensional gaps close | TestCase and relational RiskTestCase links |
| Automation | Plan, then execute IMPLEMENT_TESTS | TestImplementation, immutable generated test artifacts, ImplementationTestCase links |
| Official execution | Execute tests with an available Runner | TestExecution, per-case results, checksum-verified Evidence and ExecutionEvidence links |
| Diagnosis | Plan, then execute DIAGNOSE_FAILURE when official facts show failures | Evidence-backed Finding proposals |
| Finding management | Inspect, triage, confirm, resolve, close, or reopen a finding | Controlled lifecycle transition, reason, AuditEvent and OutboxEvent |
| Quality decision | Evaluate quality gate | Append-only Verdict, state hash, evidence manifest hash, evidence/finding links |

The Web workbench exposes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, and Verdicts. Operators can inspect Mission attempts, proposals, validation failures, runner results, artifact contents, saved PRD/configuration inputs with checksum verification, finding evidence, and decision rationale. Active Mission cancellation interrupts running work; disposable Agent/Runner processes are cleaned up. Explicit replanning creates a new Mission generation while retaining cancelled history. State refreshes while work runs. The product does not require a chat conversation.

Cycle execution is user-triggered and bounded: Web uses 12 planning steps per request; `POST /test-runs/{id}/advance` permits 1–32. Completed steps are persisted by their owning services. A rejected Proposal, active external work, runtime error, or step limit stops the request visibly; another request resumes from canonical state. The controller follows Planner reasons such as `EXECUTION_REQUIRED`, `EXECUTION_IN_PROGRESS`, and `VERDICT_REQUIRED`; it does not become an LLM reasoning loop. An unattended background scheduler is not part of this MVP.

## Current trust and coverage boundaries

- Agent output is a Proposal. HyperTest alone validates and commits Canonical State.
- Runner-generated metadata, stdout, stderr, and JUnit are collected independently of Agent assertions. Artifact contents are addressed by SHA-256 and verified when read and when the gate consumes them.
- PostgreSQL stores canonical entities, relational traceability, audit events, and transactional outbox rows. Outbox publishing infrastructure is a later operational extension.
- Test design coverage requires `FUNCTIONAL` plus the applicable risk-specific dimension. It is a deterministic baseline behind `RiskCoverageEvaluator`, not a claim of semantic completeness.
- The gate requires complete identification/design coverage and successful latest OFFICIAL results for every active TestCase, matching source commit, verified trusted execution metadata and JUnit, and no policy-blocking confirmed product defect. Missing or inconclusive facts produce `BLOCKED`; observed failures or blocking defects produce `RELEASE_BLOCKED`; complete passing facts produce `RELEASE_READY`.
- The gate's baseline does not waive official execution or trusted evidence. The currently configurable gate policy is `gate.blocking_finding_severities`; `BLOCKER` always blocks.
- Finding deduplication currently scopes the affected component to the TestRun and referenced cases. Historical cross-run recurrence analysis remains a separate extension.
- Generated tests are separate assets from the immutable application commit. Runner overlays are limited to safe Python paths under `tests/`; they cannot replace tracked application files.

## Operating mode

This MVP is for one trusted operator in a controlled development or test environment. It does not include application login, tenant isolation, project RBAC, or hardened public deployment. Keep its API and Web access within that operating boundary. A Docker daemon and authenticated Agent CLI are privileged host integrations managed by the operator.

The trusted Docker Runner uses a prebuilt Python/pytest image, records its resolved image identity, and executes with networking disabled, a read-only root filesystem, dropped capabilities, a non-root user, and resource limits. Build the image before execution. Project-specific dependencies must be preinstalled in an appropriate trusted image; execution does not install them.

The local Runner is an explicit development fallback enabled with `HYPERTEST_RUNNER_ALLOW_LOCAL=true`. It executes trusted code as a host process and provides no container isolation. Its provenance still comes from the Runner collector; enabling it is not a claim that host processes are sandboxed.

Agent execution requires a Codex CLI available and authenticated on the API host, plus a checkout accessible under `HYPERTEST_WORKSPACE_ROOT` matching the pinned repository and commit. Web can prepare/reuse managed checkouts for credential-free GitHub HTTPS URLs through the existing Git proxy/authentication; other hosts use a supplied checkout path. It does not reset operator checkouts. Source preparation and official execution reject mismatched or modified tracked files. Agents work in temporary copies; Agent Sessions and provider telemetry are operational data, never canonical domain state.

See [README](../README.md) for setup commands and [the domain specification](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md) for canonical constraints.

## Verification

Required repository checks are:

```bash
ruff check src tests alembic
alembic upgrade head
pytest -q
cd web
npm ci
npm run typecheck
npm run build
```

PostgreSQL integration tests exercise the canonical Planner chain and the delivery layers. Migration validation covers a clean database through `0005_delivery`, empty delivery downgrade/reupgrade, and delivery model/schema parity. Dedicated PostgreSQL regressions verify immutable execution input, immutable Evidence content, append-only FINAL Verdicts with controlled revocation, and active Finding fingerprint uniqueness while preserving resolved history.

The bounded controller is tested against real PostgreSQL and real pytest execution, including continuation after a step limit. `scripts/dev.sh --check` verifies migrations and API imports; normal invocation starts the installed host API and Node.js 22 Web, with configurable development ports and cleanup of its own processes.

During this implementation's cloud validation, Codex reported an available login, but live app-server startup failed with `EROFS` against managed read-only runtime state, including attempts with supported ephemeral/log/sqlite path overrides. This is a limitation observed in that cloud instance; missing credentials were not established. Canonical controller tests use a provider-neutral test harness, so they do not establish successful live-model execution there.

Real provider credentials, a running Docker daemon, and repository-specific application dependencies are external operating prerequisites. Passing local tests alone does not establish that those integrations are available on another deployment; the Web capabilities panel reports installed Agent and Runner choices.

## Secondary roadmap

These are extensions to the current operable workflow, not hidden prerequisites for completing a supported run:

- Additional Agent harnesses and capability negotiation.
- More test languages, frameworks, Runner backends, and trusted environment images.
- Policy-defined multidimensional risk/semantic coverage beyond the deterministic baseline.
- Automated repair/retest selection, change impact, and cross-run knowledge reuse.
- Background job scheduling, durable worker restart/recovery, and automatic outbox delivery.
- Object storage and signed evidence manifests beyond the local content-addressed store.
- Authentication, authorization, multi-user/tenant isolation, and hardened production deployment.
- Direct Requirement-to-TestCase links when needed beyond the existing relational Risk path.
- Cleanup of legacy Alembic/ORM enum-length and index metadata differences unrelated to delivery; new delivery table definitions match their ORM metadata.
