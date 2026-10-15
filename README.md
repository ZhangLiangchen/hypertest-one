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
- Canonical entities: `Project`, `SourceSnapshot`, `PolicySnapshot`, `TestRun`, `Requirement`, `Risk`, `Mission`.
- `RequirementRisk` relational traceability.
- `MissionAttempt`, `MissionProposal`, `AgentSession`, `AuditEvent`, and transactional `OutboxEvent`.
- UUIDv7 canonical primary keys and human-readable operational keys.
- Immutable source/policy snapshot semantics.
- Deterministic source/risk fingerprinting and Mission spec hashing.
- Provider-neutral `AgentHarness` and thin `CodexCliAdapter`.
- TMP result boundary: provider telemetry is operational state; only `RESULT_SUBMITTED` is considered for domain verification.
- Canonical verifier for `ANALYZE_REQUIREMENTS` and `ANALYZE_RISKS`.
- Deterministic Planner that derives the next Mission from canonical state gaps.
- PostgreSQL integration coverage for `Requirement → Risk` canonical state transitions.

### Planner loop

```text
TestRun
  ↓ observe canonical state
Planner
  ├─ no Requirement → ANALYZE_REQUIREMENTS
  ├─ Requirement without Risk → ANALYZE_RISKS
  └─ all Requirements risk-covered → no action (next slice: DESIGN_TESTS)
```

The current implementation makes the architectural rule executable:

> **Agent proposes. HyperTest commits.**

## Web v0.1

`web/` contains the first Next.js + Ant Design + TanStack Query workbench. It is intentionally centered on **Testing State rather than Agent Conversation**.

Current pages:

```text
/                         Project dashboard
/projects/{project_id}    Project + TestRun list
/runs/{test_run_id}       Canonical TestRun workbench
```

The TestRun workbench displays:

- TestRun status and SourceSnapshot identity.
- Requirement canonical state.
- Risk canonical state and Requirement ↔ Risk traceability.
- Mission history and attempt count.
- Derived Requirement risk coverage.
- `Plan next mission` action backed by the HyperTest Planner.

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
npm install
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
npm run typecheck
npm run build
```

## Project principle

HyperTest One orchestrates **testing work**, not model reasoning. Agent harnesses remain replaceable; testing state, evidence, policy, history, and verdicts remain owned by HyperTest One.
