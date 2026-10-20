# Test Mission Protocol Specification

**Protocol Name:** TMP  
**Full Name:** Test Mission Protocol  
**Version:** v0.6
**Status:** Draft  
**Owner:** HyperTest
**Accepted target decision:** [ADR-013 — Containerized Platform and Persistent Harness](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
**Dual-mode implementation decision:** [ADR-015 — Dual-mode Harness and Local Connector](../architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)；Connector 契约及 `0015`—`0018` 已实现，隔离回归通过，核心隔离真实端到端验收通过，已部署生产，线上核心周期已通过，扩展故障矩阵继续逐设备登记；现有 TMP wire / profile / Host Bridge 版本保持。
**Interactive access implementation:** [ADR-016 — Interactive Agent MCP Access](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)；当前分支已实现 stdio MCP / 私有 UDS / typed HTTPS、当前 Agent 绑定及原 Worker 工具 inbox，包含 `0019_interactive_mcp` / `0020_interactive_tool_inbox`；已部署生产，线上当前 Agent 核心周期已通过（2026-10-20，Asia/Singapore）。隔离 API / Worker / 数据库及真实 Docker Runner 回归已通过；真实当前 Codex Desktop Agent 的隔离端到端周期已完成，见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)及[机器可读证据](../evidence/adr016-20261020.json)。该隔离结果不替代下段独立生产验收，不改变 ADR-015 的历史发布与验收记录。
**Implementation boundary:** 已实现 v1alpha2 持续会话 profile、Host Bridge、九个领域工具及独立 Connector 传输；ADR-016 的九个交互入口与绑定后的九个 TMP 工具由独立授权接入，正式工具工作仍由原 Job Worker 执行。旧 v1alpha1 保留原语义，2026-10-19 正式容器化及 Codex 正反链路属于既有验收，各 Provider / driver / 外部集成分别登记。

生产发布为 PR #17 / `c7cd43ad6346d8ce6c85564f7838afbb017f2da4`，正式库已向前升至 `0020_interactive_tool_inbox`；PR / main CI 为967 passed、21 skipped。同一真实当前 Codex Desktop Agent 经官方 MCP SDK console 完成生产核心周期：2 Requirements / 3 Risks / 4 Cases / 4 Implementations，唯一平台可信 Docker Execution 的33项 HTTP 测试通过，五份 VERIFIED Evidence 与两页报告内容均经 MCP 读取并核验 hash / 字节数，形成 FINAL `RELEASE_READY`。真实过期后的两次显式 Worker 恢复保留原 Run / native / workspace，epoch 1 → 2 → 3，旧 Job / Attempt 保留；最终历史保全另经39项只读检查通过。详细身份、时序与保全边界见[ADR-016 生产部署记录](../ADR016_PRODUCTION_DEPLOYMENT.md)及[生产机器证据](../evidence/adr016-production-20261020.json)。隔离验收的27项测试仍属其独立历史；本轮不宣称聊天原生工具目录热加载、运行中断线注入、两种原受管路径的新完整周期、私有 SUT 业务或新增问题单写入通过。

已包含 `0013_run_bindings` / `0014_harness_operations`；本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)，正式切换与恢复历史见[部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。历史 PR #10 当时部署源码 `828225d`，兼容 Host Bridge 保留 `95e92c5`，当时 schema 为0014；ADR-015 当时 schema 升至0018，历史发布与验收范围见[生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)；当前 ADR-016 生产 schema 为0020，见[当前生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)；当前访问配置只在[运维材料](../SERVER_OPERATIONS.md)维护。[ADR-014](../architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)的关闭后治理属于平台操作者接口，不扩展已关闭 Agent 的工具权限，也不改 TMP wire/profile 版本。受控 GitLab 真实创建已有 ADR-015 独立隔离验收；其他 Provider 与未执行扩展场景继续单独登记。


ADR-015 双模式、设备 / 项目授权、WSS 持久 mailbox、HTTPS 源码接收、本地问题单适配与显式恢复已实现，`0015_connector_nodes` → `0018_harness_selection` 已部署生产。核心隔离真实验收已通过，包括本地 Codex → 远端可信 Docker Runner → Evidence / Gate → 报告正反链、私有 Git 经 HTTPS 接受、原会话断线恢复及获准测试 Issue 的创建 / 负责人核验。这些隔离结果不冒称生产结果。生产切换已完成原数据、文件、认证、SSH / VPN 与服务器 Bridge 保全；严格外部 TLS、线上本地 Connector 核心周期和生产私有源码 source-only 接受补验已通过，后者未启动私有业务 Run 或问题单操作，扩展真实设备故障矩阵继续分别登记。该次发布与实际验收范围见 [ADR-015 生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)，隔离历史见 [ADR-015 总验收](../ADR015_ACCEPTANCE.md)，源码统计见[源码验收记录](../ADR015_ACCEPTANCE_SOURCE.md)。

---

## 1. 目标

Test Mission Protocol（TMP）定义 HyperTest 与外部 Agent Harness 之间的稳定协议。

支持目标包括 Codex、Claude Code、Pi、OpenCode 以及 Future Agent Harnesses。

TMP 不定义 Agent 内部如何 reason、plan、spawn subagent、manage context、retry tools；这些属于 Agent Harness 自身能力。

目标工作方式为：一个 SUT 对应一个 Project，一个 feat / MR 的固定完整 SHA 的一次测试轮次对应一个 TestRun；同一 TestRun 绑定一个逻辑任务 Worker 和一个持续主 Harness 会话，Harness 自驱串行完成分析、设计、实现、申请正式执行、诊断和报告。不同 TestRun 可以并发；不向同一 Run 派发多个任务 Worker 或并行阶段。输入仍由不可变 SourceSnapshot / PolicySnapshot 固定，不能仅按 SHA 去重而禁止显式复测。

平台服务及任务 Worker 容器化。ADR-013 已实现的 `SERVER_HOST` 模式由服务器宿主 Host Harness Bridge 托管 Harness；ADR-015 已在本分支实现 `LOCAL_CONNECTOR` 模式，由用户设备的常驻 Connector 主动连接平台并托管本地 Harness。两种模式均保留一个 Run 的主会话、原生认证与受控工作区，不能因 Worker 容器重建而丢失会话身份。模式和节点在 Run 首次绑定时固定；本地模式不绑定浏览器标签页生命周期，不因离线改派服务器。部署边界见 ADR-013 / ADR-015，绑定、租约、生命周期和持久化约束以领域模型为准。

当前 `hypertest.tmp/v1alpha1` 兼容路径仍由 Web 提交 DurableJob、独立 Worker 调用 bounded Run test cycle controller，按 deterministic Planner 的 Canonical State gap 逐个启动 Mission；每次新 Attempt 创建会话，人工等待按 §29 恢复原会话。`max_steps` 限制当前平台工作单元；Job SUCCEEDED 不等于测试 PASS，Job payload 不是 Canonical State。本分支的持续会话使用 §6.1 独立协商的新 profile，不重解释旧 controller 或冻结的 v1alpha1 历史。

周期先以所选 Runner 的只读 fingerprint 预检实际 daemon / 可信镜像或显式 local 启用条件，成功后才进行 Git / Agent；前后重新验证归属，预检 I/O 不持 Run / Job 行锁。失败不创建正式 Execution / Evidence，预检成功也不等于测试通过。独立 Gate-only 操作不要求 Runner。

`ADVANCE_RUN` 可在同一持久请求内先准备固定源 checkout（`prepare_workspace: true`），或接收已有 workspace；二者互斥。源准备是进入 Mission 之前的平台步骤，不消耗 max_steps、不产生 Agent Intelligence。Git I/O 不持有 Run / Job 行锁；准备后重新验证归属与 lease，失败或失联时不得开始 Agent。该扩展不改变 TestMission schema、Mission identity 或 Canonical 状态所有权。

ADR-015 的本地源码传输另遵守 §22.3：批准的本地采集器取得固定完整 SHA，经平台验收后形成不可变输入；不要求服务器复用或取得本地 Git 凭据，也不接受本地路径作为服务器 Runner 的源码引用。该能力经新的 SourceAcquisitionRequest / Transfer / UploadGrant 接口实现，不由旧 prepare_workspace 参数或 ADR-013 部署状态推定。

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
HarnessConnectorEnvelope / SourceBundleReceipt（ADR-015 已实现独立远程传输）
InteractiveTaskSubmission / InteractiveSubmissionReceipt / InteractiveToolRequest（ADR-016 已实现，已部署生产，线上当前 Agent 核心周期已通过）
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

ADR-013 的持续会话 profile 为 **`run-persistent-harness/v1`**，只在显式协商的 **`hypertest.tmp/v1alpha2`** 上启用；本分支已实现该版本，不能把 `profile` 等新字段附加到现有 v1alpha1 请求后假定支持。新 Run admission 固定 wire version、profile、Provider / Harness 能力与策略，任何一项不支持时明确拒绝，不能降级为每阶段新建会话并声称仍满足本 profile。已冻结 v1alpha1 Mission 保留原执行语义；迁移不得改写其版本、spec / hash、Attempt、Job 或 Session 历史。

目标 `RunWorkflowContract` 引用固定 Project、TestRun、SourceSnapshot、PolicySnapshot、MR / feat 来源及完整 SHA，声明串行阶段、验收规则、允许工具与运行预算。该 Contract 是受控任务上下文，不新建 Canonical 事实链，也不把源输入保存在聊天历史中代替数据库。

稳定运行身份引用领域模型的 `RunExecutionBinding` / `run_execution_bindings`：`logical_worker_id`、`primary_agent_session_id`、`harness_host_id`、`workspace_id` 和单调递增的 `binding_epoch`。这些 Operational State 已由本分支 `0013_run_bindings` 实现；关系、唯一性和不可变约束以领域模型为准。平台托管原生 Provider session ID 仅在首次创建事件前允许未绑定，之后不可被新 session 替换；ADR-016 交互式绑定则须先核验当前真实 native session，不能用该临时空值许可创建影子会话。`logical_worker_id` 表示专属于该 Run 的逻辑 Worker 身份，不能与某次领取的 `Job.worker_id`、租约 token、容器 / PID 混用；进程可在显式 fencing 后替换，逻辑绑定、主 AgentSession 与原生 Provider session 保持。一个物理 Worker 实例同一时刻只推进一个 Run，完成后可服务其他任务。

ADR-015 的 `RunHarnessPlacement` 在该绑定旁冻结 `SERVER_HOST / LOCAL_CONNECTOR`、节点与源码传输策略；不会重解释或回填 `0013` 已有字段。新 Run admission 必须同时校验节点归属、项目授权、在线可用性、能力和选定模式；后续阶段、重新连接与显式恢复继续使用该 placement。新模式的 Operational 记录及不变约束以领域模型 §23.9 为准。

新创建请求的幂等输入比较包含冻结的 mode/node、来源信任策略及源码 transfer 策略；同 key 同输入返回原请求，任一异值冲突。Placement 仍是 Operational 归属，不进入 SourceSnapshot fingerprint/Gate hash；不为旧缺 mode 的 Job payload 回填字段、改变旧 Schema 或扩展既有 TMP 工具业务参数。

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

协议的目标工具模式允许 Agent 通过 HyperTest MCP 获取详细对象。v1alpha1 兼容路径由 Runtime 预先读取必要对象并注入 Context，使用结构化最终结果提交 Proposal；本分支 v1alpha2 通过 §25.2 的分页 `get_state` 获取详细对象，使用 `complete_mission` 提交当前 Attempt 的 Proposal batch。

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

`hypertest.harness-bridge/v1alpha1` 是本分支已实现的容器 Worker ↔ 宿主 Bridge 传输版本，与 TMP wire version / profile 分别协商。初版同机使用限权 Unix domain socket；后续跨主机必须使用经过认证和加密的传输，不能把无认证本机接口直接暴露到网络。Bridge 仅适配 Provider 生命周期、身份、工作目录和标准化事件 / 结果，不接管测试规划或 Canonical 提交。

允许操作为 `capabilities`、`create_session`（仅 Run 初次绑定）、`restore_session`、`execute`、`resume`、`interrupt`、`close` 与只读 `get_call`；它不是 arbitrary shell / SSH 执行接口。已绑定 Run 上的 execute / resume 必须引用已登记的原生会话，不能隐式 create；具体 CLI 的启动和 resume 差异由 Adapter 封装。

上述为生命周期语义；本分支实际操作名为 `capabilities`、`create_session`、`start_call`、`get_call`、`renew`、`respond_tool`、`restore_session`、`interrupt`、`recover`、`close`。`start_call(resume=false/true)` 对应 execute / resume，`renew` 仅续当前有效执行授权，`respond_tool` 仅交付平台已验权的工具结果；二者均不能恢复失效 claim。`recover` 使用管理权限核验已静止的原调用及原生会话后，将 Bridge generation 与领域显式恢复的下一 epoch 对齐，不启动模型。实际参数和签名上下文见 [Host Harness Bridge](../HARNESS_BRIDGE.md)，不提供名为 execute / resume 的额外 wire 操作。

Bridge 区分执行授权与管理 / 恢复授权，不能要求已取消或租约失效的调用继续持有原执行 claim 才能停止和对账：

| 授权类别 | 允许的操作与约束 |
|---|---|
| 执行授权 | `create_session`、`execute`、`resume` 及任何启动新 Provider 工作的操作，必须具有当前可执行 Binding / epoch、有效 Job / claim 与该阶段工具权限；旧 owner / claim / epoch 不得启动工作或提交 Canonical。 |
| 管理 / 恢复授权 | 可信服务身份携带明确的目标 Binding、Session、call 及其历史 generation，可在旧 claim 已撤销后执行 `get_call`、只读核验原会话 / 工作区、`interrupt`、`close` 和既有句柄恢复，以完成对账、fencing 和清理。授权不得扩大到 create / execute / resume、运行新 Provider 工作或 Canonical 提交。 |

只读 `capabilities` 探测使用服务身份。其余调用包含版本、profile、call_id、idempotency_key、TestRun / AgentSession、logical_worker_id、harness_host_id、目标 binding_epoch / call generation、工作目录受控标识和 deadline；执行调用另携有效 Job / claim 及当前 Mission / Attempt（若适用），管理调用另携窄范围服务授权和精确目标。原生 Provider ID 仅作为已持久化的外部引用，由 Bridge 校验匹配；不能允许 Agent 提交任意宿主路径或选择其他用户的会话。`restore_session` 只有在纯粹恢复既有受控句柄且不启动 Provider 工作时可用管理授权；任何启动进程 / turn 的变体仍须执行授权。租约 / 授权材料不进入 Agent Prompt、事件 payload 或报告。

Bridge 和平台共同拒绝以旧 epoch / 旧 claim 执行工作、跨 Run / Session 与并发 execute / resume，同 Session 同时最多一个活跃调用；恢复前需 fencing 旧 owner。对历史 epoch 的查询 / 中断 / 清理，只能由明确指向该历史调用的窄管理授权执行，不能让旧 owner 获得通用续接权限。相同 idempotency key / 同输入返回既有 call 状态或结果，异输入冲突；call_id 贯穿标准化事件、最终结果及确认。Bridge 先登记操作再启动 Provider，返回可查询句柄；不承诺外部 exactly-once。首次创建收到原生 session 引用后必须持久确认，若结果丢失则先对账，不能盲目再次 create。Worker 超时、断线或 ACK 丢失时，先查询 / 对账已登记 call，不能自动重发可能有副作用的 execute / resume。

Bridge 按已授权 deadline / lease watchdog 停止失联调用；interrupt 结果区分请求已受理与进程确已停止。取消先在平台持久化终态 Binding / 取消状态并撤销执行 call / 工具权限，再以窄管理授权尽力 interrupt / close；租约撤销不阻止清理和对账。取消不自行增加 binding_epoch，epoch 只在领域模型允许的显式恢复中递增。可恢复的中断必须确认原调用静止后才能重新获得执行授权；终态取消不能恢复执行。迟到事件 / 结果必须按 owner、claim、epoch、call 和当前状态校验，过期响应不得写 Canonical 或触发新的外部调用；管理对账只可记录受控操作结果。CLI 的 stdout / stderr、原生事件与秘密由 Adapter 投影或受控保留，不直接进入持久活动记录。

本分支执行 grant 不超过当前 Job lease 和 120 秒传输上限，Worker 在长工具 / Runner I/O 期间独立续约；Bridge 到期中断且不自动重放。`get_call` 提供持久的 `created_at`、`finished_at`、`elapsed_seconds` 与 `stopped`，仅确认进程停止后固定耗时，供 Run 总预算对账；它不提供计费 token 或 reasoning 内容。

### 22.2 ADR-015 双模式与 Connector 传输契约（已部署生产，线上核心验收通过）

本节的 Provider 创建、进程托管和调用操作记录 ADR-015 已实现的 `PLATFORM_MANAGED` driver；其本地 Harness 由 Connector 托管。ADR-016 新增 LOCAL / INTERACTIVE_MCP 时，当前 Agent 的显式绑定和生命周期按 §23.6 适配，不调用下述 managed create/start 路径再启动另一个 Agent，不重解释既有生产调用历史。

`SERVER_HOST` 继续使用 §22.1 的限权 UDS Bridge；`LOCAL_CONNECTOR` 使用用户设备常驻进程主动发起的 WSS 双向连接。Web / bootstrap API 已提供 harness_mode、node_id 与 source_bundle_transfer_id；首选服务器模式保持旧 payload 兼容，本地选择由 RunHarnessSelection 在绑定前冻结，首绑定形成 Placement。设备配对 / 轮换 / 撤销与项目能力端点已实现，独立真实验收与生产部署状态另行登记。Web 承担节点选择、配对、撤销及任务提交，页面刷新、关闭或退出不作为 Connector 的连接或任务生命周期。WSS 沿用部署的 VPN / 入口访问边界、验证服务端证书；不要求用户设备开放入站端口，不把 UDS 接口直接代理到公网。

新远程传输独立协商 **`hypertest.harness-connector/v1alpha1`**，不替换 `hypertest.harness-bridge/v1alpha1`，不改变 `hypertest.tmp/v1alpha2`、`run-persistent-harness/v1` 或既有九个领域工具的业务 Schema。双方协商传输版本、TMP/profile、Provider 能力、消息与队列上限、事件保留窗口、心跳、短期授权及源码/Artifact 传输能力；缺少必需能力明确拒绝。其逻辑操作复用 §22.1 的 capability、创建/恢复原句柄、start/resume、查询、续授权、工具请求/响应、中断、显式恢复和关闭语义，不提供任意命令、SSH、文件路径或通用远程 Shell。

设备配对产生独立、可撤销且限用户/项目范围的设备授权；平台登记稳定 `node_id`、所有者、允许的 Project、能力与设备注册状态，连接在线状态另行记录。当前单 Operator 部署仍须明确可信操作者和允许项目，不能由设备配对推定已有多租户安全。设备身份不等于 Run 执行授权，也不等于源码来源采集或问题单写入权限。心跳只证明连接近期可达，不证明有效 Job claim、Provider 正在工作或执行成功。

远程 envelope 至少绑定 transport version、message/request ID、node、owner/project scope 和 deadline；Run 任务消息另绑定 TestRun/Binding、`binding_epoch`、主 AgentSession/native session、workspace、`call_id` 与幂等键；执行消息另绑定当前 Job/claim、Mission/Attempt（若适用）及短期 dispatch grant，工具消息另有稳定 `tool_call_id`，问题单委派另有平台 `operation_id`。注册/握手使用设备 scope；源码准入发生在 Run 绑定之前时以明确的 Project/源码输入 scope 授权，不伪造尚不存在的 Binding。所有消息由接收端验证身份、目标、有效期和 scope；平台在每次提交和外部操作准入时重新验证当前数据库 owner/claim/epoch。不能只凭通道已认证或消息已 ACK 接受迟到结果。

设备仅取得绑定特定任务/调用的短期执行 grant，及明确指向历史调用的窄查询/清理 grant；平台的全局管理签名密钥、Job lease 原始秘密和数据库权限不下发设备或 Agent。取消/撤销后的查询、中断、关闭可用独立清理权限，但不能借清理消息创建会话、resume、新发工具或提交 Canonical。原生会话 ID、第三方认证和授权材料不进入模型上下文、活动流或报告。

首版平台与 Connector 只交换白名单类型化请求 / 响应、规范化活动及结构化结果，不持久化 Provider 私有原始事件、stdout / stderr 或 reasoning。通过原 get_call(cursor) 有界读取 Bridge 持久调用账本；单次最多 256 events、最多一个 pending typed tool，事件 sequence 必须连续，cursor gap 明确拒绝。响应经白名单投影和数据库事务保存后才视为接收；ConnectorRequest 在发送前提交 SENT，重连不重发 SENT，未知结果只查询原 call / operation。补读事件不重跑 Provider turn、Runner 或 Issue POST，不承诺无界 push log 或网络 exactly-once。

**首版设备身份与 mailbox。** 操作者经独立 operator key 配对；平台生成高熵随机 bearer token，设备以 Authorization: Bearer 使用，明文仅留节点私有文件；平台持久化 SHA-256 token_hash / key_version 引用。key_version 不是公钥，WSS / HTTPS 使用 TLS 校验平台身份和已认证设备 scope。轮换保持 node_id，撤销旧 grant 并保留其 hash / 审计；旧已知凭据仅可获得匹配历史对象的窄查询 / 清理通道，不能恢复执行。项目权限由独立 NodeProjectCapability 的 harness / source_acquisition / issue_executor 分别授权。

WSS 请求 envelope 固定 type、transport、request_id、node_id、operation、authority、payload、input_sha256、expires_at，以及 issue_create 的 create_once；Run / Project / Binding / Session / workspace / claim / epoch 等在对应 payload / context 内固定。PostgreSQL ConnectorRequest 记录 QUEUED → SENT → SUCCEEDED / FAILED / UNKNOWN，发送前持久消费，断线不重投原 SENT。单消息最多 4,000,000 bytes，每节点最多 256 个 QUEUED / SENT；hello / hello_ack 验证现有 TMP v1alpha2、profile 与 host_id / node_key，心跳间隔 5 秒、失联观察窗口 20 秒，均不授予新工作。

| 操作面 | 实际 allowlist 与响应边界 |
|---|---|
| 执行 | create_session、execute、resume、get_call、renew、respond_tool，及 install_workspace(create=true)；必须当前 DispatchGrant / claim / epoch |
| 管理 | capabilities、get_call、restore_session、interrupt、recover、close、issue_query，以及 install_workspace(create=false)；只针对原身份，不启动 Provider 工作 |
| 来源 / 问题单集成 | prepare_source、issue_create、issue_query；协议解析兼容 source_prepare 名称，不具备已注册能力时明确拒绝；issue_create 按 operation_id 只消费一次创建权限 |
| 会话响应 | 仅 session_id / provider_session_id / binding_epoch / closed / recovery_required / active_call_id |
| 调用响应 | 仅 call_id / status / stopped / timestamps / elapsed_seconds / binding_epoch / provider_session_id / error_code / cursor / events / pending_tools；事件与九个 typed tools 各自再验 Schema |
| 简单 ACK | renew 仅 expires_at；respond_tool 仅 accepted=true；interrupt / close 仅 accepted / stopped / closed 三个布尔值 |
| 来源 / 安装响应 | prepare_source 仅 SourceTransferRead 精确字段并匹配原请求；安装仅 workspace_id / installed=true，不能把任意本机路径当服务器可执行路径 |
| 问题单响应 | 仅 operation_id / delegation_sha256 / status / issue；issue 限 IID / project / description / HTTPS URL / 精确 assignee，须匹配原 correlation 与授权 |

未知字段和非法结果在入库前拒绝，不把普通设备文字当可信外部结果。install_workspace(create=true) 匹配 Run / Binding / Session / workspace / 已接受 transfer、当前 Job claim / epoch 与执行 grant，发送及返回后重新 fencing。create=false 仅限原身份的只读核验；目录丢失或内容改变返回确定错误，禁止自动重建，网络或授权未知不构成永久丢失的证明。

<a id="223-本地授权复用与固定源码artifact-传输adr-015-目标"></a>

### 22.3 本地授权复用与固定源码/Artifact 传输（ADR-015 已实现）

本地 Harness 可使用本机实际可用的 Provider CLI/SDK 登录；Connector 的受控源码采集与问题单适配器可分别复用本机 Git credential helper、SSH agent、CLI 或集成认证。浏览器登录不自动代表存在 CLI/API 权限，各 capability 必须实际探测并按项目授权。Provider 自身认证留在其本地运行时，Git/问题单凭据由相应适配器使用，不转发平台、不放入 AgentContext、模型工具、Artifact 或日志；配对也不导入这些第三方 token。

源码传输分为受控采集、平台验收和只读分发三个步骤：

1. 平台先固定批准的 repository origin、可选 ref 与完整 commit SHA、对象格式及采集策略。与 Agent 隔离的本地 source-acquisition adapter 使用本地 Git 权限从批准 origin 获取该 SHA，并生成无凭据的 Git 对象闭包包与 tracked tree manifest；不能把当前工作目录、可变分支 tip 或 Agent 自报 checkout 视作固定输入。
2. 来源可信性必须有可验证路径。项目可显式授权已配对节点的受控 source-acquisition adapter 为来源采集者：采集器提交设备认证的 receipt，固定 Project/不可变源码输入请求、node、批准 origin/ref、完整 commit/tree、bundle digest、授权策略/版本引用和采集结果；设备登录本身不授予此角色。首版平台在 TLS 连接上验证随机 bearer 的设备哈希身份与 receipt 所属 grant、授权、scope 和固定输入；receipt 不使用非对称设备签名。平台独立验证 Git commit → tree → blob 对象链、相对路径、文件模式与内容 hash，再接受源码。receipt 的来源保证依赖被明确授权的采集适配器及其主机，不是对不可信电脑的密码学来源证明；Harness 不能自签或替换它。平台也可直接核验批准 origin/commit 作为另一可信来源路径。origin 字符串、设备声称、Agent 输出或包 SHA-256 均不能单独证明来源真实性；包 hash 只证明传输完整性。没有可信采集授权或独立来源核验路径时 fail closed，不冻结/复用相应 SourceSnapshot。
3. 平台在 SourceSnapshot 冻结前接受包及 manifest/receipt 关联，保存不可变、内容寻址源码供 Runner 使用；Runner 从平台受控存储取包并独立校验固定源与实际执行树，不依赖用户设备路径或 Agent 自报 hash。本地会话工作副本也从已接受身份核验，不能带入其他 commit 或 dirty 修改。SourceSnapshot 字段、hash 和历史不因传输方式改变而重写。

包只包含固定 commit 所需 tracked Git 对象和声明文件，不上传完整认证 `.git` 目录、credential/config、dirty/untracked 文件或无关 `.env`。若敏感内容本就被该 commit 跟踪，拒绝传输并要求新的合规输入/commit；不能静默过滤 tracked 文件后仍声称是原 tree。批准 origin/receipt 只使用去凭据的规范引用，不携带 URL 内认证、SSH 私钥、访问 token 或本地任意绝对路径。

首版拒绝未支持的 submodule、LFS 及外部下载依赖，直到存在显式固定对象与独立验证契约；不能静默跟随远端、遗失文件或以指针代替完整执行源码。

大包和 Artifact 通过独立 HTTPS 上传/下载，WSS 只传控制和受控引用。平台签发有限期、限方向、限对象与限大小的 transfer grant，绑定 owner/Project、source input 或 Run/Binding scope、`bundle_id`/Artifact ID、预期 digest、长度/上限与 expiry；设备授权、传输授权和执行授权分别撤销、校验，过期 URL 不能继续读写。下载端校验 hash，上传验收检查实际大小、路径遍历、绝对路径、符号链接逃逸、文件类型、对象数量和解压缩资源上限，拒绝压缩炸弹与超额内容。已开始的大文件 I/O 也不能越过撤销/过期后验收；不在数据库聚合行锁中传输或校验包。

生成测试仍通过现有 typed Proposal 的 `code` 提交，Verifier 接受后生成 immutable TestImplementation Artifact，Runner 按已有规则验证和执行；传输内容引用不自行扩展工具业务 Schema。Connector 上传成功不是 Canonical acceptance，也不让本地工作文件成为正式 Implementation/Evidence。可信 Runner 仍默认运行在平台受信执行环境，本地 Harness 不因持有源码或认证获得 Runner 身份。

**首版实现的源码包与资源边界（2026-10-19）。** `hypertest.source-bundle/v1alpha1` 使用无压缩 JSON，原始 Git commit / tree / blob 对象以 Base64 编码；拒绝额外字段、重复对象、无关对象及父历史。manifest 列出完整 tracked tree 的 path / mode / Git OID / SHA-256；接收端重算每个对象的 Git Hash 并从目标 commit 独立遍历完整 root tree，不能以 manifest 替代对象链。

| 限制 | 当前实现 |
|---|---|
| 单个对象原始 payload | 最多 24 MiB（25,165,824 bytes） |
| 所有对象原始 payload 合计 | 最多 32 MiB（33,554,432 bytes），包含 commit / tree / blob |
| HTTPS 接收的完整 JSON 包 | 最多 48 MiB（50,331,648 bytes），并精确匹配 grant 中的长度和 SHA-256 |
| 对象 / 文件 / tree 深度 | 最多 50,000 个对象、25,000 个文件、100 层 tree；展开后的 tree 访问也有界 |
| 当前支持的 tracked file mode | `100644`、`100755`；首版 Runner 不支持 symlink，故接收端连安全 symlink 也明确拒绝；submodule / LFS 同样拒绝 |
| 上传授权与传输 | grant 最长 120 秒；流式接收同样受剩余时限限制，完成 I/O 后重新核对设备 / Project source-acquisition scope / policy |
| 暂存空间 | 每个受控 store 最多预留 192 MiB，跨 API 进程使用文件锁；崩溃遗留 `sources/staging/source-*` 在 600 秒后清理 |
| 本地缓存 | 2 GiB 准入配额；保留已接受包供原 workspace 恢复，达到配额时拒绝新采集，不自动删除活跃或结果未知的 Run |

24 MiB 单对象上限用于容纳固定 tree 中合法跟踪的二进制对象；它不放宽 32 MiB 总 payload、48 MiB JSON 包或秘密拒绝规则。源码适配器只在独立受管目录读取固定 Git 对象，失败后移除 fetch 的裸仓库；物化不运行 hooks、smudge filter 或仓库脚本。越界输入必须失败，不通过删除文件、LFS 下载或修改原 commit 绕过上限。实测统计与独立验收范围见[源码验收记录](../ADR015_ACCEPTANCE_SOURCE.md)。

### 22.4 本地问题单执行的受控委派（ADR-015 已实现，真实创建已独立核验）

`request_gitlab_issue`/`get_issue` 业务 Schema 及 §30.1 的 Finding/Evidence/策略规则保持。服务器集成继续可用；新本地 executor 是 Connector 的单独 capability，由本地可信适配器执行平台已批准的类型化 create/read 操作，凭据不交给 Harness。两种 executor 共享平台 operation 账本和去重范围，不因换后端、重连或更换幂等键给同一 Finding 再建 Issue。

平台先完成项目白名单、调用者、责任人、已接受 Finding/可信 Evidence、Run/SHA 与策略校验，并持久化不可变创建意图；再向固定 executor mode/node 发委派。委派至少固定 `operation_id`、Run/Binding/epoch、Finding、输入摘要、目标 Project/负责人、允许动作、授权快照引用和 expiry；本地校验精确目标和有效权限，持久登记该操作后才发外部请求。同 operation/输入的消息重投返回既有账本状态，异输入冲突。设备配对、Agent 生成 draft、人工补充回答及消息送达都不替代该授权，不能扩大为任意问题单 API、URL、项目或通用外部工具。

已登记意图的结果未知时保持 `UNKNOWN`，只允许同一 `operation_id` 的 correlation 查询/核对；即使重连、ACK 丢失或本地执行器重启也不得自动再次 POST。实际 Issue 引用须由受控适配器从目标平台响应/查询核验，并由 HyperTest 校验其项目、关联标识、输入摘要和引用范围后入账；Agent 自报 URL 不算核验。收到迟到结果只可对账原操作，不恢复过期执行权限、不推进已取消 Run；已发生外部副作用保留审计，不假定可回滚。

### 22.5 连接丢失、恢复与离线撤销（ADR-015 已实现，完整矩阵验收中）

本节中断受控 Provider 进程的实现语义适用于既有平台托管 driver。ADR-016 当前 Agent driver 保留相同 Run fencing/对账约束，但暂停、关闭和 watchdog 只约束本 Run 的 attachment/授权与受控工作，不承诺终止整个用户聊天；具体见 §23.6。

连接在线、执行授权、Binding 状态和 Provider 调用状态分别判断：短暂 WSS 重连可重建认证通道、补送有界事件及查询原调用，不能单凭 reconnect 自动 start/resume。仍有效的 grant 也必须按原 `call_id` 查询并复核；无法确定原调用是否启动或停止时保持不确定状态，不新建会话或重复 execute。离线不把任务改派服务器，也不替换原节点/Provider。

Connector 有独立于网络与 Provider 的本地 watchdog，以本地单调时钟限制授权存活；执行 grant 的到期时间不得晚于当前 Job lease 和协商的传输授权上限。续授权依赖平台当前 claim/epoch，不以心跳自续。到期或可达时获知撤销后，停止接受新 Provider/工具/Issue 工作并尽力 interrupt 原调用，区分“已请求中断”与“确认 stopped”。平台不因暂时无法联系设备而断言进程已停止；授权失效或原调用无法确认时进入领域模型的受控失联/恢复处理，保留原调用、预算预留与未知操作记录。Connector 通道/dispatch grant、服务器 Worker Job lease、Runner 执行授权相互独立；设备断线不等于服务器 Worker 失联，不自动使仍有有效平台治理的 Execution 失败。已被可信 Runner 接受的 Execution 可独立完成并按原 Execution/授权规则记账，不因本地离线另发一次 Runner 请求；服务器 Job 自身失联才应用既有 Job/Attempt/Execution 规则。

恢复先以窄查询/管理授权对账同一 node、Binding、原生 Session、workspace、固定源码、原 `call_id`、工具与 Issue operations；确认旧 owner/call 已 fenced/stopped 并核对耗时后，才按领域模型显式恢复规则取得新 epoch/Job claim 和新执行 grant。原会话/工作区缺失或来源校验失败时明确失败并保留历史，新 Provider/节点/会话只能开始关联新 Run。事件补送、原结果核对与新工作授权分开，旧 epoch 事件不得提交 Canonical。

若仍有服务器有效 owner/lease 治理的 Runner Execution，先撤销 Harness dispatch 并拒绝所有新的 Harness/typed tool 工作，保留原 Binding 可提交状态、epoch 与 Job claim，仅由原 owner 按原 Execution 完成执行与收集，或执行有审计的受控取消；收尾后才转 `RECOVERY_REQUIRED` 并推进需要更换 epoch/new claim 的 Harness 恢复。无有效 Runner 时可直接进入受控恢复。不能抢先改变 Binding 状态/epoch 或撤销有效 claim 使原 Runner 的正常提交变成迟到结果，也不放宽 `RECOVERY_REQUIRED` 的既有提交准入；不能以本地恢复绕过每 Run 单活跃 Job 或创建替代 Execution 冒充对账。

`WAITING_INPUT` 保留已有持久问题、原 Session/节点/workspace，不能由 reconnect 代替有效回答消费和恢复准入；连接丢失不是虚构人工问题的理由。CLOSED/FAILED/CANCELLED 仍为不可重开的终态，ADR-014 的独立 Gate 仍不调用 Connector/Harness。离线 cancel/设备撤销先在平台持久生效，拒绝新 dispatch、工具提交与源码/Artifact 验收；远端中断/清理可标记待执行。设备回连后只获精确的查询/清理权限，不补发失效工作，清理完成与任务取消分别审计。

---

## 23. TMP 与 MCP 分工

```text
TMP = Task Contract
Worker MCP = Run-scoped Runtime Domain Tool Contract
Interactive MCP = Current-Agent Task Access / Explicit LOCAL Execution Binding（ADR-016 已实现，已部署生产，线上当前 Agent 核心周期已通过）
```

TMP 告诉任务 Harness“你要完成什么”；Worker MCP 允许该 Harness 在有效 Run / Binding / epoch / Job claim 下读取 Testing State、提交 Proposal、申请 Execution。ADR-016 的当前交互式 Agent 可提交/读取任务，也可经 LOCAL / INTERACTIVE_MCP 显式绑定成为该 Run 的唯一测试 Harness，复用同一 TMP 业务工具。聊天/MCP 连接本身不是执行 owner；执行权必须由受控绑定、真实当前会话身份及平台当前 claim 派生。

§24–26 定义 MCP 领域语义，持续会话 profile 需要可在会话内调用的版本化领域工具。本分支以 §25.2 的固定九工具实现该工具面；§24–25 的细粒度名称表达目标操作语义，不表示另有同名端点。v1alpha1 Codex 兼容路径仍采用逐 Mission 最终结果通道。正式 Execution 由平台校验和 Runner 执行，Agent 自行运行命令不能形成正式事实。

### 23.1 ADR-016 当前 Agent 接入与版本边界（已实现，已部署生产，线上当前 Agent 核心周期已通过）

HyperTest 是当前交互式 Agent 的外接测试平台；本地执行时，承担测试工作的就是这个当前 Agent。首版由本地 stdio MCP Server 配合配置 / Skill，经常驻 Connector 和新增 typed HTTPS 交互门面连接平台。提交/查询入口与绑定后的 TMP 执行入口分层授权，不因处于同一聊天或 MCP 连接就混用权限。当前分支已实现 MCP Server、受限 UDS、交互门面、持久客户端 journal 和首个 `codex-desktop-stdio/v1` 当前 Agent 宿主 adapter；已部署生产，线上当前 Agent 核心周期已通过；真实当前 Codex Desktop Agent 的隔离端到端周期已验收，范围与限制见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)。现有 Run-scoped 内部 relay 保持内部用途，不能直接作为公开入口。当前宿主适配能力不代表所有 Provider / 客户端均已支持 LOCAL 绑定。

此前隔离真实验收由当前 Agent 经官方 MCP ClientSession / 透明 stdio console、私有 UDS、证书校验 HTTPS、持久 inbox 和原 Job Worker 完成四个 Mission，接受四个测试实现；独立可信 Docker Runner 的正式 Execution 运行 27 项 HTTP 测试全部通过。五个 RUNNER / VERIFIED Evidence 均经 MCP 读取并校验 SHA-256 / 字节数，平台形成 `FINAL / RELEASE_READY`，报告接受后 Run / Job 为 COMPLETED / SUCCEEDED，平台 Binding / 主 AgentSession 为 CLOSED；报告的两页读取也完成版本、hash 和长度核验。用户原生聊天仍可使用，且只存在一个主 native Session、一个正式 Execution 和一个 `request_execution` inbox 记录。该验收不宣称将新工具目录热加载进已打开聊天，也不代表其他宿主已取得 LOCAL 绑定能力。最终 Worker-only 恢复路线由独立集成测试核验，早期现场恢复与后续修复的证据边界见[验收记录](../ADR016_ACCEPTANCE.md)。

新接入 profile 为 **`hypertest.interactive-mcp/v1alpha1`**，定义交互工具、执行绑定及当前 Agent 的 TMP 转发能力；它是 HyperTest 业务 profile，独立于 MCP 标准版本。实现使用兼容 SDK 协商受支持的 MCP 标准版本，不假定某个未知“最新”版本。既有 TMP `hypertest.tmp/v1alpha2`、`run-persistent-harness/v1`、Bridge `hypertest.harness-bridge/v1alpha1` 和 Connector `hypertest.harness-connector/v1alpha1` 保留现有 wire/业务语义；新 adapter 与权限入口须独立协商，不能给旧 relay 加字段就推定兼容。首版采用本机 stdio，不含 Remote MCP 或 MCP sampling。

本地 UDS 验证调用方、客户端安装实例和明确的 delegated integration grant，只提供批准的 typed 操作；插件不取得完整设备 bearer、全局 Operator key、Worker lease secret 或清理权限。配置 / Skill 说明调用流程，不保存秘密、不作为授权依据、不导入个人全部 MCP 配置。身份与授权由可信 adapter 提供，不由模型文本或 tool arguments 自报。

### 23.2 交互工具、执行工具与独立权限

首版提交、进度、Evidence 和报告读取提供七个入口工具，另有两个当前 Agent 执行绑定工具。下表是当前严格类型接口，未知参数拒绝；`get_*` / `list_*` / `read_*` 只读取记录/对账原身份，不启动执行。两个写入口 `hypertest_submit_task` 和 `hypertest_bind_execution` 分别创建任务和建立受控执行关联。

| 入口工具 | 请求与返回语义 | 必需 Project scope |
|---|---|---|
| `hypertest_submit_task` | 向已有 Project 提交固定输入与 execution mode/driver/节点选择；返回原子持久 receipt、Run 和初始 Job。 | `task:submit` |
| `hypertest_get_submission` | 按原 client instance / Project / submission key 读取最小提交回执、Run/初始 Job 身份；不读取测试结果。 | `task:submit` |
| `hypertest_get_progress` | 按 Project / Run 读取任务、Job、阶段、等待/恢复需求和平台 Verdict 引用，不把遥测或 Job 成功当质量通过。 | `run:read` |
| `hypertest_list_evidence` | 按 Run 分页读取有权限的 Evidence metadata、固定内容身份和所属 Execution/来源。 | `evidence:read` |
| `hypertest_read_evidence` | 按该 Run 的 Evidence ID/固定版本，有界读取经 hash 校验的内容。 | `evidence:read` |
| `hypertest_list_reports` | 按 Run 分页读取平台已接受的报告 metadata、schema、Artifact hash 和原 Verdict 引用。 | `report:read` |
| `hypertest_read_report` | 按报告 ID/固定版本读取正文，保留 `hypertest.report/run-summary/v1` 原 schema、hash 和新鲜度说明。 | `report:read` |
| `hypertest_bind_execution` | 用私有持久 `attach_key` 将受信宿主证明的当前 Agent/native session、node、workspace 和固定源码关联到指定 LOCAL / INTERACTIVE_MCP Run；返回原绑定身份和受控状态。 | `run:execute`，并须通过绑定准入 |
| `hypertest_get_execution` | 按原 Run / attach key 查询执行关联、当前授权与 coordinator 状态；未决工具另按原 transport/business key 查询，不新绑定、不启动 turn/Runner。 | `run:execute` |

`InteractiveIntegrationGrant` 的 `task:submit`、`run:read`、`evidence:read`、`report:read`、`run:execute` 五种 scope 分别授权指定 actor/client instance 的 Project。提交权不继承结果读取或执行权；读取权不授予执行权，执行权也不等于 Worker claim。每次请求校验当前 grant、有效期、撤销、actor/client、Project、Run 与对象归属。grant 与设备配对、NodeProjectCapability、Run 短执行 grant、Worker claim、清理授权和 Operator key 分离；轮换/撤销按各自范围生效，旧 cursor/缓存不能绕过当前读权限。

完成 §23.6 显式绑定且持有当前短执行 grant 后，当前 Agent 才能使用 §25.2 的现有九个 TMP 工具：`get_state`、`request_mission`、`complete_mission`、`request_execution`、`ask_user`、`evaluate_gate`、`submit_report`、`request_gitlab_issue`、`get_issue`。这些执行工具保留原名字、严格业务 Schema 和 handler；它们具有既有 Proposal/Runner/Gate/报告/受控 Issue 副作用，不能由七个提交/读取工具或仅 integration scope 代替其执行 fencing。新 adapter 通过平台 coordinator 注入被验证的 Run/Binding/epoch/Session/Attempt/call 范围，不直接公开内部 relay，不给模型 Job lease 原始秘密。

首版不新增任意外部写入、业务 cancel、恢复、设备配对、source upload 或人工回答工具；这些仍走既有受控入口。执行态的 `ask_user`、Gate 和 Issue 属于原 TMP 流程；Issue 使用现有 request/get 及项目/责任人/事实授权策略。

### 23.3 固定任务输入、执行位置与原子回执

产品 **`execution_mode=CLOUD|LOCAL` 指 Agent/Harness 在哪里承担任务，不表示正式 Runner 在哪里执行**。`execution_driver=PLATFORM_MANAGED|INTERACTIVE_MCP` 是 Operational 驱动方式，不是第三种 Harness mode。CLOUD 对应 `SERVER_HOST + PLATFORM_MANAGED`；LOCAL 对应 `LOCAL_CONNECTOR`，可选择 ADR-015 既有平台托管 driver，或本 ADR 的当前 Agent `INTERACTIVE_MCP` driver。模式、driver、稳定 node、来源信任/transfer 策略在新请求中显式规范化并冻结；旧无新字段请求只按其原 SERVER_HOST/LOCAL_CONNECTOR 行为映射，不重写历史 payload。省略产品选择只可按版本化兼容缺省解释为 CLOUD / SERVER_HOST / PLATFORM_MANAGED，不因本地离线隐式回退。

任务针对已有且获授权 Project，固定 credential-free origin、完整 commit SHA、PRD/configuration 精确内容或已验证不可变引用、受控环境与生效 Policy。LOCAL 延续 ADR-015 的已登记节点及 `ACCEPTED` SourceBundleTransfer 归属/来源核验条件；SERVER_HOST 保留其既有受控 pinned source 路径，不强制新增 bundle。插件不把 dirty/untracked checkout 当输入、不自行授予 source-acquisition 或 Git/问题单权限；需要源码时先经已有 Web / Connector 准备并接受，不能以 MCP 模型提供的任意 URL/目录替代。来源、环境和 Policy 不由聊天文本绕过准入。

当前交互门面在同一数据库事务中原子保存 accepted receipt、创建/复用 bootstrap SourceSnapshot/PolicySnapshot 和新 Run、冻结 harness selection / execution driver、初始 `ADVANCE_RUN` DurableJob 及配对 Audit/Outbox；事务提交后才返回持久身份。环境预检、Git/网络、输入 Artifact 物化等 I/O 在聚合行锁外，返回后再检查当前授权、固定输入/来源、选择和幂等竞争。暂存 Artifact 不是 accepted receipt；当前创建 Run 与提交 Job 的两个 POST 不能被称为这一原子接口。

LOCAL / INTERACTIVE_MCP 的初始 Job 已持久入队，但必须等待有效当前 Agent 绑定后才通过执行准入；回执不等于绑定、开始执行或测试通过。平台 coordinator 仍是唯一 DurableJob/claim owner，并在 driver 判定后只向绑定当前 Agent 交付任务；不能同时通过旧 Bridge 启动第二个 Harness，也不能把 MCP Server 变成第二个平台 Worker。mode/driver、交互身份和 binding 关联是 Operational State，不进入 SourceSnapshot fingerprint 或 Gate hash。

### 23.4 提交幂等、绑定幂等与未知结果

客户端使用持久安装身份 `client_instance_id`，首次有副作用提交前将 `submission_key` 和版本化规范输入摘要写入私有 journal。平台唯一范围为 **`(actor_identity_id, client_instance_id, project_id, submission_key)`**；actor 从 grant 推导，不能由模型自报。版本化请求 digest 覆盖固定 origin/SHA、PRD/configuration 精确字节或固定身份、环境选择/生效 Policy、execution mode/driver、harness mode/node、来源信任/transfer 策略及适用的已接受 source 引用；receipt 的 frozen input manifest 另固定实际 SourceSnapshot / PolicySnapshot、环境解析结果、源码 fingerprint 与解析后的 Harness host，并保存独立固定摘要。重查原 key 先比较原请求摘要，不重新解析可变环境标签后伪造输入冲突。grant/token、MCP session、JSON-RPC/聊天调用 ID 不参与测试输入摘要，避免轮换把同一请求变成异输入；digest version 和缺省规范化规则固定。

同 key 同输入返回原 receipt/Run/初始 Job，异输入冲突。`InteractiveSubmissionReceipt.ACCEPTED` 与上述完整关联同事务落库；可记录无 Run/Job、带明确原因的 REJECTED 提交结果，但不增加 Canonical Task 或 TestRun 提交状态。写请求失答、超时或连接取消后，UNKNOWN 只属于客户端 journal；仅用原 key 调用 `hypertest_get_submission`。NOT_FOUND 只表示该次查询未观察到回执，不证明原请求未创建；不自动重发 POST、换 key 或另开 Run。新测试轮次必须有新的明确用户意图。

绑定也须在首次写入前持久保存 **`attach_key`、目标 Run、可信当前会话/工作区和版本化输入摘要**，平台唯一范围为 **`(actor_identity_id, client_instance_id, test_run_id, attach_key)`**。摘要固定 native/session、node、workspace/source、mode/driver；token/grant、可变 claim 和当前 epoch 不进入固定摘要，首次 `attached_epoch` 留作历史，当前 epoch 从原 Binding 投影。`hypertest_bind_execution` 同 key 同输入返回原执行关联，异输入冲突；其他唯一/归属约束以领域模型 §23.10 为准。ACK 丢失、MCP 重启或超时后只能用原 attach key 调用 `hypertest_get_execution` 对账，不能重绑、伪造新 native ID、换 key 或用重复请求重获执行权。绑定 UNKNOWN 也只属于客户端状态，不是新的 Run/Binding 生命周期。既有 TMP 工具另按原 `idempotency_key` / RunToolCall 对账，读取原结果不等于重放 Proposal、Runner 或 Issue。

### 23.5 有界读取、固定对象版本与非指令内容

所有提交回执、进度、列表和内容逐次验证 actor/client → Project → Run → 具体对象；仅知道 UUID、hash、receipt 或 cursor 不授予访问权。Evidence 保留可信来源与原 Execution，报告保留原 schema、hash、Verdict 引用和新鲜度，未形成 Verdict 时明确未判定，不把 Agent 文本、Issue 或 Job 成功升格为正式事实。

列表有界分页，cursor 固定授权范围、查询条件和可验证的集合/对象版本；内容页固定 Evidence/Report ID、版本和 SHA-256，禁止拼接不同版本。Evidence/Report 使用同一版本化内容 envelope，至少含对象类型/ID/版本、Run、media type、encoding、总长度、固定 SHA-256、有界内容和下一页 cursor/终止标志。实现须协商并强制消息、单页/总内容及媒体类型上限；cursor 过期、对象变化、缺失、篡改或不支持媒体类型明确拒绝，不静默读取“最新”或返回任意下载链接。

平台只按受控对象 ID 解析 Artifact Store，读取内容时重新验证固定 hash/完整性；模型不能给任意 URL、绝对路径、storage URI 或 Provider transcript 作为读取目标。metadata 不暴露存储路径、秘密和原生对话。PRD、报告、日志与 Evidence 均按来源明确标为不可信数据，正文命令/链接不能成为新指令、grant 或平台决策；它们不扩大入口 scope 或绑定执行工具范围。

### 23.6 当前 Agent 的唯一执行绑定、生命周期与恢复

`hypertest_bind_execution` 只适用于已选择 LOCAL / INTERACTIVE_MCP 的 Run。受控宿主 adapter 必须证明当前 Agent 的 Provider 与真实 native continuation/session 身份、已登记 node、专属受控 workspace、已接受固定源码和宿主生命周期；模型自报字符串、MCP session/进程 ID 或连接存活不构成该证明。平台确认当前 actor/client 的 `run:execute`、匹配的当前设备身份与节点 Project harness capability、source 权限、Run 排他与执行能力后，将当前 Agent 作为该 Run 唯一主 AgentSession/原生会话绑定，不额外启动 CLI、影子 Session 或第二 Worker。不支持可信当前会话身份及生命周期的宿主只能提交/读取或选择 CLOUD，必须拒绝 LOCAL 交互绑定。

新增 `InteractiveExecutionBinding` 是既有 `RunExecutionBinding` / 主 AgentSession 的 1:1 Operational 引用，固定 actor/client、Run、mode/driver、node、真实 Provider/native session、workspace/source、attach key 和输入摘要；首次 bind 原子建立所需原 Binding/主 Session/Placement 及此登记，已存在的绑定不得替换。它不是第二套运行绑定。现有 `UNIQUE(provider, provider_session_id)` 与主 Session 唯一性继续有效：一个真实 native 执行会话首版只绑定一个 Run，可提交/读取其他 Run，不能在同一聊天中接管另一执行 Run 或伪造复合 ID。另一执行 Run 需要用户/宿主建立真实新 native 上下文并显式创建新 Run，Connector 不偷偷 spawn。

初次 attach 的已实现顺序为：先凭当前 `run:execute`、设备/节点 harness capability、可信宿主证明及 Run 排他约束，在互斥事务中登记唯一 Binding、已核验 Session、Placement 和 InteractiveExecutionBinding；该结构登记不要求尚未领取的初始 Job claim，也不授予领域执行权。登记完成后 coordinator 才按原规则领取 initial Job，再凭有效 claim/epoch 派生短执行 grant，当前 Agent 方可调用九个 TMP 工具。平台 Worker 在激活前核验并物化自己的固定源码镜像；本地受控 workspace 由可信宿主 adapter 核验，服务器不读取本地绝对路径。不能把执行工具的 claim/grant 前置要求套到结构登记而形成循环，也不能把结构登记成功等同于已经取得执行权。

平台 coordinator 持有唯一 server Job claim，经已核验的当前 attachment 发放有界短执行 grant（当前配置上限 120 秒，且不越过 Job / integration / 设备有效期），并将每个工具请求映射到固定 Run/Binding/epoch/Session/call/当前 Mission/Attempt 与工具范围；客户端只有 integration `run:execute` 仍不足以执行九工具。短 grant 固定原 `device_grant_id`，逐次检查该精确设备 grant，而非接受同 node 的任意新凭据；设备 token 轮换撤销旧设备 grant 后，旧短 grant 和已排队请求失去执行权，新设备 grant 不使其复活。平台在准入、消费、外部 I/O 返回、领域写事务与结果读取时重新 fencing；领域提交按 Run → Binding → Job 后锁定当前授权引用，与撤销串行。未绑定、grant 失效、旧 epoch/claim、错误 Session/workspace 或阶段的调用拒绝；设备在线、Worker Job heartbeat 或 Connector 心跳不能续当前 Agent grant。

`request_mission` 返回冻结契约，`complete_mission` 提交 Proposal 并经原 Verifier 接受，`request_execution` 仍由平台可信 Runner 执行；本地 Agent 自行执行/日志不是正式 Evidence。`ask_user`、报告完成及 interrupt/close 只暂停/结束本 Run 的活动工作、授权和绑定，不终止用户整个聊天。人工问题/回答继续遵守 §29；报告接受关闭 Run 主会话的测试关联，不能因此声称关闭了用户客户端。原 managed Bridge 的进程中断语义不原样套给当前聊天。

客户端可继续拥有用户独立授予的原生工具，但 HyperTest 接入不会加载/扩大个人全部 MCP 或赋予任意外部写权；平台只能 fence 本 Run 提交，不能保证终止用户所有 Agent 进程。宿主 adapter 要提供可验证的 Run attachment/授权活跃时长与停止/脱离信号，预算继续有界且恢复不重置；整个聊天在线时间或模型自报耗时不能冒充旧 Bridge 的可信 stopped/elapsed 预算证明，缺少能力必须明确拒绝执行/恢复。

仅 MCP transport 短暂抖动时暂停新的执行请求，先以原 attach key 和工具幂等身份查询/对账；连接抖动不等于宿主已结束，也不自动撤销全部仍有效授权。聊天关闭、宿主结束、attachment 不再有效或无法证明当前 Agent 活动后，本地任务推进停止，对应执行 grant 撤销或按有界 TTL 到期；常驻 Connector 不得伪造 Agent 心跳、代替推理、自动重开 native 会话或改派服务器。原宿主/native Session、attachment、workspace/源码、平台 lease 与当前 grant 确仍有效时，经过可信核验和明确准入才可显式继续，不能因重连自动 resume。授权失效则按原 owner/call fencing 和显式 epoch 恢复，不能通过重连/重绑重新授权；新 native 会话需要新 Run。WAITING_INPUT 的答案不能因重连重复消费，CLOSED/FAILED/CANCELLED 不重开。

客户端断线/工具 cancellation 不是业务 cancel，已接受任务和已发外部副作用保留原历史。仍有效的服务器 Runner 先按原 Execution/owner 完成收集或受控取消，保持原 Binding 可提交状态/epoch/claim；随后才进入需要换 epoch/claim 的 Harness 恢复，不能绕过单活跃 Job 或重新请求 Runner。未知 Issue 只用原 operation 查询对账；撤权不回滚既有副作用，旧 generation 只可获窄管理对账/清理，不能继续写 Canonical。恢复仍须操作者通过独立管理接口，携带当前 integration / 原节点设备授权、可信宿主证明及 expected epoch / row version，核对原会话/工作区/来源并 fence；首版 MCP 没有恢复工具，也不能把它隐式送入 managed Bridge 的 create/resume/interrupt。API 仅校验和持久化已有 `RuntimeControlRequest.RECOVER_BINDING` 类型的交互恢复命令，按 execution attachment / `retry_key` 去重，不在 API 执行 Git 或读取服务器源码镜像。命令只含固定身份、expected epoch/version、宿主证明与当前 integration / 精确设备 grant 引用，不传原始 token 或任意路径；可信 Worker 从原 Binding / 已接受 transfer 解析固定源码，在行锁外核验 workspace，再重锁 Run 并复核全部权限、版本、原会话和旧 Job / Runner 状态后执行恢复。原 Job 已终态且 Runner 已结算后，恢复递增原 Binding epoch，并新建关联原 Job 的 retry Job，不重开终态 Job。原请求成功仍返回绑定投影与 `new_job_id`；有限等待尚未确认时返回 `QUEUED` / `RUNNING` / `UNKNOWN` 及 `control_request_id` / 原 `retry_key`，操作者用 `GET /interactive/executions/{id}/recoveries/by-key` 查询原命令。相同 key 不重做 Worker 恢复，UNKNOWN 不换 key 自动重放；须核对原 Binding / Job 历史。当前 client 还须显式 continue 取得新短 grant；旧 epoch / 旧短 grant 继续拒绝。ADR-014 的 CLOSED-only Gate 治理不重开当前 Agent 的测试绑定。


### 23.7 持久工具 transport inbox 与唯一 Worker 消费

LOCAL / INTERACTIVE_MCP 的九个执行工具使用 `InteractiveToolRequest` 持久 inbox。typed HTTPS API 只完成当前身份/短 grant 校验、严格参数验证、入队、有限等待及原结果查询；不调用 `HarnessTools.dispatch`、启动 Provider、调用 Docker 或产生正式 Execution。inbox 是原 `ADVANCE_RUN` DurableJob 内的受控传输 mailbox，不是第二任务队列或第二逻辑 Worker。该 Job 的 coordinator 在原 server claim 下串行消费，同一 `HarnessTools` handler 继续负责 Mission / Proposal / Verifier / Runner / Gate / Report / Issue；平台 API 无需 Docker 权限。

客户端在首次发请求前将稳定 transport key 写入私有 journal。公共工具 wrapper 可携 `execution_id`、`request_key` 和原样嵌套的 `arguments`；受控 adapter 剥离路由字段，将 key 放入 `X-Hypertest-Request-Key`，不把 key、宿主证明或秘密混入严格 TMP 业务 Schema。七个写工具的 key 必须等于其原 `arguments.idempotency_key`；无业务幂等键的 `get_state` / `get_issue` 使用独立 transport key。平台在同一 execution attachment 内按 key 唯一，并比较工具名及规范化业务参数 digest；key 不因新 Job、epoch 或重连而改变，不将 MCP/JSON-RPC request ID 作为业务身份。

inbox 只保存 identity / grant / Job / epoch / claim 摘要引用及规范业务参数，不保存 HTTP integration bearer、设备 token、短 execution token 或原 server lease secret。真正消费前和每次领域提交重新验证原 grant、精确设备授权、node / Project capability、原 Binding / epoch / Session 及当前 Job claim；队列记录本身不是权限。先锁 Run / Binding / Job 与授权引用，再认领 request；外部 I/O 不持这些行锁。另一 owner 不得接管旧 `RUNNING` 请求重调 handler。

当前 POST `/interactive/executions/{id}/tools/{name}` 与 GET `/interactive/executions/{id}/tools/by-key` 使用同一 transport envelope：`status`、`request_id`、稳定 `tool_call_id`、`request_key` / `idempotency_key`、`result` 和受控 `error_code`。暂态为 `QUEUED` / `RUNNING`；正常完成为 `SUCCEEDED` 或 `REJECTED`，结果不确定为 `UNKNOWN`。查询不存在返回 `NOT_FOUND`，不据此自动重新提交。`SUCCEEDED` 只表示 handler 结果已经记录，其 `result.status` 仍可能是业务拒绝或未完成；不表示 Proposal 已接受、测试 PASS 或质量放行。客户端可将成功 envelope 解包回原业务结果并附 transport 引用，不能覆盖业务状态。

API 当前最多等待 15 秒，随后返回已持久暂态；HTTP 超时、stdio 退出或取消等待协程不取消独立 Worker 的 handler / 已接受 Runner 请求。客户端对所有已发送、已确认或未知写入只 GET 原 key，不自动重 POST、换 key、换 Job 重放。`UNKNOWN` 是 transport / 操作知识状态，可以持久于 inbox / 原 RunToolCall，不是新的 Canonical TestRun 状态；它只允许依据精确匹配的原 RunToolCall key / 工具 / digest / 终态结果对账，不回到 QUEUED / RUNNING。原 Worker claim 结束后，未执行 `QUEUED` 请求落为 `REJECTED`，未完成 `RUNNING` 请求落为 `UNKNOWN`，不留给新 owner 消费。已接受的可信 Runner 在原仍有效 claim / Execution 下先完成或受控取消，再结束交互 Job；UNKNOWN Issue 仍只查询原 operation，不重复外部 POST。

明确 continue 可以在原身份、attachment、当前 Job / epoch 与尚有效原 grant 下续发有界短 grant，或为首次 / 显式恢复后的新 Job 发放首个 grant。原 grant 已撤或到期时，不能利用 coordinator 尚未观察到失效的窗口在同 epoch 重新授权；须先对账并走 §23.6 的操作者显式恢复。inbox、短 grant 和预算是 Operational 记录，不改变 Canonical 事实来源、Snapshot fingerprint 或 Gate hash。

---

## 24. HyperTest MCP Read Tools

本节列出 Worker/TMP 的任务读取语义；ADR-016 当前 Agent 完成显式执行绑定后可经受控 adapter 使用 §25.2 的实际映射。仅有七个提交/读取入口权限时不能取得这些执行工具，也不授权任何客户端直接调用内部 relay。

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

本节及 §25.1–25.2 只适用于有效 Run 绑定下的任务 Harness，包括 ADR-016 完成当前 Agent 执行绑定的 LOCAL 路径。七个提交/读取工具不授予 Proposal/阶段/Runner/Gate/报告写入/Issue 权限；这些动作仍须原 TMP 工具及当前执行授权。

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

报告 envelope 至少声明 schema version、TestRun、SourceSnapshot、完整 SHA、PolicySnapshot、summary、coverage / execution / evidence / finding 引用、未完成项及平台 Verdict 引用（若已形成）；Markdown / HTML 正文作为有 hash 的 Artifact 保存。Agent 生成的摘要、解释和建议属于报告内容，质量结论只引用平台已持久 Verdict，未形成时明确标示未判定。平台验证必需阶段、引用范围和内容完整性后才能接受 Run completion；报告写入失败或存在未满足 guard 不得伪报完整周期结束。本分支的完成报告使用 §25.2 实际参数及领域模型 §23.7 的 Operational RunReport，必须引用已形成的最新正式 Verdict；不新增报告 MissionType 或另一个 Canonical 质量结论。

### 25.2 本分支实际九工具与分页契约

本节 Worker/TMP 工具名不带 `hypertest.` 前缀；仅向当前有效 Run Harness 开放下表九个名字，运行时 `inputSchema` 由 Worker 的严格类型模型产生，未知字段拒绝。Run / Binding / Session / Job / epoch 由受信传输上下文提供并由 Worker 核验，不要求 Agent 自报授权身份。§24–25 的语义通过下表映射，不能把示例 envelope 或细粒度语义名称直接当作实际工具参数。ADR-016 的新 adapter 对已显式绑定当前 Agent 复用同名工具/Schema/handler，不向未绑定客户端默认开放，也不直接暴露原 relay。

| 实际工具 | 参数与语义映射 |
|---|---|
| `get_state` | `resource`、`offset`、`limit` 及对应的 `collection` / `entity_id` / `mission_id` / `path` / `evidence_id`；统一读取本 Run 的状态、冻结输入、契约、源码与可信 Evidence。 |
| `request_mission` | `mission_type`、`idempotency_key`；本版支持需求、风险、设计、实现和失败诊断五种 typed intent，返回确定性准入后的冻结契约。 |
| `complete_mission` | `mission_id`、`attempt_id`、`result`、`idempotency_key`；`result.protocol=hypertest.tmp/v1alpha2`，沿用结构化 Proposal 验证语义，由 Verifier 原子接受 / 拒绝。 |
| `request_execution` | `idempotency_key`；平台从绑定的固定 Run 输入、已接受实现和受控环境推导正式执行，Agent 不传命令、镜像或任意工作目录。 |
| `ask_user` | `scope`、`request`、`idempotency_key`；`request` 保留既有 HumanInputRequest 约束，成功确认后结束当前 turn，按 §29.1 暂停。 |
| `evaluate_gate` | `idempotency_key`；实现 `request_gate` 语义，返回平台决定及 Verdict 引用。 |
| `submit_report` | `schema_version`、`test_run_id`、`source_snapshot_id`、`policy_snapshot_id`、`commit_sha`、`summary`、`markdown`、`execution_keys`、`evidence_keys`、`finding_keys`、`verdict_key`、`unresolved`、`idempotency_key`；必须引用最新正式 Verdict，平台另核验其覆盖、状态 hash 与 Artifact 新鲜度。 |
| `request_gitlab_issue` | `finding_id`、`title`、`description`、`assignee`、`idempotency_key`；Run / SHA / Evidence 由已接受 Finding 与绑定推导，GitLab 项目和责任人权限由 Worker 固定策略解析。 |
| `get_issue` | `operation_id`；读取或 GET 对账既有操作，不能再次 POST。 |

`get_state.resource` 允许 `state`、`source`、`evidence`、`prd`、`configuration`、`entity`、`contract`、`coverage`、`human_inputs`、`operations`。Canonical 集合默认每类 30 行，`limit` 范围 1–100；完整响应最多 500,000 UTF-8 JSON 字节，达到预算会减少实际行数并返回正确的 `collections.<name>.next_offset`。大行显式标为 `_truncated` 并提供 `_detail`；`entity` 按 collection / entity_id 读完整原值，`contract` 按 mission_id 读完整冻结契约，不能把摘要当作全部目标或验收规则。

文本资源每页最多 24,000 Unicode 字符，`offset` / `next_offset` 是字符索引而非字节索引。`entity`、`contract`、`coverage`、`human_inputs`、`operations` 使用 `encoding=json` 的 `content` 文本页，按 next_offset 拼接后解析；其他资源按对应文本或源码列表结构分页。Mission 响应中的大型 PRD / configuration 摘要提供后续资源引用，原始 spec / targets / Schema / 内容不被截断或改写。写调用若已提交而响应较大，返回已持久结果身份和显式读取指引，不因响应超限把已接受事实改称失败。

`operations` 提供有界、安全的 GitLab operation ID / 状态 / Finding 引用及已核验 URL，并暴露可对账的领域工具记录；不返回凭据、授权配置或原 draft。Worker 保留的 `__bridge_call__` 预算账本不是第十个工具。工具 `STARTED` / `UNKNOWN` 的重试按原输入摘要与既有 Canonical / Operational 关联核对；外部结果未知时不自动重放 Provider、正式执行或 GitLab POST。

---

## 26. Execution Request

本节属于内部 Worker/TMP 的正式执行请求契约。ADR-016 的交互 `submit_task` 只创建受控任务及初始 Job，不直接暴露 `request_execution` 或接受外部模型给定的 ExecutionSpec。

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

### 29.1 持续会话 profile 的 Mission / Run scope 问题（本分支已实现）

`hypertest.ask_user` 必须显式声明 `scope=mission` 或 `scope=run`，由平台验证问题实际所处的工作边界；目标 v1alpha2 工具不把现有 v1alpha1 的 mission_id / attempt_id 改为 nullable，也不改写旧问题 Schema：

- **Mission scope**：存在当前未终态 Mission / Attempt 时，沿用 `MissionInputRequest` 的归属、问答和同 Attempt 恢复规则；问题必须引用当前 Run 的绑定、主 Session、当前 Job 及该 Mission / Attempt。
- **Run scope**：用于前一 Mission 已完成后的阶段边界、报告准备或 GitLab 策略决策，创建独立 `RunInputRequest`（本分支 `0013_run_bindings`），归属同一 RunExecutionBinding、主 Session 与当前 DurableJob；问题有稳定 question_id、不可变问题 / 选项 / 归属及受控回答状态。不得虚构 Mission / Attempt、重开已完成 Mission 或改变历史 Attempt 状态以容纳该问题。

两个 scope 均在 Run 锁下验证当前有效 Binding / epoch / Job claim，并共同保证同一 Run 同时最多一个 PENDING / ANSWERED 问题，而不是在两张表各允许一个。提出问题、保存已完成步骤、Job / 主 Session / Binding 进入 WAITING_INPUT、释放实时执行 lease 在同一事务提交；Mission scope 还暂停其当前未终态 Mission，Run scope 不触碰已完成阶段。问题、选项和归属不可修改，回答采用幂等键、预期 row_version 与只写一次语义；字段、唯一性、状态和锁序以领域模型为准，不能仅靠工具 payload 声明实现。

答案与原 Job 重新排队在同一事务提交，不新建 Job、Attempt 或会话。重新取得有效 claim 后，校验同一 Binding / 原生 Session / 受控工作区，把答案按问题身份原子置为 CONSUMED，并恢复原主会话；Mission scope 另恢复其原未终态 Mission / Attempt，Run scope 只继续 Run 级工作，不改变已完成 Mission。正常问答恢复不增加 binding_epoch，不重置阶段预算，不改写固定输入 / Policy / spec，答案也不自动扩大外部操作权限。

暂停后查询、核验、中断和清理使用 §22.1 的窄管理授权；新 Provider 工作仍须恢复后的有效执行授权。取消终止任一 scope 的开放问题，保留问题、回答、归属和成对 Audit / Outbox 历史；取消 / 失联 / 旧 epoch 后的迟到回答或执行结果不得推进任务。原生会话无法恢复时明确失败并保留历史，不能创建替代会话冒充续接。`RunInputRequest` 及跨 scope 唯一性已由本分支 `0013_run_bindings` additive 实现，现有 v1alpha1 仅支持原 Mission scope 控制路径。

---

## 30. Approval

对于 production mutation、database delete、external side effect、secret access 等危险操作，Mission 可声明审批策略。Adapter 尽量映射 Provider Approval / Sandbox 能力；Provider 不支持时由 HyperTest Tool Layer 拦截。预先配置的授权策略可以允许受控外部操作；问题或回答不能绕过固定权限和平台验证。

### 30.1 GitLab 缺陷协作（服务器兼容保留，本地真实创建已独立核验）

Harness 通过 `hypertest.request_gitlab_issue` 提交 Issue draft、当前 Run / SHA、已接受 Finding 及可信 Evidence 引用和可选责任人建议。平台检查预先配置的 GitLab Project 白名单、提单 / 通知策略、责任人映射、调用者权限和关联范围；未配置或超出规则时请求人工决策，不把 GitLab token、任意项目 URL 或直接外部写权限暴露给 Agent。关键决策可通过 §29 暂停询问；若前一 Mission 已完成，使用 §29.1 的 Run scope 问题，不重开原 Mission / Attempt。非阻塞提单可返回操作句柄供同会话继续查询。

外部操作以稳定 correlation / idempotency key 去重，保存 draft 摘要、Run / Finding / Evidence 关联、授权来源、请求状态及实际 GitLab project / issue IID / URL；同一逻辑缺陷的重复调用应返回既有 Issue 或明确更新请求，不重复创建。超时或连接中断产生 outcome unknown 时，必须先依据 correlation 对账；不能假定失败后自动重提。审计记录平台实际确认的外部结果，Issue 本身不成为可信 Evidence 或质量 Verdict。本分支已实现固定项目 / 责任人策略、`0014` 操作账本及仅 GET 的未知结果对账；未配置或未授权时返回 `DECISION_REQUIRED`。服务器兼容回归使用注入 HTTP transport；ADR-015 本地受控 glab 已在明确批准的隔离验收中完成一次真实创建、负责人及引用核验，见[总验收记录](../ADR015_ACCEPTANCE.md)。本次生产部署没有新增外部问题单写入，UNKNOWN 的真实外部故障注入矩阵仍未全覆盖。

ADR-015 保留上述平台治理和服务器 executor，已实现 §22.4 的本地受控 executor；不改变现有工具参数、不把本地权限暴露给模型，也不由 `0014` 已实现推定本地执行/真实外部验收完成。mode/node 选择和委派记录遵守领域模型 §23.9；已登记 operation 的 executor、目标和摘要不可因重连或后端切换改变。

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

ADR-015 的本地连接中断按 §22.5 区分通道恢复和执行恢复，不能直接套用“服务器 Worker 租约过期”改变仍有效的 Runner Execution。dispatch/call 失效后的恢复保留固定 mode/node；超时的执行、工具写入及 Issue 创建先对账，不以消息重传代替显式执行授权。

本分支的实际预算为首次绑定时冻结的 `max_steps`、Runner 单次 timeout 与 Run 总 `harness_budget_seconds`（默认 3600，范围 1–7200 秒）。总预算按原生调用活跃墙钟时间计量，包含工具等待，不包含已停止后的人工等待；不是计费 token、金额或账号额度硬限制。每次 start 预留剩余预算；只有 Bridge 确认 `stopped` 并返回可信 `elapsed_seconds` 后，才按向上取整秒数结算并释放未用预留。未知调用保留全部预留，显式恢复须先取得停止与耗时证明；问答、新 Job、配置变化和 epoch 递增都不重置累计使用量。预算用尽不再启动新 turn。

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

本地节点离线时，平台取消与设备撤销先持久生效，远端清理按 §22.5 留下待完成状态；不能等待连接恢复才撤权，也不能声称无法确认的本地进程已经停止。重连仅授予精确历史调用的查询/清理权限，不能重新派发原工作或重开终态。

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

本分支 Bridge 区分 `SESSION_UNAVAILABLE`、`STALE_BINDING`、`CAPABILITY_UNSUPPORTED`、`OUTCOME_UNKNOWN` 等受控错误；这些属于独立 Bridge 传输，不加入当前 v1alpha1 enum 后假定兼容。Provider-specific Error 经脱敏和限长后隔离于受控 `provider_metadata`；原生 stderr、秘密与 reasoning 不直接成为用户错误详情或活动记录。

---

## 35. Schema Version

核心对象必须包含 protocol/version，例如 `hypertest.tmp/v1alpha1`。

演进路径：v1alpha1 → v1alpha2 → v1beta1 → v1。

同一 Major 优先 additive change；禁止无版本重命名 required field、改变字段语义或删除 enum value。

文档 v0.6、兼容 wire `hypertest.tmp/v1alpha1`、已实现持续会话 wire `hypertest.tmp/v1alpha2`、profile `run-persistent-harness/v1`、宿主 transport `hypertest.harness-bridge/v1alpha1` 与 ADR-015 已实现的独立远程 transport `hypertest.harness-connector/v1alpha1` 是不同版本轴。ADR-016 的 `hypertest.interactive-mcp/v1alpha1` 接入 profile 与交互门面已在当前分支实现，含 `0019` / `0020` 迁移，已部署生产，线上当前 Agent 核心周期已通过；真实当前 Codex Desktop Agent 的隔离端到端周期已验收，详见[验收记录](../ADR016_ACCEPTANCE.md)；不升级既有 wire/profile，其版本也不是 MCP 标准版本。ADR-015 生产已部署的事实另由[生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)证明；协议版本本身不证明上线或全部真实验收，线上核心周期已通过，扩展矩阵继续按实际范围登记。持续会话生命周期、能力要求和工具 envelope 只在新版本 / profile 明确协商后适用；旧 Run 仍按其冻结版本执行，不通过调整 Adapter 默认值重解释历史。

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

v1alpha1 兼容路径使用默认 Codex Harness，并提供 §29 的持久等待、Web 回答与明确原生 thread 的 Codex resume 控制路径。本分支 managed Bridge 另对实际 Codex CLI 版本、功能开关及精确 resume 参数做能力探测，并协商 transport / wire / profile / 固定九工具。它明确关闭原生 shell、filesystem、多 Agent 及外部通用工具；不能根据上述目标示例的 `true` 推断已开放。该能力限制描述平台托管路径，不宣称控制 ADR-016 用户当前 Agent 的全部独立工具；新绑定不能扩大其既有权限，仍须满足 §23.6 的来源/执行/事实边界。跨 Harness 选择和其他 Provider 的 resume 仍待独立实现与真实验收，Codex 的已验收范围见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)。

ADR-015 节点协商已要求声明 `SERVER_HOST / LOCAL_CONNECTOR`、支持的 Connector 版本、可恢复调用/事件 cursor、受控源码采集/传输及问题单 executor 能力与授权 scope。能力声明不是权限授予，Git/问题单登录就绪不表示可以访问任意项目。源码采集、传输和问题单操作属于 Connector 的受控适配器，不因部署本地而打开 Harness 原生 shell/filesystem 或外部通用工具。

---

## 37. Agent Selection

Mission 声明需要的 Capability，而不是硬编码必须使用 Codex / Claude。Scheduler 可在新 Run admission 考虑 Capability、Cost、Latency、Reliability、Model Quality、Workspace Affinity、Historical Success。目标 profile 的绑定一经建立，后续 Mission 只能在该会话能力内执行；能力不足时显式停止 / 请求决策，不在同一 Run 中静默换 Harness。Provider 可替换性意味着平台契约独立且新 Run 可选不同 Provider，不保证跨 Provider 搬运原生会话。

MVP 可简单配置 `default_agent = codex`。

---

## 38. Security Boundary

TMP 明确区分 Agent Identity、User Identity、HyperTest Service Identity、Runner Identity。

ADR-016 还区分交互客户端安装身份与 Run 执行身份。`InteractiveIntegrationGrant` 的项目提交/读取 scope 与 `run:execute` 分离；后者也须完成当前 Agent 的真实身份/Run 绑定，再派生当前短执行授权，不能直接转换成 Worker claim、设备配对、清理或 Operator 管理权限。交互 stdio/UDS 只使用限权委派，平台秘密不进入模型。该独立入口已在当前分支实现、已部署生产，线上当前 Agent 核心周期已通过；现有内部 relay 仍只服务绑定 Run，不是公开客户端 API。短执行 grant 固定精确原设备 grant，设备轮换不会把旧授权转给新凭据；API 的持久 inbox 不持原始 bearer / lease，只允许原 Job Worker 消费。

目标 Agent 对 HyperTest MCP 的访问权限由受控工具 Token 控制，至少绑定 mission_id / attempt_id（若适用）、test_run_id、project_id、agent_session_id、logical_worker_id、binding_epoch、allowed_tools、allowed_resources、expiration。Token 为可撤销、限范围的授权，容器 Worker 和 Bridge 另以服务身份认证；不得把原始 Job lease、宿主登录或 GitLab 管理凭据交给 Agent。

本分支平台托管路径采用分层授权落实上述范围：Agent 的 relay 仅持有可撤销、单 call 的随机 capability；Bridge 以独立执行 / 管理签名、固定绑定上下文、epoch、call 和短期 grant 约束传输，Worker 每次工具读取、写入及响应交付再核验当前数据库 claim、阶段、资源和策略。relay token 不自含所有领域权限，也不能越过 Worker 准入；不将其描述为独立通用 Mission Token 服务。该 managed profile 只开放九个受控 MCP 工具，明确声明 `native_shell=false`、`native_filesystem=false`；不由此推断 ADR-016 当前交互 Agent 的全部宿主权限，后者按 §23.6 仅取得指定 Run 的 TMP 工具权，原生探索不成为正式事实。v1alpha1 的最终结果路径保留原有边界。

ADR-015 的设备配对、源码来源采集、HTTPS transfer、dispatch 执行和问题单委派是独立 scope：用户本机拥有第三方凭据不等于平台或模型获授全部权限。节点只能使用批准 Project 的受控适配器；所有授权可撤销且不得携带第三方凭据内容，平台保留全局管理密钥。新模式不得放宽上述 Agent 能力；具体远程安全/恢复和来源验证契约见 §22.2–22.5。

Agent Session 不拥有项目全局管理员权限。

---

### 38.1 会话关闭后的平台操作者请求

ADR-014 的独立 Gate 不是 Agent `evaluate_gate` 工具调用。Agent 的工具仍要求运行中 Binding/epoch/Job claim；CLOSED Session 不能取得新工具 token、resume 或提交报告。可信平台只在领域模型 §23.8 的 CLOSED 主 Session/Binding、已接受报告、排他 Job 和有效 lease 条件下处理用户显式 EVALUATE_GATE/finalize=true，并保存必填 reason。

该操作不创建 Agent turn、Runner 请求或 Evidence，不改变主会话状态、预算、报告 envelope 或旧 Verdict。请求理由和任务关联属于 Operational 审计，不加入 TMP AgentContext 或 Gate Canonical hash。失败/取消/显式重试只影响对应 Gate Job。报告接口新增的 nullable 原 verdict 引用仅投影既有 envelope；旧报告内容及 SHA 不变。

## 39. Audit

Mission Created、Mission Dispatched、Tool Called、Proposal Submitted、Proposal Accepted、Execution Requested、Evidence Created、Verdict Changed 都必须产生 Audit Event。

---

## 40. End-to-End Example

以下是 ADR-013 持续会话 profile 的完整周期，本分支实际工具映射见 §25.2，真实验收范围见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)；当前 v1alpha1 仍为逐 Mission 新会话，仅支持同 Mission 人工等待后的原会话恢复。

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
  │              8. evaluate_gate（request_gate 语义）→ 平台持久 Verdict
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
