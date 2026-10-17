# HyperTest Technical Architecture

**Document Status:** Draft  
**Version:** v0.3
**Parent Document:** HyperTest Whitepaper v1.0  
**Architecture Role:** Autonomous Testing Control Plane

---

## 1. 文档目的

本文定义 HyperTest 的技术架构、模块边界、核心数据模型、运行时状态、部署模型以及与外部 Agent Harness、Test Runner、BUGate Protocol 的关系。

本文重点回答：

1. HyperTest 具体由哪些服务组成；
2. 哪些能力属于 HyperTest，哪些能力交给 Codex / Claude Code；
3. Testing State 如何持久化；
4. Mission 如何产生、执行、验证；
5. Test Runner 如何产生可信 Evidence；
6. 如何支持多 Agent Harness；
7. 系统如何从 MVP 演进为完整 Autonomous Testing System。

---

## 2. 架构目标

HyperTest 不重新实现 Coding Agent，而是建立一个长期稳定的软件测试控制平面，使不同通用 Agent 能围绕统一的 Testing State、Testing Policy、Mission、Evidence 和 Verdict 工作。

核心公式：

> **Agent produces intelligence.**  
> **Runner produces facts.**  
> **HyperTest produces decisions.**

系统必须满足：Agent-independent、Model-independent、Stateful、Evidence-driven、Policy-driven、Reproducible、Auditable、Extensible、Human-observable、Agent-native。

---

## 3. 系统边界

### 3.1 HyperTest 负责

Testing State、Requirement Model、Risk Model、Test Case Model、Coverage Model、Mission Planning、Mission Compilation、Agent Dispatch、Proposal Validation、Canonical State Commit、Official Test Execution、Evidence Collection、Finding Management、Quality Gate、Verdict、Audit / History。

### 3.2 Agent Harness 负责

Codex、Claude Code、Pi、OpenCode 等负责 Reasoning、Repository Understanding、Code Search、File Reading、Code Editing、Shell、Debugging、Tool Calling、Context Management、Agent Loop、Subagent、Local Retry。

### 3.3 Test Framework 负责

pytest、JUnit、Playwright、k6、Frigate、Hypersonic 等负责具体测试逻辑和测试执行语义。HyperTest 负责调度、记录和证据治理。

---

## 4. 总体逻辑架构

```text
┌──────────────────────────────────────────────────────┐
│                    HyperTest Web                     │
│ Project / Requirement / Risk / Case / Run / Finding │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│                 HyperTest API Layer                  │
│ Project API    TestRun API     Mission API           │
│ State API      Evidence API    Finding API           │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│             Autonomous Testing Control Plane         │
│                                                      │
│ State Engine      Test Planner                       │
│ Policy Engine     Mission Compiler                   │
│ Coverage Engine   Agent Gateway                      │
│ Verifier          Runner Controller                  │
│ Gate Engine                                           │
└───────────────┬──────────────┬───────────────────────┘
                │              │
        ┌───────▼──────┐ ┌────▼─────────┐
        │Agent Harness │ │ Test Runner   │
        │Codex         │ │Docker        │
        │Claude Code   │ │Kubernetes    │
        │Pi / ...      │ │Remote SIT    │
        └──────────────┘ └──────────────┘
```

---

## 5. 核心服务划分

MVP 推荐“模块化单体 + 独立 Worker”，而不是一开始微服务化：

```text
hypertest-web
hypertest-api
agent-gateway
runner-worker
postgres
artifact-store
```

长期根据负载和团队边界拆分。

---

## 6. hypertest-web

推荐技术栈：Next.js + Ant Design + TanStack Query。

主要页面：Project Overview、Requirement Explorer、Risk Matrix、Test Case Explorer、Coverage Dashboard、Test Run、Mission Activity、Evidence Viewer、Finding Center、Quality Verdict、Agent Activity。

Agent Chat 可以存在，但只能是辅助界面，不能成为产品主界面。

当前 MVP 的 TestRun Workbench 提供 Requirements、Risks、Test Cases、Missions、Automation、Executions、Evidence、Findings、Verdicts。用户通过表单创建 Project / 输入快照 / Run，规划和执行 Mission，启动 Runner、查看证据、管理 Finding、评估 Gate。计数、Risk identification coverage 和 Risk test coverage 来自 Canonical State；每个被评估 Risk 显示 Complete / Gap 以及 required / covered / missing dimensions。没有分母时显示未知，设计覆盖不代表执行或发布验收完成。

这是面向单个可信 Operator 的可操作工作台。当前没有 Login / RBAC / Tenant Isolation，不能宣称多用户生产安全；Agent / Docker / Workspace 是 Operator 管理的主机集成。运行前提、当前能力和后续路线见 `docs/MVP_STATUS.md`。

---

## 7. hypertest-api

推荐：FastAPI + Pydantic + SQLAlchemy + PostgreSQL。

主要职责：Authentication、Project Management、Testing State CRUD、Mission Lifecycle、Policy Access、Evidence Metadata、Finding Lifecycle、Verdict、Audit。

API 不直接执行 Agent，所有 Agent 工作必须进入 Mission。

---

## 8. Test State Engine

State Engine 维护 Canonical Testing State。

Canonical State 指经过 Schema、Policy、Consistency 验证，正式成为 HyperTest 系统事实的数据。

Agent Conversation 不属于 Canonical State。

---

## 9. Domain Model

核心实体：

```text
Project
SourceSnapshot
PolicySnapshot
TestRun
Requirement
Risk
TestCase
TestImplementation
TestExecution
Evidence
Finding
Verdict
Mission
MissionAttempt
MissionProposal
AgentSession
```

详细字段、关系、生命周期和数据库约束以 `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` 为准。

---

## 10. SourceSnapshot

一次 TestRun 必须绑定不可变 SourceSnapshot，至少固定 Repository、Commit SHA、PRD Hash、Configuration Hash、Environment Definition。

原则：

> TestRun 必须能够回答“测试的到底是什么”。

---

## 11. TestRun

TestRun 是一次正式自治测试活动，绑定 SourceSnapshot 和 PolicySnapshot，并拥有 CREATED、ANALYZING、DESIGNING、IMPLEMENTING、EXECUTING、DIAGNOSING、VERIFYING、COMPLETED、BLOCKED、CANCELLED 等运行状态。

PASS / FAIL 不属于 TestRun Status，而属于 Verdict。

---

## 12. Mission

Mission 是 HyperTest 内部最重要的工作单元：

> 为推动 TestRun 从当前 State 向目标 State 转移而创建的 Testing Work Unit。

典型类型：ANALYZE_REQUIREMENTS、ANALYZE_RISKS、DESIGN_TESTS、IMPLEMENT_TESTS、DIAGNOSE_FAILURE、INVESTIGATE_FINDING、VERIFY_COVERAGE。

---

## 13. Mission State Machine

```text
CREATED
   │
   ▼
READY
   │
   ▼
DISPATCHED
   │
   ▼
RUNNING
   │
   ├──► WAITING_INPUT ──► RUNNING
   ├──► WAITING_EXECUTION ──► RUNNING
   ▼
SUBMITTED
   │
   ▼
VERIFYING
   │
   ├──► RETRYING ──► DISPATCHED
   ▼
COMPLETED

异常：FAILED / CANCELLED / EXPIRED
```

Mission Retry 不覆盖历史 Attempt，而是创建新的 MissionAttempt。

---

## 14. Test Planner

Planner 不执行测试，只回答：

> 基于当前 Test State，下一步最值得做什么？

输入：Canonical Test State、Coverage Gap、BUGate Policy、Historical Knowledge、Pending Findings、Resource Constraints。

输出：`MissionIntent[]`。

Planner 采用：

```text
Deterministic Rules
        +
Policy Rules
        +
Heuristics
        +
Optional LLM Reasoning
```

LLM 不独占 Planner。像“P0 Risk 没有 Case”这种判断应 deterministic；“Git Diff 是否引入新的 consistency risk”适合 Agent reasoning。

当前可执行的 deterministic-first 闭环：

```text
无 ACTIVE Requirement → ANALYZE_REQUIREMENTS
ACTIVE Requirement 无非 OBSOLETE Risk → ANALYZE_RISKS
非 OBSOLETE Risk 缺少 required test design dimensions → DESIGN_TESTS
所有 Risk 的设计维度满足、Case 无可用实现 → IMPLEMENT_TESTS
Case 已实现、缺少正式执行 → EXECUTION_REQUIRED
正式执行进行中 → EXECUTION_IN_PROGRESS
正式执行失败且有可信证据 → DIAGNOSE_FAILURE
事实可供质量评估 → VERDICT_REQUIRED
```

Planner 返回 Mission 或运行阶段原因；正式执行由 Runner API 发起，Verdict 由独立 Gate API 评估。Planner 调用独立的 `RiskCoverageEvaluator`，不自行使用 LLM 判定覆盖。重复规划复用仍相关的可执行 Mission；后续缺口变化时创建新的不可变 Mission，保留已有 Mission 和 Attempt 历史。Web 的 Run test cycle 提交持久化 Job，由独立 Worker 调用 bounded controller；每个周期默认最多 12 步，上限 32。controller 根据 Planner 决策委派 Mission Runtime、Runner、Gate，不生成 Agent Intelligence 或改写 Canonical 结果。每一步由所属服务验证提交，遇到拒绝、活动中的外部步骤、错误或 work limit 可观察停止，下次从 Canonical State 继续。单步操作也可提交独立 Job；用户不需要保持 HTTP 请求或浏览器页面存活。

### 14.1 Durable Work Queue

PostgreSQL 保存 Job 的请求、状态、结果与 Worker liveness；队列属于平台 Operational State，不把 Canonical 状态塞入 Job JSON 或 Agent Session。每个 Run 同时最多一个活跃 Job，重复 idempotency key 必须匹配相同输入。独立进程 `python -m hypertest.worker` 通过 `FOR UPDATE SKIP LOCKED` 领取任务、续租并执行既有服务。API 与 Worker 共用数据库、Artifact Store、Workspace Root 和宿主集成配置。

Worker 对每次 Canonical commit 使用有效 lease token、Job 状态与数据库时钟进行 fencing，租约锁顺序为 TestRun → Job。MissionAttempt / TestExecution 使用不可变 nullable durable_job_id FK 保存同一 Run 的受控归属；恢复不依赖跨宿主时间戳推断，也不替历史 direct API 调用回填关系。取消先持久化，再中断外部工作；API 重启或 Web 刷新不取消已提交的请求。Worker 退出或租约过期会显式记录 INTERRUPTED，并把其拥有的未完成 Attempt / Execution 转为可观察的失败，保留原始历史。恢复不会自动重放可能已产生外部影响的任务，用户检查后创建关联新 Job 重试。租约不保证外部执行 exactly-once。

Docker 的 staging / execution containers 和预创建的 source / result volumes 均带 Job UUID label。失联恢复先提交领域终态，再在数据库锁外清理精确匹配的受控资源；`job.resources_cleanup` Audit / Outbox 记录可用性与清理数量。清理属于运行治理，不是测试 Evidence。Docker 不可访问或 provider 残留进程仍需 Operator 检查。

兼容 direct `/advance` 仍是同步调用，不独占整个 Loop。controller 在每个 Planner 步骤前后重新检查当前操作归属；若服务提交间隙入队了 DurableJob，旧 direct controller 停止继续派发，避免替新 Job 启动未归属的工作。

每个 Worker 一次处理一个 Job，可启动多个 Worker 处理不同 Run。`worker_heartbeats` 提供近期活动状态；后台 Worker 仅消费用户提交的工作，没有新增自动发布、任意 Agent reasoning loop 或周期性项目扫描 Scheduler。

---

## 15. Mission Compiler

Planner 输出 `MissionIntent`，Mission Compiler 负责：Resolve Context、Attach Policy、Calculate Permissions、Build Acceptance Criteria、Select Output Schema、Select Execution Profile，最终生成不可变 `TestMission`。

当前 DESIGN_TESTS 编译上下文包含同一 Project / SourceSnapshot 下的 Canonical Risks、PolicySnapshot 引用和覆盖评估。Mission 固定目标 Risk 和 missing dimensions；Verifier 至少要求有效 Proposal 对其中仍缺失的一个维度形成进展。Mission 完成不等于整个 TestRun 设计完成，剩余缺口由下次 Planner 评估。

---

## 16. Agent Gateway

Agent Gateway 是 HyperTest 与外部 Agent Harness 的 Anti-Corruption Layer，防止 Codex / Claude / OpenCode 的 Provider-specific Session、Event、CLI/API Model 渗入 HyperTest Domain。

统一接口概念：

```python
class AgentHarness:
    async def create_session(self, workspace, profile): ...
    async def execute(self, session, mission): ...
    async def interrupt(self, session): ...
    async def close(self, session): ...
```

实现：`CodexAdapter`、`ClaudeCodeAdapter`、`PiAdapter`、`OpenCodeAdapter`。

---

## 17. Provider Adapter 责任

Adapter 负责：

```text
Mission → Provider Input
Provider Event → HyperTest AgentEvent
Provider Result → AgentResult
HyperTest Permissions → Provider Sandbox / Approval
HyperTest Session → Provider Session / Thread
```

Provider-specific metadata 必须隔离在 Adapter 或 `provider_metadata` 中。

---

## 18. AgentSession

HyperTest 维护自己的 AgentSession ID；Provider Session 只是外部引用。

```text
AgentSession
├── id
├── provider
├── harness
├── provider_session_id
├── workspace_id
├── test_run_id
├── status
├── created_at
└── last_active_at
```

禁止以 Codex thread ID / Claude session ID 作为系统主键。

---

## 19. Context Delivery

Agent Context 不应该等于整个数据库 Dump。Context Compiler 根据 Mission 只构建最小充分上下文：Mission、Relevant Requirements、Relevant Risks、Relevant Cases、Relevant Evidence、Relevant Findings、Policy Excerpts、Repository、Source Diff。

> **Context should be mission-scoped, not project-global.**

---

## 20. Workspace

每个 TestRun 或 AgentSession 获取独立 Workspace：

```text
/workspace
├── repo/
├── context/
│   ├── mission.json
│   ├── requirements.json
│   ├── risks.json
│   └── policy.md
├── artifacts/
└── scratch/
```

Workspace 是 Agent 的操作世界；数据库是 HyperTest 的 Canonical World。

当前 Web 可通过 prepare-workspace 为 GitHub HTTPS 源准备/复用 managed pinned checkout，使用既有 Git proxy/auth，不重置 Operator checkout；其他 Host 使用明确的既有 workspace。

当前 Runtime 在临时 tracked-source 副本中运行 Agent，固定 SourceSnapshot / PolicySnapshot 并注入 PRD 与规范化 Mission；Canonical Artifact 和业务状态不放入 Vendor Session。IMPLEMENT_TESTS 的生成源码作为 Proposal `code` 返回，经 Verifier 校验后进入内容寻址 Artifact Store，不直接修改用户 checkout 或应用 Commit。

---

## 21. HyperTest MCP

HyperTest 提供领域 MCP Server。

Read Tools：`get_mission`、`get_requirement`、`get_risk`、`get_test_case`、`get_coverage`、`get_execution`、`get_evidence`、`get_finding`。

Proposal Tools：`propose_requirement`、`propose_risk`、`propose_test_case`、`propose_implementation`、`report_finding`。

Execution Tool：`request_execution`。

Agent 默认只能：

> **READ canonical state / WRITE proposals**

禁止 Agent 直接修改 Canonical State、删除 Evidence、标记 Verdict 或改变 Policy。

---

## 22. Proposal Engine

所有 Agent-generated Domain Objects 先进入 MissionProposal，再经过 Schema Validation、Reference Validation、Policy Validation、Semantic Validation、Deduplication，最终 Accepted / Rejected。

---

## 23. Verifier

Verifier 分三层：

- **L1 Structural**：Schema、required fields、references。
- **L2 Policy**：required risk categories、evidence、forbidden operations、acceptance criteria。
- **L3 Semantic**：必要时使用 LLM 判断 Test 是否真正覆盖 Risk、Finding 是否匹配 Evidence、Requirement 拆解是否合理。

v0.2 DESIGN_TESTS 使用确定性 schema / reference / source snapshot / fingerprint / idempotency / coverage progress 校验。整个 Proposal batch 通过后，TestCase、`risk_test_cases` 关系、Proposal acceptance、AuditEvent 和 OutboxEvent 在同一数据库事务提交。Canonical State 不保存在 Agent Session 中。语义质量判定属于后续扩展，当前类型维度覆盖不能替代语义证明或 Runner Evidence。

---

## 24. Runner Controller

正式 Execution 不能通过 Agent Shell 直接成为系统事实。

```text
Agent
  │ request_execution
  ▼
HyperTest Runner Controller
  │
  ▼
ExecutionSpec
  │
  ▼
Runner Worker
```

---

## 25. ExecutionSpec

ExecutionSpec 至少固定 execution_id、source_commit、environment、framework、targets、timeout、collect 等字段，并计算不可变 SHA256。

当前 Runner 只接受 Canonical TestImplementation 中的安全 pytest node ID，校验 Repository origin、完整 Commit SHA、干净的 tracked 内容以及实现源码 hash。平台复制 tracked 源码到隔离执行副本，按已接受 Artifact 覆盖安全 `tests/**/*.py` 新文件；生成测试不能覆盖 Snapshot 中已跟踪文件。Execution 输入和环境指纹固定后才执行，重复 request key 不启动第二次执行。

---

## 26. Runner Backend

统一抽象 `RunnerBackend`，实现 DockerRunner、KubernetesRunner、SSHRunner、ExistingEnvironmentRunner。

长期优先 Kubernetes Job，因为具备 Isolation、Resource Limit、Scheduling、Cleanup、Parallel Execution。

MVP 提供 DockerRunner 与显式开启的 LocalRunner。DockerRunner 使用预构建 Python/pytest 镜像，并记录解析出的 image ID；禁用网络、只读根文件系统、非 root、移除 capabilities、限制资源。执行时不安装依赖。LocalRunner 仅用于受控开发环境，需 `HYPERTEST_RUNNER_ALLOW_LOCAL=true`，不是安全沙箱。其他框架/语言和应用依赖需通过后续可信镜像扩展。

---

## 27. Evidence Collector

Runner 执行完成不能只返回 PASS / FAIL，必须输出 Execution Metadata、Command、Exit Code、JUnit、Stdout、Stderr、Logs、Metrics、Traces、Screenshots、Artifacts。

Evidence Artifact 放 S3 / MinIO / Object Storage，PostgreSQL 保存 Metadata、Hash、URI、Relations。

---

## 28. Evidence Integrity

Evidence 至少记录 SHA256、Source Execution、Source Commit、Environment ID、Created At、Collector、Content Type。

当前 MVP 使用本地 SHA-256 内容寻址 Store，数据库保存 immutable metadata。ExecutionEvidence 是显式关系，允许同一 Run 的相同内容在多个 Execution 中去重复用；Gate 不依赖 Evidence.execution_id 的单一首次来源判断全部关系。读取与 Gate 评估重新验证内容摘要；丢失/篡改 Artifact 阻止放行。

重要 Evidence 长期可形成 Evidence Manifest，必要时支持 signed Evidence Manifest。

---

## 29. Coverage Engine

Coverage 不只是代码覆盖率。HyperTest 应管理：Requirement Coverage、Risk Coverage、Case Coverage、Automation Coverage、Execution Coverage、Evidence Coverage。

Coverage 是 Derived State，不是 Agent Claim。

当前设计覆盖边界位于 `application/coverage.py` 的 `RiskCoverageEvaluator`，供 Planner 和 Coverage API 共同使用。`risk-design-baseline/v1` 对每个非 OBSOLETE Risk 要求 FUNCTIONAL；BOUNDARY、FAILURE、CONCURRENCY、SECURITY、PERFORMANCE 额外要求同名维度，RELIABILITY 额外要求 RECOVERY，其他类别使用 FUNCTIONAL 基线。只有同一 Snapshot 下通过 `RiskTestCase` 关联的 ACTIVE TestCase 贡献维度。

`application/policy.py` 编译当前 TestRun 固定的 PolicySnapshot。`coverage.default_dimensions` 声明全局维度，`coverage.by_category` 覆盖指定类别的专用维度，未配置类别继承基线；FUNCTIONAL 保持强制。自定义规则版本为 `risk-design-policy/v1`，等效基线保持原规则版本。Coverage API 返回 `rule_version` 与规范化规则的 `effective_policy_hash`；Planner 以二者构建不可变 Mission 契约和幂等身份，Verifier 校验契约与固定 Policy 一致，Gate 消费同一覆盖结果。未知规则在创建快照前拒绝，不能静默忽略 Policy。

Risk identification coverage 为存在非 OBSOLETE Risk 关联的 ACTIVE Requirements / 全部 ACTIVE Requirements；Risk test coverage 为已满足全部 required dimensions 的非 OBSOLETE Risks / 全部非 OBSOLETE Risks。空分母返回 `null`。未来 Policy 可扩展所需维度，Planner 和 Web 继续使用同一服务边界，无需成为通用 LLM Agent。

---

## 30. Gate Engine

Gate 采用 deterministic-first。示例：Requirement Coverage = 100%，P0 Risk Coverage = 100%，P0 Case 仅允许 PASS，Blocker Finding = 0，Evidence Complete = true。

最终 Verdict 必须尽量可解释。

当前 `canonical-gate/v1` 是确定性 Policy 组件。它要求完整识别/设计覆盖、每个 ACTIVE Case 最新 OFFICIAL 事实匹配 Commit 且通过、可信 VERIFIED metadata + JUnit Artifact，以及没有阻断级 confirmed PRODUCT_DEFECT。默认 BLOCKER / CRITICAL 阻断，可配置其他 FindingSeverity，BLOCKER 不可移除。缺失事实为 BLOCKED，失败为 RELEASE_BLOCKED，完整满足为 RELEASE_READY。评估记录规范化 State hash、Evidence manifest hash 和关系，重复状态评估幂等，变化追加新 Verdict；FINAL 内容由数据库 Trigger 保护。

多个 TestRun 共享同一 SourceSnapshot 的 Canonical 分析 / 设计 / Implementation 状态。Gate 在 TestRun 锁之后持有 SourceSnapshot `FOR UPDATE`，覆盖读取、决策与 Hash 序列化处于一致的快照范围；Verifier 提交与 Runner 共享 Implementation 更新使用同一锁，不跨实际测试执行持有快照锁。State Hash 绑定既有 Gate rule version、Canonical 输入、Artifact integrity 与 computed decision；重用 Verdict 还要求 decision 和 Evidence manifest 相同，不能让矛盾的历史决策命中旧缓存。规则版本仍为 `canonical-gate/v1`，旧 FINAL 记录保持不变。

---

## 31. BUGate Integration

BUGate 是 Policy Source：

```text
BUGate Protocol
       │
       ▼
Policy Compiler
       │
       ▼
PolicySnapshot
```

每个 TestRun 固定一个 PolicySnapshot，避免 BUGate 后续升级改变历史 Run 的解释。

SourceSnapshot 与 PolicySnapshot 的完整行内容由 PostgreSQL Trigger 保护，创建后禁止变更或删除；未引用的 Snapshot 同样受保护。已离开 CREATED 的 Mission 也冻结身份、spec、目标、协议、优先级和幂等键，Retry 只更新运行状态并追加 Attempt。`0006_immutable_contracts` 为已有数据库安装这些守卫，不重写历史输入。

---

## 32. Event System

HyperTest 内部采用 Domain Event：`test_run.created`、`requirement.accepted`、`risk.accepted`、`test_case.accepted`、`mission.created`、`mission.completed`、`execution.completed`、`evidence.created`、`finding.reported`、`verdict.changed` 等。

MVP 使用 PostgreSQL Transaction + Transactional Outbox，不需要一开始引入 Kafka。

Mission 生命周期由共享记录组件写 AuditEvent / OutboxEvent，并与创建、Attempt 更新或 Proposal 接受处于同一事务。`mission.completed` 仅在 Verifier 接受 required outputs 后产生；重复处理不重复发出同一决策事件。记录中只包含领域身份、状态、错误类别与受控原因，Provider 日志和 raw results 不进入 Domain Event。Outbox 行持久化不等于已发布到外部总线；自动投递仍是独立扩展。

---

## 33. AgentEvent

Provider-specific Event 进入 Adapter 后统一为：

```text
AgentEvent
├── session_id
├── mission_id
├── type
├── timestamp
├── payload
└── provider_metadata
```

类型可包括 SESSION_STARTED、TURN_STARTED、ACTIVITY、TOOL_REQUESTED、TOOL_COMPLETED、FILE_CHANGED、WAITING_INPUT、RESULT_SUBMITTED、ERROR、TURN_COMPLETED。

这些用于 UI、Observability、Debug、Audit，但不是 Canonical Testing State。

---

## 34. Persistence

PostgreSQL 负责 Domain State、Mission State、Audit、Metadata；Object Storage 负责 PRD、Artifacts、JUnit、Logs、Screenshots、Reports；Redis 可用于 Queue、Short-lived Lock、Streaming Buffer，但不能成为 Canonical Store。

---

## 35. Consistency Model

Canonical State 写入必须 transactional；关键状态迁移使用 optimistic locking；Mission 和 Runner Request 必须支持 idempotency key。

---

## 36. Observability

至少暴露 mission_duration、mission_success_rate、agent_token_usage、agent_failure_rate、runner_duration、execution_failure_rate、proposal_acceptance_rate、evidence_collection_failure、coverage_progress、test_run_cycle_time。

Trace 应贯穿 TestRun → Mission → AgentSession → Execution → Evidence。

---

## 37. Security

必须考虑 Repo Credential Isolation、Secret Injection、Agent Tool Permission、Network Policy、Workspace Isolation、Command Approval、Environment RBAC、Evidence Access、Audit Log。

Agent 默认不能看到非 Mission 必需的 Secret；Secret 按 Mission / Execution 注入。

---

## 38. 推荐 MVP 部署

```text
Docker Compose

nginx
│
├── web
├── api
├── agent-gateway
├── runner-worker
├── postgres
├── redis
└── minio
```

Agent Workspace 独立 container。

---

## 39. Kubernetes 目标形态

```text
HyperTest Control Plane
        │
        ├── Agent Job
        ├── Runner Job
        └── Artifact Collector
```

一次 TestRun 可以派生 N Agent Jobs 和 M Runner Jobs。Control Plane 长期运行，Worker 短生命周期。

---

## 40. MVP Architecture

MVP 仅支持：CodexAdapter、pytest、DockerRunner、Backend/API Testing，以及 Requirement、Risk、TestCase、Implementation、Execution、Evidence、Finding、Verdict。

核心验证目标不是“Agent 能否写测试”，而是：

> **Testing Semantic Chain 是否能够完整闭环。**

---

## 41. Architecture Decision Principles

- **ADR-001** HyperTest 不自研通用 Agent Loop。
- **ADR-002** Agent Harness 必须可替换。
- **ADR-003** Agent Output 默认是 Proposal。
- **ADR-004** Agent Conversation 不是 Canonical State。
- **ADR-005** 正式 Test Execution 只能由受控 Runner 产生。
- **ADR-006** Verdict 必须基于 Policy + Canonical State + Evidence。
- **ADR-007** BUGate 保持 Stateless。
- **ADR-008** HyperTest orchestrates Testing Missions, not model reasoning.
- **ADR-009** v0.2 首次实现 TestCase 时采用 `description`、`test_type`、字符串 `expected_result` 和 `risk_test_cases` Join Table；替代早期草案未实现的 `objective` / `case_type` / 结构化步骤方案。详细持久化约束以领域模型为准，不涉及已有 Canonical 列的破坏性重命名。
- **ADR-010** MVP 的生成测试是 checksum-addressed Artifact，应用 SourceSnapshot 保持不变；正式结果由 Runner 独立采集，Gate 基于最新正式事实形成不可改写的质量决策。
- **ADR-011** 用户触发的长任务使用 PostgreSQL DurableJob 与独立 Worker；租约 fencing 约束 Canonical commit，失联工作显式中断并人工重试，不宣称外部 exactly-once，也不引入 Redis / Kafka 前提。

---

## 42. 最终技术定义

```text
State
  ↓
Planner
  ↓
Mission Compiler
  ↓
Agent / Runner
  ↓
Proposal / Evidence
  ↓
Verifier
  ↓
Canonical State
  ↓
Gate
  ↓
Verdict
  ↓
Next State
```

HyperTest 不需要成为最聪明的 Agent。

它需要成为：

> **最可靠的软件测试控制平面。**
