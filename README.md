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

The current product targets **one trusted operator** in a controlled development/test environment. Application login, tenant isolation, RBAC, and hardened public deployment are future work.

## Use the Web workbench

```text
/                         Create and browse projects
/projects/{project_id}    Create runs from pinned source inputs
/runs/{test_run_id}       Operate the testing cycle and inspect canonical state
```

1. Create a Project.
2. Create a Run with repository URL, full Git commit SHA, PRD text, optional configuration text, and policy. HyperTest stores the PRD artifact and fixes immutable SourceSnapshot and PolicySnapshot identities.
3. Select **Run test cycle**, use **Prepare pinned checkout** for a supported GitHub HTTPS repository (or provide an existing matching checkout), choose the trusted Runner, and start. HyperTest plans and verifies requirement/risk/design/implementation Missions, executes official tests, diagnoses failures when appropriate, and evaluates the quality gate.
4. Watch canonical state, Mission attempts, proposals, executions, and Evidence populate. Each request advances at most 12 planning steps in Web; completed work persists. If the work limit is reached, review progress and continue the cycle.
5. If a Proposal is rejected or another Mission/execution is active, the cycle stops with an explicit reason. Inspect the affected step and correct or resume it. Agent runtime failures remain visible in Attempt history.
6. Inspect the final quality verdict, rationale, canonical state hash, evidence manifest hash, and history. Findings support controlled triage, confirmation, resolution, closure, and reopening with a recorded reason.

Individual **Plan next mission**, Mission execution, **Execute tests**, and **Evaluate quality gate** controls remain available for inspection and intervention. Cancelled/expired Missions retain their immutable specification and history; explicitly planning again creates a new generation when the work is still needed. Generated Python tests become checksum-addressed artifacts linked to canonical TestCases; the application commit stays fixed.

The Run workbench includes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, and Verdicts. Attempts, rejected proposals, execution errors, artifact content, and finding transitions are inspectable. Operations refresh their state while work runs.

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

The **Run test cycle** action invokes a bounded control-plane controller. It follows deterministic Planner decisions and delegates to Mission Runtime, Runner, and Gate; it does not orchestrate model reasoning. Completed steps are durable and subsequent requests resume from canonical state. An unattended background scheduler is secondary work.

## Coverage and decisions

`RiskCoverageEvaluator` requires FUNCTIONAL for every non-obsolete Risk, plus BOUNDARY, FAILURE, CONCURRENCY, SECURITY, or PERFORMANCE for the corresponding category; RELIABILITY additionally requires RECOVERY. Only relationally linked ACTIVE TestCases contribute. The component can later accept richer policy dimensions without changing Planner into an LLM Agent.

The workbench displays eligible Requirement/Risk/TestCase counts, Risk identification coverage, Risk test coverage, and each Risk's required/covered/missing dimensions. Empty denominators return `null` and display as unknown.

The gate requires full identification/design coverage and every active Case's latest OFFICIAL execution to match the source commit, complete successfully, and provide verified trusted metadata and JUnit artifacts. Confirmed policy-blocking product defects prevent release. Missing facts produce `BLOCKED`, observed failures produce `RELEASE_BLOCKED`, and complete passing facts produce `RELEASE_READY`. Design coverage alone never produces a release decision.

## Run the complete development workflow

Use Python 3.12, PostgreSQL 17, Node.js 22, Git, a Docker CLI/daemon, and a Codex CLI available and authenticated on the API host. API-host execution preserves the operator's existing Agent authentication and repository access.

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

Install Web dependencies, configure the API host, and start both services:

```bash
npm --prefix web ci
export HYPERTEST_ARTIFACT_ROOT="$PWD/.hypertest-artifacts"
export HYPERTEST_WORKSPACE_ROOT=/workspace
bash scripts/dev.sh
```

The helper requires the installed `.venv` and `web/node_modules`, verifies Node.js 22, applies migrations, and starts API/Web on loopback. Exiting the helper cleans up its own service processes. Set `HYPERTEST_DEV_API_PORT` / `HYPERTEST_DEV_WEB_PORT` to override defaults 8000 / 3000. `bash scripts/dev.sh --check` applies migrations and verifies API imports without starting services.

`HYPERTEST_WORKSPACE_ROOT` must contain the repository checkout paths supplied through Web. **Prepare pinned checkout** creates or reuses a clean pinned checkout under `.hypertest-checkouts/{source_snapshot_id}/repo` inside that root. Automatic preparation supports credential-free `https://github.com/owner/repository` URLs, uses the existing Git proxy/authentication, and does not reset operator checkouts. Other hosts retain the existing-workspace path. Each checkout must have the matching origin, full pinned commit at HEAD, and clean tracked content. Agent work and generated-test execution use temporary copies; keep the source checkout at its pinned commit.

To start each service manually instead, run `uvicorn hypertest.main:app --host 127.0.0.1 --port 8000` in the activated Python environment, then start Web in another terminal:

```bash
cd web
HYPERTEST_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1
```

```text
Web:      http://localhost:3000
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
```

The capabilities panel reports installed Agent and Runner choices. Codex authentication, checkout access, a usable Docker daemon, and the trusted image must exist on the API host before their respective actions can succeed.

For a controlled local-development fallback, explicitly set `HYPERTEST_RUNNER_ALLOW_LOCAL=true` before starting the API and select the local Runner. It runs trusted repository code as a host process; it is not a container sandbox. Docker remains the default Runner.

`docker compose up --build` can host the database/API/Web browsing stack. The default API container does not inherit the host's Agent login, tools, checkouts, or artifact configuration. Use the host workflow above for working Missions and official Runner execution unless those integrations are explicitly provisioned for the container.

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
```

The prepare-workspace endpoint needs no request body and returns `workspace`, `repository_url`, and the pinned `commit_sha`. PRD and configuration text reads verify their saved snapshot checksums.

The advance request accepts `workspace`, `backend` (`docker` by default), `timeout_seconds`, and `max_steps` (default 12, range 1–32). It runs real Mission/Runner/Gate services until a final Verdict, interruption, rejection, or work limit; the HTTP API does not accept synthetic Agent results. The response includes completed steps and a stop reason.

The bootstrap request accepts `repository_url`, a full 40- or 64-character `commit_sha`, `prd_text`, optional `branch`, `configuration_text`, `policy`, and `idempotency_key`. Retrying the same project/key returns its original Run. A supported policy example is:

```json
{
  "gate": {
    "blocking_finding_severities": ["BLOCKER", "CRITICAL"]
  }
}
```

## Migrations and validation

`0004_test_design` creates TestCase and RiskTestCase. `0005_delivery` adds canonical implementations, executions, evidence, findings, verdicts, relational links, proposal types, and immutable-history guards. It widens the original proposal-type column to accommodate `TEST_IMPLEMENTATION`. Upgrade from a clean database applies `0001 → 0002 → 0003 → 0004 → 0005`.

Backend validation requires a real PostgreSQL database:

```bash
ruff check src tests alembic
alembic upgrade head
pytest -q
```

Web validation:

```bash
cd web
npm ci
npm run typecheck
npm run build
```

GitHub Actions runs backend checks against PostgreSQL 17 and the mandatory Web job on Node.js 22, installing each job's dependencies once. Tests cover the canonical Planner cycle, proposal boundaries, trusted Runner facts, evidence integrity, finding lifecycle, deterministic Gate decisions, Web APIs, and PostgreSQL history constraints.
