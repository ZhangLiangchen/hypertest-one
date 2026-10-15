# HyperTest One

> **One Input. One Mission. One Complete Test Cycle.**

**HyperTest One** is an agent-native autonomous testing platform and AI test engineering workbench. It turns a PRD, source repository, and test environment into a governed end-to-end testing cycle: requirement analysis, risk identification, test design, test implementation, execution, evidence collection, findings, and verdict.

HyperTest One does not attempt to replace general-purpose coding agents such as Codex or Claude Code. It acts as the **Autonomous Testing Control Plane** that defines testing missions, maintains canonical testing state, governs agent proposals, executes tests through trusted runners, and produces evidence-backed quality decisions.

## Core model

```text
Requirement
    ↓
Risk
    ↓
Test Case
    ↓
Implementation
    ↓
Execution
    ↓
Evidence
    ↓
Finding
    ↓
Verdict
```

> **Agent produces intelligence. Runner produces facts. HyperTest produces decisions.**

## Foundational documents

The following documents define the project-wide product, architecture, protocol, and domain-model baseline. They should be treated as global guidance for implementation and future design decisions.

1. [HyperTest Whitepaper](docs/foundation/HYPERTEST_WHITEPAPER.md)
2. [HyperTest Technical Architecture](docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)
3. [Test Mission Protocol Specification](docs/protocol/TEST_MISSION_PROTOCOL.md)
4. [HyperTest Domain Model & State Machine Specification](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)

## Current implementation

The control-plane spine now includes:

- FastAPI `/api/v1` REST surface.
- PostgreSQL + SQLAlchemy async persistence and Alembic migrations.
- Canonical entities: `Project`, `SourceSnapshot`, `PolicySnapshot`, `TestRun`, `Requirement`, `Risk`, `TestCase`, `Mission`.
- `RequirementRisk` and `RiskTestCase` relational traceability.
- `MissionAttempt`, `MissionProposal`, `AgentSession`, `AuditEvent`, and transactional `OutboxEvent`.
- UUIDv7 canonical primary keys and human-readable operational keys.
- Immutable source/policy snapshot semantics.
- Deterministic source/risk/test-intent fingerprinting and Mission spec hashing.
- Provider-neutral `AgentHarness` and thin `CodexCliAdapter`.
- TMP result boundary: provider telemetry is operational state; only `RESULT_SUBMITTED` is considered for domain verification.
- Canonical verifier for `ANALYZE_REQUIREMENTS`, `ANALYZE_RISKS`, and `DESIGN_TESTS`.
- Deterministic Planner that derives the next Mission from canonical state gaps.
- A dedicated `RiskCoverageEvaluator` for deterministic test design dimensions.
- PostgreSQL integration coverage for the continuous `Requirement → Risk → TestCase` Planner loop, idempotency, deduplication, and atomic audit/outbox persistence.

### Planner loop

```text
TestRun
  ↓ observe canonical state
Planner
  ├─ no Requirement → ANALYZE_REQUIREMENTS
  ├─ Requirement without Risk → ANALYZE_RISKS
  ├─ Risk with missing test design dimensions → DESIGN_TESTS
  └─ all Risks design-covered → TEST_DESIGN_COVERAGE_COMPLETE
```

The baseline requires `FUNCTIONAL` tests for every non-obsolete Risk, plus a matching `BOUNDARY`, `FAILURE`, `CONCURRENCY`, `SECURITY`, or `PERFORMANCE` dimension where applicable. `RELIABILITY` Risks additionally require `RECOVERY`. Only linked `ACTIVE` TestCases contribute. The evaluator is a separate component so future policy can define richer dimensions. Design coverage does not imply test execution, evidence, or a release verdict.

Each design Mission receives canonical Risks and an immutable description of missing dimensions. A submission must contribute to at least one currently missing target dimension; the Planner creates the next Mission for remaining gaps. Repeated planning reuses an actionable design Mission.

The current implementation makes the architectural rule executable:

> **Agent proposes. HyperTest commits.**

## Web v0.2

`web/` contains the Next.js + Ant Design + TanStack Query workbench. It is centered on **Testing State rather than Agent Conversation**.

Current pages:

```text
/                         Project dashboard
/projects/{project_id}    Project + TestRun list
/runs/{test_run_id}       Canonical TestRun workbench
```

The TestRun workbench displays:

- TestRun status and SourceSnapshot identity.
- Requirements, Risks, Test Cases, and Missions tabs.
- Requirement ↔ Risk ↔ TestCase traceability, including test intent, preconditions, and expected result.
- Mission history and attempt count.
- Active Requirement, non-obsolete Risk, and active TestCase counts.
- Risk identification coverage and Risk test coverage, derived by the backend.
- Complete/gap status and required, covered, and missing design dimensions for each assessed Risk.
- `Plan next mission` action backed by the HyperTest Planner.

Coverage ratios with no eligible denominator are `null` and shown as unknown, never as 100%.

## Current API

```text
GET  /api/v1/health

POST /api/v1/projects
GET  /api/v1/projects
GET  /api/v1/projects/{project_id}
GET  /api/v1/projects/{project_id}/test-runs
POST /api/v1/projects/{project_id}/source-snapshots

POST /api/v1/policy-snapshots

POST /api/v1/test-runs
GET  /api/v1/test-runs/{test_run_id}
GET  /api/v1/test-runs/{test_run_id}/requirements
GET  /api/v1/test-runs/{test_run_id}/risks
GET  /api/v1/test-runs/{test_run_id}/test-cases
GET  /api/v1/test-runs/{test_run_id}/coverage
GET  /api/v1/test-runs/{test_run_id}/missions
POST /api/v1/test-runs/{test_run_id}/missions
POST /api/v1/test-runs/{test_run_id}/plan-next

GET  /api/v1/missions/{mission_id}
POST /api/v1/missions/{mission_id}/execute
```

## Local development

Requirements:

- Docker / Docker Compose, or Python 3.12 + PostgreSQL 17.
- Node.js 22 if running the Web frontend outside Docker.

Start the complete stack:

```bash
docker compose up --build
```

Endpoints:

```text
Web:      http://localhost:3000
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
```

For a local backend environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
uvicorn hypertest.main:app --reload
```

For local Web development:

```bash
cd web
npm ci
HYPERTEST_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

Backend validation:

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

GitHub Actions runs both backend validation against PostgreSQL 17 and Web validation on Node.js 22 for every pull request and push to `main`. Web dependencies are installed once with the committed lockfile.

Migration `0004_test_design` follows `0003_risk_planner`, creates `test_cases` and the relational `risk_test_cases` association, and permits `TEST_CASE` proposals. `alembic upgrade head` applies the full chain from a clean database.

## Project principle

HyperTest One orchestrates **testing work**, not model reasoning. Agent harnesses remain replaceable; testing state, evidence, policy, history, and verdicts remain owned by HyperTest One.
