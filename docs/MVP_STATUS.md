# HyperTest One MVP status

This document separates the usable single-operator testing workflow from the longer-term product roadmap. The foundation documents remain authoritative for domain ownership, protocol, and evidence trust.

## Release and acceptance baseline

The development and pre-upgrade deployment baseline is main `79d329299d038ff9e6a3fe1659fb27bf589062c1`: its required backend checks passed with **223 tests / 3 warnings**, and both [CI jobs](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39033073576) succeeded. The four historical real Codex/model/Docker chains ran on `89d15ae` (the local analysis portion began on `5b1b7ce`); those execution identities and results remain unchanged. The 79d server synchronization independently preserved 64 API resource paths and all 12 Evidence/input artifacts.

The final frozen working tree above 79d passed **302 backend tests / 3 warnings (32.87s)**, Ruff and dedicated-test-DB Alembic head `0008_job_ownership`. All 23 Web inputs remain hash-identical to the independent installation that passed typecheck, production build and npm audit 0; the backend-only final URL rejection patch did not rerun Web checks. The [check report](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-checks-2026-10-17.md) records the exact 86 backend and 23 Web inputs, commands and manifest `6ea1934a8a4a577d6990e38eda11a49c1727b9505b333d416d961b207f68e85f`.

New live Web Run `01a149ff-2749-7ecc-b5f4-5a02307cb7b0` completed automatic GitHub source preparation, real Codex/model proposals, trusted Docker execution, evidence and FINAL **RELEASE_READY**: 7 Requirements, 6 Risks, 9 Cases, 9 Implementations, 1 Execution, 4 verified Evidence; JUnit **34 tests / 0 failures / 0 errors / 0 skipped**. The first Risk call was cancelled through Web after a long interval without new events; a linked explicit retry preserved all history and reused the accepted Requirements. Task → Verdict → JUnit navigation and original Attempt summaries were verified in the actual bilingual Web.

That live cycle used the 298-test frozen source manifest `0a34e3356d1b2f37b2731b160730747b5dcfa49e9e549c59ad94c8c7e29f1273`. A subsequent rejection-path-only URL parser hardening and four API regressions passed the final 302-test suite; valid GitHub behavior was unchanged. The running model process identity is not rewritten as a later commit. This iteration did not rerun the already accepted failure-diagnosis chains. See [first-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) for the itemized current-versus-historical matrix and [delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-delivery-2026-10-17.md) for the final commit and actual deployment/readiness identity.

## Implemented workflow

The primary **Run test cycle** action submits durable work to PostgreSQL. An independent Worker drives the stages below through a bounded controller. A cycle request selects exactly one source mode: automatic pinned GitHub HTTPS checkout (`prepare_workspace: true`), or an existing matching workspace path. Automatic preparation runs inside that same `ADVANCE_RUN` Job before any Mission; the standalone `PREPARE_WORKSPACE` action remains available. Operators choose a Runner once; HyperTest follows deterministic Planner decisions, verifies Agent proposals, executes official tests, and evaluates the Gate. Individual stage actions remain available for inspection and intervention.

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

Before Git or Agent work, the cycle performs a read-only Runner fingerprint check against the actual Docker daemon/trusted image or the explicit local-development opt-in. It releases Run/Job locks before this I/O and revalidates its lease/admission afterward. Failure starts no Git/Agent/Mission, creates no Execution/Evidence and performs no image pull or install. Readiness is operational and may change before official execution; a separate Gate-only action does not depend on it.

Automatic preparation releases database Run/Job row locks before Git I/O, then rechecks ownership and the live lease before further dispatch. Preparation failure starts no Agent; preparation is a prelude rather than a planning step. The cycle result includes the resolved workspace for subsequent operator actions. A controlled `MISSION_REJECTED` or `MISSION_FAILED` stop leaves its Job `FAILED` while preserving the stop reason, already-persisted steps and available related identities in `result`. A failed Mission is not reported as merely in progress and is not silently replayed. Generic runtime failures need not have a partial result. Historical Job payloads missing the additive `prepare_workspace: false` default compare equivalently in memory; their stored immutable payloads are never rewritten.

PostgreSQL `durable_jobs` stores request identity, inputs, state/result, cancellation, and retry lineage. Only one active request is allowed per Run. Independent Workers claim jobs using SKIP LOCKED, renew leases, and fence canonical commits with their live token. Worker shutdown or expired leases produce explicit interruptions; unfinished Mission Attempts and Executions retain failure history. No automatic replay occurs after a lease expires because external work may already have run. Explicit retry creates a new Job. Job success is distinct from a passing quality Verdict. Worker liveness is exposed through capabilities; queued work with no available Worker is visible. Time-based project scanning and unattended release automation remain outside this iteration.

Mission Attempts and Executions carry immutable nullable `durable_job_id` relationships, guarded for matching Run and allowed operation; existing synchronous history remains unowned. Recovery uses those links rather than timestamp inference across machine clocks. The compatibility direct controller checks ownership before and after each Planner step, so a queued request admitted between commits stops further direct work; the entire legacy loop is not exclusively reserved.

Run creation uses Source → Requirements → Policy → Review. Operators select shared and category-specific design dimensions and gate-blocking Finding severities; the immutable resulting Policy is visible in the Run inputs and coverage rule/hash.

The interface supports Chinese and English with a persisted browser preference,
localized component controls, dates, state labels and validation messages. Project
and run drafts survive closing/reopening the dialog and switching language within
the page. UTF-8 Markdown/text PRDs can be imported into the editable requirements
field. Task completion is explicitly separated from quality decisions; task steps
and Verdict relations link directly to recorded execution, evidence and findings.
Temporary polling errors preserve loaded data and the selected result tab.
Uncertain task submissions recover the saved Job by request identity before any
explicit retry. Bootstrap rejects reuse of a request key for different substantive
inputs before writing artifacts; branch reference labels follow the existing
SourceSnapshot identity rules. See the [Web workflow guide](WEB_PRODUCT_WORKFLOW.md).

The prior browser acceptance exercised pasted Chinese PRD text. Actual file import remains unverified: Chrome extension “Allow access to file URLs” was disabled, so only the file chooser entry and source implementation were inspected. It must not be reported as a completed import acceptance.

## Current trust and coverage boundaries

- Agent output is a Proposal. HyperTest alone validates and commits Canonical State.
- Repository origins cannot embed passwords, or HTTP(S) usernames/tokens. Authentication belongs to host Git configuration; SSH usernames and existing credential-free local/scp-style origins retain their identity. Creation rejects unsafe inputs before snapshot/Run/artifact writes. Runtime also rejects historical credential-bearing snapshots before creating an Agent Session or Attempt, without rewriting them. HTTP 422 details expose only `type`, `loc` and `msg`, omitting submitted `input`, validator `ctx` and raw request values. This guard does not scan paths/query strings for arbitrary secrets or establish comprehensive log redaction.
- Materialized Web input sets require readable, hash-matching PRD and configuration artifacts before an Agent Session starts. A missing configuration artifact is an error even when its intended content is empty. Legacy direct hash-only snapshots with no PRD artifact URI retain their optional configuration context; any materialized configuration is still checked. Compatibility does not alter immutable hashes or reconstruct missing truth.
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

The Codex adapter passes its UTF-8 Mission prompt through the official CLI stdin interface (`codex exec -`), while keeping the strict output schema, CLI-written final-result file, read-only sandbox and noninteractive approval policy. Concurrent pipe draining avoids blocking telemetry behind prompt transport. The multi-megabyte subprocess regression establishes transport without argv size failure; it does not establish provider context-window capacity. The current supported harness is Codex; full domain MCP tools, `WAITING_INPUT` question/answer/resume, additional harnesses and capability-based selection remain roadmap work.

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

Historical local live acceptance is complete for the supported stdlib/pytest backend workflow. Real Codex proposals produced the canonical analysis/design/implementation chain, and the trusted Docker Runner produced official evidence. The passing source yielded FINAL `RELEASE_READY`; the defective source yielded actual failures, a real diagnosis Finding, and FINAL `RELEASE_BLOCKED`. The operator then used Web to triage/confirm the Finding and reevaluate the Gate, appending a second blocked Verdict while retaining the first. Initial PARTIAL/REJECTED implementation attempts and FAILED Jobs remain visible; explicit retries created new linked work and accepted real model output.

The Debian 13 server independently passed both historical live-model/Docker acceptance paths after the operator completed OAuth under the service account. All nine server Missions completed on their first Attempt. Its successful source produced 14 passing pytest instances across 11 canonical Cases and FINAL `RELEASE_READY`; its defective source produced actual failures, a new evidence-backed product Finding, and FINAL `RELEASE_BLOCKED`. The single Worker consumed the two Runs serially, and the production Web was operated through the loopback SSH tunnel. Server versions, SQL provenance, paired backup/recovery, and exact identities are recorded in [first-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) and [server operations](SERVER_OPERATIONS.md).

The historical live-integration implementation `89d15ae` passed **212 backend tests** with three warnings, Web install/typecheck/build, npm audit with zero reported vulnerabilities, and both backend/Web CI jobs. [First-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) records exact identities, hashes, SQL traceability, Web evidence, supported scope, and separately maintained server results. The [old cloud diagnosis](CODEX_RUNTIME_TROUBLESHOOTING.md) remains historical EROFS/CONNECT 403 evidence; it did not establish invalid credentials. Canonical controller fixture tests and local live acceptance remain different evidence, and neither substitutes for another host's actual integration checks.

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
