# Test Mission Protocol Specification

**Protocol Name:** TMP  
**Full Name:** Test Mission Protocol  
**Version:** v0.3
**Status:** Draft  
**Owner:** HyperTest

---

## 1. 目标

Test Mission Protocol（TMP）定义 HyperTest 与外部 Agent Harness 之间的稳定协议。

支持目标包括 Codex、Claude Code、Pi、OpenCode 以及 Future Agent Harnesses。

TMP 不定义 Agent 内部如何 reason、plan、spawn subagent、manage context、retry tools；这些属于 Agent Harness 自身能力。

Web 提交的 DurableJob 由独立 Worker 执行；bounded Run test cycle controller 可以依次调度多个符合 TMP 的 Mission、正式 Runner 执行与 Gate 评估。它根据 deterministic Planner 的 Canonical State gap 推进工作，不接管 Agent reasoning；max_steps 限制的是平台工作单元，单个 Mission 的 Proposal / Verifier / Attempt 契约不变。Job 是平台运行请求，不能把 Job SUCCEEDED 等同于测试 PASS 或把 Job payload 当作 Canonical State。

TMP 定义的是：

> **HyperTest 如何表达测试任务，以及 Agent 如何向 HyperTest 提交工作结果。**

---

## 2. 设计目标

TMP 必须具备：Provider-independent、Versioned、Typed、Schema-driven、Auditable、Resumable、Idempotent、Extensible、Policy-aware、Evidence-aware。

---

## 3. 核心抽象

TMP 有五种核心对象：

```text
TestMission
MissionContext
AgentEvent
MissionProposal
MissionResult
```

辅助对象：

```text
ExecutionRequest
EvidenceReference
```

---

## 4. 协议方向

```text
HyperTest
   │
   │ TestMission
   ▼
Agent Harness
   │
   ├── AgentEvent ─────────────► HyperTest
   ├── Tool Invocation ─────────► HyperTest MCP
   └── MissionResult ───────────► HyperTest
```

---

## 5. TestMission

Mission 是不可变任务描述。Mission 进入 READY 后不得原地改变目标；需要改变目标时，应 cancel old mission + create new mission。

HyperTest 在数据库层冻结已离开 CREATED 的 Mission 身份、优先级、协议版本、目标、spec 及摘要、幂等键与创建者信息。Retry 只创建新的 Attempt，不能改写原 Mission 或把状态退回 CREATED 重新编辑；已冻结 Mission 不允许删除。

---

## 6. 基础 Schema

```json
{
  "protocol": "hypertest.tmp/v1alpha1",
  "mission_id": "M-1024",
  "test_run_id": "TR-100",
  "type": "DESIGN_TESTS",
  "objective": "为 dailyLimit 需求设计风险驱动测试",
  "priority": "P0",
  "targets": {
    "requirements": ["REQ-17"],
    "risks": ["RK-21", "RK-22"]
  },
  "context": {},
  "constraints": {},
  "acceptance_criteria": {},
  "output_contract": {},
  "execution_profile": {},
  "metadata": {}
}
```

---

## 7. Mission Type

第一版标准 Mission Type：

```text
ANALYZE_REQUIREMENTS
ANALYZE_IMPACT
ANALYZE_RISKS
DESIGN_TESTS
REVIEW_TESTS
IMPLEMENT_TESTS
REVIEW_IMPLEMENTATION
DIAGNOSE_FAILURE
INVESTIGATE_FINDING
REPAIR_TEST
RETEST_ANALYSIS
VERIFY_COVERAGE
```

`EXECUTE_TESTS` 通常由 Runner 处理，而不是 Coding Agent。Agent 通过 `request_execution` 请求正式执行。

---

## 8. Mission 输入输出约定

### ANALYZE_REQUIREMENTS

输入：PRD、Git Diff、Relevant Code、Existing Requirements。  
输出：`RequirementProposal[]`。

### ANALYZE_RISKS

输入：Requirement[]、Implementation Context、Historical Findings。  
输出：`RiskProposal[]`。

### DESIGN_TESTS

输入：同一 Project / SourceSnapshot 的 Canonical Risk[]、PolicySnapshot 引用、已有设计覆盖与 missing dimensions；可附带相关 Requirement / Existing TestCase 引用。
输出：`TestCaseProposal[]`。

v0.2 必须使用 `proposal_type = TEST_CASE`、`operation = CREATE`。Agent 不写 Canonical TestCase 或 Canonical Lifecycle。Risk 关系以 `object_payload.risk_keys` 提议，由 HyperTest 解析并持久化为 `RiskTestCase` Join Table。

Planner 创建的 Mission 固定 `targets.risks`、`context.risks`（已接受的 Canonical 内容）、`context.coverage` 与 `acceptance_criteria.risk_coverage_gaps`。后者记录 Risk key 和该 Mission 创建时的 missing dimensions，并保存 `coverage_rule_version` 和 `coverage_policy_hash`。规则由当前 TestRun 的不可变 PolicySnapshot 编译，默认 `risk-design-baseline/v1`，自定义维度为 `risk-design-policy/v1`。同一 Hash 表示解析后的相同覆盖规则，维度输入顺序不影响身份。Agent 无法用返回值覆盖这些约束；Verifier 拒绝与固定 Policy 不符的版本或 Hash。没有 Hash 的历史基线 Mission 只对未改变的基线规则兼容。

Verifier 要求整批 Proposal 合法，并至少对一个仍缺失的目标 Risk / dimension 形成覆盖进展。允许一次 Mission 只补齐部分维度；剩余缺口由下次 Planner 创建 Mission。重复规划复用仍可执行的 Mission，历史 Mission spec 不被覆盖。设计阶段全部满足后，当前完整 MVP 继续规划 IMPLEMENT_TESTS；早期切片的 `TEST_DESIGN_COVERAGE_COMPLETE` 仅代表设计阶段边界，不表示已经执行测试、产生 Runner Evidence 或形成质量 Verdict。

### IMPLEMENT_TESTS

输入：ACTIVE Canonical TestCase[]、固定 Repository / Commit、Testing Framework Context、现有实现、Constraints。
输出：`TEST_IMPLEMENTATION` / CREATE Proposal[]，可通过 `object_payload.code` 返回生成测试源码。HyperTest 保存 Artifact；Runner 独立验证并执行，Agent 不更新 Canonical validation status。

### DIAGNOSE_FAILURE

输入：TestCase、Implementation、Execution、Evidence、Application Context。  
输出：`FindingProposal[]` + Diagnosis。

---

## 9. Mission Context

Context 使用引用优先，不把所有对象直接嵌进 Mission。

```json
{
  "context": {
    "source_snapshot": "SS-21",
    "requirements": ["REQ-17"],
    "risks": ["RK-21"],
    "policy_snapshot": "POL-3",
    "workspace": {
      "repo_path": "/workspace/repo"
    }
  }
}
```

Agent 可以通过 HyperTest MCP 获取详细对象。

原则：

> **Reference First, Materialize When Necessary.**

---

## 10. Constraints

Constraints 定义 Agent 能做什么。

```json
{
  "constraints": {
    "filesystem": {
      "read": ["**"],
      "write": ["tests/**"],
      "deny": ["src/**"]
    },
    "network": {
      "mode": "restricted"
    },
    "source_modification": false,
    "max_duration_seconds": 1800
  }
}
```

---

## 11. Acceptance Criteria

Acceptance Criteria 定义“做到什么程度算完成”。

```json
{
  "acceptance_criteria": {
    "required_risk_categories": [
      "functional",
      "boundary",
      "failure",
      "concurrency"
    ],
    "requirement_coverage": 1.0,
    "unresolved_targets_allowed": false
  }
}
```

Agent 不能通过一句 `done` 宣告 Mission 完成。最终由 HyperTest Verifier 判断。

---

## 12. Output Contract

TMP 强制支持结构化结果：

```json
{
  "output_contract": {
    "schema": "hypertest.result/test-design/v1",
    "human_summary": true
  }
}
```

支持 Structured Output 的 Agent Harness 应直接将 Schema 映射到 Provider 能力。

当前 DESIGN_TESTS 的运行时 Output Contract 同时提供 `proposal_type = TEST_CASE`、`operation = CREATE`、`object_payload_schema` 与 `result_schema`。Schema 来自 HyperTest 协议模型，Provider Adapter 负责传递，最终仍由 HyperTest Verifier 强制验证。

五种已支持的 Mission（ANALYZE_REQUIREMENTS、ANALYZE_RISKS、DESIGN_TESTS、IMPLEMENT_TESTS、DIAGNOSE_FAILURE）都提供上述完整 Typed Contract，包括各自的 Proposal 类型和 Payload Schema；仅给出 Schema 名称不能作为 Agent 理解提交字段的前提。

Codex CLI Adapter 使用官方 `--output-schema` 和 `--output-last-message`：Agent 在 read-only 工具沙箱中分析源代码，将结构化 JSON 作为最终响应，由 CLI 宿主保存结果文件。Agent 不需通过 Shell 写结果文件；生成测试源码仍通过 Proposal `code` 字段提交。Provider JSONL 只作为运行遥测，不能代替最终结果。

Codex 的严格结构化输出投影使用本 Mission 的 Typed Payload，关闭对象的额外字段并列出全部 required 字段，nullable 字段仍允许 null。该投影只生成当前 MVP 所需的 protocol / mission_id / status / summary / proposals；TMP 可选的 artifacts / execution_requests / unresolved / metrics / provider_metadata 保持原协议语义，由 HyperTest 的完整 TMP 模型补齐默认值。这个 Adapter 映射不修改 Canonical Schema 或降低 Verifier 校验。参考 [官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema) 与 [严格结构化输出约束](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas)。

---

## 13. MissionResult

```json
{
  "protocol": "hypertest.tmp/v1alpha1",
  "mission_id": "M-1024",
  "status": "COMPLETED",
  "summary": "完成 dailyLimit 风险驱动测试设计",
  "proposals": [],
  "artifacts": [],
  "execution_requests": [],
  "unresolved": [],
  "metrics": {},
  "provider_metadata": {}
}
```

Mission Result Status：

```text
COMPLETED
PARTIAL
BLOCKED
FAILED
CANCELLED
```

`COMPLETED` 只表示 Agent 已提交工作，不代表 HyperTest 已接受 Mission。

---

## 14. Proposal

Agent 的 Domain Output 必须表示为 Proposal。

```json
{
  "proposal_type": "TEST_CASE",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:concurrency:v1",
  "object_payload": {},
  "rationale": "...",
  "confidence": 0.91
}
```

`proposal_type`、`operation`、`idempotency_key`、`object_payload` 为提交边界必填字段；Proposal UUID 由 HyperTest 分配。此 envelope 是当前运行时契约，替代早期未落地示例中的 `type` / `object` 简写，不涉及已发布字段重命名。

Proposal Operation 的长期模型包括 CREATE、UPDATE、DEPRECATE、LINK、UNLINK。当前 Requirement / Risk / TestCase / Implementation / Finding Canonical Verifier 仅支持 CREATE；其他操作不能绕过 Verifier。v1 不建议开放 DELETE。

---

## 15. RequirementProposal

```json
{
  "proposal_type": "REQUIREMENT",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:requirement:v1",
  "object_payload": {
    "title": "支持 dailyLimit",
    "description": "...",
    "source_ref": "PRD#3.2"
  },
  "rationale": "...",
  "confidence": 0.95
}
```

---

## 16. RiskProposal

```json
{
  "proposal_type": "RISK",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:concurrency-risk:v1",
  "object_payload": {
    "requirement_keys": ["REQ-17"],
    "category": "CONCURRENCY",
    "title": "并发转账超出额度",
    "severity": "HIGH",
    "description": "并发转账可能造成额度超卖"
  },
  "rationale": "...",
  "confidence": 0.91
}
```

---

## 17. TestCaseProposal

```json
{
  "proposal_type": "TEST_CASE",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:concurrency-test:v1",
  "object_payload": {
    "risk_keys": ["RK-21"],
    "title": "并发请求不允许超过 dailyLimit",
    "description": "并发提交累计超出 dailyLimit 的转账请求，检查最终已接受金额和请求结果。",
    "priority": "P0",
    "test_type": "CONCURRENCY",
    "preconditions": ["账户 dailyLimit 已配置", "当前累计转账金额为零"],
    "expected_result": "已接受请求的总金额不超过 dailyLimit，超出额度的请求明确失败。",
    "confidence": 0.95
  }
}
```

Payload 要求：至少一个非空 `risk_keys`；非空 `title`、`description`、`expected_result`；合法 `test_type`；`preconditions` 为字符串列表；priority 默认 P1，confidence 可省略且必须在 [0, 1]。Risk keys 会去除首尾空白、排序并去重。支持 FUNCTIONAL、BOUNDARY、FAILURE、CONCURRENCY、SECURITY、PERFORMANCE、RECOVERY，以及领域规范保留的 NEGATIVE、CONSISTENCY、COMPATIBILITY、RELIABILITY、UPGRADE、DATA。

Verifier 在 Canonical 写入前完成：

1. Result / proposal / payload schema 和 CREATE 操作校验。
2. 所有 Risk 均存在、属于当前 Project / SourceSnapshot，且非 OBSOLETE；跨快照引用拒绝。
3. Mission-scoped Proposal idempotency 校验，batch 中重复 key 或已使用 key 都拒绝；拒绝 Attempt 的原 Proposal 记录保留。
4. 根据 source snapshot、归一化 description / preconditions / expected_result、test_type、排序的 Canonical Risk fingerprints 计算 `case_fingerprint`。标题、优先级与 confidence 不影响精确意图去重。
5. 规划 Mission 的不可变 missing dimensions 与当前覆盖进展校验；仅生成无关维度不能使 Mission 完成。
6. 在一个事务中提交 Canonical TestCase、关系表、Proposal ACCEPTED、AuditEvent、OutboxEvent 和 Mission / Attempt 成功状态；任何一项失败均回滚。

同 fingerprint 的多条合法 Proposal 指向同一 Canonical TestCase，保留各自 Proposal 来源，不重复用例或 `test_case.accepted` 事件。preconditions 的顺序具有语义；文本只折叠空白，不改变大小写。跨 Snapshot 复用必须 clone / derive，不能直接引用旧 Snapshot 的 Canonical 行。

v0.2 TestCase 的 `description` / `test_type` / 字符串 `expected_result` 是首次实现的域模型选择，替代旧草案未实现的 objective / case_type / steps / expected 示例；完整约束见领域规范 §14。

---

## 18. ImplementationProposal

```json
{
  "proposal_type": "TEST_IMPLEMENTATION",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:implementation:v1",
  "object_payload": {
    "test_case_keys": ["TC-31"],
    "repository_url": "https://github.com/example/payments",
    "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "file_path": "tests/test_daily_limit.py",
    "symbol": "test_concurrent_daily_limit",
    "framework": "pytest",
    "language": "python",
    "code": "from concurrent.futures import ThreadPoolExecutor\nfrom app.limits import Account\n\ndef test_concurrent_daily_limit():\n    account = Account(daily_limit=100)\n    with ThreadPoolExecutor(max_workers=2) as pool:\n        accepted = list(pool.map(account.transfer, [60, 60]))\n    assert sum(accepted) == 1\n"
  }
}
```

示例应用符号需根据被测仓库调整。当前支持 Python / pytest，payload 必须提供至少一个当前 Snapshot 下的 ACTIVE test_case_keys。Repository 与 Commit 必须匹配 Canonical SourceSnapshot；file_path 必须为安全相对 Python 路径，symbol 由 Python identifier / `::` 构成。正式 Runner 进一步限制安全 `tests/**/*.py` 和 pytest test function 目标。

可选 code 必须可编译为 Python，生成路径必须在 tests/ 下。HyperTest 计算 source_sha256 并保存只写入一次的内容寻址 Artifact；Canonical TestImplementation 记录 artifact_uri / source_sha256。Fingerprint 使用规范化 repository / commit / file_path / symbol，生成源码另加入内容 hash。旧实现可被精确去重，但不同源码产生新版本；Case links 使用 ImplementationTestCase 关系表。

没有 code 表示引用已存在于固定 SourceSnapshot 的测试；Runner 校验 tracked 路径与内容。生成代码仅在临时执行副本中覆盖未被 Snapshot 跟踪的测试文件，不修改应用快照。Verifier 创建 PENDING 实现；VALIDATED 是 Runner 校验结果，不是 Agent 提交字段。

---

## 19. FindingProposal

```json
{
  "proposal_type": "FINDING",
  "operation": "CREATE",
  "idempotency_key": "daily-limit:finding:v1",
  "object_payload": {
    "classification": "PRODUCT_DEFECT",
    "severity": "CRITICAL",
    "title": "并发转账导致 dailyLimit 超卖",
    "description": "同一账户的两个并发额度预留请求均被接受，累计金额超出每日额度。",
    "root_cause": "额度读取和更新缺少原子性。",
    "test_case_keys": ["TC-31"],
    "requirement_keys": ["REQ-17"],
    "risk_keys": ["RK-21"],
    "evidence_keys": ["EV-22", "EV-23"],
    "confidence": 0.93
  }
}
```

当前 DIAGNOSE_FAILURE 的 Proposal 必须为 FINDING / CREATE；INVESTIGATE_FINDING 保留为后续 Mission 类型。evidence_keys 至少一个，必须是本 TestRun 的 VERIFIED Evidence；PRODUCT_DEFECT 必须有 RUNNER / SYSTEM / EXTERNAL_VERIFIED 可信支持。Case / Requirement / Risk 引用限制在同一 Project / Snapshot 的有效 Canonical State。Source commit 不一致的执行证据不能跨快照混用。

Verifier 以 project、classification、归一化 description 和 run-scoped affected component（Run ID + 排序 Case keys）去重，保存 FindingEvidence / FindingTestCase / FindingRequirement / FindingRisk Join Tables；接受后的初始状态为 NEW，Agent 不提交 CONFIRMED 或 Resolution。Proposal acceptance、Canonical 行/links、AuditEvent、OutboxEvent 在同一事务完成。

用户受控生命周期操作必须提供 reason，可提供 expected_row_version 防止覆盖并发修改。CONFIRMED 需要 VERIFIED supporting Evidence；PRODUCT_DEFECT 还要求可信 trust level。RESOLVED 必须提供 Resolution；REOPENED 清除旧 resolution / resolved_at，历史通过审计保留。质量结论仍由 Gate 决定。

---

## 20. Agent Event Protocol

Mission 执行过程中，Agent 可以持续发送事件：

```json
{
  "event_id": "AE-1022",
  "mission_id": "M-1024",
  "session_id": "AS-10",
  "type": "ACTIVITY",
  "timestamp": "...",
  "payload": {}
}
```

标准 AgentEvent Type：SESSION_STARTED、MISSION_STARTED、ACTIVITY、TOOL_STARTED、TOOL_COMPLETED、FILE_CHANGED、EXECUTION_REQUESTED、WAITING_INPUT、PROGRESS、WARNING、ERROR、RESULT_SUBMITTED、MISSION_FINISHED。

Provider Event 不直接暴露给 HyperTest Core。

---

## 21. ACTIVITY / PROGRESS

ACTIVITY 主要服务 UI、Audit、Debug。

```json
{
  "type": "ACTIVITY",
  "payload": {
    "category": "repository_analysis",
    "message": "Analyzing transfer concurrency control"
  }
}
```

PROGRESS 可选，Agent 无法可靠估计时不得伪造百分比。

---

## 22. Provider Mapping

TMP 不要求 Provider 原生理解 Mission，Adapter 负责 TMP Mission → Provider-specific session / turn / request。

### Codex Mapping

```text
HyperTest AgentSession → Codex Thread
TestMission           → Codex Turn
Output Contract       → Structured Output Schema
AgentEvent            ← Codex Streaming Event
```

### Claude Mapping

```text
HyperTest AgentSession → Claude Agent Session / Runtime
TestMission            → Claude Task / Message
HyperTest Tools        → Claude Tool Schema
AgentEvent             ← Claude Streaming Events
```

Provider-specific model 永远不能成为 HyperTest Domain Contract。

---

## 23. TMP 与 MCP 分工

```text
TMP = Task Contract
MCP = Runtime Domain Tool Contract
```

TMP 告诉 Agent“你要完成什么”；MCP 允许 Agent 在执行过程中读取 Testing State、提交 Proposal、申请 Execution。

---

## 24. HyperTest MCP Read Tools

```text
hypertest.get_mission
hypertest.get_requirement
hypertest.get_risk
hypertest.get_test_case
hypertest.get_coverage
hypertest.get_execution
hypertest.get_evidence
hypertest.get_finding
```

---

## 25. HyperTest MCP Proposal Tools

```text
hypertest.propose_requirement
hypertest.propose_risk
hypertest.propose_test_case
hypertest.propose_implementation
hypertest.report_finding
```

这些操作只写 Proposal Store，不直接写 Canonical State。

---

## 26. Execution Request

```json
{
  "type": "ExecutionRequest",
  "mission_id": "M-103",
  "test_cases": ["TC-31"],
  "implementation": {
    "commit": "agent-worktree-abc",
    "targets": [
      "tests/test_daily_limit.py::test_concurrent_daily_limit"
    ]
  },
  "environment": "sit-payment",
  "purpose": "VALIDATION"
}
```

Execution Purpose：EXPLORATORY、VALIDATION、OFFICIAL、REPRODUCTION。

只有 OFFICIAL Runner Evidence 默认可进入 Release Gate。

---

## 27. Agent Shell Execution

Agent 自己执行 pytest、curl、docker、kubectl 等结果默认是 exploratory context，除非 HyperTest Runner 对 Execution 进行了采集和认证。

> **Agent tool output is context. Runner output is evidence.**

---

## 28. EvidenceReference

Agent 引用 Evidence ID，而不是复制全部 Evidence：

```json
{
  "evidence_id": "EV-200",
  "execution_id": "EX-20",
  "type": "JUNIT",
  "hash": "sha256:..."
}
```

---

## 29. Human Input

Agent 需要人工输入时发出 WAITING_INPUT：

```json
{
  "type": "WAITING_INPUT",
  "payload": {
    "question_id": "Q-1",
    "question": "测试环境中应使用哪个租户？",
    "options": ["tenant-a", "tenant-b"]
  }
}
```

HyperTest UI 展示，用户回答后 resume mission，Provider-specific resume 由 Adapter 完成。

---

## 30. Approval

对于 production mutation、database delete、external side effect、secret access 等危险操作，Mission 可声明审批策略。Adapter 尽量映射 Provider Approval / Sandbox 能力；Provider 不支持时由 HyperTest Tool Layer 拦截。

---

## 31. Retry

TMP 将 Retry 分两类：

- **Agent Internal Retry**：command failed、edit failed、tool timeout，由 Harness 自己处理。
- **Mission Retry**：Agent crashed、result schema invalid、provider unavailable，由 HyperTest 重新调度。

Mission Attempt 必须独立记录，历史 Attempt 不覆盖。

接受 required outputs 的事务必须同时保存 `mission.completed` AuditEvent 与 OutboxEvent；SUBMITTED 或 Agent 自称 COMPLETED 不触发该平台事件。创建、开始、拒绝、超时、中断、取消和重试控制决策形成可审计的 Mission 生命周期，不能只从 Requirement / Case 的接受事件推测。生命周期事件只携带领域状态与原因，不承载 Vendor 日志、raw Proposal payload 或 reasoning。

Worker 租约过期或进程中断时，平台保留失联 Attempt 并标记 FAILED，将 Mission 标记 RETRYING；旧 lease token 不能再提交 Canonical 结果。Job 记录 INTERRUPTED，不自动重放外部执行。用户确认后显式重试生成新的 Job；Mission 重试仍追加新的 Attempt，Execution 重试仍创建新 Execution。Web 刷新或 API 请求结束不会撤销已经入库的 Job。

---

## 32. Idempotency

所有写操作必须支持 `idempotency_key`：

```json
{
  "proposal_id": "PROP-200",
  "idempotency_key": "M-100:testcase:daily-limit:concurrency"
}
```

避免 Agent Retry 产生重复 Case / Risk / Finding。

---

## 33. Cancellation

HyperTest 可以 cancel mission；Adapter 对 Provider interrupt 为 best-effort。

Canonical State 必须保证：

> 未 Accepted Proposal 不影响 State。

---

## 34. Error Model

统一 Error：

```text
PROVIDER_ERROR
AUTH_ERROR
RATE_LIMIT
TIMEOUT
SANDBOX_ERROR
TOOL_ERROR
SCHEMA_ERROR
POLICY_VIOLATION
CONTEXT_ERROR
EXECUTION_ERROR
UNKNOWN
```

Provider-specific Error 保留在 `provider_metadata`。

---

## 35. Schema Version

核心对象必须包含 protocol/version，例如 `hypertest.tmp/v1alpha1`。

演进路径：v1alpha1 → v1alpha2 → v1beta1 → v1。

同一 Major 优先 additive change；禁止无版本重命名 required field、改变字段语义或删除 enum value。

---

## 36. Capability Negotiation

Adapter 注册 Harness Capability：

```json
{
  "harness": "codex",
  "capabilities": {
    "structured_output": true,
    "streaming": true,
    "session_resume": true,
    "filesystem": true,
    "shell": true,
    "mcp": true,
    "subagent": true
  }
}
```

Planner / Scheduler 可基于 Capability 选择 Worker。

---

## 37. Agent Selection

Mission 声明需要的 Capability，而不是硬编码必须使用 Codex / Claude。Scheduler 可考虑 Capability、Cost、Latency、Reliability、Model Quality、Workspace Affinity、Historical Success。

MVP 可简单配置 `default_agent = codex`。

---

## 38. Security Boundary

TMP 明确区分 Agent Identity、User Identity、HyperTest Service Identity、Runner Identity。

Agent 对 HyperTest MCP 的访问权限由 Mission Token 控制，至少绑定 mission_id、test_run_id、project_id、allowed_tools、allowed_resources、expiration。

Agent Session 不拥有项目全局管理员权限。

---

## 39. Audit

Mission Created、Mission Dispatched、Tool Called、Proposal Submitted、Proposal Accepted、Execution Requested、Evidence Created、Verdict Changed 都必须产生 Audit Event。

---

## 40. End-to-End Example

```text
PRD + commit abc123 + SIT
        │
        ▼
M-1 ANALYZE_REQUIREMENTS
        │
        ▼
RequirementProposal[]
        │ Verifier accept
        ▼
REQ-1 / REQ-2 / REQ-3
        │
        ▼
M-2 ANALYZE_RISKS
        │
        ▼
REQ → RISK
        │
        ▼
M-3 DESIGN_TESTS
        │
        ▼
M-4 IMPLEMENT_TESTS
        │
        ▼
hypertest.request_execution
        │
        ▼
EX-100 → EV-1 / EV-2 / EV-3
        │ failure
        ▼
M-5 DIAGNOSE_FAILURE
        │
        ▼
FindingProposal
        │
        ▼
Gate → RELEASE_BLOCKED / RELEASE_READY
```

整个过程中 Codex 可以被换成 Claude，Canonical Testing State 不受影响。

---

## 41. TMP 核心不变量

1. Agent 不直接拥有 Canonical State。
2. Mission 描述目标，不规定 Agent 内部 reasoning。
3. Provider-specific Session 不进入 HyperTest Domain。
4. Agent Result 是 Submission，不是事实。
5. Runner Evidence 才能成为正式执行事实。
6. Mission Acceptance 由 HyperTest Verifier 决定。
7. TMP 必须允许 Agent Harness 被替换。

---

## 42. 协议定位

TMP 不应演进成 Generic Agent Protocol，而必须始终保持：

> **Testing-domain-specific Agent Work Protocol**

它描述 Requirement、Risk、Case、Implementation、Execution、Evidence、Finding，而不描述 LLM thinking steps。

---

## 43. 最终定义

Test Mission Protocol 是：

> **HyperTest 将 Testing Intent 编译成 Agent 可执行工作，并将 Agent Intelligence 安全地重新纳入 Testing State 的标准协议。**

```text
Testing State
     │
     ▼
Test Mission
     │
     ▼
Agent Harness
     │
     ▼
Proposal / Request
     │
     ▼
HyperTest Verification
     │
     ▼
Canonical State / Runner
     │
     ▼
Evidence
     │
     ▼
Next Mission
```

TMP 的价值不在于规定 Codex 或 Claude Code 应该如何思考，而在于：

> **无论底层 Agent 如何变化，HyperTest 对软件测试的理解、状态、证据和治理协议始终保持稳定。**
