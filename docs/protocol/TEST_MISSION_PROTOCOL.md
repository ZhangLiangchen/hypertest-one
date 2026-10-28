# Test Mission Protocol Specification

> **2026-10-28 快速原型决策：** [ADR-028](../architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 覆盖本文与旧 ADR 中要求对被新实现替代且不兼容的旧实现、入口及对应数据无条件兼容或保留的条款。对应旧任务和关联记录可定向删除；现行合同、无关数据、用户源文件与凭据不因此改变。历史描述不代表旧记录将永久可访问。

**阅读范围（2026-10-27 起）：** 新 Local 归档协议以 [ADR-027](../architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 与本文 §51 为准；字段及状态由领域 §56 拥有。§45/47 的 SessionTask、Hooks/MCP、BIND/JOIN 与旧回执继续约束旧 profile 和历史，不是新归档前提。下文部署、发行与验收叙述记录各自时点，不能作为当前运行状态；交付和待办见 [TODO](../TODO.md) 及对应记录。

旧 Local `local-v0.1.0` 的真实宿主矩阵及其限定范围见[历史验收记录](../LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)与[矩阵](../local-acceptance/local-matrix-20261023.json)；该资格不自动扩展到新归档。

**Protocol Name:** TMP  
**Full Name:** Test Mission Protocol  
**Version:** v0.8

**Profile precedence:** ADR-027 and §51 govern new Local artifact archive. [ADR-018](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) and §45 govern legacy SessionTask synchronization, including the separately enabled ADR-026 collaboration profile. ADR-017 §44 and legacy execution contracts retain their own meanings and are not prerequisites for archive. Transport UNKNOWN is reconciled by the original key and is distinct from a report's test result.
**Status:** Draft  
**Owner:** HyperTest
**Native intake decision:** [ADR-017](../architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md)；新增独立业务 profile `native-framework-intake/v1alpha1`，本机 Operator 受控 typed API / 客户端，详见 §44。旧 TMP wire、九工具、MCP、Bridge / Connector 均不升级或重解释。旧 §5–43 的 Mission/Runner/Session 契约仅约束对应 legacy profile；native 的字段、准入和单 writer 能力由 §44 与领域 §49 定义。本轮不宣称新 MCP 工具、可信 CI 接入、正式 native PASS 或生产发布。
**Accepted target decision:** [ADR-013 — Containerized Platform and Persistent Harness](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
**Dual-mode implementation decision:** [ADR-015 — Dual-mode Harness and Local Connector](../architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)；Connector 契约及 `0015`—`0018` 已实现，隔离回归通过，核心隔离真实端到端验收通过，已部署生产，线上核心周期已通过，扩展故障矩阵继续逐设备登记；现有 TMP wire / profile / Host Bridge 版本保持。
**Interactive access implementation:** [ADR-016 — Interactive Agent MCP Access](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)；当前分支已实现 stdio MCP / 私有 UDS / typed HTTPS、当前 Agent 绑定及原 Worker 工具 inbox，包含 `0019_interactive_mcp` / `0020_interactive_tool_inbox`；已部署生产，线上当前 Agent 核心周期已通过（2026-10-20，Asia/Singapore）。隔离 API / Worker / 数据库及真实 Docker Runner 回归已通过；真实当前 Codex Desktop Agent 的隔离端到端周期已完成，见 [ADR-016 验收记录](../ADR016_ACCEPTANCE.md)及[机器可读证据](../evidence/adr016-20261020.json)。该隔离结果不替代下段独立生产验收，不改变 ADR-015 的历史发布与验收记录。
**Implementation boundary:** 已实现 v1alpha2 持续会话 profile、Host Bridge、九个领域工具及独立 Connector 传输；ADR-016 的九个交互入口与绑定后的九个 TMP 工具由独立授权接入，正式工具工作仍由原 Job Worker 执行。旧 v1alpha1 保留原语义，2026-10-19 正式容器化及 Codex 正反链路属于既有验收，各 Provider / driver / 外部集成分别登记。

生产发布为 PR #17 / `c7cd43ad6346d8ce6c85564f7838afbb017f2da4`，正式库已向前升至 `0020_interactive_tool_inbox`；PR / main CI 为967 passed、21 skipped。同一真实当前 Codex Desktop Agent 经官方 MCP SDK console 完成生产核心周期：2 Requirements / 3 Risks / 4 Cases / 4 Implementations，唯一平台可信 Docker Execution 的33项 HTTP 测试通过，五份 VERIFIED Evidence 与两页报告内容均经 MCP 读取并核验 hash / 字节数，形成 FINAL `RELEASE_READY`。真实过期后的两次显式 Worker 恢复保留原 Run / native / workspace，epoch 1 → 2 → 3，旧 Job / Attempt 保留；最终历史保全另经39项只读检查通过。详细身份、时序与保全边界见[ADR-016 生产部署记录](../ADR016_PRODUCTION_DEPLOYMENT.md)及[生产机器证据](../evidence/adr016-production-20261020.json)。隔离验收的27项测试仍属其独立历史；本轮不宣称聊天原生工具目录热加载、运行中断线注入、两种原受管路径的新完整周期、私有 SUT 业务或新增问题单写入通过。

已包含 `0013_run_bindings` / `0014_harness_operations`；本地实现证据见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)，正式切换与恢复历史见[部署验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。历史 PR #10 当时部署源码 `828225d`，兼容 Host Bridge 保留 `95e92c5`，当时 schema 为0014；ADR-015 当时 schema 升至0018，历史发布与验收范围见[生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)；ADR-016 当次部署 schema 为0020，见[历史部署记录](../ADR016_PRODUCTION_DEPLOYMENT.md)；访问配置在[运维材料](../SERVER_OPERATIONS.md)维护。[ADR-014](../architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)的关闭后治理属于平台操作者接口，不扩展已关闭 Agent 的工具权限，也不改 TMP wire/profile 版本。受控 GitLab 真实创建已有 ADR-015 独立隔离验收；其他 Provider 与未执行扩展场景继续单独登记。


ADR-015 双模式、设备 / 项目授权、WSS 持久 mailbox、HTTPS 源码接收、本地问题单适配与显式恢复已实现，`0015_connector_nodes` → `0018_harness_selection` 已部署生产。核心隔离真实验收已通过，包括本地 Codex → 远端可信 Docker Runner → Evidence / Gate → 报告正反链、私有 Git 经 HTTPS 接受、原会话断线恢复及获准测试 Issue 的创建 / 负责人核验。这些隔离结果不冒称生产结果。生产切换已完成原数据、文件、认证、SSH / VPN 与服务器 Bridge 保全；严格外部 TLS、线上本地 Connector 核心周期和生产私有源码 source-only 接受补验已通过，后者未启动私有业务 Run 或问题单操作，扩展真实设备故障矩阵继续分别登记。该次发布与实际验收范围见 [ADR-015 生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)，隔离历史见 [ADR-015 总验收](../ADR015_ACCEPTANCE.md)，源码统计见[源码验收记录](../ADR015_ACCEPTANCE_SOURCE.md)。

---

## 1. 目标

Test Mission Protocol（TMP）定义 HyperTest 与外部 Agent Harness 之间的稳定协议。

支持目标包括 Codex、Claude Code、Pi、OpenCode 以及 Future Agent Harnesses。

TMP 不定义 Agent 内部如何 reason、plan、spawn subagent、manage context、retry tools；这些属于 Agent Harness 自身能力。

产品目标为：一个 SUT 对应长期 Project，HyperTest 管理计划 / 用例 / 任务 / 记录 / 证据 / 结论，Agent 调用项目已有框架 / CI。ADR-017 native 轮次按 §44 管理不可变输入与显式顺序贡献者交接；同一时刻只允许一个有效 writer。以下旧 managed / interactive TestRun 仍绑定一个逻辑任务 Worker 与持续主 Harness，使用不可变 SourceSnapshot / PolicySnapshot，自驱串行阶段并保留原会话恢复，不因新目标重解释历史。同 SHA 的显式复测仍可建立新轮次。

平台服务及任务 Worker 容器化。ADR-013 已实现的 `SERVER_HOST` 模式由服务器宿主 Host Harness Bridge 托管 Harness；ADR-015 已在本分支实现 `LOCAL_CONNECTOR` 模式，由用户设备的常驻 Connector 主动连接平台并托管本地 Harness。两种模式均保留一个 Run 的主会话、原生认证与受控工作区，不能因 Worker 容器重建而丢失会话身份。模式和节点在 Run 首次绑定时固定；本地模式不绑定浏览器标签页生命周期，不因离线改派服务器。部署边界见 ADR-013 / ADR-015，绑定、租约、生命周期和持久化约束以领域模型为准。

当前 `hypertest.tmp/v1alpha1` 兼容路径仍由 Web 提交 DurableJob、独立 Worker 调用 bounded Run test cycle controller，按 deterministic Planner 的 Canonical State gap 逐个启动 Mission；每次新 Attempt 创建会话，人工等待按 §29 恢复原会话。`max_steps` 限制当前平台工作单元；Job SUCCEEDED 不等于测试 PASS，Job payload 不是 Canonical State。本分支的持续会话使用 §6.1 独立协商的新 profile，不重解释旧 controller 或冻结的 v1alpha1 历史。

旧 Runner profile 的周期先以所选 Runner 的只读 fingerprint 预检实际 daemon / 可信镜像或显式 local 启用条件，成功后才进行 Git / Agent；前后重新验证归属，预检 I/O 不持 Run / Job 行锁。失败不创建正式 Execution / Evidence，预检成功也不等于测试通过。独立 Gate-only 操作不要求 Runner。

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

### 6.1 Legacy 持续会话 profile 与协商

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

旧 TMP profile 的 `EXECUTE_TESTS` 由 Runner 处理，Agent 通过 `request_execution` 申请。ADR-017 native profile 中 Agent 自行调用项目原生入口，随后按 §44 提交执行材料，平台 API 不运行测试；不能把两种执行语义混在同一请求。

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

### 9.1 Legacy controlled execution environment context

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

## 18. Legacy ImplementationProposal

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

示例应用符号需根据被测仓库调整。这个旧 Runner payload 支持 Python / pytest，payload 必须提供至少一个当前 Snapshot 下的 ACTIVE test_case_keys。Repository 与 Commit 必须匹配 Canonical SourceSnapshot；file_path 必须为安全相对 Python 路径，symbol 由 Python identifier / `::` 构成。正式 Runner 进一步限制安全 `tests/**/*.py` 和 pytest test function 目标。

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

## 23. Legacy TMP 与 MCP 分工

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

独立安装准备 CLI 不属于本 MCP profile：它仅在操作者从 owned `0600` 文件或真实终端隐藏输入明确提供既有 Operator 授权后，调用现有设备配对、项目 Harness capability 与交互注册 HTTP 管理接口，保存限权私有凭据；不新增 MCP 管理工具或从模型自报身份授予权限。安装 prompt / 客户端片段只含平台、Project、固定发行 / 摘要及文件路径，不含 key 或 token；安装与 doctor 查询不产生 Run、执行绑定、短期执行 grant、源码接受或 Issue 操作。

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

## 24. Legacy HyperTest MCP Read Tools

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

## 25. Legacy HyperTest MCP Proposal Tools

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

## 26. Legacy Runner Execution Request

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

在旧 profile，只有符合固定 Policy、来自可信 Runner 且已验证的 OFFICIAL Execution / Evidence 可进入原 Release Gate；native 材料不会进入这个 Gate。等待执行期间保持主会话身份；Runner 执行和事实提交仍具有独立可审计的身份、取消与幂等边界。

---

## 27. Agent 原生执行与正式事实边界

旧 TMP profile 下 Agent 自行执行命令仍属 exploratory context，不能绕过 Runner 把结果写成旧 OFFICIAL / VERIFIED Evidence。ADR-017 profile 下，Agent 应调用 SUT 已有原生框架并按 §44 保留实际结果为材料；平台分别校验完整性、报告一致性和独立来源。本轮材料 provenance=UNVERIFIED，合法 shell 输出、报告或 hash 都不能形成正式 native PASS。项目框架 / CI 的正式来源接入要求见 ADR-017 §8，不以平台重跑为唯一核验方法。

> **Project tools produce results; independently verified provenance and policy determine admissible evidence.**

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

## 36. Legacy 持续会话 Capability Negotiation

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

## 37. Legacy 持续会话 Agent Selection

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
5. 旧 TMP 的正式执行事实仍要求 Runner Evidence；native 材料按 §44 分层接受，未经独立来源验证不成为正式质量通过。
6. Mission Acceptance 由 HyperTest Verifier 决定。
7. 新轮次可选择不同 Harness；旧持续会话 Run 不得静默换 Provider，native 则使用 §44 的显式贡献者交接而不伪造 Provider 身份。
8. 旧任务的逻辑 Worker / 主 Session 绑定跨阶段与恢复保持；native current contributor / generation / 私有能力按 §44 受控切换，二者不能互换或回填。
9. 不同 Run 可以并发；同 Run 的 Mission / Attempt 串行且只有一个有效 owner。
10. 目标 profile 必须显式协商，不能改写旧 wire schema、固定输入或执行历史。

---

## 42. 协议定位

TMP 不应演进成 Generic Agent Protocol，而必须始终保持：

> **Testing-domain-specific Agent Work Protocol**

它描述 Requirement、Risk、Case、Implementation、Execution、Evidence、Finding 及受控报告 / 人工协作边界，而不描述 LLM thinking steps。旧持续主会话由 Harness 自驱；native 工程动作仍由 Agent 自驱，平台维持类型化 guard 与事实治理，不演进成自制 Generic Agent Loop。

---

## 43. Legacy TMP 最终定义（native 契约见 §44）

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

## 44. 原生框架材料接入 profile（ADR-017）

### 44.1 版本与实际调用方

`profile=native-framework-intake/v1alpha1` 是独立业务契约，不是新增 TMP wire、HarnessMode、RunnerBackend 或 MCP 标准版本。首版仅 opt-in FastAPI `/api/v1/native-runs` 和本机受保护客户端；MCP 的旧 `request_execution` 仍调用旧 Runner，不能附上新字段后改为本机执行。

所有请求继续要求明确 Operator 授权；Operator 管理客户端保管全局 key，不将其交给 Agent、MCP、任务材料或提示词。create / handoff 首次成功时一次返回 run/generation-scoped 随机 writer capability；平台只保存 hash，客户端以 owned `0600` 私有文件保管，日志 / GET / 普通幂等回执不返回原文或 hash。除 create / handoff / reconcile 三类 Operator 管理写外，其余写另带 `X-Hypertest-Native-Writer-Key` 并验证当前 contributor / generation / capability。可读取的 generation 和模型自报 session_ref 不授予写权。

首版由 Operator 确认管理调用与输入、Agent 负责原生工程动作；不宣称任意 Agent 已直接接入、contributor label 已证明真实 Provider 会话、或凭平台权限就可以执行 Git / 链写 / 问题单操作。

### 44.2 请求与返回

下列均为严格类型对象，未知字段拒绝；平台读写 PostgreSQL 记录，不执行 `command` 或访问 `cwd`。

create / 各写 envelope 的 `idempotency_key` 必须匹配 `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`，以保证原 key 在精确查询路径中可安全对账；不允许 slash / dot-segment 绕过身份。新格式不改写任何既有 legacy key。

| API | 契约 |
| --- | --- |
| `POST /native-runs` | `profile, project_id, idempotency_key, session_ref, plan`；`plan` 固定 `objective, scope, requirement_refs, risk_refs, inputs, cases`。原始 Proposal、Verifier 接受结果、计划与用例、初始 contributor/generation、operation 回执与 Audit/Outbox 同事务；响应含 run / contributor / generation 和仅首次可见 writer key |
| `GET /native-runs/{run_id}` | 读取固定计划、用例、贡献、执行 / 材料 / 验证 / 结论、交接及未决操作的受控投影，不返回凭据或任意存储路径 |
| `POST /native-runs/{run_id}/executions` | 写 envelope 为 `contributor_id, generation, idempotency_key`，加 `command, cwd, framework, started_at, finished_at, exit_code, results, materials`；执行已经在项目框架发生，API 仅登记观察 / 原件并追加平台验证 |
| `POST /native-runs/{run_id}/evaluate` | 相同写 envelope；平台从固定计划及完整已有事实确定 UNKNOWN/BLOCKED，不接受 Agent 传 decision |
| `POST /native-runs/{run_id}/handoffs` | Operator 显式管理操作，带原 contributor/generation、稳定 key、`successor_session_ref, remaining_work, reason`；核验原状态及未决操作后原子追加 handoff、递增 generation、换 contributor / 私有 writer capability；无需恢复旧 key，旧 key 失效 |
| `GET /native-runs/{run_id}/operations/{key}` | 按原 key 只读对账原请求与已提交结果，不重做调用、不返旧 capability |
| `GET /native-runs/submissions/{project_id}/{key}` | create 响应遗失时按原 Project/key 查询已接受轮次，不重发 create / writer key |
| `GET /native-runs/{run_id}/materials/{material_id}` | 有界读取本轮原始 bytes（base64）与固定 metadata，服务端重验 hash / size，provenance 仍 UNVERIFIED |
| `GET /native-runs/{run_id}/handoffs/{handoff_id}/state` | 按本轮 handoff ID 读取并核验原 generation 的冻结状态快照；摘要只能证明该快照完整性，不证明测试执行 |
| `POST /native-runs/{run_id}/uncertainties` | 当前 writer 登记原外部 operation 的未知意图与受控材料引用，不发外部请求 |
| `POST /native-runs/{run_id}/uncertainties/{key}/reconcile` | Operator 窄管理例外，可在 writer key 遗失时按原 key / 原 UNKNOWN 状态，提交 `resolution, observed_operation_ref, material, attestation, reason`；核验具体原操作查证材料、按 run 行锁追加 Audit，不运行测试 / CI 或重发外部 POST |

`plan.inputs.sut` 区分 credential-free `repository_url`、nullable `source_commit` 与 nullable `binary_sha256`，必须如实固定可观察身份；framework 有独立 `repository_url, commit_sha, local_changes`，`test_assets` 固定 `path, sha256`；SUT 另有 `source_association=DECLARED|UNVERIFIED|UNKNOWN`、`local_changes`，`environment` 为无秘密工具 / 依赖 / 环境观察，`environment_variable_names` 只含变量名称；`authorization_scope` 记明确范围；首版 `source_transfer=NONE`。SUT SHA 不得被 framework SHA 替代。更详细 dirty / source-build 证明不足的材料进入已知缺口，不因 schema 合法就被认作完整源码身份。

`cases` 每项为 `key, title, requirement_ref, risk_ref, expected_result, implementation_ref`。requirement / risk 是本计划固定来源引用，implementation_ref 是原生测试入口 / native case 引用，均不能冒充不存在的旧 Canonical UUID。Case 关系以 SQL FK / join 表保存；列表仅是输入 / 读投影，不是无约束的持久关系替代。

`results` 每项为 `case_key, result`，result 为 PASS / FAIL / SKIPPED / ERROR / UNKNOWN，表示提交的原生断言观察。`materials` 为有界 `name, kind, format, content_base64, sha256`；kind 为 STDOUT / STDERR / REPORT / CONTEXT，format 为 TEXT / CONSUMER_PARITY_JSONL / JUNIT_XML。平台重算内容摘要与长度，按已支持格式校验报告的 case 标识、计数、结果与 exit code。format 扩展须来自真实项目，不建通用执行适配器。首版每文件最多 2 MiB、每执行最多 8 份材料 / 总共 6 MiB；最多 200 cases / results / test_assets，environment 最多 64 项，环境变量名最多 64 项；每字符串最多 16,000 字符（各字段可更严），plan 最多 512 KiB，每轮最多 128 条执行，普通 operation 最多 512、管理 operation 保留到 1,024；state / handoff snapshot 读取最多 8 MiB。达到限额停止新写并保留原轮次，不能删历史获得额度。

`attestation` 是 Operator 对原操作回查的人工确认：`kind=ORIGINAL_OPERATION_READBACK|EXECUTION_CONTROL_READBACK`、`source_ref`、匹配原操作的 `operation_ref`、带时区 `observed_at`、匹配 resolution 的 `result`、匹配原件的 `raw_material_sha256` 与 `operator_attests_original_readback=true`。它和非空 CONTEXT/TEXT 原件一起约束管理确认；JSON 形状或一次人工声明不是独立 CI / 测试来源证明，本机材料 provenance 不变。

### 44.3 信任、结论与原键对账

接收 Plan / Cases 的 Proposal 验证、接收 material、校验报告一致性、独立确认 execution provenance 和形成质量结论分别报告。本轮来源核验固定 UNVERIFIED；NativeVerification 不把 `command`、process metadata、自报 exit、hash 或合法 XML/JSONL 当执行证明，也不生成旧 Evidence。`native-material-gate/v1alpha1` 原生结论仅 UNKNOWN / BLOCKED，观察到 PASS 也不能形成正式质量 PASS；实测断言失败 / setup ERROR 与平台采纳状态分别保留。

所有写在发送前将稳定 key / versioned input digest / intent 写私有 journal；服务端同 key 同输入复用原 operation，异输入冲突。失答只 GET 原 key，NOT_FOUND 不使写请求安全重放。一次性 writer key 丢失后只能先对账、再由 Operator 发起新的显式 handoff 管理意图；不自动重签或通过 GET 恢复秘密，原操作 / 贡献历史保留。

`NativeOperation.UNKNOWN` 阻断新执行和 handoff。reconcile 是独立 Operator 管理例外，不要求已遗失 writer key，但必须匹配原 operation key 与 UNKNOWN 状态、具体查证结果、受控原始材料及 reason；没有材料、仅摘要或 NOT_FOUND 不消除 UNKNOWN。服务端仍以 UNVERIFIED 对待本地查证材料，不因此提升测试来源；Operator 对原副作用结果承担明确确认责任。对账结果不能由换 session label / generation / key 来绕过。handoff 不重复测试，不恢复原生聊天，不复制对话，不让旧 key 在新 generation 继续写。Artifact 上传与业务记录的提交失败保留原意图和受控失败，不覆盖已经提交的事实。

本轮是 retrospective intake：原生运行先于新 API 接受计划；observed started_at/finished_at 与平台 created_at/submitted_at 分别保存，不回填时间或声称平台先前已下发执行。计划可引用执行前的原始测试设计。

后续独立可信 CI 接入必须按 ADR-017 §8 校验批准项目、pipeline/job/attempt、实际 source/test/env、原始报告、独立采集身份及对应关系，并发布新 profile / Gate 验收；当前 API 并未实现此来源提升或 native PASS。

## 45. Codex 会话任务管理同步（ADR-018，当前阶段）

[ADR-026 多会话协作](../architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)通过 §45.5 的版本化协作 profile 分离成员贡献与主会话汇总；以下 full sync 和初始 BIND 合同继续用于未启用协作的任务，不把旧接口放宽为多写者。

§45 是管理数据同步，不是执行申请或新的 Runner profile。一个 `(provider, session_id)` 对应一个 SessionTask；Project、actor 与客户端授权来自有效 integration grant，session reference 仅为提交来源元数据。MCP/API 不启动或接管 Codex，不需要 execution binding、device token、host proof、源码传输、SourceSnapshot、Policy、Job、Runner 或 Gate。

### 45.1 请求与读取

| MCP / typed HTTPS | 契约 |
| --- | --- |
| `hypertest_sync_task` / `POST /interactive/tasks/sync` | `project_id, task_id?, idempotency_key, expected_version, provider, session_id, title, objective, status, plan_markdown, reported_result, cases, reports`；权限 `task:sync`；§45.4手动绑定任务强制task_id，缺省仅保留legacy自动路径 |
| `hypertest_get_task` / `GET /interactive/tasks/by-session` | `project_id, provider, session_id, version?, offset?, limit?`；分页读取固定版本当前任务/用例/原报告，权限 `task:sync` |
| `hypertest_get_task` / `GET /interactive/tasks/syncs/by-key` | `project_id, idempotency_key`；只查询原同步回执，权限 `task:sync` |

get工具原两组参数与§45.4新增task_id选择器互斥，未知字段拒绝。所有字段按服务端 typed schema 校验；schema 标识不引入新的执行生命周期。Case 是 `{key,title,steps:list[str],expected,actual,reported_result,implementation_ref?}`；Report 是 `{key,title,markdown,artifact_uri?,source_ref?,reported_result}`。`artifact_uri` 与 `source_ref` 是引用元数据，平台不得执行命令或自动访问任意本机路径/URL。`markdown` 原文由平台存储并可读回。

状态为 `DRAFT | IN_PROGRESS | BLOCKED | COMPLETED | CANCELLED`，表示任务进度。任务/用例/报告的 `reported_result` 为 `NOT_RUN | PASS | FAIL | ERROR | SKIPPED | UNKNOWN | BLOCKED`，表示提交者报告的结果。平台校验管理一致性后保存，不要求独立 CI 才能记录 PASS，也不把来源不足统一转换为 UNKNOWN；旧 Evidence/FINAL/RELEASE_READY 权限不随此扩展。

业务 key 为 `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`。provider 为小写字母起始、后续小写字母/数字/下划线/连字符，最多64字符；session reference 最多512字符。任务与报告标题最多512字符；objective/expected/actual/单step最多16,000字符；计划与原始报告各最多262,144字符；每同步最多200用例、每用例100 steps、16报告，typed payload最多2MiB。现有本机 MCP 通道还按完整JSON消息实施1,000,000字节上限；超出须缩减为获准的本次资产范围，不丢原件、不静默截断或增加隐式上传。

成功同步与原key查询只返回瘦回执 `status=ACCEPTED, profile, task_id, project_id, provider, session_id, version, idempotency_key, source=AGENT_REPORTED`，不夹带snapshot或历史原文。客户端核对原key、Project/provider/session、task UUID、expected version+1与契约标识，已接受回执的后续查询继续固定原task ID；不匹配时保留UNKNOWN并只查询，不误ACK。

MCP按会话读取返回有界 envelope `{task_id,version,format:'application/json',offset,total_chars,next_offset,content,complete,source}`，实际同步版本source为AGENT_REPORTED；§45.4未同步的预建/仅绑定版本source可NULL。content是固定版本current-only `{task,cases,reports}` JSON原文分片；不重复附带全history。offset/limit按Unicode字符计算，limit默认/最大24,000；首片offset=0可省version取得当前版，续片offset>0必须携首片version。每片核对固定task/version/total和next_offset连续性，拼接后JSON解析并核对Project/provider/session及原文；不截断报告、不把通道1MiB上限无限调大。原版本由冻结同步、管理、绑定快照及对应修订重建；省略history不删除它们。

管理 Web 查询用 `/tasks?project_id=…`、`/tasks/{id}`、`/tasks/{id}?version=N` 与 `/tasks/{id}/reports/{report_id}`，其详情可提供历史投影；沿用平台读取边界，不使客户端获得Operator权限。

### 45.2 接受、身份与原 key 对账

权限、schema、唯一性、owner、expected version、稳定 key 和引用一致性构成管理 Proposal/Verifier 接受边界。legacy自动首次同步用expected_version=0；§45.4预建任务首个实际sync使用绑定后的当前version。后续必须与当前任务版本匹配。一个同步原子保存任务更新、case/report新修订、冻结回执及 Audit/Outbox；失败不留下已接受的部分任务。用例/报告 key 稳定，同内容不伪造新修订，变更追加历史；省略不代表删除。

首次固定 Project 和 actor owner，同项目的其他 actor 不得凭知道 session ID 覆盖任务；新 client 仍需同 actor 的有效项目授权。认证 scope 由现有 integration actor/client/project链核验，`task:sync` 不授予 `run:execute` 或设备控制。管理型 Operator 操作保留其独立权限；token只在本机私有文件/daemon保管，不进入模型工具参数。

同 key 同输入返回原回执，同 key 异输入冲突。发送前保存 journal intent；发送后失答/响应不可确认时保持同步 UNKNOWN，只 GET 原 key。404/NOT_FOUND 不证明原 POST 未执行；客户端不得自动 POST 重发、换key、重建任务或重新发放凭据。旧 expected version 不能覆盖当前状态，失答查询结果不改变报告原 reported result。测试事实、推断与待验证材料在来源和原始报告中分别说明，摘要/hash不产生执行证明。

### 45.3 Operator 项目与任务管理 API（2026-10-23）

以下入口沿用管理 Web / Operator 的独立访问边界，不扩充 `task:sync` scope，也不新增 MCP工具或执行权限。路径均以 `/api/v1` 为前缀。

| HTTP入口 | 请求与行为 |
| --- | --- |
| `POST /projects` | 新建 Project 必须提供非空 `repository_url`（SUT）和 `test_framework_repository_url`（测试框架）；可相同，均执行无凭据 origin 校验并拒绝 query、fragment、ASCII 空格和控制字符。已有项目读取允许旧字段为空；UI 不要求指定 `default_branch` |
| `PATCH /projects/{id}` | `{expected_version, name?, description?, repository_url?, test_framework_repository_url?, default_branch?, status?}`；前两项仓库地址分别为 SUT 和测试框架；`expected_version`匹配项目row_version，状态仅ACTIVE/ARCHIVED；id/key固定 |
| `DELETE /projects/{id}?expected_version=N` | 软删除项目；存在未删除SessionTask或任何legacy/native测试轮次时409，不级联删除 |
| `POST /projects/{id}/restore` | `{expected_version}`；清除软删除标记并保留原状态 |
| `GET /projects?include_deleted=true` | 显式读取包含已删除项目的回收站列表，返回row_version与deleted_at |
| `PATCH /tasks/{id}` | `{expected_version, title?, objective?, plan_markdown?, status?}`；匹配任务version，状态为§45.1五值，允许人工重开；不得写reported_result、cases/reports、身份或归属 |
| `DELETE /tasks/{id}?expected_version=N` | 软删除任务，保留session唯一性、同步回执和全部历史 |
| `POST /tasks/{id}/restore` | `{expected_version}`；项目未删除时恢复原任务 |
| `GET /tasks?project_id=…&include_deleted=true` | 显式读取包含已删除任务的回收站列表，返回version与deleted_at |
| `GET /projects/{id}?include_deleted=true`、`GET /tasks/{id}?include_deleted=true` | 管理回收站详情，显式读取已删除对象；任务仍可用version选择固定历史 |

写入校验字段白名单及当前版本；版本过期或删除/恢复前置条件冲突返回409，未知/非法字段返回422，不存在或已从普通入口隐藏的对象返回404。任务管理写返回任务详情，包含独立 `management_history`，每条有id/task_version/action/actor_ref/created_at；原UPDATE/DELETE/RESTORE及§45.4 CREATE/AUTHORIZE分别保存。项目写返回项目投影。人工变更原子递增对应版本并写Audit/Outbox；同值任务PATCH在版本匹配时为no-op，不制造版本或历史。任务另存冻结TaskManagementRevision，原SyncReceipt与case/report不变。任务任一固定版本可由同步、人工或绑定快照读取，不将新进度套用到旧报告。

默认列表、详情与by-session不返回已删除任务或已删除项目下的任务；Agent新同步拒绝已删除对象。原 `syncs/by-key` 在当前有效授权下仍可返回历史瘦回执，便于对账，不因软删除改写原version或自动恢复对象。`source=AGENT_REPORTED` 继续标识产物及reported result来源，人工字段变更另由management_history溯源。人工进度调整、软删除或恢复均无执行、取消执行、测试重跑或质量裁决语义。

项目软删除同时约束旧入口的新资源准入：任务/源码创建、上传授权和接受、集成授权及Connector新采集的入队/投递检查项目仍未删除，保留只读历史与原key回执。该检查不改写原transfer或外部操作的状态，不将删除伪装为已确认取消。

### 45.4 统一创建与Local显式绑定（ADR-024）

统一创建UI选择Cloud/Local但调用独立领域API；task_kind不可转型。下表Local路径以`/api/v1`为前缀，Operator key不进入MCP或Agent，integration调用仍使用当前task:sync grant。

| 接口/工具 | 请求与接受行为 |
| --- | --- |
| `GET /projects/{id}/local-task-actors` | Operator读取`{items:[{actor_ref,label}],total}`，仅当前有效Project task:sync actor去重列表，不含token |
| `POST /projects/{id}/local-tasks` | Operator提交`{idempotency_key,title,objective?,plan_markdown?,intended_actor_ref?}`；返回固定接受version的SessionTaskDetail（`.task.id`为稳定ID）及creation_receipt；v1/UNBOUND/DRAFT/NOT_RUN |
| `GET /projects/{id}/local-tasks/by-key?idempotency_key=…` | Operator仅查原CREATE key，返回原接受版本detail+creation_receipt，不跟随当前head；软删后仍可对账，不授权replay |
| `PATCH /tasks/{id}/binding-authorization` | Operator提交`{expected_version,intended_actor_ref:string|null}`，仅UNBOUND；返回detail，变更保存AUTHORIZE，同值no-op |
| `hypertest_bind_task` / `POST /interactive/tasks/bind` | `{project_id,task_id,provider,session_id,expected_version,idempotency_key}`，实际来源必须匹配私有native root；当前grant actor必须精确等于intended_actor_ref |
| `hypertest_get_task_binding` / `GET /interactive/tasks/bindings/by-key` | `{project_id,idempotency_key}`原BIND key只读对账，查询原绑定回执，不查询SyncReceipt、不改目标或重发 |
| `hypertest_get_task`的task_id选择器 / `GET /interactive/tasks/{task_id}` | `project_id,task_id,version?,offset?,limit?`；有界固定版本读取，仅UNBOUND intended actor或BOUND owner，source在首次实际sync前可NULL |

创建时省略intended_actor_ref仅sole可用actor允许默认；显式NULL保持未授权，多/无候选不隐式认领。未授权UNBOUND不能BIND；Operator在UNBOUND同version设置/清除授权。creator_actor_ref、Task ID及root metadata都不是能力密钥，不以知道ID替代有效授权。

MCP工具arguments及服务端TaskBind字段不增加caller自报项。Codex CLI 0.144.6由实际MCP request context的`_meta.threadId`生成私有IPC `native_caller_context={provider:'codex',session_id:threadId,transport:'codex-mcp-thread-id/v1'}`，daemon转交协调器核对已存在SessionStart root和拟写来源；不能从arguments选取、覆盖或把child归一成parent。该字段不上传平台，不进入冻结业务请求/幂等摘要。新BIND和手动已绑定Task的显式MCP新sync缺context返回`NATIVE_CALLER_CONTEXT_REQUIRED`，错配返回`NATIVE_CALLER_CONTEXT_MISMATCH`；无已实现宿主适配返回`NATIVE_CALLER_CONTEXT_UNSUPPORTED`，均不得POST或建立新target/intent/snapshot。当前Claude/DeepSeek及无原生metadata的CLI绑定属于未支持路径；授权GET、已确认legacy auto resume及未决原key只读对账保留。此合同仅提供正常宿主调用归因，不是服务端独立原生身份证明。

BIND与CREATE/管理/sync共用version；一次事务填真实provider/session/owner、BOUND及bound_at，追加独立BIND回执/snapshot/Audit/Outbox，不产生SyncReceipt，不推进source/last_synced_at，不改status/result/用例/报告。Web `binding_history` 投影`{id,action:'BIND',actor_ref,task_version,task_snapshot,created_at}`，区别于人工管理与Agent同步历史。已绑定（包括软删除后）不可改绑，原来源唯一性不释放。

CREATE的`creation_receipt`为`{status:'ACCEPTED',operation:'CREATE',project_id,task_id,version,idempotency_key}`。BIND回执为`{status:'ACCEPTED',operation:'BIND',profile:'codex-session-task-sync/v1alpha1',project_id,task_id,provider,session_id,actor_ref,binding_state:'BOUND',source:null,version,idempotency_key}`；version为本次expected_version+1。客户端校验原key、操作、来源与目标身份及接受版本，完整读回固定接受版本后才确认绑定；当前head变化不改写回执。

同key同输入返回原接受身份/版本，同key异输入拒绝；CREATE/BIND失答、SENT/UNKNOWN或GET原key NOT_FOUND只继续对应key GET，不自动重POST、换key或另建Task。幂等匹配在当前版本检查之前，回执读取仍要求当前有效授权。两种操作不能混用key查询。普通404不证明之前写入未接受。

Web 的 Local CREATE 在发送前将完整原请求、原 key 与 expected_version=0 写入浏览器持久账本；与 Cloud 使用独立记录及原 key 查询路径。多标签页通过 IndexedDB readwrite 事务占据同 Project 的 Local 创建流，不能以无锁 localStorage 或单页内存互锁替代。已有未决记录、旧 sessionStorage 迁移冲突或存储失败时禁止新 CREATE POST；迁移不得覆盖未决原件。有效 creation_receipt 后还须完整 GET 同 Task 的固定接受版本并核对身份及请求内容，才完成本次 CREATE。关闭普通标签页后可恢复；用户清除站点数据、浏览器驱逐或私密模式结束不承诺持久保留。

新Local客户端在首次asset上传前未绑定返回TASK_BINDING_REQUIRED，零sync POST；Hooks/MCP共用同一真实root、目标ID、协调器及未决账本。旧已确认auto根保留原ID兼容resume；服务端旧无task_id自动创建仅为legacy兼容，不作为新客户端fallback。新手动绑定任务的每次sync强校验task_id、Project/provider/session/owner/BOUND及当前version；不匹配不得另建任务。来源已属于另一Task时409，错误code为SESSION_ALREADY_HAS_TASK，仅对有权读取者给existing_task_id，不自动合并或改ID/历史。

### 45.5 Local 多会话协作 profile（ADR-026）

profile 为 `local-task-collaboration/v1alpha1`。所有操作仍为管理接受，不执行 Agent、模型、SUT、Runner 或 Cloud Worker；沿用当前可信 Operator 管理边界及 integration actor/client/Project `task:sync` 授权，不新增跨模式 token 或 scope。

| 路径（`/api/v1` 前缀） | 合同 |
| --- | --- |
| `GET /tasks/{task_id}/collaboration?version?` | Operator 读取完整协作文档，含固定 task、collaboration 与 operation_history |
| `POST /tasks/{task_id}/collaboration` | Operator 提交 ENABLE/AUTHORIZE/REVOKE/HANDOFF；共同字段 profile、operation、expected_version、idempotency_key |
| `GET /tasks/{task_id}/collaboration/receipts/by-key?idempotency_key` | 原 Operator key 只读回执，不发新操作 |
| `GET /interactive/tasks/{task_id}/collaboration` | integration 按 project_id/provider/session_id 读取；支持 version、offset、limit，分片固定版本且每片最多24,000字符 |
| `POST /interactive/tasks/{task_id}/collaboration` | 共同字段 profile、project_id、真实 provider/session_id、operation、expected_version、idempotency_key；操作 JOIN/CONTRIBUTE/PUBLISH |
| `GET /interactive/tasks/{task_id}/collaboration/receipts/by-key` | project_id/provider/session_id/idempotency_key 定位原成员回执，仍核当前授权及原来源 |

ENABLE 没有额外业务字段，初始真实绑定成为首个 PRIMARY。AUTHORIZE 要求精确 actor_ref/provider/session_id 和可选 assignment，仅允许既有 owner actor；REVOKE 要求 participant_id。HANDOFF 要求 participant_id、expected_primary_generation 与 handoff `{materials,unresolved_items,private_journals_observed:false}`，清单不声明已读到失联会话私有 journal。

JOIN 没有额外业务字段。CONTRIBUTE 携 `contributions:[{kind,stable_key,expected_revision,content}]`，kind 为 PLAN/CASE/REPORT/REVIEW；CASE/REPORT content 使用原 TaskCase/TaskReport 的内容字段，key 由 stable_key 单独提供。单项内容最多512KiB，最多200项，完整成员请求最多2MiB。同成员同 kind/key 不重复，追加新 revision，不更新整体任务字段。

PUBLISH 携当前 `primary_generation` 和完整 `summary`：title/objective/status/plan_markdown/reported_result、`contribution_refs:[{contribution_id,revision,disposition,shared_key?}]`、completion_basis、unresolved_items。disposition 为 ADOPTED/MERGED/DIVERGENCE/DEFERRED，引用须为同任务的准确接受修订，不能以最新内容替换冻结引用；首片只保存显式发布映射，不将其伪装为已产生旧 CaseRevision/ReportRevision。COMPLETED 必须有非空完成依据。

公共回执为 `{status:'ACCEPTED',profile,operation,task_id,project_id,actor_ref,provider,session_id,participant_id,version,idempotency_key,request_digest,primary_generation,contribution_refs}`，Operator 回执的 source/participant 字段为空；新接受 version=expected_version+1。CONTRIBUTE 回执引用本次新增贡献 ID/revision。完整文档包含 `task`、`collaboration:{enabled,primary_participant_id,primary_generation,participants,contributions,publications}` 和不可变 operation_history；成员分页 envelope 与 §45.1 相同，续片须固定 version。

精确 AUTHORIZED/ACTIVE 来源在当前 grant 下允许只读，JOIN前可据此选择明确基线；ACTIVE 才能贡献，当前 PRIMARY/generation 才能汇总。新 MCP 写仍要求受支持真实 root 与逐调用 caller fence，工具参数不能覆盖宿主来源；child、错配和未支持宿主零新 POST。授权 GET、原 key 恢复不需要伪造 caller 或重新写入目标。

键唯一性属于独立 collaboration receipt 命名空间中的 actor/Project/key，完整摘要包含操作、来源、任务和版本；同 key 换操作/来源/输入冲突。原 key 查重先版本与新角色检查，回执读取仍按当前授权和原提交者来源。SENT/UNKNOWN/失答/原 key NOT_FOUND 只查询原 key；冻结请求不可重基、换 generation 或换会话重发。ACK 后完整读取固定接受版本，核请求摘要、来源、贡献引用和原文，才确认本次交付。

旧单会话任务保留原 wire。协作启用后旧 full sync 新写返回 `COLLABORATION_PROFILE_REQUIRED`，不因已知 Task ID 回退自动创建；已接受旧 key 仍返回原结果，旧历史保留。新 profile 不能把全部贡献标成初始 session，原初始 BIND 来源不被主会话交接替换。客户端/公开包/宿主资格分别记录，API 能力目录存在不代表旧安装已支持新工具。

## 46. 云端测试任务 profile（ADR-019，部分实现、代码默认关闭）

Cloud 本轮仅接入官方 Python SDK 驱动的 DeepSeek Harness + Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 任务已固定完整读回 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 只读验收器对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT 为 strict PASS，独立只读重放 19 项通过并核对接受原件。该重评没有新的 current GET、模型、SSH 或 SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 和其他失败原件保持。C4已按固定Git部署到单人专用测试服务器，schema26、Cloud Worker以Codex=true / SSH=false空闲运行；构建、组件回归、doctor、迁移和基础健康只记部署检查。代码开关默认仍关闭，用户验收为PENDING / USER_OWNED，未经用户明确要求不擅自开展；Web Cloud详情步骤显示修正已按6d49单独部署，API / Worker / schema保持C4身份。精确Git / image / 轮次见[交付记录](../CLOUD_GIT_DELIVERY_20261023.md)，不以当前部署覆盖旧fixture身份。

### 能力响应：实现支持、配置与准入分别读取

`GET /cloud/capabilities` 返回静态实现能力，不读取秘密或文件、不 import SDK，也不探测当前凭据、进程或模型。

- `support_semantics="IMPLEMENTATION_NOT_ADMISSION"`：`supported.codex_delegation=true` 表示本候选具有 Codex 实现，不表示当前 Attempt 可执行；`claude_code_delegation=false` 保持占位。
- `supported.ssh=false` / `remote_ci=false` 表示一般 SSH / CI 不支持；固定诊断单列为 `ssh_fixed_diagnostics=true`、`ssh_profile="SSH_FIXED_DIAGNOSTICS_V1"`。`environment_connections=["NONE"]` 保持现有连接语义，不能据此否定或扩大这个独立受控 profile。
- `configuration` 分别给出 `cloud_enabled`、`worker_enabled`、`codex_enabled`、`ssh_fixed_diagnostics_enabled`；这些是当前开关值，不是认证、payload、网络、预算或隔离预检成功。
- `admission={"state":"NOT_CHECKED","scope":"PER_ATTEMPT","checked_by":"WORKER"}` 明确本 GET 未做准入。原 `profile` / `enabled` / `worker_enabled` / `sdk_package_version` / `not_proven` 保留；模型身份、执行和委派仍由 Worker 在具体 Attempt 领取前检查并单独留证。


### 46.1 版本、模式与六步职责

新增业务 profile 为 **`cloud-harness-task/v1alpha1`**。它定义 HyperTest 的完整云端任务协作契约，不是 DeepSeek SDK wire version，也不是 §45 同步请求的可选执行开关。当前typed HTTP / schema / Worker / Web已随C4 Git部署；代码默认关闭，测试服务器显式启用Cloud / Codex并保持SSH关闭，用户验收未执行。实现准入支持HTTPS Git / 工作区内框架及显式opt-in固定SSH诊断，既有SSH证明限隔离fixture，不授一般网络 / 远端SUT执行。source-r18受控六步Task已正式接受v14 COMPLETED / reported PASS、根工作和Codex原生推理 / 文本贡献；source-r21所选535通过 / 1跳过、source-r22针对性169通过；source-r22新native16任务已固定读回v17 COMPLETED / reported PASS、接受子原件 / 资产 / Run并独立重放9项；DESIGN仅通过ANALYSIS传递关联原件，未完全满足本次PRD直接引用要求，偏差与旧RECOVERY / HELD保留；后续r8固定SSH专项PASS，source31对同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与staging待验收；Claude占位、CI不支持，参见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。以下操作概念不等同 SDK method 或新增 MCP 工具；字段/关系/状态的最终约束以领域 §51 为准。

| 用户流程 | HyperTest / 云端 Worker | Harness / 项目工具链 |
| --- | --- | --- |
| 1. 创建项目 | 在云端创建或复用共享 Project，登记 SUT/framework Git、连接方式及项目凭据；可选保存默认配置 | 不启动 Agent，不隐式导入本机登录 |
| 2. 创建任务 | 在云端创建 DRAFT CloudTask，输入含版本选择器、PRD、测试目标、流程、环境/授权/预算 | 不执行测试 |
| 3. 下发任务 | 输入预检 Worker 解析双 SHA，dispatch 冻结解析快照并原子入队独立 Attempt | 仅排队不构成已接取/测试通过 |
| 4. Harness 接取 | Worker 通过官方 Python SDK 启动独立 runtime、提交冻结任务、收集受控进度 | DeepSeek 自行参与或委派 Codex/Claude，维护分工清单 |
| 5. 输出产物 | 按阶段校验并持久接受 analysis/design/cases/implementation 修订与原件 | 生成分析、设计、用例和测试代码 |
| 6. 执行并汇报 | 保存每次框架执行、原报告/日志、case actual 与最终汇报，核对收尾 | 调用项目已有框架/CI，诊断并迭代；第 5/6 步可循环 |

CloudTask / CloudAttempt 是新独立身份。DeepSeek 主任务是唯一汇总者，Worker 是唯一管理提交边界；子代理只提交给主任务，不各自创建 Task、使用 Operator key 或持有管理 writer 能力。Task/Attempt ID 不伪装成 Codex session_id，也不填入 legacy TestRun/Job 的 FK。§45 的 legacy MCP/API、`task:sync`、幂等、版本、UNKNOWN 和 reported_result 保留原义；ADR-024 的预创建、一次性绑定与明确 Task ID 选择按 §45.4 叠加，不由 Cloud 流程绕过。

最新严格验收状态：source-r23新独立Task已固定读回v20 COMPLETED / reported PASS，ANALYSIS与DESIGN均直接引用当前child原件；source-r24只读验收器对同v20严格PASS，独立只读重放8项与原件 / 实际文件 / host日志关联通过。旧source-r22 v17仍保留DESIGN直接引用NON_PASS，原RECOVERY / HELD历史不变；SSH固定诊断默认关闭，source30 Worker的r8 canonical专项PASS，source31对同v19固定快照strict重评PASS；旧source30 NON_PASS保留（不是新的current GET，精确证据见实现状态），故障矩阵与真实staging未验收；Claude占位，CI / 一般远端shell和生产未准入。source-r23所选201 / source-r24所选231通过与各自Ruff独立登记，未覆盖其余P0；[当前证据](../CLOUD_IMPLEMENTATION_STATUS.md)。

### 46.2 SDK 与平台运行边界

HyperTest Python Worker → 官方 `deepseek-harness-sdk` → 配套 `dsh --profile sdk` 子进程 → DeepSeek harness；Codex/Claude 是该 Harness 委派的外部工具能力。平台保留自己的领域操作与资产模型，SDK 类型和事件只在 adapter 内映射。SDK 仍通过 NDJSON/JSON-RPC 进程通信，不宣称能缩短模型或框架执行耗时。SDK/runtime 配对版本与能力探针在接入阶段固定并随 Attempt 保存，不能假设 master 文档与已部署二进制总是相同。

按本设计核对时的[官方 Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)与[SDK 协议](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)，首版不能依赖单 session cancel/close 或运行中动态权限审批。每 Attempt 使用独立 runtime/workspace/dsh_home，取消/超时由 Worker fence 写权并终止整个本地进程树。远程 CI/SSH/业务动作可能继续，必须记录原操作身份并对账；关闭进程不构成外部副作用已停止的证明。

使用预授权 profile 加可执行的 Worker/隔离环境限制；Git helper、SSH agent 或专门目标代理按 Project/目标/用途物化凭据，密钥不进 Prompt、任务 JSON、普通 journal 或日志。模型服务身份由云端预配，不复制个人 HOME。子代理取得允许操作的能力，不自动继承完整父进程密钥环境。权限不足在动作发生前拒绝并创建 WAITING_INPUT；无法强制约束的任意 shell 不能通过准入。

SDK [`session/wait` 完成语义](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/client/README.md#L54)不能代替平台收尾：root idle 及 SDK 管理的后代等待，与外部 Codex/Claude CLI 的进程/产物状态不是同一事实。输入停放的后代可能不阻塞 idle，`subagent.finished` 只覆盖对应 in-process 活动。Worker 必须核对显式委派清单、可观察终态与实际产物；idle、turn 结束或最终文本不能直接标记 Task COMPLETED。

当前固定 SDK / runtime 为 `0.2.1rc2`，wire 为 `0.0.1`。固定官方 DeepSeek provider 使用 Anthropic Messages（`/v1/messages`、`x-api-key`），由宿主 broker 限定固定模型、文本 / thinking 与客户端执行工具；不回退 Chat Completions，不接收图片 / 文件 URL、provider-hosted 工具或未知扩权字段。Codex opt-in 使用官方 `dsh-subagent-codex@0.2.1-rc.2` + `@openai/codex@0.153.4`，其宿主 OAuth relay 仅允许固定 Responses 推理；真实身份留在 namespace 外，内部只有 socket 与 sentinel。两种协议和各自认证不能混为一个模型 API。

Codex 官方生命周期观察通过专属有界 UDS 发送序号化 READY / DELEGATION / CLOSED 并等待 ACK；仅使用已固定版本公开 plugin lifecycle，不扩 SDK wire、不扫描 transcript。READY 只证明 provider / tool / shim 已加载。委派 handoff 必须引用官方工具回执的 child UUID（不是产品 thread ID），由 Worker 用 start / terminal 观察注入状态；所有 child 终态、父任务各委派贡献回执、观察通道关闭、整 namespace 停止及 broker drained 共同核对后才能收尾。该来源标为 runtime-reported；2026-10-22的r10无模型探针仅观察四组件就绪 / 干净关闭，无OAuth请求或child，不能据该探针推定委派。后续source-r18已完整读回v14 COMPLETED / reported PASS、根工作及Codex原生推理 / 文本贡献，正式child身份与接受资产引用也已核验；该Task子文件 / 命令工具保留SIGTRAP历史；后续source-r21的native16任务因Artifact引用误用遭拒，RECOVERY / HELD历史保留；source-r22新任务已接受v17 COMPLETED / reported PASS、子原件 / 资产 / Run及独立重放9项，来源仍runtime-reported。DESIGN经ANALYSIS传递关联子原件有效，但未字面满足本次PRD两者均直接ref的要求，不称strict PRD全部PASS或独立writer证明。source-r21所选535通过 / 1跳过、source-r22针对性169通过与实际Task分别登记，精确结果见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。Claude保留placeholder；后续r8固定SSH专项PASS，source31对同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与真实staging未验收，CI不支持，默认关闭、本会话未部署生产。

### 46.3 Typed operations 与权限

以下是领域操作，不等同 SDK 方法名或 MCP 工具；当前 typed HTTP 入口见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md#服务端-api-与权限)。所有普通写操作带 `profile, project_id, operation_key, expected_version`；Task 创建为 expected_version=0，资源配置/凭据用各自聚合版本。输入严格校验未知字段、长度/字节上限、引用归属和当前权限；明确错误，不静默截断。各通道的实际限额由实现 schema 发布，不扩大 §45 现有限额。

| 操作概念 | 输入/结果及授权 |
| --- | --- |
| ConfigureCloudProject | 仓库角色/地址、可选历史兼容默认 ref、环境连接 metadata、credential ref/version；追加配置修订，`cloud:configure` |
| Store/RotateProjectCredential | 专门秘密入口接收 token/私钥与类型、目标/用途、有效期；加密持久化，返回非秘密 ref/version；`credential:manage`。原文不进入普通操作回执/读取接口 |
| Create/UpdateCloudTask | `title, selectors, config_revision, prd, objective, basic_flow, framework_entrypoints, environment_ref, authorization_manifest, budgets`；DRAFT 可改，`cloud:dispatch` |
| ResolveCloudInputs | `task_id, expected_version`；受限 Worker 预检固定输入，不启动 Harness/测试；接受不可变 `resolution_id`、完整双 SHA/MR 身份、资源版本与来源；`cloud:dispatch` 请求，限定 INPUT_RESOLUTION 的 `cloud:work` 执行 |
| DispatchCloudTask | `task_id, resolution_id`（首次）或 `task_id, retry_of_attempt_id, reason`（同冻结输入显式复测）；返回冻结 input digest、task version、QUEUED Attempt 与原 key 回执；`cloud:dispatch` |
| GetCloudTask / GetCloudOperation | 固定 task/version 的任务/Attempt/资产分页，或 project/原 operation_key 的回执查询；`cloud:read`，回执查询另核验原提交者/授权委派关系 |
| AnswerCloudInput / ResumeCloudAttempt | `task_id, attempt_id, question_key, answer` 或 `checkpoint_ref, reason`；回答与恢复分开审计，当前权限和冻结上限重新核验；`cloud:control` |
| CancelCloudTask | `task_id, reason`；仅允许 DRAFT 且无 Attempt，核验 expected task version 后原子置 CANCELLED、递增版本并保存原 key 回执及 Audit/Outbox；`cloud:control`。不启动/取消 SDK 或产生执行副作用；该 Task 保持终态，重新开始须新建关联 DRAFT |
| CancelCloudAttempt / ReconcileCloudOperation | 取消原因；或原 key、原操作/目标、观察时间、原始材料与明确 resolution；`cloud:control`，UNKNOWN 对账不得执行原动作 |
| SubmitCloudAssets / SubmitCloudRun | 指定 Task/Attempt、当前 lease/generation、修订或新 run key、来源/确切版本、已持久原件；Assets 可带 `checkpoint_report_key?` 将本批一个 REPORT 的接受修订原子绑定到 Attempt 既有 checkpoint（§46.5）；限定本 Attempt 的短期 `cloud:work` |
| CompleteCloudAttempt | `task_id, attempt_id, final_report_revision, delegation_terminal_refs, reported_result, completion_manifest`；平台核对所有收尾条件后原子结束，`cloud:work`；恢复对账后的人工收尾用 `cloud:control` 并留原因 |
| ReadCloudArtifact | Project/Task/Artifact 身份、固定对象版本和受控 offset/length；重新鉴权的 `cloud:read`，不提供任意 URL/本机路径读取 |

新增云端专用权限须沿用项目身份/授权链并独立授予；`task:sync` 不蕴含 `cloud:*` 或 `credential:manage`。`cloud:work` 为短期能力，绑定 Task、用途及适用的 Attempt/lease generation；INPUT_RESOLUTION 能力不能启动 Harness 或测试。引用 ID、可见 generation、Provider session label 不构成密钥。撤权、过期或越项目时拒绝新操作与凭据物化，不因旧 manifest 已冻结而继续使用。

### 46.4 下发输入与冻结快照

DRAFT 请求中，SUT selector 支持 branch、关联 feat、MR 或完整 SHA；framework 有独立 ref，允许同仓。feat 是变更标签，需要关联可解析 Git selector。PRD 必须冻结正文或附件版本；来源 URL 仅作出处。环境连接描述与 SSH/应用私钥 ref 分开，应用签名密钥不能拿来 SSH 登录。

Cloud 新资源配置可省略两仓 `default_selector`，缺省不序列化该字段；历史配置及其请求摘要原样保留。新 Task 输入须显式提供 `sut_selector` 和 `framework_selector`；历史配置的 selector 可供兼容预填，但资源设置不再要求先选择分支。Project 通用仓库地址只用于用户可见的配置预填，不自动写 Cloud 资源修订或隐含授权。

Environment的可选`cloud_access_policy=LOCAL_ONLY|WEB_ONLY|None`随配置冻结，None序列化省略保旧digest；LOCAL_ONLY在Cloud创建 / 更新 / 解析 / 下发 / 领取 / 物化及prompt前拒绝，WEB_ONLY只允许HTTPS且不授网或启用当前未实现的HTTPSruntime。它不新增scope / Project排他mode或Task转换；仅收紧用户已经批准的资源访问。

ResolveCloudInputs 在聚合锁外通过受限 Worker 进行 Git/必要环境预检，记录 draft version、config/credential version、选择器、观察与完整解析结果；结果接受前重新核对当前权限与原 draft 版本。同一事务接受 resolution 并递增 task version，结果保存 source_draft_version 与 accepted_task_version。DRAFT 后续变更使原解析结果不能用于首次 dispatch。预检、暂存原件或成功 clone 不等于任务已下发。

DispatchCloudTask 必须匹配 resolution 的 accepted_task_version、当前 expected_version 和未变的输入/资源摘要，只引用已接受解析快照；API 不运行 Git。事务内固定 manifest 与首个 Attempt 并写原 key 回执、Audit/Outbox，之后 PREPARING 仅获取/核验固定版本，不再次解析移动分支。

冻结 manifest 至少包含：

```text
profile / project_id / cloud_task_id / input_digest
SUT: repository, selector, full_commit_sha, config_revision
MR (if selected): source_ref, base_sha, head_sha,
                  checkout_strategy=HEAD|MERGE, actual_checkout_sha
framework: repository, selector, full_commit_sha, entrypoints, config_revision
PRD: exact content/artifact revision, source_ref, digest
objective / basic_flow / test_scope / expected_outputs
environment: connection_revision, expected_deployment,
             observed_deployment|UNKNOWN, observed_at, observation_source
authorization: credential_ref/version, targets, permitted actions,
               side-effect limits, network boundaries, expiry
budgets: task total time/cost, attempt/concurrency limits
SDK/runtime: required capability profile (actual paired versions recorded in Attempt)
```

MR 的 actual checkout SHA 指明测试 head 还是实际 merge commit；不存在的 merge SHA 不可推断。同仓仍固定两个角色的确切版本。部署观察与 Git SHA 分开，framework HEAD 不得冒充 SUT build。若连通但部署身份未知则保存 UNKNOWN；任务要求匹配指定部署时，未确认前不能声称已测目标版本。

首次接受后不修改冻结输入。项目默认配置/分支移动不能改变现有 Task；更改 PRD、目标、环境、授权或预算上限要建显式关联的新 CloudTask。显式复测引用同一冻结 manifest 和先前 Attempt，重新鉴权且不得重置 Task 累计预算；不以自动重试处理提交失答。

预算遵循领域 §51.3：输入冻结 `accounting_unit=CONSERVATIVE_MICROUNITS|REQUEST_CREDITS`，缺省不改变既有任务解释。claim 在 Git 前持久时间 hold；RUNNING 的 Worker TRANSITION 必须含严格 `budget_reservation={accounting_unit,reserved_seconds,request_limits:[{scope,max_requests,cost_per_request_microunits}]}`，预留覆盖准备与执行的完整截止和所有模型 scope 共用的最坏额度。host-only `budget_settlement={accounting_unit,observed_seconds,namespace_stopped:true,brokers_drained:true,requests:[{scope,requests}]}` 仅在完整停止 / drain 后附于终态或其他允许的非 RUNNING transition；计数、unit 与 observed usage 必须匹配原 hold。没有有效结算保持 HELD，取消 / 失联 / 人工对账不返还未知额度。REQUEST_CREDITS 沿用 cost 字段名但不表示 USD / 供应商计费；Codex OAuth 首片要求显式 opt-in 该单位。Agent handoff 不含这些 Worker 字段，也不能通过 runtime_metadata 覆盖预算记录。

### 46.5 阶段资产、原件与框架执行

SubmitCloudAssets 提交稳定 `kind/key` 与完整内容/原件引用，平台追加 revision，来源关联具体 Attempt 与接受版本。分析/设计可为原文，case 至少含 title、steps、expected、actual、reported_result 与 implementation ref。阶段保存不依赖全部任务完成；不同阶段可循环保留历史。

当前模型可读 `hypertest-cloud-handoff/v1alpha1` 契约由实际 Cloud typed schemas 派生，绑定确切 Task / Attempt，给出完整 payload schema、receipt refs 和原件字节 / hash 规则。Agent 先写临时文件再原子发布 `.hypertest-cloud/ready/KEY.json`；依赖操作须先等原 key 的 ACCEPTED + 固定版本完整读回回执，再引用确切 CASE revision / Artifact ID。Worker 按词法顺序读取文件不意味着可并发猜测依赖 ID。上传由 Worker 读取批准 workspace 相对普通文件并核验 byte_count / SHA-256，再生成内部 base64 请求；Agent 不提交平台 auth / key / expected_version、预算字段或进程停止观察。COMPLETE / REQUEST_INPUT 发布后立即结束本轮，不等待终态回执而阻止 namespace 收尾。真实失败发生时保留原报告与后续修订 / 新 Run；并非要求每任务制造失败。

JSON Schema 不能自动表达全部 Python model validators 或跨对象关系，派生契约必须同时发布可检视语义及最小有效样例：CASE 的 `details` 内必须有 `steps/expected/actual`，不能仅写在 Markdown；非 CASE 需要原正文或已接受 Artifact；同批 `(kind,key)` 唯一，`checkpoint_report_key` 必须命中本批 REPORT。Run 缺结束 / 退出观察必须说明原因，结束不得早于开始，CI 身份和所有引用仍按原约束。可表达的条件直接进入 schema，时间 / 引用比较和复合唯一等另作显式规则；不因模型遗漏而放宽正式验证。

仅在严格 typed payload 校验失败且尚未冻结 / 提交任何平台请求时，可在 `.hypertest-cloud/rejections/<sha256(handoff-key)>.json` 写有界 `LOCAL_REJECTED` 反馈，标记 `platform_operation_submitted=false` 并关联 `key_sha256/handoff_sha256`。它不是平台 ACK、业务修订或已接受资产；反馈仅含闭集错误类型与静态 schema 路径，不回显原输入、任意 dict key、秘密或异常消息。模型根据原 schema 修正为新的 handoff key，原拒绝文件 / key 不改、不重发。已冻结 / SENT / UNKNOWN、未决请求、秘密 / 安全失败和平台 HTTP 拒绝均不适用此反馈；无反馈也不证明未提交，仍按原 key GET-only 规则处理，不通过新 key 绕过对账。

中途业务进度复用 SubmitCloudAssets 的 **`kind=REPORT` 非最终进度报告修订**，不新增操作或 REPORT 子类型 enum。每个 Attempt 选择独立的稳定业务 key（例如按 Attempt 命名），同 Task 内不跨 Attempt 复用该进度 key；完整原文明确阶段、已达里程碑、阻塞/未观察项及已接受产物的确切修订引用，有实质变化追加 revision。产物引用须同 Project/Task，属于当前 Attempt 的进度报告以该 Attempt 为来源；引用先前 Attempt 的已接受材料须保留真实来源，不能伪装为本次新产出。此 Cloud typed 操作支持可选 `checkpoint_report_key`：仅选择本批正式提交的一个 REPORT key，服务端将其本次接受/复用的确切 revision 原子绑定到 CloudAttempt 既有 checkpoint，并校验同 Task/Attempt 归属；省略不改 checkpoint，不允许任意 ref 或隐式清除。接受资产与该引用按同一 expected_version、operation key、lease/generation 和事务校验/保存，不在回执后补一次无 key 的更新；回执及固定版本读回须包含该绑定。报告接受只推进管理版本和已接受资产/checkpoint，不自动改变 Task/Attempt status 或 reported_result；缺省字段不能清空或改写原结果。最终报告仍须由 CompleteCloudAttempt 显式指定 final_report_revision 并满足 §46.6 收尾，不能把最后一份进度报告自动当成最终报告。

`checkpoint_report_key` 只更新既有 checkpoint 中的业务进度报告引用，保留并区分 SDK 会话、固定文件、委派状态及外部操作等运行恢复材料，不覆盖整个 checkpoint。REPORT 已读回不证明 SDK/进程可恢复；WAITING_INPUT / Resume 仍按领域 §51.4–51.5 核验全部必要上下文与未决操作。

实现产物必须固定 framework 基线、确切测试树、工作目录、commit（若存在）、dirty/untracked 清单，并保存完整 patch 与新增文件原件。只有 local path、commit 字符串或 hash 不足以交付未 push 代码。是否 push、建 MR 或写 Issue 由本任务允许动作决定，不因产物回收自动扩大 Git 权限。

上传通过受控 Project/Task/Attempt 对象入口，限制大小/类型、校验内容并持久读回字节/hash/大小，再接受 Artifact 关系。返回 URI 或摘要只证明引用存在，不证明原件上传完成。提交不得令平台执行文件、访问模型提供的任意本机路径或主动抓取任意 URL。大原件按固定版本分片读回，校验总量/连续性后重建；禁止静默截断报告。含秘密材料须在入库前拒收/脱敏，不能在持久日志留下凭据。

SubmitCloudRun 必须记录：`run_key, source_attempt, framework/CI source, actual_sut_build|UNKNOWN, exact_framework_and_test_tree, case_revisions, environment_observation, command/entrypoint, cwd, started_at, finished_at|unobserved_reason, exit_code|unobserved_reason, raw_report_artifacts, log_artifacts, case_actuals, reported_result`。CI 场景附批准项目及 pipeline/job/attempt 身份；现场观察时间与平台接受时间分开。每次重新执行使用新 run key，旧报告重提不制造新执行。

平台校验引用、原件与报告一致性后保存 Agent/framework 的 reported result；无需强制独立 CI 才能存 PASS。保存与完整性接受不等于独立来源验证，也不生成旧 VERIFIED Evidence、Gate PASS、FINAL 或 RELEASE_READY。原始 FAIL、setup ERROR、未执行与来源 UNKNOWN 持久保留；修正错误用例要保留原断言与结果，说明理由并产生新修订/新执行，不能改原断言洗 PASS。

SDK 原始事件只映射成脱敏、有界活动摘要与必要来源元数据；全 transcript、思维链、内部 Provider 事件不作为 canonical 产物。平台不把活动 PROGRESS、root idle 或模型自述转成 RunRecord。

### 46.6 等待、取消、恢复与完成

当前 workspace-local 实现提供不依赖凭据库可读性的受控取消兜底：仅 `CANCEL_TASK` / `CANCEL_ATTEMPT`，完整请求仍含原 Project/Task/Attempt、operation key 与 expected_version；`reason` 必须精确为公开常量 `OPERATOR_REQUESTED_CANCELLATION`，key 限定为 `web:<UUID>` 或 `cancel:<UUID>`。当加密 key 不可读、不可解密或加密依赖不可用时，该无自由文本请求可继续鉴权、版本检查和 fence；回执标记 `safety_control=FIXED_CANCELLATION_WITH_SECRET_SCAN_UNAVAILABLE`。完整原请求 digest、原 key 幂等与历史保持，不得换 key 自动重试。其他自由理由、ANSWER_INPUT 和 RECONCILE_ATTEMPT 不绕过秘密扫描；兜底取消只隔离写权，不证明进程或外部操作已停止，活动尝试仍进入 RECOVERY_REQUIRED 后独立对账。

进度状态和转换由领域 §51.4 拥有：DRAFT → QUEUED → PREPARING → RUNNING，可经 WAITING_INPUT 暂停并回到 PREPARING 复核后继续；COMPLETED/FAILED/CANCELLED 是 Attempt 终态，RECOVERY_REQUIRED 阻止新执行。CloudTask 在下发后投影最新 Attempt 状态；显式同输入复测追加新 Attempt，旧终态不变。DRAFT 直接取消则无 Attempt/冻结 manifest，保持终态，重新开始须新建关联 DRAFT，不适用同输入复测。`reported_result=NOT_RUN|PASS|FAIL|ERROR|SKIPPED|UNKNOWN|BLOCKED` 与任务进度、传输结果分离。

Worker 提问先持久化 question/checkpoint 和已接受资产，再安全停止/停放本地活动、释放 lease/计算。SDK 不提供的动态审批不能模拟成“已允许”；权限不足的动作必须在边界拒绝。回答补充上下文或满足冻结范围内的前置条件；新增资源、目标或权限上限须新任务。

租约/fencing 在本 profile 独立实施，Worker 结果写入须持当前短期能力、lease/generation 和 expected_version。失联时拒绝旧 owner 的迟到写入并进入 RECOVERY_REQUIRED；fencing 只保护平台提交，不证明外部动作终止。取消/超时终止整棵本地进程树，逐项记录委派、远端执行和未决副作用。仍有未知时不能仅标 CANCELLED 后重跑。

Resume 只能延续原 Attempt 的已保存上下文/文件/SDK session（确实可恢复时），不恢复 shell、浏览器、CI 或测试进程。恢复前读取原 operation key，核对外部动作、委派和产物，fence 旧 owner、重新鉴权并记录新 generation；无法安全续接则继续 RECOVERY_REQUIRED。只有对账结束且旧 Attempt 已明确终结，才允许显式新 Attempt。

当前受控 Worker 不支持原 SDK 会话续接；SDK 包中存在 resume 方法不构成本运行端能力。能力 GET 必须明确该限制，Web 不提供可用的 RESUME 承诺，服务端拒绝新 RESUME_ATTEMPT，且不推进版本或重新排队。请求取消、平台写权已 fence 但停止待确认、待对账、已终止与可续接分别显示；只有实现支持并满足服务端前置条件时才能称为可续接。

具体能力字段为 `supported.resume_attempt=false`、`supported.reconcile_attempt=true`，`recovery.resume_supported=false` / `resume_reason="SDK_RESUME_UNSUPPORTED"`、`reconcile_supported=true`、`reconciliation_source="OPERATOR_ATTESTATION"`、`independent_stop_proof=false`、`budget_disposition="KEEP_HELD"`。当前 task summary 的 `recovery` 投影 owner fence、原 pending key、remote closure、phase、can_reconcile 和 blocking_reasons；这是已检查到的 Canonical 前置条件，不代表操作者已有 cloud:control，也不声明独立进程停止。

RECONCILE_ATTEMPT 是 cloud:control / Operator 的显式人工收尾，不启动 runtime。服务端重新核对当前版本、最新 RECOVERY_REQUIRED Attempt、旧 writer 已 fence、平台/外部及 checkpoint 未决操作与委派状态；有 UNKNOWN 或未决原 key 时拒绝，不能由操作者声明清空。操作者须引用原停止/对账观察并作明确声明；声明保留为 operator-attested 来源，不构成独立进程停止证明、模型 drain 证明或测试结果。人工 FAILED/CANCELLED 收尾保留原 reported_result、checkpoint、完整回执及 HELD/preparation hold，不结算预算；旧终态不可改写。超时、异常和失联清理先封闭普通 broker 写入并按原 owner/generation 安全 fence，再停止本地进程；只有原 key 查询与限域清理保留。

CompleteCloudAttempt 须核对必需阶段资产已接受且原件可读、委派终态、执行记录/明确未执行原因、无未决操作，以及最终报告的范围/失败/阻塞/不确定项。测试 FAIL/ERROR/BLOCKED 可与任务 COMPLETED 并存。若材料不足以交付约定工作则保留 WAITING_INPUT/RECOVERY_REQUIRED 或显式 FAILED；不能用“Agent 已回答”代替交付。

### 46.7 幂等、外部副作用与同步兼容

普通 mutation 在发送前固定完整非秘密请求、稳定 operation key 与 expected_version；同 Project/key 同输入返回冻结原回执，异输入冲突。资源配置/凭据匹配各自聚合版本；Task 创建 expected_version=0，后续 Task/Attempt 控制及资产/结果写入匹配当前 Task version 并严格递增，同 key 查重先于版本检查。Worker 写入还须有效 lease/generation，管理操作按生命周期规则核验所有权并 fence 旧 owner，Task version 不替代租约检查。Task/Attempt 状态、修订、报告结果、回执与 Audit/Outbox 同事务接受；Git、SDK、远端命令和 Artifact I/O 在行锁外，返回后重新核验当前授权、版本与 fencing。凭据原文只走专门秘密入口和审计，普通 journal/回执不复制秘密。

收到回执要核对 profile、Project、Task/Attempt、原 key、请求摘要与接受版本。失答、不完整回执或 UNKNOWN 时仅 GetCloudOperation 查询原 key；NOT_FOUND 不证明原请求未接受，不授权自动 POST、换 key、新 Task 或启动另一次 Harness。外部 Git/CI/SSH/业务动作另有执行前固定的 operation key 与输入摘要，UNKNOWN 逐项保存，查询管理回执不能替代外部状态对账。

Web Cloud 操作发送前，以 IndexedDB readwrite 事务原子保全并占据同 Project 的 Cloud 操作流；只持久保存原 key、expected_version、操作/目标身份、请求摘要和传输状态等恢复所需的非秘密元数据，不保存秘密、PRD 或完整正文。Local CREATE 使用独立账本和契约。存储不可用、迁移失败或已有未决时禁止新 POST；SENT/UNKNOWN/失答/NOT_FOUND 只查原 key。跨标签通知只刷新视图，不授予发送权；响应仅可按匹配原 key 更新/移除自身记录，迟到响应不能清除新操作或另一 Project/模式的账本。旧 sessionStorage 记录事务迁移成功后才移除，冲突原 key 全部保留待对账。ACK 后按固定接受版本完整读回才移除未决记录，不用可变 head 代替。

ReconcileCloudOperation 只追加原 key 的确定观察、原材料和有权 resolution，不触发原动作或改变既有测试结果。PENDING/UNKNOWN 未消除前禁止重投/重跑；恢复和新 Attempt 都是对账完成后的显式管理动作，不宣称 exactly-once 外部执行。

§45 的 `hypertest_sync_task` / `hypertest_get_task`、`task:sync`、原同步请求/回执、分页、SessionTask 状态/result 和 UNKNOWN 规则原样保留；不得调用它们去触发云端执行。§44 native 与 legacy managed/interactive、Runner/Gate、历史 hash/FINAL 和授权不因新增 profile 迁移或升格。云端 profile 不可用时，现有会话同步仍独立可用。

### 46.7.1 固定SSH诊断的host窄协议（ADR-023，实施中）

`SSH_FIXED_DIAGNOSTICS_V1`独立opt-in，任务冻结精确canonical `ssh://user@IP:port`、完整host key、helper / catalog / 固定动作摘要及限额。Agent只可向`/run/hypertest-ssh.sock`调用`invoke --key KEY --action KEY`或`query --operation UUID`，无目标 / shell / 参数 / 环境字段，不接受Agent提供的停止或授权证明。普通Cloud handoff与平台typed操作仍由唯一Worker写入，不新增Agent writer scope。

远端操作先以Attempt / generation / stable key / 完整request digest持久SENT后单次发送；重复、失答、UNKNOWN及NOT_FOUND只能查询原ID。QUERY绝不启动，STOP不续租 / 扩大动作；签名短票据绑定请求 / 目标 / lease / hard deadline，公开有界撤销窗口。失租只保留原操作查询 / 停止 / 观察能力，新连接仍核对未撤销credential。远端真正终态与emptycgroup由canonical ledger核验；本地停止、SDK idle、模型drain或Agent布尔不能代替。未确认保持RECOVERY_REQUIRED / HELD，不得借COMPLETE / rerun / reconcile释放预算。精确契约及受控 fixture 证明见[ADR-023](../architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)；已有 canonical 固定诊断专项不表示通用 SSH、真实 staging 或最终常驻服务已验收。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。固定 SSH 诊断仅在隔离 fixture 中实施；通用 SSH 仍不支持，不改变Project共享双模式；见[执行环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

### 46.8 双产品模式与同项目任务查询

产品模式是任务协作方式，按领域 §51.8 的固定映射派生：`CLOUD_TASK → product_mode=CLOUD`、`SESSION_TASK → product_mode=LOCAL`。云端六步的项目配置、任务创建、下发和受监督执行均由云端平台完成；本地模式按 §45.4 在平台预创建 Local Task 并绑定真实父会话，由用户已有本地 Agent 负责测试工作，通过 §45 MCP 通道同步到原 Task；已确认的 legacy 自动任务保持原 ID 与 resume 契约。Local 0.1.0 的 Claude Code / Codex / DeepSeek harness 适配按其独立真实矩阵交付，不能从 Cloud provider 字段或本节混合查询推定其他宿主 / 版本已支持。LOCAL 不证明测试实际运行在本机，本地 Agent 仍可调用已有授权范围内的远端环境或 CI。

同一个 `project_id` 可同时包含两种任务。Project 不因产品模式拆分、锁定或切换；云端配置只是该 Project 的可选资源，不是本地同步的前提。每个任务保留真实类型、UUID、来源、版本和历史；不把会话同步升级为云端任务，不因云端子代理使用 Codex/Claude 自动建立 SessionTask，也不以旧 `execution_mode=LOCAL` / `CLOUD` 对新任务分类。ADR-015/016 的 Connector、交互式 Run 与旧执行模式继续按原 profile 管理。

当前项目级混合查询源码只返回领域 §51.8 定义的 `ProjectTaskSummary` 只读投影，以 **`(task_kind, task_id)`** 识别每行，并显示派生 `product_mode`、真实 source、原状态与 reported result。允许按类型/产品模式/来源筛选，不能按筛选请求更改类型。列表详情路由按类型调用原读取契约，固定对应任务版本读取原件/历史；不得新增跨表通用任务 FK、重编号任务或合并两类结果/证据等级。本设计不声明 §45 现有工具/API 已支持混合查询，也不为该目录新增 scope 或修改原请求/回执。

每行必须核验当前 Project grant、对应类型的既有读取授权及 owner 约束：SessionTask 遵循 §45 / 领域 §50 的 `task:sync` 与归属规则，UNBOUND 不能伪造 owner 或来源；其按 ID 读取 / 绑定另须满足 §45.4 intended actor 规则，不因混合目录自动扩大读取范围。CloudTask 遵循本节的 `cloud:read`。只有 Project 可见或只有一种授权均不开放另一类任务，未授权行/计数/来源不得泄露；云端控制和凭据使用仍按独立授权检查。`task:sync` 既不授予云端读取/执行/凭据能力，也不要求先取得这些能力。关闭云端入口、SDK/Worker 不可用或云端凭据缺失/撤销时，现有本地同步与获授权历史读回仍独立工作。同项目并存、筛选、隔离与历史保全的验收见领域 §51.8。

## 47. ADR-020 Local Hooks 与显式 MCP 协作

2026-10-27：[ADR-027](../architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)确定新的 Local 显式 Skill/CLI 后置归档方向，首片协议实现见§51及[本轮交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)。本节与§45继续解释已交付版本及旧回执；新归档不复用 native BIND/JOIN 合同。

本节记录 Local（ADR-020）与 TaskSyncCore（ADR-021）Local 消费方的独立交付边界。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

Local 客户端沿用 ADR-018、TMP §45 与领域 §50 的身份和同步契约；人工管理见§45.3/领域§50.4，ADR-024预建绑定与新会话前置门槛见§45.4/领域§50.5。legacy API/profile、task:sync、
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

## 48. ADR-021 共享同步语义的 Local 约束

TaskSyncCore 是内部可复用库，LocalSyncAdapter 保留 SessionTask 的原请求、身份、权限与版本规则。
共享语义是批准的结构化意图、完整基线、冻结请求、原 key 对账、回执验证与固定版本完整读回；
不增加通用 Task/API、跨模式 token、全局 journal 或服务端 fencing 字段。
Source binding、事件队列、snapshot 与 checkpoint 均为私有客户端记录，不是新的业务状态；不等同§45.4的服务端Task绑定字段/回执。新增TaskID选择仍进入同一root协调器，不增加writer或授权。
只合并未冻结新意图；显式 MCP 完整请求的空值不被自动推断为 omitted，传输失败不修改业务报告。
Cloud 消费方由 §46 和下节独立集成/验收拥有；Local 包不包含 Cloud runtime。

### 48.1 Cloud adapter 的独立协议约束

CloudSyncAdapter 仅构造 §46 对应 typed operation，不把 CloudTask 转为 SessionTask，不复用 task:sync、Local expected_version+1 规则或本机账本。Worker 核对当前 Task/Attempt、lease/generation、Project/资源授权后冻结完整非秘密请求和原 operation key；根及 Codex 子代理只贡献原件，Claude仍占位，均无平台 writer token。

阶段进度使用非最终 REPORT 修订；checkpoint_report_key 仅选择本批正式 REPORT，省略保留原绑定，最终报告仍由 final_report_revision 指定。SDK/Hook活动只触发检查，不决定 Task.status、reported_result 或正式执行事实。

SENT/UNKNOWN/失答及NOT_FOUND只查询原key，不重POST、不换generation改写旧请求或自动重跑；有效ACK之后还须完整读回该操作承诺的固定版本/原件。取消与lease丢失先阻止旧writer，领域接受、在途上传、模型/子进程和远端操作分别对账，未确认则保持恢复态及历史；不能跨过未决直接完成。

Cloud/Local分别固定共享库、adapter和版本兼容性，关闭/失败的一方不得阻断另一方同步、原key查询和获授权历史。既有Cloud fixture及Local真实矩阵保持各自身份；最终Git的组件回归和部署检查见[交付记录](../CLOUD_GIT_DELIVERY_20261023.md)，用户验收由用户执行，不从这些检查推定真实native bind通过。

## 49. ADR-022 显式项目经验协议

ADR-027 归档来源增补：Memory `CREATE_CANDIDATE` 的 `source` 可为 `{mode:"LOCAL_ARCHIVE", task_id, submission_id, archive_version, asset_revision_id}`。Operator 提供确切已接受 Submission 及快照中 REPORT 修订；Gateway 按领域 §54 核 Project、目标、版本和内容。此类型只允许 Operator，公开检索不附私有报告。`archive:read/write` 与 Memory scope 不互相授权，报告结果仍是上传者声明。

独立profile为 `hypertest-project-memory/v1alpha1`；实体和状态由领域§54拥有，[ADR-022 §0](../architecture/ADR-022_PROJECT_MEMORY_WITH_POWERCONTEXT.md)定义本轮接口/信任边界。服务端前缀 `/api/v1/memory`，与任务sync/Cloud operation无共享key、版本、journal或成功判定。

| 接口 | 契约 |
| --- | --- |
| POST /operations | `{operation,project_id,operation_key,expected_version,...}`，操作为CONFIGURE/CREATE_CANDIDATE/PUBLISH/REVISE/RETRACT；原key同输入返回原回执，异输入409；候选版本0，entry/映射修改匹配其独立版本 |
| GET /operations/by-key | `project_id,operation_key`；当前独立memory权限及原actor/Operator核验，只查原key；SENT/UNKNOWN/NOT_FOUND不重POST、不换key |
| GET /projects/{id} | status/offset/limit有界目录，候选限owner/Operator，当前共享与独立未决操作投影 |
| GET /projects/{id}/configuration?version=N | 固定接受的映射配置版本，当前开关与历史分开 |
| GET /entries/{id}?project_id&version=N | 完整固定经验修订；旧版另标SUPERSEDED/EXPIRED等当前处置，不改原revision_status |
| POST /query | `{project_id,query,limit?,source?,context?}`，query≤1000字符/limit≤20；显式最小query，固定来源与Cloud claim context互斥；没有自动prompt/聊天采集 |

独立scope为memory:read/propose/publish，配置/发布/修订/撤回还必须人工Operator。Local候选source为 `{mode:LOCAL,task_id,task_version,report_id}`，核当前BOUND owner、固定SyncReceipt和ReportRevision；Cloud候选source为 `{mode:CLOUD,task_id,task_version,attempt_id,asset_revision_id}`，核同Project/Attempt固定接受资产及当前Worker。Cloud私有HTTP headers携worker_id/lease_token/generation/work_token，不能进入业务请求摘要、账本、SDK/Agent或报告。独立memory bearer不替代fence，cloud:work不替代memory授权。Local查询无需报告，但私有MCP核真实父caller/绑定；Cloud查询context为原claim `{mode:CLOUD,task_id,attempt_id,task_version}`，Worker注入且Gateway前后核验，不需asset。共享读取只给opaque provenance，源报告另按原权限读取。

Local显式工具为hypertest_query_memory/propose_memory/get_memory_operation，默认关闭、memory.sqlite3独立；目前新调用仅Codex可信caller，其他宿主明确拒绝，原key恢复保留。Cloud使用独立memory-ready JSON与memory-responses，后台optional broker不占正式report同步槽。Web独立IndexedDB只保留lookup metadata，写前事务占据流，ACK完整读回固定修订后按原key结算；跨页响应不得清后续记录。

Gateway发布先持久SENT，再单次上游remember；ACK后GET原artifact固定revision并核完整正文/digest后接受。UNKNOWN仅原ID查询，或原marker只读FTS定位后GET确切原件；上游FTS协议的只读POST不重发remember。撤回立即从当前可见集剔除，旧索引/迟到响应不能复活。独立网络阶段≤5秒，故障只降级memory，不改测试结果/Cloud HELD、不阻原任务同步。命中是历史参考，不能授权外部动作或代替当前执行证据；Generation/Embedding及自动Hooks关闭。

## 50. ADR-025 Cloud 受控 HTTPS 与框架冻结

本节只扩展Cloud profile，不改Local协议。`environment.https_access`使用HTTPS_CONTROLLED_API_V1，固定目录与profile字段见[ADR-025](../architecture/ADR-025_CLOUD_CONTROLLED_HTTPS_READS.md)。任务须有FRAMEWORK_LOCKED_V1的inputs.framework_runtime、精确framework_entrypoints与origin读授权；省略新字段的旧请求序列化不增加null。API capabilities区分implemented支持、API配置开关与每Attempt准入；默认关闭不因WEB_ONLY或host可达而变为执行许可。

namespace仅访问固定Unix socket，用单行JSON请求：`{verb:INVOKE,key,resource_key}`；只读恢复为互斥的`{verb:QUERY,key}`或`{verb:QUERY,operation_id}`。CLI为`python -m hypertest.cloud.http_client invoke --key K --resource R`及`query --key K`/`query --operation UUID`。原key先持久化SENT后单次发送，失答/UNKNOWN/NOT_FOUND不再INVOKE，不换key。缺UUID时仍按key查询，不借prepare_start恢复发送。

响应status为OBSERVED或UNKNOWN，response使用hypertest-https-response/v1：原operation_id/request_digest/state/http_status/body_base64/body_sha256/byte_count/reason/observed_at。OBSERVED必须完整原件/摘要与canonical metadata一致，并经当前fence/秘密扫描；UNKNOWN不含body/HTTP状态，只用固定reason。HTTP状态与正文不是reported_result。REFUSED/UNKNOWN或丢响应不能推导未执行。

框架冻结检查只读锁文件并对固定Python/Node执行--version，不自动安装、联网或执行声明argv，不声称依赖闭包或限制了任意SDK shell语义。一般凭据HTTP/写操作/浏览器/CI不通过本profile准入；UNKNOWN阻止收尾并保持原预算及历史。

## 51. ADR-027 Local 显式归档协议目标合同

> **ADR-028 覆盖：** 以下旧实现的兼容、记录及恢复保留义务不阻止退休不兼容实现并定向删除其旧数据；实际仍可访问的记录按原语义解释，未知外部操作不得自动重发。

本节为首片已实现的 `local-artifact-archive/v1alpha1`；部署、发行与 USER_OWNED 状态见[本轮交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)。该协议由 [ADR-027](../architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)采用，领域语义见[领域§56](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#56-adr-027-local-显式后置归档目标合同)。它通过普通 HTTPS 请求/响应工作，不需要 MCP、Hook、SessionStart、source binding、常驻连接或 Agent 执行通道。

### 51.1 目标接口与授权

下表均以 `/api/v1/local-archive` 为前缀，已有首片实现；实际服务器能力由已部署源码及 capabilities 确认。归档管理 API 要求显式 Operator 认证；Web 通过独立 BFF 在服务端注入凭据，并核写请求 Origin，浏览器与 CLI 不持有 Operator key。无凭据请求不自动成为管理请求。

| HTTP 操作 | 权限与契约 |
| --- | --- |
| `GET /capabilities` | 归档授权；分别返回 implemented/configured、profile、正文/条数上限和支持的产物类型 |
| `GET /actors`、`GET /tasks` | 前者 Operator 获取当前可用归档上传 actor；后者 Operator 或 archive:read 获取项目内当前获准任务的有界目录 |
| `POST /tasks/{id}/update` | Operator；显式 title/objective 管理变更，原管理 key 与 expected_task_version；结果通过 Publication 更新 |
| `POST /tasks`、`POST /tasks/{id}/subtasks` | Operator；明确 Project/父 Task、title、可选 uploader；管理 key 与适用 expected_task_version。创建 Task 可选 `sut_branch`、`framework_branch` 和 `expected_project_version`，API 固定当时 Project 的 `repository_url` 与 `test_framework_repository_url`；四项作为声明在任务读取及原创建回执中返回 |
| `POST /tasks/{id}/authorize` | Operator；明确 owner/子任务 uploader，expected_task_version；不签发或扩大 integration grant |
| `POST /tasks/{id}/publications` | Operator；expected_task_version、root_archive_version、精确子任务归档版本清单、显式汇总与原 key |
| `GET /operations/by-key` | Operator 按 Project/原管理 key 恢复创建、授权或汇总，返回原固定管理回执 |
| `GET /tasks/{id}` | Operator 或获准的 archive:read；返回任务管理信息及根/子任务归档版本 |
| `GET /tasks/{id}/archive`、`GET /tasks/{id}/subtasks/{subtask_id}/archive` | Operator 或获准的 archive:read；选择明确 archive_version，分页读取目标空间完整快照 |
| `POST /tasks/{id}/submissions` | archive:write，CLI 同时需 archive:read 完成确认；上传者由认证得出，归档正文见下节 |
| `GET /submissions/by-key` | archive:read；Project/原操作 key，按原上传 actor 权限返回瘦回执，NOT_FOUND 不授权重传 |
| `GET /submissions/{id}` | archive:read；固定接受的 TASK/SUBTASK 空间快照及引用资产正文，分页参数与下节一致 |

每次归档显式传 Project ID、Task ID，Subtask ID 可选，路径和正文目标必须一致。省略 Subtask 时 target_kind=TASK；指定时 target_kind=SUBTASK，目标不存在/跨任务/越权均拒绝，不能回退 Task 或推断子任务。所有读取检查目标授权，不凭 UUID 或来源字符串开放跨项目数据。新的 CLI 不携带 Operator key；Web 创建者和 integration 上传者的身份域分别记录。旧 `task:sync` 或 `cloud:work` 不满足新 scope。

Local Task 的分支声明各为可选、1–255 字符，拒绝 ASCII 空格及控制字符；不能据此推定已获取对应 Git 对象或已验证执行。新 Web 创建时提交所见 `expected_project_version`，服务端在锁内对新 key 校验版本，变更则 409；旧客户端省略保持兼容。原 CREATE key 与其实际请求字段保持幂等，先核对原 key、再检查新请求项目版本，重查返回原固定回执；项目后续变更不替换该 Task 的仓库/分支，旧 Task 不补造缺失值。Cloud Task 双 selector、资源配置修订与冻结 manifest 仍依 §46 独立处理。

### 51.2 Manifest、上传与完整读回

私有 manifest 携必填 `profile/project_id/task_id`、可选 `subtask_id`、`assets` 及仅对子任务有效的可选 `subtask_update`；profile 在 wire 中为协议标识，不是 CLI 的本机连接 profile 名。CLI 显式参数与 manifest 目标不一致时拒绝，不静默覆盖。每个 asset 明确 kind、stable_key、标题/结果、origin 和本地文件路径或结构化 CASE 内容；目录必须展开成用户批准的有限文件清单。Agent 不能将命令、任意聊天/凭据目录或远程抓取要求嵌入 manifest。CLI 安全读取实际文件并构造 typed wire body，本地绝对路径不作为上传原件。

wire body 为 `{profile, project_id, task_id, subtask_id?, idempotency_key, expected_archive_version, assets, subtask_update?}`；省略或 null subtask_id 规范化为同一 TASK 目标后冻结摘要，target_kind 由此唯一确定。assets 为明确 upsert 集合，每项带完整内容与来源；省略资产不删除，更新子任务字段必须显式出现且非 null；TASK 目标不接受 subtask_update 或整体 Task 状态/结果写入。CASE 使用§45.1的结构化业务字段；PLAN/REPORT 使用 UTF-8 正文，原始报告保持原文，source_ref/artifact_uri 只作引用，不触发服务端下载。新 profile 明确定义部分更新语义，不将旧 hypertest_sync_task 重新解释为 PATCH。

首片沿用 stable_key 128字符、单计划/报告262144字符、每批16计划/200用例/16报告、每用例100 steps 等业务字段上限，typed JSON 总量上限2MiB。以最终 UTF-8 请求字节核总量；不沿用 MCP 的1MiB消息限制，也不无界扩大。能力不支持、超限、路径/秘密检查失败时整批拒绝；不静默截断、隐式拆分或仅保存 hash 后称原件已上传。

CLI 在冻结新请求前读取固定目标空间基线并核当前权限；保存最终完整请求、文件字节和预期合并结果后单次发送。重复同一私有 request_id 复用原 key 和冻结内容；已确认完成且内容未变时可直接返回原结果。显式后续新归档使用新的本地请求记录，服务端仍按领域§56处理版本与 UNCHANGED。

瘦回执包含 `{profile, submission_id, project_id, task_id, target_kind, subtask_id, uploader_actor_ref, idempotency_key, request_digest, outcome, accepted_version}`，outcome 为 ACCEPTED 或 UNCHANGED；subtask_id 对 TASK 返回 null，accepted_version 是该目标的 archive_version。客户端核请求/目标/上传者及版本（变化为 expected+1，无变化为 expected），再读取该 Submission 的完整固定快照。

分页 envelope 为 `{profile, submission_id, project_id, task_id, target_kind, subtask_id, archive_version, offset, total_chars, next_offset, content, complete}`；按 Unicode 字符计 offset，单页上限24000字符，所有页面固定同目标/submission/archive_version。末页 next_offset=null，非末页为 offset 加本页 Unicode 字符数；每页的 complete/total_chars/目标/版本须一致核验。读回包括完整目标空间快照（SUBTASK 含子任务状态；TASK 不含可变管理状态/结果）、资产 key/revision、原文/结构化内容和逐资产来源；按冻结预期验证，不能用 current head 或仅摘要代替原文。

### 51.3 CLI、Skill 与恢复结果

`hypertest archive --profile NAME --project-id UUID --task-id UUID [--subtask-id UUID] --manifest FILE --json` 完成一次归档（方括号表示可选，不输入方括号）。`auth` 完成全局配对/状态/恢复/本机退出，`profile` 管理按 server/client/actor 隔离的私有连接引用，`doctor` 只读诊断能力，`status` 查看本地请求状态，`reconcile --request-id UUID` 查询原 key/继续固定读回，`skill install --global --host codex` 或 `--directory DIR` 安装明确目标中的归档 Skill；宿主支持按实际核验声明。CLI 必须显式接收 project-id/task-id，不从 cwd/profile 推导，缺失则零业务 POST。多个平台配置需明确选用 profile；任务 ID 不触发隐式换平台或身份。`status --remote` 才执行远端查询，`--dry-run` 不创建业务提交。

`--json` 至少返回 `{status, request_id, project_id, task_id, target_kind, subtask_id, submission_id?, accepted_version?, readback_complete, task_url?, code?}`；status 区分 ARCHIVED、UNCHANGED、PREVIEW、PENDING、UNKNOWN、REJECTED。只有完整读回或已验证的同一原请求可返回 ARCHIVED/UNCHANGED；预览成功不能冒充归档成功。普通命令成功为退出码0，参数/本地输入错误2，明确拒绝3，未决/UNKNOWN/读回未完4，配置/能力缺口5；stderr 日志与 stdout JSON 分开。

Skill 名为 `hypertest-archive`，需用户显式选择；自然语言关键词和 Project/Task/Subtask ID 不作为鉴权字段。用户授权的文件范围足够明确时直接完成归档，未知必要输入才澄清。Skill 不隐式读聊天、自动触发 CLI 或执行 SUT；结果 UNKNOWN 时只引导原请求查询，不循环换 key 重发。

2026-10-27 页面 Prompt 可显式授权 Agent 根据本次测试上下文和限定的相关输出目录解析实际产物路径、生成有限 manifest，并按明确服务器/项目/上传身份匹配既有连接；不要求用户逐项填写路径或配置占位。该授权仅覆盖可确定归属于本次任务的计划、用例与报告，默认排除秘密、聊天/推理及无关文件。Agent 列出清单后无需再次确认，但目标、范围、身份或受信 CA 确实不明确时须澄清，不得全盘扫描、猜测任务、切换身份绕过权限或自动扩大范围。最终 CLI 显式目标、有限清单与原 key 恢复合同不变。

新档案请求与旧 Local bind/sync/collaboration namespace 分离。`hypertest legacy reconcile --config FILE --request-id KEY` 显式选择既有私有账本，歧义时用 `namespace/key`，执行旧 SYNC/BIND/协作原 key GET/固定版读回；不能生成新的旧 POST、伪造 native caller 或启动 MCP/Hooks/daemon。切换后新的旧操作返回明确退休错误，旧历史仍按原协议读回；公开旧 tag 与已接受回执不重标。旧 compact journal 缺少原正文时返回 `LEGACY_ACCEPTED_READBACK`、`original_request_verified=false`，不声称原请求内容比对；完整冻结请求通过比对才返回 `LEGACY_RECOVERED`。旧 CREATE 保留原 Web journal 恢复；CLI 不获得 Operator key。`hypertest legacy retire --directory DIR --host HOST` 只按旧安装收据移除自有配置，漂移时拒绝并保留，停止进程须核私有 IPC 的 runtime/配置指纹；原件、未决 key 和账本保留。

### 51.4 CLI 授权页面与一次绑定

下列为已实现的独立 `/api/v1/cli-authorizations` 合同，与归档提交、旧 task:sync 授权的 namespace 分开；不复用当前一次返回明文 token 的注册接口来假定失答可恢复。

| HTTP 操作 | 权限与契约 |
| --- | --- |
| `POST /requests` | CLI 发起配对；联网前已持久保存 request_id、原 CREATE key、credential secret 与独立 verifier。只提交 credential_hash、verifier challenge、非秘密 client 信息及可选预选项目；尚无归档权限 |
| `POST /requests/{id}/approve` | 既有 Web Operator；核配对短码、稳定 APPROVE key，一次冻结服务端解析的专用 CLI actor、项目 allowlist、archive:read/write、期限和原指纹；新正文不传 actor，遵守现有 Web 访问/CSRF 边界 |
| `POST /requests/{id}/redeem` | CLI 持有私有 verifier proof；独立 REDEEM key 绑定批准结果，只允许兑换原固定授权，不接收扩权字段、不返回长期 secret |
| `GET /requests/by-key`、`GET /requests/{id}` | CLI 私有 proof 或有管理权限的 Web 身份；按原操作 key/阶段读取固定回执及当前状态；公开 ID/短码不足以获取授权详情 |
| `GET /grants`、`POST /grants/{id}/revoke` | Web Operator 查看/撤销 CLI 授权；撤销有原管理 key，不清历史，CLI 的 archive scope 不获得该管理权 |
| `GET /actors` | 保留 Operator 认证后返回 410 / `CLI_UPLOADER_SELECTION_RETIRED`；不再为新配对枚举历史 ACTIVE 身份，不删除其历史记录 |

`hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default` 从任意工作目录启动配对。可选 `--project-id UUID` 只预选项目。CLI 显示/打开现有 Web 授权页与短码，命令、URL、日志、stdout 不携带 credential secret/verifier/Operator key。用户在 Web 核对短码和客户端，一次批准明确项目、scope 和期限，无需选择历史上传身份；CLI 在短时窗口内有界查询，兑换并核对原 grant/client/credential 指纹，原子保存用户级 profile 后退出。无 localhost callback、daemon 或后台续签。

2026-10-27 授权入口增补：服务端使用稳定 `connector_operator_identity` 查找不可变 `CliArchiveUploader` 映射，在首次有效 APPROVE 通过短码、客户端、项目和期限检查后同事务创建专用 integration actor 与映射。同一 Operator 跨设备复用该 actor，各设备的项目授权仍单独批准；客户端自报身份、短码或旧 ACTIVE 列表不能决定 actor。专用 actor 或客户端已撤销时拒绝批准，不另建身份绕过撤销。

新 APPROVE 不发送 `actor_identity_id`。该可选旧字段仅保留用于已接受旧 APPROVE 的精确原 key/原正文回执恢复；同 key 异正文仍拒绝，无已接受回执的带 actor 新写拒绝。旧 APPROVED/BOUND 按原 actor 兑换或恢复，不替换为新专用 actor，不改写旧 grant、Task owner 和回执。旧 PENDING 配对可接受符合新合同的批准；但已冻结或可能发送的旧 APPROVE 只能按原 key 查询，不能去掉 actor 改正文后重发。

CREATE 固定配对上下文，APPROVE 固定实际授权，REDEEM 绑定该批准结果；三者分别有原 key/冻结正文/状态，不把尚未批准的项目预选当作 grant。原请求同 key 异输入拒绝。配对窗口例如10分钟，与 grant 期限分开。正常流程中的查询只在 auth bind 命令存活期间进行，不在测试中同步。

`hypertest auth status --request-id UUID --json` 查看本机配对记录，不推断服务端授权仍有效；`auth reconcile --request-id UUID --json` 才使用私有 proof 按原 key 查询并核对非秘密回执，已 BOUND 时可恢复 profile 保存。任何已发送/可能已发送操作的失答、UNKNOWN 或 NOT_FOUND 均不重 POST、不换 key 签发；确认前一阶段后，明确从未发送的下一阶段可用 `auth bind --resume --request-id UUID` 首次推进。CLI 预存 credential 使绑定成功后的失答无需再次获取明文 token；原 key 查询不充当新的授权。服务端以原配对 credential_hash 与 `CliAuthorizationGrant` 映射选择显式 Project 的独立 grant；各 grant 的 token_hash 唯一性不变，CLI credential 不成为跨项目通配授权。

已有 profile 的 server/client/actor 不匹配则拒绝覆盖并提示使用新 profile；相同身份新增项目需 Web 明确批准后原子合并。授权状态输出仅含 request_id、阶段、状态、grant/client 指纹、actor、获准项目/scopes/期限等安全字段，不显示 secret/hash 验证材料。auth logout --profile NAME 停用本机 profile；服务端撤销由页面明确执行。两者不清 journal/未决 key，不自动扩权或重绑；过期/撤销后归档和读回仍按当前有效授权判定。操作指南见[CLI 授权指南](../CLI_AUTHORIZATION_GUIDE.md)。
