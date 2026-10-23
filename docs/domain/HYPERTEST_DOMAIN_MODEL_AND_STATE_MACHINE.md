# HyperTest Domain Model & State Machine Specification

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](../LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](../local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。

**Document Status:** Normative / Accepted v0.8 / ADR-018 Session Task Management (2026-10-21, Asia/Singapore); implementation and acceptance tracked separately. ADR-017 and legacy production histories retained below.

**Version:** v0.8

**Current-stage precedence:** [ADR-018](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) adds SessionTask management (§50): one `(provider, session_id)` identifies one task under an existing Project. Task progress, reported test result and synchronization outcome are distinct. Case/report revisions and receipts preserve history; permission, expected-version and idempotency validation govern acceptance. No source snapshot, policy, execution binding, Job, Runner, Gate or independent CI proof is required for synchronization. ADR-017 §49 and legacy execution facts retain their own meaning and history.
**Parent Documents:**

- HyperTest Whitepaper v1.6 (v1.4 product responsibility correction retained)
- HyperTest Technical Architecture v0.8
- Test Mission Protocol Specification v0.8
- [ADR-018 — Codex Session Task Sync](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md)
- [ADR-017 — Native Framework Evidence and Handoff](../architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md)
- [ADR-013 — Containerized Platform and Persistent Harness](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
- [ADR-015 — Dual-mode Harness and Local Connector](../architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)
- [ADR-016 — Interactive Agent MCP Access](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)

**Applies To:** HyperTest Canonical Testing State and its Operational Ownership Boundaries

### v0.7 适用范围

§49 定义 ADR-017 的独立 `native-framework-intake/v1alpha1` 持久化。经 Proposal / Verifier 接受的计划 / 用例是管理资产；NativeExecutionRecord / Material 是未验证观察，独立 NativeConclusion 只允许 UNKNOWN / BLOCKED，不是旧 Verdict / VERIFIED Evidence。本轮仍使用 PostgreSQL + 关系表 + Audit / transactional outbox，JSON / SQLite / 客户端 journal 不成为 Canonical Store。

下文 §9/9.1、§11、§15–17、§20–23.10、§25、§33–40 及 §46 的 v0.4–v0.6 限制继续约束旧 TestRun / Snapshot / Mission / Runner / Binding profile 及历史；其中 Runner 唯一、Python/pytest、固定主 Session 与源码上传不对 §49 新 native profile 施加执行引擎或聊天绑定要求。新旧 ID / 表 / 权限不可混用，不能把 native 材料回填为旧 Evidence 或修改旧 FINAL。新 native contributor 的私有代次 capability 才参与写入授权，session label 和可读取 generation 本身不是权限。

---

## 1. 文档目的

本文正式定义 HyperTest 的领域模型、实体关系、生命周期、数据库约束和持久化规则。

本文是 HyperTest Canonical State 的规范性定义。如果本文与上层架构文档在 Field、Relationship、Lifecycle、Uniqueness、Persistence、State Transition 上冲突，以本文为准。

### 1.1 Legacy v0.3–v0.6 实施边界

v0.4 已接受设计为：一个稳定 SUT 对应一个 Project；一个 feat / MR 的完整 SHA 及固定测试输入对应一次用户可见 TestRun。每个 Run 只有一个逻辑 TaskWorker 绑定及一个持久主 AgentSession，串行推进多个 typed Mission / Attempt。平台 Worker 和 Control Plane 容器化；ADR-013 已实现的 SERVER_HOST 模式将 Provider Harness、其认证 / 原生会话运行时及窄 Host Bridge 留在服务器宿主。不同 Run 可以并发，同一 Run 不引入多个平台 Worker 同时协作。

[ADR-015](../architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md) 已实现 LOCAL_CONNECTOR 模式：用户电脑的 Connector 主动建立 WSS 连接，托管原生 Harness 与受控集成，固定源码经 HTTPS 交付，Implementation 继续通过 typed Proposal 接受至 Artifact store；通用 Artifact HTTPS 通道不属于首版实现。SERVER_HOST 的现有 Unix domain socket Bridge 继续保留。首次绑定前明确选择模式和稳定节点，同一 Run 固定原节点、主 Session 与 workspace，不因离线自动切换。§9.1、§18.1 与 §23.9 定义新增约束，已由 `0015`—`0018` 和相关服务实现；隔离回归通过，私有 Git / HTTPS、真实正反周期、同会话断线恢复与 GitLab 测试 Issue / 负责人均已独立核验；扩展真实设备故障矩阵尚未全覆盖。生产已部署，严格外部 TLS、线上核心周期及私有源码 source-only 接受补验已通过；私有补验没有业务 Run 或问题单操作，见[生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)。本次实现不改写旧 ADR-013 生产基线和历史 hash；最终结果见 [ADR-015 总验收](../ADR015_ACCEPTANCE.md)。

[ADR-016](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md) 为 **Implemented / Isolated Tests Verified / Current-Agent E2E Verified / Production Deployed / Online Current-Agent Core E2E Verified（2026-10-20，Asia/Singapore）**：当前本地 Agent 通过 stdio MCP → 常驻 Connector → 新的 scoped typed HTTPS API 使用外接测试平台。§23.10 的 CLOUD / LOCAL 执行选择、显式绑定当前真实本地 Agent 为唯一任务主会话、受控领域工具及提交 / 读取契约已由 `0019` / `0020`、交互服务与客户端实现；普通 MCP 连接不自动成为 AgentSession，LOCAL + INTERACTIVE_MCP 绑定后不另开影子 Harness。既有 SERVER_HOST / LOCAL_CONNECTOR 两种 HarnessMode 保留，正式 Runner 信任与 Agent 位置独立。原唯一绑定、会话、租约和恢复不变量继续有效。空库迁移、隔离回归、真实 Docker Runner 契约测试及隔离当前 Agent 的完整周期均已验证：同一 native Session 经显式恢复保留原绑定，27 / 27 正式用例通过，5 份 VERIFIED Evidence 的 SHA-256 / size 读取、Gate FINAL / RELEASE_READY 与报告接受 / 分页读取均已核验，见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)。本次实现已部署生产，线上当前 Agent 核心周期已通过。

生产发布为 PR #17 / `c7cd43ad6346d8ce6c85564f7838afbb017f2da4`，正式库已向前升至 `0020_interactive_tool_inbox`；PR / main CI 为967 passed、21 skipped。同一真实当前 Codex Desktop Agent 经官方 MCP SDK console 完成生产核心周期：2 Requirements / 3 Risks / 4 Cases / 4 Implementations，唯一平台可信 Docker Execution 的33项 HTTP 测试通过，五份 VERIFIED Evidence 与两页报告内容均经 MCP 读取并核验 hash / 字节数，形成 FINAL `RELEASE_READY`。真实过期后的两次显式 Worker 恢复保留原 Run / native / workspace，epoch 1 → 2 → 3，旧 Job / Attempt 保留；最终历史保全另经39项只读检查通过。详细身份、时序与保全边界见[ADR-016 生产部署记录](../ADR016_PRODUCTION_DEPLOYMENT.md)及[生产机器证据](../evidence/adr016-production-20261020.json)。隔离验收的27项测试仍属其独立历史；本轮不宣称聊天原生工具目录热加载、运行中断线注入、两种原受管路径的新完整周期、私有 SUT 业务或新增问题单写入通过。

**ADR-013 的服务器运行归属与受控工具边界已实现，2026-10-19 正式迁移与真实正反链路已验收；该验收不覆盖 ADR-015 的本地 Connector 目标。** `0013_run_bindings` 实现 RunExecutionBinding、RunInputRequest 及跨 scope 约束；`0014_harness_operations` 实现运行 checkpoint、工具 / 预算账本、报告、管理请求与受控 GitLab 操作记录。本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)。ADR-013 正式切换与恢复的历史结果见[正式部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。历史 PR #10 当时部署源码 `828225d`，API/Worker/Web 同源更新，兼容 Host Bridge 保留 `95e92c5`，当时数据库为 `0014_harness_operations`；ADR-015 当时生产已升至 `0018_harness_selection`，历史发布与验收范围见[生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)；当前 ADR-016 生产为 `0020_interactive_tool_inbox`，见[当前生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)，当前运维边界见[服务器操作](../SERVER_OPERATIONS.md)。会话关闭后的平台治理准入由 [ADR-014](../architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md) 与 §23.8 规定，其实现和真实验收另行登记。受控 GitLab 真实创建已由 ADR-015 隔离记录独立验收；其他 Provider、未完成扩展矩阵及后续 Web 改进继续单独登记。本文标为“v0.3 已实现”的逐 Mission 会话、bounded controller 和 wire contract 保留当时的历史解释；新 profile 的版本与工具 schema 以 TMP 为准，现有 `hypertest.tmp/v1alpha1` 不被原地重解释。

Canonical Chain、不可变快照、Proposal / Verifier、trusted Runner、deterministic Gate、Audit / Outbox 及已有历史保护在两者中均有效。目标迁移不得把历史上一个 Run 的多条 AgentSession 合并成一条，不得改写原 Attempt / Execution 的 `durable_job_id`。

核心领域实体：

```text
Requirement
Risk
TestCase
Execution
Evidence
Finding
Verdict
Mission
```

支撑实体：

```text
Project
SourceSnapshot
PolicySnapshot
TestRun
TestImplementation
MissionAttempt
MissionProposal
AgentSession
```

v0.4 另定义 Operational 支撑记录 `RunExecutionBinding`（§23.4），用于任务执行所有权；它不是 Canonical Test Fact，也不是新的用户可见测试任务实体。v0.5 的节点、配对、Placement、短执行 grant、源码传输与 Issue executor 目标记录见 §23.9，同样不扩展 Canonical Testing Semantic Chain。

v0.6 / ADR-016 的受控 actor / client 身份、`RunExecutionSelection`、`InteractiveIntegrationGrant`、`InteractiveSubmissionReceipt`、`InteractiveExecutionBinding`、短执行 grant 与工具 inbox 见 §23.10，均为新增 Operational 支撑记录，不属于 Canonical Testing Semantic Chain；显式交互执行登记只引用既有唯一 RunExecutionBinding / AgentSession，普通 MCP 连接不能冒充原生主会话。

---

## 2. 核心领域链路

```text
Requirement
     │
     ▼
    Risk
     │
     ▼
 TestCase
     │
     ▼
Implementation
     │
     ▼
 Execution
     │
     ▼
 Evidence
     │
     ▼
  Finding
     │
     ▼
  Verdict
```

Mission 不属于质量事实链，而是推动 Testing State 演进的工作控制对象。

---

## 3. Canonical State 与 Proposal 分离

Agent 输出 Proposal；HyperTest 验证后才产生 Canonical Entity。

```text
Agent
  ↓
MissionProposal
  ↓
Verifier
  ↓
ACCEPT
  ↓
Canonical Transaction
```

禁止 Agent 直接 INSERT / UPDATE Requirement、Risk、TestCase、Finding、Verdict 等 Canonical Entity。

---

## 4. 主键规范

所有数据库主键使用 UUIDv7，数据库类型 `uuid`。

主要领域实体同时拥有 Human-readable Key：

```text
REQ-000123
RISK-000087
TC-000451
EX-000932
EV-001223
FIND-000041
VER-000028
MIS-000512
```

Human-readable Key 仅用于 UI、日志和 Agent 交流；数据库 FK 永远使用 UUID。

当前新 Operational Key 使用 `{PREFIX}-{完整 UUIDv7 十六进制大写}`，保留 UUIDv7 的随机位，避免只截取前 12 位毫秒时间造成同毫秒碰撞。上述短 Key 为阅读示例，已持久化的旧格式 Key 继续有效，不做重写。

---

## 5. 时间、锁与删除规范

- 所有时间字段使用 `timestamp with time zone`，内部统一 UTC，API 使用 ISO 8601。
- 所有允许更新的 Canonical Entity 包含 `row_version bigint`，使用 Optimistic Lock。
- Canonical Testing State 默认禁止 Hard Delete。
- 生命周期结束使用 DEPRECATED、SUPERSEDED、CANCELLED、REVOKED、OBSOLETE 等状态表示。
- Hard Delete 只允许未接受 Proposal、临时缓存、无引用 Workspace 等非 Canonical 数据。

Requirement / Risk / TestCase / TestImplementation 按 SourceSnapshot 共享，可被不同 TestRun 引用。Gate 的覆盖 / Canonical 读取、Verifier 的 Canonical Proposal 提交和 Runner 的共享 Implementation 更新，均先锁定所属 TestRun，再对同一 SourceSnapshot `FOR UPDATE`，使 Gate 决策与 Hash 基于一致状态。快照内容本身仍不可变；不跨实际测试执行或 Agent provider 执行持有该快照锁。

---

## 6. JSONB 使用规范

允许 JSONB 保存：metadata、provider_metadata、framework_specific_data、extension_data，以及具有天然复合结构的 Test Step / Preconditions / Expected Result。

禁止使用 JSONB 保存领域关系数组，例如 `requirement_ids[]`、`risk_ids[]`、`evidence_ids[]`。

领域关系必须通过 FK / Join Table 表达。

---

## 7. 核心关系图

```text
Project
 │
 ├── SourceSnapshot
 ├── PolicySnapshot
 └── TestRun
       │
       ├── Requirement
       │      │
       │      └── Risk
       │             │
       │             └── TestCase
       │                     │
       │                     └── TestImplementation
       │                              │
       │                              └── Execution
       │                                      │
       │                                      └── Evidence
       │                                              │
       │                                              └── Finding
       │
       ├── Mission
       │      ├── MissionAttempt
       │      └── MissionProposal
       │
       └── Verdict
```

Requirement ↔ Risk、Risk ↔ TestCase、Requirement ↔ TestCase、TestCase ↔ Execution、Evidence ↔ Finding 均允许多对多，通过 Join Table 表达。

---

## 8. Project

```text
id                  uuid PK
key                 varchar(64)
name                varchar(255)
description         text
repository_url      text
default_branch      varchar(255)
status              varchar(32)
deleted_at          timestamptz nullable
created_at          timestamptz
updated_at          timestamptz
row_version         bigint
```

唯一：`UNIQUE(key)`。

Project 不以 repository URL 为唯一键，长期允许 multi-repo。

**v0.4 目标：** Project 对应一个稳定被测系统（SUT），用于组织其多个 feat / MR 测试轮次。新增 feat、MR、commit 或重测不创建另一个 Project。repository 是该 SUT 的源引用，不代替 SUT 身份；此产品约定不新增 `UNIQUE(repository_url)` 或假定当前已有独立 SUT 表。

### 8.1 项目人工管理（2026-10-23）

Operator 可编辑 `name / description / repository_url / default_branch`，并将项目状态设为 `ACTIVE / ARCHIVED`；`id / key` 固定。修改仓库或默认分支只影响项目配置，不改写已有 SourceSnapshot、任务来源、冻结输入或测试历史。归档是项目管理状态，不取消任务、不停止执行，也不生成质量结论。

编辑、软删除和恢复都必须提供与当前 `row_version` 匹配的 `expected_version`，在同一事务中更新项目、递增版本并写入 Audit / Outbox。旧版本拒绝，不以最后写入覆盖并发修改。

删除只设置 `deleted_at`，不 hard delete 项目、不释放 `key` 唯一性、不级联删除测试资产。存在任何未软删除 SessionTask、任何 legacy TestRun 或任何 NativeTestRun 时拒绝删除。检查子记录与项目写入共享项目聚合锁；新 SessionTask 的创建同样检查项目未删除，避免并发创建产生隐藏的活动任务。恢复清除 `deleted_at` 并保留原项目状态与身份。默认项目列表及普通详情隐藏已删除项目；回收站显式读取包含已删除项的列表以发起恢复。

已删除项目拒绝新任务、源码快照、源码传输、上传授权及新的集成/节点能力授权。源码上传的最终接受与Connector采集请求的入队、投递均重新检查项目未删除，不能借删除前的transfer或capability继续新写入或新采集。已有来源记录及原回执保留只读核对；删除不回写旧transfer为取消，也不宣称已经取消发出的外部操作。

---

## 9. SourceSnapshot

SourceSnapshot 表示一次不可变测试输入快照。

```text
id                     uuid PK
project_id             uuid FK
repository_url         text
commit_sha             varchar(64)
branch                 varchar(255)
prd_sha256             char(64)
prd_artifact_uri       text
configuration_sha256   char(64)
environment_definition jsonb nullable
source_fingerprint     char(64)
created_at             timestamptz
```

创建后禁止 UPDATE。PRD、Git Commit、Configuration 任一变化都创建新 Snapshot。

`0006_immutable_contracts` 通过 PostgreSQL Trigger 拒绝 SourceSnapshot 内容变更与 DELETE，包括尚未被 TestRun 引用的 Snapshot；语义完全相同的 no-op UPDATE 可通过。不修改历史 Snapshot 来修复或重解释已有 Run。

输入物化规则：Web bootstrap 保存 PRD 与 configuration Artifact，非空 `prd_artifact_uri` 表示这一物化输入集。Runtime 在创建 AgentSession / MissionAttempt 前必须读取并校验两份输入的原始 UTF-8 与相应 SHA-256；空配置也有固定空内容 Artifact，缺失、不可读、非 UTF-8 或摘要不符必须停止，不能静默省略上下文。

既有 direct API 创建的 hash-only Snapshot（无 `prd_artifact_uri`）保留原配置可选语义，不强制补造 Artifact；若其配置已经物化，仍必须按 `configuration_sha256` 验证。兼容判断不能修改 Snapshot、替换固定 Hash 或把缺失内容视作已验证。此规则不新增领域字段或迁移。

Repository origin 安全边界：Project / SourceSnapshot / Run 创建输入拒绝 HTTP(S) userinfo 和可解析 URL 的 password（含空密码），在写入 Snapshot / Run / 输入 Artifact 前失败；认证配置属于执行节点的受控 Git 集成，不持久化在源身份。无密码 SSH username、scp 形式与本地 origin 不因此改写。Runtime 在注入 Context 前对历史 Snapshot 重复校验，拒绝时不创建 AgentSession / MissionAttempt，也不修改旧 Snapshot。此现有输入守卫不是对路径 / query / 任意输入内容的秘密扫描，不新增领域字段或迁移；ADR-015 新增的源码包准入另见 §9.1。API 422 校验错误仅返回 `type` / `loc` / `msg`，不包含 `input` / `ctx` / 原请求 body；错误响应不是领域事实或全面日志脱敏保证。

Fingerprint：

```text
SHA256(project_id + repository + commit_sha + prd_sha256 + configuration_sha256)
```

唯一：`UNIQUE(project_id, source_fingerprint)`。

`0011_execution_environments` 新增 nullable JSONB `environment_definition`。旧 Snapshot 保留 SQL NULL，不回填或重算历史 hash。新 Web/bootstrap 可选严格受控环境请求（`python-pytest-v1`，或 `python-api-v1` 加 ASGI `module:attribute` / 本地 health path / 有界启动时限）；平台在任何输入 Artifact / Snapshot 写入前、Project 行锁之外解析当前可信预制镜像，固定 schema version、规范化请求、实际 image ID / OS / architecture、完整依赖版本与锁 SHA-256、可信 launcher SHA-256。调用者不提交任意镜像、安装命令或冻结绑定。原 PRD/configuration 字节和各自 hash 保持独立。

对 non-NULL 新绑定，Source fingerprint 的规范化对象额外纳入完整 `environment_definition`；旧 NULL 不添加此键，保留原算法。Gate 的 SourceSnapshot 语义序列化同样仅在 non-NULL 时包含此键，防止增加空列改变旧 FINAL 的 state hash。全行 immutable trigger 同时保护新字段；不同环境或实际镜像创建新 Snapshot。既有低层 hash-only SourceSnapshot API 保持 NULL 的 legacy 路径，不通过缺省推断服务环境。

bootstrap 同幂等键重试先比较原始 PRD/configuration、规范化 repo/commit、生效 Policy 和规范化环境请求，匹配时直接返回原 Run/绑定；不因镜像 tag 漂移重新解析或替换。新请求解析后取得 Project 锁，再次检查同键竞争。新绑定只支持 Docker；正式执行必须按固定 image ID 重新核验依赖/launcher，不改用当前 tag 或降级。

`0012_api_environment_v2` 仅扩展受控 profile CHECK，增加 `python-api-v2`，不修改已有行、环境绑定或指纹。当前 Web 目录为 pytest-v1/API-v2；API-v1 历史请求与幂等重放仍受支持。API-v2 的新 launcher 明确禁用仓库 pytest 配置和 conftest，生成的 HTTP 测试须自包含。API-v1 与 pytest-v1 保留原 launcher/lock/镜像身份；不得把旧绑定重新解释成 v2。改变此执行语义、依赖或 launcher 必须另建 profile 版本与新 Snapshot，已有 FINAL 历史不得回填。

### 9.1 ADR-015 源码传输与不可变接收（已部署，线上核心验收通过）

LOCAL_CONNECTOR 的平台与 Harness 不共享本地绝对路径。受控源码准备以已批准的 Project / origin、完整 Commit SHA 和不可变 bootstrap 请求为输入，使用该节点已有 Git credential helper / SSH agent / CLI 授权取回准确 Git 对象。源码接受必须在新的 SourceSnapshot 冻结前完成；不得先创建可执行 Snapshot，再用迟到包替换其来源。准备失败只形成受控 Operational 失败，不创建正式 Execution / Evidence / Finding，也不改写现有 Snapshot。SERVER_HOST 仍可使用既有受控 pinned checkout；若采用传输包，同样受本节约束。

SourceBundle 必须携带平台可独立验证的原始 commit / tree / blob 对象及完整目标 tree 的 tracked 内容，以及 manifest 中的 Git object format、完整 commit、root tree、对象标识、相对路径 / 文件 mode 与包 SHA-256。包的内容须足以重算所声明的 Git 对象链，不接受只有文件清单、自报 Git Hash 或压缩包 SHA-256 的来源证明。平台自行解析并计算对象标识，检查 commit → root tree → tree / blob 的完整闭包、精确 SHA、manifest 与实际对象 / 文件一致性，并生成接收结果。首版拒绝未支持的 submodule / LFS 及外部下载依赖，直到有显式受支持的固定来源 / 对象验证契约；不能静默跟随远端或将指针当完整可执行源码。

对象一致性不证明该 commit 属于获准仓库。项目可以显式授予已配对节点的受控 source-acquisition adapter 来源采集角色；该 adapter 与 Agent 隔离，以节点已有 Git 授权从批准 origin / ref 取精确 SHA，产生设备认证的 acquisition receipt，固定 Project / 请求、origin / ref、commit / tree、包 digest、节点、授权策略及采集结果。平台独立校验 receipt 身份、范围和当前项目授权，并独立校验对象链；来源真实性来自对该受控采集角色的显式信任，不来自 Git Hash 或 Agent 自报。配对 / 本地登录本身不授予该角色。平台也可使用直接读取可信 origin、可信 SCM 集成的固定 commit 证明或已有可信 commit 约束完成独立核验，无需为本地路径另复制 Git 凭据到服务器。没有可验证的可信来源路径时失败关闭；manifest 自述 origin、Agent 输出或单独包 SHA-256 不能代替核验。

上传仅包含固定 tree 所需对象和内容，不上传未提交 / 未跟踪文件、整个 `.git` 目录、credential 配置或其他无关文件。包不得混入 `.env` / 密钥等敏感内容；若敏感内容本身已被 tracked，应拒收并显式处理，不能悄悄删除后仍冒称原 commit / tree。接收器先在隔离 staging 区限制包大小、对象 / 文件数量与展开上限，拒绝路径逃逸、绝对路径、重复 / 冲突路径和不安全文件 mode；未来若支持符号链接，必须经显式策略验证且不得跟随到受控根之外；首版 Runner 不支持 symlink，故接收端明确拒绝全部 symlink。首版无压缩 JSON 包按 TMP §22.3 强制单对象 24 MiB、所有对象原始 payload 合计 32 MiB、完整包 48 MiB 上限。校验并重新核对授权后才发布可被使用的受控 immutable source identity，冻结接收回执；随后 bootstrap 以 append-only `SourceTransferSnapshot` 关联新建 / 复用的 Snapshot，不更新已 ACCEPTED transfer 或旧 Snapshot。上传凭证只允许限定 Project / 请求 / 内容和时限，不授予任意路径写权或数据库权限。

SourceBundleTransfer 及接收回执属于 §23.9 的 Operational 来源记录，不新增 Canonical 链节点、不改变既有 Source fingerprint / Gate hash。后续 Runner 必须独立复核固定 commit / tree、所需源码内容及内容地址 / SHA-256；平台接受上传和 Agent 在本地运行测试均不构成正式 Evidence。测试代码仍经 Proposal → Verifier → 内容寻址 TestImplementation Artifact，不从本地 workspace 的任意文件自动进入正式执行。

---

## 10. PolicySnapshot

BUGate Policy 在 TestRun 开始时固定：

```text
id
project_id
policy_name
policy_version
content_sha256
artifact_uri
compiled_policy JSONB
created_at
```

PolicySnapshot 创建后不可变。

同一迁移为 PolicySnapshot 安装完整行的 UPDATE / DELETE 保护。创建入口验证 compiled Policy 的受支持规则，并核对 `content_sha256` 与规范化 `compiled_policy` JSON 的 SHA-256；不接受由调用者任意指定且与内容不符的摘要。未知规则或无效维度在创建 Run / PolicySnapshot 时拒绝，避免运行到 Gate 才暴露配置错误。

---

## 11. Legacy TestRun

TestRun 表示针对一个 SourceSnapshot，在某套 Policy 下的一次自治测试活动。

**v0.4 目标：** TestRun 就是用户可见的“测试任务 / 测试轮次”，不另建与其重复的 Task Canonical 实体。ADR-017 的 NativeTestRun 是另一显式 profile 的持久化，不是旧任务双写副本，按 §49 的隔离身份与未来显式迁移边界处理。典型任务针对某个 feat / MR 的一个明确完整 Commit SHA；MR / branch 名称只作来源和展示引用，push 后的新 SHA 创建新 Run。若需要区分 MR head 与 merge-result commit，必须先选定并固定实际被测 SHA，不能运行中随分支变化而漂移。

SHA 不是完整测试身份。PRD、configuration、固定环境属于 SourceSnapshot；PolicySnapshot 由 Run 单独固定。相同 SHA 改 PRD / configuration / 环境须新建 Snapshot；改 Policy 或用户明确发起另一轮测试须新建 Run，完全相同的 Snapshot / Policy 可以被新轮次复用。禁止新增 `UNIQUE(project_id, commit_sha)` 或其他阻止同 SHA 重测的唯一约束。重复提交同一请求使用原幂等键返回原 Run；显式新轮次使用新请求身份并保留既有 Run、Verdict 与历史。Job retry、Mission retry 和 Execution retry 仍是原 Run 内追加运行历史，不等于偷偷创建另一轮测试。

每个 v0.4 受控 Run 在首次 Provider 调用前建立且只建立一次 §23.4 的逻辑 TaskWorker / 主 AgentSession 绑定。ADR-015 目标同时冻结 §23.9 的模式与节点 Placement。进程尚未启动、WAITING_INPUT 或恢复中可以没有活跃 PID / lease，但不能另建第二个绑定或把 Run 分给无关 Worker。不同 Run，包括同一 Project 下不同 feat / MR，可以通过各自绑定并发执行；独占约束不是 Project 级锁。

Web bootstrap 的幂等键按 Project 绑定规范化测试输入：repository 去首尾空白、commit 转小写，PRD/configuration 保持原始字节，Policy 按完整生效规则比较（包括 Gate 与 Coverage，默认值和无语义顺序不影响等价性）。同键同测试输入返回原 Run；同键不同测试输入在写入 Artifact 或 Canonical 行之前返回冲突，保留既有 Run、Snapshot 与历史。SourceSnapshot Fingerprint 仍遵循第 9 节：branch 只是参考标签，不参与 Source 或 bootstrap 幂等身份；不同 branch 标签可以引用相同固定 commit 的共享 Snapshot，既有 Snapshot 的标签不被重写。

ADR-015 目标创建请求的幂等比较还须纳入 mode、稳定 node_id、source trust policy / version 和 source transfer 策略；同键不同选择在写入 Artifact / Snapshot / Placement 前冲突，不能悄悄返回另一节点 / 模式的 Run。Placement 是 Operational 选择，不加入 SourceSnapshot fingerprint / Gate hash；branch 保持既有参考标签语义。旧缺少 mode 等字段的请求保持原 SERVER_HOST 行为，仅按旧 schema 在内存解释，不回填或重新序列化冻结 payload，也不借缺省迁移旧 Run。此为新增目标请求契约，不表示目前 API 已实现这些字段。

```text
id
key
project_id
source_snapshot_id
policy_snapshot_id
trigger_type
trigger_ref
status
current_verdict_id nullable
started_at
completed_at
created_by
created_at
updated_at
row_version
```

状态：

```text
CREATED
ANALYZING
DESIGNING
IMPLEMENTING
EXECUTING
DIAGNOSING
VERIFYING
BLOCKED
COMPLETED
CANCELLED
```

PASS / FAIL 不属于 TestRun Status，而属于 Verdict。

---

## 12. Requirement

Requirement 表示当前 SourceSnapshot 中一个可独立验证的软件行为、约束或质量要求的 Canonical 表达。

范围以固定 SourceSnapshot 的被测应用及 PRD 明确要求的产品功能为准；应用自身的行为、质量与产品约束可以成为 Requirement（包括 CONSTRAINT）。仅用于指导测试生成、依赖 / 装载、产物位置、源文件保护或平台执行权限的指令仍须遵守，但属于 Mission / 实施约束或前置条件，不能仅因出现在 PRD 中就升为应用 Requirement，再衍生针对编排平台自身的 Risk / TestCase。若被测仓库本身明确实现 Runner / guard 等功能，且该功能在本轮请求范围内，它仍可成为正式产品需求；不能按平台名称排除。运行时范围说明不增删实体字段或改写已接受的 Canonical 历史，也不放宽 Proposal / 完成状态校验。

```text
id                     uuid PK
key                    varchar(64)
project_id             uuid FK
source_snapshot_id     uuid FK
logical_key            varchar(255)
title                  varchar(512)
description            text
requirement_type       varchar(32)
priority               varchar(16)
source_type            varchar(32)
source_ref             text
source_fingerprint     char(64)
confidence             numeric(4,3)
lifecycle_status       varchar(32)
supersedes_id          uuid FK nullable
created_by_type        varchar(32)
created_by_ref         text
created_at             timestamptz
updated_at             timestamptz
row_version            bigint
```

Requirement Type：FUNCTIONAL、NON_FUNCTIONAL、CONSTRAINT、COMPATIBILITY、PERFORMANCE、RELIABILITY、SECURITY、OPERABILITY。

Priority：P0 / P1 / P2 / P3。

Source Type：PRD、ISSUE、API_SPEC、DESIGN_DOC、GIT_DIFF、CODE、MANUAL。

`logical_key` 用于跨 Snapshot 建立逻辑连续性，例如 `transfer.daily_limit.enforcement`。

同一 Snapshot 去重：

```text
source_fingerprint = SHA256(normalized source_ref + normalized description)
UNIQUE(source_snapshot_id, source_fingerprint)
```

生命周期：

```text
ACTIVE
  ├──► SUPERSEDED
  └──► DEPRECATED
```

Requirement 不允许 COVERED、TESTED、PASSED 等状态，这些属于派生状态。

---

## 13. Risk

Risk 表示 Requirement 或实现可能无法正确满足预期行为的具体失效模式或质量风险。

```text
id
key
project_id
source_snapshot_id
risk_fingerprint
category
title
description
severity
probability
rationale
confidence
lifecycle_status
disposition
created_by_type
created_by_ref
created_at
updated_at
row_version
```

Category：FUNCTIONAL、BOUNDARY、FAILURE、CONCURRENCY、CONSISTENCY、COMPATIBILITY、SECURITY、PERFORMANCE、RELIABILITY、OBSERVABILITY、UPGRADE、DATA。

Severity：CRITICAL、HIGH、MEDIUM、LOW。

Probability：HIGH、MEDIUM、LOW、UNKNOWN。

Requirement ↔ Risk 通过 `requirement_risks` Join Table：

```text
requirement_id
risk_id
relation_type
created_at
PRIMARY KEY(requirement_id, risk_id)
```

Risk Fingerprint：

```text
SHA256(project + snapshot + category + normalized description + sorted requirement logical keys)
```

唯一：`UNIQUE(source_snapshot_id, risk_fingerprint)`。

Risk Lifecycle：

```text
OPEN
 ├──► ACCEPTED
 ├──► MITIGATED
 └──► OBSOLETE
```

Risk Coverage 不是 Lifecycle，必须动态计算。

---

## 14. TestCase

TestCase 表示明确、可执行、可验证的测试意图，描述 what to verify，而不是 how code implements it。

### v0.2 领域决策

TestCase 在 v0.2 首次进入 Canonical persistence。按本迭代的协议约定，使用 `description` 表达测试意图、`test_type` 表达类别、字符串 `expected_result` 表达可验证预期，`preconditions` 为字符串列表。它们替代 v0.1 尚未实现的 `objective`、`case_type`、`steps` 和 JSONB expected result 草案；不存在历史 TestCase 数据或列需要重命名。未来结构化步骤可通过版本化协议和 additive migration 引入。

```text
id
key
project_id
source_snapshot_id
case_fingerprint
title
description
test_type
priority
preconditions JSON (list[str])
expected_result text
lifecycle_status
confidence
derived_from_id nullable
created_by_type
created_by_ref
created_at
updated_at
row_version
```

Test Type：FUNCTIONAL、BOUNDARY、NEGATIVE、FAILURE、CONCURRENCY、CONSISTENCY、COMPATIBILITY、SECURITY、PERFORMANCE、RELIABILITY、UPGRADE、DATA、RECOVERY。

TestCase ↔ Risk 使用 `risk_test_cases` Join Table，对应 `RiskTestCase`：

```text
risk_id          uuid FK risks(id) ON DELETE RESTRICT
test_case_id     uuid FK test_cases(id) ON DELETE RESTRICT
created_at       timestamptz
PRIMARY KEY(risk_id, test_case_id)
```

v0.2 Requirement → TestCase 追溯通过 `requirement_risks` → `risk_test_cases` 派生，不重复保存关系 JSON 数组。直接 `test_case_requirements` 关联作为后续扩展保留；v0.1 计划名称 `test_case_risks` 被首次实现名称 `risk_test_cases` 取代。

Fingerprint：

```text
SHA256(stable JSON {
  source_snapshot_id,
  normalized description,
  test_type,
  normalized preconditions (preserving order),
  normalized expected_result,
  sorted unique linked canonical risk_fingerprints
})
```

归一化折叠文本中的空白，不改变大小写；JSON 使用排序字段和固定分隔符。title、priority、confidence 不参与意图身份，因此仅修改展示标题或优先级不会创建重复用例。Risk 引用在计算前解析为当前 Project / Snapshot 下非 OBSOLETE 的 Canonical Risk。Fingerprint 是确定性精确意图去重，不宣称跨快照或语义相似去重。

唯一：`UNIQUE(source_snapshot_id, case_fingerprint)`。

同时要求 `UNIQUE(project_id, key)`、`confidence IS NULL OR confidence BETWEEN 0 AND 1`、全部 FK 以及类别 / 优先级 / 生命周期 CHECK constraints。

生命周期：DRAFT → ACTIVE → SUPERSEDED / DEPRECATED。当前 Verifier 接受 CREATE Proposal 后创建 ACTIVE 用例，DRAFT 和后续生命周期变更预留给受控服务；Agent 不设置 Canonical Lifecycle。

PASS、FAIL、AUTOMATED、NOT_AUTOMATED 都不是 TestCase Lifecycle。Automation Status 从 TestImplementation 派生。

### DESIGN_TESTS Canonical Commit

Agent 仅提交 `TEST_CASE` / `CREATE` Proposal。Verifier 校验 schema、非空测试意图、Risk 引用存在性、Project / SourceSnapshot 一致性、非 OBSOLETE Risk、Proposal idempotency 以及规划 Mission 的覆盖进展约束，然后计算 fingerprint。重复 fingerprint 关联已有 Canonical TestCase；不重复创建用例或 `test_case.accepted` 事件。

新用例、全部 `RiskTestCase` link、Proposal ACCEPTED、AuditEvent、OutboxEvent 和 Mission / Attempt 成功状态在同一事务中落库。`created_by_ref` 指向 MissionAttempt；Proposal 的 `accepted_entity_id` 与 mission_id / attempt_id 保留创建来源。任一无效 Proposal 拒绝整个 batch，不产生部分 Canonical Commit。

---

## 15. Legacy TestImplementation

TestImplementation 表示 TestCase 在具体测试框架中的可执行实现。

```text
id
key
project_id
source_snapshot_id
repository_url
commit_sha
file_path
symbol
framework
language
implementation_fingerprint
artifact_uri nullable
source_sha256 nullable
validation_status
created_by_type
created_by_ref
created_at
updated_at
row_version
```

TestImplementation ↔ TestCase 使用 `implementation_test_cases` Join Table，因为一个测试函数可以覆盖多个 Case，一个 Case 也可拥有多个 Implementation。

Fingerprint：

```text
SHA256(stable JSON {repository_url, commit_sha, file_path, symbol, source_sha256 when generated})
```

唯一：`UNIQUE(source_snapshot_id, implementation_fingerprint)`。

旧 Python / pytest Runner profile 接受 `TEST_IMPLEMENTATION` / CREATE Proposal：`test_case_keys`、repository_url、commit_sha、file_path、symbol、framework、language，以及可选 `code`。所有 Case 必须 ACTIVE 且属于同一 Project / SourceSnapshot，repository / commit 必须匹配不可变 Snapshot。HyperTest 验证 Python 语法；Agent 不能自称实现已经通过正式测试。

生成的 `code` 保存为内容寻址 Artifact，`artifact_uri` 和 `source_sha256` 固定其内容；仅允许安全的 `tests/**/*.py` 路径。应用 Commit 不因生成测试而改变。Runner 在临时副本中覆盖未跟踪的安全测试路径，禁止覆盖 Snapshot 中已跟踪文件。没有 code 的 Proposal 可引用 Snapshot 中已有的受控测试位置。

Validation Status：PENDING、VALIDATED、REJECTED、STALE。Verifier 接受后创建 PENDING，只有 Runner 在源内容和可执行目标校验后标记 VALIDATED。生成 Artifact 的 checksum 参与 fingerprint，便于追加新测试版本而不覆盖旧实现。执行前后重新校验源码 Hash 与 Snapshot，验证失败不能成为成功事实。

新实现、ImplementationTestCase links、Proposal acceptance、AuditEvent、OutboxEvent 在同一事务提交。关系数组仅属于 Proposal 输入，不是 Canonical persistence。

---

## 16. Legacy TestExecution

旧 TestExecution 表示一次由 HyperTest Runner 控制、具有明确输入和环境边界的测试执行。新 NativeExecutionRecord 是 §49 的执行观察，不需要平台 Runner，也不得写入这张旧表冒充 OFFICIAL。

```text
id
key
test_run_id
mission_id nullable
durable_job_id nullable
execution_request_id nullable
retry_of_execution_id nullable
idempotency_key
purpose
runner_backend
environment_id
environment_fingerprint
source_commit
execution_spec_sha256
spec JSON
status
outcome
queued_at
started_at
finished_at
exit_code nullable
error_code nullable
error_message nullable
runner_instance
created_at
row_version
```

Purpose：EXPLORATORY、VALIDATION、OFFICIAL、REPRODUCTION。只有 OFFICIAL 默认参与 Quality Gate。

Status 与 Outcome 必须分离：

```text
Status:
QUEUED
PROVISIONING
RUNNING
COLLECTING
COMPLETED
ERROR
TIMED_OUT
CANCELLED

Outcome:
PASS
FAIL
BLOCKED
INCONCLUSIVE
UNKNOWN
```

Execution 进入 Terminal State 后，Execution Spec 不可修改；重跑必须创建新 Execution。

Execution ↔ TestCase 使用 `execution_test_cases`：

```text
execution_id
test_case_id
implementation_id nullable
result
duration_ms nullable
failure_summary nullable
```

Per-case Result：PASS、FAIL、SKIPPED、BLOCKED、ERROR、NOT_RUN。

Execution Idempotency：`UNIQUE(test_run_id, idempotency_key)`。

`spec` 固定 SourceSnapshot、精确 Commit、Runner 环境/镜像身份、purpose、timeout、Case / Implementation 目标、源码摘要和关系。PostgreSQL Trigger 禁止创建后修改这些输入；状态、Outcome、运行时间、错误、exit code 和 row_version 可按执行进度更新。重试使用新 Execution 和 request key，重复 request key 返回原 Execution 而不重复执行。

客户端只选择 workspace、backend、purpose、timeout 和 idempotency key；Runner 从 Canonical 实现生成命令，客户端和 Agent 不提交正式结果或任意 Shell 命令。

**v0.4 目标：** 持久 Harness 通过有界 typed domain tool 申请正式 Execution；受控 Runner 仍独立固定目标、执行和采集 Evidence。RunExecutionBinding 及当前 Job 的所有权验证约束请求 / 提交，不把 Harness Bridge 或 Agent 自行运行的命令变为可信 Runner。Execution 的既有 idempotency、不可变输入和 `durable_job_id` 归属不因主会话持续存在而改变。

---

## 17. Legacy Evidence

此旧 Evidence 表表示由受信任执行或采集链产生、用于支持测试事实或 Finding 的不可变证据。§49 NativeMaterial 独立保存未验证材料，不伪造这里的执行 FK、trust level 或 VERIFIED 状态；未来外部原生可信来源接入须显式版本化。

```text
id
key
test_run_id
execution_id nullable
evidence_type
trust_level
artifact_uri nullable
content_type nullable
sha256
size_bytes nullable
inline_summary nullable
collector
source
status
created_at
verified_at nullable
rejection_reason nullable
```

Evidence Type：EXECUTION_METADATA、STDOUT、STDERR、JUNIT、HTTP_REQUEST、HTTP_RESPONSE、LOG、METRIC、TRACE、SCREENSHOT、DATABASE_STATE、FILE_ARTIFACT、GIT_DIFF、ENVIRONMENT_FINGERPRINT、CUSTOM。

Trust Level：RUNNER、SYSTEM、EXTERNAL_VERIFIED、AGENT_REPORTED、USER_PROVIDED。

默认只有 RUNNER、SYSTEM、EXTERNAL_VERIFIED 可进入正式 Release Evidence。

Evidence State：COLLECTED → VERIFIED / REJECTED；VERIFIED 可被 SUPERSEDED，但 Artifact 本身永远不修改。

Evidence Content Immutable。允许更新 status、verified_at、rejection_reason；禁止更新 artifact_uri、sha256、source、execution_id、content。

唯一：`UNIQUE(test_run_id, sha256, evidence_type)`。

同一 TestRun 中相同类型/内容的 Evidence 可被多次 Execution 复用，使用 `execution_evidence` Join Table 对应 `ExecutionEvidence`：`PRIMARY KEY(execution_id, evidence_id)`。Evidence 的 `execution_id` 保留最初采集来源，不能据此排除其他合法复用关系；Gate 与 Execution 视图应使用 Join Table 查询。

MVP 内容保存在本地只写入一次的 SHA-256 Artifact Store，URI 为 `sha256:{digest}`。读取、复用和 Gate 评估都校验 hash，读取时也校验 size；缺失、篡改或越界 Artifact 不作为可信事实。PostgreSQL Trigger 只允许更新 status、verified_at、rejection_reason，禁止改变其余内容/来源字段。

---

## 18. Finding

Finding 表示 HyperTest 根据测试结果和 Evidence 发现的需要跟踪、解释或处理的问题。Finding 不等于 Bug。

```text
id
key
project_id
test_run_id
fingerprint
classification
severity
title
description
root_cause
confidence
status
resolution
external_issue_ref nullable
reported_by_type
reported_by_ref
confirmed_by nullable
created_at
updated_at
resolved_at nullable
row_version
```

Classification：PRODUCT_DEFECT、TEST_DEFECT、ENVIRONMENT_FAILURE、INFRA_FAILURE、FLAKY、DATA_ISSUE、EXPECTED_BEHAVIOR、REQUIREMENT_ISSUE、UNKNOWN。

Severity：BLOCKER、CRITICAL、MAJOR、MINOR、INFO。

Finding ↔ Evidence 使用 `finding_evidence`，relation_type：SUPPORTS、CONTRADICTS、CONTEXT。

另外建立 `finding_test_cases`、`finding_requirements`、`finding_risks`。

Fingerprint 用于 Failure Deduplication：

```text
SHA256(project + classification + normalized failure signature + affected component)
```

当前 MVP 的 affected component 为 TestRun ID + 排序的 test_case_keys，因此去重保留同一 Run / Snapshot 的证据边界。跨 Run recurrence / lineage 属于后续知识能力，不把不同快照的 Finding 行合并。severity、title、confidence 不改变失效身份。

活动 Finding 使用 Partial Unique Index，确保同一 fingerprint 同时只有一个 NEW / TRIAGED / CONFIRMED / REOPENED 实例。

Finding Lifecycle：

```text
NEW
 │
 ▼
TRIAGED
 │
 ├──► INVALID
 ▼
CONFIRMED
 │
 ▼
RESOLVED
 │
 ▼
CLOSED

RESOLVED / CLOSED → REOPENED
```

Resolution：FIXED、DUPLICATE、WONT_FIX、RISK_ACCEPTED、NOT_REPRODUCIBLE、ENVIRONMENT_FIXED、TEST_FIXED。

Web 人工处置必须携带预期 row_version 和非空 reason；既有 API 的可选预期版本语义保持兼容。处置按当前状态机提交 before/after、操作者、时间及配对 Audit/Outbox；会话 CLOSED 不使这些人工治理失效。处置不自动产生 Verdict，也不能修改原执行与可信证据。Web 可读取同 Finding/Run 的有限生命周期审计投影（状态、resolution、row_version、reason），不透传任意审计 metadata；截断的近期列表必须明确说明，不能冒称完整历史。

### 18.1 v0.4 受控 GitLab Issue 集成（服务器兼容保留，本地真实创建已独立核验）

`external_issue_ref` 本身只是可选关联字段，不能单独证明 GitLab 创建 Issue 或指派成功。本分支已实现受控集成，Agent 可提交 typed Issue Request，引用同一授权范围内已接受 Finding、固定 Run / SourceSnapshot、已校验 Evidence 及负责人建议。HyperTest 按项目预配置的 integration、操作授权与负责人映射验证请求，不能把 Agent 给出的任意项目、用户或 URL 当作已批准目标。

外部创建 / 指派属于受控集成副作用，不是 Agent 直接写 Finding 或持有 GitLab token。平台持久保存请求身份、Finding 关联、目标、映射依据和 correlation / idempotency key；同一逻辑请求不能因重试重复提单，Issue 去重也不能合并或改写不同 Run 的 Canonical Finding。需要人工决策时使用持久输入流程并恢复同一主会话。

ADR-015 目标保留现有 `request_gitlab_issue` 语义。平台先持久化与校验同 Run 的 Finding / Evidence、获准项目、负责人和清理后的 draft，再委托 SERVER_HOST 的受控平台集成或 LOCAL_CONNECTOR 的受控 issue adapter 执行。后者复用本地 CLI / credential helper / MCP 实际可访问的授权；凭据仅供隔离的集成 adapter 使用，不交给 Agent、平台数据库或日志。浏览器已登录不等于 adapter 已获 API 权限；设备配对和项目提单授权分别治理、分别撤销。一般问题单平台可遵循同一边界，但本 ADR 不将其他 Provider 冒称为已实现。

只有校验目标 GitLab 响应或回查确认 Issue 的真实身份后，才登记 `external_issue_ref` 和派单结果。超时或连接中断后不能确定是否已创建时，明确记录“结果未知”，先按 correlation 查询 / 人工核实，不盲目再次创建。请求失败、Issue 已创建或负责人已指派均不等于产品缺陷已确认、修复或 Gate 已放行。该 Operational 记录由本分支 `0014_harness_operations` 实现，约束见 §23.7；注入 HTTP transport 回归不等于真实 GitLab 提单验收。

ADR-015 目标另以 §23.9 的固定 executor 记录扩展现有操作；operation_id / correlation、Finding 与目标不随传输、epoch 或后端改变。本地 adapter 必须先将固定 operation_id、输入摘要和 dispatch intent 写入受保护持久账本，再发送外部创建，随后保存调用结果 / 不确定状态；同 operation_id 同输入返回原状态，异输入冲突。发出请求后失联、重启、ACK 丢失或本地账本丢失时，必须按原 operation_id 查询对账；不能证明未发送时保持 UNKNOWN，不能再次 POST，也不能切换服务器 / 本地、换节点或换幂等键绕过同一 Finding 的既有去重。平台必须通过获准受控 adapter 的认证远端响应 / 查询核验真实 project、IID、URL、Finding correlation 与负责人结果，不能仅采信 Agent 自报 Issue 链接；来源不足则保持 UNKNOWN，不能先写 SUCCEEDED 再补核验。

---

## 19. Verdict

Verdict 表示 HyperTest 根据 Policy、Canonical State 和 Evidence 对某个质量范围做出的正式判断。Verdict 是 Decision，不是 Observation。

```text
id
key
test_run_id
scope
scope_ref nullable
sequence_no
decision
status
reason
policy_snapshot_id
state_snapshot_hash
evidence_manifest_sha256
issued_by_type
issued_by_ref
created_at
finalized_at nullable
revoked_at nullable
```

Scope：TEST_RUN、REQUIREMENT、RISK、RELEASE。

Decision：PASS、FAIL、BLOCKED、INCONCLUSIVE、RETEST_REQUIRED、RISK_ACCEPTED、RELEASE_READY、RELEASE_BLOCKED。

Status：DRAFT、FINAL、REVOKED。

FINAL Verdict Append-only：禁止原地 UPDATE；质量状态变化时创建新 Verdict，旧 Verdict 保留历史或 REVOKED。

建立 `verdict_evidence` 和 `verdict_findings` 用于直接 Traceability。

每个 FINAL Verdict 必须保存 `state_snapshot_hash`，证明 Verdict 基于哪一个 Canonical Testing State 得出。

MVP 对 `(test_run_id, sequence_no)` 建立唯一约束，sequence_no > 0；FINAL 必须同时有 state_snapshot_hash、evidence_manifest_sha256、finalized_at。`TestRun.current_verdict_id` 指向最近 FINAL 决策。重复评估仅在 Run / Scope 最新的相应状态 Verdict 与本次 Policy / State Hash / status / decision / Evidence Manifest 均匹配时复用；变化创建新 sequence。状态返回曾出现的旧语义也不得倒指较早 FINAL，`current_verdict_id` 必须保持最近正式结论，不能从全部历史中选择旧匹配项。

数据库 Trigger 禁止改变 FINAL 内容，只允许 FINAL → REVOKED 并设置 revoked_at，其他字段必须不变；REVOKED 同样不可重写，FINAL / REVOKED 禁止 DELETE。VerdictEvidence / VerdictFinding 保存决策引用，Canonical 内容、links、审计和 Outbox 事务性提交。

当前 `canonical-gate/v1` 要求：非空 Requirement / Risk / ACTIVE Case、Risk identification 与设计维度覆盖完整、每个 Case 最新 OFFICIAL 执行匹配 SourceSnapshot Commit、COMPLETED + aggregate PASS + exit code 0 + per-case PASS、通过 ExecutionEvidence 关联的 VERIFIED trusted EXECUTION_METADATA / JUNIT，且 Artifact hash 验证成功。最新按 queued_at、ID 倒序选择，不回退挑选更早的成功结果。

缺失/未完成/不确定事实产生 BLOCKED；执行失败或 policy-blocking confirmed PRODUCT_DEFECT 产生 RELEASE_BLOCKED；全部满足产生 RELEASE_READY。默认阻断严重程度为 BLOCKER、CRITICAL；`compiled_policy.gate.blocking_finding_severities` 可配置，但 BLOCKER 不可豁免。当前基线不提供 Official Evidence waiver。设计覆盖完成本身不形成放行结论。

v0.4 持久 Harness 的报告、会话结束、TaskWorker / Binding 状态和 GitLab 派单状态都不是 Verdict。报告只引用已接受 Canonical State、可信 Evidence 和正式 Gate 结果；即使 Agent 报告“测试完成”，也不能跳过当前固定 Policy 的 deterministic Gate。RunExecutionBinding、Provider 会话内容、进程身份和 binding_epoch 不进入 Gate 的 Canonical State Hash。

---

## 20. Legacy Mission

Mission 表示 HyperTest 为推动当前 TestRun 状态演进而创建的不可变 Testing Work Unit。Mission 不等于 Agent Session，也不等于 Agent Turn。

```text
id
key
test_run_id
mission_type
priority
objective
protocol_version
spec JSONB
spec_sha256
status
idempotency_key
created_by
created_at
ready_at nullable
dispatched_at nullable
completed_at nullable
cancelled_at nullable
current_attempt_no
row_version
```

Mission `spec`：

```json
{
  "targets": {},
  "context": {},
  "constraints": {},
  "acceptance_criteria": {},
  "output_contract": {},
  "execution_profile": {}
}
```

Mission 进入 READY 后 spec、spec_sha256、mission_type、objective 不可修改。目标变化必须 cancel + create new mission。

数据库保护范围包括 id、key、test_run_id、mission_type、priority、objective、protocol_version、spec、spec_sha256、idempotency_key、created_by、created_at。CREATED 可编辑草稿；一旦离开 CREATED，后续 RUNNING / RETRYING / COMPLETED / CANCELLED 等状态均不能改变契约、删除历史或退回 CREATED 来解冻。状态、current_attempt_no、生命周期时间戳与 row_version 仍可由所属服务更新。

Mission Type：ANALYZE_REQUIREMENTS、ANALYZE_IMPACT、ANALYZE_RISKS、DESIGN_TESTS、REVIEW_TESTS、IMPLEMENT_TESTS、REVIEW_IMPLEMENTATION、DIAGNOSE_FAILURE、INVESTIGATE_FINDING、REPAIR_TEST、RETEST_ANALYSIS、VERIFY_COVERAGE。

Mission State Machine：

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

Mission 唯一：`UNIQUE(test_run_id, idempotency_key)`。

Cancelled / expired Mission 不被重新打开或改写。用户明确再次规划仍缺失的工作时，Planner 为原 intent 分配新的 `:generation:N` idempotency key 并创建新 Mission；原 specification、Attempt、Proposal 与取消历史保留。

**v0.4 目标：** Mission 继续作为 typed、不可变、可验收的测试阶段边界，但多个串行 Mission 可以使用同一 Run 的持久主 AgentSession。持久 Harness 自驱需求分析、风险分析、设计、实现、申请正式执行、诊断和报告；Planner 对其阶段请求执行确定性的依赖、范围、覆盖缺口和预算准入，不接管每个 reasoning turn，也不因阶段转换重新创建 Provider 会话。一个 Run 同时只有一条主 Harness 执行线，不把多个阶段派给不同逻辑 TaskWorker 并行执行。

Mission COMPLETED 仅表示该 Mission 的 required outputs 已被接受，不关闭主 Session / RunExecutionBinding，不重置整个 Run 的上下文。阶段失败、人工等待、正式 Runner 执行和 Run 最终结束分别保留自己的状态；Mission 与 Agent turn、CLI 进程、用户可见 TestRun 仍不能混用。

---

## 21. Legacy MissionAttempt

Mission Retry 不修改原 Mission，而是创建新的 MissionAttempt。

```text
id
mission_id
attempt_no
durable_job_id nullable
agent_session_id
provider
harness
provider_run_ref
status
started_at
submitted_at
finished_at
error_code
error_message
result_payload JSONB
provider_metadata JSONB
```

唯一：`UNIQUE(mission_id, attempt_no)`。

Attempt Status：CREATED、RUNNING、SUBMITTED、ACCEPTED、REJECTED、FAILED、CANCELLED。

Mission 描述业务工作状态；MissionAttempt 描述某一次 Agent 执行，两者禁止混用。

v0.3 已实现基线为每个新 Mission 执行 / retry 创建新的 AgentSession；只有原 WAITING_INPUT 的恢复复用原 Attempt / Session。v0.4 目标改为同一 Run 的串行 Mission / 新 Attempt 引用同一个 §23.4 `primary_agent_session_id`。Attempt 仍按 Mission 追加编号，原结果、Proposal、Job 归属及时间历史不可覆盖；Attempt 被拒绝 / 失败不自动表示整个持久 Session 失效。若主 Session 仍可验证恢复，显式 Mission retry 可以在原绑定 / 主会话下新建 Attempt；若原生 Session 或受控 workspace 已丢失，任务明确失败，必须显式新建 TestRun 才能开启替代主会话。禁止沿用旧 Attempt 并冒充同一会话恢复。

---

## 22. Legacy MissionProposal

所有 Agent Domain 写操作进入 `mission_proposals`：

```text
id
mission_id
attempt_id
proposal_type
operation
idempotency_key
object_payload JSONB
rationale
confidence
status
validation_errors JSONB
accepted_entity_type nullable
accepted_entity_id nullable
created_at
reviewed_at nullable
```

Status：SUBMITTED、VALIDATING、ACCEPTED、REJECTED、SUPERSEDED。

唯一：`UNIQUE(mission_id, idempotency_key)`。

Proposal → Canonical Commit 必须在一个数据库事务中完成：Validate Proposal → INSERT / UPDATE Canonical Entity → Proposal ACCEPTED → Audit Event → Outbox Event；任一步失败则 ROLLBACK。

---

## 23. Legacy AgentSession

```text
id
test_run_id
provider
harness
provider_session_id
workspace_id
status
created_at
last_active_at
closed_at
```

唯一：`UNIQUE(provider, provider_session_id)`。

AgentSession 属于 Operational State，不是 Canonical Test Fact，不能直接决定 Coverage、Finding、Verdict。

**v0.3 已实现：** 普通 Mission 执行创建一条 AgentSession，Mission 返回终态后关闭该 Session 并清理其托管副本。持久 WAITING_INPUT 是当前复用同一 Session 的例外；本文记录现状，不把它解释为已经实现 Run 级长会话。

**v0.4 目标：** 一个 RunExecutionBinding 固定一个主 AgentSession，跨该 Run 的串行 Mission / Attempt 复用，正常阶段完成不关闭。AgentSession 一对多 Attempt 不是多条同时运行的 Agent 执行线。只有 Run 受控结束、取消或主会话不可恢复时，才终结该主 Session 并按审计范围清理工作副本；单个 Mission 拒绝 / retry 或运行 Job 的终态不能直接套用 v0.3 的逐阶段 close / fail 行为。

以上创建 / 关闭 Provider 和托管副本的进程语义适用于 PLATFORM_MANAGED。ADR-016 的 INTERACTIVE_MCP 由可信宿主证明并登记当前已存在的真实 native Session；平台只管理其本 Run 测试关联、执行授权和受控 workspace。其 AgentSession / Binding CLOSED 终结该测试关联，不声明用户整个聊天或原生进程已关闭，也不允许删除用户无关工作；原会话身份唯一性、历史与终态仍保持不变，详见 §23.10。

持久会话是外部原生 thread / session 与受控工作副本的持续身份，不要求同一个 CLI PID 永久常驻。原生 `provider_session_id` 初次由 Provider 真实返回后固定；恢复必须引用该身份，同一主 Session 不能变更 Provider、覆盖已有原生引用或用新原生会话冒充恢复。原生认证 / 会话运行时保存在绑定的 Harness 节点；ADR-013 为服务器宿主，ADR-015 还可为用户本地节点。平台 Canonical 数据库状态及数据库 / 问题单集成凭证不进入 Vendor Session；受控集成可在所选节点复用授权，但其凭据与 Agent 隔离。

### 23.1 DurableJob 与 WorkerHeartbeat

DurableJob 表示用户提交的平台工作请求，属于 Operational State，不是用户可见测试任务 TestRun 或 Canonical Testing Semantic Chain 的新事实节点。v0.3 中它调度现有 Planner、Mission Runtime、Runner 与 Gate；v0.4 中它仍承担持久请求 / 租约 / 取消，但必须在原 RunExecutionBinding 下调用持久 Harness 和所属领域服务，不变成另一个自研通用 Agent Loop。

`durable_jobs` 使用 UUIDv7 主键，project_id / test_run_id 为关系 FK；EXECUTE_MISSION 必须具有同一 Run 的 mission_id，其他类型禁止该引用。retry_of_job_id 关联显式重试的历史请求。支持 ADVANCE_RUN、EXECUTE_MISSION、EXECUTE_TESTS、EVALUATE_GATE、PREPARE_WORKSPACE。

ADVANCE_RUN 在 Git / Agent 前对受支持 backend 调用 Runner fingerprint 进行只读就绪预检。先验证 operation ownership 并提交释放 Run / Job 行锁，预检后以有效 lease / admission 再进入调度；Docker daemon / 可信镜像不可用或 local 未显式启用时，不启动 Git / Agent、不创建 Execution / Evidence、不自动安装或拉取镜像。预检只属于 Operational Readiness，不构成正式执行事实或环境预约；独立 EVALUATE_GATE 不依赖此预检。

ADR-013 已实现的 ADVANCE_RUN 请求必须恰选一种源方式：`prepare_workspace: true` 且不传 workspace，或提供非空 workspace 且 `prepare_workspace: false`（缺省）。自动方式在同一 Job 内调用既有 pinned checkout 服务，再继续 Planner 周期；保留原 GitHub HTTPS 白名单、固定 commit 与干净 tracked source 校验，其他 Host 仍使用已有 workspace。准备不占 max_steps，不新增 Job / Mission 类型，也不在成功并重新验证归属前创建 AgentSession / MissionAttempt。后续 Attempt / Execution 继续归属同一 Job。ADR-015 的本地传输采用 §9.1 / §23.9 的显式新请求 schema 与受控内容引用，不能把用户电脑路径当成此既有服务器 workspace 字段，也不原地重写旧 payload。

请求 identity、类型、FK、payload、idempotency_key 与 created_at 创建后不可变。payload 只保存工作区、Runner、timeout、work limit 等运行选项；Requirement / Risk / Case 等 Canonical 状态继续保存在对应关系表。`UNIQUE(test_run_id, idempotency_key)` 保证相同输入重复提交返回原 Job，不同输入复用同一 Key 被拒绝；部分唯一索引保证每个 Run 至多有一个 QUEUED / RUNNING / WAITING_INPUT / CANCEL_REQUESTED Job。

新增缺省字段允许仅在内存中按当前请求 Schema 规范化后比较输入。例如既有手动 ADVANCE_RUN payload 缺少 `prepare_workspace` 与显式 `false` 等价；相同 key 重发与显式 retry 均不得为了适配新 Schema 改写原 payload。实际 workspace / Runner / limit 或模式等实质差异仍属于冲突，不放宽既有唯一约束。

```text
QUEUED → RUNNING → SUCCEEDED / FAILED / INTERRUPTED
QUEUED → CANCELLED
RUNNING → CANCEL_REQUESTED → CANCELLED
RUNNING → WAITING_INPUT → QUEUED → RUNNING
WAITING_INPUT → CANCELLED
```

SUCCEEDED 表示调度请求成功返回，不表示质量结论为 PASS；应读取 Job result 的 stop reason 和正式 Verdict。终态 Job 不可改写，所有 Job 禁止 DELETE。显式重试创建新的 Job 并记录 retry_of_job_id，不能原地清空错误、重开终态或覆盖历史结果。

受控 `MISSION_REJECTED` / `MISSION_FAILED` 使 Job 进入 FAILED，允许同时保存 result 中的 stop reason、已持久步骤、关联 Mission ID 与已解析 workspace；独立 EXECUTE_MISSION 拒绝还保存对应 Attempt ID。FAILED Mission 不得误报为运行中或隐式重放。result 是对既有持久历史的运行索引，不能成为 Requirement / Execution / Evidence / Verdict 的替代事实。通用异常不保证存在部分 result；恢复阶段若已有暂停时提交的 checkpoint，则保留其已完成 steps、workspace 和 input reference，并记录停止原因。CANCELLED / INTERRUPTED 不保存迟到 handler 的结果，但不丢弃此前已经持久化的 checkpoint。终态 result 与原失败历史仍受不可变保护。

源码准备失败使用受控 `SOURCE_PREPARATION_FAILED`，可在同一 FAILED Job 的 result 保存 `source_preparation_diagnostic`，版本为 `hypertest.source-preparation-diagnostic/v1`。只允许固定阶段/分类、平台说明与操作建议、是否可重试、nullable 有界退出码、超时和输出截断标记；四个 Git 准备命令（init、remote add、fetch、checkout）及准备路径中的四个校验命令每流最多采集16KiB，后者不读取未使用的来源文件列表。仅用受限 stderr 在内存分类，不保存或回显原文、命令、URL、路径、认证信息或 Provider 内容。Git 校验进程失败按观察到的超时/认证/存储等类别处理，只有成功读取后证明的内容不匹配才归为 checkout_integrity；路径解析中的循环链接安全报告为存储问题。其他 Runner/Agent 调用保留默认 checkout 校验与来源文件列表每流8MiB上限，不进入诊断对象。分类是观察到的错误线索，不证明仓库存在性、认证状态或最终根因。API 对此对象按版本和枚举重新投影固定文字，未知/无效对象不展示，不修改历史行；旧失败未记录诊断时明确表示原因未知，不能追认 PR #10 的底层原因。

此诊断属于 Operational State，不创建 Finding、Execution、Evidence 或 Verdict，不加入 Gate hash，不改变 Snapshot、Job 类型或 TMP Agent wire/profile。准备在绑定/主会话建立前失败时保留无绑定状态，操作者修复外部 Git/网络/存储条件后通过原 Job 的显式 retry 创建新 Job，保留相同输入和 `retry_of_job_id`。修改仓库或 SHA 必须在新轮次审阅输入，不能改写原 Snapshot；已有绑定仍按原恢复/终态准入。取消、租约过期或旧 claim 的迟到诊断不能覆盖已提交终态。无新增迁移，旧历史不回填。

v0.3 Worker 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取 QUEUED Job，记录 worker_id、lease_token、heartbeat_at、lease_expires_at。使用数据库时钟验证租约；每个受控 Canonical commit 在 flush 前后检查 Run → Job 锁、状态和 token。租约失效或取消后的旧 Worker 不得提交 Canonical 状态。

v0.4 目标继续使用数据库队列，但领取时还必须验证 §23.4 的稳定逻辑所有者、Harness 节点亲和及 binding_epoch。`DurableJob.worker_id` / WorkerHeartbeat 标识当前实际进程，是可随显式恢复改变的运行占用记录；它们不能充当 Run 的稳定 `logical_worker_id`，也不能因 WAITING_INPUT 清空而解除 Run 绑定。未绑定的其他 Worker 即使空闲，也不得领取该 Run 的恢复工作或同时启动第二个主 Session。绑定前的首次调度可以从可用执行节点中选择，绑定后的继续执行必须回到同一逻辑所有者。

自动源准备必须在 Git 网络或文件 I/O 前提交并释放 TestRun / Job 行锁，不能把慢检出放进租约持锁事务。准备后进入领域调度前重新检查 operation ownership、Job 状态和 lease；租约过期或被取消即停止，不因已有工作区而继续启动 Agent。工作区准备与外部执行仍不具有 exactly-once 保证。

`0008_job_ownership` 为 MissionAttempt / TestExecution 增加 nullable `durable_job_id` FK 和索引。归属创建后不可修改，必须匹配同一 TestRun；ADVANCE_RUN 可以拥有其内部 Attempt / Execution，EXECUTE_MISSION 只可拥有指定 Mission 的 Attempt，EXECUTE_TESTS 只可拥有 Execution。历史 / direct API 创建的 null 归属保留，不使用 started_at 等宿主时间猜测或回填归属。取消与失联恢复只更新该 Job 关系下的执行历史。

租约过期后 Job 进入 INTERRUPTED；其未完成 Mission 的 Attempt 进入 FAILED、Mission 进入 RETRYING，未完成 Execution 进入 ERROR / INCONCLUSIVE，并保留错误和历史。取消则记录 CANCEL_REQUESTED / CANCELLED，并中断受控外部工作。恢复不会自动重放可能已发生的外部操作；用户检查后显式重试。系统不宣称外部执行 exactly-once。

v0.3 失联恢复还将所属 AgentSession 标记失败并清理其阶段副本。v0.4 中 Job / Attempt 的失败历史照常终结，但不能仅因一次进程租约过期就关闭 / 替换 Run 的主会话或删除其持久副本：绑定进入 RECOVERY_REQUIRED，由显式恢复核验原 Session / workspace、fence 旧调用后再决定能否继续。可恢复时在同一 Binding / Session 下追加新 Job / Attempt / Execution；不可恢复时使绑定 / 主 Session 明确失败并停止该 Run 的执行，新的主会话必须属于显式新 TestRun。不得改写旧 `durable_job_id`、旧结果或历史 Session 来伪造无缝续跑。

Docker 资源使用不可变 Job UUID label：包括 staging / execution containers 和预创建的 source / result volumes。恢复事务先提交领域终态，再于无数据库行锁时尽力清理精确匹配该 Job 的受控资源，记录 `job.resources_cleanup` AuditEvent / OutboxEvent、可用性与删除数量。Docker daemon 不可访问、未受控的 provider 残留进程等情况仍需 Operator 检查；清理记录不是 Execution Evidence。v0.4 必须区分 Job 所有的临时 Runner 资源与 Run 主 Session 的持久 workspace；Job 清理不能删掉仍等待输入或待恢复的主会话副本。

`worker_heartbeats` 记录 Worker 的 last_seen_at 和 active_job_id，支持 API / Web 区分队列等待与可用 Worker。其 liveness 是运行数据，不影响测试事实可信度。Job 生命周期写 AuditEvent 与 OutboxEvent；它们与队列状态在同一事务提交。

---

### 23.2 持久人工输入与原任务恢复

`MissionInputRequest` 是平台的持久交互记录，不是 Requirement、Evidence 或 Verdict。字段为 `id/key/test_run_id/mission_id/attempt_id/agent_session_id/durable_job_id/question_id/question/options/status/answer/answer_idempotency_key/created_at/answered_at/consumed_at/cancelled_at/row_version`。所有关系必须指向同一 Run、同一 Attempt 及其不可变 Job/AgentSession 归属。问题、选项和关系创建后不可修改，`(attempt_id, question_id)` 唯一；一个 Attempt 同时最多一个 PENDING/ANSWERED 问题。文本问题上限4096字符、最多8个256字符的建议选项；回答上限12000字符且不能全空白，保留原文。

问题状态为 PENDING → ANSWERED → CONSUMED；PENDING/ANSWERED 可变为 CANCELLED，历史不可删除。回答仅可写一次；同问题、同幂等key和相同原文重复提交返回原记录，异文或其他回答冲突。答案与将原 Job 重新排队在同一事务提交；不改写冻结 Mission spec、SourceSnapshot、PRD 或 Policy。澄清不能授权超出原权限的操作，实质目标变化必须新建输入快照/Run。

v0.3 已实现的持久 ADVANCE_RUN/EXECUTE_MISSION Job 支持非终态 WAITING_INPUT。等待仍占该Run的唯一活跃请求预约，但清除lease/worker并释放实际Worker，不占用进程或靠内存等待。Worker结束当前Provider turn后，在普通数据库事务中按 Run → Job → Mission → Question 锁序、有效token和数据库时钟验证，原子创建问题、Mission/AgentSession置WAITING_INPUT、保留RUNNING Attempt、保存已完成步骤、将Job置WAITING_INPUT并清lease，flush及事件完成后commit前再次验证原租约未过期；不在双重fence的运行Session内先改Job状态。回答原子将同Job WAITING_INPUT→QUEUED，新claim取得新token后恢复同Mission/Attempt/真实Provider会话；CONSUMED记录答案交付，不声称测试通过。Job attempts为领取次数，不等于Mission Attempt数，原有已完成steps和max_steps预算继续保留。

v0.4 目标保留 Mission 进行中提问的上述事务性问答与同 Attempt 恢复语义，并把原 RunExecutionBinding / logical_worker_id / 主 AgentSession / harness_host_id 作为额外所有权边界。WAITING_INPUT 只释放实际 PID、CPU 占用及当前 Job lease，不释放逻辑任务绑定，不改 binding_epoch，不把恢复请求分给无关 Worker。回答后必须在该绑定中重新取得有效 Job lease，校验同一原生会话及受控 workspace，再消费答案。阶段边界、报告或 GitLab 派单策略要求的 Run 级问题使用下述 RunInputRequest，不重新打开已完成 Mission / 已接受 Attempt；人工澄清不能代替 Scope / Snapshot / Policy 变更流程。

HyperTest句柄持久保存在Attempt operational metadata，真实Provider session ID只作外部引用，不作为领域主键；旧占位引用不推断回填。等待工作副本置于受控会话目录，供跨进程恢复；恢复从固定源码重新验证文件hash。v0.3 在阶段最终完成/取消/失效后清理副本；v0.4 在 Run 主会话终结时才清理，正常 Mission 完成或可恢复 Job 中断不能触发主副本删除。原始Agent对话不进入Canonical Testing State。丢失Provider会话或工作副本应显式失败、保留答案/Attempt，不能静默改建会话并冒称resume；v0.4 替代主会话需要显式新 Run。direct同步执行不支持可恢复人工等待，需明确报错并保留失败历史。

v0.3 取消等待Job立即成为CANCELLED，同时终止开放问题和所属未完成Mission/Attempt/Session；已回答原文保留。v0.4 取消当前 Job 仍终结其开放问题 / 未完成 Attempt 并中断对应调用，但不能偷偷释放任务绑定或创建替代主 Session；若只是取消阶段操作，继续原 Run 前须显式核验同一绑定与原 Session。取消整个 Run 则终结绑定 / 主 Session。等待不受运行租约到期扫描自动重放。取消、回答、每次等待/恢复均写配对Audit/Outbox，按Question身份去重，事件不复制问题/回答或Provider日志。新增迁移`0009_mission_inputs`仅增加交互表、状态约束与活跃索引，不回填旧历史；有交互历史时禁止降级丢失。

#### 23.2.1 v0.4 RunInputRequest（本分支已实现）

`RunInputRequest` / `run_input_requests` 是阶段之间的 Operational 问答记录，与现有 MissionInputRequest 并存，不是新 Task、Canonical Fact 或 Mission Type。当没有进行中的 MissionAttempt，或必须在已完成阶段之后决定是否报告 / 派单时，问题属于 Run 级范围；禁止为满足旧表的关系要求而伪造 RUNNING Attempt、重新打开 COMPLETED Mission 或改动 ACCEPTED Attempt。

字段与约束（本分支 `0013_run_bindings`）：

| 字段 | 目标语义 |
|---|---|
| `id` / `key` | UUIDv7 PK / 稳定 Operational Key |
| `test_run_id` | NOT NULL FK → TestRun |
| `binding_id` | NOT NULL FK → RunExecutionBinding；与 test_run_id 一致 |
| `agent_session_id` | NOT NULL FK → AgentSession；必须等于该 Binding 的 primary_agent_session_id |
| `durable_job_id` | NOT NULL FK → 当前同 Run 的 DurableJob；是该问题的不可变运行请求归属 |
| `question_id` / `question` / `options` | 稳定 question_id 为 1–128 字符；问题原文 / 选项限制沿用 MissionInputRequest |
| `context_mission_id` / `context_attempt_id` | nullable FK，若提供必须指向同 Run 的已完成阶段 / 所属 Attempt；只作上下文引用，不是可恢复或可变的所有者 |
| `status` | PENDING / ANSWERED / CONSUMED / CANCELLED |
| `answer` / `answer_idempotency_key` | nullable，回答时仅写一次；原文、长度与重复回答规则沿用 MissionInputRequest |
| `created_at` / `answered_at` / `consumed_at` / `cancelled_at` | timestamptz，未发生的转换时间为 NULL |
| `row_version` | bigint，回答 / 消费 / 取消的乐观并发版本 |

`UNIQUE(binding_id, question_id)` 固定问题身份；身份、问题 / 选项、Run / Binding / Job / Session 关系和已提供的阶段引用创建后不可修改。相同身份且相同输入的重复创建返回原记录，异文或不同范围复用该身份拒绝。FK 使用 `ON DELETE RESTRICT`；受控服务及数据库关系保护必须验证全部归属同一 Run，不能只验证 UUID 存在。可选 Attempt 引用若与 Mission 引用并存，必须属于该 Mission；这些历史行始终保持原状态。

在 Run 锁下，跨 MissionInputRequest 与 RunInputRequest 合计最多一个 PENDING / ANSWERED 问题。创建 / 消费 / 取消检查遵守 Run → Binding → Job → 对应 Question 的目标锁序；Mission 范围继续保留原 Mission / Attempt 的相对锁序。此跨表不变量由 `0013_run_bindings` 与受控写路径共同保护，不能仅给两表各加局部唯一索引后声称已满足。

Run 级暂停在当前有效执行授权下结束对应 Provider turn，核验 Binding / epoch / 原主 Session 与当前 Job token，在同一事务创建 RunInputRequest、保存 checkpoint，将原 Job / 主 AgentSession / Binding 置为 WAITING_INPUT，并清除该 Job 的 live lease / worker 占用。事务提交前再次检查数据库租约时间；不改任何已完成 Mission / Attempt，不释放逻辑绑定、原生 thread 或 workspace，不递增 epoch。

问题状态仍为 PENDING → ANSWERED → CONSUMED，PENDING / ANSWERED 可转 CANCELLED；历史不删除。回答只写一次，使用 expected row_version 与幂等键；同键同原文重试返回原记录，冲突拒绝。回答与同一原 Job 重新 QUEUED 在同一事务提交。原逻辑绑定重新取得有效 claim 后，校验原 primary / native Session 和受控 workspace，在事务中消费答案、将主 AgentSession 恢复 RUNNING / Binding 恢复 ACTIVE，再继续原会话的 Run 级工作；不得创建或重开一个阶段 Attempt 来“承接”该答案。

取消原 Job / Run 会取消尚未消费的 RunInputRequest，保留问题与已回答原文；Job 与 Run 的 Session 终结范围仍按 §23.4 区分。等待、回答、消费、取消及恢复写配对 Audit / Outbox，事件不复制正文或 Provider 日志。原生 Session / workspace 丢失仍显式失败；不把问题转绑另一个 Job、Session 或 Run 来冒充恢复。新增表及双范围互斥检查已在本分支 additive 实现，现有 v1alpha1 MissionInputRequest、问答、Attempt、Job 和 Session 历史保持原样。

### 23.3 有界任务活动与 Provider 信号

`mission_activity_events` 是可裁剪的 Operational State，属于白皮书的辅助 Agent Activity，不是 Canonical Testing State、可信 Evidence、质量进度或生命周期 Audit。新增迁移 `0010_mission_activity` 不改写既有快照、问题回答、Attempt、Job 或测试历史。活动表不进入 Gate 的状态序列化、Evidence manifest、覆盖计算或领域 Outbox。

每条记录关联同一 Run 的 DurableJob、Mission、MissionAttempt、AgentSession，保留 UUIDv7 身份、当前领取次数、固定活动类型、来源、平台记录时间和合并计数。来源区分 `PROVIDER` 与 `CONTROL_PLANE`。不允许自由文本 payload、原生 Provider 事件 / ID、命令及参数、文件路径、推理、消息正文、PRD、回答、stdout/stderr 或认证资料。Adapter 先将 Provider 事件投影至允许列表；未知事件只可产生固定的“收到信号”类型，不透传原文。错误只提供受控错误类别和退出码，不将 CLI stderr 当作活动或用户错误详情持久化。

Provider 信号表示平台观察到外部事件，不证明模型推理有效、工作已完成或测试已通过。本地生成的 Mission 开始、恢复、结果提交和结束事件不能更新 Provider 信号时间；Worker 心跳另行表示 Worker 存活。原 Attempt 在人工等待和恢复中保持，活动按新领取次数区分；最近 Provider 时间只针对当前领取，不能用上一轮事件、原始 Job.started_at 或心跳补出本轮进度。数据库记录时间是平台接收 / 持久记录时刻，不冒称 Provider 原生时间。

采集器使用有界内存队列、单独写入器及约 2 秒合并窗口；每 Attempt 最多保留最近 200 条活动。裁剪仅影响此辅助记录，不删除正式历史或问答。API 提供有上限的分页并说明近期记录可能截断，不承诺完整逐事件日志或 exactly-once 遥测。

活动写入使用独立短事务，按 Run → Job → Attempt 顺序检查关系、RUNNING 状态、当前 token / claim 和数据库时钟中的有效租约；取消、暂停、终态、旧领取及租约过期后的迟到事件拒绝写入。不能在 Provider I/O 期间持锁，不能使主任务等待一个也等待其行锁的活动写入器。写入繁忙、队列满或遥测失败可丢弃活动；有界收尾在主事务取得完成锁前进行。辅助遥测故障不能将有效 Proposal 变成失败、改变 Runner / Gate 决策或触发自动重放。

只读任务活动接口返回数据库观察时间、当前阶段 / Attempt、当前领取的最近 Provider 信号、该 Job 的 Worker 心跳及安全活动分页。阶段只由已持久运行状态推导；没有信号时应表示未知。长时间无新信号只是观察提示，不等于卡死；WAITING_INPUT、正式 Runner 执行和终态不显示“模型静默”警报。刷新失败保留已加载内容并说明尚未更新，用户取消、回答和显式重试继续由原受控流程处理。

v0.4 目标的活动和执行结果回调还必须匹配当前 RunExecutionBinding / binding_epoch 与 Job claim。持久会话跨 Mission 不允许把上一 Attempt / 旧 epoch 的信号计作当前活动；这些 Operational 关联不把 Provider 原文、原生认证或会话内容加入 Canonical 序列化。撤销后对旧调用的受限查询 / 清理权限按 §23.4 单独处理，不允许据此写入当前 Provider 活动。

### 23.4 v0.4 RunExecutionBinding（本分支已实现）

`RunExecutionBinding` 是一个 TestRun 的持久执行归属，表名为 `run_execution_bindings`。它不是 Canonical Test Fact，不取代 TestRun、DurableJob、AgentSession 或 WorkerHeartbeat，也不表示一个新测试任务。首次 Provider 调用前，平台原子建立同一 Run 的绑定和主 AgentSession 记录；主 Session 的原生引用允许在首次真实 Provider 回应前暂为 NULL，但不得伪造。

这是受管 Provider 的初次建立路径。ADR-016 的初次 interactive attach 不调用 create / execute 启动 Provider，而是经独立 run:execute、设备 / 项目能力和可信宿主证明，在互斥事务中登记当前真实 native Session；其原生引用须在接受 attach 时已可验证，不能采用占位 NULL。该结构登记不依赖尚未领取的初始 Job claim，也不颁发任何领域执行权：先登记唯一 Binding / Session / Placement，再由平台 coordinator 按原规则领取初始 Job，最后以有效 claim / epoch 颁发短执行授权。由此不得形成“未 attach 不领取，而 attach 又要求已领取”的循环，也不能让未 attach 的 Job 启动影子 Harness。

以下字段与约束由 `0013_run_bindings` 实现；生产已完成至 `0014_harness_operations` 的[独立迁移与保全验收](../ADR013_PRODUCTION_DEPLOYMENT.md)，旧历史不回填：

| 字段 | 目标语义 |
|---|---|
| `id` | UUIDv7 PK，稳定 Binding 身份 |
| `test_run_id` | NOT NULL FK → TestRun，`UNIQUE(test_run_id)` |
| `logical_worker_id` | NOT NULL UUID，`UNIQUE(logical_worker_id)`；该 Run 唯一逻辑 TaskWorker，不是进程 PID 或 `DurableJob.worker_id` |
| `primary_agent_session_id` | NOT NULL FK → AgentSession，UNIQUE；只绑定本 Run 的一条主 Session |
| `harness_host_id` | NOT NULL，稳定的 Harness 节点引用；现有实现为服务器宿主，指向原生会话 / 认证运行时所在节点，不以临时 IP / 容器名代替；ADR-015 目标与 §23.9 的 node 身份一致映射 |
| `workspace_id` | NOT NULL，原主 Session 的受控持久工作副本引用，必须等于其 AgentSession.workspace_id |
| `binding_epoch` | NOT NULL bigint，初值 1 且 > 0；只有显式受控恢复可单调递增 |
| `status` | RESERVED / ACTIVE / WAITING_INPUT / RECOVERY_REQUIRED / CLOSED / FAILED / CANCELLED |
| `created_at` / `updated_at` | timestamptz，平台观察时间 |
| `row_version` | bigint，状态 / epoch 的乐观并发版本 |

关系 / 唯一 / 历史约束：

1. `test_run_id`、`logical_worker_id`、`primary_agent_session_id`、`harness_host_id`、`workspace_id` 创建后不可改绑；Session 与 Binding 必须属于同一 Run。FK 使用 `ON DELETE RESTRICT`，拒绝删除有任务 / Attempt 归属的记录。表和约束由本分支 `0013_run_bindings` 与受控服务共同实现，不能只靠请求 JSON 声明所有权。
2. 同一 Run 全生命周期只建立一个逻辑 TaskWorker 绑定和一个主 Session。多个串行 MissionAttempt 可引用这个 Session；一个 Session 不能作为两个 Run 的主会话。不同 Run 各自独立绑定，可以同时运行；不允许一个 Run 通过多个绑定、多个活跃 owner 或多个主 Session fanout。
3. 现有每 Run 单活跃 DurableJob 约束继续有效。Job 的 request / `durable_job_id` 归属、Attempt 的 Mission / Session 关系及正式 Execution 身份仍独立且不可变。跨 Job 继续同一 Run 不意味着把历史 Attempt / Execution 改绑到新 Job。
4. 目标 admission / commit 按 Run → RunExecutionBinding → Job 的所有权锁序验证，再由领域服务遵守既有 Mission / Question / SourceSnapshot 相对锁序；插入 Binding 检查不反转已有 Run → Job 顺序。验证范围包括 Binding status、epoch、原 Session / workspace / Harness 节点和当前有效 Job token / 数据库时钟。事务不能跨 Host Bridge、Provider、Git 或 Docker I/O 持有这些锁，返回后重新 fencing。
5. 进程 ID、容器 ID、Job worker_id / lease_token、WorkerHeartbeat 是暂时占用。正常阶段转换或 WAITING_INPUT 不分配新的 logical_worker_id、不替换主 Session、不增加 epoch；每个新 Job claim 仍有独立 token。平台 Owner 进程 / 容器失联后只能经显式恢复接续同一逻辑绑定。Provider CLI 为正常执行 / resume 启停进程本身不等于替换逻辑 TaskWorker。
6. 新建 / execute / resume 等会启动 Provider 工作的 Bridge 调用，以及业务 typed tool 写入 / 正式结果提交，必须具有当前 Binding / epoch 和有效 Job claim，并匹配相应 Run / Mission / Attempt 范围。Run 级问答 / 报告等使用明确 Run 范围，不伪造阶段所有者。已取消、失联、旧 epoch、旧 claim 或错误范围的迟到执行请求不得继续工作或提交；相同 provider session 字符串本身不是授权。Bridge / Provider 不持有 Canonical 数据库或平台 GitLab 集成凭证，不拥有 Canonical 状态写权限；ADR-015 的节点受控 source / issue adapter 可持有本地授权，但必须与 Provider 分离。
7. Binding 生命周期和恢复决策写 Audit / Outbox，与状态更新事务提交；事件保存归属、旧新 epoch、原因和受控操作结果，不保存认证、原生对话或推理。Binding 不参与 Coverage、Evidence manifest 或 Gate State Hash。

执行授权与管理 / 恢复授权必须分开。可信 HyperTest 服务身份可以持有窄 management capability，明确限定 Binding、primary / native Session、原 call_id 和要检查 / 清理的历史 generation。即使该调用原 Job claim 已撤销，也可查询 get_call、只读核验既有会话 / workspace，或 interrupt / close 该受控旧调用以完成取消、失联处理和资源回收。该权限不启动新的 Provider 工作，不 resume 推理、不建立替代会话、不提交 Canonical 结果，也不把旧 owner 恢复成有效执行者。

管理操作必须显式匹配目标调用与历史 epoch；按旧 generation 清理不得影响新 epoch 的活动调用。若需要关闭整个主 Session / 删除其持久 workspace，还须满足 Run 终结或不可恢复失败的明确清理授权，不能仅因一个旧 Job 被取消而破坏仍可恢复的主会话。管理查询 / 清理的结果只用于受控恢复和审计；随后若要执行 Provider，仍必须重新通过当前 epoch / active claim 的执行准入。

对 INTERACTIVE_MCP，这些 interrupt / close / cleanup 只作用于本 Run 的执行关联及 Connector 实际管理的受控资源；不能把窄管理授权解释为启动 / 终止用户整个聊天、重建 native Session 或清理其个人目录。当前 native continuation、attachment 停止 / 脱离和预算活动仍须可信宿主核验，不以 Agent 自报或 Connector 在线代替。

状态转换：

```text
RESERVED → ACTIVE
ACTIVE → WAITING_INPUT → ACTIVE
RESERVED / ACTIVE / WAITING_INPUT → RECOVERY_REQUIRED
RECOVERY_REQUIRED → ACTIVE           # 仅显式 fenced recovery 成功
RESERVED / ACTIVE / WAITING_INPUT / RECOVERY_REQUIRED → CLOSED / FAILED / CANCELLED
```

RESERVED 表示绑定已建立但未开始主会话执行；ACTIVE 表示该逻辑主会话可在原绑定内继续，不能据此推断存在活跃 PID 或测试已通过。WAITING_INPUT 保留同一绑定 / 会话 / 原生 thread / workspace，释放运行 lease 与 CPU。正常 Mission 完成仍保持非终态绑定；CLOSED 只用于 Run 的受控结束，FAILED 用于任务执行不可恢复，CANCELLED 用于 Run 取消。三种终态不可重新打开或替换主会话，均不表达质量 PASS / FAIL。

显式恢复必须满足：

- 按失联资源范围处理：平台 Job / owner 失联时，先按原有规则结束其拥有的未完成 Job / Attempt / Execution 并保留历史，绑定进入 RECOVERY_REQUIRED。ADR-015 中只有 Connector 通道 / dispatch grant 失联时，不等同于服务器 Job / Runner owner 失联；仍有有效 Runner 时保留其原 Binding 状态 / epoch / Job claim 仅用于收集该 Execution，同时撤销 Harness grant 并阻止新工作，收集或受控取消结束后才进入 RECOVERY_REQUIRED；详见 §23.9。确认旧 Harness owner 与外部调用已经被 fence / 中断后，才在同一绑定递增 `binding_epoch`；状态 / epoch 及审计按同一事务提交。无法确认旧调用是否仍运行时保持 RECOVERY_REQUIRED，不先启动第二个 owner。
- 在无聚合行锁时验证原 Harness 节点、已固定原生 Session、受控 workspace 及 pinned source Hash；返回后再次验证新 epoch / 当前恢复授权。不能用 Agent 保存的 Hash、自报完成或新会话代替核验。
- 核验成功后回到 ACTIVE，在同一逻辑绑定 / 主 Session 下使用按原规则新建的 Job / Attempt / Execution。不得重开 INTERRUPTED Job、复用失效 token、覆盖旧 Attempt 或自动重放结果未知的外部执行。
- 原生会话 / workspace 丢失、被篡改或无法恢复时，明确使绑定 / 主 Session 失败并停止当前 Run 的执行，保留任务与已接受事实供查看；替代主 Session 必须由用户明确开始新 Run / 轮次。不得悄悄改 `primary_agent_session_id`、换 Provider / Harness 节点或用另一 PID 创建新 thread 冒充恢复。

### 23.5 v0.4 持久 Harness 的受控自驱边界（本分支已实现）

Harness 在同一主会话中串行完成分析、风险识别、测试设计、实现、请求正式执行、失败诊断和报告。平台容器中的 TaskWorker 保持任务归属、租约和治理；ADR-013 的窄 Host Bridge 仅托管允许的 Provider session / 调用，不承担 Planner、Canonical Verifier、Runner 事实认证或 Gate。ADR-015 的本地 Connector 保持同一边界，另以隔离 adapter 执行已批准的 source / issue 操作，不成为 Runner 或通用 shell。具体 tools / transport profile 由 TMP、ADR-013 / ADR-015 定义，不通过修改现有 wire version 偷渡语义。

持久会话可以通过有界、类型化、幂等的领域工具读取已接受状态，请求 / 进入 typed Mission，提交 Proposal batch，申请正式 Runner，读取受控结果，发起人工决策及报告 / GitLab Issue Request。执行调用必须限制 Run / Snapshot、当前绑定 / epoch / lease、目标及预算；阶段内调用还绑定当前 Mission / Attempt，阶段间的 Run 级问答按 §23.2 的 RunInputRequest 范围验证。Planner 检查 deterministic dependency、coverage gap、范围和预算准入；Agent 自主决定如何推理和组织其允许范围内的串行工作。禁止为了此部署形态重新实现通用 Think / Tool / Observe Agent Loop，或把任意 shell / SQL / 工作目录暴露为平台写工具。

typed Proposal 工具不直接接受 Canonical Lifecycle；Verifier 对每个显式提交 batch 保持全批合法、原子接受 / 拒绝、Audit / Outbox 和来源追溯。Mission 只有 required outputs 全部被接受才完成，不因某个工具返回成功就跳过阶段验收。Agent 申请执行不等于 Execution COMPLETED；只有可信 Runner 采集产生正式事实。报告可持久保存为可追溯输出，但不能创建另一个由模型决定的 Verdict 或把会话 / Job / Binding 终态当作质量决策。

### 23.6 v0.3 历史与 v0.4 迁移边界

现有 Run 可以具有多条阶段 AgentSession，也可能具有无 Job 归属的 direct 调用记录；这些都是有效历史。不得推断、合并、回填主会话或把历史原生 thread 换写成新的 Binding。v0.4 绑定仅在本分支新 profile 明确准入的任务上建立，`0013` / `0014` 不回填旧 Run；旧 Run 保留 v0.3 解释，必要时通过显式新测试轮次进入目标形态。

新增绑定、RunInputRequest、跨问答表互斥、唯一 / FK 约束、恢复 generation、Session 关闭策略、阶段准入和 typed tools 已有本分支实现与对应回归；部署容器、升级文档或配置 Host Bridge 地址仍不能单独证明验收完成。v0.3 的逐 Mission close、暂停恢复和显式 retry 测试只证明原行为；新 Run 级会话 / owner fencing / 丢失会话 / 人工等待 / 不同 Run 并发的实际证据与剩余条件见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)。

### 23.7 ADR-013 Operational 持久化边界

持久 Harness 的可靠续接需要以下 Operational 记录；这些记录不属于 Canonical Testing State，不加入既有 Gate state hash / evidence manifest，不回填旧 Run，不保存认证材料、Provider 对话或思维链。数据库约束保护结构和历史，Worker 的当前 Binding / epoch / Job token / 数据库时钟检查仍是写入授权；二者不能互相替代。

在 queued 部署或 Run 已建立持久 Binding 时，公开 API 的单阶段创建、plan-next、retry、cancel 与同步执行入口不得绕过受控 Harness 修改阶段；用户通过原后台任务的取消、回答及显式恢复 / 重试入口操作。阶段列表、Attempt、Proposal 与结果仍可读取。旧 direct 且未绑定的 Run 保留原有操作语义。

| 实体 / 表 | 固定身份与用途 | 可变范围 |
|---|---|---|
| `RunHarnessState` / `run_harness_states` | 每个 Binding 一行；冻结首个 ADVANCE_RUN Job、pinned source 检出路径、最大阶段预算、单次执行时限及总活跃执行秒数预算 | 当前 Mission / Attempt、最近 Bridge call / Job / epoch、尚未落入正式 Question 的 `pending_input` 意图 |
| `RunToolCall` / `run_tool_calls` | Binding 内唯一幂等键；固定工具名、输入 SHA-256、Job、epoch；调用前写入 | 受控记录结果状态、结构化返回和结束时间 |
| `RunReport` / `run_reports` | Binding 内唯一幂等键；关联同一 Run / Binding / Job，保存报告 envelope 与内容地址 / SHA-256 | 只追加，禁止改写或删除 |
| `RuntimeControlRequest` / `runtime_control_requests` | API 至可信 Worker 的窄请求；固定 operation / payload / deadline；不携带 Bridge key | 队列领取、可验证结果或有界错误分类、开始 / 结束时间 |
| `GitLabIssueOperation` / `gitlab_issue_operations` | 同一 Binding / Finding 最多一次外部创建意图；固定 Run / Job、输入摘要、清理后的 draft、已决授权快照 | 受控结果状态与经核对的真实 issue 引用 |

`RunHarnessState` 的首配置不可变；换进程、重新领取 Job、人工问答或显式恢复不能重置累计预算。累计次数由整个 Binding 的 `RunToolCall` ledger 推导。`harness_budget_seconds` 默认 3600，允许 1–7200 秒并在首次绑定时冻结；它限制整个 Run 的 Harness 活跃执行秒数，不代表模型计费 token 上限。等待用户输入不消耗活跃预算，恢复也不重置累计使用量。当前 Mission 与 Attempt 必须同时为空或成对存在，Attempt 必须属于该 Mission、同一 Run 和原主 Session。最近 call / Job / epoch 三项同时为空或同时存在，Job 必须同 Run，epoch 不能超过当前 Binding；旧 checkpoint 可保留旧 epoch 供恢复核验，不因此恢复旧写权限。`pending_input` 是有界 JSON 对象，不是已提交的问题：必须在工具成功确认前持久保存，正式暂停事务确认 Question 已保存后才能清除。重放同一工具确认不能丢失此等待意图，也不能重复创建问题或重开已完成阶段。不得删除 checkpoint 来获得新预算 / 主会话。

`RunToolCall` 新行必须匹配当前 Binding epoch；工具身份、输入摘要与关联 Job 不可变，结果不确定时不以新幂等键自动重放。允许状态转换为 `STARTED → UNKNOWN / SUCCEEDED / FAILED`，以及明确核对后的 `UNKNOWN → SUCCEEDED / FAILED`；重复核对可以保持 UNKNOWN。SUCCEEDED / FAILED 为不可变终态，禁止删除历史。Canonical 提交与工具确认之间若发生中断，原记录保持可观察的不确定状态；恢复须按已保存的 Mission / Attempt / Execution / Report 等关联核对事实，不将 Agent 自述当作成功证明。核对旧 epoch 结果只解释原调用，不恢复其执行授权。

`RunToolCall.tool_name = __bridge_call__` 是 Worker 保留的调用预算记录，Agent 不可自行调用此名称。Worker 在启动每次原生调用前以 STARTED 记录 `reserved_seconds` 和 `call_id`；这两个值不可更换。已核实终态另外保存 `elapsed_seconds` 与状态。累计预算将已核实耗时与所有尚不确定调用的完整预留相加，只有 Bridge 的可信对账可以结算预留，不能依据 Agent 自述释放额度。常规 typed tool 的 STARTED 行仍不能预填结果。

`RunReport` 内容用 `sha256:<content_sha256>` 寻址；读出时核验字节摘要，并以纯文本返回。提交服务必须核对冻结的 Source / Policy / commit、实际 Execution / Evidence / Finding 集合及最新正式 Verdict，拒绝尚有必需工作或错误引用的报告；这些准入检查不因数据库存在一行报告而被跳过。报告摘要和 Markdown 都不是质量决定。数据库保护同 Run 所有权、内容地址一致性和 append-only 历史。

`RuntimeControlRequest` 初态 QUEUED，只允许 `QUEUED → RUNNING / UNKNOWN` 和 `RUNNING → SUCCEEDED / FAILED / UNKNOWN`。期限到达或 Worker 丢失后的 UNKNOWN 是终态，不能重新排队自动执行原请求；用户先核对实际状态，必要时发起新的显式请求。API 不使用此表调用任意工具、读取宿主凭据或接管 Runtime 权限；Worker 独立验证 operation allowlist、请求内容、当前绑定及外部事实。

`GitLabIssueOperation` 初态 PENDING，允许 `PENDING → UNKNOWN / SUCCEEDED / REJECTED`、`UNKNOWN → SUCCEEDED / REJECTED` 或保持 UNKNOWN；不确定状态仅查询核对，禁止再次 POST。SUCCEEDED / REJECTED 历史不可改写或删除，只有 SUCCEEDED 可携带正数 issue IID 与核验后的 HTTPS URL。Finding 必须与 Run / Binding / Job 同属；draft、授权项目 / 受派人、输入摘要不可在请求之后更换。真实凭据只留在受控执行环境；授权快照不得保存 token 或认证文件内容。提单成功仅增加集成引用，不自动确认、解决 Finding 或改变 Verdict。

### 23.8 CLOSED 后的独立平台 Gate 治理（ADR-014）

原 Binding 和 primary AgentSession 同为 CLOSED、且同 Run/Binding 已有被接受 RunReport 时，可信平台可以接受操作者显式的 EVALUATE_GATE DurableJob。只允许 finalize=true，reason 去除首尾空白后非空、不含 NUL、最长2000字符；理由存于 Operational 请求及 Audit/Outbox，不影响质量决策或 Gate hash。没有 Binding 的历史 Run 保持既有语义，reason 缺省兼容原请求；不修改冻结的旧 payload。

准入、领取、写事务均验证 Run 排他、原 Binding ID/epoch、primary CLOSED、操作类型、当前 lease/token/数据库时钟，遵守 Run → Binding → Job → SourceSnapshot 锁序。存在活跃 Job/Mission/Execution 时拒绝并行提交。RESERVED/ACTIVE/WAITING_INPUT/RECOVERY_REQUIRED/FAILED/CANCELLED，以及缺少已接受报告的 CLOSED，不得借此绕过现有 Harness 准入。

这是平台治理授权，不是新的 Binding 执行 claim：不调用模型、Bridge、Git、Runner 或能力预检，不创建/恢复 AgentSession，不改变 Binding/原生会话/checkpoint/预算/Mission/Attempt/Execution/Evidence/RunReport。失败、取消或过期 Job 的资源清理同样不访问这些外部组件，也不关闭原主 Session。重试保留原 reason/payload 和 retry_of，通过新 Job 的租约与当前 CLOSED-only 准入执行。

Gate 仍根据固定 Policy 和可信事实决定；Finding 关闭或风险处置不能豁免失败的正式执行。只复用最新相同语义结论，否则追加新 sequence，旧 FINAL/links/报告原样保留。每个独立请求均保存理由与返回 Verdict 的配对审计/Outbox，即使复用原结论。报告读模型可从 immutable envelope 投影 nullable verdict_key/verdict_decision；未知或不合法引用保持未知，不回填报告。Web 应区分报告原结论与最新 FINAL，不重新调用 Agent 更新历史报告。

### 23.9 ADR-015 双模式 Harness 与本地 Connector（v0.5 已部署，线上核心验收通过）

本节 Operational 模型和准入已由 `0015_connector_nodes`、`0016_source_transfer`、`0017_issue_executor`、`0018_harness_selection` additive migrations 实现，隔离约束 / 服务回归已通过；核心隔离真实端到端验收通过，生产已部署，线上核心周期已通过，扩展故障矩阵继续逐设备登记。见[生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)。`0013_run_bindings` / `0014_harness_operations` 及其已有生产验收仍表示 ADR-013，不改写历史表迁移、旧 Run / Snapshot / FINAL 或 hash。SERVER_HOST 保留现有 UDS Bridge；LOCAL_CONNECTOR 由用户节点主动发起经设备认证的 WSS 连接，使用独立协商的 `hypertest.harness-connector/v1alpha1`，Artifact 使用有范围 / 时限的 HTTPS 传输。现有 TMP `hypertest.tmp/v1alpha2` / `run-persistent-harness/v1` 的领域工具语义不变，已有客户端未协商时不能声称支持 Connector。

**模式、节点与授权。** 首次源码准备 / Run 绑定前，操作者明确选择 SERVER_HOST 或 LOCAL_CONNECTOR 及稳定节点，并把选择记入不可变请求。初次绑定原子创建唯一 RunHarnessPlacement；一个 Run 只有一个逻辑 Worker、主 AgentSession、原生 Session、workspace 和 Harness 节点。模式、节点、source transfer 路径 / 关联创建后不可改绑，重连、Job retry、负载均衡和凭据缺失均不能静默降级到另一节点或服务器模式。不可恢复时保留历史并终止该绑定，替代会话须显式新建 TestRun。

Provider 认证和原生会话留在所选节点；Git 与问题单操作由该节点的受控 integration adapter 复用实际可用的 credential helper、SSH agent、CLI / MCP 等授权，不上传 token / SSH key / 认证目录，不把认证交给模型。浏览器 cookie / 登录态不自动等于 CLI / API 可用授权。设备与平台的配对身份单独授权、可撤销；连接成功、能力声明和用户已有本地授权都不自动授予 Project、source-acquisition 或 issue-write 权限。用户可以单独撤销设备、项目或集成授权，平台只保存身份 / scope / 授权策略引用与审计，不保存外部凭据。

已实现的 Operational 记录如下。平台新建主记录使用 UUIDv7；源码输入请求允许调用者提供 UUID 幂等身份，Selection 使用 Run 主键，Snapshot receipt 使用复合主键。FK 使用 `ON DELETE RESTRICT`；固定身份 / 输入和 append-only 历史不可修改或删除，可变状态按各表使用行锁 / `row_version` 与平台时间。不得通过 JSON 数组代替节点 / Binding / Job / operation 的关系约束。

| 实体与实际表 | 固定字段 / 关系与约束 | 状态与可变范围 |
|---|---|---|
| `HarnessNode` / `harness_nodes` | `id`、UNIQUE `node_key`、owner、`node_kind`、created_at；显示名、IP 和连接不是身份 | 操作者配对直接建立 ACTIVE；模型保留 PENDING，撤销为 REVOKED 且不重开。presence / generation / last_seen 与有界能力声明仅为 Operational 观察 |
| `HarnessDeviceGrant` / `harness_device_grants` | `id`、node FK、UNIQUE `token_hash`、`key_version`、operator / policy、not_before / expires_at | ACTIVE → EXPIRED / REVOKED。平台只存随机 bearer 的 SHA-256；节点私有文件保存明文。`key_version` 是代次引用，不是公开公钥；轮换建立新 grant，保留旧 hash / 引用与审计供历史核验，绝不重新激活旧执行权 |
| `NodeProjectCapability` / `node_project_capabilities` | node / Project FK、capability、constraints、policy / operator；每 node / Project / capability 至多一个 ACTIVE（partial UNIQUE） | `harness` / `source_acquisition` / `issue_executor` 分开授权；ACTIVE → REVOKED，scope 改变另建行。配对不推定拥有项目能力；source origin 和 issue project / assignee 精确范围分别核验 |
| `RunHarnessSelection` / `run_harness_selections` | Run PK/FK、mode=LOCAL_CONNECTOR、node FK、accepted transfer FK | bootstrap 与 Run / Snapshot 同事务保存，先于首 Binding，append-only；transfer 必须同 Project / node / origin / SHA 且来源角色当前有效。服务器兼容默认无该新行，不回填旧历史 |
| `RunHarnessPlacement` / `run_harness_placements` | Run / Binding 各 UNIQUE FK、node FK、mode、source_transfer_kind、适用 transfer FK；匹配 Binding.harness_host_id / Session.workspace_id 和 Selection | append-only，与首 Binding 原子创建；LOCAL_CONNECTOR 固定 SOURCE_BUNDLE，SERVER_HOST 固定 SERVER_WORKSPACE。历史无 Placement 的 ADR-013 Run 仍按原服务器行为读取 |
| `HarnessDispatchGrant` / `harness_dispatch_grants` | node / Project / Placement / Binding / Session / Job / device grant / capability FK；workspace、claim_identity、epoch、call、operation、audience、时限 | ACTIVE → EXPIRED / REVOKED；不超过 Job lease、device grant 与 120 秒。设备仅收到单向派生 claim identity，服务器 Job lease 原始秘密不下发；当前数据库 claim / epoch 才能准入与提交 |
| `ConnectorRequest` / `connector_requests` | node / 可选 dispatch FK、固定 operation / authority / payload / input_sha256 / expires_at；SENT 后 connection_generation / sent_at 不变 | QUEUED → SENT / UNKNOWN；SENT → SUCCEEDED / FAILED / UNKNOWN，终态不可重发。发送前持久消费；4,000,000 bytes 消息、每节点 256 queued/sent 上限。operation whitelist 与权限逐次核对；`issue_create` 对 payload.operation_id 全历史 UNIQUE，UNKNOWN / 账本丢失也不释放创建机会 |
| `SourceAcquisitionRequest` / `source_acquisition_requests` | request UUID、Project / node FK、批准 origin / ref、完整 SHA、policy / created_at | append-only，来源输入请求 ID 同键异值冲突；源码获取前完成必要可信 Runner 预检，Git I/O 不持聚合行锁 |
| `SourceBundleTransfer` / `source_bundle_transfers` | Project / request / node / source capability FK、idempotency_key、批准 origin / ref / commit / policy；UNIQUE(project_id,idempotency_key) | UPLOADING → VERIFYING / REJECTED / EXPIRED；VERIFYING → ACCEPTED / REJECTED / EXPIRED。ACCEPTED 一次冻结 root tree、format、包 / manifest / receipt、server workspace 与时间；终态不可改，失败显式新键建立新 transfer |
| `SourceUploadGrant` / `source_upload_grants` | 每 transfer UNIQUE FK、device grant FK、UNIQUE token_hash、包 digest / 精确长度 / receipt、时限 | ACTIVE → CONSUMED / REVOKED / EXPIRED；独立随机上传 bearer 仅存哈希，最长 120 秒且不超设备 / transfer 有效期。I/O 后重查当前设备 / 项目来源授权，认证 receipt 不携带第三方凭据 |
| `SourceTransferSnapshot` / `source_transfer_snapshots` | transfer / Snapshot 复合 PK/FK、created_at | append-only，bootstrap 冻结 Snapshot 时关联同 Project / origin / SHA 的 ACCEPTED transfer。行锁串行校验同 Snapshot 不得关联不同已固定包；不更新 ACCEPTED transfer 或 Snapshot fingerprint |
| `GitLabIssueOperationExecutor` / `gitlab_issue_operation_executors` | operation UNIQUE FK、mode、node / capability / device grant FK、integration_id、delegation / SHA-256；固定原操作输入与 correlation | append-only；LOCAL_CONNECTOR 必须显式当前 issue_executor 与 device grant。跨 epoch / Job / 后端仍使用同 Binding / Finding 去重；外部状态继续属于原 GitLabIssueOperation，不因 ACK 或设备自报而成功 |

SOURCE 的设备认证 receipt 是受控采集 adapter 的结果，必须覆盖 §9.1 的 origin / ref、commit / tree、bundle digest、Project / 请求 / node / 授权 policy 与采集结果。首版平台核验 TLS 上传连接的 bearer 设备身份、receipt 的 grant / node / Project / 请求 / policy 归属及显式 source-acquisition scope，不声称 receipt 使用非对称设备签名；仍独立重算 commit / tree / blob；receipt 不取代对象链校验，单独配对不取代来源角色。测试代码按原 Proposal / Verifier / Artifact 流程提交；SourceBundleTransfer 与本地探索结果不进入 Evidence。Issue executor 只收到已批准的固定操作，凭据由隔离 adapter 使用，平台核验其认证远端回执或查询结果，Agent 自述不构成成功。

`install_workspace(create=true)` 是执行性派发，必须匹配原 Run / Binding / Session / workspace / transfer、当前 epoch / Job claim、有效设备 / Harness scope 与短期 DispatchGrant，发送时再次 fencing；取消或撤权后旧排队安装不能落地。`create=false` 是匹配原身份的只读管理核验，不创建目录、不复制或修复文件、不重建丢失 workspace；仅确定的 WORKSPACE_UNAVAILABLE / WORKSPACE_INTEGRITY_REJECTED 才可证明不可恢复，网络 UNKNOWN / scope 暂不可用不能当作原会话永久丢失。

**连接、执行授权和平台租约分别治理。** WSS 连接的 presence / generation、HarnessDispatchGrant TTL 和服务器 DurableJob / Runner ownership 是三个不同范围。短暂断线时停止接收新派发、不自续授权，原已接受 call 最长运行到现有短 grant 到期；可达的撤权立即生效。重连只允许重建通道、查询原 call / 有界补读事件，不重复 create / execute / resume，不自动延长授权或重发外部写入。确认失联、无法续约、TTL 到期或授权撤销后，原 Connector 执行 grant 不得继续使用；节点看门狗停止接收新工作并尝试中断原受控调用，平台撤销对应执行授权，将未确认 call / tool / issue 操作保留为可观察 UNKNOWN。不能只终止 socket 就假定原 Provider / 外部 POST 已停止，也不能以心跳恢复重新授权或重放。

原 Harness 调用需要对账、且没有仍受有效服务器 owner 治理的 Execution 时，ACTIVE / RESERVED Binding 进入 RECOVERY_REQUIRED。若仍有有效 Runner，先保留原 Binding 状态 / epoch / Job claim 仅用于完成、收集或受控取消该 Execution，同时撤销 Harness dispatch 并拒绝一切新 Harness 调用 / 领域工具写入；收集或取消结束后才进入 RECOVERY_REQUIRED。不增加 RECOVERY_REQUIRED 下全面写入的例外。WAITING_INPUT 可保持原等待预约，回答仍只保存一次；若回答已使原 Job 重新排队，真正继续 Harness 前仍须满足原绑定恢复与当前授权，不因重连自动消费回答 / 发起 execute。CLOSED / FAILED / CANCELLED 均保持终态；设备重新在线不重开会话、问题、阶段或任务。离线只是 Operational presence，不增加或借用 TestRun 的领域状态。

只要服务器 Job / Runner owner 仍有效，Connector 离线不终止已经接受的正式 Execution：Runner 可以独立执行、采集并按原 Execution / spec / `durable_job_id` 提交结果；Connector 恢复后只读取原执行结果，不能再次申请同一外部执行。在需要更换 epoch / Job claim 的 Harness 恢复之前，先完成并收集该 Execution，或通过原规则受控取消；不能提前换代误拒仍有效 Runner 的结果，也不能绕过同 Run 单活跃 Job。若服务器 Job / owner 本身失联，则按 §23.1 / §23.4 原有范围终结其未完成历史，不能把 Connector 心跳当作 Runner lease，也不能向已终结 Execution 写迟到结果。

重连首先只重建认证通道和受限查询 / 清理权限，校验原 node / Binding / Session / workspace、所有未知 call / tool / operation、当前 checkpoint 与 pinned source，不启动 Provider。只有操作者显式恢复、可信平台确认旧 owner / 旧调用已 fenced，并核对原 Session / workspace 可恢复后，才在同一 Binding 递增 epoch、建立新的 Job claim / 短执行 grant；不得复用旧 claim、重开终态 Job、替换 Session 或重放结果未知的 Runner / Issue 操作。UNKNOWN Issue 只按原 operation_id 查询对账；查不清则继续 UNKNOWN 或请求人工处理。

离线取消先在平台持久化取消、撤销执行 grant、终结相应 pending 工作 / 输入并记录审计；节点再次连接仅接收针对旧 call / generation 的受限 interrupt / cleanup，不恢复业务执行。撤销后的 management capability 与执行授权分离，明确限定目标与历史 generation；无法验证外部进程已停止时保持清理待确认，不能谎称资源已释放，也不清理其他 Run 或新 epoch 的资源。节点 / 集成授权撤销同样不撤销已被平台接受的历史 Evidence / Verdict。

**事务与迁移。** admission / commit 仍遵守 Run → Binding → Job → SourceSnapshot 的既有相对锁序；节点 / 设备 / 集成授权应在该事务内按确定性次序核对当前状态，但不跨 WSS / HTTPS / Provider / Git / issue API I/O 持锁，返回后重新 fencing。节点配对 / 撤销、grant 颁发 / 失效、源码接受 / 拒绝、Issue 对账、恢复和清理均由 PostgreSQL 记录，并与相应状态变化同事务写 Audit / Outbox；不引入消息总线、Graph DB 或全量事件溯源。它们不进入 Gate State Hash / evidence manifest，也不把设备 heartbeat 当测试事实。迁移须验证唯一 / FK / append-only / scope / claim / epoch 约束；已有 Run / Snapshot / Artifact URI、`durable_job_id`、原生引用、预算和 FINAL 不回填、不合并、不重算。

### 23.10 ADR-016 交互式 Agent MCP 接入（v0.6 已实现，真实当前 Agent 已验收 / 已部署生产，线上当前 Agent 核心周期已通过）

本节于 2026-10-20（Asia/Singapore）定义并实现新增 Operational 契约。接入方向为当前交互 Agent → 可安装 stdio MCP adapter → 本地常驻 Connector → 新的 scoped typed HTTPS API；安装包不自动授予平台或节点权限。独立 profile 为 `hypertest.interactive-mcp/v1alpha1`，不原地重解释现有 TMP、UDS Bridge、Connector WSS 或内部 relay。HyperTest 是外接测试平台，MCP 既可承载任务提交和获准读取，也可在显式本地执行绑定后承载当前 Agent 的任务领域交互；该驱动下 Connector 不得另开影子 Harness。实现状态与真实宿主验收、生产部署分别记录。

**执行位置与驱动。** `execution_mode` 取 CLOUD / LOCAL，表示推进测试周期的 Agent / Harness 位置；`execution_driver` 取 PLATFORM_MANAGED / INTERACTIVE_MCP，表示该 Agent 的 Operational 驱动方式，二者均不是新增 HarnessMode：

| execution_mode | 既有 HarnessMode | execution_driver | 任务执行者 |
|---|---|---|---|
| CLOUD | SERVER_HOST | PLATFORM_MANAGED | 既有服务器受管 Harness，按原 Worker / UDS 路径执行 |
| LOCAL | LOCAL_CONNECTOR | PLATFORM_MANAGED | 保留 ADR-015 的节点受管本地 Provider 路径 |
| LOCAL | LOCAL_CONNECTOR | INTERACTIVE_MCP | 显式绑定当前本地 Agent 为该 Run 唯一执行 Worker / primary AgentSession；Connector 不另 spawn Harness |

CLOUD + INTERACTIVE_MCP 等未定义组合拒绝准入。新请求在 Run 创建前冻结 execution_mode / execution_driver、节点、来源与测试输入，写入独立 Operational 选择 / 提交回执并纳入幂等 digest；物理位置与驱动本身不加入 SourceSnapshot fingerprint / Gate hash。旧 payload 没有这些字段时仅按既有 HarnessMode 映射为 PLATFORM_MANAGED，保留旧 payload / Run / hash，不回填历史或隐式改成当前 Agent 执行。执行模式不是 Runner 地点、环境或信任等级：首版正式执行仍由平台可信 Runner 完成，按 ExecutionSpec 固定实际环境、源码和采集；LOCAL Agent 请求服务器 Runner 并不改变其 LOCAL 身份。本 ADR 不增加本地 Runner 授权，不将 Agent 自行运行的命令 / 日志升为正式 Evidence。

**交互连接与当前 Agent 的显式绑定。** `InteractiveClientSession` 仅表示一次 MCP 连接 / 有界 Operational 观察；MCP session ID、JSON-RPC request ID、聊天窗口名和模型自报 chat ID 不能自动作为 §23 的 AgentSession 或原生续接身份。`client_instance_id` 是经受控注册确认、本地持久的客户端安装身份，跨 stdio 进程和 MCP 重连保持稳定，不能信任模型自行指定或因重启换身份绕过去重。提交任务、读取结果都不自动接管会话；LOCAL + INTERACTIVE_MCP 经明确授权和可信宿主 adapter 核验后，允许把当前真实本地 Agent 登记为该 Run 的原主 AgentSession，保留一 Run 一 logical Worker / primary Session / node / workspace 规则。

宿主 adapter 必须独立核验真实 provider / native session continuation、稳定节点、受控 workspace / 固定源码与当前 Agent 生命周期，并将该身份绑定到本次 Run；不能只采信 Agent 填写的 session 字符串或把其他进程 / 新会话当成当前 Agent。不支持这些核验的宿主只能使用提交 / 读取或 CLOUD，拒绝 INTERACTIVE_MCP 本地执行绑定。平台不承诺接管任意桌面 Agent。既有 `UNIQUE(provider, provider_session_id)`、Binding.primary_agent_session_id 的唯一性和历史继续有效：首版一个可验证原生执行会话只绑定一个 Run；它仍可提交 / 读取其他获准 Run，但不能伪造复合 session ID 复用为另一个 Run 的 primary。需要替代或新的执行上下文时，必须由宿主真实建立可验证新 native session 并显式创建关联新 Run，Connector 不能静默 spawn 冒充当前会话或恢复。

新增记录关系如下；`0019_interactive_mcp` 建立下列前七类关系，`0020_interactive_tool_inbox` 增加工具 inbox 与短 grant 的精确设备 FK。独立主记录使用 UUIDv7，客户端注册使用 actor / client 复合主键，执行选择以 Run 为主键；actor、Project、grant、Run、Job、Binding 和 Session 引用以 FK / 受约束身份关系及 `ON DELETE RESTRICT` 保护历史，不能将关联 ID 塞入无校验 JSON。当前单 Operator 环境不因此宣称具备多租户隔离。

actor / client installation 的受控持久身份映射已由独立身份目录及复合 FK 实现，不能接受模型自行提供的字符串代替注册身份。`InteractiveClientSession` 是本地交互连接 / 有界观察概念，不是新建的 SQL 会话表、任务所有权或原生续接证明。这些均为 Operational 授权关系，不增加 Canonical 实体。

独立本地安装准备 CLI 在明确 Operator 授权下复用既有 Node / HarnessDeviceGrant、NodeProjectCapability 与 InteractiveActorIdentity / ClientRegistration / IntegrationGrant 的创建接口，不新增身份表、状态或凭据获取权限。安装实例的非秘密身份与已完成步骤保留于本机私有配置 / 准备记录；重启不轮换已有设备或覆写 grant，未确认结果不得以新身份自动重做。管理 key 只从 owned `0600` 文件或终端隐藏输入读取，不作为 MCP 参数或持久客户端凭据。安装完成不等于源码已接受、Run 已创建、原生会话已绑定或具备短执行授权；发行 tag / wheel hash 和 doctor 状态也不是 Canonical Testing State。

| Operational 记录 | 固定字段、关系与不可变约束 | 生命周期 / 权限边界 |
|---|---|---|
| `InteractiveActorIdentity` | 独立 `id`、唯一 actor_ref、registered_by、状态 / 审计时间及单调 row_version；注册身份固定 | 受控注册为 ACTIVE，仅可 REVOKED，历史不删除、不以重新激活绕过撤销 |
| `InteractiveClientRegistration` | `PRIMARY KEY(actor_identity_id, client_instance_id)`，actor FK、registered_by 与审计；安装身份固定 | 仅在已注册 ACTIVE actor 下建立 ACTIVE 注册，可 REVOKED；同客户端重连不生成新的安装身份 |
| `RunExecutionSelection` | 以 TestRun FK 为主键；execution_mode / execution_driver / HarnessMode / stable host、node FK 与 source transfer FK 固定 | 首次 Binding 前建立、append-only；CLOUD 仅 PLATFORM_MANAGED / SERVER_HOST，LOCAL 须与原已接受 RunHarnessSelection 的 node / source transfer 一致 |
| `InteractiveIntegrationGrant` | `id`、认证 `actor_identity_id`、稳定 `client_instance_id`、`project_id`、scope 子集、操作者 / policy version、`token_hash`、not_before / expires_at 与审计；actor / client 复合 FK、Project FK 与 scope 固定，扩权或轮换另建 grant | 受控签发为 ACTIVE，可 EXPIRED / REVOKED，终态不重开；拒绝授权不创建 PENDING grant。五个独立 scope 为 task:submit、run:read、evidence:read、report:read、run:execute；平台只存 token 哈希，Connector 本地私有文件保存秘密，不输出给模型或 stdio 调用 |
| `InteractiveSubmissionReceipt` | 原 grant FK、actor / client / Project、submission_key、normalization_version、独立计算的请求 input_digest，以及 input_manifest 中的固定快照 / 环境 / host 引用与独立 frozen_input_digest、mode / driver / node / source policy、授权策略和创建时间；`UNIQUE(actor_identity_id, client_instance_id, project_id, submission_key)` | 只保存不可变 ACCEPTED / REJECTED；不增加 UNKNOWN 业务状态。ACCEPTED 必须引用同 Project 的 TestRun 和首个 ADVANCE_RUN Job，追溯 Source / Policy / 模式驱动选择；REJECTED 无这些新 Run / Job 关联。授权轮换不解除旧幂等身份 |
| `InteractiveExecutionBinding` | UNIQUE FK → 既有 RunExecutionBinding，并 UNIQUE 引用其原 primary AgentSession；固定 Run / actor / client / node / provider / 真实 native session / workspace / INTERACTIVE_MCP driver、attach_key、versioned attach digest、首次 attached_epoch / 授权引用；`UNIQUE(actor_identity_id, client_instance_id, test_run_id, attach_key)` | 是对既有唯一 Binding 的交互执行登记，不是第二个 Run binding、AgentSession 或队列。初次 bind 原子建立所需原 Binding / Session / Placement 与该登记；已有登记不得换 actor / client / native session / workspace。活跃 epoch、lease、暂停 / 终态仍由原 Binding / Job / Session 管理，短执行 grant / 历史授权另有可审计账本，不能覆盖旧代次伪造续接 |
| `InteractiveExecutionGrant` | 原 InteractiveExecutionBinding / integration grant / Job / 精确 `device_grant_id` FK、epoch、派生 claim_identity、call_id、宿主 attachment / proof digest、token_hash、not_before / expires_at；同 attachment / call_id 唯一，身份与 scope 不可变 | ACTIVE → REVOKED / EXPIRED；期限受原 Job / integration / 精确 device 与短 TTL 约束。设备轮换撤销原 device 后，旧短 grant 不得借同节点的新 ACTIVE device 继续有效；旧 NULL device 历史不回填，执行验证失败关闭。token 明文不进入数据库、模型或 inbox |
| `InteractiveToolRequest` | 关联原 attachment / execution grant / integration grant / actor / client / Job / epoch / 派生 claim、tool_call_id、tool_name、原业务 idempotency_key、规范化 input_digest 与严格 typed arguments；`UNIQUE(interactive_binding_id, idempotency_key)` 和 `UNIQUE(interactive_binding_id, tool_call_id)` | 原 DurableJob 内的持久 typed transport inbox，不是第二 Task 队列。QUEUED → RUNNING / REJECTED / UNKNOWN；RUNNING → SUCCEEDED / REJECTED / UNKNOWN。原身份 / 参数 append-only，首次 claimed_at 固定，终态有 finished_at；UNKNOWN 仅可按精确原 RunToolCall 的 binding / key / tool / digest / 已记录 result 对账，不可重新执行。失效 server claim / epoch 不能发布执行结果 |

**提交与绑定原子性。** `hypertest_submit_task` 从已有 Project、批准的 credential-free origin、完整 SHA、原始 PRD / configuration、固定 Policy、受控环境，以及显式 mode / driver / node / source trust / transfer policy 构造既有 bootstrap + ADVANCE_RUN。LOCAL 必须引用此前 ACCEPTED 且当前 Project / node / origin / SHA / policy 一致的 SourceBundleTransfer，SOURCE 保持 §9.1 / §23.9 的独立可信采集和对象校验；插件不负责 Git 采集、dirty / untracked 自冻结、上传或节点授权。SERVER_HOST 沿用既有批准来源与 pinned checkout 规则。branch / MR 是参考信息，不代替完整 SHA。

新事务门面在一个 PostgreSQL 事务内复核当前 integration / Project / source / node / policy 权限、串行化 submission 唯一键、创建或合法复用不可变 Source / PolicySnapshot、冻结模式 / 驱动 / 节点 / SourceTransferSnapshot 关联、创建 TestRun 与首个 ADVANCE_RUN DurableJob，并写 ACCEPTED receipt 和配对 Audit / Outbox；提交后才返回 ACCEPTED。不能用既有先 bootstrap、再单独 POST Job 的两次事务冒称原子接受。外部镜像 / Artifact / source I/O 在聚合事务外执行，事务内重核当前授权和固定输入，不跨 HTTPS / Provider / Git / Docker I/O 持行锁；失败回滚全部新业务记录。需要持久拒绝时仅保存 REJECTED receipt / 安全原因与审计，不创建新 Run / Job / Selection / Snapshot，不删除此前已独立接受的来源或已有 Snapshot。

LOCAL + INTERACTIVE_MCP 的 ACCEPTED 不表示 Agent 已绑定或开始执行。初始 Job 的调度必须受显式 attach 准入约束，不能因 QUEUED 自动调用 ADR-015 的受管 Provider。平台 coordinator 按原规则持有并维护 DurableJob claim，承担领域事务、租约、工具准入和事实治理，不启动第二个智能 Worker / Harness；只有当前 Agent 的真实身份完成受控绑定、原 Binding / Session 状态允许且当前 Job claim 有效时，才授予其短期执行上下文。绑定成功也不自动创建测试 Execution，正式执行仍需原受控 request_execution 准入。

`hypertest_bind_execution` 要求独立 run:execute scope、匹配冻结的 LOCAL / INTERACTIVE_MCP / node / 预期 actor-client、当前有效设备身份与该节点的 Project Harness 能力、可信宿主核验，以及 attach_key / attach digest；integration grant 不代替现有设备 / 节点授权。初次 bind 在原规则下原子建立唯一 RunExecutionBinding / 主 AgentSession / Placement 及 InteractiveExecutionBinding，已真实存在的同一 native continuation 不得被替换。已绑定时，同 attach_key 同输入只查询 / 返回原登记，异输入冲突；不同 key 也不能创建第二绑定。attach digest 固定真实 native / workspace / node / mode / driver / source 等身份，短期 grant、claim 和当前可递增 epoch 不进入该固定 digest；首次 attached_epoch 保留历史，当前 epoch 从原 Binding 读取。actor / client / Run / native 等固定身份不因换 token 或 MCP 重连而改变。首次绑定前由客户端先持久 attach_key / digest / 意图，恢复继续使用原 attach 身份，不因恢复另造 key；失答后只以 `hypertest_get_execution` 查询原 attach 身份，不盲目重放 bind、换 key 或另建 Session。查询返回登记、当前原 Binding / claim 的受控状态，不因读取自动颁发或续约执行权；grant 颁发 / 续约必须有可信宿主证明、有效当前 claim / epoch 与显式受控执行意图。

**权限分层与 MCP 工具。** 提交 / 读取面保留 hypertest_submit_task、hypertest_get_submission、hypertest_get_progress、hypertest_list_evidence、hypertest_read_evidence、hypertest_list_reports、hypertest_read_report；增加 hypertest_bind_execution / hypertest_get_execution。提交及原键最小回执查询需要 task:submit，进度需要 run:read，Evidence 列表 / 内容需要 evidence:read，报告列表 / 内容需要 report:read，执行绑定 / 状态需要 run:execute。独立 scope 不相互推定，也不隐含设备配对、source-acquisition、issue-executor 或全局 Operator 权限。每次请求及响应交付重新核对当前 grant / actor / client / Project / Run 对象范围，撤权后不借旧回执、缓存、Artifact 地址或节点 cleanup 读取或执行。

绑定后的当前 Agent 可以经新认证 adapter 使用已有九个 TMP 工具：get_state、request_mission、complete_mission、request_execution、ask_user、evaluate_gate、submit_report、request_gitlab_issue、get_issue。它们保持 `hypertest.tmp/v1alpha2` / `run-persistent-harness/v1` 的既有 Schema、Proposal / Verifier、Mission / Attempt、预算和副作用规则，不直接公开内部 Worker relay。项目级 run:execute 不是无限任务权限；每次运行工具还须短期、限定原 Run / Binding / epoch / primary Session / node / client / call / Mission-Attempt（若适用）的执行上下文，以及平台当前有效 Job claim。客户端只得到派生 claim identity / 窄 capability，不得获得原始服务器 Job lease token、数据库写权、Runner 身份或 Operator 全局 key。读取范围仅覆盖该受控工作上下文，不能借任务工具读取其他 Run。Issue 继续按独立项目 / 负责人政策与已持久意图授权，UNKNOWN 只对账，不新增任意问题单写 API。

工具 HTTPS API 只鉴权、按严格业务 schema 规范化后持久入 InteractiveToolRequest，并有界等待 / 查询原结果；API 不执行 HarnessTools、Docker / Runner、源码核验命令或受管 Harness。原平台 coordinator 在同一个 Run 的既有 DurableJob claim 下领取该 inbox，重新核验当前 actor / client / scope、精确 device、短 grant、binding / epoch 与工具范围，再调用原 HarnessTools / Runner。固定 input_digest 与原 RunToolCall 采用同一 tool + 规范化 arguments 身份；写工具沿用原业务幂等键，读取请求有独立 transport 身份，不借 JSON-RPC session ID 当副作用幂等。每 Job 最多 256 个 QUEUED / RUNNING 请求，arguments / result 各有 4 MB 上限；不通过 RuntimeControl 增加任意工具代理，也不创建另一测试周期或租约所有者。

API 失联、请求取消或 ACK 丢失不撤回已被 Worker 接受的操作。已消费请求不再派发；失去原 Worker claim 的 RUNNING 结果不得发布，须保留 UNKNOWN 并核对原 RunToolCall / Execution / Issue。有效原 owner 仍可收集已接受 Runner 的事实；旧 Job 终结且其活跃执行已收口后，未消费 QUEUED 请求可拒绝，已消费 RUNNING 请求记录 UNKNOWN，原身份和历史保留。结果交付仍逐次鉴权，inbox 持有的授权引用与历史结果均不自动产生新的执行权。

**短期执行权、预算和恢复。** 单 Run 同时只存在一个有效 interactive owner。平台按当前数据库时间验证 grant / claim / epoch；可信宿主证明当前 Agent 的 native continuation 与本 Run attachment 活动，Connector 存活、整个聊天窗口在线或模型自报均不能续执行权。平台 coordinator 的真实服务心跳仅维护其 Job 所有权，不证明 Agent 在线或推进，也不能据此续发 Agent 执行 grant。执行授权有界到期，Run 内调用 / 正式执行沿原账本累计；只用可验证的本 Run attachment 活动计量，不把整个 chat 时间或自报 stopped / elapsed 冒称为旧 Bridge 的受控进程测量。恢复不重置累计预算，未知调用保守保留额度并先核对。

撤销或过期后立即 fence 平台写入、新 Mission / Runner / Issue 请求与迟到旧代次提交；Connector 可中断其实际管理的受控子进程，但不能声称能终止用户整个交互聊天或推理。已有正式 Runner 的结果按原 Execution / owner 授权对账，仍有效时先完成 / 收集或受控取消，再更换 epoch / Job claim；不重复启动正式执行。current Agent 关闭或不可验证活动后，本地任务推进停止，不能由仍存活的 Connector 假造 Agent 心跳或接管为受管 Harness。

MCP 重连先查询原 submission / attach / Binding 与未知 call，不自动恢复推理、消费两次答案、重放外部副作用或替换 Session。原身份与原租约仍有效时，只有可信宿主证明下的显式继续才可使用受控原执行上下文；过期 / 失联则按 §23.4 / §23.9 先 fence 旧 owner，核对原 native Session / workspace / source / 未决操作，再在同一 Binding 单调增加 epoch 并取得新 Job claim / grant。既有 WAITING_INPUT 与 CLOSED / FAILED / CANCELLED 状态机不变；报告接受仍按原规则关闭本 Run 的主 AgentSession / Binding 测试关联，不代表用户聊天已结束，也不授权清理其无关工作。原 native 身份 / workspace 不可恢复时明确失败、保留历史，替代身份必须是真实新 native 执行上下文与显式关联新 Run。get_execution、网络重连或重新 submit 均不能充当恢复授权。

恢复所需的平台工作区 / 固定源码文件核验同样在 Worker 边界执行。API 只鉴权并持久化限定原 Binding / epoch / source 关系的 typed 恢复请求、查询核验结果；不直接运行 Git、读取平台源码镜像或接受调用者自报 workspace_verified。工作区核验与授权复核不得跨外部 I/O 持行锁，应用恢复前须重新核对当前 grant / 设备 / 原身份与全部旧 Job / Runner 收口条件；受控核验也不授权通用 shell、任意路径或启动另一个 Harness。

**提交未知与受控结果读取。** 第一次写提交前，客户端先把稳定 client_instance_id、Project、submission_key、normalization version / input digest 和意图原子写入本地私有 journal，不含 token / Provider 对话 / 思维链。服务端独立规范化请求计算 input_digest，包含 mode / driver / node / source policy / transfer、PRD / config、有效 Policy hash 和环境请求；原 grant / token / MCP session 不改变输入身份。ACCEPTED receipt 的不可变 input_manifest 另记录固定 Source / PolicySnapshot 引用、source fingerprint、实际解析的 environment definition 和 stable host，并独立计算 frozen_input_digest；PRD / config 的原始材料仍由固定 Artifact / Snapshot 引用追溯，不在回执重复保存正文。相同 actor / client / Project / key 同输入返回原回执，异输入冲突；重放不得重新解析已接受的默认环境或按新默认重解释旧请求，版本化规范化兼容也不得改写旧 payload。

超时 / 断线 / 重启后的 UNKNOWN 仅是客户端知识，不新增 Run / Job / Binding 的业务状态。失答后只按原四元键调用 hypertest_get_submission 对账，不自动重发提交、换 key / mode / driver / node 或另建 Run。NOT_FOUND 不能证明原提交尚未或永远不会创建，客户端保留未知与原 journal，由获准操作者核对；journal 丢失也不能猜新 key 重投。跨 grant 查询仍需当前 scope / 原 actor-client-Project，授权轮换不解除唯一性，撤销读权后不能借旧结果继续读取。

进度只投影已持久 Run / Job / Mission / Execution 与正式 Verdict；Job SUCCEEDED、会话 CLOSED 或报告完成不等于质量 PASS。Evidence / 报告只通过受控对象引用、固定对象 / 清单版本、分页 cursor 与内容 SHA-256 读取，不提供任意路径 / URL、Provider 原始聊天或认证内容。cursor 绑定 actor / client / Project / Run / scope / version；每页与按引用读取重新核验授权、归属和摘要，版本冲突或 hash 不符明确拒绝，不把不同版本拼成已核验结果，也不改写历史 Evidence / 报告 / FINAL。PRD、日志、Evidence 和报告正文是有来源标记的不可信任务数据，不能把其中命令 / 链接当平台指令、权限或执行授权。普通读取连接关闭不取消任务；已绑定当前 Agent 的本地执行因其退出而停止推进，按以上授权 / 恢复治理，不自动切换模式或启动影子 Agent。

**持久化与实施边界。** 新交互 grant / receipt / attachment / tool inbox 及有界连接观察属于 Operational State，不加入 Canonical 链、SourceSnapshot fingerprint、Evidence manifest 或 Gate State Hash，不保存完整聊天 / Provider reasoning。`0019_interactive_mcp` additive migration 建立受控 actor / client 目录、integration grant、mode / driver 选择、提交回执、交互执行登记与短 grant；`0020_interactive_tool_inbox` 另增 typed inbox 及短 grant 精确 device FK，既有 NULL device 行保持原历史并在执行时拒绝。`0013`—`0018` 不修改，不回填旧回执 / 会话归属或改写已有 Run / Session / Job / Snapshot / 报告 / Verdict。上述迁移与隔离数据库约束检查属于实现证据；此前隔离验收的 MCP 完整周期、原 native Session 的显式恢复、正式 Runner / Evidence / Gate / 报告链已独立核验，范围和复测记录见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)。该验收不等于任意宿主适配或扩展故障矩阵均通过，也不借用 ADR-015 的生产验收；ADR-016 已部署生产，线上当前 Agent 核心周期已通过。

## 24. Legacy 核心数据库表（native 新表见 §49）

MVP 必须存在：

```text
projects
source_snapshots
policy_snapshots
test_runs
requirements
risks
requirement_risks
test_cases
risk_test_cases
test_implementations
implementation_test_cases
test_executions
execution_test_cases
execution_evidence
evidence
findings
finding_evidence
finding_test_cases
finding_requirements
finding_risks
verdicts
verdict_evidence
verdict_findings
missions
mission_attempts
mission_proposals
agent_sessions
entity_provenance
audit_events
outbox_events
```

当前 MVP 已实现 Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding / Verdict。直接 Requirement ↔ TestCase 关系（后续 `test_case_requirements`）和独立 entity_provenance 投影仍为扩展；当前 provenance 通过 Canonical created_by_ref / reported_by_ref 与 MissionProposal 的 mission_id、attempt_id、accepted_entity_id 保留。

`0007_durable_jobs` 在 `0006_immutable_contracts` 后增加 Operational 表 `durable_jobs` 与 `worker_heartbeats`、FK、幂等 / 活跃请求唯一索引和请求 / 历史保护 Trigger；不重写 Canonical Entity 或 Vendor Session。

`0010_mission_activity` 交付时在 `0009_mission_inputs` 之上增加独立的有界活动表，不回填或重写历史行。`0009` 保留 `0008_job_ownership` 引入的 Attempt / Execution 显式归属关系，并增加持久问题、回答历史、原任务等待预约及 AgentSession 等待状态。已有归属或人工输入历史时禁止降级丢失关系；活动裁剪不构成这些历史的删除许可。

当前代码另有 §9 的 `0011_execution_environments` 与 `0012_api_environment_v2`。`0013_run_bindings` 新增 `run_execution_bindings` / `run_input_requests`；`0014_harness_operations` 新增 §23.7 的 `run_harness_states`、`run_tool_calls`、`run_reports`、`runtime_control_requests`、`gitlab_issue_operations` 及状态 / 关系保护。以上 v0.3 表清单和 SQL 示例保留历史基线；ADR-013 历史切换时 schema 为 `0014_harness_operations`；ADR-014 不增加迁移。ADR-015 历史生产为 `0018_harness_selection`，发布与验收见[历史生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)；当前生产为 `0020_interactive_tool_inbox`，见[ADR-016 生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)。

ADR-015 的 §23.9 已新增 `0015`—`0018` Operational schema：harness_nodes、harness_device_grants、node_project_capabilities、run_harness_placements、harness_dispatch_grants、connector_requests、source_acquisition_requests、source_bundle_transfers、source_upload_grants、source_transfer_snapshots、gitlab_issue_operation_executors、run_harness_selections。隔离迁移 / 回归与正式生产向前升级已分别记录，该次历史生产 head 为 `0018_harness_selection`；`0013` / `0014` 历史迁移和既有 Canonical hash 保留。

ADR-016 的 §23.10 已由 `0019_interactive_mcp` / `0020_interactive_tool_inbox` 增加 interactive_actor_identities、interactive_client_registrations、interactive_integration_grants、run_execution_selections、interactive_submission_receipts、interactive_execution_bindings、interactive_execution_grants、interactive_tool_requests 及相关 FK / 唯一 / scope / append-only / 当前 claim 保护。空库向前迁移、隔离约束回归与 [当前真实 Agent 完整周期](../ADR016_ACCEPTANCE.md) 已验证；本次实现已部署生产，线上当前 Agent 核心周期已通过；生产 head 向前升至 `0020_interactive_tool_inbox`，以上 ADR-015 的历史发布身份与验收结论保留，见[当前生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)。

---

## 25. 核心 SQL 约束示例

### Requirement

```sql
CREATE TABLE requirements (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    project_id uuid NOT NULL REFERENCES projects(id),
    source_snapshot_id uuid NOT NULL REFERENCES source_snapshots(id),
    logical_key varchar(255),
    title varchar(512) NOT NULL,
    description text NOT NULL,
    requirement_type varchar(32) NOT NULL,
    priority varchar(16) NOT NULL,
    source_type varchar(32) NOT NULL,
    source_ref text,
    source_fingerprint char(64) NOT NULL,
    confidence numeric(4,3),
    lifecycle_status varchar(32) NOT NULL,
    supersedes_id uuid REFERENCES requirements(id),
    created_by_type varchar(32) NOT NULL,
    created_by_ref text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(project_id, key),
    UNIQUE(source_snapshot_id, source_fingerprint),
    CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
```

### Risk

```sql
CREATE TABLE risks (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    project_id uuid NOT NULL REFERENCES projects(id),
    source_snapshot_id uuid NOT NULL REFERENCES source_snapshots(id),
    risk_fingerprint char(64) NOT NULL,
    category varchar(32) NOT NULL,
    title varchar(512) NOT NULL,
    description text NOT NULL,
    severity varchar(16) NOT NULL,
    probability varchar(16) NOT NULL,
    rationale text,
    confidence numeric(4,3),
    lifecycle_status varchar(32) NOT NULL,
    disposition text,
    created_by_type varchar(32) NOT NULL,
    created_by_ref text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(project_id, key),
    UNIQUE(source_snapshot_id, risk_fingerprint)
);
```

### TestCase

```sql
CREATE TABLE test_cases (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    project_id uuid NOT NULL REFERENCES projects(id),
    source_snapshot_id uuid NOT NULL REFERENCES source_snapshots(id),
    case_fingerprint varchar(64) NOT NULL,
    title varchar(512) NOT NULL,
    description text NOT NULL,
    test_type varchar(32) NOT NULL,
    priority varchar(16) NOT NULL,
    preconditions json NOT NULL DEFAULT '[]',
    expected_result text NOT NULL,
    lifecycle_status varchar(32) NOT NULL,
    confidence numeric(4,3),
    derived_from_id uuid REFERENCES test_cases(id),
    created_by_type varchar(32) NOT NULL,
    created_by_ref text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(project_id, key),
    UNIQUE(source_snapshot_id, case_fingerprint),
    CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CHECK(test_type IN ('FUNCTIONAL', 'BOUNDARY', 'NEGATIVE', 'FAILURE', 'CONCURRENCY',
                      'CONSISTENCY', 'COMPATIBILITY', 'SECURITY', 'PERFORMANCE',
                      'RELIABILITY', 'UPGRADE', 'DATA', 'RECOVERY')),
    CHECK(priority IN ('P0', 'P1', 'P2', 'P3')),
    CHECK(lifecycle_status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'DEPRECATED'))
);

CREATE TABLE risk_test_cases (
    risk_id uuid NOT NULL REFERENCES risks(id) ON DELETE RESTRICT,
    test_case_id uuid NOT NULL REFERENCES test_cases(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    PRIMARY KEY(risk_id, test_case_id)
);
```

`0004_test_design` 在 `0003_risk_planner` 后创建以上两表，并把 MissionProposal 类型约束扩展至 TEST_CASE。从空库升级依次执行 0001 → 0002 → 0003 → 0004；新表不重写历史 Requirement / Risk。存在 TestCase 行或 TEST_CASE Proposal 时降级失败，避免破坏已接受的历史。

### TestExecution

```sql
CREATE TABLE test_executions (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    test_run_id uuid NOT NULL REFERENCES test_runs(id),
    mission_id uuid REFERENCES missions(id),
    durable_job_id uuid REFERENCES durable_jobs(id) ON DELETE RESTRICT,
    retry_of_execution_id uuid REFERENCES test_executions(id),
    idempotency_key varchar(512) NOT NULL,
    purpose varchar(32) NOT NULL,
    runner_backend varchar(64) NOT NULL,
    environment_id varchar(255) NOT NULL,
    environment_fingerprint char(64) NOT NULL,
    source_commit varchar(64) NOT NULL,
    execution_spec_sha256 char(64) NOT NULL,
    spec json NOT NULL,
    status varchar(32) NOT NULL,
    outcome varchar(32),
    queued_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    exit_code integer,
    error_code varchar(64),
    error_message text,
    runner_instance text,
    created_at timestamptz NOT NULL,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(test_run_id, key),
    UNIQUE(test_run_id, idempotency_key)
);
```

### Evidence

```sql
CREATE TABLE evidence (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    test_run_id uuid NOT NULL REFERENCES test_runs(id),
    execution_id uuid REFERENCES test_executions(id),
    evidence_type varchar(64) NOT NULL,
    trust_level varchar(32) NOT NULL,
    artifact_uri text,
    content_type varchar(255),
    sha256 char(64) NOT NULL,
    size_bytes bigint,
    inline_summary text,
    collector varchar(128) NOT NULL,
    source varchar(128) NOT NULL,
    status varchar(32) NOT NULL,
    created_at timestamptz NOT NULL,
    verified_at timestamptz,
    rejection_reason text,
    UNIQUE(test_run_id, key),
    UNIQUE(test_run_id, sha256, evidence_type)
);
```

### Mission

```sql
CREATE TABLE missions (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    test_run_id uuid NOT NULL REFERENCES test_runs(id),
    mission_type varchar(64) NOT NULL,
    priority varchar(16) NOT NULL,
    objective text NOT NULL,
    protocol_version varchar(32) NOT NULL,
    spec jsonb NOT NULL,
    spec_sha256 char(64) NOT NULL,
    status varchar(32) NOT NULL,
    idempotency_key varchar(512) NOT NULL,
    current_attempt_no integer NOT NULL DEFAULT 0,
    created_by varchar(128) NOT NULL,
    created_at timestamptz NOT NULL,
    ready_at timestamptz,
    dispatched_at timestamptz,
    completed_at timestamptz,
    cancelled_at timestamptz,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(test_run_id, key),
    UNIQUE(test_run_id, idempotency_key)
);
```

---

## 26. 索引与 FK 策略

除 Unique Index 外，至少为 project_id、source_snapshot_id、test_run_id、mission_id、status、outcome、category、severity、classification、evidence_type 等高频查询列建立索引。

Canonical Entity FK 默认 `ON DELETE RESTRICT`，禁止因为删除父对象而级联删除整条 Evidence Chain。Join Table 可以使用 CASCADE 删除 link，但 Canonical Entity 本身通常不 Hard Delete。

---

## 27. Derived State 与 Coverage

以下原则上不直接存 Canonical Entity：requirement_coverage、risk_coverage、automation_coverage、execution_coverage、evidence_coverage、latest_result。

需要性能时建立 Read Model / Materialized View，例如 `coverage_projection`。

v0.2 的 Risk identification coverage：

```text
具有至少一个非 OBSOLETE Risk 关联的 ACTIVE Requirements / 全部 ACTIVE Requirements
```

Requirement 无 Risk 时标记 gap，不能视为已识别。没有 ACTIVE Requirement 时比例为 `null`（未知），不是 100%。

v0.2 的 Risk test coverage 由独立 `RiskCoverageEvaluator` 从关系计算，规则版本为 `risk-design-baseline/v1`：

| Risk category | Required test design dimensions |
|---|---|
| FUNCTIONAL、CONSISTENCY、COMPATIBILITY、OBSERVABILITY、UPGRADE、DATA | FUNCTIONAL |
| BOUNDARY | FUNCTIONAL + BOUNDARY |
| FAILURE | FUNCTIONAL + FAILURE |
| CONCURRENCY | FUNCTIONAL + CONCURRENCY |
| SECURITY | FUNCTIONAL + SECURITY |
| PERFORMANCE | FUNCTIONAL + PERFORMANCE |
| RELIABILITY | FUNCTIONAL + RECOVERY |

每个 Risk 的 covered dimensions 来自同一 Project / SourceSnapshot 下通过 `risk_test_cases` 关联的 ACTIVE TestCases；只有 required dimensions 全部满足才算 Complete，否则为 Gap。DRAFT / SUPERSEDED / DEPRECATED 用例不贡献覆盖，OBSOLETE Risk 不参与评估。

```text
Risk test coverage = Complete 的非 OBSOLETE Risks / 全部非 OBSOLETE Risks
```

没有 eligible Risk 时比例为 `null`，不是 100%。API 返回每个 Risk 的 required / covered / missing dimensions；Planner 与 Web 共用此评估结果，禁止由 Agent 自述覆盖。

此规则是可替换的确定性基线，不是永久的“存在一个用例即覆盖”模型。当前 PolicySnapshot 的 `compiled_policy.coverage` 已支持声明设计维度：

```json
{
  "coverage": {
    "version": "risk-design-policy/v1",
    "default_dimensions": ["FUNCTIONAL", "FAILURE"],
    "by_category": {
      "CONCURRENCY": ["CONCURRENCY", "BOUNDARY"],
      "SECURITY": ["SECURITY", "BOUNDARY"]
    }
  }
}
```

`default_dimensions` 对所有 Risk 生效；`by_category` 替换该类别的专用维度，未声明类别保留上表的专用维度。FUNCTIONAL 始终必需，包括显式空数组；空数组不能豁免全部设计覆盖。只接受受支持的 RiskCategory / TestCaseType、规则版本与字段；未知规则、重复维度及错误结构在 Policy 编译时拒绝。

未配置 coverage 或解析后与基线相同的 Policy 使用 `risk-design-baseline/v1`；其他规则使用 `risk-design-policy/v1`。Coverage API 返回实际 `rule_version` 与规范化 effective coverage rules 的 `effective_policy_hash`。等效维度顺序不改变 Hash。Planner、Verifier、Gate 和 Web 共用当前 TestRun 固定的 PolicySnapshot，不能使用项目后来创建的新 Policy 重解释旧 Run。

DESIGN_TESTS 的 Mission idempotency identity 与 acceptance criteria 包含生效的 coverage Hash 和规则版本；Verifier 拒绝与当前固定 Policy 不符的 Mission 约束。规则仍由专用确定性评估组件执行，不把 Planner 改造成通用 LLM Agent。更丰富的语义覆盖仍可通过该组件扩展。

v0.3 已实现的 Planner 在 Requirement 和 Risk 缺口满足后，对剩余维度创建 DESIGN_TESTS Mission。全部 Risk 达到基线表示测试设计覆盖完成；当前完整 MVP 继续创建 IMPLEMENT_TESTS，随后返回 EXECUTION_REQUIRED / EXECUTION_IN_PROGRESS，失败时创建 DIAGNOSE_FAILURE，最后返回 VERDICT_REQUIRED。早期切片的 TEST_DESIGN_COVERAGE_COMPLETE 是设计阶段边界，不是 TestRun 的 PASS / FINAL Verdict。

v0.4 保留这些确定性依赖 / Coverage 判定作为持久 Harness 的阶段准入和完成检查，不再以逐 Mission 新建会话作为推进机制。Agent 可以在同一主会话请求下一 typed 阶段；缺口、目标和验收仍由当前固定 Snapshot / Policy 计算，不能由 Agent 自述覆盖或绕过 Verifier。

Risk Coverage 分层：

```text
DESIGN_COVERED
IMPLEMENTED
EXECUTED
EVIDENCED
```

TestCase 不存 latest_result，通过 `execution_test_cases` 查询 current SourceSnapshot 下 latest OFFICIAL execution。

---

## 28. Evidence Graph

Evidence 通过 Execution → Evidence、Evidence → Finding、Evidence → Verdict 形成图。长期可增加 `evidence_relations`，支持 DERIVED_FROM、CORROBORATES、CONTRADICTS。

MVP 不需要 Graph DB，PostgreSQL + Join Tables 足够。

---

## 29. State Snapshot Hash

每次 FINAL Verdict 必须记录 `state_snapshot_hash`。

Hash 基于 Requirements、Risks、TestCases、Executions、Evidence、Findings、PolicySnapshot 的 Canonical Serialization 计算。

当前 Hash 还包含 `gate_rule_version = canonical-gate/v1`、重新校验后的 Artifact integrity 和本次计算的 decision。Gate 在持有共享 SourceSnapshot 锁期间读取覆盖、生成决策并序列化状态，避免其他 Run 的 Canonical 提交插入决策与 Hash 之间。Verdict 重用另行匹配 decision 和 evidence_manifest_sha256；新 Hash 语义会为旧 Hash 的重新评估追加 Verdict，不改写历史 FINAL 记录，也不宣称 Gate 规则版本已升级。

Canonical Serialization 必须稳定字段顺序和关系顺序，并排除不影响语义的 volatile timestamp。

目标：未来能够证明 Verdict 是基于哪一个 Testing State 得出的。

---

## 30. Entity Provenance

旧 Mission profile 中 Agent 创建的 Canonical Entity 必须追溯到 Mission、MissionAttempt、MissionProposal。新 native 接受的 Plan/Case 按 §49 追溯原始 Proposal、Operator、Contributor 与 operation；不为满足旧 FK 而伪造 Mission / Attempt。

建议 `entity_provenance`：

```text
entity_type
entity_id
mission_id
attempt_id
proposal_id
created_at
```

人工修改同样必须 Audit，记录 actor、before_hash、after_hash、reason。

---

## 31. Audit 与 Outbox

`audit_events` 至少保存 project_id、test_run_id、actor_type、actor_ref、action、entity_type、entity_id、before_state/hash、after_state/hash、metadata、created_at。

Canonical Transaction 内同步写 `outbox_events`，例如 requirement.accepted、risk.accepted、test_case.accepted、mission.completed、execution.completed、evidence.verified、finding.confirmed、verdict.finalized。

Canonical Entity Change + Audit Event + Outbox Event + Proposal Acceptance 必须在同一事务；任一步失败全部回滚。

Mission 控制决策同样使用事务性配对事件：创建记录 `mission.created`；接受 required outputs 时记录 `mission.completed`，与 Canonical Entity / Proposal / Attempt 状态一并提交。成功事件按 Mission 幂等；`mission.dispatched`、`mission.started`、`mission.result_rejected`、`mission.attempt_failed`、`mission.timed_out`、`mission.interrupted` 按 Attempt 身份幂等。取消、重试分别记录 `mission.cancelled`、`mission.retry_requested`，失联恢复保留受控生命周期事件。事件保存领域身份、状态和原因，不复制 provider logs、raw result payload 或 Agent reasoning；Provider 运行元数据继续属于 AgentSession / MissionAttempt。

---

## 32. Finding Confirmation Rule

Agent 可以 report FindingProposal，但正式 `Finding.status = CONFIRMED` 至少需要 Verified Evidence。

若 classification = PRODUCT_DEFECT，至少需要一个 Trust Level 属于 RUNNER / SYSTEM / EXTERNAL_VERIFIED 的 Evidence；禁止仅凭 AGENT_REPORTED 确认 Product Defect。

BUGate Policy 可进一步要求 reproduction。

---

## 33. Verdict Finalization Rule

FINAL Verdict 至少需要 PolicySnapshot、StateSnapshotHash、Reason。

旧 Verdict 的 PASS / RELEASE_READY 必须满足其冻结 Policy 与 canonical-gate/v1 的可信 OFFICIAL Evidence 规则（当前 Gate 不实现 waiver）。新 NativeConclusion 首版仅 UNKNOWN / BLOCKED；不利用本条生成 native PASS 或将材料冒充旧 Evidence。

---

## 34. Mission Completion / Retry Rule

Mission SUBMITTED 不等于 COMPLETED。只有 Verifier 接受 required outputs 才进入 COMPLETED。

若 Result Schema invalid、Policy violation、required outputs incomplete：Attempt = REJECTED，Mission = RETRYING，新建 Attempt N+1；禁止覆盖历史 Attempt Result。

v0.4 的可恢复拒绝 / retry 仍使用原 RunExecutionBinding 和主 AgentSession，不因新 Attempt 重建 Provider thread。主 Session 的不可恢复失败与普通 Proposal 拒绝是不同事件；恢复、工作副本保留和终结按 §23.4 处理。Mission COMPLETED 也不终结该 Run 的主 Session。

---

## 35. Execution Retry Rule

Execution 不 Retry-in-place。ERROR / TIMED_OUT 后重跑必须创建新 Execution，通过 `retry_of_execution_id` 建立关联。

---

## 36. Evidence Rejection Rule

Evidence 因 hash mismatch、artifact missing、source untrusted、collector failure 等校验失败进入 REJECTED，禁止删除。

---

## 37. Cross-Snapshot Reuse

Requirement / Risk / TestCase 在不同 SourceSnapshot 之间不直接复用同一行。

原因：历史事实必须保持快照语义。通过 logical_key、supersedes、derived_from 建立 lineage。

> **Snapshot-scoped Canonical Entity + Cross-snapshot Lineage**

TestCase 复用采用 clone / derive 到新 Snapshot，并记录 `derived_from_id`。

---

## 38. Legacy 正式 Verdict 的最小数据闭环（native 材料闭环见 §49）

一个 TestRun 要产生有效最终 Verdict，最小链路：

```text
SourceSnapshot
     │
     ▼
Requirement
     │
     ▼
Risk
     │
     ▼
TestCase
     │
     ▼
TestImplementation
     │
     ▼
Official Execution
     │
     ▼
Verified Evidence
     │
     ▼
Verdict
```

Finding 只有出现异常时才必须存在。

正常 PASS 链路：

```text
REQ-1 → RISK-1 → TC-1 → IMP-1 → EX-1 OFFICIAL → EV-1 VERIFIED → PASS
```

Defect 链路：

```text
REQ-1 → RISK-2 → TC-3 → EX-7 FAIL → EV-20/EV-21
     → FIND-4 PRODUCT_DEFECT → RELEASE_BLOCKED
```

---

## 39. Legacy 状态所有权（native 所有权见 §49.3–49.4）

| 对象 | 状态所有者 |
|---|---|
| Requirement | HyperTest State Engine |
| Risk | HyperTest State Engine |
| TestCase | HyperTest State Engine |
| Mission | HyperTest Mission Runtime |
| MissionAttempt | Agent Gateway |
| Execution | Runner Controller |
| Evidence | Evidence Collector / Verifier |
| Finding | HyperTest Finding Service |
| Verdict | Gate Engine |
| RunExecutionBinding（v0.4 目标） | HyperTest Task Runtime；保持唯一逻辑 owner，Bridge 不拥有 Canonical State |
| 持久主 AgentSession（v0.4 目标） | HyperTest Task Runtime / Agent Gateway 管理身份及生命周期，绑定的 Harness 节点托管原生运行时 |
| HarnessNode / DeviceGrant / Capability / Selection / Placement / DispatchGrant / ConnectorRequest（ADR-015 已实现） | HyperTest 受控设备与任务服务；Connector 不拥有 Canonical State 或自续授权 |
| SourceAcquisitionRequest / SourceBundleTransfer / SourceUploadGrant / SourceTransferSnapshot（ADR-015 已实现） | 受控 source-acquisition adapter 采集，HyperTest 接收器独立校验并冻结来源关联 |
| GitLabIssueOperationExecutor（ADR-015 已实现） | HyperTest 固定意图与 executor，受控集成持凭据执行，平台核验远端结果 |
| InteractiveIntegrationGrant / InteractiveSubmissionReceipt（ADR-016） | HyperTest scoped integration / submission 服务管理独立授权与原子回执；提交 / 读取不自动取得执行权 |
| InteractiveExecutionBinding（ADR-016） | HyperTest 核验当前 Agent 的真实宿主身份，将其登记为既有 RunExecutionBinding 的唯一交互执行者；不新建第二绑定或独立调度队列 |
| InteractiveExecutionGrant / InteractiveToolRequest（ADR-016） | 平台签发 / 撤销精确 device 的短执行授权；API 仅持久化 typed inbox，原 Job 的 Worker 在有效 claim / epoch 下执行并记录结果，不向 API 转移 Runner 权限 |
| InteractiveClientSession（ADR-016 连接概念） | 仅交互连接 / 有界 Operational 观察身份，不对应新增 SQL 会话表；显式绑定须另核验真实 native Session，不将 MCP session ID 当 AgentSession 或写权 |

Agent 不直接拥有任何 Canonical Lifecycle。

---

## 40. Legacy 写权限矩阵（native 权限见 §49.3）

| Actor | Requirement | Risk | TestCase | Execution | Evidence | Finding | Verdict |
|---|---|---|---|---|---|---|---|
| 平台主 Harness Agent（TMP 运行 profile） | Proposal | Proposal | Proposal | Request | Read | Proposal | No |
| 未绑定交互 Agent（ADR-016 MCP profile） | No | No | No | No | Scoped Read | No | No |
| 已显式绑定的当前 LOCAL Agent（ADR-016 INTERACTIVE_MCP + TMP 执行上下文） | Proposal | Proposal | Proposal | Request | Scoped Read | Proposal | No |
| Runner | No | No | No | Write | Write | No | No |
| Verifier | Accept | Accept | Accept | Read | Verify | Validate | No |
| Gate | Read | Read | Read | Read | Read | Read | Write |
| User | Controlled | Controlled | Controlled | Trigger | Read | Manage | Override by Policy |

上表区分入口、绑定和当前授权，而不是给同一模型永久全局角色。未绑定 Agent 的结果读取分别需要 evidence:read / report:read / run:read；hypertest_submit_task 经事务准入创建 Run / 初始 Job，不自动授予执行权。当前 LOCAL Agent 经 run:execute 和可信宿主核验完成显式绑定后，仍须每次具备原 Binding / Session / 当前 epoch / 有效 Job claim / Mission-Attempt 的短执行上下文，才可使用既有 TMP 工具；单独 integration grant 不足以执行。Proposal 仍由 Verifier 接受，Execution / Evidence 仍由平台可信 Runner 产生，当前 Agent 不直接写 Canonical State。

---

## 41. Schema Migration Policy

使用 Alembic。

规则：No destructive migration without backfill；No enum semantic changes in-place；No dropping canonical column in same release；Deprecate → migrate → remove。

v1 初期不使用 PostgreSQL native ENUM，使用 varchar + application enum + CHECK constraint，以便协议快速演进。

v0.4 的 Binding / Session 生命周期、唯一 / FK、epoch fencing 与 typed tools 需要 additive migration、版本化契约和成套验收。旧 Run / Session / Attempt / Job 的身份、原生引用与历史解释不因目标规则而回填或合并；新的绑定不能用改写旧结果代替显式恢复或新测试轮次。

v0.5 / ADR-015 已通过 `0015`—`0018` 增加 §23.9 的 Operational schema、版本协商与隔离约束验收；真实集成和生产部署继续分别登记。旧 SERVER_HOST Run 不补造节点配对、source receipt、Placement 或 issue executor；其现有授权 / 历史解释保留，不能借兼容缺省把它迁入 LOCAL_CONNECTOR。新增 scope / 关系也不改变既有 Snapshot / Policy / Mission / ExecutionSpec / FINAL 内容或 hash。

v0.6 / ADR-016 通过 `0019` / `0020` 实现 §23.10 Operational 身份 / grant / receipt / interactive attachment / typed inbox、模式驱动选择、唯一键 / 同 Project FK / append-only 历史约束及原子提交 / 绑定门面。迁移与隔离测试验证提交 / attach 的持久身份、同键幂等、失答先查、原生会话唯一性、短执行授权 / fencing / 预算及读取完整性；此前隔离当前 Agent 完整周期的独立验收见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)；生产发布与线上当前 Agent 核心周期已通过，见[生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)。`0013`—`0018` 保持原样，不回填历史，不改 TestRun / DurableJob / AgentSession / Binding / Verdict 状态枚举。

---

## 42. MVP 必须实现的约束

第一版不能省略：

```text
UUID PK
FK
Unique Fingerprint
Mission Idempotency
Execution Idempotency
row_version
Evidence sha256
Proposal separation
Audit Event
Outbox Event
Official vs Exploratory execution distinction
```

这些不是企业增强能力，而是 HyperTest 架构成立的基础。

第一阶段可暂缓 Evidence signing、Graph DB、Kafka、Full Event Sourcing、Global Ontology、Cross-project Semantic Deduplication、Temporal DB、Dedicated Lineage Service。

---

## 43. Persistence Decision

HyperTest v1 使用：

```text
Canonical Relational State
+
Audit Log
+
Transactional Outbox
```

不采用 Full Event Sourcing 作为主存储；不采用 Graph DB 作为主数据库。

PostgreSQL + Join Tables 足以支持 MVP 和中期规模。

---

## 44. 推荐代码模块

```text
hypertest/domain/
├── project/
├── snapshot/
├── requirement/
├── risk/
├── testcase/
├── implementation/
├── execution/
├── evidence/
├── finding/
├── verdict/
└── mission/

hypertest/infrastructure/
├── db/
├── outbox/
├── artifact/
└── audit/
```

领域层建议定义 RequirementRepository、RiskRepository、TestCaseRepository、ExecutionRepository、EvidenceRepository、FindingRepository、VerdictRepository、MissionRepository，并通过 Domain Service 控制事务、Optimistic Lock、Audit、Outbox。

禁止创建 `HugeHyperTestService`。

---

## 45. Canonical State 最终定义

HyperTest Canonical Testing State 包括：

```text
SourceSnapshot
+
Accepted Requirements
+
Accepted Risks
+
Accepted TestCases
+
Accepted TestImplementations
+
Trusted TestExecutions
+
Verified Evidence
+
Confirmed / Active Findings
+
Final Verdict History
```

ADR-017 新 profile 另包含接受的 NativePlan/Case 管理资产、其操作 / 贡献归属、已知证据缺口与 append-only NativeConclusion；未验证执行材料虽持久保存，不能按上述 Trusted TestExecution / Verified Evidence 解释。

不包含：Agent Chain-of-Thought、Agent Conversation、Temporary Workspace、Unaccepted Proposal、Provider-specific Event。

---

## 46. 核心数据不变量

1. 任何 Canonical Domain Object 必须属于明确 Project。
2. Requirement / Risk / TestCase 必须绑定 SourceSnapshot。
3. Historical Snapshot Semantic 不允许被后续版本覆盖。
4. Agent 不能直接写 Canonical State。
5. Execution 结束后不可修改执行输入。
6. Evidence Content Immutable。
7. FINAL Verdict Append-only。
8. 所有正式质量结论必须可沿关系追溯至 Evidence。
9. Coverage 是 Derived State，不是 Agent Claim。
10. Mission Retry 不覆盖历史 Attempt。

v0.4 新增运行归属不变量（本分支实现，验收范围见 §1.1）：

11. 一个稳定 SUT 对应一个 Project；feat / MR 完整 SHA 的一轮固定输入测试由 TestRun 表达，SHA 不是禁止重测的唯一任务键。
12. 每个受控 Run 只有一个稳定 RunExecutionBinding / logical_worker_id 和一个主 AgentSession；不同 Run 可并发，同一 Run 不 fanout 到多个逻辑 Worker。
13. 正常 Mission 完成、WAITING_INPUT 和可恢复 Attempt 拒绝不关闭 / 替换主 Session；释放进程 lease 不解除任务绑定。
14. 只有原 Binding / 原生 Session / workspace 的显式 fenced recovery 能接续所有权；旧 epoch / token 不能提交，不可恢复时明确失败，替代会话属于新 Run。
15. Harness 通过 typed Proposal / Request 自驱；正式事实仍来自可信 Runner，质量决策仍来自 deterministic Gate。报告、GitLab Issue、Binding / Session / Worker 状态不代替 Verdict。

v0.5 / ADR-015 新增不变量（已部署生产、隔离核心验收通过，线上核心已验，扩展矩阵按记录继续验收）：

16. SERVER_HOST / LOCAL_CONNECTOR 在首绑定前显式选择，模式、节点、主 Session / workspace 不因离线或后端切换重绑；本地凭据与设备配对授权分别治理。
17. 源码在 Snapshot 冻结前经过可信来源采集与平台独立 Git 对象链校验；包 Hash 或 Agent 自报不证明 origin / commit 来源，Runner 再独立校验正式输入。
18. 问题单先持久化获准意图和唯一 executor，UNKNOWN 只查询对账，后端、节点或新 epoch 不绕过同 Finding 去重。
19. 连接 presence、短执行 grant 与服务器 Job / Runner lease 分开；重连不恢复执行权，显式 fenced recovery 只续原绑定，已有有效 Runner 仍可按原 Execution 完成。

v0.6 / ADR-016 新增不变量（Implemented / Isolated Tests Verified；真实当前 Agent 已验收 / 已部署生产，线上当前 Agent 核心周期已通过，2026-10-20）：

20. execution_mode=CLOUD / LOCAL 固定 Agent 位置，execution_driver 固定受管或当前 Agent 驱动；不新增 HarnessMode，不改变正式 Runner 信任。
21. 普通 MCP 连接不自动成为主会话；LOCAL / INTERACTIVE_MCP 只经可信宿主核验显式登记当前原生 Agent 为既有唯一 Binding / Session 的执行者，不启动影子 Harness，同一真实 native 执行会话只绑定一个 Run。
22. ACCEPTED receipt、冻结输入 / mode / driver / node、TestRun、首个 ADVANCE_RUN Job 与 Audit / Outbox 同事务提交；INTERACTIVE_MCP 未显式绑定时不能因初始 Job 入队自动启动受管 Provider。
23. submission_key / attach_key 与 digest 在首次写入前持久；失答 UNKNOWN 仅为客户端知识，先按原身份查询，NOT_FOUND 不触发自动重提或新 Session / Run。
24. 项目 run:execute 和每次当前 Run / Session / epoch / claim 的短执行上下文分层验证；撤权立即 fence 平台提交，不把 Connector 在线或 Agent 自报当原生继续 / 停止证明。
25. 当前 Agent 退出时本地推进停止，仍有效 Runner 先收集或受控取消；重连按原身份显式继续或 fenced recovery，不自动重开终态或更换主会话。

---

## 47. Legacy 领域结构（native 关系见 §49.1）

```text
                             Project
                                │
                    ┌───────────┴───────────┐
                    │                       │
             SourceSnapshot           PolicySnapshot
                    │                       │
                    └───────────┬───────────┘
                                ▼
                             TestRun
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
         Requirement          Mission           Verdict
             │                  │
             ▼                  ├── Attempt
            Risk                │
             │                  └── Proposal
             ▼
          TestCase
             │
             ▼
      TestImplementation
             │
             ▼
         Execution
             │
             ▼
          Evidence
             │
             ▼
          Finding
             │
             └────────────────────────────► Verdict
```

v0.4 的 Operational 所有权侧链（本分支已实现，不加入质量事实链）：

```text
TestRun ── 1:1 ── RunExecutionBinding
                      ├── logical_worker_id（稳定）
                      ├── primary AgentSession ── 多个串行 MissionAttempt
                      ├── harness_host_id / workspace_id
                      └── binding_epoch（显式恢复 generation）

TestRun ── 多个串行 DurableJob ── 当前 worker_id / lease_token（暂时）
```

---

## 48. 最终定义

HyperTest 不是用数据库保存 Agent 工作日志。

HyperTest 数据模型的目标是保存：

> **软件质量本身的可验证状态。**

数据库中心不是 conversation / prompt / completion，而是 Requirement / Risk / TestCase / Execution / Evidence / Finding / Verdict。

Mission 构成推动这些状态演进的：

> **Agent-native Work Control Layer。**

最终：

```text
Testing Intent
      ↓
Requirement
      ↓
Risk
      ↓
TestCase
      ↓
Execution
      ↓
Evidence
      ↓
Finding
      ↓
Verdict
```

构成 HyperTest 的 **Canonical Testing State Machine**。

只要 Requirement、Risk、Case、Execution、Evidence、Finding、Verdict 这套软件质量事实模型成立，HyperTest 就始终拥有属于自己的：

> **Testing State、Testing History 与 Evidence Graph。**

## 49. ADR-017 原生测试轮次与材料治理（v0.7）

### 49.1 语义与持久化

`native-framework-intake/v1alpha1` 使用既有 Project 和 PostgreSQL 新表，不能把独立 JSON / SQLite ledger 当 Canonical Store。NativeTestRun 是本 profile 的一次测试轮次，不是旧 TestRun 的第二份可双写对象；旧 `TestRun.id` 与 `NativeTestRun.id` 类型、API 和关联不可互用，不回填旧 Snapshot / Binding / Evidence / Verdict。新 native 轮次不要求创建平台 Docker 环境或 SourceBundle。本轮真实框架运行先于新 API 接受，因此是 retrospective intake；不得回填 created_at / accepted_at 伪造平台预先下发。

计划与原始 Plan/Case Proposal 一次冻结在 `native_test_runs` 根行，不单建一张同义 plan 表。计划 / 用例由平台 schema / reference Verifier 原子接受为长期管理资产；本轮不宣称完成旧 Requirement→Risk 覆盖证明。执行观察与原始材料虽持久保存，provenance 仍 UNVERIFIED；只有接受的管理事实、已知缺口与平台保守结论进入该 profile 的状态，不将未验证观察冒充可信测试事实。

| 实体 / 表 | 固定内容与关系 |
| --- | --- |
| `NativeTestRun` / `native_test_runs` | UUIDv7 PK、Project FK、profile、原始 proposal / input digest、objective / scope / 固定 requirements / risks / manifest / plan、初始请求身份与创建者；generation 是受控运行字段；当前 contributor 从 `(run_id, generation)` 唯一关系派生，不存在第二可变绑定或 native row_version 列 |
| `NativeCase` / `native_cases` | run FK、run 内唯一 case_key；accepted_payload 内冻结 title / requirement_ref / risk_ref / expected_result / implementation_ref，来源引用是计划内文本、不是伪造的 Canonical ID；接受后 append-only |
| `NativeContributor` / `native_contributors` | run FK、generation、Operator 登记的 actor/session metadata 与 capability hash；run 内 generation 唯一，session label 非 Provider native 证明，capability 明文不持久化 |
| `NativeExecutionRecord` / `native_execution_records` | run / contributor FK、generation、稳定操作 key、冻结的 command / cwd / framework / 实际输入上下文、开始结束 / exit / observed outcome；observed started_at / finished_at 与平台提交时间分别保存，已提交记录不原地重跑或改写 |
| `NativeExecutionCase` / `native_execution_cases` | execution / case FK 及复合唯一，保存该次原生 case result，引用须同 run；结果不是 Case lifecycle |
| `NativeMaterial` / `native_materials` | run FK、nullable execution FK（对账原件可以无 execution）、kind / format、SHA-256 / length / immutable Artifact URI / name；media type 由格式派生，按受控对象读取，不接受任意本机路径 / URL |
| `NativeVerification` / `native_verifications` | execution FK、Verifier identity / version、完整性与 report consistency、provenance=UNVERIFIED、查证时间 / 原因；只追加验证，不改原材料或自报来源 |
| `NativeConclusion` / `native_conclusions` | run FK、native Gate version、UNKNOWN/BLOCKED、固定状态 / Policy 与原因、创建时间；append-only，不改旧 current_verdict_id |
| `NativeConclusionExecution` / `native_conclusion_executions` | conclusion / execution FK 及唯一关系，显式关联参与结论的原记录 |
| `NativeHandoff` / `native_handoffs` | run、原/新 contributor FK、旧/新 generation、accepted state snapshot、remaining work、reason、Operator / 时间；append-only，不修改历史 contributor / 执行归属 |
| `NativeOperation` / `native_operations` | run FK、稳定 key、operation name、versioned input digest、结果 / 对账材料引用、状态 / 审计时间；run/key 唯一，UNKNOWN 不释放幂等身份 |

UUID FK 默认 ON DELETE RESTRICT；关系以 SQL FK / join 保存，JSON 只存原始 Proposal、不可变复合输入 / 状态快照和非关系环境描述。状态快照中的 ID 是既有关系的审计读投影，不作为可任意重绑的事实数组。全部正式行和已提交操作历史禁止 hard delete，新增 schema 不改旧表历史内容或 hash。

### 49.2 固定输入与来源

manifest 分别固定 SUT source / binary、framework source 与实际 test assets；完整 SHA、原始 dirty / untracked 状态、文件 / patch 引用、工具环境、入口范围、授权和传输范围不能混成一个 repository hash。`source_commit=null` / 未证实源码关联与二进制 SHA-256 并存合法，但必须产生可复现性 / 来源缺口；用 framework HEAD 冒充 SUT 版本非法。`dirty=true` 没有必要 diff / 文件版本时不能被验证为完整测试树。

首版 `source_transfer=NONE`，API 仅接收选定 manifest 和已检查原始报告 / 日志，不上传 JAR、应用源码或认证。文件摘要只验证对应字节；不证明源码归属、被运行的测试、环境或真实业务正确。输入变化创建关联新轮次；原始失败、setup 错误、未完成与未知不被后续重跑覆盖。

### 49.3 Proposal、写权、事务与交接

create 的计划 / case Proposal 校验通过后，run、原始 Proposal 与接受结果、case、初始 contributor、operation、Audit 与 Outbox 同 PostgreSQL 事务提交；批中任一无效则不部分接受。新 profile 的 provenance 指向 native 原始 Proposal / contributor / operation，替代旧 §30 中仅 Mission/Attempt/Proposal 的归属形式；不伪造 Mission / Attempt。无效 Proposal 全批拒绝，不产生已接受的半成品计划；拒绝 HTTP 回执与原始 Proposal 由调用方私有 journal / 受控验收材料保存，首版不虚构服务端 REJECTED Proposal 表或接受后的 operation 回执。

所有请求须有效 Operator 授权。create / handoff 的随机 writer capability 仅在首次成功响应提供，平台只保存 hash；除 create / handoff / reconcile 三类 Operator 管理写外，其他写请求还必须同时验证当前 contributor / generation 与 `X-Hypertest-Native-Writer-Key`，不能将可 GET 的 contributor 或 generation 当成授权。读接口与幂等响应不返回 key 或 hash；Operator key 保留在管理客户端，不能交给 Agent / 提示词 / MCP。

§5 的 Canonical 可变字段 row_version 通则不为此根行增设第二版本：计划 / 输入 / policy_version / 身份不可变，唯一可变 generation 属于 Operational ownership；它由 `SELECT FOR UPDATE`、expected generation 与严格递增 1 的数据库保护治理，不是任意乐观更新的 Canonical 字段。当前 contributor 由对应 generation 的唯一行派生，不存在未实现的 current_contributor_id FK 或 native row_version 列。

handoff 是独立 Operator 管理意图，不需要旧 writer key；在 run 行锁中检查 expected generation、原状态与未决操作，原子追加新 contributor / handoff、单调递增 generation、换新 capability 并写 Audit / Outbox。提交后旧 key / generation 失效，即使知道新 contributor ID 也不能写；继任者须获得私下交付的新 capability 并先读取原计划 / case / materials / 结论。session label 不构成真实 native 身份，不能声称接管旧聊天或并发多个 writer。平台只能 fence 本 profile 的 API 写入，不能证明用户原生工具进程已停止。

域写均在锁定 run、当前 writer 与操作唯一身份后验证；Artifact / 远端 I/O 不持聚合锁，返回后复核当前权限及 generation。接受事实、join、对应验证、操作回执、Audit / Outbox 在同事务提交。Artifact Store 写入不是事务已经接受的证明，读时重新检查 hash / size。不会在 API 运行测试、安装依赖或访问模型提供的文件路径。

### 49.4 材料验证、结论及 UNKNOWN

平台校验报告结构、case 名、计数、退出码和已提交观察的一致性，并分别记录 integrity / report consistency / provenance；本轮来源始终 UNVERIFIED。NativeMaterial / Verification 不进入旧 Evidence、ExecutionEvidence、Finding confirmation 或 canonical-gate/v1。观察 PASS / FAIL / ERROR 是原生框架结果描述，非正式可信状态。

当前 native Gate 只生成 UNKNOWN / BLOCKED，不允许 PASS / RELEASE_READY。完整本地通过材料若缺独立来源证明则 UNKNOWN；观察失败、setup / incomplete 条件或材料矛盾使质量治理 BLOCKED，保留全部原因而不直接认定产品缺陷。所有执行与原失败均在历史中，不能仅选成功记录删除 / 覆盖失败。结论只追加，引用对应执行 / 验证与固定状态，Agent 无写 decision 权。

NativeConclusion.UNKNOWN 是质量证据不足；NativeOperation.UNKNOWN 是副作用完成情况未知，互不转换，不新增旧 TestRun / Job enum。存在未对账 operation 时禁止新执行与 handoff；reconcile 为窄 Operator 管理例外，允许不持遗失的 writer key，但必须用原 operation key / 原 UNKNOWN 状态、具体 resolution / 原操作引用、受控原始材料、非空 reason 和绑定 source_ref / operation_ref / observed_at / result / 原件 SHA 的 Operator attestation（严格字段见 TMP §44）。run 行锁下追加人工确认 / 审计，不重跑命令或重发 CI / Issue POST；无材料、仅摘要或 NOT_FOUND 均不能消除未知，JSON 形状 / 人工确认不等于独立来源验证，本地材料的测试来源仍 UNVERIFIED。只有完成对账后才允许显式新 handoff，不自动 rotation。已发请求失答只读原 key，NOT_FOUND 不证明未执行；稳定 key / digest 与私有 journal 保留，异输入拒绝。一次性 capability 遗失时先对账，再经新 Operator handoff 管理意图交付新 key，不能从 GET 取回或自动重签。

### 49.5 迁移与验收界限

本轮 additive schema、隔离 PostgreSQL 及本机客户端验收不包含生产迁移 / 发布。旧两种受管 Harness、ADR-016 当前 Agent 身份、授权、VPN / TLS / SSH、SourceSnapshot、Execution、FINAL / 报告与失败历史原样保留，不以新 profile 绕开旧归属检查。

正式 native PASS 的后续设计须按 ADR-017 §8，由与 Agent 隔离的 CI / SCM 可信身份独立核验批准项目、pipeline/job/attempt、源码 / 测试资产 / 环境、exit 和原始产物及 case 关联；另行版本化 Gate 与正式 Evidence 准入并验收失败 / 伪造 / 撤权 / 重复 / UNKNOWN。当前只有设计门槛，没有该来源 verifier、Web/MCP 接入或真实 Provider 会话身份交接证明。

## 50. SessionTask 管理数据与历史（ADR-018，当前阶段）

本节规范当前“一个 Codex 会话一个测试任务”的管理同步；独立于 legacy TestRun/Mission/Execution/Evidence/Verdict 与 §49 native材料/Gate。平台保存 Codex产物，不执行测试；既有 Project 是唯一共享的项目身份。任务不要求存在 SourceSnapshot、Policy、执行绑定、Job、Runner或Gate记录，不向旧表回填历史。

### 50.1 实体与归属

| 对象 | 规范字段/关系与不变量 |
| --- | --- |
| SessionTask | UUID、Project FK、binding_state/binding_required、creator_actor_ref/intended_actor_ref、nullable provider/session_id/owner_actor_ref/source/last_synced_at/bound_at、title/objective/status/plan_markdown/reported_result、nullable deleted_at/last_managed_at、严格递增version、created/updated；UNBOUND与BOUND约束见§50.5，真实来源一旦绑定不可改，`(provider,session_id)`全局唯一，软删除不释放唯一性 |
| CaseRevision | Task FK、稳定case key、递增revision、接受该修订的task version、完整case内容与来源；task/key/revision唯一，不覆写旧版本 |
| ReportRevision | Task FK、稳定report key、递增revision、接受该修订的task version、标题、PostgreSQL保存的原始Markdown原文、可选artifact_uri/source_ref来源元数据、原reported result；task/key/revision唯一，不覆写旧报告 |
| SyncReceipt | Project/Task、actor_ref、稳定idempotency key、原请求摘要/原提交、接受version、冻结task_snapshot和结果引用；actor/项目/key唯一，异输入拒绝，历史回执不可变；client只在当前授权链核验 |
| TaskManagementRevision | UUID、Task FK、严格唯一的task version、人工管理action（CREATE/AUTHORIZE/UPDATE/DELETE/RESTORE）、actor_ref、冻结task_snapshot、created_at；与任务及Audit/Outbox同事务追加，不修改SyncReceipt或用例/报告修订 |
| CREATE/BIND operation receipt | Task/Project、操作类型、actor、稳定key、输入摘要、固定接受version及snapshot；独立于SyncReceipt，原key查询固定接受状态；BIND历史投影单列，不伪造Agent同步 |

Task mutable字段经同步事务、§50.4人工管理或§50.5预创建/绑定事务更新；Case/Report/各类Receipt/TaskManagementRevision为append-only。相同case/report key内容不变时复用现有修订，内容变化才递增revision；省略某key保留既有资产，禁止以“全量同步”名义删除失败历史。CREATE、管理、BIND和sync共用Task version，接受新变更时严格递增；原SyncReceipt、管理与绑定冻结快照共同覆盖可读版本，关联该版本以前已接受的case/report修订重建当时状态，不从最新字段拼装过去。

任务状态为 DRAFT/IN_PROGRESS/BLOCKED/COMPLETED/CANCELLED，表示会话任务进度，不是平台执行状态。reported result为NOT_RUN/PASS/FAIL/ERROR/SKIPPED/UNKNOWN/BLOCKED，表示提交者报告的测试结果；进行中任务可以FAIL。新报告PASS不删除原FAIL；不同判定口径分别保存来源和报告key，不伪造用例重跑或把业务复核覆盖自动断言。

### 50.2 接受与并发

legacy同步的 `expected_version=0`仅创建；预创建任务的绑定及后续sync使用§50.5同一当前version，不能以0另建替代任务。更新必须匹配当前version。在PostgreSQL聚合锁和唯一约束下核验权限/owner/版本/原key，原子保存Task、修订、Receipt、Audit/Outbox。幂等原key在版本检查前查重：已接受同请求返回原回执，不能因任务后来变更而接受第二次写；同key异输入拒绝。旧版本请求不覆盖新状态。客户端journal只是传输意图账本，不是服务端Canonical Store。

`task:sync`沿用integration actor/client/project授权链，已撤销、未生效、过期、client/actor无效和越项目均拒绝。同actor换client不伪造新任务归属；其他actor不能仅凭session reference写入已有任务。session reference是来源标签，不是原生宿主身份、执行证明或能力密钥。一个新会话建立自己的任务，交接关联先前任务与剩余工作，不改历史session身份。

### 50.3 原始报告与结果含义

Report原Markdown直接保存在PostgreSQL ReportRevision.markdown，读接口返回已保存原文；source_ref/artifact_uri是元数据，不宣称文件已上传Artifact Store，不能指令平台运行命令、读任意本机路径或抓取URL。来源、原报告与reported结果可查询；摘要与hash只用于关联、完整性和幂等，不证明测试执行。客户端journal仅保存原查询身份和完整请求digest，不反复持久复制计划/报告；原文由平台保存，来源快照可独立保留。

同步回执对外只投影固定接受身份/版本/key/source，不夹带task snapshot或全历史，存储的原response不因新增correlation投影而重写。MCP按会话读取只分页输出指定version的当前task/cases/reports JSON；续片固定version，最多24,000字符，完整拼接后仍是原文。历史仍在数据库与Web管理详情中，不因有界投影丢失；具体分页字段由TMP §45拥有。

管理保存不要求独立CI证明，不生成UNVERIFIED→UNKNOWN强制转换，也不产生legacy VERIFIED Evidence、FINAL Verdict或RELEASE_READY。Proposal/Verifier原则在本节表现为管理输入接受，Gate不进入同步事务。旧路径保留其正式质量判定职责与历史。

同步UNKNOWN表示客户端不能确认该写是否接受，和reported_result.UNKNOWN不同。保持原journal/key，只查询原Receipt；NOT_FOUND不授权自动重发、换key或替代任务。原始失败、历史结果、撤权记录与既有两种受管模式均保留；本机开发与验收不授权生产schema迁移或部署。

### 50.4 人工编辑、进度调整与软删除（2026-10-23）

Operator 可编辑 `title / objective / plan_markdown / status`，使用当前任务 `version` 作为 `expected_version`。人工PATCH在版本匹配且字段与当前值相同时为no-op，不增加版本或管理历史。五种任务进度状态之间允许人工调整，包括从 COMPLETED / CANCELLED 重新设为 IN_PROGRESS；这是管理记录的重开，不恢复原生会话、不启动或重跑测试，也不改变 legacy Run / Job / Session 的状态机。人工入口禁止更改 Project、provider、session_id、owner、reported_result、case/report及来源身份。

软删除设置 `deleted_at`，恢复清除该字段，两者均递增任务版本并追加 TaskManagementRevision 和 Audit / Outbox。删除不自动将状态改为 CANCELLED；恢复保留删除前的进度、reported result及全部产物。恢复要求所属 Project 未删除。已删除任务的 session 唯一键继续占用，新同步不能隐式恢复任务、创建替代任务或把原记录改到其他项目。

普通列表、详情及按会话查询隐藏已删除任务；回收站列表和带 `include_deleted=true` 的管理详情显式包含已删除记录。已删除项目也使其任务从普通读取隐藏。原 key 回执查询在当前有效 actor/client/project授权下仍返回原接受记录，确保删除后可以对账 UNKNOWN；它不恢复对象、不改写原回执或原接受版本，也不绕过撤权。

人工管理与Agent同步使用同一任务版本并串行接受；发生并发修改时旧版本拒绝，客户端先读取当前记录再根据真实新意图提交。历史版本读取从同步、管理和§50.5绑定不可变快照重建，Web详情提供 `management_history` 区分人工修改的版本、动作、actor与时间。实际同步后 `source=AGENT_REPORTED` 继续说明用例、报告及reported result的来源；人工管理历史不能被标为新的Agent测试结果或执行证明。

人工变更只更新 `last_managed_at`，不更新代表Agent实际同步时间的 `last_synced_at`。页面将最近同步与最近人工管理分别展示，不能把修改标题、删除或恢复显示成一次新的产物同步。

### 50.5 预创建Local任务与一次性来源绑定（ADR-024）

统一“创建测试任务”入口选择Cloud/Local；模式由任务类型派生，同一Project允许两者共存。Local仍为SessionTask，CloudTask/Attempt的ID、权限与执行生命周期不用于Local来源身份；统一目录只作有类型查询，不合并任务实体或写API。

Operator创建Local任务即生成稳定UUID、version=1、binding_state=UNBOUND、binding_required=true、DRAFT/NOT_RUN。creator_actor_ref记录创建者；provider/session_id/owner_actor_ref/source/last_synced_at/bound_at均NULL，不以Web操作者或占位ID冒充Agent。CREATE保存独立原key回执、管理CREATE快照和Audit/Outbox，固定版本1可以读取，未形成SyncReceipt/用例/报告或执行记录。

intended_actor_ref只指向有当前有效Project task:sync授权的integration actor；省略时仅sole可用actor允许默认，显式NULL保持未授权，无或多候选不先到先得。UNBOUND可保存而不可绑定。Operator使用expected_version修改/清除该字段，接受时追加AUTHORIZE管理快照与Audit/Outbox；同值no-op不增版。creator与intended actor均不是秘密，Task UUID不是凭据。BOUND后不得更改intended actor或writer owner。

Local MCP在发送BIND前核对受支持宿主SessionStart建立的私有root context；服务端事务重新核验Project/Task未删除、当前integration actor/client/Project grant、intended actor精确匹配、expected_version及全局来源唯一性。root context是本地来源选择约束，不是服务端可独立验证的宿主执行证明或额外授权。成功将provider、真实父session_id、owner_actor_ref、BOUND、bound_at一次性写入原UUID并递增version，独立BIND回执冻结同版本snapshot、配对Audit/Outbox。source和last_synced_at在BOUND后仍NULL，直到首次实际sync；不能用绑定制造Agent报告或最近同步。BIND不改变status/reported_result/cases/reports。

数据库条件约束必须拒绝半个来源对、UNBOUND带owner/来源、BOUND缺真实来源/owner、BOUND回UNBOUND或改绑。binding_required在创建时固定，手动任务true，legacy自动任务false。所有来源对（包括软删除Task）继续全局唯一；两Task抢一来源或两会话抢一Task最多一个接受，失败不得留下部分字段、版本或历史。绑定、AUTHORIZE、其他管理及sync共享version和聚合锁，不存在第二套绑定版本。

原自动任务只标记为BOUND/binding_required=false，原UUID/provider/session/owner/结果/版本/修订/回执不改；creator只能使用已有可证实来源，不伪造人工创建身份。新的Local客户端在首次批准资产上传前必须显式绑定Task ID，否则TASK_BINDING_REQUIRED且不POST sync/不自动创建。已经核验原Task ID与来源的旧自动根允许resume，既有未决journal先按原key对账。

手动任务后续sync必须携task_id并同时匹配Project、BOUND、真实provider/session、owner及version；Operator身份不绕过该integration owner校验。丢ID、错ID或身份不符明确拒绝，不忽略ID退回自动建任务。服务端原无task_id的legacy自动同步兼容单独保留，不作为新Local客户端fallback。首个实际sync使用绑定后的当前version，才写AGENT_REPORTED/source、last_synced_at及SyncReceipt。

若来源已对应另一个autoTask，绑定409，只向有权读取者返回existing_task_id；不merge、不重分配主键/来源、不搬历史或覆盖原FAIL。可以显式继续已有Task并删除未绑定草稿，或以真实新会话绑定；计划/报告的前序引用不改变原身份和权限。软删除后不得新绑定或改绑，恢复保留UNBOUND/BOUND及原来源。

CREATE/BIND写前冻结完整请求/key/version；同key同输入返回固定接受Task与版本，同key异输入冲突。SENT/UNKNOWN/失答甚至原keyNOT_FOUND只继续原key GET，不重POST、换key、另建Task或发新凭据。原回执在当前有效授权下可查询，软删除/版本前进不改原接受记录。绑定回执与sync回执是不同操作，不能混用查询身份。Web binding_history仅投影BIND的{id,action,actor_ref,task_version,task_snapshot,created_at}。

## 51. 云端测试任务模型（ADR-019，部分实现、默认关闭）

本节定义完整 `cloud-harness-task/v1alpha1` 目标；协议见 TMP §46，运行边界见 [ADR-019](../architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md)。HyperTest 管理项目资源、任务、隔离工作区、执行尝试与产物；云端 DeepSeek harness 通过官方 Python SDK 接收任务，自行工作或委派 Codex / Claude Code，并调用项目已有框架 / CI。Worker 是任务运行宿主，不是新测试引擎。当前表 / API / SDK Worker / 凭据 / 产物已有默认关闭、尚未更新测试服务器常驻Cloud服务的增量实现，准入支持HTTPS Git / 工作区内框架及显式opt-in隔离fixture固定SSH诊断，不授一般网络 / 远端SUT执行。source-r18受控六步Task已固定读回v14 COMPLETED / reported PASS、根工作及Codex原生推理 / 文本贡献；source-r21所选回归535通过 / 1跳过、source-r22针对性169通过；source-r22新native16任务已固定读回v17 COMPLETED / reported PASS、接受子原件 / 资产 / Run并独立重放9项；DESIGN仅通过ANALYSIS传递关联原件，未完全满足本次PRD直接引用要求，偏差与旧RECOVERY / HELD保留；后续r8固定SSH专项PASS，source31对同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与staging待验收；Claude占位、CI不支持，详见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。本节不因首片限制删除原不变量。

最新严格验收状态：source-r23新独立Task已固定读回v20 COMPLETED / reported PASS，ANALYSIS与DESIGN均直接引用当前child原件；source-r24只读验收器对同v20严格PASS，独立只读重放8项与原件 / 实际文件 / host日志关联通过。旧source-r22 v17仍保留DESIGN直接引用NON_PASS，原RECOVERY / HELD历史不变；SSH固定诊断默认关闭，source30 Worker的r8 canonical专项PASS，source31对同v19固定快照strict重评PASS；旧source30 NON_PASS保留（不是新的current GET，精确证据见实现状态），故障矩阵与真实staging未验收；Claude占位，CI / 一般远端shell和生产未准入。source-r23所选201 / source-r24所选231通过与各自Ruff独立登记，未覆盖其余P0；[当前证据](../CLOUD_IMPLEMENTATION_STATUS.md)。

Cloud 本轮仅接入官方 Python SDK 驱动的 DeepSeek Harness + Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 任务已固定完整读回 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 只读验收器对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT 为 strict PASS，独立只读重放 19 项通过并核对接受原件。该重评没有新的 current GET、模型、SSH 或 SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 和其他失败原件保持。最终合并树、统一 Web 入口及测试服务器常驻 Cloud 服务尚未进行本轮验收或部署；Cloud 默认关闭，精确轮次见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。

### 51.1 身份、实体与关系

既有 Project 是共享项目身份，同一 Project 可同时承载 CloudTask 和 §50 SessionTask；不存在把 Project 限定为 CLOUD 或 LOCAL 的所有权约束，云端资源配置也不是 SessionTask 的必需关系。两类任务首次所属 Project 均不随产品模式或后续更新改变。CloudTask 的 UUID 是稳定业务任务身份，CloudAttempt 的 UUID 是一次显式执行尝试身份；两者均不依赖 Codex 会话。DeepSeek / Codex / Claude 的原生 session 引用仅作带 Provider 的运行来源，不生成虚构 `(provider, session_id)`，不自动创建 SessionTask、legacy TestRun / Mission / AgentSession 或 native run。若未来关联这些记录，只能增加显式关系并保留原身份，不能借用它们的 FK 或信任语义。

以下为规范最小逻辑模型，当前正式集成的 Cloud 物理表由 `0025_cloud_tasks` 定义，固定 SSH 表由 `0026_cloud_ssh_operations` 定义，接续管理路径的 `0024_local_task_binding`；旧隔离 fixture 的 source/DDL 仍保留 `0023_cloud_tasks` / `0024_cloud_ssh_operations` 原身份；实际实现 / 证明范围另记。关系必须用 FK / 受约束 join 表实现，不以 JSON 内 ID 数组代替关系。

| 对象 | 必需字段、关系与不变量 |
| --- | --- |
| ProjectCloudConfigRevision | Project FK、递增 revision、创建者/时间；SUT 与 framework 仓库地址及默认 ref、受控 Git 访问方式、环境连接描述、credential-version 引用。同仓库合法，角色和版本仍分别记录；修改追加修订，不影响已下发任务 |
| ProjectCredential / CredentialVersion | Project FK、类型、用途、允许目标、权限范围、状态/有效期、创建/轮换审计；不可变 version 与专用加密秘密存储的引用。普通业务数据只保存 metadata/ref/version，不保存原文。秘密在专用持久层加密，主密钥与数据库/备份隔离；撤销/轮换不改写已用版本 |
| CloudInputResolution | DRAFT Task FK、解析操作 key、source_draft_version、accepted_task_version、config version 与选择器摘要、双仓库完整 SHA/MR checkout 身份、PRD/资源版本、观察时间与来源；不可变解析结果及 digest。接受结果核验原 draft version 并递增 Task version；dispatch 须匹配 accepted_task_version，不能为改变后的 DRAFT 复用旧解析快照。只由受限输入预检 Worker 产生，不启动 Harness/测试 |
| CloudTask | UUID、Project FK、固定创建者、profile、title、输入、配置修订/资源引用、status、reported_result、递增 version、latest_attempt FK、创建/更新时间；首次下发后输入 manifest/digest 不变，latest_attempt 必须属于本 Task |
| CloudAttempt | Task FK、递增 attempt_no、冻结输入 digest、status、reported_result、排队/开始/结束时间、原因、checkpoint 与已接受资产引用、专属 workspace / runtime namespace / dsh_home 身份、原生 session 来源；task/attempt_no 唯一，所属 Task/输入/序号不可变 |
| CloudAssetRevision | Task FK、来源 Attempt FK、kind、稳定 key、递增 revision、接受时 task version、来源/时间、文本原件或 CloudArtifact FK；kind 至少为 ANALYSIS / DESIGN / CASE / IMPLEMENTATION / REPORT。同 task/kind/key/revision 唯一，同内容复用，不覆写旧修订；CASE 保存步骤、预期、actual 与 reported_result，来源 Attempt 必须同 Task |
| CloudArtifact | Project/Task/Attempt 归属、受控对象身份、原文件名/媒体类型、字节数、SHA-256、上传和持久读回校验信息；对象不可变、按项目鉴权读取。仅 URI/hash、暂存文件或上传意图不是已接收 Artifact |
| CloudRunRecord / CloudRunCase | Attempt FK、稳定 run key、框架/CI 来源、实际入口/cwd、版本与环境观察、开始/结束、exit/outcome、原报告/日志 Artifact FK；每次重跑新 run key。case 结果通过 join 引用同 Task 的确切 CASE 修订，含 actual/reported_result，不能把结果写进旧 Case 修订 |
| CloudDelegation | Attempt FK、稳定 delegation key、Provider、分工/文件责任、原生引用（若观察到）、运行状态、结果/资产关联和可观察终态；同 attempt/key 唯一。不暴露独立管理写权，不因父会话 idle 自动结束 |
| CloudInputRequest | Attempt FK、稳定 question key、问题/选项、checkpoint、所需已声明操作、创建与回答者/时间；回答追加且审计，不改变冻结输入。跨项目、资源或授权上限变化须新 Task |
| CloudRemoteOperation | 独立SSH远端意图；Project / Task / Attempt / config / credential-version / 原WorkGrant FK、worker / generation、稳定operation key、operation UUID、不可变request / digest、target / action / hard deadline；task/attempt/key唯一，SENT先于I/O，重复 / UNKNOWN只原ID查询 |
| CloudRemoteObservation | 绑定原operation及同request digest的追加观察；operation/sequence及operation/digest分别唯一，来源worker / generation / CURRENT或CLEANUP模式、远端boot / unit / invocation与输出摘要；不可覆盖 / 删除或冒充普通平台mutation回执 |
| CloudRemoteOperationResult | 原operation / 确切terminal observation的唯一不可变结果；完整request / digest、terminal / stopped / 输出摘要；跨Task / Attempt拒绝，只有真实收口后建立，不由本地退出推定 |
| CloudOperationReceipt | Project/Task/Attempt（适用时）FK、稳定 operation key、操作名、actor、完整非秘密请求 digest、expected_version、状态与冻结接受结果/版本/引用、时间和对账关联；project/key 唯一，同 key 异输入冲突，UNKNOWN 不释放 key |

所有 FK 默认 ON DELETE RESTRICT；跨表引用检查同 Project/Task/Attempt 归属，Asset 的 source Attempt 不能挂到另一任务，CloudRunCase 的 case 不能挂到另一项目。Task 输入、修订、终结 Attempt、Run、Artifact、回执与审计禁止硬删除或回填成功。凭据保留/销毁遵守专门策略；销毁秘密时保留非秘密版本与使用审计，不删除历史归属。运行内容保留期限与受控清理由项目策略明示，不能静默清除未回收产物或恢复 checkpoint。

### 51.2 项目资源、凭据与授权

项目可手动登记 SUT Git、framework Git、仓库 token / SSH Git 方式，以及环境地址与连接方式；保存为项目默认供后续任务复用由用户选择。SSH 连接至少记录主机/端口、用户、跳板/网络需求与已核验 host key；不得关闭 host-key 校验。SSH 客户端认证密钥与应用签名/鉴权私钥是不同类型和用途，不可互换。环境连接成功不证明可执行业务动作，也不证明环境部署了目标 SHA。

Environment可选`cloud_access_policy=LOCAL_ONLY|WEB_ONLY|None`仅收紧路由，None在序列化中省略以保历史digest。LOCAL_ONLY拒绝Cloud创建 / 更新 / 输入解析 / 下发与执行，要求另行授权Local；WEB_ONLY要求HTTPS连接，但不启用尚缺失的HTTPSruntime / 网络。资源配置可以保存限制，执行不推导新权限；冻结限制在当前授权 / claim / credential物化与Worker prompt前重新核验，不转换Task身份。XBlock staging SSH与166dev内网资源仅Local，staging纯Web资源为WEB_ONLY，见[环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。当前未实际修改这些项目配置或读取本机秘密。

Git token、SSH 私钥、应用私钥原文只经专用秘密入口进入加密持久层；普通任务 JSON、幂等 journal、Prompt、仓库 URL、报告、Git 与日志不含秘密。资源选择和授权 manifest 冻结 credential ref/version、Project、精确目标、用途和操作上限；运行时通过目标限定的 Git helper、SSH agent、临时受控挂载或集成代理提供，按 Attempt 授权、在撤权/结束后撤销。文件模式、临时文件与日志脱敏属于执行宿主强制边界，不能只依赖 Prompt 要求 Agent 自律。

DeepSeek、Codex、Claude Code 的模型身份由云端受控服务预配，独立于项目 Git/环境凭据；不导入用户个人 HOME、浏览器档案或整套本机凭据目录。对子代理复用的是本任务允许的操作能力，不是无范围继承所有环境变量/密钥。允许的仓库、环境目标、写入动作、网络路径、测试入口、时间/费用和并发上限必须可执行地限制；不受限制的 shell 加一段说明不满足本规范。

权限分离为 `cloud:configure`（非秘密项目资源配置）、`credential:manage`（专门秘密写入/轮换）、`cloud:dispatch`（创建/解析/下发/显式复测）、`cloud:control`（回答/取消/恢复/对账）、`cloud:read` 与短期 `cloud:work`。`cloud:work` 只绑定一个 Task 的 INPUT_RESOLUTION 操作或一个具体 Attempt，前者仅允许固定输入预检，不能启动 Harness/测试。它们是该 Cloud profile 新增的专用权限，须独立授予。`task:sync` 不授予任一种云端执行或凭据读取权；知道 UUID、session label、lease generation 或 credential ref 不构成授权。全部写入/凭据物化/恢复时重新核验当前 Project grant 与撤销状态；固定旧授权快照不使已撤销权限继续有效。

#### 51.2.1 固定SSH操作账本（ADR-023，实施中）

`SSH_FIXED_DIAGNOSTICS_V1`作为独立默认关闭能力，冻结一个literal IP / port / 非root用户 / 完整Ed25519 host key和helper / catalog / 无参数动作摘要及资源上限。credential allowed_targets与任务network_targets精确匹配canonical `ssh://user@IP:port`；旧host-only元数据不自动升级授权。namespace没有SSH / signing key、平台 / DB身份或一般网络。

canonical远端操作绑定Project / Task / Attempt、原worker grant / generation、稳定client key、operation UUID、不可变完整request digest、目标 / 动作摘要 / hard deadline；追加观察保留SENT / RUNNING / STOP_REQUESTED / 终态 / UNKNOWN与远端boot / unit / invocation身份。SENT在任何远端发送前事务持久，重复和未知仅原ID QUERY，NOT_FOUND不授权重发。固定接受版本不嵌入可变远端状态，当前summary另投影；真实终态及输出引用不可回填成成功。

失租后的原owner仅凭原绑定身份对原操作QUERY / STOP / 追加真实观察，不新START / RENEW、不恢复普通平台写权；新连接仍复核credential，撤销后不得偷偷缓存使用。独立签名短票据约束lease和hard deadline，远端登记 / manager / TTL保证有界失联停止；票据有效期内撤销传播有明确有限窗口，不能称即时撤销。未观察到远端terminal / inactive unit / emptycgroup / sealed output的操作阻止Task完成、复测和释放预算，保持RECOVERY_REQUIRED / HELD；本地namespace / 模型停止不是远端证明。详见[ADR-023](../architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。固定 SSH 诊断仅在隔离 fixture 中实施；通用 SSH 仍不支持，不改变Project共享双模式；见[执行环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

### 51.3 六步输入冻结

1. 在云端创建或复用 Project，并登记/可选保存资源配置及凭据版本。
2. 在云端创建 DRAFT CloudTask，选择 SUT branch / feat / MR / SHA、framework ref、环境、PRD、测试目标、基本流程、测试范围、允许副作用和预算。feat 是需求/变更标签，必须有可解析 Git 选择器，不能替代源码身份。
3. 先用 `ResolveCloudInputs` 将 DRAFT 的资源版本与选择器交给受限 Worker 解析，形成不可变 CloudInputResolution；Git/环境预检在 Worker 和聚合行锁外进行，API 不运行 Git。显式 dispatch 引用 resolution_id，重新检查授权、draft/config version 与 expected_version，原子接受冻结 manifest、首个 QUEUED Attempt、操作回执、Audit 和 Outbox。排队成功不代表已启动 Harness 或测试通过。
4. 云端 Worker 领取该 Attempt，准备隔离运行环境，以官方 Python SDK 启动 DeepSeek harness、提交冻结任务并记录分工。
5. 持久接受分析、设计、用例和实现修订；原件回收独立于主进程是否仍存活。
6. Agent 调用已有测试入口，保存每次 Run、case actual、日志/原报告及最终汇报。第 5/6 步可循环，所有失败与修订保留。

冻结 manifest 必须包含两个仓库的规范地址、角色、选择器、完整 commit SHA 与访问配置版本。MR 记录 base/head SHA、来源 MR 和 checkout_strategy（HEAD 或 MERGE），实际测试 checkout SHA 明示；MERGE 结果须实际存在且被固定，不自行猜测合并 SHA。同仓双角色也分别固定。PRD 保存确切内容/附件版本及 digest，不能只保存一个可变 URL；目标、流程、范围、framework 入口、环境连接修订、授权 manifest 和预算版本同时冻结。

环境保存期望部署身份与下发时观察（含 observed_at / source / UNKNOWN）；每次测试另记录实际部署身份和不确定项。Git checkout SHA、测试框架 SHA 和实际 SUT build 分开，连通性或 framework HEAD 不代替 SUT 版本证明。若任务要求匹配部署版本而不能确认，则该测试前置条件 BLOCKED；允许测试现有部署时可保存 UNKNOWN 来源并在结论说明缺口。

首次 dispatch 后不修改输入；配置默认值或分支移动不影响原 manifest。更换 PRD、目标版本、环境、授权上限、credential 版本或预算上限创建显式关联的新 CloudTask。相同冻结输入的显式复测可建立新 Attempt，须重新验证当前权限并受原 Task 累计预算约束，不因重试自动重置额度。允许范围内的凭据临时物化/短令牌续期不得扩大冻结授权。

预算的 `accounting_unit` 随输入冻结：缺省 / 既有任务按 `CONSERVATIVE_MICROUNITS` 解释，不迁移或改写旧任务；单独批准的模型接入可显式选 `REQUEST_CREDITS`。后者虽沿用 `total_cost_microunits` / `cost_microunits` 字段名，值表示按已冻结请求费率计算的计数额度，不能解释为 USD、供应商 token 账单、真实费用或退款。Codex OAuth 首片仅接受显式 `REQUEST_CREDITS`，不假定可观测其货币价格。

CloudAttempt 既有 `runtime_metadata` 保存独立预算记录，不新增实体或改变任务身份。claim 在任何 Git 准备之前持久化 `preparation_budget_reservation`：状态 `HELD`，保留本次允许的完整准备 / 执行截止秒数、generation 和时间。进入 RUNNING 前，当前 Worker 必须用严格类型的 `budget_reservation` 持久预留整个截止区间（包含准备时间），以及 ROOT / 获准 child 各 scope 的 `max_requests × cost_per_request_microunits` 最坏额度；所有 scope 共用 Task 剩余额度，不能各得一份完整预算。服务端按 Task 锁串行检查累计上限；Agent 不能提交、覆盖或结算这些记录。

`budget_reservation` 保留原 operation key、generation、时间和请求上限，状态仅为 `HELD` / `SETTLED`。累计用量按每 Attempt 的 `max(已观察用量, 未释放预留)` 计入；准备期间也计时间 hold，不能等实际模型费用回写后才限制复测。丢失 lease、取消、超时、报告 UNKNOWN 或人工 RECONCILE 均不自动释放 hold。只有当前 fenced Worker 观察整 namespace 已停止、所有模型 broker 关闭并 join / 无在途请求，才可在原 typed mutation 中附 `budget_settlement`：相同 accounting unit、完整 scope 请求计数、观察耗时及停止 / drained 为 true 的证据。计数不得超预留上限，计数乘预留费率须与提交的 observed usage 一致；原 hold 和结算记录同时保留。无法证明收尾则继续 HELD；结算不伪称供应商账单，不能由模型自述替代。结算、终态及 fencing 必须在同一接受事务完成，终态记录首次落库后仍不可变。

### 51.4 生命周期、复测与恢复

CloudTask 是任务聚合；DRAFT 仅表示尚未下发。下发后，其 status/reported_result 是最新 Attempt 的受控投影，历史状态通过回执、修订与审计重建。CloudAttempt 状态如下：

| 当前状态 | 允许后继及条件 |
| --- | --- |
| QUEUED | PREPARING（有效租约领取）；CANCELLED（未开始且无未决副作用） |
| PREPARING | RUNNING（固定工作区/授权检查通过）；WAITING_INPUT（可安全暂停的问题）；FAILED（确定准备失败）；CANCELLED；RECOVERY_REQUIRED |
| RUNNING | WAITING_INPUT；COMPLETED（§51.6 收尾检查通过）；FAILED（本次工作不能完成）；CANCELLED；RECOVERY_REQUIRED |
| WAITING_INPUT | PREPARING（同 Attempt 回答后显式恢复并重查）；CANCELLED；RECOVERY_REQUIRED |
| RECOVERY_REQUIRED | PREPARING（原操作已对账、旧进程/owner 已隔离后显式恢复同 Attempt）；COMPLETED / FAILED / CANCELLED（有材料支持且确认无未决操作的显式收尾） |
| COMPLETED / FAILED / CANCELLED | Attempt 终态，不再重开。CloudTask 可经新显式 dispatch 在同冻结输入下追加新 Attempt 并投影为 QUEUED |

Task 还允许 DRAFT → CANCELLED；无 Attempt 的取消不伪造执行历史，也没有可复测的冻结 manifest，此类 Task 保持终态，重新开始须新建关联 DRAFT。只有已下发、存在冻结 manifest 且最新 Attempt 已终结的 Task 才适用同输入复测。`COMPLETED` 表示约定工作和产物交付结束，不表示测试 PASS；测试发现 FAIL / ERROR / BLOCKED 仍可按完整报告完成任务。`FAILED` 表示尝试未能交付任务，不能用它覆盖已经观察到的 case FAIL。Task/Attempt/Case/Report 的 `reported_result` 使用 `NOT_RUN | PASS | FAIL | ERROR | SKIPPED | UNKNOWN | BLOCKED`，与进度状态及 operation UNKNOWN 分离。

每 Task 至多一个未终结 Attempt；QUEUED/PREPARING/RUNNING/WAITING_INPUT/RECOVERY_REQUIRED 均占用该唯一性。无租约的等待或恢复状态也不允许新 Attempt 越过它。显式复测先确认当前 Attempt 已终结、未决操作已对账，再在聚合锁下追加 attempt_no；旧 Attempt 和原结果不可变。测试循环内一次新框架调用创建新 RunRecord，无需为每次失败诊断生成 Attempt。

运行所有权使用独立 CloudAttempt lease：worker owner、不可猜的 lease token、单调递增 fencing generation 和 expiry。claim/续租/释放是 Operational 事务；普通 Task 版本与租约 generation 不能互相替代。Worker 提交阶段/产物/结果必须同时持有效短期 `cloud:work`、当前 lease/generation 和匹配 task version。失效 Worker 的迟到提交被拒绝；网络/Artifact/SDK I/O 不持聚合行锁，返回后重新检查所有权。沿用 PostgreSQL 队列/租约模式可以，不能将 CloudTask UUID 写进旧 `DurableJob.test_run_id` 或改动 legacy Job 归属。

受控验收控制器的人工协调不结算模型预算：操作者私有 host proof 必须绑定原 Project / Task / Attempt / expected_version，明确旧 owner 已 fence、整树停止、无未决平台 / 获准外部操作，同时声明 `model_drain_observed=false` 和 `model_budget_disposition=KEEP_HELD`。该路径只将 RECOVERY_REQUIRED 显式收尾为 FAILED；读回还核对原完整 hold 与 preparation hold 不变。原模型在途完成未知仍保留额度，不将停止本地进程当供应商结算证明。输入 / 授权 / 预算修订用同 Project 下明确 `related_task_id` 的新 Task，复用经核验的原配置与固定双 SHA，独立持久原 key / version，不自动 dispatch、不重开旧 Attempt、不借新任务重发已知未决外部动作。2026-10-22 首个真实 Task 的 v7 FAILED / HELD 已按此边界读回；它证明受控失败恢复，未证明测试执行或六步成功。r11 的 370 项隔离回归与后续真实结果见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。

### 51.5 SDK 运行隔离、WAITING_INPUT 与 UNKNOWN

每 Attempt 拥有独立 runtime、workspace、dsh_home；恢复仍归同 Attempt，但新运行进程/代次另记来源。官方 Python SDK 经 `dsh --profile sdk` 子进程通信，不是免进程调用或更快测试引擎。SDK/runtime 配对版本和能力探针结果随 Attempt 固定；不能把尚未提供的单 session cancel/close 或实时审批当成可用能力。DeepSeek 是唯一任务汇总者；平台 Worker 是唯一管理提交边界，子代理只贡献产物，不各自创建 Task 或获得管理写密钥。

当前固定 Codex opt-in profile 的 `CloudDelegation.native_ref` 是官方 `subagent_codex` 工具返回的 external activation child UUID；另存官方 run UUID 与受控生命周期观察。它不是 Codex app-server 的产品 thread ID，不证明原生会话可恢复。责任与已接受资产由父任务 handoff 提供，status / terminal_observation 仅由 Worker 的已验证事件观察注入，Agent 不能自报。该 runtime-reported 来源仍不等于独立执行证明；只有实际子代理验收后才记录 observed，Claude Code 仍为 placeholder。

WAITING_INPUT 必须先保存问题、已接受产物和 checkpoint，再停止或安全停放本地活动并释放计算/租约；存在状态不明的外部动作时进入 RECOVERY_REQUIRED。预授权 profile 仅支持冻结 manifest 内允许的动作；Worker/隔离运行环境必须在工具、凭据、网络和进程边界阻止未授权调用。缺少权限就等待输入；不能通过通用 shell 绕过禁止动作，也不能声称 SDK 会进行运行中审批。回答不隐式授权跨项目/新环境/更高副作用，超出原上限须新任务。

取消/超时首先 fence 管理写权，再终止该 Attempt 整棵本地进程树，记录结果；终止本地 runtime 不证明已触发的远程命令、CI 或业务副作用停止。已知未决操作存在时保持 RECOVERY_REQUIRED，reported_result 原样保留。租约失联、崩溃、半成品上传或提交失答均需对账，不以 runtime 重启自动重跑。

恢复只保证可恢复的对话/文件/checkpoint，不能恢复旧 shell、浏览器或测试进程。须先只读核对原 operation key、进程/委派状态、CI/远端状态和已经保存的资产，再由有权操作者明确选择继续；无法确认安全续接则保留恢复阻塞，或完成对账后结束旧 Attempt，再显式新 Attempt。每个外部副作用在执行前固定 operation key 与非秘密输入摘要，结果失答不换 key、不再触发。operation UNKNOWN 的原 key 查询得到 NOT_FOUND 不证明外部未执行；消除 UNKNOWN 要有原操作/目标、观察时间、原始材料与有权对账记录。不得通过取消标记、复测或新 Task 绕过已知未决副作用。

### 51.6 产物、执行记录与完成条件

分析、设计、用例、实现和报告分阶段版本化。实现必须关联精确 framework 基线 SHA、工作目录、commit（若存在）、dirty/untracked 清单与足以重建测试树的完整 patch/新增文件；未 push 代码不能只有不可访问本地路径或 commit 文本。push/MR/Issue 写入须在本任务既有授权内，不能因要保存产物自动获得仓库写权限。

云端中途业务进度保存为同一 CloudTask/当前 CloudAttempt 的 **CloudAssetRevision，kind=REPORT**；每个 Attempt 选择独立稳定进度 key，同 Task 内不跨 Attempt 复用该 key，在本 Attempt 内追加非最终报告修订。原文明确阶段、里程碑、阻塞/未观察项和已接受产物的确切修订引用；只记录活动不构成正式进度报告。引用检查同 Project/Task，复用旧 Attempt 材料须保留真实来源；当前报告的 source Attempt 不得伪造。CloudAttempt 既有 checkpoint 可引用此报告修订：SubmitCloudAssets 的可选参数 `checkpoint_report_key` 只选择本批一个正式 REPORT key；接受事务将其确切接受/复用 revision 绑定为同 Task/Attempt 的 checkpoint，省略不改，不允许任意 ref 或隐式清除。资产与引用按同一 Task version、原 key、lease/generation 原子校验/保存，回执和固定接受版本读回包含该绑定，历史可重建。它不是新实体、状态或 REPORT 子类型 enum，也不新增独立无 key 的更新。进度资产接受不改变 Task/Attempt status/reported_result；不得用 schema 默认空值/NOT_RUN 覆盖既有结果。最终报告仍由显式 completion manifest 的 final_report_revision 指定并接受全部收尾校验，不从“最新 REPORT”自动推导。

上述绑定只更新既有 checkpoint 中的业务进度报告引用，不能覆盖或替代 SDK 会话、固定文件、委派及外部操作等运行恢复材料。业务进度报告与可恢复运行上下文须分别保留和校验；REPORT 可读回不证明 SDK/进程可恢复，WAITING_INPUT / Resume 继续遵守 §51.4–51.5 的所有权、上下文和未决操作规则。

文本原文在数据库或受控对象中持久保存并读回；附件先完成受限上传与字节/hash/大小校验，再由事务接受 Artifact 关系。只保存 URI、摘要或平台暂存成功不能宣称原件已回收。大型报告按固定版本分页/分块读回，投影有界且不可静默截断；秘密扫描/脱敏拒收含秘密材料，修订不能掩盖原始失败事实。

每次 RunRecord 保存实际 SUT build/来源（未知明确 UNKNOWN）、framework 基线及确切 test tree/patch、CASE 修订集合、环境观察、原执行入口/cwd/框架版本、时间、退出码或未观察原因、CI/project/job 身份（适用时）、stdout/stderr/原报告 Artifact、case actual 与来源。提交时间与实际执行时间分开；不得将重提历史报告记为新执行。执行在项目框架/CI 中发生，平台只回收和校验，不将 SDK 事件转成正式执行事实。

完成必须确认：必需阶段资产已接受并可读回；每个委派有可观察终态或明确取消记录；所需测试均有 Run/结果或明确未执行与原因；无未决副作用/操作；最终报告明确范围、FAIL/ERROR/BLOCKED/未观察项和产物引用。root idle、turn 完成、`session/wait` 返回或 Agent 一段“完成”文本都不足以触发 COMPLETED；外部 Codex/Claude CLI 子进程需要委派清单与产物核对，不能只消费 in-process `subagent.finished`。

允许记录 Agent/framework 报告的 PASS，无独立 CI 不强制改为 UNKNOWN；平台结构/版本/完整性接受不证明产品通过，不自动产生 legacy VERIFIED Evidence、FINAL Verdict、Finding confirmation、Gate PASS 或 RELEASE_READY。第 5/6 步循环保留每次原始 FAIL 与后续修订；不能改断言来洗 PASS，纠正错误测试须说明原因、保留旧代码/结果并新建执行记录。SDK 全量会话、思维链与 Provider 内部事件不成为 Canonical Testing State；只保存脱敏活动摘要、必要工具/委派来源和领域资产。

### 51.7 事务、幂等和兼容验收

配置/凭据/Task 修改、dispatch、复测、回答、取消、恢复、资产/结果接受各有稳定 operation key 与 expected_version。项目配置与凭据分别匹配其自身聚合版本，不使用 Task version；创建 Task 用 expected_version=0，后续 Task 修改、Attempt 控制及资产/结果接受匹配当前 Task version 并在接受时严格递增。Attempt 相关写入同时核验当前运行所有权：Worker 提交必须持有效 lease/generation，管理取消/恢复按 §51.4–51.5 核对并 fence 旧 owner，不能用 Task version 代替租约检查。操作先检查同 key 回执，再做版本冲突判定；已接受同请求返回冻结原回执，同 key 异输入拒绝。Task/Attempt 关系、资产修订、状态与 result 投影、回执、Audit/Outbox 原子接受；秘密原文不入普通请求回执或 journal。

写请求失答保留原意图/key/digest，仅查原回执；PENDING/UNKNOWN/NOT_FOUND 不授权自动 POST、换 key、重新下发或重启 Harness。查询/读取本身须重新鉴权；对账只能追加结论与材料，不能修改原请求或测试结果。业务 mutation 回执、Artifact 接收和外部执行副作用各自对账，不能用其中一个成功代替另一个。

本设计 additive；§50 的 `(provider,session_id)` 唯一性、Project/owner、version、`task:sync`、两原生 MCP 工具、原 key UNKNOWN 处理及原报告结果全部保留。云端未启用时现有会话同步继续可用；新旧路径不自动互转。§49 native、旧两种受管 Harness、Job/FK、授权、Execution/Evidence/Gate 和 FINAL 历史不迁移或重新解释。后续实现必须验收凭据隔离/撤权、版本冻结、重复/失答、租约 fencing、取消/恢复、委派收尾、原件读回和失败保全，并证明新云端操作没有改变 ADR-018 的既有同步与历史。

### 51.8 双产品模式、共享 Project 与只读任务目录

以下是产品模式的规范映射，不新增可变的持久化 mode 列：

| 真实任务类型 `task_kind` | 派生 `product_mode` | 规范实体与工作归属 |
| --- | --- | --- |
| `CLOUD_TASK` | `CLOUD` | §51 CloudTask/CloudAttempt；项目/任务创建和受监督执行在云端，由官方 Python SDK 驱动 DeepSeek，按六步流程回收产物 |
| `SESSION_TASK` | `LOCAL` | §50 SessionTask；按 §50.5 预创建原 UUID 并绑定真实父会话后，由本地 Agent 经 MCP 同步测试资产；已确认的 legacy 自动任务保留原身份。Local 0.1.0 三宿主资格保持其独立版本边界，ADR-024 新客户端 / 绑定验收与发行另记；平台不因此执行测试 |

`task_kind` 由实际实体类型确定，`product_mode` 是该类型的固定读投影，不是任务可修改字段、Project 属性或新的执行选择器。不能从 SDK runtime、Agent Provider、本地/远端文件路径、测试环境位置或 reported result 推导模式；本地 Agent 调用授权远端框架/CI 仍是 SESSION_TASK。两类任务不自动转换或重建为彼此；原生子代理 session 引用也不自动生成 SessionTask。

产品 LOCAL 会话同步与 ADR-015/016 legacy `execution_mode=LOCAL` 的受管/交互式 TestRun 路径不同；产品 CLOUD/CloudTask 也不是旧 `execution_mode=CLOUD` 的别名。旧 HarnessMode、绑定、TestRun ID 和历史保持原含义；不能为显示产品模式回填、重编号或迁移旧记录。Project 是长期共同归属，不因两种模式拆成两个项目，也不要求项目先选一个排他的 mode。

项目通过 **ProjectTaskSummary** 只读混合投影提供目录（当前源码已加入，部署与完整验收未完成）；它不是新的 Canonical 任务实体或跨表共享 FK：

| 投影字段 | 约束 |
| --- | --- |
| `project_id` | 原任务的真实 Project FK；读取前按当前项目授权与对应任务归属核验 |
| `task_kind, task_id` | 分别为 CLOUD_TASK / SESSION_TASK 与原表 UUID；二者共同构成目录行身份，不能仅按 UUID 去重或跨类型查询详情 |
| `product_mode` | 由上述固定映射派生，拒绝把它作为类型转换或模式修改输入 |
| `source_profile, source_ref` | 保留对应契约标识与非秘密来源；LOCAL 的 `provider, session_id` 在 UNBOUND 时为 null，BOUND 后为一次性绑定的真实来源；其 `source` 在首次实际 sync 前仍为 null，不造 AGENT_REPORTED。CLOUD 为最新 `attempt_id`（尚无 Attempt 时为 null），更细原生来源在其详情读取。来源标签不构成授权或执行证明 |
| `title, task_version, status, reported_result, created_at, updated_at` | 原任务的真实摘要、版本、类型内进度和结果；updated_at 保留真实创建 / 管理 / 同步时间，不把管理或 BIND 伪装为 Agent 同步。不创造跨类型共同版本或改写状态枚举，不合并 reported result 或证据等级 |
| Local `last_synced_at` | 首次实际 sync 前为 null，BIND 不推进此时间；不能因目录排序、绑定或人工管理补造最近同步 |

目录按每行原类型的读取规则过滤，Project 可见不自动获得该项目全部任务权限。SessionTask 仍遵守 §50 的 integration actor/client/project、owner 和 `task:sync`；UNBOUND 不能补造 owner，按 ID 读取 / BIND 须另核 §50.5 intended actor 的当前授权，目录不能自动扩大其读取范围。CloudTask 仍遵守 §51.2 的项目授权与 `cloud:read`。目录不得以共用 Project 规避 owner、暴露未授权记录/计数/来源或向本地会话授予云端控制/凭据能力；无需为目录增设 scope。明确只具有一种权限的调用者只能看到该类中获准的任务，两种权限兼有者才可读取两类获准任务。

允许按 `task_kind`、派生 `product_mode` 和来源筛选；确定性排序/分页保留完整复合行身份，不能因两表 UUID 相同丢行。详情、历史版本和原件按类型路由至各自读取契约，并固定对应 task version；统一列表不是共同写入口，不取代原同步回执、CloudOperationReceipt 或各自幂等空间。本规范不声明现有 API/MCP 已实现混合查询，不修改 §50 的请求、回执或字段。

同项目并存的实施验收至少覆盖：

1. 在同一真实 project_id 下分别建立 CloudTask 与 SessionTask，混合目录正确返回类型/UUID/派生模式/来源，并按两种类型和来源筛选；构造跨表相同 UUID 时仍是两行，详情正确路由。
2. 只有 `task:sync` 的当前授权保持 SessionTask 原 owner 约束，无云端读取/执行/凭据能力；只有云端权限不自动取得本地任务读写；跨项目、跨 owner、撤权及未授权计数/来源不泄露。
3. 不配置云端仓库/凭据、不存在 CloudAttempt/Job/执行绑定时，本地任务仍可同步；云端凭据失效、SDK/Worker 停止或云端准入关闭不阻断本地同步与获授权历史读回。
4. 两种任务在同项目内独立版本化、并行更新和取消；一种任务的控制/恢复不修改另一种任务，模式筛选或页面操作不触发执行、任务转换或额外 SessionTask。
5. 分类型固定版本、完整分页读回分析/用例/原报告与失败修订；新增云端任务前后的本地原回执、原报告和 reported result 不变，云端失败/复测不覆盖本地或历史结论。

以上为完整验收要求；混合查询与云端执行已有部分源码，源码存在不替代上述各项验收。source-r18受控六步Task的reported PASS、根工作和Codex原生推理 / 文本贡献已正式接受，source-r22新native16任务的子原件 / 资产 / Run及独立重放9项已核验，DESIGN直接原件引用的精确PRD偏差、旧引用拒绝 / RECOVERY / HELD历史与上述其余验收仍分别跟踪，当前证明边界见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。

本次 Cloud 集成的项目与混合目录必须遵循已存在的 Project/SessionTask 软删除、owner/provider/type 读取边界；不覆盖 §50 的人工管理历史。统一创建入口与 Local 预建 Task/绑定由管理路径及其 ADR-024 拥有，本节不引入另一套 Local 身份或绕过该路径。最终集成兼容性验证尚未执行。

## 52. ADR-020 Local 客户端不变量


本节记录 Local（ADR-020）与 TaskSyncCore（ADR-021）Local 消费方的独立交付边界。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

Local 客户端沿用 ADR-018、TMP §45 与领域 §50 的身份和同步契约；人工管理见§50.4 / TMP§45.3，ADR-024预建绑定及新会话前置门槛见§50.5 / TMP§45.4。legacy API/profile、task:sync、
Project/actor owner、完整请求、expected_version 与历史语义不变；hypertest_sync_task 不是 PATCH。
同一真实父会话由一个有效 LocalSyncCoordinator 接受 Hook 触发与显式 MCP；子代理只回交父任务。
只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录。
冻结后保留完整请求/key/version；SENT/UNKNOWN/失答及 NOT_FOUND 只 GET 原 key，不自动再次 POST。
有效 ACK 后完整读回固定接受版本才确认本次同步；传输状态不重写 reported_result，Stop 不代表 PASS/COMPLETED。

Local 发行独立使用 local-vSEMVER，旧 mcp-v0.1.0/mcp-v0.2.0 历史不重标。
安装只复用既有私有 Project 授权，不申请 Operator key、签发 grant 或复制模型登录；
Hooks 需显式选择 workspace 或私有 approved artifact policy，版本匹配后启用。
升级/回退/卸载保留私有身份、账本、未决 key、源产物、用户项目与其他宿主配置。
Local 发行不包含 Cloud runtime；Cloud 实施进度与最终树验收按独立 Cloud 状态记录，不由 Local 发行成绩推定。

## 53. ADR-021 私有同步记录与域隔离

TaskSyncCore 是内部可复用库，LocalSyncAdapter 保留 SessionTask 的原请求、身份、权限与版本规则。
共享语义是批准的结构化意图、完整基线、冻结请求、原 key 对账、回执验证与固定版本完整读回；
不增加通用 Task/API、跨模式 token、全局 journal 或服务端 fencing 字段。
Source binding、事件队列、snapshot 与 checkpoint 均为私有客户端记录，不是新的业务状态；此处Source binding不等同§50.5的服务端Task绑定字段/回执。私有root记录选定Task ID后，Hook与MCP共用目标及未决账本，不借共享核心改变授权或来源。
只合并未冻结新意图；显式 MCP 完整请求的空值不被自动推断为 omitted，传输失败不修改业务报告。
Cloud 消费方由 §51 和下节独立集成/验收拥有；Local 包不包含 Cloud runtime。

### 53.1 Cloud 的私有账本与 Canonical 边界

CloudTaskReporter 只在当前 fenced Worker 内，经 CloudSyncAdapter 使用共享同步语义；CloudOperationReceipt 与 Attempt 私有报告账本不与 Local SyncReceipt/journal 合并。Task/Attempt UUID、lease/generation、操作类型和Project归属分别核对，共享 Project 或相同 key 文本不形成跨模式权限。

### 53.2 Cloud 冻结、接受与结果保全

正式阶段资产及非最终 REPORT 可以持续追加，版本、原件和来源必须可读回；SDK活动或子代理回答不成为业务进度和PASS。冻结后的完整请求/key/expected_version/适用generation不因重启、文件变化或换owner修改。SENT/UNKNOWN/NOT_FOUND只查原key；有效接受后按该固定版本完整分页/分块读回。安全取消或失租不删除未决请求；在途上传、领域接受、子进程/模型与远端动作分开对账，未知仍保留，不能自动重放或释放HELD。

Cloud模型与子代理不持有平台writer/DB/Operator凭据，子贡献回到原CloudTask；Cloud不依赖终端Local安装器，也不向Local新增附件上传、lease或scope。新Cloud规范不改 §50/§52 的Local管理、绑定及发行历史；最终合并树验证另行记录。
