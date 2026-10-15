# HyperTest Domain Model & State Machine Specification

**Document Status:** Draft / Normative  
**Version:** v0.1  
**Parent Documents:**

- HyperTest Whitepaper v1.0
- HyperTest Technical Architecture v0.1
- Test Mission Protocol Specification v0.1

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

---

## 5. 时间、锁与删除规范

- 所有时间字段使用 `timestamp with time zone`，内部统一 UTC，API 使用 ISO 8601。
- 所有允许更新的 Canonical Entity 包含 `row_version bigint`，使用 Optimistic Lock。
- Canonical Testing State 默认禁止 Hard Delete。
- 生命周期结束使用 DEPRECATED、SUPERSEDED、CANCELLED、REVOKED、OBSOLETE 等状态表示。
- Hard Delete 只允许未接受 Proposal、临时缓存、无引用 Workspace 等非 Canonical 数据。

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

---

## 11. TestRun

TestRun 表示针对一个 SourceSnapshot，在某套 Policy 下的一次自治测试活动。

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

```text
id
key
project_id
source_snapshot_id
case_fingerprint
title
objective
case_type
priority
preconditions JSONB
steps JSONB
expected_result JSONB
lifecycle_status
confidence
derived_from_id nullable
created_by_type
created_by_ref
created_at
updated_at
row_version
```

Case Type：FUNCTIONAL、BOUNDARY、NEGATIVE、FAILURE、CONCURRENCY、CONSISTENCY、COMPATIBILITY、SECURITY、PERFORMANCE、RELIABILITY、UPGRADE、DATA。

TestCase ↔ Requirement 使用 `test_case_requirements`；TestCase ↔ Risk 使用 `test_case_risks`。

Fingerprint：

```text
SHA256(source_snapshot + normalized objective + case_type + linked risk fingerprints)
```

唯一：`UNIQUE(source_snapshot_id, case_fingerprint)`。

生命周期：ACTIVE → SUPERSEDED / DEPRECATED。

PASS、FAIL、AUTOMATED、NOT_AUTOMATED 都不是 TestCase Lifecycle。Automation Status 从 TestImplementation 派生。

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
validation_status
created_by_type
created_by_ref
created_at
updated_at
```

TestImplementation ↔ TestCase 使用 `implementation_test_cases` Join Table，因为一个测试函数可以覆盖多个 Case，一个 Case 也可拥有多个 Implementation。

Fingerprint：

```text
SHA256(repo + commit + file_path + symbol)
```

唯一：`UNIQUE(source_snapshot_id, implementation_fingerprint)`。

---

## 16. TestExecution

TestExecution 表示一次由 HyperTest Runner 控制、具有明确输入和环境边界的测试执行。

```text
id
key
test_run_id
mission_id nullable
execution_request_id nullable
retry_of_execution_id nullable
idempotency_key
purpose
runner_backend
environment_id
environment_fingerprint
source_commit
execution_spec_sha256
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

---

## 21. MissionAttempt

Mission Retry 不修改原 Mission，而是创建新的 MissionAttempt。

```text
id
mission_id
attempt_no
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
test_case_requirements
test_case_risks
test_implementations
implementation_test_cases
test_executions
execution_test_cases
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
    case_fingerprint char(64) NOT NULL,
    title varchar(512) NOT NULL,
    objective text NOT NULL,
    case_type varchar(32) NOT NULL,
    priority varchar(16) NOT NULL,
    preconditions jsonb NOT NULL DEFAULT '[]',
    steps jsonb NOT NULL DEFAULT '[]',
    expected_result jsonb NOT NULL DEFAULT '{}',
    lifecycle_status varchar(32) NOT NULL,
    confidence numeric(4,3),
    derived_from_id uuid REFERENCES test_cases(id),
    created_by_type varchar(32) NOT NULL,
    created_by_ref text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    row_version bigint NOT NULL DEFAULT 1,
    UNIQUE(project_id, key),
    UNIQUE(source_snapshot_id, case_fingerprint)
);
```

### TestExecution

```sql
CREATE TABLE test_executions (
    id uuid PRIMARY KEY,
    key varchar(64) NOT NULL,
    test_run_id uuid NOT NULL REFERENCES test_runs(id),
    mission_id uuid REFERENCES missions(id),
    retry_of_execution_id uuid REFERENCES test_executions(id),
    idempotency_key varchar(512) NOT NULL,
    purpose varchar(32) NOT NULL,
    runner_backend varchar(64) NOT NULL,
    environment_id varchar(255) NOT NULL,
    environment_fingerprint char(64) NOT NULL,
    source_commit varchar(64) NOT NULL,
    execution_spec_sha256 char(64) NOT NULL,
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

Requirement Coverage 第一版：

```text
covered active risks / all required active risks
```

若 Requirement 尚无 Risk，coverage = UNKNOWN，而不是 100%。

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
