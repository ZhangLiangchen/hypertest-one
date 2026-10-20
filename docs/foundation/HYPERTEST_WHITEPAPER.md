# HyperTest 白皮书

**版本：v1.3**

**部署与工作流决策：ADR-013 / ADR-015 生产状态与历史验收保留；ADR-016 已实现 / 隔离当前 Agent 核心周期验收通过 / 已部署生产，线上当前 Agent 核心周期已通过（2026-10-20，Asia/Singapore）**

**定位：Agent-native Autonomous Testing Platform**

**架构角色：Autonomous Testing Control Plane**

[ADR-013：容器化平台与持续 Harness 会话](../architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)定义部署组件与任务执行边界。[ADR-014：会话关闭后的独立质量重评](../architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)将报告完成后的 Finding 处置与平台 Gate 治理区分于 Agent 工作。字段和生命周期以[领域模型](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)为准，工具与消息以[TMP](../protocol/TEST_MISSION_PROTOCOL.md)为准。实现与真实集成结果见[第一阶段验收](../FIRST_PHASE_ACCEPTANCE.md)，不由设计目标推定全部完成。

[ADR-015：双模式 Harness 与本地 Connector](../architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)扩展部署选择：保留服务器 Harness，增加用户电脑主动连接的本地 Harness，复用本地实际可用的模型、Git 与问题单授权。它不移动控制平面、Canonical State 或可信 Runner，也不改变单任务单主会话原则。ADR-015 双模式、设备 / 项目授权、WSS 持久 mailbox、HTTPS 源码接收、本地问题单适配与显式恢复已实现，`0015_connector_nodes` → `0018_harness_selection` 已部署生产。核心隔离真实验收已通过，包括本地 Codex → 远端可信 Docker Runner → Evidence / Gate → 报告正反链、私有 Git 经 HTTPS 接受、原会话断线恢复及获准测试 Issue 的创建 / 负责人核验。这些隔离结果不冒称生产结果。生产切换已完成原数据、文件、认证、SSH / VPN 与服务器 Bridge 保全；严格外部 TLS、线上本地 Connector 核心周期和生产私有源码 source-only 接受补验已通过，后者未启动私有业务 Run 或问题单操作，扩展真实设备故障矩阵继续分别登记。该次发布与实际验收范围见 [ADR-015 生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)，隔离历史见 [ADR-015 总验收](../ADR015_ACCEPTANCE.md)，源码统计见[源码验收记录](../ADR015_ACCEPTANCE_SOURCE.md)。

[ADR-016：交互式 Agent MCP 接入](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)接受云端 / 本地 Agent 执行选择：云端由平台托管 Harness，本地交互式执行时，当前 Agent 可经可信宿主证明与显式绑定成为任务执行者，通过 MCP 获取 Mission、推理 / 实现、提交 Proposal 并获取可信 Runner 事实。HyperTest 是其外接测试平台，不另启第二个 Agent 代执行。原有 Harness 接入模式与 Canonical / Runner / Gate 边界保留。安装包、执行绑定、独立集成授权、新 typed HTTPS API 及原 Job Worker 工具收件箱已在本分支实现，新增 `0019` / `0020` additive migration；当前真实 Codex Agent 的隔离正向完整周期已独立通过，见 [ADR-016 验收](../ADR016_ACCEPTANCE.md)。已部署生产，线上当前 Agent 核心周期已通过，也不由该结果推定所有宿主、外部集成或恢复矩阵通过。

生产发布为 PR #17 / `c7cd43ad6346d8ce6c85564f7838afbb017f2da4`，正式库已向前升至 `0020_interactive_tool_inbox`；PR / main CI 为967 passed、21 skipped。同一真实当前 Codex Desktop Agent 经官方 MCP SDK console 完成生产核心周期：2 Requirements / 3 Risks / 4 Cases / 4 Implementations，唯一平台可信 Docker Execution 的33项 HTTP 测试通过，五份 VERIFIED Evidence 与两页报告内容均经 MCP 读取并核验 hash / 字节数，形成 FINAL `RELEASE_READY`。真实过期后的两次显式 Worker 恢复保留原 Run / native / workspace，epoch 1 → 2 → 3，旧 Job / Attempt 保留；最终历史保全另经39项只读检查通过。详细身份、时序与保全边界见[ADR-016 生产部署记录](../ADR016_PRODUCTION_DEPLOYMENT.md)及[生产机器证据](../evidence/adr016-production-20261020.json)。隔离验收的27项测试仍属其独立历史；本轮不宣称聊天原生工具目录热加载、运行中断线注入、两种原受管路径的新完整周期、私有 SUT 业务或新增问题单写入通过。

---

## 1. 执行摘要

随着 Codex、Claude Code、OpenCode、Pi 等通用 Coding Agent 快速发展，软件研发正在从“AI 辅助编码”进入“Agent 自主完成复杂工程任务”的阶段。

测试领域也正在发生同样的变化。

今天的通用 Coding Agent 已经能够完成大量传统测试开发工作：

- 阅读 PRD 和技术文档；
- 理解代码仓库；
- 分析 Git Diff；
- 生成测试场景与测试代码；
- 调用 Shell、Docker、Kubernetes 和测试框架；
- 执行测试；
- 分析失败日志；
- 修改代码并进行迭代。

因此，HyperTest 不应重复构建另一个通用 Coding Agent。

HyperTest 的核心目标是解决另一个更重要的问题：

> **如何将通用 Agent 的智能能力转化为可治理、可验证、可追溯、可持续演进的软件测试能力。**

HyperTest 因此被定义为：

> **面向 Agent 时代的自治测试平台（Agent-native Autonomous Testing Platform）。**

在架构上，HyperTest 是：

> **Autonomous Testing Control Plane。**

Codex、Claude Code、Pi、OpenCode 等则作为：

> **Agent Harness / Intelligent Testing Worker。**

HyperTest 不负责重新实现 Agent Loop，而负责定义：

- 应该测试什么；
- 为什么测试；
- 应该测试到什么程度；
- 当前测试覆盖是否充分；
- Agent 应完成什么 Mission；
- 测试是否真正执行；
- 什么证据可以被信任；
- 测试结果是否满足质量门禁；
- 测试资产如何形成长期知识；
- 一个版本为什么可以或不可以发布。

HyperTest 的核心链路为：

**Requirement → Risk → Test Case → Implementation → Execution → Evidence → Finding → Verdict**

这条 Testing Semantic Chain，是 HyperTest 的核心领域模型，也是其长期技术与产品壁垒。

### 1.1 实际使用单位与执行方式

- 一个 SUT（被测系统）对应一个长期存在的 Project；同一系统的 feat / MR 在项目内组织，而非各建一个项目。Project 是系统身份，仓库 URL 不是唯一系统标识，长期仍可支持一个系统的多个仓库。
- 一个 feat / MR 的确定完整 SHA 的一次完整测试活动对应一个 TestRun，即用户看到的测试任务。任务同时冻结需求原文、配置、执行环境和 Policy；MR 编号、分支名是关联与展示信息，不替代实际被测 SHA。
- 一个任务绑定一个逻辑 Task Worker 和一个持续的主 Harness 会话。该会话串行、自驱地完成测试分析、风险分析、测试设计、代码实现、正式执行请求、失败诊断和报告；阶段切换不重新开会话。
- Harness 可选服务器 `SERVER_HOST` 或用户电脑 `LOCAL_CONNECTOR`。现有默认保留服务器模式；用户显式选择模式和节点，可保存本地偏好。首次绑定后模式、节点、Provider、主会话与工作区固定，离线不自动回退；更换这些身份或主会话丢失需要新测试轮次。
- 同一任务不由多个平台 Worker 同时协作；多个不同任务可并发，包括同一个 SUT 的不同 feat / MR SHA。并发上限由平台、Harness 和 Runner 的实际容量共同约束。
- 关键决策通过持久人工问题交给操作者，回答后恢复原会话。缺陷可按已配置的 GitLab 项目、责任人和提单策略形成 Issue，并关联测试任务、Finding 与正式 Evidence。

ADR-016 的产品 `execution_mode=CLOUD|LOCAL` 表示 Agent / Harness 的执行位置；正式 Runner 的位置与信任独立，首版仍为平台可信 Runner。`CLOUD` 对应 `SERVER_HOST + PLATFORM_MANAGED`；`LOCAL` 对应 `LOCAL_CONNECTOR`，既保留 ADR-015 的 `PLATFORM_MANAGED` 本机专属会话，也增加 `INTERACTIVE_MCP` 当前 Agent 直接执行。新的 execution driver 属 Operational 选择，不是第三种 Harness mode；组合明确固定，旧请求缺新字段时保持原平台托管行为，不改写历史。

当前本地 Agent 可以显式成为该 Run 主 Session，但普通提交 / 查询不会自动绑定聊天。须验证真实 native 身份、节点、受控工作区、固定源码与宿主生命周期，并保持一任务一逻辑 Worker / 主 Session / 节点 / Workspace 和唯一 owner；无这些宿主能力时只能提交 / 读取或选择云端执行。

Task Worker 的稳定身份与操作系统进程、容器 ID、一次 Job 租约不同。等待人工输入可以释放运行资源，但保留任务绑定、原生会话和工作区；进程替换必须显式恢复同一绑定并隔离旧执行者。原会话丢失时停止并保留历史，不能另开会话冒充续接。

人工问题既可以属于当前阶段，也可以发生在阶段之间或缺陷派单时。任务级提问不重开已完成的阶段；平台保留明确的问答归属，回答后继续同一主会话。具体持久化与暂停恢复规则由领域模型和 TMP 定义。

相同测试输入的重复提交应幂等复用原请求；新 SHA 创建新测试任务。同一 SHA 需要改变需求、策略或环境、或显式重新测试时，保留新的测试轮次与旧结论，不以 `Project + SHA` 唯一约束阻止复测，也不改写旧快照。

---

## 2. 背景：Coding Agent 正在改变测试开发

过去，测试自动化的核心问题是：

> 如何把人工编写的测试用例自动执行。

因此形成了大量测试框架：pytest、JUnit、Playwright、Selenium、k6、Locust、Robot Framework 以及各类内部测试平台。

这些工具解决的是 **Execution Automation**，但它们通常不负责理解需求、分析代码、判断风险、自动设计测试、自动实现测试代码、根据失败结果继续调查以及自动形成测试结论。

LLM 与 Coding Agent 的出现改变了这一边界。Agent 已经能够动态执行：

```text
理解需求
  ↓
阅读代码
  ↓
形成假设
  ↓
设计测试
  ↓
实现测试
  ↓
执行
  ↓
观察结果
  ↓
分析
  ↓
继续探索
```

软件测试由此开始从 **Automation** 演进为 **Autonomous Testing**。

然而，直接让 Codex 或 Claude Code 接收一句“根据 PRD 和代码完成测试”，并不能形成真正的自治测试平台。它只是一个强大的 Agent Session。

---

## 3. 问题定义

如果直接将 Codex CLI 部署在服务器，并由 Web 页面触发：

```text
PRD + Git
   ↓
Codex
   ↓
生成测试
   ↓
执行
   ↓
Markdown Report
```

短期能够快速形成 Demo，但随着项目规模增长，会迅速出现以下问题。

### 3.1 测试状态隐藏在 Agent Context 中

系统无法可靠回答：当前有哪些 Requirement、哪些 Requirement 已测试、哪些 Risk 尚未覆盖、一个 Test Case 为什么存在、哪些 Test Case 已实现自动化、哪些 Case 真正执行过、上一次执行对应哪个 Commit、哪些测试失败属于产品缺陷、哪些属于环境问题、当前发布结论基于哪些 Evidence。

**Agent Conversation 不能成为 Testing State。**

### 3.2 Agent 自述不能成为事实

Agent 可以说“所有测试均执行成功”，但自治测试系统必须能够证明：测试在哪里执行、使用什么代码版本和环境、执行命令、Exit Code、JUnit/XML、HTTP 返回、Metrics、Log、Trace、Screenshot 等。

因此：

> **Agent Claim ≠ Evidence**

### 3.3 Prompt 无法成为稳定的平台协议

如果平台核心逻辑长期存在于 `prompt_v37_final_final.md`，平台将很难实现版本升级、多 Agent、历史兼容、数据分析、测试资产复用、企业治理、审计、API 化和自动评估。

HyperTest 必须拥有 Agent 之外的稳定领域协议。

---

## 4. 产品定位

HyperTest 同时具有三个层次的身份。

### 4.1 面向用户：AI Test Engineering Workbench

> **AI 原生测试开发工作台。**

用户提供 PRD、Git Repository、Branch / Commit 和 Test Environment，HyperTest 自动完成测试分析、风险识别、测试设计、测试用例、自动化实现、测试执行、失败诊断、问题发现和质量报告。

### 4.2 面向产品市场：Agent-native Autonomous Testing Platform

HyperTest 是 **Agent-native 自治测试平台**。它不绑定单一模型或单一 Agent，可接入 Codex、Claude Code、OpenCode、Pi 以及未来 Agent Harness。

### 4.3 面向架构：Autonomous Testing Control Plane

HyperTest 负责：Testing State、Testing Policy、Testing Knowledge、Testing Missions、Testing Evidence、Testing Governance、Testing Verdict。

Codex / Claude Code 负责：reason、search、read、edit、code、shell、debug、tool use。

---

## 5. HyperTest 不是什么

HyperTest 不应该成为另一个 Coding Agent，不重新实现 LLM Loop、Tool Calling Loop、Context Compaction、Shell Harness、Filesystem Harness 和 Generic Subagent Runtime。

HyperTest 也不应该只是 Codex Web UI。如果平台只是 Web → Prompt → Codex → Terminal Output，那么核心能力仍属于 Codex。

HyperTest 必须拥有自己的 Testing State 和 Testing Semantic Model。

---

## 6. 核心设计原则

### 6.1 Agent 可以消失，Testing State 不能消失

Codex Session 可以结束，Claude Code 可以被替换，模型可以升级，Agent Harness 可以代际变化，但 Requirement、Risk、Test Case、Execution、Evidence、Finding、Verdict 必须长期存在。

### 6.2 Agent 产生 Intelligence

理解需求、推断风险、发现边界、设计测试、分析根因、编写自动化代码属于 **Agent Intelligence**。

### 6.3 Runner 产生 Facts

Exit Code、HTTP 响应、JUnit、Prometheus 指标、DB State、Trace、Screenshot、Log 属于 **Execution Facts**。

### 6.4 HyperTest 产生 Decision

HyperTest 基于 Policy + State + Agent Intelligence + Execution Facts 形成 PASS、FAIL、BLOCKED、RISK ACCEPTED、RETEST REQUIRED、RELEASE READY、RELEASE BLOCKED 等判断。

> **Agent produces intelligence.**  
> **Runner produces facts.**  
> **HyperTest produces decisions.**

---

## 7. 总体架构

```text
┌────────────────────────────────────────────────────┐
│                   HyperTest Web                    │
│ Project / PRD / Repo / Runs / Cases / Findings    │
└──────────────────────┬─────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────┐
│           HyperTest Autonomous Testing CP          │
│ Test Knowledge Model                               │
│ Test Planner                                       │
│ Mission Compiler                                   │
│ Policy / BUGate                                    │
│ Verifier / Gate                                    │
│ Coverage Engine                                    │
│ State / History                                    │
└─────────────┬──────────────────────────┬────────────┘
              │                          │
              ▼                          ▼
       Agent Gateway                 Test Runner
              │                          │
   ┌──────────┼──────────┐               │
   ▼          ▼          ▼               ▼
 Codex     Claude      Pi/...       pytest / k6
                                   Playwright
                                   Frigate
                                   Docker/K8s
```

---

## 8. HyperTest 核心组件

HyperTest 第一性架构可以归纳为六个组件：

1. **Test Knowledge Model**：描述 Requirement / Risk / TestCase / Execution / Evidence / Finding / Verdict 等测试世界对象。
2. **Test Planner**：基于当前状态、Policy、Coverage Gap 和依赖验证可接受的测试动作，向 Harness 返回允许的范围、缺口与约束。
3. **Mission Compiler**：把 Testing Intent 编译成 Agent 可执行的标准 TestMission。
4. **Agent Gateway**：屏蔽 Codex / Claude Code / Pi / OpenCode 的差异，统一 AgentHarness。
5. **Test Runner**：执行正式、可复现、可审计的测试并产出 Evidence。
6. **Verifier / Gate**：验证 Agent Proposal 与执行事实，并形成阶段和发布 Verdict。

---

## 9. HyperTest 与 Codex / Claude Code 的关系

HyperTest 与 Agent 不是简单 Prompt 调用，而是：

```text
                    HyperTest
                        │
        ┌───────────────┼────────────────┐
        │               │                │
     Mission          Context           Tools
        │               │                │
        └──────────────►Agent◄────────────┘
                        │
                 Events / Result
                        │
                        ▼
                    HyperTest
```

HyperTest 定义 Mission 和验收标准；Agent 决定如何推理与完成工作。

ADR-013 的目标是在一个 TestRun 的持续原生会话内串行处理多个有类型的 Mission / Attempt。Harness 自驱思考和调用领域工具；平台执行范围、依赖、预算、权限与产物验收，不为每个阶段建立新会话，不接管 Provider 的推理循环。v0.3 的逐 Mission 最终结果调用和 bounded controller 保留为历史兼容基线；本分支的新 profile 已实现上述持续会话路径，旧 Run 不被回填或重解释。

---

## 10. Agent Harness Interface

HyperTest 定义统一 `AgentHarness` 抽象，目标适配 Codex CLI、Claude Code CLI、DeepSeek Harness 及其他 CLI / SDK。上层仅理解 `AgentSession`、`TestMission`、`AgentEvent`、`AgentResult`，Provider-specific 参数、事件与原生会话格式由 Adapter Normalize。当前已接入的 Codex 实现不能作为其他 Provider 已可运行的证明。

服务器模式延续平台任务 Worker 容器通过受限 UDS Host Harness Bridge 调用服务器宿主适配器。ADR-015 的本地模式由用户电脑上的受管 Connector 主动建立 WSS，平台通过该连接调度本机 Harness；源码与 Artifact 经独立 HTTPS 传输，不假设两端共享路径。Connector 独立于浏览器页面存活，无需用户电脑开放公网入站端口，平台继续沿用受控 VPN / 白名单访问边界。

ADR-015 的 Bridge / Connector 托管原生会话、进程、事件和中断，不持有数据库写权限，不代替 Verifier、Runner 或 Gate，也不提供通用远程 shell。原生认证与会话目录留在实际 Harness 节点。CLI / SDK 已登录认证、Git helper / SSH agent 或本地问题单适配器只有在本机进程实际可用时才可复用，浏览器登录不保证能使用。原 `PLATFORM_MANAGED` 路径创建 / 恢复专属会话，不接管任意已有聊天；ADR-016 另允许经可信宿主验证和显式绑定的当前本地 Agent 执行，不自动占用用户聊天。首次设备配对仍是独立、可到期/撤销/轮换的 HyperTest 授权。首版采用随机设备 bearer token：明文保存在节点受保护文件，平台只存哈希和凭据代次引用；项目的 Harness、source-acquisition 与 issue-executor 能力分别授权。它不要求把模型、Git、问题单 token 或 cookie 再复制到服务器、镜像或 Agent Context，也不扩大原有权限。

---

## 11. Test Mission Protocol

Test Mission Protocol 是 HyperTest 控制 Agent 的核心协议。Mission 至少包含 Mission ID、Mission Type、Objective、Target、Context References、Constraints、Acceptance Criteria、Expected Output Schema。

用户提交的是完整测试任务；Mission M-203 等内部契约为同一持续会话中的测试工作划定目标、依赖、输出和权限。Mission 完成关闭该工作单元，主会话在任务结束时统一收尾。

这是 HyperTest 从 Prompt Engineering 走向 **Protocol Engineering** 的关键一步。

---

## 12. Agent Result Protocol

Agent 的最终产出必须是 Machine-readable structured result。Markdown 总结可以保留，但只能作为 Human-readable Summary，不能替代 Canonical Domain State。

---

## 13. Proposal Model

Agent 不应直接修改 HyperTest Canonical State。

```text
Agent
   │
   ▼
Proposal
   │
   ▼
HyperTest Verifier
   │
   ├─ schema validation
   ├─ policy validation
   ├─ deduplication
   ├─ consistency check
   └─ permission check
   │
   ▼
Canonical State
```

原则：

> **Agent proposes. HyperTest commits.**

---

## 14. 运行中领域 MCP 与交互式入口

HyperTest 对受控任务主 Harness 提供运行中领域 MCP。读取工具包括 `get_requirement`、`get_risk`、`get_test_case`、`get_execution`、`get_evidence`、`get_coverage`；写工具采用 Proposal 语义，包括 `propose_requirement`、`propose_risk`、`propose_test_case`、`propose_implementation`、`report_finding`、`request_execution`。这些是任务内受绑定与执行授权约束的能力，不等于向用户交互式聊天开放同样权限。

持续会话目标还包括申请 / 完成有类型 Mission、提问、读取正式执行结果、请求 Gate、提交报告和请求 GitLab Issue。工具由平台验证并审计，按既定项目 / 责任人 / 权限策略执行外部操作；未知外部结果需要核对，不能盲目重复提单。本分支以九个固定工具实现这些能力：读取语义映射到分页 `get_state`，Proposal batch 经 `complete_mission` 提交，Gate 请求使用 `evaluate_gate`；完整名称和契约映射见 TMP §25.2。上述细粒度名称保留为领域语义，不代表另有同名端点。

ADR-015 的本地问题单操作仍由平台治理：先批准具体项目、责任人、Finding / Evidence 和操作意图，再委托持有本地凭据的受控适配器执行，平台核验真实问题单引用并审计。Agent 不能借已有 MCP 登录绕过这一流程。操作 ID 与执行方固定，超时或断线后的未知结果只查询对账，不重复创建，也不切换服务器/本地后端另开同一问题单。提单不自动确认 Finding 或改变 Verdict；其他问题单平台须单独适配与验收。

任务主 Harness 默认只能：

> **Read Facts, Propose Changes.**

### 14.1 交互式 Agent 接入（ADR-016 已实现，隔离与生产真实核心验收通过）

安装包由 MCP Server、客户端配置与 Skill 组成。首版“当前本地 Agent → stdio MCP → 受限本地 Connector → 新 typed HTTPS API”承担平台通信；不假设现有 Node WSS / UDS Bridge 已能代理这些新接口。原“平台 Worker → Connector WSS → 受管 Harness”继续服务 `PLATFORM_MANAGED`，而 `LOCAL + INTERACTIVE_MCP` 就由当前 Agent 执行智能工作，不经 Connector 另启模型或 Provider。

首版提供七个提交 / 读取工具：`hypertest_submit_task` / `hypertest_get_submission`、`hypertest_get_progress`、`hypertest_list_evidence` / `hypertest_read_evidence`、`hypertest_list_reports` / `hypertest_read_report`，以及 `hypertest_bind_execution` / `hypertest_get_execution` 的显式绑定与幂等查询。绑定后的本地 Agent 可在有效 Run / Mission / Attempt / epoch / claim 范围内复用九个 TMP 领域工具，完成分析、设计、实现、正式执行请求、诊断、受控协作和报告。未绑定客户端不能取得这些写能力；查询不会自动 bind / resume，人工回答、独立取消 / 恢复和设备授权仍沿用各自操作者入口。

提交使用已批准 Project、完整 SHA、PRD / configuration、Policy、环境、execution mode / driver 和节点；本地模式还引用已接受源码与既有节点能力。插件不自动采集 Git、上传 dirty 文件、配对设备或新增来源信任；MCP 安装和执行权限也不授予任意本地问题单操作。交互门面已在同一事务中提交回执、固定 Run/bootstrap 输入与选择、初始 `ADVANCE_RUN` Job 和审计，再确认受理；原有两个 POST 不因此获得原子能力。`LOCAL + INTERACTIVE_MCP` 的初始 Job 须等待显式绑定才获得执行准入，平台 coordinator 维护租约、领域编排和验证，不调第二个 Harness。

九个领域工具的请求先进入原 Run 的 typed tool inbox。API 只鉴权、校验并入账 / 查询，原 Job Worker 持唯一 claim 消费请求、执行领域服务和 Docker Runner，不另建业务调度循环。客户端先持久运输 key；响应丢失、排队或执行中只查询原请求，不自动 POST。运输成功返回原 TMP 业务结果，不能把业务拒绝变成接受；HTTP / MCP 断开不取消 Worker 已接受的正式执行。

请求以跨重连稳定的 `submission_key` 和输入摘要对账，不以单次 JSON-RPC ID 识别测试轮次。响应丢失时显示 UNKNOWN 并查询原 key；UNKNOWN 不是 Run 新状态，NOT_FOUND 也不能证明未创建，插件不自动再次 POST、换 key 或新建 Run。执行绑定也必须幂等、可查询，不以丢失回复为由接管另一个 owner。当前聊天可显式成为 primary Session，但须由可信宿主适配器证明真实身份，不能采信模型传入 chat ID；保留 `UNIQUE(provider, provider_session_id)`，首版一个真实执行会话只绑定一个 Run，可提交 / 读取其他 Run。新的执行 Run 需真实新上下文，不伪造 ID 或由 Connector 悄悄另启会话，也不上传原聊天或思维链。

新的 `InteractiveIntegrationGrant` 按项目分别授予提交 / 读取及显式 `run:execute` 权限，凭据留在 Connector 私有文件，与设备 token、节点能力、Bridge 管理权限和 operator 全局 key 分开。实际执行另需限定 Run / Binding / Session / epoch / Job claim / Mission / Attempt 的短期能力，不因项目有执行权就能任意写状态。平台仍以 Verifier 接受 Proposal、以可信 Runner 采集 Evidence、以 Gate 判定；本地 shell 测试不是正式事实，MCP 不扩大个人 shell / filesystem / 其他 MCP 权限。读取继续验证范围、归属、固定版本、hash 与分页，不读任意路径或 Provider 对话，报告保留历史结论。

短期能力固定其原 `device_grant_id`；即使同 node 取得轮换后的新设备凭据，旧短期能力也不能继续发起工作。当前宿主适配仅支持受控 Codex Desktop stdio 上下文，核验真实 native 身份、原生 metadata、Codex 进程、kernel 观察的 stdio peer 与固定源码；daemon 固定首个可信 peer PID 和出生时间。替换 stdio 进程须在原可信 native 上下文显式重启 daemon、按原身份对账后显式继续，不能自动创建新 Session、Job 或 grant。不具备这些能力的通用 MCP 宿主只支持提交 / 读取或 CLOUD；不上传聊天或思维链。安装与限制见[客户端说明](../INTERACTIVE_MCP_CLIENT.md)。

---

## 15. Testing Semantic Chain

HyperTest 最核心的领域模型：

```text
Requirement
     │
     ▼
    Risk
     │
     ▼
 Test Case
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

任何质量结论都应能够沿这条链正向或反向追溯。

---

## 16. Evidence Model

Evidence 是 HyperTest 与普通 AI Agent 最大的差异之一。Agent 自述不能成为正式证据。正式 Evidence 应来自可信执行通道，包括 Execution Metadata、Exit Code、JUnit、HTTP Request / Response、Logs、Metrics、Trace、Database State、Screenshot、Artifact、Git Diff、Environment Fingerprint 等。

Evidence 应至少具备 Source、Timestamp、Execution ID、Environment ID、Code Version、Artifact Hash，并最终形成 **Evidence Chain**。

---

## 17. Finding

Testing Failure 不等于 Product Bug。Finding 可分类为 PRODUCT_DEFECT、TEST_DEFECT、ENVIRONMENT_FAILURE、INFRA_FAILURE、FLAKY、DATA_ISSUE、EXPECTED_BEHAVIOR、REQUIREMENT_ISSUE、UNKNOWN。

Agent 可以完成初步 Root Cause Analysis，但正式 Finding 必须绑定 Evidence。

---

## 18. Verdict

Verdict 是 Testing Semantic Chain 的终点。Verdict 不应由 Agent 一句话决定，而应由 Policy + Coverage + Execution + Evidence + Finding 共同形成。

测试报告完成、Agent 会话关闭后，测试事实与质量治理仍可持续：操作者可以审计处置 Finding，并明确请求 HyperTest 根据固定策略和已有可信事实独立重评。重评不重开 Agent、不产生新的执行事实；新结论追加历史，旧报告保留生成时引用的结论。关闭 Finding 不等于修复通过，失败正式执行仍阻止发布；验证修复须在新轮次取得可信事实。具体准入与幂等规则见 ADR-014 及领域模型。

---

## 19. BUGate 与 HyperTest 的关系

BUGate 不再承担 Runtime，而定位为 **Testing Protocol / Policy Layer**。

```text
BUGate
   │
   ▼
Testing Protocol
   │
   ▼
HyperTest
   │
 compile
   ▼
Policy
Acceptance Criteria
Mission
Gate
```

BUGate 保持 Stateless；HyperTest 是 Stateful Runtime。

---

## 20. 典型端到端工作流

用户在 SUT 的 Project 中为一个 feat / MR 的完整 SHA 提交 PRD、配置、策略与测试环境，平台创建 TestRun。以下步骤在同一个主 Harness 会话内自驱、串行推进：

ADR-016 允许选择云端受管 Harness 或本地当前 Agent 执行该周期。当前 Agent 经显式绑定成为本地主会话后，下面的推理 / 实现步骤由它完成，平台维护 Mission、准入、可信执行与决策；不会另启替身模型，也不由插件重建通用 Agent Loop。

1. **Snapshot / Binding**：显式选择 Harness 模式和节点，准备并验证固定源码，冻结输入和实际执行环境，建立唯一任务 Worker 绑定与主 AgentSession。
2. **Requirement Analysis**：Harness 申请 `ANALYZE_REQUIREMENTS` Mission，形成 Proposal；HyperTest 验证后保存 Requirement。
3. **Risk Analysis**：读取已接受需求，申请 `ANALYZE_RISKS`，形成 Requirement → Risk。
4. **Test Design**：根据覆盖缺口申请 `DESIGN_TESTS`，形成 Risk → TestCase。
5. **Test Implementation**：申请 `IMPLEMENT_TESTS` 并提交测试代码 Proposal，经校验形成 TestCase → Implementation。
6. **Official Execution**：Harness 请求可信 Runner 在冻结环境执行，等待并读取 Execution → Evidence；自行 shell 探索不能替代这一事实通道。
7. **Failure Diagnosis / Collaboration**：需要时申请 `DIAGNOSE_FAILURE`，关联 Finding 和 Evidence，并按配置策略请求 GitLab Issue。任意阶段遇到关键歧义可提问，回答后恢复同一会话。
8. **Verification / Verdict**：平台验证产物、覆盖和证据；Harness 请求评估，Gate 根据正式状态形成可追溯结论。
9. **Report / Close**：Harness 提交引用输入、Evidence、Finding、Issue 与 Verdict 的报告，平台保存引用并收尾该任务的会话和绑定。报告文字不代替 Gate 结论。

---

## 21. HyperTest Runtime Loop

```text
创建冻结输入的 TestRun
  → 建立一个 RunExecutionBinding 与一个主 AgentSession
  → 原生 Harness 在同一会话中思考并串行调用领域工具
  → 平台逐次验证范围、依赖、权限、租约和 Proposal
  → 可信 Runner 执行并保存可校验事实
  → 人工回答后恢复原会话，或按预算 / 取消 / 失联停止
  → Gate 判定，保存报告与历史，关闭任务绑定
```

复杂的 Think / Tool / Observe / Edit / Retry Agent Loop 交由 Codex / Claude Code 自身完成。HyperTest 不重复实现。

平台通过 PostgreSQL 持久队列和容器化任务 Worker 托管测试任务，浏览器页面关闭不终止后台工作；本地模式仍依赖本机 Connector 与 Harness 在线。Planner 对可接受动作提供确定性守卫；Provider 的循环、上下文压缩和工具选择由 Harness 负责。队列、连接和绑定属于 Operational State，不拥有 Canonical Testing State。Worker 或 Connector 失联保留 Attempt / Execution 历史，不自动重放外部执行。任务间可以并发，任务内保持单 Worker、单主会话、串行测试周期。

本地断线或电脑休眠后，连接恢复只建立通道并对账，不自动恢复模型执行。授权 TTL 到期后本地 watchdog 停止新工作并中断受控调用；平台拒绝过期、撤权或旧 epoch 持有者的执行性提交。达到恢复阈值后须显式核对原节点、会话、工作区、固定源码和未决调用，隔离旧 owner，再接续原绑定；丢失身份需新 Run。平台可继续已接受且有独立有效授权的 Runner 执行，但不得因此启动第二次执行；先完成/收集该执行或受控取消，再进行需换 epoch / claim 的 Harness 恢复，不提前换代或绕过单活跃 Job。离线取消先撤权并保留待清理记录，重连不覆盖 WAITING_INPUT，也不重开终态。具体字段、事务和恢复授权由领域模型及 TMP 定义。

其中 ADR-013 的服务器持续会话路径已在本分支实现，并取得真实成功、失败诊断及两类问答证据，范围见 [ADR-013 验收记录](../ADR013_ACCEPTANCE.md)；ADR-015 的本地 Harness、跨网络传输与显式恢复已有独立实现和隔离回归，核心隔离真实周期 / 恢复已按 ADR-015 单独登记，生产已部署，线上核心周期已通过。v0.3 的历史路径仍由平台 bounded controller 逐步选择 Mission 并收取阶段最终结果；它不被描述为持续会话验收，也不被新 profile 改写。

ADR-016 中，云端执行不依赖聊天在线；当前本地 Agent / 宿主关闭则智能工作停止，Connector 不得替身继续，已经有效授权并持久接受的 Runner 请求可按有效原归属完成。平台保留状态、预算和事实，聊天退出本身不是业务取消。重连先查 submission、执行绑定和未知操作；只有原身份及租约 / scope 仍有效时，才可经显式继续准入推进。更换 stdio 进程需在原 native 上下文显式重启 transport daemon；这不会自动新建 native Session、Job、执行 grant 或重放工具。超期按 ADR-015 对账与 fencing 后显式恢复，原 native Session 不可恢复需关联新 Run，不自动换节点或另启模型。撤权只隔离本 Run 平台能力，不承诺终止用户整个聊天或个人原生工具。

---

## 22. Web 产品形态

HyperTest 的核心 UI 不应该是聊天框，而应该呈现 Requirements、Risks、Test Cases、Automation、Execution、Coverage、Findings、Evidence、Verdict。Agent Activity 只是其中一个辅助面板。

用户感受到的是“测试平台正在工作”，而不是“我正在和 AI 聊天”。

双模式工作台还应清楚说明所选设备与 Provider、连接状态、源码接收进度、问题单未知结果和显式恢复入口。节点在线不等于测试通过，重连不等于恢复执行；本地未在线时允许查看已有状态，但不能隐藏地改用服务器认证。本分支 Web / API 已提供模式 / 节点选择、设备配对 / 撤销、源码接收及恢复入口；真实浏览器与完整周期验收仍单独记录，不据此宣称生产已交付。

ADR-016 的 Web 执行步骤应提供“云端执行 / 本地执行”选择，并明确本地是否由当前 Agent 经 MCP 执行；不能把“本地”仅作为提交入口、实际再起另一个 Agent。平台应显示待绑定、原执行身份、租约与恢复状态，正式测试 Runner 的位置独立说明。MCP / typed API 与执行路径已有实现，新 Web 的 execution mode / driver 展示仍需独立交付和验收，不能由旧 ADR-015 的模式 / 节点界面推定已完成。

---

## 23. 推荐技术架构

ADR-013 的已实现基线为 Docker Compose 管理平台常驻服务、服务器宿主托管 Harness。ADR-015 在同一服务器控制平面下增加本机 Harness 选项，具体版本与实际部署状态由交付记录维护：

```text
Ingress:        nginx container
Frontend:       Next.js container
Backend:        FastAPI container
Task Worker:    HyperTest Worker container, one logical binding per task
Database:       PostgreSQL container + persistent volume
Queue:          PostgreSQL DurableJob + audit / transactional outbox
SERVER_HOST:    server UDS Host Harness Bridge + provider CLI / SDK + native sessions
LOCAL_CONNECTOR: user daemon + local CLI / SDK + native sessions (production deployed; online core E2E verified)
Transport:      local-originated WSS control + HTTPS bounded source transfer (production deployed; online core E2E verified)
Runner:         trusted controller + short-lived isolated Docker containers
Artifacts:      shared persistent platform store; object storage when required
Middleware:     containerized when justified by an actual dependency
```

已有数据库卷、Artifact、工作区、原生认证与受控访问边界需要在迁移中保全；容器删除不代表数据删除。各类常驻服务、宿主 Harness 和正式 Runner 分别配置容量与资源预算。现有开发 Compose 不是该生产目标的完整实现。

本地 Connector 不要求新增消息中间件；服务器 Worker、PostgreSQL、Verifier、Gate 与 Runner 继续承担原有职责。现有 TMP/profile 和服务器 UDS Bridge 不改变语义，本地传输以独立版本协商；两种模式都需保留数据、认证、SSH 与现行 VPN / 白名单边界。

ADR-016 已实现 stdio MCP → 常驻 Connector → 新 typed HTTPS API，以及当前本地 Agent 的可信绑定与短期执行授权。`CLOUD / LOCAL` 表示 Agent 执行位置，`PLATFORM_MANAGED / INTERACTIVE_MCP` 表示会话驱动；它们不改变 Runner 信任。API 将严格类型请求写入 PostgreSQL 运输 inbox，由原 Job Worker 执行九个 TMP 工具与可信 Runner；不新增数据库、消息中间件、独立业务调度队列或通用 Agent Loop，本地交互执行不使用上面的 WSS 派生另一主会话。此实现已部署生产，线上当前 Agent 核心周期已通过。

---

## 24. Workspace 模型

每个 TestRun 的主会话拥有独立、可恢复的托管工作副本，串行阶段共享任务上下文；正式 Runner 使用独立执行环境：

```text
/workspace
├── repo/
├── prd/
├── hypertest/
│   ├── mission.json
│   ├── requirements.json
│   ├── risks.json
│   └── cases.json
├── artifacts/
└── results/
```

主会话的工作副本在阶段完成和人工等待时保留，任务终止后按策略收尾；重启仅能恢复已记录的绑定、原生会话和工作区。所选 Harness 只访问任务受控副本及其自身授权目录，Canonical Artifact Store 由平台维护。运行目录、原始 Provider 对话和认证内容不成为 Canonical Testing State。

本地模式不把用户目录挂到服务器。受控 Git 采集器从批准 origin 获取完整 SHA，只上传该提交验证所需的 tracked Git 对象和 manifest，不包含 dirty / untracked 文件、凭据或无关 `.env`；tracked 秘密应拒绝传输，不能删改后冒称原 SHA。平台独立重算 commit / tree / blob 哈希、路径与 mode，包 SHA-256 只证明传输完整性。项目可显式信任与 Agent 隔离的本地 source-acquisition adapter，并验证其设备认证 acquisition receipt；也可采用平台独立读取 origin 或既有可信 commit 约束。配对本身不授予来源采集角色；缺少可信来源路径时拒绝接收。这样私有 Git 授权可留本机，同时平台明确记录来源信任依据。

上传验收前只属于临时接收状态；平台验证后固定不可变 SourceSnapshot，服务器 Runner 再次验证并在独立环境执行。测试代码继续通过 Proposal / Verifier 进入 Artifact Store，本地探索不成为正式 Evidence。平台 Worker、Bridge / Connector 和 Runner 的部署生命周期与持久会话身份独立；ADR-015 的跨机器定位、源码传输与恢复实现已落地；私有 Git 的本地授权复用和 HTTPS 平台源码接受已取得独立结果，正式 Runner / 质量闭环与完整恢复矩阵仍单独验收。

---

## 25. MVP 范围

第一阶段目标是打通：

```text
PRD + Git
↓
Requirement
↓
Risk
↓
Case
↓
Test Code
↓
Execution
↓
Evidence
↓
Report / Verdict
```

MVP 建议只支持一个 Agent Harness（Codex）、API / Backend Functional Test、pytest、Docker / existing SIT，以及基础 Requirement / Risk / Case / Finding / Evidence / Verdict 模型。

现有 MVP 能力与 ADR-013 目标须分别验收：容器部署、宿主 Bridge、整个 Run 的持续会话与运行中领域工具已有实现；生产迁移、数据 / 认证 / 访问边界保全及真实正反链路已完成[独立验收](../ADR013_PRODUCTION_DEPLOYMENT.md)。受控 GitLab 集成已有回归，实际提单仍需授权配置与真实服务证据。Claude Code / DeepSeek 等适配器也需各自的真实运行证据，不能由 Codex 结果代替。

ADR-015 双模式已实现并部署生产，其隔离验收与本次生产记录独立于上述 ADR-013 历史。隔离核心链已核验本机授权复用、私有源码与来源 receipt、可信 Runner、获准问题单创建及原会话恢复；UNKNOWN 去重和服务器 UDS 兼容另有回归。严格外部 TLS 已确认，线上本地 Connector 核心周期已通过，扩展休眠 / 离线取消 / WAITING_INPUT / 原会话丢失及外部 UNKNOWN 故障矩阵未逐项完成。文档、mock 和能力声明不能代替这些证据。见[生产部署记录](../ADR015_PRODUCTION_DEPLOYMENT.md)。

ADR-016 的安装包、typed API、执行绑定 / 短期能力、原子提交门面和原 Worker 工具 inbox 已实现。当前真实 Codex Agent 经官方 MCP SDK 通路完成四个 Mission 的 Proposal、四份 Implementation、真实 Docker live HTTP 27 / 27 和五份 VERIFIED Runner Evidence，形成 `RELEASE_READY` 与已接受报告，Job / Binding 正常收口；证据和两页报告均经 MCP 读取并核验摘要与字节数。没有另启模型，详见[隔离验收记录](../ADR016_ACCEPTANCE.md)及[机器可读观察](../evidence/adr016-20261020.json)。

此前隔离验收中，同一 Run / native / workspace 的过期恢复保留历史并递增 epoch，恢复实现的最终版本另经独立集成回归验证，具体版本与时序边界以验收记录为准。该隔离周期的 stdio / daemon 重启与原 key 查询发生在 Runner 完成后，查回同一 Execution，不能据此宣称当前 Agent 的运行中断线已经实测。该能力已部署生产，线上当前 Agent 核心周期已通过，另见[独立生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)；其他宿主、私有 Git / 问题单写入、扩展真实设备故障及新 Web 展示仍独立验收。来源 / 问题单权限和正式 Runner 信任保持原边界，无宿主能力时拒绝冒称本地执行，ADR-015 历史验收不替代这些新结果。

第一阶段不做复杂多 Agent Blackboard、自研 LLM Agent Loop、复杂 Workflow DSL、跨公司通用测试 Ontology、完全无人值守 Release。

---

## 26. 第二阶段

完成 ADR-015 已实现的服务器/本机 Harness 共存、本地认证复用、受控源码传输、问题单适配与断线恢复的独立真实验收及生产部署评审；再逐步增加 Claude Code Adapter、Multiple Harness Selection、Playwright、Performance Testing、Kubernetes Runner、Coverage Engine、Evidence Graph、Finding Classification、Historical Comparison、Regression Selection、Test Asset Reuse。

---

## 27. 长期阶段

长期目标是 **Autonomous Testing System**，逐渐支持需求变化检测、Impact Analysis、自动回归范围选择、自主实验、Failure Hypothesis、Dynamic Test Generation、Test Coverage Convergence、Agent Collaboration、Cross-version Learning、Cross-project Testing Knowledge、Continuous Quality Evaluation。

Blackboard / Event-driven Collaboration / Specialized Testing Agents 仅是长期实验方向。ADR-013 的任务执行模型明确保持单 Worker、单主会话和任务内串行；改变为任务内多个平台 Worker 协作需要新的 ADR，不能把它作为当前目标的默认扩展方式。

---

## 28. 为什么暂时不自研 Agent

Codex / Claude Code 等 Agent Harness 已经提供 Model Interaction、Agent Loop、Tool Use、Shell、Filesystem、Code Editing、Context Management、Retry、Session、Subagent。

HyperTest 如果重新实现这一层，会增加开发与长期维护成本，却没有形成测试领域核心竞争优势。

正确策略是：

> **复用最先进的通用 Agent，专注构建最先进的 Testing Runtime。**

只有未来证明通用 Agent Loop 无法满足 Autonomous Testing 的特殊执行模型时，才开发 `HyperTest Native Harness`，并且它仍然只是 `AgentHarness` 的一个实现。

---

## 29. Agent Orchestration 的真正含义

HyperTest 的 Agent Orchestration 不微管理 Agent reasoning。它真正编排的是 Testing Mission：Analyze Requirement、Analyze Risk、Design Tests、Implement Tests、Diagnose Failure、Investigate Finding 等。

在 ADR-013 中，Harness 在同一持续会话中自驱申请和完成这些有类型的工作，平台对其输入、依赖、权限、输出、预算和事实负责。Mission / Attempt 保持审计边界，但不意味着换一个 Worker 或新开原生会话。平台不再把逐 Mission 重建会话的旧实现作为目标工作流。

> **HyperTest orchestrates testing work, not model reasoning.**

---

## 30. 核心资产

随着使用时间增长，HyperTest 最有价值的数据不是 Agent Conversation，而是：

```text
Testing State
Testing Policy
Testing Knowledge
Testing Evidence
Testing History
```

这些资产会逐渐支持历史缺陷模式、风险预测、回归测试选择、Case 复用、测试策略学习、版本质量趋势和项目质量画像，形成长期 Data Flywheel。

---

## 31. 产品壁垒

即使未来 Codex 和 Claude Code 强大到“输入 Repo 就能完成大量测试工作”，企业仍然需要知道：应该覆盖什么、为什么覆盖、哪些 Requirement 被验证、哪些 Risk 被接受、测试在哪里执行、Evidence 是什么、失败是否可靠、历史如何变化、为什么允许发布。

Coding Agent 负责 **完成工作**；HyperTest 负责 **定义、管理、证明和治理工作**。

---

## 32. 竞争边界

HyperTest 不与 Codex、Claude Code、OpenCode、Pi 竞争。它们属于 General-purpose Agent Harness。

```text
General Agent Capability
          │
          ▼
       HyperTest
          │
          ▼
Software Testing Domain
```

> **Coding Agent 越强，HyperTest 越强。**

---

## 33. 对外产品叙事

- 英文定位：**Agent-native Autonomous Testing Platform**
- 架构定位：**Autonomous Testing Control Plane**
- 用户产品：**AI Test Engineering Workbench**

---

## 34. 推荐宣传语

> **From Requirements to Evidence.**

中文：

> **从需求，到可信的质量结论。**

业务化表达：

> **把 PRD 和代码交给 HyperTest，自动完成从测试分析到可信质量结论的全过程。**

HyperTest One 的产品 slogan：

> **One Input. One Mission. One Complete Test Cycle.**

---

## 35. 对技术社区的介绍

> HyperTest is an agent-native autonomous testing platform that turns general-purpose coding agents such as Codex and Claude Code into governed testing workers.

中文：

> HyperTest 是一个 Agent-native 自治测试平台，将 Codex、Claude Code 等通用 Coding Agent 转化为受测试策略、状态、证据和质量门禁约束的 Testing Worker。

---

## 36. 对企业客户的介绍

> HyperTest 是从需求到质量结论的自治测试平台。输入 PRD、代码仓库和测试环境，平台自动完成需求分析、风险识别、测试设计、自动化实现、真实环境执行、失败诊断和质量评估，并保留完整的 Requirement → Case → Evidence → Finding 可追溯链路。

---

## 37. 核心架构原则总结

- **Agent 可以替换，Testing State 不可丢失。**
- **Agent 可以推理，但不能自证。**
- **正式测试事实必须由可信 Runner 产生。**
- **Agent 提议，HyperTest 验证并提交。**
- **BUGate 定义 Protocol，HyperTest 执行 Protocol。**
- **HyperTest 编排 Testing Mission，而不是微管理 Agent reasoning。**
- **一个 SUT 一个 Project；一个确定变更版本的测试任务绑定一个逻辑 Worker 和一个持续主会话。**
- **Harness 自驱任务内串行工作；平台管理任务间并发、状态、证据与决策。**
- **Harness 可在服务器或已配对本机运行；认证留节点，模式与会话不因断线静默替换。**
- **源码来源与内容、外部问题单结果均须受控核验；本地授权不赋予 Canonical 写权或 Runner 信任。**
- **本地交互式 Agent 可显式成为任务执行者；MCP 连接平台，Verifier / Runner / Gate 仍拥有状态、事实与决策。**
- **通用 Agent 越强，HyperTest 应该越强，而不是受到威胁。**

---

## 38. 最终定义

HyperTest 最终不是 Test Agent、Codex Wrapper 或 AI Chat + Test Platform。

HyperTest 是：

> **面向 Agent 时代的软件自治测试基础设施。**

它位于通用智能 Agent 与真实软件质量体系之间。其核心职责不是创造另一个会写测试的 AI，而是建立一个能够让智能 Agent知道应该测试什么、为什么测试、做到什么程度，能够真实执行测试、留下可信证据、判断测试是否充分、沉淀长期测试知识并最终形成可靠质量结论的软件测试控制平面。

因此 HyperTest 的最终公式是：

> **HyperTest = Test Intelligence + Test Governance + Test Execution + Agent Orchestration**

它最重要的长期资产是：

> **Testing State + Evidence Graph + Testing Knowledge**

最终愿景：

> **让软件测试从自动化执行，迈向由 Agent 驱动、由 Evidence 证明、由 Policy 治理的 Autonomous Testing。**
