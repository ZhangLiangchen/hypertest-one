# HyperTest One — Agent Guidance

> **One Input. One Mission. One Complete Test Cycle.**

This repository is governed by four foundational documents. Any implementation, refactor, protocol change, schema change, or architecture decision MUST remain consistent with them unless an explicit Architecture Decision supersedes the relevant rule.

## Required reading

1. `docs/foundation/HYPERTEST_WHITEPAPER.md` — product identity, scope, principles, and long-term direction.
2. `docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md` — system boundaries, runtime components, control-plane architecture, runner and agent integration.
3. `docs/protocol/TEST_MISSION_PROTOCOL.md` — provider-independent contract between HyperTest and Codex / Claude Code / other agent harnesses.
4. `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` — normative canonical data model, lifecycle, database constraints, ownership and invariants.

## Precedence

When details conflict:

1. `HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` is normative for fields, relationships, lifecycle, uniqueness, persistence, database constraints and state transitions.
2. `TEST_MISSION_PROTOCOL.md` is normative for HyperTest ↔ Agent mission, proposal, event, result and tool interaction contracts.
3. `HYPERTEST_TECHNICAL_ARCHITECTURE.md` is normative for service boundaries and runtime architecture.
4. `HYPERTEST_WHITEPAPER.md` defines product intent, principles and long-term positioning.

## Non-negotiable architecture principles

- **Current stage: HyperTest One manages Codex testing tasks, cases and reports. One Codex session corresponds to one SessionTask; Codex performs testing and synchronizes its outputs. HyperTest does not execute tests.** [ADR-018](docs/architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) takes precedence for this management path.
- Session sync shares Project, stores versioned plans/cases/raw reports and reported results with source metadata, and uses scoped authorization, idempotency receipts and expected-version checks. It does not require Job, Harness, Runner, execution binding, source transfer, independent CI proof or Gate. Reported PASS/FAIL is preserved and does not become legacy VERIFIED Evidence or RELEASE_READY automatically. Sync UNKNOWN is reconciled by original key and never rewrites a test result.
- ADR-017 native intake and ADR-010/012/013/015/016 execution paths remain separate compatibility/history; do not apply their execution admission rules to current management sync or alter historical results.

- HyperTest is an **Autonomous Testing Control Plane**, not another generic coding agent.
- HyperTest orchestrates **testing missions**, not model reasoning.
- General-purpose agent harnesses such as Codex and Claude Code are replaceable Testing Workers.
- **Agent performs testing work. Project test tools produce execution results. HyperTest governs evidence and conclusions.**
- Agent output is a Proposal by default; agents do not directly own Canonical Testing State.
- Agent calls each SUT's existing framework / CI; HyperTest does not build another test engine or Runner backend matrix. Formal facts require independently verified execution provenance; Agent summaries, hashes and shell self-reports are insufficient.
- [ADR-017](docs/architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md) defines the additive `native-framework-intake/v1alpha1` profile. Native plans / cases pass Proposal / Verifier acceptance; local execution materials remain UNVERIFIED and the first native Gate only emits UNKNOWN / BLOCKED. Native Contributor handoff is explicit, sequential and fenced by a private generation-scoped capability; session labels are metadata, not native-chat identity proof.
- ADR-010 / 012 / 013 / 015 / 016 Runner-only facts, Python/pytest targets, source transfer and persistent primary-session rules continue to govern their legacy profiles and history. They do not restrict the new native profile to platform execution; native records cannot be relabeled as legacy VERIFIED Evidence or RELEASE_READY.
- Canonical chain: `Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding → Verdict`.
- Agent conversation, chain-of-thought, provider-specific event formats and temporary workspace data are not Canonical Testing State.
- BUGate remains a stateless Testing Protocol / Policy layer; HyperTest is the stateful runtime.
- Prefer PostgreSQL canonical relational state + audit log + transactional outbox for v1. Do not introduce Graph DB, Kafka, full event sourcing or a custom generic Agent Loop without a demonstrated requirement.

## Change discipline

Before changing a core domain entity, mission lifecycle, runner/evidence trust model, or agent contract:

1. Identify which foundational document owns the rule.
2. Preserve existing invariants and history semantics.
3. If the rule must change, update the corresponding specification in the same change.
4. Do not silently encode architecture decisions only in implementation code.

The goal is for HyperTest One to remain agent-independent, model-independent, evidence-driven, auditable, reproducible, and replaceable at the harness layer.

## HyperTest One development and test-server delivery

The `hypertest-one` server is the user's **single-user dedicated test environment**,
used to validate HyperTest One and cloud task execution. It is not a production or
shared multi-user service. Service interruption and restart are allowed during
development; a running test does not by itself impose a maintenance-window gate.
This describes the deployment environment, not a change to the ADR-018 management
boundary or authorization to run an unrelated SUT.

- Default flow for HyperTest One code changes: edit locally → commit and push to
  Git → fetch the specified branch/commit on the server and record its resolved
  full SHA → build there, apply needed migrations and restart affected services
  → run the relevant remote validation once. If a full suite is needed, run it
  remotely. Do not default to a full local test suite or local production build;
  quick local checks are optional debugging aids, not a mandatory preflight matrix.
- Pure documentation changes only need static checks and commit/push. They do not
  trigger a server build, migration, restart or functional regression run.
- Deploy from pushed Git history. Do not package and upload an uncommitted local
  worktree as the normal source-delivery path. Do not reset another checkout's
  uncommitted work; fetch into a clean, separate server release when needed.
- Routine authorized development does not require an extra deployment approval,
  a formal maintenance window, a paired cold-backup/restore rehearsal or a fixed
  15-minute observation. Choose additional checks for the actual change or an
  explicitly requested validation goal, rather than treating old release records
  as permanent gates.
- Preserve projects, tasks, cases, reports, revisions, receipts, audit history,
  credentials and persistent files. Permission to interrupt services is not
  permission to reset the database, delete volumes, overwrite history or replay
  an uncertain external operation. Back up according to migration/data risk;
  restoration exercises are separate validation work, not an every-deploy default.
- Record the deployed Git SHA and resulting image identities. For this server,
  these current rules and the [default operations flow](docs/SERVER_OPERATIONS.md#当前环境与默认交付流程)
  supersede older descriptions of a production environment and routine heavy
  deployment gates. Historical commands, paths and evidence remain historical facts.

## Remote operations

- Read [server operations](docs/SERVER_OPERATIONS.md#ssh-access) before connecting to the deployed server.
- On the configured local Mac, use `ssh hypertest-one` for interactive access. Automated checks must use the same alias with `BatchMode=yes` and `PreferredAuthentications=publickey`; use `bash ops/check-remote.sh` for platform health checks.
- Keep the existing password login available for manual recovery. Automated checks must fail on key authentication errors rather than depend on a temporary `SSH_ASKPASS` helper or prompt for a password.
- The alias and private key are local to this Mac, not provisioned in CI or cloud executors. Preserve host-key verification, existing server access, and the VPN allowlist.
