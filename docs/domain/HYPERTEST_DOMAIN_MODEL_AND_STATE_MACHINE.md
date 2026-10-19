# HyperTest Domain Model & State Machine Specification

**Document Status:** Normative / Accepted v0.4; Implemented, Production Migration Verified (2026-10-19)

**Version:** v0.4 Target
**Parent Documents:**

- HyperTest Whitepaper v1.1
- HyperTest Technical Architecture v0.4 Target
- Test Mission Protocol Specification v0.4 Target
- [ADR-013 — Containerized Platform and Persistent Harness](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)

**Applies To:** HyperTest Canonical Testing State and its Operational Ownership Boundaries

---

## 1. 文档目的

本文正式定义 HyperTest 的领域模型、实体关系、生命周期、数据库约束和持久化规则。

本文是 HyperTest Canonical State 的规范性定义。如果本文与上层架构文档在 Field、Relationship、Lifecycle、Uniqueness、Persistence、State Transition 上冲突，以本文为准。

### 1.1 实施边界

v0.4 已接受设计为：一个稳定 SUT 对应一个 Project；一个 feat / MR 的完整 SHA 及固定测试输入对应一次用户可见 TestRun。每个 Run 只有一个逻辑 TaskWorker 绑定及一个持久主 AgentSession，串行推进多个 typed Mission / Attempt。平台 Worker 和 Control Plane 容器化；只有 Provider Harness、其认证 / 原生会话运行时及窄 Host Bridge 保留在宿主。不同 Run 可以并发，同一 Run 不引入多个平台 Worker 同时协作。

**这些运行归属与受控工具边界已实现，2026-10-19 正式迁移与真实正反链路已验收。** `0013_run_bindings` 实现 RunExecutionBinding、RunInputRequest 及跨 scope 约束；`0014_harness_operations` 实现运行 checkpoint、工具 / 预算账本、报告、管理请求与受控 GitLab 操作记录。本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)。ADR-013 正式切换与恢复的历史结果见[正式部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。后续 PR #10 已部署源码 `828225d`，API/Worker/Web 同源更新，兼容 Host Bridge 保留 `95e92c5`，数据库仍为 `0014_harness_operations`；当前运维边界见[服务器操作](../SERVER_OPERATIONS.md)。会话关闭后的平台治理准入由 [ADR-014](../architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md) 与 §23.8 规定，其实现和真实验收另行登记。真实 GitLab 提单、其他 Provider 及后续 Web 改进仍须独立验收。本文标为“v0.3 已实现”的逐 Mission 会话、bounded controller 和 wire contract 保留当时的历史解释；新 profile 的版本与工具 schema 以 TMP 为准，现有 `hypertest.tmp/v1alpha1` 不被原地重解释。

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

v0.4 另定义 Operational 支撑记录 `RunExecutionBinding`（§23.4），用于任务执行所有权；它不是 Canonical Test Fact，也不是新的用户可见测试任务实体。

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
created_at          timestamptz
updated_at          timestamptz
row_version         bigint
```

唯一：`UNIQUE(key)`。

Project 不以 repository URL 为唯一键，长期允许 multi-repo。

**v0.4 目标：** Project 对应一个稳定被测系统（SUT），用于组织其多个 feat / MR 测试轮次。新增 feat、MR、commit 或重测不创建另一个 Project。repository 是该 SUT 的源引用，不代替 SUT 身份；此产品约定不新增 `UNIQUE(repository_url)` 或假定当前已有独立 SUT 表。

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

Repository origin 安全边界：Project / SourceSnapshot / Run 创建输入拒绝 HTTP(S) userinfo 和可解析 URL 的 password（含空密码），在写入 Snapshot / Run / 输入 Artifact 前失败；认证配置属于宿主 Git，不持久化在源身份。无密码 SSH username、scp 形式与本地 origin 不因此改写。Runtime 在注入 Context 前对历史 Snapshot 重复校验，拒绝时不创建 AgentSession / MissionAttempt，也不修改旧 Snapshot。此规则不是对路径 / query / 任意输入内容的秘密扫描，不新增领域字段或迁移。API 422 校验错误仅返回 `type` / `loc` / `msg`，不包含 `input` / `ctx` / 原请求 body；错误响应不是领域事实或全面日志脱敏保证。

Fingerprint：

```text
SHA256(project_id + repository + commit_sha + prd_sha256 + configuration_sha256)
```

唯一：`UNIQUE(project_id, source_fingerprint)`。

`0011_execution_environments` 新增 nullable JSONB `environment_definition`。旧 Snapshot 保留 SQL NULL，不回填或重算历史 hash。新 Web/bootstrap 可选严格受控环境请求（`python-pytest-v1`，或 `python-api-v1` 加 ASGI `module:attribute` / 本地 health path / 有界启动时限）；平台在任何输入 Artifact / Snapshot 写入前、Project 行锁之外解析当前可信预制镜像，固定 schema version、规范化请求、实际 image ID / OS / architecture、完整依赖版本与锁 SHA-256、可信 launcher SHA-256。调用者不提交任意镜像、安装命令或冻结绑定。原 PRD/configuration 字节和各自 hash 保持独立。

对 non-NULL 新绑定，Source fingerprint 的规范化对象额外纳入完整 `environment_definition`；旧 NULL 不添加此键，保留原算法。Gate 的 SourceSnapshot 语义序列化同样仅在 non-NULL 时包含此键，防止增加空列改变旧 FINAL 的 state hash。全行 immutable trigger 同时保护新字段；不同环境或实际镜像创建新 Snapshot。既有低层 hash-only SourceSnapshot API 保持 NULL 的 legacy 路径，不通过缺省推断服务环境。

bootstrap 同幂等键重试先比较原始 PRD/configuration、规范化 repo/commit、生效 Policy 和规范化环境请求，匹配时直接返回原 Run/绑定；不因镜像 tag 漂移重新解析或替换。新请求解析后取得 Project 锁，再次检查同键竞争。新绑定只支持 Docker；正式执行必须按固定 image ID 重新核验依赖/launcher，不改用当前 tag 或降级。

`0012_api_environment_v2` 仅扩展受控 profile CHECK，增加 `python-api-v2`，不修改已有行、环境绑定或指纹。当前 Web 目录为 pytest-v1/API-v2；API-v1 历史请求与幂等重放仍受支持。API-v2 的新 launcher 明确禁用仓库 pytest 配置和 conftest，生成的 HTTP 测试须自包含。API-v1 与 pytest-v1 保留原 launcher/lock/镜像身份；不得把旧绑定重新解释成 v2。改变此执行语义、依赖或 launcher 必须另建 profile 版本与新 Snapshot，已有 FINAL 历史不得回填。

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

## 11. TestRun

TestRun 表示针对一个 SourceSnapshot，在某套 Policy 下的一次自治测试活动。

**v0.4 目标：** TestRun 就是用户可见的“测试任务 / 测试轮次”，不另建与其重复的 Task Canonical 实体。典型任务针对某个 feat / MR 的一个明确完整 Commit SHA；MR / branch 名称只作来源和展示引用，push 后的新 SHA 创建新 Run。若需要区分 MR head 与 merge-result commit，必须先选定并固定实际被测 SHA，不能运行中随分支变化而漂移。

SHA 不是完整测试身份。PRD、configuration、固定环境属于 SourceSnapshot；PolicySnapshot 由 Run 单独固定。相同 SHA 改 PRD / configuration / 环境须新建 Snapshot；改 Policy 或用户明确发起另一轮测试须新建 Run，完全相同的 Snapshot / Policy 可以被新轮次复用。禁止新增 `UNIQUE(project_id, commit_sha)` 或其他阻止同 SHA 重测的唯一约束。重复提交同一请求使用原幂等键返回原 Run；显式新轮次使用新请求身份并保留既有 Run、Verdict 与历史。Job retry、Mission retry 和 Execution retry 仍是原 Run 内追加运行历史，不等于偷偷创建另一轮测试。

每个 v0.4 受控 Run 在首次 Provider 调用前建立且只建立一次 §23.4 的逻辑 TaskWorker / 主 AgentSession 绑定。进程尚未启动、WAITING_INPUT 或恢复中可以没有活跃 PID / lease，但不能另建第二个绑定或把 Run 分给无关 Worker。不同 Run，包括同一 Project 下不同 feat / MR，可以通过各自绑定并发执行；独占约束不是 Project 级锁。

Web bootstrap 的幂等键按 Project 绑定规范化测试输入：repository 去首尾空白、commit 转小写，PRD/configuration 保持原始字节，Policy 按完整生效规则比较（包括 Gate 与 Coverage，默认值和无语义顺序不影响等价性）。同键同测试输入返回原 Run；同键不同测试输入在写入 Artifact 或 Canonical 行之前返回冲突，保留既有 Run、Snapshot 与历史。SourceSnapshot Fingerprint 仍遵循第 9 节：branch 只是参考标签，不参与 Source 或 bootstrap 幂等身份；不同 branch 标签可以引用相同固定 commit 的共享 Snapshot，既有 Snapshot 的标签不被重写。

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

## 15. TestImplementation

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

当前 Python / pytest MVP 接受 `TEST_IMPLEMENTATION` / CREATE Proposal：`test_case_keys`、repository_url、commit_sha、file_path、symbol、framework、language，以及可选 `code`。所有 Case 必须 ACTIVE 且属于同一 Project / SourceSnapshot，repository / commit 必须匹配不可变 Snapshot。HyperTest 验证 Python 语法；Agent 不能自称实现已经通过正式测试。

生成的 `code` 保存为内容寻址 Artifact，`artifact_uri` 和 `source_sha256` 固定其内容；仅允许安全的 `tests/**/*.py` 路径。应用 Commit 不因生成测试而改变。Runner 在临时副本中覆盖未跟踪的安全测试路径，禁止覆盖 Snapshot 中已跟踪文件。没有 code 的 Proposal 可引用 Snapshot 中已有的受控测试位置。

Validation Status：PENDING、VALIDATED、REJECTED、STALE。Verifier 接受后创建 PENDING，只有 Runner 在源内容和可执行目标校验后标记 VALIDATED。生成 Artifact 的 checksum 参与 fingerprint，便于追加新测试版本而不覆盖旧实现。执行前后重新校验源码 Hash 与 Snapshot，验证失败不能成为成功事实。

新实现、ImplementationTestCase links、Proposal acceptance、AuditEvent、OutboxEvent 在同一事务提交。关系数组仅属于 Proposal 输入，不是 Canonical persistence。

---

## 16. TestExecution

TestExecution 表示一次由 HyperTest Runner 控制、具有明确输入和环境边界的测试执行。

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

## 17. Evidence

Evidence 表示由受信任执行或采集链产生、用于支持测试事实或 Finding 的不可变证据。

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

### 18.1 v0.4 受控 GitLab Issue 集成（本分支实现，真实提单待验收）

`external_issue_ref` 本身只是可选关联字段，不能单独证明 GitLab 创建 Issue 或指派成功。本分支已实现受控集成，Agent 可提交 typed Issue Request，引用同一授权范围内已接受 Finding、固定 Run / SourceSnapshot、已校验 Evidence 及负责人建议。HyperTest 按项目预配置的 integration、操作授权与负责人映射验证请求，不能把 Agent 给出的任意项目、用户或 URL 当作已批准目标。

外部创建 / 指派属于受控集成副作用，不是 Agent 直接写 Finding 或持有 GitLab token。平台持久保存请求身份、Finding 关联、目标、映射依据和 correlation / idempotency key；同一逻辑请求不能因重试重复提单，Issue 去重也不能合并或改写不同 Run 的 Canonical Finding。需要人工决策时使用持久输入流程并恢复同一主会话。

只有校验目标 GitLab 响应或回查确认 Issue 的真实身份后，才登记 `external_issue_ref` 和派单结果。超时或连接中断后不能确定是否已创建时，明确记录“结果未知”，先按 correlation 查询 / 人工核实，不盲目再次创建。请求失败、Issue 已创建或负责人已指派均不等于产品缺陷已确认、修复或 Gate 已放行。该 Operational 记录由本分支 `0014_harness_operations` 实现，约束见 §23.7；注入 HTTP transport 回归不等于真实 GitLab 提单验收。

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

## 20. Mission

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

## 21. MissionAttempt

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

## 22. MissionProposal

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

## 23. AgentSession

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

持久会话是外部原生 thread / session 与受控工作副本的持续身份，不要求同一个 CLI PID 永久常驻。原生 `provider_session_id` 初次由 Provider 真实返回后固定；恢复必须引用该身份，同一主 Session 不能变更 Provider、覆盖已有原生引用或用新原生会话冒充恢复。原生认证 / 会话运行时保存在绑定的宿主 Harness 节点，平台 Canonical 数据库状态及数据库 / GitLab 集成凭证不进入 Vendor Session。

### 23.1 DurableJob 与 WorkerHeartbeat

DurableJob 表示用户提交的平台工作请求，属于 Operational State，不是用户可见测试任务 TestRun 或 Canonical Testing Semantic Chain 的新事实节点。v0.3 中它调度现有 Planner、Mission Runtime、Runner 与 Gate；v0.4 中它仍承担持久请求 / 租约 / 取消，但必须在原 RunExecutionBinding 下调用持久 Harness 和所属领域服务，不变成另一个自研通用 Agent Loop。

`durable_jobs` 使用 UUIDv7 主键，project_id / test_run_id 为关系 FK；EXECUTE_MISSION 必须具有同一 Run 的 mission_id，其他类型禁止该引用。retry_of_job_id 关联显式重试的历史请求。支持 ADVANCE_RUN、EXECUTE_MISSION、EXECUTE_TESTS、EVALUATE_GATE、PREPARE_WORKSPACE。

ADVANCE_RUN 在 Git / Agent 前对受支持 backend 调用 Runner fingerprint 进行只读就绪预检。先验证 operation ownership 并提交释放 Run / Job 行锁，预检后以有效 lease / admission 再进入调度；Docker daemon / 可信镜像不可用或 local 未显式启用时，不启动 Git / Agent、不创建 Execution / Evidence、不自动安装或拉取镜像。预检只属于 Operational Readiness，不构成正式执行事实或环境预约；独立 EVALUATE_GATE 不依赖此预检。

ADVANCE_RUN 请求必须恰选一种源方式：`prepare_workspace: true` 且不传 workspace，或提供非空 workspace 且 `prepare_workspace: false`（缺省）。自动方式在同一 Job 内调用既有 pinned checkout 服务，再继续 Planner 周期；保留原 GitHub HTTPS 白名单、固定 commit 与干净 tracked source 校验，其他 Host 仍使用已有 workspace。准备不占 max_steps，不新增 Job / Mission 类型，也不在成功并重新验证归属前创建 AgentSession / MissionAttempt。后续 Attempt / Execution 继续归属同一 Job。

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

以下字段与约束由 `0013_run_bindings` 实现；生产已完成至 `0014_harness_operations` 的[独立迁移与保全验收](../ADR013_PRODUCTION_DEPLOYMENT.md)，旧历史不回填：

| 字段 | 目标语义 |
|---|---|
| `id` | UUIDv7 PK，稳定 Binding 身份 |
| `test_run_id` | NOT NULL FK → TestRun，`UNIQUE(test_run_id)` |
| `logical_worker_id` | NOT NULL UUID，`UNIQUE(logical_worker_id)`；该 Run 唯一逻辑 TaskWorker，不是进程 PID 或 `DurableJob.worker_id` |
| `primary_agent_session_id` | NOT NULL FK → AgentSession，UNIQUE；只绑定本 Run 的一条主 Session |
| `harness_host_id` | NOT NULL，稳定的宿主 Harness 节点引用；指向原生会话 / 认证运行时所在节点，不以临时 IP / 容器名代替 |
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
6. 新建 / execute / resume 等会启动 Provider 工作的 Bridge 调用，以及业务 typed tool 写入 / 正式结果提交，必须具有当前 Binding / epoch 和有效 Job claim，并匹配相应 Run / Mission / Attempt 范围。Run 级问答 / 报告等使用明确 Run 范围，不伪造阶段所有者。已取消、失联、旧 epoch、旧 claim 或错误范围的迟到执行请求不得继续工作或提交；相同 provider session 字符串本身不是授权。Bridge / Provider 不持有 Canonical 数据库或 GitLab 集成凭证，不拥有 Canonical 状态写权限。
7. Binding 生命周期和恢复决策写 Audit / Outbox，与状态更新事务提交；事件保存归属、旧新 epoch、原因和受控操作结果，不保存认证、原生对话或推理。Binding 不参与 Coverage、Evidence manifest 或 Gate State Hash。

执行授权与管理 / 恢复授权必须分开。可信 HyperTest 服务身份可以持有窄 management capability，明确限定 Binding、primary / native Session、原 call_id 和要检查 / 清理的历史 generation。即使该调用原 Job claim 已撤销，也可查询 get_call、只读核验既有会话 / workspace，或 interrupt / close 该受控旧调用以完成取消、失联处理和资源回收。该权限不启动新的 Provider 工作，不 resume 推理、不建立替代会话、不提交 Canonical 结果，也不把旧 owner 恢复成有效执行者。

管理操作必须显式匹配目标调用与历史 epoch；按旧 generation 清理不得影响新 epoch 的活动调用。若需要关闭整个主 Session / 删除其持久 workspace，还须满足 Run 终结或不可恢复失败的明确清理授权，不能仅因一个旧 Job 被取消而破坏仍可恢复的主会话。管理查询 / 清理的结果只用于受控恢复和审计；随后若要执行 Provider，仍必须重新通过当前 epoch / active claim 的执行准入。

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

- 先按原有规则结束失联 Job / Attempt / Execution 并保留历史，绑定进入 RECOVERY_REQUIRED。确认旧 owner 与外部调用已经被 fence / 中断后，才在同一绑定递增 `binding_epoch`；状态 / epoch 及审计按同一事务提交。无法确认旧调用是否仍运行时保持 RECOVERY_REQUIRED，不先启动第二个 owner。
- 在无聚合行锁时验证原 Harness 节点、已固定原生 Session、受控 workspace 及 pinned source Hash；返回后再次验证新 epoch / 当前恢复授权。不能用 Agent 保存的 Hash、自报完成或新会话代替核验。
- 核验成功后回到 ACTIVE，在同一逻辑绑定 / 主 Session 下使用按原规则新建的 Job / Attempt / Execution。不得重开 INTERRUPTED Job、复用失效 token、覆盖旧 Attempt 或自动重放结果未知的外部执行。
- 原生会话 / workspace 丢失、被篡改或无法恢复时，明确使绑定 / 主 Session 失败并停止当前 Run 的执行，保留任务与已接受事实供查看；替代主 Session 必须由用户明确开始新 Run / 轮次。不得悄悄改 `primary_agent_session_id`、换 Provider / Harness 节点或用另一 PID 创建新 thread 冒充恢复。

### 23.5 v0.4 持久 Harness 的受控自驱边界（本分支已实现）

宿主 Harness 在同一主会话中串行完成分析、风险识别、测试设计、实现、请求正式执行、失败诊断和报告。平台容器中的 TaskWorker 保持任务归属、租约和治理；窄 Host Bridge 仅托管允许的 Provider session / 调用，不承担 Planner、Canonical Verifier、Runner 事实认证或 Gate。具体目标 tools / transport profile 由 TMP 与 ADR-013 定义，不通过修改现有 wire version 偷渡语义。

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

## 24. 核心数据库表

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

当前代码另有 §9 的 `0011_execution_environments` 与 `0012_api_environment_v2`。`0013_run_bindings` 新增 `run_execution_bindings` / `run_input_requests`；`0014_harness_operations` 新增 §23.7 的 `run_harness_states`、`run_tool_calls`、`run_reports`、`runtime_control_requests`、`gitlab_issue_operations` 及状态 / 关系保护。以上 v0.3 表清单和 SQL 示例保留历史基线；生产已完成 ADR-013 切换，当前 schema 为 `0014_harness_operations`。ADR-014 不增加迁移；功能实现和部署分别记录。

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

所有 Agent 创建的 Canonical Entity 必须追溯到 Mission、MissionAttempt、MissionProposal。

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

如果 Decision 为 PASS / RELEASE_READY，则至少需要 verified OFFICIAL Execution Evidence，除非 Policy 显式配置 evidence waiver。

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

## 38. 最小数据闭环

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

## 39. 状态所有权

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
| 持久主 AgentSession（v0.4 目标） | HyperTest Task Runtime / Agent Gateway 管理身份及生命周期，宿主 Harness 托管原生运行时 |

Agent 不直接拥有任何 Canonical Lifecycle。

---

## 40. 写权限矩阵

| Actor | Requirement | Risk | TestCase | Execution | Evidence | Finding | Verdict |
|---|---|---|---|---|---|---|---|
| Agent | Proposal | Proposal | Proposal | Request | Read | Proposal | No |
| Runner | No | No | No | Write | Write | No | No |
| Verifier | Accept | Accept | Accept | Read | Verify | Validate | No |
| Gate | Read | Read | Read | Read | Read | Read | Write |
| User | Controlled | Controlled | Controlled | Trigger | Read | Manage | Override by Policy |

---

## 41. Schema Migration Policy

使用 Alembic。

规则：No destructive migration without backfill；No enum semantic changes in-place；No dropping canonical column in same release；Deprecate → migrate → remove。

v1 初期不使用 PostgreSQL native ENUM，使用 varchar + application enum + CHECK constraint，以便协议快速演进。

v0.4 的 Binding / Session 生命周期、唯一 / FK、epoch fencing 与 typed tools 需要 additive migration、版本化契约和成套验收。旧 Run / Session / Attempt / Job 的身份、原生引用与历史解释不因目标规则而回填或合并；新的绑定不能用改写旧结果代替显式恢复或新测试轮次。

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

---

## 47. 最终领域结构

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
