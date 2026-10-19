# HyperTest Technical Architecture

**Document Status:** Accepted Architecture / Implemented; Production Cutover Verified (2026-10-19)

**Version:** v0.4

**Parent Document:** HyperTest Whitepaper v1.1

**Architecture Role:** Autonomous Testing Control Plane

v0.4 由 [ADR-013：平台容器化与持续 Harness 会话](ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md) 确立。Run Binding、Host Harness Bridge、持续会话、九个领域工具和受控 GitLab 集成已有实现，新增 `0013_run_bindings` / `0014_harness_operations`；本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)。2026-10-19 生产容器切换及真实正反链路已验收：源码入口为 `f415fd0`，API / Worker / Bridge 运行构建来源为 `95e92c5`，数据库为 `0014_harness_operations`，原数据、Codex OAuth、VPN 白名单及 SSH 隧道保留。完整结果见[正式部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)；真实 GitLab 提单、其他 Provider 及后续 Web 改进不由该结果推定完成。标注“当前 v0.3”的段落记录当时的兼容路径，不描述当前生产拓扑；部署现状以[服务器运维文档](../SERVER_OPERATIONS.md)与实际验收为准。字段、关系及生命周期以[领域模型](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)为准，消息与工具契约以 [TMP](../protocol/TEST_MISSION_PROTOCOL.md) 为准。

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

Testing State、Requirement Model、Risk Model、Test Case Model、Coverage Model、Mission Admission / Compilation、Task Worker Binding、Agent Dispatch、Proposal Validation、Canonical State Commit、Official Test Execution、Evidence Collection、Finding Management、Quality Gate、Verdict、Audit / History。

### 3.2 Agent Harness 负责

Codex、Claude Code、DeepSeek Harness 以及未来 Provider 负责 Reasoning、Repository Understanding、Code Search、File Reading、Code Editing、Shell、Debugging、Tool Calling、Context Management、Agent Loop、Local Retry。一个 TestRun 使用同一个持续主会话，自驱串行完成分析、设计、实现、请求正式执行、诊断和报告；平台不把这些阶段拆成相互独立的 Harness 会话，也不为一个 Run 分配多个平台 Task Worker 并行推进。

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

v0.4 保留“模块化单体 + 独立 Task Worker”的服务边界。Task Worker 指平台任务托管组件，Harness 指实际执行智能工作的 Provider CLI / SDK；两者不是同一个进程。部署边界为：

```text
容器：nginx / hypertest-web / hypertest-api / hypertest-task-worker / postgres
宿主机：Host Harness Bridge / Provider CLI 或 SDK / Provider 原生会话与认证
按需容器：可信 Runner 的隔离测试执行容器
持久存储：PostgreSQL volume / Canonical Artifacts / 每 Run 的受控 Workspace
```

Agent Gateway、Planner、Verifier、Gate 与 Runner Controller 首先是平台模块，不要求分别部署服务。未来确有需要的中间件同样容器化；PostgreSQL 队列、本地持久 Artifact Store 已足够作为起点，不把 Redis、Kafka 或 MinIO 设为首版依赖。完整物理拓扑见 §38。

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

API 不直接执行 Agent，所有 Agent 工作必须进入 Run 绑定，并取得显式的 Mission 或 Run scope 授权。API 容器不安装 Provider CLI、不挂载 Host Harness Bridge socket 或 Docker socket，也不依赖宿主 Provider 认证目录。长任务、受控环境实际镜像查询/绑定、运行能力检查及取消后的外部资源清理，交由具备相应权限的 Task Worker / Runner 组件处理；API 读取其受控结果并按领域规则冻结输入，不能用镜像 tag 或缓存配置冒充实际 image ID。已有同步 direct 执行和宿主检查入口需要迁移，不属于此目标形态的保留接口。

请求校验失败的 HTTP 422 仅返回错误的 `type`、`loc`、`msg`；不回显 `input`、validator `ctx` 或原请求 body，避免把提交中的凭据和 PRD 放入表单错误响应。此约束不等于所有日志已全面脱敏，持久化边界见领域模型 §9。

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
RunExecutionBinding  # Operational State，非质量事实链
```

详细字段、关系、生命周期和数据库约束以 `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` 为准。

---

## 10. SourceSnapshot

一次 TestRun 必须绑定不可变 SourceSnapshot，至少固定 Repository、完整 Commit SHA、PRD Hash、Configuration Hash、Environment Definition。feat / MR 编号、分支名和 URL 是来源参考；正式测试对象始终是创建时解析并固定的精确 SHA，MR 更新后创建新测试任务，不能改写原 Snapshot。

Web bootstrap 物化 PRD 与配置为输入 Artifact。Runtime 在创建 AgentSession / Attempt 前读取并校验这些原始 UTF-8 内容和快照 Hash；配置为空也必须保留其空内容 Artifact，缺失或损坏时停止，不能静默省略。已有 direct API 的 hash-only Snapshot（无 PRD Artifact URI）不因此强制补造配置文件；其配置仍为可选上下文，但一旦存在物化文件必须校验。此兼容范围不更改不可变输入或 Hash，具体规则见领域模型 §9。

Repository origin 的身份不得包含 HTTP(S) userinfo 或可解析 URL 的 password（包括空密码），认证由宿主 Git 管理。创建 Project / SourceSnapshot / Run 的输入 Schema 拒绝这些形式，不重写原 URL；无密码 SSH username、scp 形式及本地 origin 保持兼容。Runtime 在注入 Snapshot 上下文前重复校验，历史含凭据 Snapshot 在 AgentSession / Attempt 创建前阻断且不改写历史。此守卫不扫描路径、query 或任意文本中的秘密，也不证明仓库可达。

原则：

> TestRun 必须能够回答“测试的到底是什么”。

---

## 11. TestRun

TestRun 是用户可见的一个测试任务：一个 SUT 对应一个长期 Project，一个 feat / MR 的精确 SHA 的一次测试轮次对应一个 TestRun。TestRun 绑定 SourceSnapshot 和 PolicySnapshot，固定 PRD、配置、环境与策略，并拥有 CREATED、ANALYZING、DESIGNING、IMPLEMENTING、EXECUTING、DIAGNOSING、VERIFYING、COMPLETED、BLOCKED、CANCELLED 等运行状态。同一 SHA 可显式创建多个独立测试轮次；禁止以 `(project, SHA)` 唯一约束吞掉复测历史。

每个 Run 具有一个稳定的逻辑 Task Worker 绑定和一个持续主 Harness Session，由领域模型的 Operational `RunExecutionBinding` 表达。逻辑绑定不等于容器 ID、PID 或短期 Job lease；物理进程重启/恢复必须继续原绑定、原会话和原 Workspace，并取得有效 fencing。不同 Run 可以并发，包括同一 Project 下不同 MR、不同 SHA 或显式复测轮次；同一个 Run 内不进行多 Worker fan-out。

PASS / FAIL 不属于 TestRun Status，而属于 Verdict。

---

## 12. Mission

Mission 是 HyperTest 内部最重要的工作单元：

> 为推动 TestRun 从当前 State 向目标 State 转移而创建的 Testing Work Unit。

典型类型：ANALYZE_REQUIREMENTS、ANALYZE_RISKS、DESIGN_TESTS、IMPLEMENT_TESTS、DIAGNOSE_FAILURE、INVESTIGATE_FINDING、VERIFY_COVERAGE。Mission 保留为阶段目标、权限、验收与审计边界；一个持续 Session 可以依次履行多个 Mission，Mission 完成不关闭或另建会话。

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

Mission Retry 不覆盖历史 Attempt，而是创建新的 MissionAttempt。v0.4 的新 Attempt 仍使用该 Run 绑定的持续主 Session；会话丢失时明确阻断恢复，不能用新会话冒充原会话。具体恢复和新测试轮次规则以领域模型为准。

---

## 14. Test Planner

v0.4 的 Planner 是确定性的依赖、准入与覆盖守卫，不是驱动模型 reasoning 的外部 Agent Loop。Harness 在同一会话中读取 Canonical State、提出下一阶段意图、提交 Proposal、请求执行并分析反馈；Planner / Mission Compiler 判断该意图是否符合输入、Policy、依赖、覆盖缺口和资源限制，为允许的工作建立不可变 Mission。像“P0 Risk 没有 Case”这样的完整性检查仍由平台确定性组件完成。

平台可拒绝越权、依赖不满足或没有覆盖进展的请求，并把结构化原因返回原会话。平台不为每个阶段重建 Session，不逐条规定 Harness 的思考、工具调用或局部重试。Gate 的正式质量决策也不由 Harness 代写。

### 14.1 v0.4 Run 执行与并发

一个 Run 的逻辑 Task Worker 负责托管该 Run 的同一个主 Session，按序完成分析 → 风险 → 设计 → 实现 → 请求正式执行 → 诊断/修正 → 报告。按冻结 Policy 允许的诊断、补充测试或重执行仍在同一串行周期内；不增加 Run 内并行 Worker。Typed domain tools 把每个阶段的 Mission、Attempt、Proposal、Runner 请求和 Gate 决策保存为平台记录，不把原生 Session 变成 Canonical Store。

平台仍使用 PostgreSQL DurableJob 和 `SKIP LOCKED` 分发工作，但任务领取必须匹配 `RunExecutionBinding` 的逻辑 Worker、主 Session、Harness Host 和 Workspace。每次执行性外部调用和正式提交同时受当前 binding epoch 与有效 Job lease 约束；旧进程、失效 epoch 或迟到结果不得继续调用 Harness、提交 Proposal、启动正式 Runner 或创建 Issue。具体字段、唯一约束和恢复事务以领域模型为准。

WAITING_INPUT 原子持久化问题和等待状态，释放运行 lease、CPU 和 Provider 调用名额，保留逻辑绑定、原生会话与宿主亲和性。用户回答后恢复原会话；阶段内等待还恢复原 Mission / Attempt。物理 Worker 容器或 PID 可以在显式恢复后变化，但必须 fencing 掉旧持有者并继续同一绑定与工作区；不能由任意空闲 Worker 静默换会话接管。租约失效或未知外部结果仍显式中断，不承诺 exactly-once，也不自动重放正式执行或 GitLab 副作用。

阶段内问题沿用 `MissionInputRequest`；阶段边界或 GitLab 策略决策处没有非终态 Mission / Attempt 时，使用 Operational `RunInputRequest`，不重开已经完成的阶段。两种问答都暂停同一 Job / Session / Run 绑定，回答重新排队原 Job，并在原绑定下继续。字段与互斥约束以领域模型为准。

多个 Run 可各自绑定逻辑 Worker 并发推进；同一 Project 不需要全局串行。调度分别限制活跃 Run、宿主 Harness 调用和 Runner 执行数量，避免把 Worker 副本数误认为可安全运行的模型或测试并发数。

### 14.2 当前 v0.3 deterministic controller

以下为既有 bounded controller 的实现记录，供迁移与历史兼容使用；此旧路径不提供 §14.1 的持续会话、自驱域工具与绑定调度，本分支通过独立 persistent profile 实现这些能力：

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

### 14.3 当前 v0.3 Durable Work Queue

PostgreSQL 保存 Job 的请求、状态、结果与 Worker liveness；队列属于平台 Operational State，不把 Canonical 状态塞入 Job JSON 或 Agent Session。每个 Run 同时最多一个活跃 Job，重复 idempotency key 必须匹配相同输入。独立进程 `python -m hypertest.worker` 通过 `FOR UPDATE SKIP LOCKED` 领取任务、续租并执行既有服务。API 与 Worker 共用数据库、Artifact Store、Workspace Root 和宿主集成配置。

周期在 Git / Agent 之前调用所选 `DockerRunner` / `LocalRunner.fingerprint` 做只读就绪预检，确认 Docker daemon / 预制可信镜像可访问，或本地 Runner 已显式启用。预检前 owner guard 后提交释放 Run / Job 行锁，预检后重新 fence / admission；不持锁跨 Docker I/O，不自动 pull / install，不创建 Execution 或 Evidence。预检不保留环境可用性，正式执行仍重新检查。独立 Gate 评估不要求 Runner 就绪。

`ADVANCE_RUN` 恰选一种输入方式：`prepare_workspace: true` 且不传 workspace，或使用已有 workspace 且 `prepare_workspace: false`（缺省）。自动方式由同一 Job 调用既有 source preparation 服务，准备固定 GitHub HTTPS commit 后继续周期；不新增 Job 类型。准备在 max_steps 计数前执行，失败时不创建 AgentSession / Mission。controller 在 Git I/O 前提交并释放 Run / Job 行锁，准备后重新检查 operation ownership / lease，失联 Worker 不得继续派发 Mission。最终周期 result 返回已解析 workspace，供 UI 后续操作；独立 `PREPARE_WORKSPACE` 仍可使用，其他 Host 保持明确已有 workspace 模式。

Worker 对每次 Canonical commit 使用有效 lease token、Job 状态与数据库时钟进行 fencing，租约锁顺序为 TestRun → Job。MissionAttempt / TestExecution 使用不可变 nullable durable_job_id FK 保存同一 Run 的受控归属；恢复不依赖跨宿主时间戳推断，也不替历史 direct API 调用回填关系。取消先持久化，再中断外部工作；API 重启或 Web 刷新不取消已提交的请求。Worker 退出或租约过期会显式记录 INTERRUPTED，并把其拥有的未完成 Attempt / Execution 转为可观察的失败，保留原始历史。恢复不会自动重放可能已产生外部影响的任务，用户检查后创建关联新 Job 重试。租约不保证外部执行 exactly-once。

受控 `MISSION_REJECTED` / `MISSION_FAILED` 停止使 Job 进入 FAILED，并保存 stop reason、已持久步骤、关联 Mission ID 与已解析 workspace；独立 EXECUTE_MISSION 拒绝还保存 Attempt ID。这些是导航与恢复信息，不是新的 Canonical 测试事实。已有 FAILED Mission 不能误报为活动中或自动重放。通用异常未必具有部分 result；取消与失联仍以其已提交终态为准，不写入迟到 handler 的推测结果。终态 Job、原 Proposal / Attempt 与显式 retry lineage 保持不变。旧 ADVANCE_RUN payload 缺少新增缺省 `prepare_workspace: false` 时，仅在内存中按 schema 规范化后比较幂等输入，不改写历史 payload。

Docker 的 staging / execution containers 和预创建的 source / result volumes 均带 Job UUID label。失联恢复先提交领域终态，再在数据库锁外清理精确匹配的受控资源；`job.resources_cleanup` Audit / Outbox 记录可用性与清理数量。清理属于运行治理，不是测试 Evidence。Docker 不可访问或 provider 残留进程仍需 Operator 检查。

兼容 direct `/advance` 仍是同步调用，不独占整个 Loop。controller 在每个 Planner 步骤前后重新检查当前操作归属；若服务提交间隙入队了 DurableJob，旧 direct controller 停止继续派发，避免替新 Job 启动未归属的工作。

每个 Worker 一次处理一个 Job，可启动多个 Worker 处理不同 Run。`worker_heartbeats` 提供近期活动状态；后台 Worker 仅消费用户提交的工作，没有新增自动发布、任意 Agent reasoning loop 或周期性项目扫描 Scheduler。

---

## 15. Mission Compiler

v0.4 中 Harness 通过受控 `request_mission` 提出阶段意图，Planner 验证准入后由 Mission Compiler 负责：Resolve Context、Attach Policy、Calculate Permissions、Build Acceptance Criteria、Select Output Schema、Select Execution Profile，最终生成不可变 `TestMission`。

当前 v0.3 DESIGN_TESTS 编译上下文包含同一 Project / SourceSnapshot 下的 Canonical Risks、PolicySnapshot 引用和覆盖评估。Mission 固定目标 Risk 和 missing dimensions；Verifier 至少要求有效 Proposal 对其中仍缺失的一个维度形成进展。Mission 完成不等于整个 TestRun 设计完成，剩余缺口由下次 Planner 评估。

---

## 16. Agent Gateway

Agent Gateway 是 HyperTest 与外部 Agent Harness 的 Anti-Corruption Layer，防止 Codex / Claude / OpenCode 的 Provider-specific Session、Event、CLI/API Model 渗入 HyperTest Domain。

v0.4 的 Gateway 位于平台 Task Worker 一侧，通过 Host Harness Bridge 访问宿主 Provider Adapter。Bridge 与 CLI / SDK 留在宿主机，由 systemd 管理；它只负责受控会话生命周期、Provider 调用、取消和事件投影，不拥有 Canonical 数据写权，不负责规划模型思考。

统一接口概念：

```python
class AgentHarness:
    async def create_session(self, workspace, profile): ...
    async def execute(self, session, mission): ...
    async def restore_session(self, session, workspace): ...
    async def resume(self, session, mission): ...
    async def interrupt(self, session): ...
    async def close(self, session): ...
```

这些是生命周期能力，不表示在每个 Mission 调用 create / close。v0.4 在 Run 获得绑定时创建主会话，之后的 Mission 和人工回答在同一会话中执行或 resume；只有整个任务结束、取消或不可恢复失败才关闭会话。

当前 v0.3 实现：`CodexAdapter`，由 Worker 直接运行本地 CLI。`ClaudeCodeAdapter`、DeepSeek Harness 及其他 Provider 属于后续可替换路线，统一接口不表示已完成这些集成。

restore_session 使用已持久化的 Gateway handle、真实 Provider thread 引用和受控 workspace 恢复进程内映射，不能创建新会话冒充原会话。当前 v0.3 的阶段内人工问答以 resume 进入原 Mission / Attempt 的下一交互轮次；人工回答不是新 Mission，原 Attempt 的 Job 所有权和冻结 spec 保持不变。v0.4 对 Run scope 问答则恢复同一 Run 的主会话和原 Job / 绑定，不伪造活动阶段或重开已完成 Mission / Attempt；阶段内问答继续保留原 Attempt。完整 Capability 协商和跨 Provider 的恢复不由接口声明推断为已实现。

### 16.1 Host Harness Bridge 边界（v0.4 目标）

单台 Linux 宿主机首先使用受限 Unix domain socket，把 socket 的专用目录挂载给授权 Task Worker；按专用服务 UID/GID 和文件权限控制访问，不向 Web、API 或测试容器挂载。Bridge 校验调用方身份、Run 绑定、执行性调用的有效 epoch / lease，Worker 进一步校验当前 Mission / Attempt 范围和领域准入，串行处理同一 Run 的会话调用。本分支已实现 `hypertest.harness-bridge/v1alpha1`；实际操作、签名上下文、续约与管理授权见 [Host Harness Bridge](../HARNESS_BRIDGE.md)，生产启用单独验收。

执行授权与管理/恢复授权分开：create / execute / resume 及领域写调用必须匹配当前有效绑定、epoch 和 Job claim；原 claim 撤销后，可信管理组件仍可用限范围管理授权查询、对账、interrupt / close 和清理明确的历史 binding / Session / call。该授权可以指向原调用的历史 epoch，但不能启动新执行、创建替代会话、提交 Canonical 事实或绕过显式恢复。不能以“旧 claim 无效”阻止取消清理，也不能把管理授权变成新的执行 owner。

允许面限于结构化 create / restore / resume / interrupt / close、受控事件与结果、健康/能力查询。请求绑定显式 Provider、既有会话/工作区身份、有界 timeout 和幂等身份；不提供任意 shell、可执行路径、host mount、Provider 认证导出或通用宿主 RPC。Bridge 管理完整受控进程组、取消和失联清理，不能仅结束 Worker HTTP 请求便假定宿主 CLI 已退出。

多宿主机时再增加节点登记、认证和加密传输、会话路由及受控 Artifact 传输；原生会话默认具有宿主亲和性，不能因负载均衡而迁移到任意节点。该扩展不等于已实现跨节点 resume。

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

当前 v0.3 Codex CLI Adapter 通过官方 `exec -` stdin 接口传输 UTF-8 Mission Prompt，避免大 PRD 进入 argv 触发宿主参数长度限制；写入与 stdout / stderr 读取并行，防止管道相互阻塞。正式响应仍使用严格 `--output-schema` 和 CLI 写入的 `--output-last-message` 文件，read-only sandbox 与非交互审批策略保持；Provider telemetry 不代替正式结果。大输入 subprocess 回归仅证明传输，不证明 Provider 上下文容量或语义处理能力。

Codex 的真实 thread.started 引用与 HyperTest 自有 AgentSession ID 分离持久化；Attempt.provider_metadata 保存 Gateway handle，恢复只调用明确的 thread UUID，不使用 --last 或旧占位值。exec resume 的 JSON / Schema / 最终结果文件选项显式传给 resume 子命令；Agent 仍在父 exec 的 read-only 沙箱内。人工输入使用结构化 WAITING_INPUT 控制结果，不假定普通 CLI 暴露实验性 App Server 工具。Provider 进程结束后返回可暂停标记，由 Worker 的租约归属事务决定是否持久暂停；Adapter 不自行改变 Canonical 状态。

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

v0.4 每个 Run 的 `RunExecutionBinding` 引用唯一持续主 AgentSession；Session 的生命周期覆盖多个串行 Mission / Attempt 和多次 Provider turn / CLI 进程。阶段结束、等待用户或进程退出都不意味着主会话结束。Provider 原生会话目录、认证和上下文压缩由宿主 Harness 管理；平台只保存恢复所需的受控外部引用与 Operational 状态。原生会话或 Workspace 丢失时明确阻断，不静默生成替代 Session；需要全新会话时显式新建测试轮次，并关联历史。

---

## 19. Context Delivery

Agent Context 不应该等于整个数据库 Dump。Context Compiler 根据 Mission 只构建最小充分上下文：Mission、Relevant Requirements、Relevant Risks、Relevant Cases、Relevant Evidence、Relevant Findings、Policy Excerpts、Repository、Source Diff。

> **Context should be mission-scoped, not project-global.**

持续会话不等于项目全权限：每个阶段的工具授权仍绑定当前 Mission / Attempt 和有效 Run 绑定，阶段结束后旧工具权限失效。Harness 可以保留上下文，但继续工作前通过领域工具读取当前已验证状态，不把聊天记忆或先前拒绝的 Proposal 当作 Canonical 事实。

---

## 20. Workspace

v0.4 每个 TestRun 绑定一个隔离、持续的受控 Workspace，供该 Run 的逻辑 Worker 和宿主主 Session 在完整周期中使用：

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

Workspace 需要区分固定源码、可写的生成/临时目录和已接受 Artifact；保护 Snapshot 中的 tracked source，不因持续会话而允许改写被测应用版本。阶段间保留所需上下文和生成内容，整个 Run 结束、取消或明确失效后才按保留策略清理，不能在每个 Mission 完成时删除。等待人工回答期间仍保留原目录；恢复时验证归属、固定源码与受控路径，禁止重用其他 Run 的工作区。

单宿主机中，Worker 和宿主 Bridge 通过专用持久目录共享必要 Workspace，并保持可验证的绝对路径映射、UID/GID 和读写权限；它不包含 Provider OAuth、API key 或完整原生配置目录。Provider 认证与原生会话目录仅由宿主服务访问，既不挂给平台容器，也不进入 Runner。API 与 Task Worker 的 Canonical Artifact Store 暂时必须使用同一持久根目录和相同绝对路径，保留已有 URI；后续改成对象存储必须先做显式 URI/读取兼容迁移。

以下为当前 v0.3 Workspace 实现记录；该旧路径按 Mission 创建/结束 Agent 副本，不满足持续 Run Workspace 目标。本分支 persistent profile 另以稳定 Binding 保留并核验原副本，不修改旧生命周期历史：

当前 Web 可通过同一 `ADVANCE_RUN` 的自动准备选项，或独立 prepare-workspace 操作，为 GitHub HTTPS 源准备/复用 managed pinned checkout，使用既有 Git proxy/auth，不重置 Operator checkout；其他 Host 使用明确的既有 workspace。准备阶段不得跨 Git 网络或文件 I/O 持有 Run / Job 行锁，进入后续领域工作前重新验证归属。

创建 Run 前，Web 可通过只读 `/sources/resolve` 将 credential-free GitHub HTTPS 的分支或标签解析为固定完整 SHA；同名分支/标签必须明确 ref namespace。解析不创建 Canonical Snapshot、不改写 checkout，仍在 bootstrap 时固定 SHA，Runner 继续独立验证匹配的 origin、commit 与 tracked 内容。其他来源保留手工完整 SHA 与匹配 Worker checkout 路径，不能把任意检出目录当作 repository origin。

当前 Runtime 在临时 tracked-source 副本中运行 Agent，固定 SourceSnapshot / PolicySnapshot 并注入 PRD 与规范化 Mission；Canonical Artifact 和业务状态不放入 Vendor Session。IMPLEMENT_TESTS 的生成源码作为 Proposal `code` 返回，经 Verifier 校验后进入内容寻址 Artifact Store，不直接修改用户 checkout 或应用 Commit。

该副本位于配置 workspace_root 下的 `.hypertest-agent-sessions/<UUID>/repo`，是可清理的托管 Agent 数据。WAITING_INPUT 时保留副本以跨 Worker / Gateway 实例恢复，不依赖 TemporaryDirectory 析构；正常完成、失败或取消时通过受限路径清理。恢复前从原 pinned source 重建 expected Hash 并验证副本，不使用 Agent 保存的 Hash 作为可信来源。缺失、改动或越界路径必须停止恢复；清理函数不能删除 Operator checkout、其他目录或符号链接目标。Provider 原生会话、临时副本及运行遥测都不升级为 Canonical Testing State。

---

## 21. HyperTest MCP

领域 MCP / typed domain tools 是 v0.4 自驱工作流的工具契约，本分支已在 `hypertest.tmp/v1alpha2` 与 `run-persistent-harness/v1` profile 实现，不能按现有 `v1alpha1` 消息直接改变语义。Harness 使用 `request_mission` / `complete_mission` 顺序推进阶段并提交 Proposal batch，使用 `request_execution` 申请可信 Runner，通过 `get_state` 读取正式事实继续诊断，最后通过 `evaluate_gate` 和 `submit_report` 请求判定并提交报告。平台保留工具准入、Schema/Policy/关系校验、事务提交及审计；不在工具实现中重建通用 Agent Loop。报告不引入新的 Mission Type，也不替代 Canonical State 或 Verdict。

当前 v0.3 使用预先物化的 Mission Context、结构化最终 Proposal 结果及独立 WAITING_INPUT 控制结果；尚未提供完整 MCP 域工具或 Mission Token 工具授权，不能由协议定义或状态枚举推断这些功能已实现。WAITING_INPUT 的持久问题、Web 回答与原会话 resume 不依赖完整 MCP，具体契约见 TMP §29、领域模型 §23.2；真实模型验收按实际版本单独登记。

当前阶段内等待时，同一 DurableJob 保持非终态但释放 Worker lease，继续保留 per-Run 操作独占。Worker 原子提交 Question、Mission / Session WAITING_INPUT 与 Job WAITING_INPUT；回答通过 row_version 和 idempotency_key 防并发覆盖，在原 Job 上重新排队。新 lease 的 Worker 消费已回答问题、同事务记录 Audit / Outbox 后恢复同一 Attempt / Session，不重复启动已完成步骤，也不覆盖取消或失败历史。v0.4 还必须保留并检查原逻辑绑定和宿主亲和性，而不是因 lease 释放就重新选择会话。v0.4 的阶段边界问题使用本分支已实现的 `RunInputRequest` / `run_input_requests`，暂停同一 Job / Session / Binding，不依赖或重开已完成的 Mission / Attempt；回答后继续原会话，由下一阶段准入建立后续工作。回答仅作为补充上下文，原 PRD、Snapshot、Policy、spec / spec_hash 与 Canonical 接受规则不变。Provider 会话丢失时明确失败，显式重试仍保留旧记录；direct 无持久 Job 的等待请求不能留下不可恢复的暂停状态。

Read Tools 目标语义：`get_mission`、`get_requirement`、`get_risk`、`get_test_case`、`get_coverage`、`get_execution`、`get_evidence`、`get_finding`。本分支统一通过分页 `get_state` 的受控资源读取，不提供这些同名别名端点。

Proposal Tools 目标语义：`propose_requirement`、`propose_risk`、`propose_test_case`、`propose_implementation`、`report_finding`。本分支通过当前 Attempt 的 `complete_mission` batch 交由既有 Verifier 原子接受 / 拒绝。

Execution Tool：`request_execution`。

Interaction / completion tools（本分支）：`ask_user`、`evaluate_gate`、`submit_report`、`request_gitlab_issue`、`get_issue`；其中 `evaluate_gate` 实现目标 `request_gate` 语义。关键产品歧义和需要用户决策的分支通过 `ask_user` 进入持久 WAITING_INPUT；回答后继续原会话。对开发的缺陷协作通过受控 GitLab 集成：只允许已配置的 Project、责任人映射与提单策略，必须关联已接受 Finding / 可信 Evidence、精确 SHA 和 Run；先执行去重/幂等校验，外部写入结果与 Issue 引用进入审计。GitLab 凭据仅由可信集成持有，不传给 Agent。Issue 创建不自动确认 Finding、不替代修复验证或改变 Gate 结论，未知外部结果先查询/核对，不自动重复提单。该受控集成已有实现及注入 HTTP transport 的数据库回归，尚未向真实 GitLab 提单验收。九工具名称、分页与权限映射见 TMP §25.2。

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

v0.4 Runner Controller / 执行组件在授权 Task Worker 一侧接收领域请求，按 Canonical Implementation 和冻结环境构造 ExecutionSpec，再启动临时隔离测试容器。API 仅接收请求和提供状态，不挂载 Docker socket。具有 Docker 控制权的 Worker / Runner 组件属于高权限可信基础设施，必须与 Host Harness、Web/API 及不可信测试代码隔离；不能把 Docker socket、Bridge socket、平台数据库或 Provider 凭据传进测试容器。

---

## 25. ExecutionSpec

ExecutionSpec 至少固定 execution_id、source_commit、environment、framework、targets、timeout、collect 等字段，并计算不可变 SHA256。

当前 Runner 只接受 Canonical TestImplementation 中的安全 pytest node ID，校验 Repository origin、完整 Commit SHA、干净的 tracked 内容以及实现源码 hash。平台复制 tracked 源码到隔离执行副本，按已接受 Artifact 覆盖安全 `tests/**/*.py` 新文件；生成测试不能覆盖 Snapshot 中已跟踪文件。Execution 输入和环境指纹固定后才执行，重复 request key 不启动第二次执行。

---

## 26. Runner Backend

统一抽象 `RunnerBackend`，实现 DockerRunner、KubernetesRunner、SSHRunner、ExistingEnvironmentRunner。

多节点负载出现时可选择 Kubernetes Job 或其他受控执行节点；容器化首版不依赖 Kubernetes，也不把 Harness 会话改成短期 Agent Job。Runner 可以有不同后端，但同一 Run 的任务编排仍为单 Worker / 单主会话串行模型。

MVP 提供 DockerRunner 与显式开启的 LocalRunner。DockerRunner 使用预构建 Python/pytest 镜像，并记录解析出的 image ID；禁用网络、只读根文件系统、非 root、移除 capabilities、限制资源。执行时不安装依赖。LocalRunner 仅用于受控开发环境，需 `HYPERTEST_RUNNER_ALLOW_LOCAL=true`，不是安全沙箱。

受控环境扩展见 [ADR-012](ADR-012_CONTROLLED_API_ENVIRONMENTS.md) 与领域模型 §9：平台提供 `python-pytest-v1` 和预装 FastAPI / uvicorn / httpx 的 `python-api-v2`，完整传递依赖经 pin/hash 的 binary wheelhouse 离线安装到 digest-pinned 基础镜像。bootstrap 固定实际镜像、依赖锁和 launcher 身份，运行按绑定 image ID 校验；不执行 Repo Dockerfile / 安装 hooks，不接受 Agent 或 Web 提供任意依赖、Shell、host mount、外部 URL 或网络配置。

当前 API-v2 固定禁用仓库 pytest 配置和所有 conftest（`-c /dev/null --noconftest --rootdir=/repo`），生成测试/fixtures 须在提交模块内自包含；原 API-v1 与 pytest-v1 launcher/lock/image 保持历史身份，迁移0012只扩profile CHECK。

API profile 的可信 launcher 在同一 Docker 容器内启动单个 ASGI SUT，通过 `127.0.0.1:8765` 有界 HTTP200 就绪探测后启动 pytest，注入 `HYPERTEST_BASE_URL`。保留 `--network none`（仅容器 loopback）、只读源、非 root、资源限制及 Job 标签清理，不开放宿主端口。Runner 采集服务生命周期、探测身份、退出/清理结果及有界日志；未就绪、早退、超时或证明缺失不得形成 PASS。服务就绪仅为环境事实，真实业务断言与最终 Gate 仍独立。image inspection、服务等待和 Docker 执行不持 Run/Job/Project 行锁；正式 Execution 预留与结果提交前后仍按已有 lease 重新 fencing。External SIT、多服务、外部数据库、秘密与其他语言/框架另需明确契约。

---

## 27. Evidence Collector

Runner 执行完成不能只返回 PASS / FAIL，必须输出 Execution Metadata、Command、Exit Code、JUnit、Stdout、Stderr、Logs、Metrics、Traces、Screenshots、Artifacts。

PostgreSQL 保存 Evidence Metadata、Hash、URI、Relations。首版继续使用持久的本地内容寻址 Artifact Store，并在 API / Worker 中保持一致绝对路径；S3 / MinIO / Object Storage 是后续有独立需求时的迁移选项，不是容器化前提。

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

当前辅助活动面板通过独立 Operational 表 `mission_activity_events` 与只读 Job activity API 提供。Adapter 只输出允许列表的活动代码；不透传 Provider JSONL、推理、命令、路径、消息正文或 stderr。固定类型、来源、平台时间、合并计数和平台所属身份足以说明“最近观察到了什么”，不把原始 Agent 会话复制成平台状态。

采集通过有界队列和独立单写入器，约 2 秒合并、每 Attempt 保留最近 200 条。短事务检查当前有效 Job lease / claim、Run / Attempt / AgentSession 关系；繁忙或失效时丢弃遥测，不跨 Provider I/O 持锁，不让活动收尾与主任务完成事务互等。正式 Result 与 Runner 事实仍由原通道提交，遥测失败不会变更 Canonical 结果。活动不写领域 Outbox，也不参与 Gate hash。

Web 区分当前领取的 Provider 信号、该 Job 的 Worker 心跳与接口最近成功刷新，使用服务器观察时间避免浏览器时钟误差。人工等待不消耗运行 lease，也不构成模型静默；沉默提示不判定卡死或自动重放。首次实现使用有界轮询，不以引入 SSE / Redis 作为前提。关系、保留与取消边界见领域模型 §23.3，消息边界见 TMP §21。

---

## 34. Persistence

PostgreSQL 负责 Domain State、Mission State、Run 绑定、DurableJob、Audit、Outbox 和 Metadata；持久 Artifact Store 负责 PRD、Artifacts、JUnit、Logs、Screenshots、Reports。首版使用 PostgreSQL 队列，不新增 Redis / Kafka / MinIO 前提。未来确有容量或共享存储需求时再引入并容器化中间件；任何缓存或队列都不能代替 Canonical Store。

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

v0.4 的容器化本身不构成 Agent 安全沙箱。宿主 Harness 必须使用专用服务身份、Provider sandbox / approval、限定工具和受控目录；平台容器资源限额不会约束宿主 CLI 或 Docker 创建的子容器。Task Worker、Harness 和 Runner 分别设置并发与 CPU/内存/超时预算，独立保留取消与清理能力。Provider OAuth 和密钥只保存在宿主认证目录，现有认证不得通过复制到镜像或共享 `.codex` / `.claude` 来迁移。

---

## 38. 单宿主机目标部署（v0.4）

```text
Linux Host
├── Production Docker Compose
│   ├── nginx             # 唯一受限访问入口
│   ├── web               # Next.js production
│   ├── api               # Control Plane / typed domain API
│   ├── task-worker A     # Run A 的逻辑绑定，Gateway / Runner Controller
│   ├── task-worker B     # Run B 的逻辑绑定，同一 Project 也可并发
│   └── postgres          # Canonical + Operational + Audit + Outbox + Queue
├── Host Harness Bridge   # systemd，受限 UDS，仅授权 Task Worker 可调用
│   ├── Run A → 原生 Session A → Codex / Claude Code / DeepSeek Harness
│   └── Run B → 原生 Session B → Codex / Claude Code / DeepSeek Harness
├── Trusted Docker Runner
│   └── 临时隔离测试容器   # 只处理批准 ExecutionSpec，独立采集事实
└── Persistent data
    ├── 既有 PostgreSQL volume
    ├── Canonical Artifacts（API / Worker 同绝对路径）
    ├── Run Workspaces（Worker / Bridge 受控共享）
    └── Provider 认证与原生 Session（仅宿主身份访问）
```

所有平台服务和平台 Task Worker 容器化。一个 Run 只绑定一个逻辑 Task Worker 和一个持续主 Session；上图的 A/B 是两个独立任务，不是同一 Run 的多个执行分支。物理容器可回收或经显式恢复替换，但不得改变绑定、原生会话、Workspace 和宿主身份。Agent Gateway / Runner Controller 可先作为 Worker 内模块；只有存在明确需求才拆成独立服务。

数据库不暴露公网；API、Web 和内部服务仅在私有网络或受控回环入口通信。Nginx 保留现有 VPN 来源白名单与 SSH 备用路径。Docker 发布端口与宿主防火墙的处理路径必须专项核验，不能仅凭原 UFW 规则推断容器入口仍受限制；保留拒绝非白名单来源的实际探测证据。已有密码登录和 `ssh hypertest-one` 密钥别名继续保留，自动运维按 [Remote operations](../../AGENTS.md#remote-operations) 使用统一密钥连接。

### 38.1 生产配置与调用边界

- 新建独立生产 Compose 配置，与现有开发 `docker-compose.yml` 区分；现有文件含开发口令、源码挂载、`--reload` 和 API 启动内迁移，不能原样宣称生产可用。
- Web/API/Worker 使用不可变、带明确版本的构建镜像；API 与 Worker 发布必须通过协议、数据库 schema 和 Job payload 兼容性检查。在途任务先 drain 或显式中断/恢复，不让旧版本 Worker 持有无法理解的新绑定或工具契约。
- Alembic 作为受控一次性 migration job 运行，成功后再启动兼容服务，不由多个 API/Worker 副本同时自动迁移；应用回滚不自动回滚 schema。
- API 不获得 Docker/Bridge socket 或 Provider 凭据。Worker 的能力与就绪检查、受控环境目录和实际镜像解析通过授权 Worker / Runner 通道提供；在冻结 Snapshot 前完成实际镜像绑定，正式执行按既有 image ID/依赖锁/launcher 重新核验，禁止降级或改按当前 tag 执行。
- 取消先持久化并使旧调用失效，再由 Worker / Bridge / Runner 分别终止其受控进程组和精确带归属标签的容器/volume，记录清理结果；API 容器重启、HTTP 断连或仅清除 lease 都不能证明外部执行已停止。
- 分别限制平台 Worker、宿主 Harness、Runner 的资源和并发；容器副本数、活跃模型调用数、正式执行数是三个独立容量。实际服务器容量必须压测，不预设增加副本就能承载多个活跃测试任务。

### 38.2 迁移与数据保全

容器化迁移必须在单独实施变更中完成，不能通过本文更新推断远端已切换。迁移前核对真实服务、活跃任务、数据库迁移 head 和配对 DB/Artifacts 备份，演练恢复与应用回退，并在无活动执行或受控 drain 后切换。

显式复用现有 PostgreSQL volume、数据库数据、Canonical Artifacts、固定 Snapshot、FINAL Verdict 与 Audit/Job/Attempt 历史；保留 Workspace、Provider OAuth/原生会话、服务配置、SSH 密钥/密码登录和 VPN allowlist。不要因 Compose project name 改变而误建空数据库或将匿名新 volume 当作旧数据，不执行删除 volume 的清理。已持久化 PRD 等输入的绝对路径引用和 Evidence / Implementation 的 `sha256:` 内容地址必须在 API/Worker 中可读，不能先改挂载路径再假定历史输入和证据仍可访问。

在旧 release 与配置保留的前提下核对数据计数、关键摘要、真实 Artifact 读取、数据库 readiness、Web/API health、Worker heartbeat、Bridge 原生 session resume，以及正式 Docker Runner / Gate 完整闭环。新 Bridge 和绑定 schema 使用 additive migration；旧的 per-Mission Session 保持其真实历史，不把旧多会话 Run 回填成“一个持续会话”的已验收任务。

---

## 39. 并发与多节点演进

扩容单元是独立 TestRun。每个 SUT Project 可以有多个 feat / MR SHA 的 Run，同一 SHA 的显式复测也独立记录；各 Run 分别使用一个逻辑 Worker、一个持续主 Session 和隔离 Workspace。首版在同一宿主机增加 Task Worker 实例，受 Harness Provider/账号配额、CPU/内存和 Runner 容量共同限制。

未来多节点时，为每个执行节点登记 Harness 能力、可信 Runner 能力、容量和 Workspace/Session 亲和性。调度先选定绑定宿主，后续执行与人工恢复路由到原宿主；原会话或工作区不可达时进入可观察阻断，不向另一台机器静默创建新 Session。跨节点认证、受控传输、Artifact 可达性与取消 fencing 必须先实现，再宣称具备跨节点恢复能力。

Kubernetes 可以在有需求时承载平台或 Runner，而宿主 Harness 仍通过受控 Bridge 托管。本文替代原先“一次 TestRun 派生 N Agent Jobs、Agent Workspace 独立短期容器”的目标；不把 Run 内多 Worker / 多主 Session 作为未来扩容前提。若未来改变串行持续会话模型，需要新的 ADR 和领域/协议版本。

---

## 40. 实现状态与验收边界

v0.3 历史兼容路径已有 CodexAdapter、Python/pytest、DockerRunner、受控 ASGI profile，以及 Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding / Verdict 闭环。v0.4 保留其 Canonical 事实与历史语义，新增持续会话边界；目标仍是验证 Testing Semantic Chain，而非仅验证 Agent 能生成测试。

以下区分历史兼容路径、当前实现与仍需独立验收的边界：

| 领域 | v0.3 历史兼容路径（非当前生产拓扑） | 当前实现与验收边界 |
|---|---|---|
| 平台部署 | `0a2af9c` / `0012`，宿主 Nginx 与 systemd Web/API/Worker + Docker PostgreSQL | 正式五容器 Compose + 宿主 Bridge 已切换；源码 `f415fd0` / 运行构建 `95e92c5` / schema `0014`，数据 / OAuth / SSH / VPN 保全已验收 |
| Harness 调用 | Worker 直接运行 Codex CLI | 已实现宿主 Bridge + 受限 UDS，认证与原生会话留宿主；本地及正式容器 Worker 的真实 Codex 链路已运行 |
| 调度与会话 | PostgreSQL Job；逐 Mission 创建/关闭 Session；bounded controller 推进 | `0013` / `0014` 支撑稳定 Binding、主 Session 与运行账本；正式正向经 Web 显式恢复后完成报告，负向在运行补丁下完整完成 |
| 人工交互 | 阶段内持久 WAITING_INPUT、Web 回答和原 Attempt/Session resume | Mission / Run 两类问答已实现并真实消费回答，原 Job / Session / epoch 保持，最终形成 `RELEASE_READY` 报告 |
| 运行工具 | Mission Context + 结构化最终结果，无完整域工具 | 已实现 v1alpha2 profile 九工具、分页读取、准入 / 验证、正式执行与 Gate、报告及 Run 总活跃时间预算 |
| Provider / 协作 | 默认 Codex；无完整多 Harness 协商和 GitLab 提单集成 | Codex 能力探测已实现；受控 GitLab 配置、去重与未知结果对账已有回归，真实提单与其他 Provider 尚待验收 |

本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)；正式正反链、恢复、配对备份与访问边界见[正式部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。宿主实际重启、真实 GitLab 提单和其他 Provider 尚未据此验收，后续 Web 改进须单独记录结果。

v0.4 验收至少覆盖：同一 Project 的两个独立 Run 并发；单 Run 全周期只有一个逻辑 Worker 绑定和一个真实原生 Session；跨多个 Mission 的上下文保持；人工等待释放运行资源后原会话恢复；物理 Worker 显式恢复时拒绝旧 epoch/lease；会话/Workspace 丢失不静默替换；可信执行、Evidence 验证与 Gate 判定；Issue 幂等与取消；迁移前后数据/Artifacts/认证/SSH/VPN 保全。fake Harness 或文档检查只能验证契约，不能代替真实 Provider、生产拓扑和多任务验收。

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
- **ADR-012** [受控 Python 与隔离 ASGI 环境](ADR-012_CONTROLLED_API_ENVIRONMENTS.md)：SourceSnapshot 固定实际镜像/依赖/launcher，可信 Runner 管理同容器 loopback HTTP 服务生命周期与证据，legacy NULL 保持旧身份。
- **ADR-013** [平台容器化与持续 Harness 会话](ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)：平台服务/Task Worker 容器化，Harness/Bridge 留宿主；一 SUT 一 Project，一 feat/MR 精确 SHA 的测试轮次一 TestRun，一逻辑 Worker 与一持续主 Session 串行完成完整周期，Run 间并发。领域模型拥有绑定/唯一性/恢复规则，TMP 拥有持续会话 profile/工具契约，本文拥有服务/部署边界；该目标不等于已实施迁移。

---

## 42. 最终技术定义

```text
Project（SUT）
  ↓
TestRun（feat/MR 的精确 SHA + 冻结输入/Policy + 一次测试轮次）
  ↓
单一逻辑 Task Worker 绑定 + 宿主上的单一持续 Harness Session
  │
  ├─ Harness 自驱串行分析 / 设计 / 实现 / 诊断 / 报告
  │      ↕ typed domain tools / Mission admission / WAITING_INPUT
  ├─ Proposal → Verifier → Canonical State
  ├─ request_execution → 可信 Runner → Verified Evidence
  └─ evaluate_gate（request_gate 语义）→ Gate → Verdict

多个独立 TestRun 可并发；同一 Run 不派生并行平台 Worker。
```

HyperTest 复用 Harness 的智能与 Agent Loop，维护测试输入、结构化状态、执行信任、策略决策和长期历史，成为可靠的软件测试控制平面。
