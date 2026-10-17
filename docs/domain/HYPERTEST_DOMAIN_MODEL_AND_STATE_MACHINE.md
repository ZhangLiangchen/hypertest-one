# HyperTest Domain Model & State Machine Specification

**Document Status:** Draft / Normative  
**Version:** v0.3
**Parent Documents:**

- HyperTest Whitepaper v1.0
- HyperTest Technical Architecture v0.3
- Test Mission Protocol Specification v0.3

**Applies To:** HyperTest Canonical Testing State

---

## 1. 文档目的

本文正式定义 HyperTest 的领域模型、实体关系、生命周期、数据库约束和持久化规则。

本文是 HyperTest Canonical State 的规范性定义。如果本文与上层架构文档在 Field、Relationship、Lifecycle、Uniqueness、Persistence、State Transition 上冲突，以本文为准。

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
source_fingerprint     char(64)
created_at             timestamptz
```

创建后禁止 UPDATE。PRD、Git Commit、Configuration 任一变化都创建新 Snapshot。

`0006_immutable_contracts` 通过 PostgreSQL Trigger 拒绝 SourceSnapshot 内容变更与 DELETE，包括尚未被 TestRun 引用的 Snapshot；语义完全相同的 no-op UPDATE 可通过。不修改历史 Snapshot 来修复或重解释已有 Run。

Fingerprint：

```text
SHA256(project_id + repository + commit_sha + prd_sha256 + configuration_sha256)
```

唯一：`UNIQUE(project_id, source_fingerprint)`。

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

MVP 对 `(test_run_id, sequence_no)` 建立唯一约束，sequence_no > 0；FINAL 必须同时有 state_snapshot_hash、evidence_manifest_sha256、finalized_at。`TestRun.current_verdict_id` 指向最近 FINAL 决策。重复评估只有在 Run / Scope / Policy / State Hash / status / decision / Evidence Manifest 均匹配时返回已有 Verdict，变化创建新 sequence，不能复用与本次决策矛盾的历史记录。

数据库 Trigger 禁止改变 FINAL 内容，只允许 FINAL → REVOKED 并设置 revoked_at，其他字段必须不变；REVOKED 同样不可重写，FINAL / REVOKED 禁止 DELETE。VerdictEvidence / VerdictFinding 保存决策引用，Canonical 内容、links、审计和 Outbox 事务性提交。

当前 `canonical-gate/v1` 要求：非空 Requirement / Risk / ACTIVE Case、Risk identification 与设计维度覆盖完整、每个 Case 最新 OFFICIAL 执行匹配 SourceSnapshot Commit、COMPLETED + aggregate PASS + exit code 0 + per-case PASS、通过 ExecutionEvidence 关联的 VERIFIED trusted EXECUTION_METADATA / JUNIT，且 Artifact hash 验证成功。最新按 queued_at、ID 倒序选择，不回退挑选更早的成功结果。

缺失/未完成/不确定事实产生 BLOCKED；执行失败或 policy-blocking confirmed PRODUCT_DEFECT 产生 RELEASE_BLOCKED；全部满足产生 RELEASE_READY。默认阻断严重程度为 BLOCKER、CRITICAL；`compiled_policy.gate.blocking_finding_severities` 可配置，但 BLOCKER 不可豁免。当前基线不提供 Official Evidence waiver。设计覆盖完成本身不形成放行结论。

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

### 23.1 DurableJob 与 WorkerHeartbeat

DurableJob 表示用户提交的平台工作请求，属于 Operational State。它调度现有 Planner、Mission Runtime、Runner 与 Gate，不代替这些组件，也不成为 Canonical Testing Semantic Chain 的新事实节点。

`durable_jobs` 使用 UUIDv7 主键，project_id / test_run_id 为关系 FK；EXECUTE_MISSION 必须具有同一 Run 的 mission_id，其他类型禁止该引用。retry_of_job_id 关联显式重试的历史请求。支持 ADVANCE_RUN、EXECUTE_MISSION、EXECUTE_TESTS、EVALUATE_GATE、PREPARE_WORKSPACE。

请求 identity、类型、FK、payload、idempotency_key 与 created_at 创建后不可变。payload 只保存工作区、Runner、timeout、work limit 等运行选项；Requirement / Risk / Case 等 Canonical 状态继续保存在对应关系表。`UNIQUE(test_run_id, idempotency_key)` 保证相同输入重复提交返回原 Job，不同输入复用同一 Key 被拒绝；部分唯一索引保证每个 Run 至多有一个 QUEUED / RUNNING / CANCEL_REQUESTED Job。

```text
QUEUED → RUNNING → SUCCEEDED / FAILED / INTERRUPTED
QUEUED → CANCELLED
RUNNING → CANCEL_REQUESTED → CANCELLED
```

SUCCEEDED 表示调度请求成功返回，不表示质量结论为 PASS；应读取 Job result 的 stop reason 和正式 Verdict。终态 Job 不可改写，所有 Job 禁止 DELETE。显式重试创建新的 Job 并记录 retry_of_job_id，不能原地清空错误、重开终态或覆盖历史结果。

Worker 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取 QUEUED Job，记录 worker_id、lease_token、heartbeat_at、lease_expires_at。使用数据库时钟验证租约；每个受控 Canonical commit 在 flush 前后检查 Run → Job 锁、状态和 token。租约失效或取消后的旧 Worker 不得提交 Canonical 状态。

`0008_job_ownership` 为 MissionAttempt / TestExecution 增加 nullable `durable_job_id` FK 和索引。归属创建后不可修改，必须匹配同一 TestRun；ADVANCE_RUN 可以拥有其内部 Attempt / Execution，EXECUTE_MISSION 只可拥有指定 Mission 的 Attempt，EXECUTE_TESTS 只可拥有 Execution。历史 / direct API 创建的 null 归属保留，不使用 started_at 等宿主时间猜测或回填归属。取消与失联恢复只更新该 Job 关系下的执行历史。

租约过期后 Job 进入 INTERRUPTED；其未完成 Mission 的 Attempt 进入 FAILED、Mission 进入 RETRYING，未完成 Execution 进入 ERROR / INCONCLUSIVE，并保留错误和历史。取消则记录 CANCEL_REQUESTED / CANCELLED，并中断受控外部工作。恢复不会自动重放可能已发生的外部操作；用户检查后显式重试。系统不宣称外部执行 exactly-once。

Docker 资源使用不可变 Job UUID label：包括 staging / execution containers 和预创建的 source / result volumes。恢复事务先提交领域终态，再于无数据库行锁时尽力清理精确匹配该 Job 的受控资源，记录 `job.resources_cleanup` AuditEvent / OutboxEvent、可用性与删除数量。Docker daemon 不可访问、未受控的 provider 残留进程等情况仍需 Operator 检查；清理记录不是 Execution Evidence。

`worker_heartbeats` 记录 Worker 的 last_seen_at 和 active_job_id，支持 API / Web 区分队列等待与可用 Worker。其 liveness 是运行数据，不影响测试事实可信度。Job 生命周期写 AuditEvent 与 OutboxEvent；它们与队列状态在同一事务提交。

---

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

当前迁移 head 为 `0008_job_ownership`，在上述队列表之后增加 Attempt / Execution 的显式归属关系和约束。历史行不推断归属；已有归属记录时禁止降级丢失关系。

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

Planner 在 Requirement 和 Risk 缺口满足后，对剩余维度创建 DESIGN_TESTS Mission。全部 Risk 达到基线表示测试设计覆盖完成；当前完整 MVP 继续创建 IMPLEMENT_TESTS，随后返回 EXECUTION_REQUIRED / EXECUTION_IN_PROGRESS，失败时创建 DIAGNOSE_FAILURE，最后返回 VERDICT_REQUIRED。早期切片的 TEST_DESIGN_COVERAGE_COMPLETE 是设计阶段边界，不是 TestRun 的 PASS / FINAL Verdict。

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
