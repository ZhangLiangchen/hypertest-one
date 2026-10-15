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

## Foundation implementation

The first implementation slice establishes the control-plane spine:

- FastAPI application and `/api/v1` REST surface.
- PostgreSQL + SQLAlchemy async persistence.
- Alembic foundation migration.
- Canonical foundation entities: `Project`, `SourceSnapshot`, `PolicySnapshot`, `TestRun`, `Mission`.
- UUIDv7 canonical primary keys and human-readable operational keys.
- Immutable source/policy snapshot semantics.
- Deterministic source fingerprinting and Mission spec hashing.
- Mission idempotency keyed by `test_run_id + idempotency_key`.
- Provider-neutral `AgentHarness` interface.
- Initial thin `CodexCliAdapter` that maps TMP missions to Codex CLI JSONL activity without leaking provider-specific state into the domain.

### Current API

```text
GET  /api/v1/health
POST /api/v1/projects
GET  /api/v1/projects/{project_id}
POST /api/v1/projects/{project_id}/source-snapshots
POST /api/v1/policy-snapshots
POST /api/v1/test-runs
GET  /api/v1/test-runs/{test_run_id}
POST /api/v1/test-runs/{test_run_id}/missions
GET  /api/v1/missions/{mission_id}
```

## Local development

Requirements:

- Docker / Docker Compose, or Python 3.12 + PostgreSQL 17.

Start the local stack:

```bash
docker compose up --build
```

The API will be available at:

```text
http://localhost:8000
http://localhost:8000/docs
```

For a local Python environment instead:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
uvicorn hypertest.main:app --reload
```

Run validation:

```bash
ruff check src tests alembic
pytest -q
```

## Project principle

HyperTest One orchestrates **testing work**, not model reasoning. Agent harnesses remain replaceable; testing state, evidence, policy, history, and verdicts remain owned by HyperTest One.
