# HyperTest One MVP status

This document separates the usable single-operator testing workflow from the longer-term product roadmap. The foundation documents remain authoritative for domain ownership, protocol, and evidence trust.

## Implemented workflow

The primary **Run test cycle** action submits durable work to PostgreSQL. An independent Worker drives the stages below through a bounded controller. Operators prepare a managed GitHub HTTPS checkout in Web or provide an existing matching checkout, then choose a Runner once; HyperTest follows deterministic Planner decisions, verifies Agent proposals, executes official tests, and evaluates the Gate. Individual stage actions remain available for inspection and intervention.

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

The Web workbench exposes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, Verdicts, and Tasks. Its background task monitor polls durable work every 1.5 seconds; canonical state refreshes every 5 seconds. Operators can inspect task timelines, errors, cancellations and linked retries alongside Mission attempts, proposals, validation failures, runner results, artifact contents, saved PRD/configuration inputs with checksum verification, finding evidence, and decision rationale. Refreshing the page does not submit duplicate work. Active cancellation interrupts controlled external work; explicit replanning creates a new Mission generation while retaining cancelled history. The product does not require a chat conversation.

Cycle execution is user-triggered and bounded: Web uses 12 planning steps per Job, with a supported limit of 1–32. Job submission returns 202; refreshing or closing the browser does not end the work. Completed steps are persisted by their owning services. A rejected Proposal, active external work, runtime error, or step limit stops the work visibly; another request resumes from canonical state. The controller follows Planner reasons such as `EXECUTION_REQUIRED`, `EXECUTION_IN_PROGRESS`, and `VERDICT_REQUIRED`; it does not become an LLM reasoning loop.

PostgreSQL `durable_jobs` stores request identity, inputs, state/result, cancellation, and retry lineage. Only one active request is allowed per Run. Independent Workers claim jobs using SKIP LOCKED, renew leases, and fence canonical commits with their live token. Worker shutdown or expired leases produce explicit interruptions; unfinished Mission Attempts and Executions retain failure history. No automatic replay occurs after a lease expires because external work may already have run. Explicit retry creates a new Job. Job success is distinct from a passing quality Verdict. Worker liveness is exposed through capabilities; queued work with no available Worker is visible. Time-based project scanning and unattended release automation remain outside this iteration.

Mission Attempts and Executions carry immutable nullable `durable_job_id` relationships, guarded for matching Run and allowed operation; existing synchronous history remains unowned. Recovery uses those links rather than timestamp inference across machine clocks. The compatibility direct controller checks ownership before and after each Planner step, so a queued request admitted between commits stops further direct work; the entire legacy loop is not exclusively reserved.

Run creation uses Source → Requirements → Policy → Review. Operators select shared and category-specific design dimensions and gate-blocking Finding severities; the immutable resulting Policy is visible in the Run inputs and coverage rule/hash.

## Current trust and coverage boundaries

- Agent output is a Proposal. HyperTest alone validates and commits Canonical State.
- Runner-generated metadata, stdout, stderr, and JUnit are collected independently of Agent assertions. Artifact contents are addressed by SHA-256 and verified when read and when the gate consumes them.
- PostgreSQL stores canonical entities, relational traceability, audit events, and transactional outbox rows. Outbox publishing infrastructure is a later operational extension.
- SourceSnapshot and PolicySnapshot UPDATE/DELETE guards preserve immutable inputs. Once a Mission leaves CREATED, its identity, spec, objective, protocol, priority, and request identity remain frozen; retry cannot return it to draft or erase history. Mission creation, acceptance, interruption, rejection, timeout, and cancellation use transactional lifecycle Audit/Outbox records.
- Test design coverage defaults to `FUNCTIONAL` plus the applicable risk-specific dimension. Immutable PolicySnapshot rules can configure global and category-specific dimensions through `coverage.default_dimensions` and `coverage.by_category`; FUNCTIONAL remains mandatory. The compiler rejects unsupported rules before storing Policy state. Planner, Verifier, Gate, and Web share the resolved rule version and hash. Dimensional coverage remains deterministic, not a claim of semantic completeness.
- The gate requires complete identification/design coverage and successful latest OFFICIAL results for every active TestCase, matching source commit, verified trusted execution metadata and JUnit, and no policy-blocking confirmed product defect. Missing or inconclusive facts produce `BLOCKED`; observed failures or blocking defects produce `RELEASE_BLOCKED`; complete passing facts produce `RELEASE_READY`.
- Gate reads, canonical proposal commits, and Runner updates to shared implementations use a SourceSnapshot lock after the Run lock, preserving consistent decisions across Runs sharing the same source. The lock does not span actual test/provider execution. Verdict hashing binds the rule version and computed decision alongside canonical inputs and artifact integrity; reuse additionally matches the decision and evidence manifest, preserving append-only history when evaluation changes.
- The gate's baseline does not waive official execution or trusted evidence. The currently configurable gate policy is `gate.blocking_finding_severities`; `BLOCKER` always blocks.
- Finding deduplication currently scopes the affected component to the TestRun and referenced cases. Historical cross-run recurrence analysis remains a separate extension.
- Generated tests are separate assets from the immutable application commit. Runner overlays are limited to safe Python paths under `tests/`; they cannot replace tracked application files.

## Operating mode

This MVP is for one trusted operator in a controlled development or test environment. It does not include application login, tenant isolation, project RBAC, or hardened public deployment. Keep its API and Web access within that operating boundary. A Docker daemon and authenticated Agent CLI are privileged host integrations managed by the operator.

The trusted Docker Runner uses a prebuilt Python/pytest image, records its resolved image identity, and executes with networking disabled, a read-only root filesystem, dropped capabilities, a non-root user, and resource limits. Build the image before execution. Project-specific dependencies must be preinstalled in an appropriate trusted image; execution does not install them.

The local Runner is an explicit development fallback enabled with `HYPERTEST_RUNNER_ALLOW_LOCAL=true`. It executes trusted code as a host process and provides no container isolation. Its provenance still comes from the Runner collector; enabling it is not a claim that host processes are sandboxed.

Agent execution requires a Codex CLI available and authenticated on the Worker host, plus a checkout accessible under `HYPERTEST_WORKSPACE_ROOT` matching the pinned repository and commit. API and Worker share the same database, Artifact Store, Workspace Root, and integration configuration. Web can prepare/reuse managed checkouts for credential-free GitHub HTTPS URLs through the existing Git proxy/authentication; other hosts use a supplied checkout path. It does not reset operator checkouts. Source preparation and official execution reject mismatched or modified tracked files. Agents work in temporary copies; Agent Sessions and provider telemetry are operational data, never canonical domain state. Lease fencing prevents stale canonical commits; external execution is not exactly-once.

Docker staging/execution containers and precreated source/result volumes carry the owning Job UUID. Expired-job recovery commits interrupted state first, then performs best-effort cleanup outside database locks, removing only matching managed resources and recording paired `job.resources_cleanup` Audit/Outbox events with availability and removal counts. An unreachable Docker daemon or orphan provider process still requires operator inspection before retry.

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

PostgreSQL integration tests exercise the canonical Planner chain, configurable dimensional coverage, Mission lifecycle events, durable queue behavior, and the delivery layers. Dedicated regressions verify immutable input snapshots and Mission contracts alongside immutable execution input, immutable Evidence content, append-only FINAL Verdicts with controlled revocation, and active Finding fingerprint uniqueness while preserving resolved history. The migration chain now extends through `0008_job_ownership`, after the input guards and durable queue migrations.

The bounded controller is tested against real PostgreSQL and real pytest execution, including continuation after a step limit. Queue checks cover idempotency, concurrent claims, durable cancellation, interruption/retry, and rejection of stale lease commits. `scripts/dev.sh --check` verifies migrations and API/Worker imports; normal invocation starts the installed host API, independent Worker, and Node.js 22 Web, with configurable development ports and cleanup of its own processes.

Live Codex acceptance remains unverified. Follow-up diagnosis confirmed that ordinary managed-shell startup requires writable Codex runtime state; an approved diagnostic command passed initialization, then model access was blocked by proxy CONNECT 403 for both WebSocket and HTTPS probes. Runtime permission and model connectivity must both be provisioned; invalid credentials were not established. See [Codex runtime troubleshooting](CODEX_RUNTIME_TROUBLESHOOTING.md) for evidence and deployment conditions. Canonical controller tests use a provider-neutral test harness and do not establish successful live-model execution.

Real provider credentials, a running Docker daemon, and repository-specific application dependencies are external operating prerequisites. Passing local tests alone does not establish that those integrations are available on another deployment; the Web capabilities panel reports installed Agent and Runner choices.

## Secondary roadmap

These are extensions to the current operable workflow, not hidden prerequisites for completing a supported run:

- Additional Agent harnesses and capability negotiation.
- More test languages, frameworks, Runner backends, and trusted environment images.
- Semantic coverage evaluation beyond the configurable deterministic test dimensions.
- Automated repair/retest selection, change impact, and cross-run knowledge reuse.
- Time-based project scheduling and automatic outbox delivery beyond the user-triggered durable queue.
- Object storage and signed evidence manifests beyond the local content-addressed store.
- Authentication, authorization, multi-user/tenant isolation, and hardened production deployment.
- Direct Requirement-to-TestCase links when needed beyond the existing relational Risk path.
- Cleanup of legacy Alembic/ORM enum-length and index metadata differences unrelated to delivery; new delivery table definitions match their ORM metadata.
