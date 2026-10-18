# Test Mission Protocol Specification

**Protocol Name:** TMP  
**Full Name:** Test Mission Protocol  
**Version:** v0.4
**Status:** Draft  
**Owner:** HyperTest
**Accepted target decision:** [ADR-013 — Containerized Platform and Persistent Harness](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
**Implementation boundary:** 本版包含已接受但尚未实现的目标 profile；文档版本不升级现有 wire schema 或宣称部署已迁移。

---

## 1. 目标

Test Mission Protocol（TMP）定义 HyperTest 与外部 Agent Harness 之间的稳定协议。

支持目标包括 Codex、Claude Code、Pi、OpenCode 以及 Future Agent Harnesses。

TMP 不定义 Agent 内部如何 reason、plan、spawn subagent、manage context、retry tools；这些属于 Agent Harness 自身能力。

目标工作方式为：一个 SUT 对应一个 Project，一个 feat / MR 的固定完整 SHA 的一次测试轮次对应一个 TestRun；同一 TestRun 绑定一个逻辑任务 Worker 和一个持续主 Harness 会话，Harness 自驱串行完成分析、设计、实现、申请正式执行、诊断和报告。不同 TestRun 可以并发；不向同一 Run 派发多个任务 Worker 或并行阶段。输入仍由不可变 SourceSnapshot / PolicySnapshot 固定，不能仅按 SHA 去重而禁止显式复测。

平台服务及任务 Worker 容器化，Agent Harness 与最小 Host Harness Bridge 留在宿主机。容器 Worker 通过受控接口托管会话；Provider 登录、原生会话及其运行工作目录由宿主集成管理，不能因容器重建而丢失会话身份。部署边界见 ADR-013，绑定、租约、生命周期和持久化约束以领域模型为准。

当前 `hypertest.tmp/v1alpha1` 实现仍由 Web 提交 DurableJob、独立 Worker 调用 bounded Run test cycle controller，按 deterministic Planner 的 Canonical State gap 逐个启动 Mission；每次新 Attempt 创建会话，人工等待按 §29 恢复原会话。`max_steps` 限制当前平台工作单元；Job SUCCEEDED 不等于测试 PASS，Job payload 不是 Canonical State。持续会话目标需实现 §6.1 的新 profile，不能从本次文档调整推断当前 controller 已改变。

周期先以所选 Runner 的只读 fingerprint 预检实际 daemon / 可信镜像或显式 local 启用条件，成功后才进行 Git / Agent；前后重新验证归属，预检 I/O 不持 Run / Job 行锁。失败不创建正式 Execution / Evidence，预检成功也不等于测试通过。独立 Gate-only 操作不要求 Runner。

`ADVANCE_RUN` 可在同一持久请求内先准备固定源 checkout（`prepare_workspace: true`），或接收已有 workspace；二者互斥。源准备是进入 Mission 之前的平台步骤，不消耗 max_steps、不产生 Agent Intelligence。Git I/O 不持有 Run / Job 行锁；准备后重新验证归属与 lease，失败或失联时不得开始 Agent。该扩展不改变 TestMission schema、Mission identity 或 Canonical 状态所有权。

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
RunWorkflowContract / ReportSubmission（目标 profile）
HarnessBridgeRequest / HarnessBridgeEvent（目标宿主传输）
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

Mission 是不可变的类型化阶段工作描述，不等于用户完整测试任务、Harness Session 或一次 Provider 进程。用户任务由 TestRun 承载；目标持续会话可以依次处理同一 Run 的多个 Mission / Attempt。Mission 进入 READY 后不得原地改变目标；需要改变目标时，应 cancel old mission + create new mission。

HyperTest 在数据库层冻结已离开 CREATED 的 Mission 身份、优先级、协议版本、目标、spec 及摘要、幂等键与创建者信息。Retry 只创建新的 Attempt，不能改写原 Mission 或把状态退回 CREATED 重新编辑；已冻结 Mission 不允许删除。

---

## 6. 基础 Schema

以下是当前已实现 `hypertest.tmp/v1alpha1` Mission envelope；保留其字段、枚举和冻结历史。

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

### 6.1 目标持续会话 profile 与协商

ADR-013 的目标 profile 为 **`run-persistent-harness/v1`**，只在显式协商的 **`hypertest.tmp/v1alpha2`** 上启用；这是待实现的协议版本，不能把 `profile` 等新字段附加到现有 v1alpha1 请求后假定支持。新 Run admission 固定 wire version、profile、Provider / Harness 能力与策略，任何一项不支持时明确拒绝，不能降级为每阶段新建会话并声称仍满足本 profile。已冻结 v1alpha1 Mission 保留原执行语义；迁移不得改写其版本、spec / hash、Attempt、Job 或 Session 历史。

目标 `RunWorkflowContract` 引用固定 Project、TestRun、SourceSnapshot、PolicySnapshot、MR / feat 来源及完整 SHA，声明串行阶段、验收规则、允许工具与运行预算。该 Contract 是受控任务上下文，不新建 Canonical 事实链，也不把源输入保存在聊天历史中代替数据库。

稳定运行身份引用领域模型的 `RunExecutionBinding` / `run_execution_bindings`：`logical_worker_id`、`primary_agent_session_id`、`harness_host_id`、`workspace_id` 和单调递增的 `binding_epoch`。这些是规划中的 Operational State，不是当前数据库已有字段；关系、唯一性和不可变约束以领域模型为准。原生 Provider session ID 仅在首次创建事件前允许未绑定，之后不可被新 session 替换。`logical_worker_id` 表示专属于该 Run 的逻辑 Worker 身份，不能与某次领取的 `Job.worker_id`、租约 token、容器 / PID 混用；进程可在显式 fencing 后替换，逻辑绑定、主 AgentSession 与原生 Provider session 保持。一个物理 Worker 实例同一时刻只推进一个 Run，完成后可服务其他任务。

正常阶段转换或 `WAITING_INPUT` 不增加 binding_epoch。阶段完成只结束相应 Mission / Attempt；不得关闭主 Session、删除 Run 工作目录或建立新的 Provider 会话。新阶段按相同 Session 继续；失败后显式 Mission Retry 追加 Attempt，但仍引用该 Run 的主 Session。`WAITING_INPUT` 保留绑定、会话和工作目录，释放实时租约和计算资源；恢复需要原主 Session 和精确原生引用。其缺失必须显式进入失败 / 恢复决策，不能换 Provider 或新建会话冒充续接。Run 结束 / 取消后的受控 close 与清理遵守保留策略，不能删除 Canonical、问答或审计历史。

### 6.2 自驱串行工作与平台决策

Harness 在同一会话内决定如何分析、调用工具和继续探索，依次开展需求 / 风险分析、测试设计、实现、申请正式执行、读取结果、必要诊断和报告。Mission / Attempt 是类型化授权、提交及验收边界；一个阶段可以因未满足覆盖而有多个串行 Mission。Planner 是确定性的准入、依赖、覆盖和预算 guard：检查 Harness 提出的下一阶段请求，返回允许的冻结 Mission 或有理由的拒绝 / 缺口；它不重新实现 Harness 的通用思考 / 调用循环。

Agent 的 Proposal 由 Verifier 原子接受后才成为 Canonical；`request_execution` 只申请由可信 Runner 执行，不能把 Agent shell 结果升级为正式事实；Gate 根据固定 Policy 与 Canonical / Runner 事实作出 Verdict。Harness 读取工具响应决定继续、提问或提交报告，不能以自己“完成”跳过平台必要条件。工具等待、Provider turn 结束或单个 Mission 完成均不等于整个 Run 结束。

目标 profile 保留每 Run 一个活跃 DurableJob 和一次一个有效 owner，活动 Job 内串行推进工作；跨步骤 / 重试仍保存不可变 `durable_job_id` 所有权。新 lease 不能转移既有 Attempt / Execution 的 Job FK。不同 Run 可以并发，并按 Worker、宿主 Harness 和可信 Runner 的各自容量准入；等待人工回答释放 CPU 不释放该 Run 的逻辑独占绑定。

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

协议的目标工具模式允许 Agent 通过 HyperTest MCP 获取详细对象。当前 MVP 由 Runtime 预先读取必要对象并注入 Context，使用结构化最终结果提交 Proposal；完整 MCP 域工具尚未实现。

原则：

> **Reference First, Materialize When Necessary.**

物化上下文不得静默丢失固定输入。Web bootstrap 输入集的 PRD / configuration 在 AgentSession / Attempt 创建前按原始 UTF-8 与快照 Hash 校验，空配置也必须存在；缺失或损坏则停止。无 PRD Artifact URI 的既有 direct hash-only Snapshot 保持可选配置上下文；存在物化配置时仍必须验证。此 legacy 兼容不改写或补造 Snapshot 真值，持久化规则以领域模型 §9 为准。

Repository origin 只作为无内嵌认证的源身份传递：拒绝 HTTP(S) userinfo 与可解析 URL 的 password，认证由宿主 Git 管理；保留无密码 SSH username / scp / 本地 origin。Runtime 对历史 Snapshot 也在 AgentSession / Attempt 前检查，不修改旧身份或把含凭据 URL 送入 Agent Context。输入校验的 HTTP 422 只输出 `type` / `loc` / `msg`，不回显 `input` / `ctx` 或请求 body。该边界不等于任意秘密扫描或所有日志的全面脱敏。

ANALYZE_REQUIREMENTS / ANALYZE_RISKS / DESIGN_TESTS / IMPLEMENT_TESTS 的 Runtime Context 附加 `testing_scope`，其 repository / commit 必须来自绑定的 SourceSnapshot，不能由 PRD 或 Mission spec 中的同名值覆盖。它区分 PRD 明确要求的被测应用行为、应用自身约束与测试实施指令：依赖、装载方式、测试文件位置、源文件不可变和正式 Runner 执行等指令仍须遵守，但不能仅因此升格为应用 Requirement / Risk，或要求测试不存在于被测仓库的 HyperTest 内部机制。设计阶段把这些指令用于实施约束或前置条件，实现阶段不得虚构平台接口、假通过测试或执行事实。若固定仓库本身实现 Runner / guard 等产品功能且 PRD 明确要求测试，该功能仍是有效被测范围；不得按名称一刀切排除。已有 Canonical target 真正超出范围或无法实现时应如实报告冲突，不能改写历史、静默忽略或伪报 COMPLETED。此执行期范围说明不改写原 PRD / configuration、Snapshot Hash、冻结 Mission spec 或 Planner / Verifier / Gate 规则；语义范围以领域模型 §12 为准。

---

### 9.1 Controlled execution environment context

对领域模型 §9 的非空环境绑定，Runtime 在 AgentSession / Attempt 创建前校验定义、固定 image ID、依赖/launcher 身份及安全 tracked ASGI 模块。`context.execution_environment` 由 HyperTest 从 SourceSnapshot 提供并覆盖同名未受信 Mission 输入；不能由 PRD、Agent Proposal 或当前可变镜像 tag 重绑定。旧 NULL 路径不伪造此上下文。所有 Docker 检查均在数据库行锁外完成，随后按既有状态/租约重新 admission。

上下文含规范化 profile/service 请求、image ID/platform、依赖清单和锁/launcher hash。API profile 另含固定 `service_base_url=http://127.0.0.1:8765`、`base_url_environment_variable=HYPERTEST_BASE_URL`：正式 Runner 负责启动服务和探测就绪，再执行 pytest。Agent 只生成真实 HTTP 断言源码，使用该变量和可用 httpx（`trust_env=False`）或标准库客户端；不得以 TestClient、ASGITransport、mock 或直接应用函数调用代替本轮 HTTP API 行为。Agent 工作区不保证有运行中的服务，也不允许生成测试自行启动/停止 SUT、安装依赖或修改环境。

API-v2 上下文另含 `pytest_isolation`：平台固定 `-c /dev/null --noconftest --rootdir=/repo`，不加载仓库 pytest 配置或任何 conftest；生成的 HTTP 测试及 fixtures 必须在提交的测试模块内自包含。该规则仅属于新 profile；旧 API-v1 / pytest-v1 继续按原 launcher 身份执行，不能静默升级历史。

服务健康探测成功、Agent 自行 curl/pytest、模型自报成功都不是 Case PASS。正式服务启动/退出/日志与执行结果由 Runner 采集，缺少环境事实产生 ERROR/INCONCLUSIVE，产品 HTTP 断言失败产生正式 FAIL 后再 DIAGNOSE_FAILURE。环境上下文不修改冻结 Mission spec、原 PRD/configuration 或 Canonical Proposal/Gate 规则。

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

IMPLEMENT_TESTS 的 `runner_validation_required` 由 HyperTest 在接受实现 Proposal 后交给正式 Runner 满足。Agent 仍须完成任务要求的代码与追溯产出；完整 Proposal 可标记 COMPLETED，不因 Agent 工作区没有 pytest 或尚未进行正式执行而自行降为 PARTIAL。缺少实际任务产出时仍须如实报告未完成。Implementation 的 `symbol` Schema 明确反映现有 pytest test function 约束；仅有模块名或类名不能作为可执行 Canonical 目标。

当前 v1alpha1 Codex Adapter 为每次 execution session 的 Proposal key 声明 `ASid:` 前缀，Prompt 与 Provider Schema 使用同一个前缀；新 Attempt 创建新 session，因而可区分拒绝后的重试。目标 profile 不能沿用“新 Attempt 必须新 Session”的隐含前提：应由平台为每个 Attempt 提供独立且稳定的 Proposal namespace，随工具重发保持一致，在新 Attempt 下变化；Session ID 不再承担 Attempt 唯一性。两种 profile 都保留 Canonical 的 `(mission_id, idempotency_key)` 唯一规则、冻结 Mission spec 及全部拒绝 / 重试历史。

Codex 的严格结构化输出投影使用本 Mission 的 Typed Payload，关闭对象的额外字段并列出全部 required 字段，nullable 字段仍允许 null。该投影生成 protocol / mission_id / status / summary / proposals / input_request；普通最终结果的 input_request 为 null，等待输入结果按 §29 提供问题且不包含 Proposal。TMP 可选的 artifacts / execution_requests / unresolved / metrics / provider_metadata 保持原协议语义，由 HyperTest 的完整 TMP 模型补齐默认值。旧冻结 Mission 的结果 Schema 可以由当前 Runtime 在内存中投影新增的输入控制字段和状态，不能改写持久 spec、spec_hash 或其业务输出契约。这个 Adapter 映射不修改 Canonical Schema 或降低 Verifier 校验。参考 [官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema) 与 [严格结构化输出约束](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas)。

---

## 13. MissionResult

```json
{
  "protocol": "hypertest.tmp/v1alpha1",
  "mission_id": "M-1024",
  "status": "COMPLETED",
  "summary": "完成 dailyLimit 风险驱动测试设计",
  "proposals": [],
  "input_request": null,
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
WAITING_INPUT
```

`COMPLETED` 只表示 Agent 已提交工作，不代表 HyperTest 已接受 Mission。在目标 profile 中，MissionResult 是阶段提交，不是整个 Harness Session 的终止信号；Run 完成还需平台验收、正式执行 / Gate 和 §25.1 的报告提交。

`WAITING_INPUT` 是非终态控制结果，不提交业务 Proposal，也不表示 Mission 已完成；问题、回答及恢复契约见 §29。

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

目标 profile 的桥接事件另以受信 envelope 绑定 TestRun、AgentSession、当前 Mission / Attempt（若适用）、call_id 与 binding_epoch；Provider 原文不能自行指定归属。`MISSION_FINISHED` 不意味着 `SESSION_CLOSED`。会话活动仍为可裁剪遥测，不能作为正式 Result、Evidence 或取消成功的证明。

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

当前 Web 可观察性使用受控活动类型、来源、平台时间和合并计数，不展示上例中的自由文本 message。Adapter 必须在跨越边界前投影 Provider JSONL；推理、命令、路径、输出、消息正文、PRD / 回答和凭据不进入持久活动记录。未知事件只产生固定信号类型；Provider 错误仅保留受控类别和退出码，不持久化 stderr 作为活动或错误详情。原始事件流不是 Result 通道。

`PROVIDER` 与 `CONTROL_PLANE` 来源分开。本地开始 / 恢复 / 结果提交事件和 Worker 心跳不能被计作模型新信号。人工等待恢复继续原 Attempt，但本轮信号按当前 Job 领取次数隔离；没有信号时为未知。活动不改变 Mission 状态、Canonical State、Coverage、Evidence 或 Verdict。

实现采用有界异步队列、约 2 秒窗口合并、每 Attempt 最近 200 条与有上限的只读分页，细则见领域模型 §23.3。有效租约及归属校验失败、繁忙或遥测故障可以丢弃记录，不得阻塞正式 Result 的处理，也不得自动取消、重放或估算百分比。长时间未收到信号的提示必须保留“仍可能正常工作”的含义；WAITING_INPUT、Runner 执行与终态不按模型静默判断。

---

## 22. Provider Mapping

TMP 不要求 Provider 原生理解 Mission，Adapter 负责 TMP Mission → Provider-specific turn / request。目标 profile 一个 Run 的多个 Mission 复用一个主 AgentSession / 原生会话；不能把 Mission 到 Provider Turn 的概念映射解释为每 Mission 创建 Session。

### Codex Mapping

```text
HyperTest AgentSession → Codex Thread
TestMission           → Codex Turn
Output Contract       → Structured Output Schema
AgentEvent            ← Codex Streaming Event
```

当前 v1alpha1 CLI Adapter 用官方 `codex exec -` 的 stdin 传入 UTF-8 Prompt，不把大 PRD 作为 argv 参数；传输与事件流读取并行。严格 `--output-schema`、CLI 写入 `--output-last-message` 的最终响应、read-only sandbox 与非交互审批策略保持。stdin 是 Provider 传输细节，不修改 TMP 消息、权限或 Canonical identity；多兆输入的 subprocess 回归不能用作模型上下文容量或真实模型验收证据。

Codex `thread.started.thread_id` 是真实 Provider 引用，独立于 HyperTest AgentSession / Gateway ID。恢复调用 `codex exec --sandbox read-only resume <明确的 thread UUID> --json --output-schema ... --output-last-message ... -`；resume 子命令自己的输出参数必须显式传递，不能依赖父命令同名选项的默认值。不得使用 `--last`、将旧 AS 占位值推断成原生 ID，或在原生会话丢失时静默新开会话。普通 exec 没有被假定支持 App Server 的实验性 requestUserInput 工具；当前人工输入使用 §29 的结构化控制结果。CLI 能力与语义以 [官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode) 和部署 CLI 的 help 为准。

### Claude Mapping

```text
HyperTest AgentSession → Claude Agent Session / Runtime
TestMission            → Claude Task / Message
HyperTest Tools        → Claude Tool Schema
AgentEvent             ← Claude Streaming Events
```

Provider-specific model 永远不能成为 HyperTest Domain Contract。当前只实现 Codex Adapter；Claude Code、DeepSeek Harness 等属于后续 Provider，只有通过能力协商及会话持续性验收才可启用目标 profile。

### 22.1 宿主 Harness Bridge 目标传输契约

`hypertest.harness-bridge/v1alpha1` 是待实现的容器 Worker ↔ 宿主 Bridge 传输版本，与 TMP wire version / profile 分别协商。初版同机使用限权 Unix domain socket 或等效受控私有端点；后续跨主机必须使用经过认证和加密的传输，不能把无认证本机接口直接暴露到网络。Bridge 仅适配 Provider 生命周期、身份、工作目录和标准化事件 / 结果，不接管测试规划或 Canonical 提交。

允许操作为 `capabilities`、`create_session`（仅 Run 初次绑定）、`restore_session`、`execute`、`resume`、`interrupt`、`close` 与只读 `get_call`；它不是 arbitrary shell / SSH 执行接口。已绑定 Run 上的 execute / resume 必须引用已登记的原生会话，不能隐式 create；具体 CLI 的启动和 resume 差异由 Adapter 封装。

Bridge 区分执行授权与管理 / 恢复授权，不能要求已取消或租约失效的调用继续持有原执行 claim 才能停止和对账：

| 授权类别 | 允许的操作与约束 |
|---|---|
| 执行授权 | `create_session`、`execute`、`resume` 及任何启动新 Provider 工作的操作，必须具有当前可执行 Binding / epoch、有效 Job / claim 与该阶段工具权限；旧 owner / claim / epoch 不得启动工作或提交 Canonical。 |
| 管理 / 恢复授权 | 可信服务身份携带明确的目标 Binding、Session、call 及其历史 generation，可在旧 claim 已撤销后执行 `get_call`、只读核验原会话 / 工作区、`interrupt`、`close` 和既有句柄恢复，以完成对账、fencing 和清理。授权不得扩大到 create / execute / resume、运行新 Provider 工作或 Canonical 提交。 |

只读 `capabilities` 探测使用服务身份。其余调用包含版本、profile、call_id、idempotency_key、TestRun / AgentSession、logical_worker_id、harness_host_id、目标 binding_epoch / call generation、工作目录受控标识和 deadline；执行调用另携有效 Job / claim 及当前 Mission / Attempt（若适用），管理调用另携窄范围服务授权和精确目标。原生 Provider ID 仅作为已持久化的外部引用，由 Bridge 校验匹配；不能允许 Agent 提交任意宿主路径或选择其他用户的会话。`restore_session` 只有在纯粹恢复既有受控句柄且不启动 Provider 工作时可用管理授权；任何启动进程 / turn 的变体仍须执行授权。租约 / 授权材料不进入 Agent Prompt、事件 payload 或报告。

Bridge 和平台共同拒绝以旧 epoch / 旧 claim 执行工作、跨 Run / Session 与并发 execute / resume，同 Session 同时最多一个活跃调用；恢复前需 fencing 旧 owner。对历史 epoch 的查询 / 中断 / 清理，只能由明确指向该历史调用的窄管理授权执行，不能让旧 owner 获得通用续接权限。相同 idempotency key / 同输入返回既有 call 状态或结果，异输入冲突；call_id 贯穿标准化事件、最终结果及确认。Bridge 先登记操作再启动 Provider，返回可查询句柄；不承诺外部 exactly-once。首次创建收到原生 session 引用后必须持久确认，若结果丢失则先对账，不能盲目再次 create。Worker 超时、断线或 ACK 丢失时，先查询 / 对账已登记 call，不能自动重发可能有副作用的 execute / resume。

Bridge 按已授权 deadline / lease watchdog 停止失联调用；interrupt 结果区分请求已受理与进程确已停止。取消先在平台持久化终态 Binding / 取消状态并撤销执行 call / 工具权限，再以窄管理授权尽力 interrupt / close；租约撤销不阻止清理和对账。取消不自行增加 binding_epoch，epoch 只在领域模型允许的显式恢复中递增。可恢复的中断必须确认原调用静止后才能重新获得执行授权；终态取消不能恢复执行。迟到事件 / 结果必须按 owner、claim、epoch、call 和当前状态校验，过期响应不得写 Canonical 或触发新的外部调用；管理对账只可记录受控操作结果。CLI 的 stdout / stderr、原生事件与秘密由 Adapter 投影或受控保留，不直接进入持久活动记录。

---

## 23. TMP 与 MCP 分工

```text
TMP = Task Contract
MCP = Runtime Domain Tool Contract
```

TMP 告诉 Agent“你要完成什么”；MCP 允许 Agent 在执行过程中读取 Testing State、提交 Proposal、申请 Execution。

§24–26 定义目标 MCP 工具面，持续会话 profile 需要可在会话内调用的版本化领域工具。当前 Codex MVP 采用逐 Mission 最终结果通道，不声称已经提供这些运行时工具、Host Bridge 或完整会话级自驱能力。正式 Execution 由平台校验和 Runner 执行，Agent 自行运行命令不能形成正式事实。

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
hypertest.get_run
hypertest.get_policy
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

### 25.1 持续会话的流程与报告工具（目标）

| 工具 | 类型化语义与平台约束 |
|---|---|
| `hypertest.request_mission` | 提交下一阶段的 typed intent；Planner 校验依赖 / 覆盖 / 权限后返回冻结 Mission，不接受 Agent 指定 Canonical 完成状态。 |
| `hypertest.complete_mission` | 提交当前 Attempt 的结构化结果及显式 Proposal batch（可引用本 Attempt 已暂存 Proposal）；Verifier 决定接受与否，调用完成不关闭 Run Session。 |
| `hypertest.ask_user` | 显式选择 `scope=mission` 或 `scope=run`，按 §29.1 持久化受控问题并暂停 Job / 主 Session / Binding；Mission scope 另暂停当前未终态 Mission，Run scope 不重开已完成阶段。 |
| `hypertest.request_execution` | 引用已接受实现、固定输入和受控环境，创建可信 Runner 请求；用 `get_execution` / `get_evidence` 读取正式事实。 |
| `hypertest.request_gate` | 请求平台根据固定 Policy 评估；返回持久 Verdict 引用，不允许 Agent 指定 decision。 |
| `hypertest.submit_report` | 提交版本化 `hypertest.report/run-summary/v1` 报告 Artifact 与引用；平台验证关联和完整性，不能写 Verdict。 |
| `hypertest.request_gitlab_issue` | 按 §30.1 申请受控提单，返回持久的外部操作状态与 Issue 引用。 |

每次写调用携带由平台验证的 Run / 主 Session / binding_epoch 及当前 Mission / Attempt（若适用）、幂等键和输入摘要，重复调用不得重复接受 Proposal、启动测试或提单。工具完成响应包含已持久对象引用或明确的 pending / rejected / failed 状态；Agent 不能以请求已发送当作成功。Token 按 Run / Binding 与具体工具 scope 授权并随阶段更新：Mission scope 绑定当前 Mission / Attempt，阶段边界的 Run scope 不伪造这些引用；只授予该 Run 当前允许的工具及资源。

报告 envelope 至少声明 schema version、TestRun、SourceSnapshot、完整 SHA、PolicySnapshot、summary、coverage / execution / evidence / finding 引用、未完成项及平台 Verdict 引用（若已形成）；Markdown / HTML 正文作为有 hash 的 Artifact 保存。Agent 生成的摘要、解释和建议属于报告内容，质量结论只引用平台已持久 Verdict，未形成时明确标示未判定。平台验证必需阶段、引用范围和内容完整性后才能接受 Run completion；报告写入失败或存在未满足 guard 不得伪报完整周期结束。这里不新增未实现的 MissionType、Canonical Report 表或当前 API 字段。

---

## 26. Execution Request

以下为 v1alpha2 目标工具请求的语义示例，并非当前 v1alpha1 已实现的请求 Schema。授权 / 绑定 envelope 见 §22.1 / §25.1；Agent 不提交任意 shell、动态 commit、镜像或可变环境：

```json
{
  "protocol": "hypertest.tmp/v1alpha2",
  "profile": "run-persistent-harness/v1",
  "idempotency_key": "TR-100:official:implementation-batch-1",
  "test_run_id": "TR-100",
  "mission_id": "M-103",
  "attempt_id": "MA-103-1",
  "source_snapshot_id": "SS-21",
  "policy_snapshot_id": "POL-3",
  "test_case_keys": ["TC-31"],
  "implementation_keys": ["IMPL-31"],
  "environment_ref": "SS-21:execution-environment",
  "purpose": "OFFICIAL"
}
```

Execution Purpose：EXPLORATORY、VALIDATION、OFFICIAL、REPRODUCTION。平台解析 Canonical TestCase / Implementation 及其 Artifact hash，强制匹配本 Run / SourceSnapshot；Runner 独立验证源码、环境和执行目标，冻结 ExecutionSpec 后采集事实。Tool request 仅为受控请求，不能由 Agent 提供的测试工作区路径 / 临时 commit 或自报结果取代该验证。

只有符合固定 Policy、来自可信 Runner 且已经验证的 OFFICIAL Execution / Evidence 可按规则进入 Release Gate。等待执行期间保持主会话身份；Runner 执行和事实提交仍具有独立可审计的身份、取消与幂等边界。

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

本节 JSON 及既有持久化路径描述当前 v1alpha1 控制结果；目标 profile 的 `hypertest.ask_user` 必须保留相同问答与冻结输入语义，并采用 §6.1 的持续绑定。Agent 在关键决策、缺少测试输入或固定输入无法消除的产品歧义阻止任务继续时提出问题：

```json
{
  "protocol": "hypertest.tmp/v1alpha1",
  "mission_id": "M-1024",
  "status": "WAITING_INPUT",
  "summary": "需要确认测试租户",
  "proposals": [],
  "input_request": {
    "question_id": "Q-1",
    "question": "测试环境中应使用哪个租户？",
    "options": ["tenant-a", "tenant-b"]
  }
}
```

question_id 在同一 Attempt 中唯一且最长 128 字符；question 非空、最长 4096 字符；options 最多 8 项，每项非空、最长 256 字符且不能重复。WAITING_INPUT 不得包含 proposals、artifacts 或 execution_requests；非等待结果不得附带 input_request。所有 Question / Answer 是交互与控制记录，不能成为 Requirement、Execution、Evidence 或 Verdict，也不能替代正式 Runner 事实。

Runtime 根据原有 Mission / Attempt / AgentSession / Job 组装可信等待标记，Provider 只提出 question_id / question / options。Worker 在同一事务验证当前 lease 与 Run→Job→Mission 归属，持久化 MissionInputRequest，并将原 Mission、AgentSession 与 DurableJob 转入 WAITING_INPUT，释放 Job lease；不得先在 Runtime 单独提交一半等待状态。暂停后没有活跃 Provider 进程，等待问题不能占用实际 Worker 计算资源。目标 profile 仍保留该 Run 的逻辑 Worker 绑定、主 AgentSession、原生会话和工作目录，不将释放 Job lease 解释为解绑。无 DurableJob 的 direct 调用遇到等待结果必须明确失败，不能留下无法回答恢复的悬空 Mission。

Web 展示问题原文并提交自由回答。回答长度上限 12000 字符，要求 idempotency_key 和预期 row_version：同 key / 同回答重试复用原结果，不同回答或并发过期写入拒绝。回答和问题不可覆盖；同一事务把原 Job 重新排队，保持 Mission、Attempt、AgentSession、Job 与不可变所有权。持久化约束和精确状态转换以领域模型 §23.2 为准。

当前 v1alpha1 重新领取的 Worker 使用新 lease，锁定原 Mission 与已回答问题，校验原 Attempt / Session / Job 归属，并恢复托管副本与明确的原生 Provider thread。问题置为 CONSUMED、Mission / Session 恢复 RUNNING，与 input.consumed / mission.resumed 的成对 Audit / Outbox 一起提交后才调用 Harness.resume；同一 Attempt 多轮问题分别保留独立消费历史。回答仅附加为运行时 human_inputs 上下文，不改变 PRD、configuration、Snapshot、Policy、冻结 Mission spec 或 spec_hash。后续普通最终结果仍通过原 Verifier。

托管 Agent 副本等待期间保留，恢复时依据原 pinned source 重建并验证可信源文件 Hash，不能信任 Agent 自报 Hash。原生会话或副本缺失、篡改、归属不符时明确失败，不用新会话冒充续接。取消清理只删除托管副本并保留问题、回答、Attempt 和拒绝历史；显式失败重试按既有新 Job / Attempt 规则追加记录。以上 v1alpha1 路径不单凭 fake Harness 回归宣称真实模型闭环验收，实际版本与证据登记在第一阶段验收报告。目标 profile 的新 claim 还需校验稳定 RunExecutionBinding / binding_epoch，必要时先显式 fence 原物理进程，再由同一逻辑 Worker 恢复；不能启动第二个 Worker / 新原生会话继续该 Run。失败后按 §31 追加 Attempt 的恢复也保留原绑定，丢失会话时必须明确进入恢复或新 Run 决策。

### 29.1 目标 profile 的 Mission / Run scope 问题（未实现）

`hypertest.ask_user` 必须显式声明 `scope=mission` 或 `scope=run`，由平台验证问题实际所处的工作边界；目标 v1alpha2 工具不把现有 v1alpha1 的 mission_id / attempt_id 改为 nullable，也不改写旧问题 Schema：

- **Mission scope**：存在当前未终态 Mission / Attempt 时，沿用 `MissionInputRequest` 的归属、问答和同 Attempt 恢复规则；问题必须引用当前 Run 的绑定、主 Session、当前 Job 及该 Mission / Attempt。
- **Run scope**：用于前一 Mission 已完成后的阶段边界、报告准备或 GitLab 策略决策，创建规划中的独立 `RunInputRequest`，归属同一 RunExecutionBinding、主 Session 与当前 DurableJob；问题有稳定 question_id、不可变问题 / 选项 / 归属及受控回答状态。不得虚构 Mission / Attempt、重开已完成 Mission 或改变历史 Attempt 状态以容纳该问题。

两个 scope 均在 Run 锁下验证当前有效 Binding / epoch / Job claim，并共同保证同一 Run 同时最多一个 PENDING / ANSWERED 问题，而不是在两张表各允许一个。提出问题、保存已完成步骤、Job / 主 Session / Binding 进入 WAITING_INPUT、释放实时执行 lease 在同一事务提交；Mission scope 还暂停其当前未终态 Mission，Run scope 不触碰已完成阶段。问题、选项和归属不可修改，回答采用幂等键、预期 row_version 与只写一次语义；字段、唯一性、状态和锁序以领域模型为准，不能仅靠工具 payload 声明实现。

答案与原 Job 重新排队在同一事务提交，不新建 Job、Attempt 或会话。重新取得有效 claim 后，校验同一 Binding / 原生 Session / 受控工作区，把答案按问题身份原子置为 CONSUMED，并恢复原主会话；Mission scope 另恢复其原未终态 Mission / Attempt，Run scope 只继续 Run 级工作，不改变已完成 Mission。正常问答恢复不增加 binding_epoch，不重置阶段预算，不改写固定输入 / Policy / spec，答案也不自动扩大外部操作权限。

暂停后查询、核验、中断和清理使用 §22.1 的窄管理授权；新 Provider 工作仍须恢复后的有效执行授权。取消终止任一 scope 的开放问题，保留问题、回答、归属和成对 Audit / Outbox 历史；取消 / 失联 / 旧 epoch 后的迟到回答或执行结果不得推进任务。原生会话无法恢复时明确失败并保留历史，不能创建替代会话冒充续接。`RunInputRequest` 及跨 scope 唯一性需后续独立实现 / additive migration，现有 v1alpha1 仅支持原 Mission scope 控制路径。

---

## 30. Approval

对于 production mutation、database delete、external side effect、secret access 等危险操作，Mission 可声明审批策略。Adapter 尽量映射 Provider Approval / Sandbox 能力；Provider 不支持时由 HyperTest Tool Layer 拦截。预先配置的授权策略可以允许受控外部操作；问题或回答不能绕过固定权限和平台验证。

### 30.1 GitLab 缺陷协作（目标，尚未实现）

Harness 通过 `hypertest.request_gitlab_issue` 提交 Issue draft、当前 Run / SHA、已接受 Finding 及可信 Evidence 引用和可选责任人建议。平台检查预先配置的 GitLab Project 白名单、提单 / 通知策略、责任人映射、调用者权限和关联范围；未配置或超出规则时请求人工决策，不把 GitLab token、任意项目 URL 或直接外部写权限暴露给 Agent。关键决策可通过 §29 暂停询问；若前一 Mission 已完成，使用 §29.1 的 Run scope 问题，不重开原 Mission / Attempt。非阻塞提单可返回操作句柄供同会话继续查询。

外部操作以稳定 correlation / idempotency key 去重，保存 draft 摘要、Run / Finding / Evidence 关联、授权来源、请求状态及实际 GitLab project / issue IID / URL；同一逻辑缺陷的重复调用应返回既有 Issue 或明确更新请求，不重复创建。超时或连接中断产生 outcome unknown 时，必须先依据 correlation 对账；不能假定失败后自动重提。审计记录平台实际确认的外部结果，Issue 本身不成为可信 Evidence 或质量 Verdict。当前仓库没有此 GitLab 集成，需后续实现、授权配置及验收。

---

## 31. Retry

TMP 将 Retry 分两类：

- **Agent Internal Retry**：command failed、edit failed、tool timeout，由 Harness 自己处理。
- **Mission Retry**：Agent crashed、result schema invalid、provider unavailable，由 HyperTest 在显式恢复决策后重新调度。目标 profile 在原主会话上追加 Attempt / 恢复 turn，不因 Retry 自动更换 Provider 或会话。

Mission Attempt 必须独立记录，历史 Attempt 不覆盖。当前 v1alpha1 的新 Attempt 会创建新 Session；该实现不满足持续会话目标，不能作为目标 profile 的恢复策略。新 Job 的 Attempt 只能归属新 Job；不得把已失败 / 暂停的 Attempt 的 `durable_job_id` 改到新 Job。

接受 required outputs 的事务必须同时保存 `mission.completed` AuditEvent 与 OutboxEvent；SUBMITTED 或 Agent 自称 COMPLETED 不触发该平台事件。创建、开始、拒绝、超时、中断、取消和重试控制决策形成可审计的 Mission 生命周期，不能只从 Requirement / Case 的接受事件推测。生命周期事件只携带领域状态与原因，不承载 Vendor 日志、raw Proposal payload 或 reasoning。

Worker 租约过期或进程中断时，平台保留失联 Attempt 并标记 FAILED，将 Mission 标记 RETRYING；旧 lease token 不能再提交 Canonical 结果。Job 记录 INTERRUPTED，不自动重放外部执行。用户确认后显式重试生成新的 Job；Mission 重试仍追加新的 Attempt，Execution 重试仍创建新 Execution。Web 刷新或 API 请求结束不会撤销已经入库的 Job。

周期因 `MISSION_REJECTED` / `MISSION_FAILED` 受控停止时，FAILED Job result 保留 stop reason、已持久步骤、相关 Mission ID 和已解析 workspace；独立 EXECUTE_MISSION 拒绝还保留 Attempt ID。它只索引已有历史，不接受模型自报为执行事实，也不重新打开终态 Mission。FAILED Mission 必须明确报告失败，不能作为 `MISSION_IN_PROGRESS` 返回。通用异常可没有部分 result；取消或租约失效不接受迟到 handler 结果。用户显式 retry 仍生成关联新 Job，不覆盖旧 Job / Attempt / Proposal。

目标 profile 中需要先对账旧 Bridge call、确认停止并提高 binding_epoch，才可由替代 PID / 容器继续该 Run；保留 logical_worker_id、主 Session、宿主路由、固定输入及历史。如果原生 Session / 工作目录不可恢复，必须明确报告并由 Operator 选择恢复原环境或创建关联新 Run；不得在原 Run 中静默新建 Provider Session。预算由 Run 总预算、阶段 / Attempt 限额、Bridge call deadline 和允许重试次数共同约束，等待人工输入不消耗活跃 lease；恢复不能重置已消耗步骤 / 费用。达到预算或外部结果不明时可观察停止，不构造自动重试循环。

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

Operational Job 的输入比较允许对新增缺省项作内存规范化：旧 `ADVANCE_RUN` payload 未包含 `prepare_workspace` 与显式 `false` 等价。原持久 payload 不 UPDATE，真实输入差异仍拒绝复用同一 key；显式 retry 仍保留 lineage。该兼容不放宽 Mission / Proposal 的幂等规则，规范以领域模型 §23.1 为准。

---

## 33. Cancellation

HyperTest 可以 cancel mission；Adapter 对 Provider interrupt 为 best-effort。目标 profile 取消单个阶段不自动新建会话或越过该阶段；是否可继续其他工作由依赖 / 策略 guard 明确决定。取消整个 Run 时先持久化终态 Binding / 取消状态并撤销执行 call / 工具权限，随后使用 §22.1 的窄管理授权中断主会话并对账 / 清理其受控 Runner / GitLab pending 操作；不因取消自行增加 binding_epoch，epoch 仅在显式受控恢复中递增。已完成的外部副作用不能假定可回滚，需保留引用和审计；迟到结果不得推进已取消 Run。关闭主会话、清理工作区与证据保留各有边界，不能用删 Session 代替取消。

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

目标 Bridge 还须区分 `SESSION_UNAVAILABLE`、`STALE_BINDING`、`CAPABILITY_UNSUPPORTED`、`OUTCOME_UNKNOWN` 等受控错误；不能把这些规划错误值加入当前 v1alpha1 enum 后假定兼容。Provider-specific Error 经脱敏和限长后隔离于受控 `provider_metadata`；原生 stderr、秘密与 reasoning 不直接成为用户错误详情或活动记录。

---

## 35. Schema Version

核心对象必须包含 protocol/version，例如 `hypertest.tmp/v1alpha1`。

演进路径：v1alpha1 → v1alpha2 → v1beta1 → v1。

同一 Major 优先 additive change；禁止无版本重命名 required field、改变字段语义或删除 enum value。

文档 v0.4、已实现 wire `hypertest.tmp/v1alpha1`、目标 wire `hypertest.tmp/v1alpha2`、profile `run-persistent-harness/v1` 与宿主 transport `hypertest.harness-bridge/v1alpha1` 是不同版本轴。持续会话生命周期、能力要求和工具 envelope 只在新版本 / profile 明确协商后适用；旧 Run 仍按其冻结版本执行，不通过调整 Adapter 默认值重解释历史。

---

## 36. Capability Negotiation

目标契约由 Adapter 注册 Harness Capability，以下为能力描述示例，并非当前 Codex Adapter 的已验收能力清单：

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

Planner / Scheduler 在 Run 初次 admission 时基于 Capability 选择逻辑 Worker / Harness；目标 profile 的阶段推进和恢复必须复用原绑定，不能每 Mission 重新选 Provider。

目标 profile 至少要求：persistent native session、精确 resume、Run-scoped isolated workspace、结构化提交、运行中 typed domain tools、受控暂停 / 中断、调用对账及 version / binding fencing。`session_resume: true` 单独不足以证明能跨多个 Mission / Attempt 保持同一会话；Adapter 必须证明阶段完成不 close、新阶段不 create、人工等待不丢绑定和失联不自动重放。

当前 MVP 使用配置的默认 Codex Harness，并提供 §29 的持久等待、Web 回答与明确原生 thread 的 Codex resume 控制路径。完整 Capability 协商、跨 Harness 选择、其他 Provider 的 resume 与完整 MCP 工具面仍未实现；不能根据上述示例的 `true` 推断额外能力，真实模型验收范围以实际版本证据为准。

---

## 37. Agent Selection

Mission 声明需要的 Capability，而不是硬编码必须使用 Codex / Claude。Scheduler 可在新 Run admission 考虑 Capability、Cost、Latency、Reliability、Model Quality、Workspace Affinity、Historical Success。目标 profile 的绑定一经建立，后续 Mission 只能在该会话能力内执行；能力不足时显式停止 / 请求决策，不在同一 Run 中静默换 Harness。Provider 可替换性意味着平台契约独立且新 Run 可选不同 Provider，不保证跨 Provider 搬运原生会话。

MVP 可简单配置 `default_agent = codex`。

---

## 38. Security Boundary

TMP 明确区分 Agent Identity、User Identity、HyperTest Service Identity、Runner Identity。

目标 Agent 对 HyperTest MCP 的访问权限由受控工具 Token 控制，至少绑定 mission_id / attempt_id（若适用）、test_run_id、project_id、agent_session_id、logical_worker_id、binding_epoch、allowed_tools、allowed_resources、expiration。Token 为可撤销、限范围的授权，容器 Worker 和 Bridge 另以服务身份认证；不得把原始 Job lease、宿主登录或 GitLab 管理凭据交给 Agent。当前 MVP 尚未实现完整 Mission Token 工具授权，不能用此定义宣称已有安全能力。

Agent Session 不拥有项目全局管理员权限。

---

## 39. Audit

Mission Created、Mission Dispatched、Tool Called、Proposal Submitted、Proposal Accepted、Execution Requested、Evidence Created、Verdict Changed 都必须产生 Audit Event。

---

## 40. End-to-End Example

以下是 ADR-013 目标 profile 的完整周期；当前 v1alpha1 仍为逐 Mission 新会话，仅支持同 Mission 人工等待后的原会话恢复。

```text
SUT: payments → Project P-1
  ├─ MR !101 @ full SHA-A → TestRun TR-A
  │    └─ TaskWorker TW-A（容器）↔ Host Bridge H-1
  │         └─ AgentSession AS-A / 原生 Session PS-A
  │              1. 固定 SourceSnapshot / PolicySnapshot，验证工作区
  │              2. request_mission(ANALYZE_REQUIREMENTS) → M-1
  │                 Requirement Proposal[] → Verifier accept
  │              3. 同 AS-A 继续 ANALYZE_RISKS → M-2
  │              4. 同 AS-A 继续 DESIGN_TESTS → M-3
  │                 ask_user → WAITING_INPUT，保留 TW-A / AS-A / 工作区
  │                 用户回答 → 新 lease，同逻辑 TW-A、原 PS-A resume
  │              5. 同 AS-A 继续 IMPLEMENT_TESTS → M-4
  │              6. request_execution → 可信 Runner EX-100 / EV-1…
  │              7. 读取事实，必要时 DIAGNOSE_FAILURE → M-5
  │                 Finding Proposal → Verifier accept
  │                 按预授权策略 request_gitlab_issue → 实际 Issue 引用
  │              8. request_gate → 平台持久 Verdict
  │              9. submit_report → 有 hash 的报告 + 事实 / Verdict 引用
  │             10. 平台确认完整周期后受控结束会话，保留历史
  └─ MR !102 @ full SHA-B → TestRun TR-B
       └─ TaskWorker TW-B / AS-B / PS-B，可与 TR-A 并发
```

同一 SHA 可因显式复测或需求 / 配置 / 环境 / Policy 改变创建新 TestRun；MR 新 SHA 创建新 Run，不覆盖旧证据与结论。每个 Run 内维持串行单 owner；不为阶段切换创建新会话，也不允许多个任务 Worker 同时推进同一 Run。不同 Run 可选择 Codex、Claude Code 或其他已通过能力验收的 Harness，Canonical 协议与事实边界保持一致。

---

## 41. TMP 核心不变量

1. Agent 不直接拥有 Canonical State。
2. Mission 描述目标，不规定 Agent 内部 reasoning。
3. Provider-specific Session 只作隔离的外部引用，不能充当领域主键或 Canonical State。
4. Agent Result 是 Submission，不是事实。
5. Runner Evidence 才能成为正式执行事实。
6. Mission Acceptance 由 HyperTest Verifier 决定。
7. TMP 必须允许新 Run 选择不同 Harness；同 Run 的持续会话不得静默换 Provider。
8. 一个任务的逻辑 Worker / 主 Session 绑定跨阶段、人工等待和显式恢复保持，物理进程 / lease 不等于绑定。
9. 不同 Run 可以并发；同 Run 的 Mission / Attempt 串行且只有一个有效 owner。
10. 目标 profile 必须显式协商，不能改写旧 wire schema、固定输入或执行历史。

---

## 42. 协议定位

TMP 不应演进成 Generic Agent Protocol，而必须始终保持：

> **Testing-domain-specific Agent Work Protocol**

它描述 Requirement、Risk、Case、Implementation、Execution、Evidence、Finding 及受控报告 / 人工协作边界，而不描述 LLM thinking steps。持续主会话由 Harness 自驱，平台维持类型化 guard 与事实治理，不演进成自制 Generic Agent Loop。

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
Next typed Mission / Request（同一 Run 主会话）
```

TMP 的价值不在于规定 Codex 或 Claude Code 应该如何思考，而在于：

> **无论底层 Agent 如何变化，HyperTest 对软件测试的理解、状态、证据和治理协议始终保持稳定。**
