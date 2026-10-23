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

- **Local management path: HyperTest One manages session testing tasks, cases and reports. One real parent session corresponds to one SessionTask; the local Agent performs testing and synchronizes its outputs. This management API does not execute tests.** [ADR-018](docs/architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) takes precedence for this management path.
- **Cloud and Local share one Project:** Cloud uses independent CloudTask / CloudAttempt identities and the official DeepSeek Harness Python SDK under [ADR-019](docs/architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md). The six steps are Project resources → frozen task inputs → dispatch → DeepSeek/Codex work → accepted artifacts → project-framework execution/reporting. Claude remains a placeholder. Cloud 当前仅实现官方 Python SDK + DeepSeek Harness + 显式 opt-in Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 Task 固定 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT strict PASS，独立只读重放 19 项通过。重评没有新的 current GET、模型 / SSH / SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，也不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 与失败原件保持。最终合并树、统一 Web 入口与测试服务器常驻 Cloud 服务尚未进行本轮验收或部署；默认关闭。 See [Cloud status](docs/CLOUD_IMPLEMENTATION_STATUS.md).
- Cloud API processes do not run Agents or tests. Only the current fenced Worker broker writes Cloud reports; root / child Agents receive no platform token, DB access or Operator key. Cloud `cloud:work` and Local `task:sync`, identities, ledgers and UNKNOWN reconciliation remain separate. Model identities must be provisioned in the cloud; do not copy local logins. Cloud disablement or failure must not block Local synchronization or history.
- [ADR-021](docs/architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) shares TaskSyncCore semantics / library through separate LocalSyncAdapter and CloudSyncAdapter, not a generic Task table, API, token or global journal. Activity, uploads and SDK idle are not completion or PASS. ADR-022 的 Memory Gateway 是独立 Proposed / NOT IMPLEMENTED 提案，不在本次 Cloud 交付中。经验服务与 Canonical 测试状态、TaskSyncCore 分离；`task:sync` / `cloud:work` 不授权经验访问，服务管理 key 不进入 Agent，外部 Generation / Embedding 默认关闭。
- Session sync shares Project, stores versioned plans/cases/raw reports and reported results with source metadata, and uses scoped authorization, idempotency receipts and expected-version checks. It does not require Job, Harness, Runner, execution binding, source transfer, independent CI proof or Gate. Reported PASS/FAIL is preserved and does not become legacy VERIFIED Evidence or RELEASE_READY automatically. Sync UNKNOWN is reconciled by original key and never rewrites a test result.
- [ADR-024](docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md) adds Operator-created UNBOUND Local tasks and one-time binding of the same UUID to a real native parent session. Do not invent provider/session/owner/source metadata for an unbound task. New Local clients must bind an explicit Task ID before their first asset sync; return TASK_BINDING_REQUIRED without POST when missing. Preserve confirmed legacy auto-task resume, shared Hook/MCP coordination, exact intended-actor authorization, and original-key-only CREATE/BIND reconciliation. Cloud and Local share Project, not task identity or execution rights.
- ADR-024的新BIND及手动已绑定Task的显式MCP新sync，目前仅实现已核对上游源码的Codex CLI `0.144.6`逐调用caller路径：宿主注入的`_meta.threadId`经独立私有IPC与SessionStart root核对，child不能只填已知父ID写父Task。缺context、错配或未支持的宿主明确拒绝，零新POST；Claude/DeepSeek对应适配未实现，CLI自报session不能替代。保留已确认legacy auto任务resume、授权GET及原key只读恢复。此context是本地宿主归因，不是服务端独立身份证明；远端组件验证及真实宿主E2E未观察的边界见[绑定验收记录](docs/LOCAL_TASK_BINDING_ACCEPTANCE_20261023.md)。
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

## Local 实现与独立发行增补

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](docs/LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](docs/local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR #23 已合并，项目页 → 本地会话任务 → 接入本地模式已按 `b27c8c14c80dce46bc21a02c83daba7070cf8292` 上线，精确证据见[Local Web 历史部署记录](docs/LOCAL_WEB_PRODUCTION_DEPLOYMENT_20261023.md)。本次 Cloud 集成未重验或升级该 Local 包。


本节记录 Local（ADR-020）与 TaskSyncCore（ADR-021）Local 消费方的独立交付边界。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

Local独立发行当时以原ADR-018全文、TMP §45与领域 §50为历史基线；现行预创建、绑定及caller增补按ADR-024、TMP §45.4与领域 §50.5执行。原API/profile、task:sync、
Project/actor owner、完整请求、expected_version与既存历史语义继续保留；hypertest_sync_task不是PATCH。
同一真实父会话由一个有效 LocalSyncCoordinator 接受 Hook 触发与显式 MCP；子代理只回交父任务。
只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录。
冻结后保留完整请求/key/version；SENT/UNKNOWN/失答及 NOT_FOUND 只 GET 原 key，不自动再次 POST。
有效 ACK 后完整读回固定接受版本才确认本次同步；传输状态不重写 reported_result，Stop 不代表 PASS/COMPLETED。

Local 发行独立使用 local-vSEMVER，旧 mcp-v0.1.0/mcp-v0.2.0 历史不重标。
安装只复用既有私有 Project 授权，不申请 Operator key、签发 grant 或复制模型登录；
Hooks 需显式选择 workspace 或私有 approved artifact policy，版本匹配后启用。
升级/回退/卸载保留私有身份、账本、未决 key、源产物、用户项目与其他宿主配置。
Local 发行不包含 Cloud runtime；Cloud 实施进度与最终树验收按独立 Cloud 状态记录，不由 Local 发行成绩推定。
