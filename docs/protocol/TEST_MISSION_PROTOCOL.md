# Test Mission Protocol Specification

**Protocol Name:** TMP  
**Full Name:** Test Mission Protocol  
**Version:** v0.1  
**Status:** Draft  
**Owner:** HyperTest

---

## 1. 目标

Test Mission Protocol（TMP）定义 HyperTest 与外部 Agent Harness 之间的稳定协议。

支持目标包括 Codex、Claude Code、Pi、OpenCode 以及 Future Agent Harnesses。

TMP 不定义 Agent 内部如何 reason、plan、spawn subagent、manage context、retry tools；这些属于 Agent Harness 自身能力。

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

输入：Requirement[]、Risk[]、Policy、Existing Test Cases。  
输出：`TestCaseProposal[]`。

### IMPLEMENT_TESTS

输入：TestCase[]、Repository、Testing Framework Context、Constraints。  
输出：`ImplementationProposal[]`。

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
  "proposal_id": "PROP-301",
  "type": "TEST_CASE",
  "operation": "CREATE",
  "object": {},
  "rationale": "...",
  "source_refs": [],
  "confidence": 0.91
}
```

Proposal Operation：CREATE、UPDATE、DEPRECATE、LINK、UNLINK。v1 不建议开放 DELETE。

---

## 15. RequirementProposal

```json
{
  "type": "REQUIREMENT",
  "operation": "CREATE",
  "object": {
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
  "type": "RISK",
  "operation": "CREATE",
  "object": {
    "requirements": ["REQ-17"],
    "category": "concurrency",
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
  "type": "TEST_CASE",
  "operation": "CREATE",
  "object": {
    "requirements": ["REQ-17"],
    "risks": ["RK-21"],
    "title": "并发请求不允许超过 dailyLimit",
    "priority": "P0",
    "type": "concurrency",
    "preconditions": [],
    "steps": [],
    "expected": []
  }
}
```

---

## 18. ImplementationProposal

```json
{
  "type": "TEST_IMPLEMENTATION",
  "operation": "CREATE",
  "object": {
    "cases": ["TC-31"],
    "file": "tests/test_daily_limit.py",
    "symbol": "test_concurrent_daily_limit"
  },
  "artifacts": [
    {
      "type": "git_diff",
      "ref": "artifact://A-23"
    }
  ]
}
```

---

## 19. FindingProposal

```json
{
  "type": "FINDING",
  "operation": "CREATE",
  "object": {
    "classification": "PRODUCT_DEFECT",
    "severity": "S2",
    "title": "并发转账导致 dailyLimit 超卖",
    "test_cases": ["TC-31"],
    "evidence": ["EV-22", "EV-23"]
  },
  "confidence": 0.93
}
```

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
