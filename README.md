# HyperTest One

> **One Input. One Mission. One Complete Test Cycle.**

HyperTest One is an autonomous testing control plane with a state-centered Web workbench. It governs the complete supported testing cycle:

```text
Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding → Verdict
```

**Agent produces intelligence. Runner produces facts. HyperTest produces decisions.**

Agents submit proposals; HyperTest validates and commits canonical state. PostgreSQL owns traceability, snapshots, audit, and transactional outbox records. Agent sessions are temporary and replaceable.

## Foundation and implementation status

Read these before changing the architecture or domain:

1. [Whitepaper](docs/foundation/HYPERTEST_WHITEPAPER.md)
2. [Technical architecture](docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)
3. [Test Mission Protocol](docs/protocol/TEST_MISSION_PROTOCOL.md)
4. [Canonical domain model and state machines](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)

[Current MVP status](docs/MVP_STATUS.md) records implemented capabilities, trust boundaries, verification, and the secondary roadmap.

[First-phase acceptance](docs/FIRST_PHASE_ACCEPTANCE.md) records actual checks and live
integration evidence. [Server operations](docs/SERVER_OPERATIONS.md) contains the
deployed release, SSH access, service management, and paired backup/recovery steps.

The current product targets **one trusted operator** in a controlled development/test environment. Application login, tenant isolation, RBAC, and hardened public deployment are future work.

## Use the Web workbench

The workbench supports **中文 / English** switching in the top-right corner, with
the choice preserved across navigation and reloads. It includes guided project/run
creation, UTF-8 Markdown/text PRD import, durable task progress and direct links
from quality decisions to evidence and findings. See the bilingual
[Web workflow guide](docs/WEB_PRODUCT_WORKFLOW.md) for the complete operating flow,
input limits, server checkout paths, and the distinction between task completion
and a passing testing verdict. The deployed environment continues to use SSH-tunnel access.

```text
/                         Create and browse projects
/projects/{project_id}    Create runs from pinned source inputs
/runs/{test_run_id}       Operate the testing cycle and inspect canonical state
```

1. Create a Project.
2. Create a Run with the repository's origin, PRD text, optional configuration, and policy. Resolve a GitHub branch/tag to a full pinned SHA, or enter the full SHA manually. HyperTest stores input artifacts and fixes immutable SourceSnapshot and PolicySnapshot identities. A checkout directory is not a replacement for its origin address.
3. Select **Run test cycle** and choose **Prepare pinned source and run automatically** for GitHub HTTPS origins, or provide an existing matching checkout on the Worker host. One durable request can prepare source and continue through verified requirement/risk/design/implementation Missions, trusted Docker execution, diagnosis when required, and the quality gate.
4. Watch canonical state, Mission attempts, proposals, executions, and Evidence populate. Work continues after refreshing or closing the page. A cycle advances at most 12 planning steps in Web; completed work persists. If the work limit is reached, review progress and continue the cycle.
5. Inspect queued/running work, errors, and stop reasons. Cancel a request or explicitly retry unsuccessful work; retries create linked history rather than overwriting old requests. Controlled Mission rejection retains recorded cycle steps. Expand an Attempt to read its original Agent summary and unresolved items separately from formal test facts. Interrupted work requires inspection and explicit retry.
6. Inspect the final quality verdict, rationale, canonical state hash, evidence manifest hash, and history. Findings support controlled triage, confirmation, resolution, closure, and reopening with a recorded reason.

Individual **Plan next mission**, Mission execution, **Execute tests**, and **Evaluate quality gate** controls remain available for inspection and intervention. Cancelled/expired Missions retain their immutable specification and history; explicitly planning again creates a new generation when the work is still needed. Generated Python tests become checksum-addressed artifacts linked to canonical TestCases; the application commit stays fixed.

The Run workbench includes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, Verdicts, and Tasks. The background task monitor and task details show queue state, timestamps, errors, cancellation, and retry history. Tasks refresh every 1.5 seconds and canonical state every 5 seconds. Refreshing the page observes saved work without submitting another request. Attempts, rejected proposals, execution errors, artifact content, and finding transitions remain inspectable.

The Planner is deterministic-first:

```text
No active Requirement                 → ANALYZE_REQUIREMENTS
Requirement without identified Risk   → ANALYZE_RISKS
Risk with missing design dimensions   → DESIGN_TESTS
TestCase without a usable implementation → IMPLEMENT_TESTS
Missing official execution            → EXECUTION_REQUIRED
Observed failure with trusted evidence → DIAGNOSE_FAILURE
Facts ready for a quality decision     → VERDICT_REQUIRED
```

The **Run test cycle** action queues a bounded control-plane controller. It follows deterministic Planner decisions and delegates to Mission Runtime, Runner, and Gate; it does not orchestrate model reasoning. PostgreSQL stores immutable Job inputs and history, and permits at most one active request per Run. Worker leases fence canonical commits. API restarts and page refreshes preserve submitted work; a Worker crash becomes an explicit interruption after its lease expires. Recovery does not automatically replay external operations. A Job's `SUCCEEDED` status means the request finished; its result and formal Verdict describe testing outcomes.

## Coverage and decisions

`RiskCoverageEvaluator` requires FUNCTIONAL for every non-obsolete Risk, plus BOUNDARY, FAILURE, CONCURRENCY, SECURITY, or PERFORMANCE for the corresponding category; RELIABILITY additionally requires RECOVERY. Only relationally linked ACTIVE TestCases contribute. Each Run's immutable PolicySnapshot can declare additional global or category-specific dimensions. Planner, Verifier, Gate, and Web use the same resolved rules and policy hash.

The workbench displays eligible Requirement/Risk/TestCase counts, Risk identification coverage, Risk test coverage, and each Risk's required/covered/missing dimensions. Empty denominators return `null` and display as unknown.

The gate requires full identification/design coverage and every active Case's latest OFFICIAL execution to match the source commit, complete successfully, and provide verified trusted metadata and JUnit artifacts. Confirmed policy-blocking product defects prevent release. Missing facts produce `BLOCKED`, observed failures produce `RELEASE_BLOCKED`, and complete passing facts produce `RELEASE_READY`. Design coverage alone never produces a release decision.

Runs sharing a SourceSnapshot serialize Gate reads with canonical proposal commits and implementation-status updates, so a decision and its state hash describe the same snapshot state. These locks are released for actual Agent/test execution. Verdict hashes bind canonical inputs, artifact integrity, the Gate rule version, and the computed decision; reuse also requires matching decision and evidence manifest. Changed evaluations append history rather than reusing a contradictory cached Verdict.

## Run the complete development workflow

Use Python 3.12, PostgreSQL 17, Node.js 22, Git, a Docker CLI/daemon, and a Codex CLI available and authenticated on the Worker host. Host-based Worker execution preserves the operator's existing Agent authentication and repository access.

Start PostgreSQL and install backend dependencies:

```bash
docker compose up -d postgres
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
```

Build the trusted Runner image before running tests:

```bash
bash scripts/build-runner-image.sh
```

The script downloads pinned pytest wheels through the host's supported HTTPS route and builds the image without package-index access inside Docker. It uses `hypertest-runner:py312` by default; set `HYPERTEST_RUNNER_IMAGE` consistently for a different image. Project-specific dependencies belong in a trusted prebuilt image. Runner execution never installs dependencies.

Install Web dependencies, configure the host, and start API, Worker, and Web:

```bash
npm --prefix web ci
export HYPERTEST_ARTIFACT_ROOT="$PWD/.hypertest-artifacts"
export HYPERTEST_WORKSPACE_ROOT="$PWD/.hypertest-workspaces"
mkdir -p "$HYPERTEST_WORKSPACE_ROOT"
bash scripts/dev.sh
```

The helper requires the installed `.venv` and `web/node_modules`, verifies Node.js 22, applies migrations, and starts API, Worker, and Web. API/Web listen on loopback. Exiting the helper cleans up its own service processes. Set `HYPERTEST_DEV_API_PORT` / `HYPERTEST_DEV_WEB_PORT` to override defaults 8000 / 3000. `bash scripts/dev.sh --check` applies migrations and verifies API/Worker imports without starting services.

The supervisor supports macOS's system Bash and Linux without GNU `setsid` or
`wait -n`. Configure paths for the actual host; `/workspace` is not a required path.
`HYPERTEST_CODEX_BINARY` selects an installed official CLI (default `codex`).
`HYPERTEST_CODEX_MODEL` optionally selects a model supported by that Worker's account.
If desktop/user CLI settings select an incompatible model, explicitly set
`HYPERTEST_CODEX_IGNORE_USER_CONFIG=true` to use the standalone CLI defaults while
retaining its existing authentication. This does not change the user's global
configuration or copy credentials. HyperTest supplies a typed output schema and
collects the CLI's saved final response; model tools remain in the read-only sandbox.

`HYPERTEST_WORKSPACE_ROOT` must contain the repository checkout paths supplied through Web. **Prepare pinned checkout** creates or reuses a clean pinned checkout under `.hypertest-checkouts/{source_snapshot_id}/repo` inside that root. Automatic preparation supports credential-free `https://github.com/owner/repository` URLs, uses the existing Git proxy/authentication, and does not reset operator checkouts. Other hosts retain the existing-workspace path. Each checkout must have the matching origin, full pinned commit at HEAD, and clean tracked content. Agent work and generated-test execution use temporary copies; keep the source checkout at its pinned commit.

To start each service manually instead, run `uvicorn hypertest.main:app --host 127.0.0.1 --port 8000` in the activated Python environment, start the Worker in a second terminal with the same configuration, then start Web in a third terminal:

```bash
source .venv/bin/activate
python -m hypertest.worker
```

```bash
cd web
HYPERTEST_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1
```

```text
Web:      http://localhost:3000
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
```

The capabilities panel reports installed Agent and Runner choices and recent Worker liveness. API and Worker must share the PostgreSQL database, artifact store, workspace root, and host integration configuration. Codex authentication, checkout access, a usable Docker daemon, and the trusted image must exist on the Worker host before their respective actions can succeed.

Worker settings default to `HYPERTEST_WORKER_LEASE_SECONDS=30`, `HYPERTEST_WORKER_HEARTBEAT_SECONDS=5`, and `HYPERTEST_WORKER_POLL_SECONDS=1`. Heartbeats must be positive and shorter than the lease. Each Worker executes one request at a time; multiple Workers can process different Runs. `python -m hypertest.worker --once` recovers expired leases and processes at most one queued request. Mission Attempts and Executions record their owning Job through immutable relational links, so recovery does not infer ownership from machine timestamps.

Worker shutdown interrupts active work. Docker staging/execution containers and their volumes carry the owning Job UUID; recovery first commits interrupted domain history, then attempts cleanup of only those labelled resources outside database locks. Cleanup availability and removal counts are audited. If Docker is unreachable, or a provider process survived a hard host/process kill, inspect external resources before retrying. The system preserves canonical history without claiming exactly-once external execution.

Local and Debian 13 server acceptance cover both supported stdlib/pytest backend paths using real Codex proposals and trusted Docker execution: passing applications produced FINAL `RELEASE_READY`; defective applications produced actual failures, evidence-backed Findings, and FINAL `RELEASE_BLOCKED`. Their original execution identity is `89d15ae` (212 tests); that history remains preserved. The later deployed main baseline `79d3292` passed 223 tests and both CI jobs. This iteration extends source resolution, automatic checkout, large-input transport and failure details; its checks and new real Web cycle are recorded separately in [first-phase acceptance](docs/FIRST_PHASE_ACCEPTANCE.md), alongside exact Run/Execution/Evidence/Verdict identities and supported scope.

The [old cloud runtime diagnosis](docs/CODEX_RUNTIME_TROUBLESHOOTING.md) retains the historical EROFS and CONNECT 403 findings; it does not describe current local or server authentication. Provider-neutral tests remain distinct from live acceptance, and supported-path results do not establish semantic completeness or another host's integration readiness.

For a controlled local-development fallback, explicitly set `HYPERTEST_RUNNER_ALLOW_LOCAL=true` for API and Worker and select the local Runner. It runs trusted repository code as a host process; it is not a container sandbox. Docker remains the default Runner.

`docker compose up --build` can host the database/API/Web browsing stack. Its default services do not start the independent Worker or inherit the host's Agent login, tools, checkouts, or artifact configuration. Use the host workflow above for working Missions and official Runner execution unless the Worker and those integrations are explicitly provisioned for the containers.

## API

All routes use `/api/v1` by default. OpenAPI documents request and response schemas.

```text
GET  /health
GET  /capabilities

POST /projects
GET  /projects
GET  /projects/{project_id}
GET  /projects/{project_id}/test-runs
POST /projects/{project_id}/source-snapshots
POST /projects/{project_id}/runs/bootstrap
POST /policy-snapshots
GET  /source-snapshots/{source_snapshot_id}
GET  /source-snapshots/{source_snapshot_id}/prd
GET  /source-snapshots/{source_snapshot_id}/configuration
GET  /policy-snapshots/{policy_snapshot_id}

POST /test-runs
GET  /test-runs/{test_run_id}
GET  /test-runs/{test_run_id}/requirements
GET  /test-runs/{test_run_id}/risks
GET  /test-runs/{test_run_id}/test-cases
GET  /test-runs/{test_run_id}/coverage
GET  /test-runs/{test_run_id}/missions
POST /test-runs/{test_run_id}/missions
POST /test-runs/{test_run_id}/plan-next
POST /test-runs/{test_run_id}/advance
POST /test-runs/{test_run_id}/prepare-workspace
POST /test-runs/{test_run_id}/jobs
GET  /test-runs/{test_run_id}/jobs
GET  /test-runs/{test_run_id}/implementations
GET  /test-runs/{test_run_id}/executions
POST /test-runs/{test_run_id}/executions
GET  /test-runs/{test_run_id}/evidence
GET  /test-runs/{test_run_id}/findings
GET  /test-runs/{test_run_id}/verdicts
POST /test-runs/{test_run_id}/evaluate

GET  /missions/{mission_id}
POST /missions/{mission_id}/execute
GET  /missions/{mission_id}/attempts
GET  /missions/{mission_id}/proposals
POST /missions/{mission_id}/retry
POST /missions/{mission_id}/cancel
GET  /executions/{execution_id}
GET  /evidence/{evidence_id}/content
POST /findings/{finding_id}/transition
GET  /jobs/{job_id}
POST /jobs/{job_id}/cancel
POST /jobs/{job_id}/retry
```

The prepare-workspace endpoint needs no request body and returns `workspace`, `repository_url`, and the pinned `commit_sha`. PRD and configuration text reads verify their saved snapshot checksums.

Web uses the Job API for long operations. `POST /test-runs/{id}/jobs` accepts `operation`, `idempotency_key`, optional `mission_id` (required only for EXECUTE_MISSION), and operation-specific `payload`, then returns HTTP 202. Supported operations are ADVANCE_RUN, EXECUTE_MISSION, EXECUTE_TESTS, EVALUATE_GATE, and PREPARE_WORKSPACE. A request to advance the Run is:

```json
{
  "operation": "ADVANCE_RUN",
  "idempotency_key": "run-cycle:request-1",
  "payload": {
    "workspace": "/workspace/my-project",
    "backend": "docker",
    "timeout_seconds": 300,
    "max_steps": 12
  }
}
```

For automatic GitHub checkout, replace `workspace` with `"prepare_workspace": true`; provide exactly one source mode. The same Worker request prepares the pinned source before starting missions. `POST /sources/resolve` accepts `repository_url` and a branch/tag `revision` before bootstrap, returning the full SHA without changing canonical state or a checkout. Other origins continue to use an existing workspace.

Poll the Run's Job list or `GET /jobs/{id}` for state and result. The same key and input return the original request; conflicting input or another active request returns 409. Cancellation returns 202. Retry accepts a new `idempotency_key` and returns 202 with a new linked Job. A cancelled Mission remains cancelled; explicitly plan a new Mission generation when its work is still needed. A FAILED Mission must first use the controlled Mission retry action before execution can be submitted again. `GET /capabilities` includes `worker.available`, `worker.last_seen_at`, and `worker.active_workers`.

The older direct `/advance`, Mission execute, Runner execute, Gate, and prepare-workspace endpoints remain available for compatibility. They run synchronously and check for conflicting queued work. The direct advance loop rechecks operation ownership before and after each Planner step and stops if a durable request was admitted between service commits; it does not hold exclusive ownership for its entire loop. The advance payload accepts `workspace`, `backend` (`docker` by default), `timeout_seconds`, and `max_steps` (default 12, range 1–32). Its controller uses real Mission/Runner/Gate services until a final Verdict, interruption, rejection, or work limit; the HTTP API does not accept synthetic Agent results. Job results retain completed steps and a stop reason.

The bootstrap request accepts `repository_url`, a full 40- or 64-character `commit_sha`, `prd_text`, optional `branch`, `configuration_text`, `policy`, and `idempotency_key`. Retrying the same project/key returns its original Run. A supported policy example is:

```json
{
  "gate": {
    "blocking_finding_severities": ["BLOCKER", "CRITICAL"]
  },
  "coverage": {
    "version": "risk-design-policy/v1",
    "default_dimensions": ["FUNCTIONAL", "FAILURE"],
    "by_category": {
      "CONCURRENCY": ["CONCURRENCY", "BOUNDARY"]
    }
  }
}
```

Global `default_dimensions` apply to every Risk. `by_category` replaces a category's specialized dimensions; unspecified categories retain the baseline specialization. FUNCTIONAL is always required, including when a configured list is empty. Unknown rules, categories, test dimensions, versions, and duplicate dimensions are rejected before creating immutable Policy state. The Coverage API exposes `rule_version` and `effective_policy_hash`; equal effective rules have the same hash regardless of dimension order. Omitting coverage preserves the original baseline.

The Web creation flow guides Source → Requirements → Policy → Review. Its Policy controls configure shared dimensions, per-category dimensions, and blocking Finding severities; FUNCTIONAL and BLOCKER remain mandatory.

Direct `POST /policy-snapshots` callers must provide `content_sha256` matching the canonical JSON of `compiled_policy` (sorted keys, compact separators, UTF-8). Bootstrap computes this digest for Web users. Creating a new PolicySnapshot does not alter existing Runs.

## Migrations and validation

`0004_test_design` creates TestCase and RiskTestCase. `0005_delivery` adds canonical implementations, executions, evidence, findings, verdicts, relational links, proposal types, and delivery history guards. `0006_immutable_contracts` adds immutable SourceSnapshot/PolicySnapshot and frozen Mission contract guards without rewriting historical rows. `0007_durable_jobs` adds operational jobs, Worker liveness, request idempotency, one-active-request-per-Run enforcement, and immutable Job history. `0008_job_ownership` adds immutable nullable Job FKs to Mission Attempts and Executions, with same-Run and supported-operation guards. Existing direct-operation history keeps null ownership. Upgrade from a clean database applies `0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008`.

Backend validation requires a real PostgreSQL database:

```bash
ruff check src tests alembic
alembic upgrade head
pytest -q
```

Tests isolate their workspace and artifact paths from the operator's `.env` settings.
For a separate local test database, create and migrate it once, then set
`HYPERTEST_TEST_DATABASE_URL` in the environment or ignored `.env` file:

```bash
docker compose exec postgres createdb -U hypertest hypertest_test
export HYPERTEST_TEST_DATABASE_URL=postgresql+asyncpg://hypertest:hypertest@127.0.0.1:5432/hypertest_test
HYPERTEST_DATABASE_URL="$HYPERTEST_TEST_DATABASE_URL" alembic upgrade head
pytest -q
```

The test database must already exist; pytest never drops, recreates, or clears a
database. Without this optional setting, tests use the configured development/CI
database, which must be disposable.

Web validation:

```bash
cd web
npm ci
npm run typecheck
npm run build
```

GitHub Actions runs backend checks against PostgreSQL 17 and the mandatory Web job on Node.js 22, installing each job's dependencies once. Tests cover the canonical Planner cycle, proposal boundaries, trusted Runner facts, evidence integrity, finding lifecycle, deterministic Gate decisions, Web APIs, and PostgreSQL history constraints.
