# HyperTest 白皮书

**版本：v1.0 Draft**  
**定位：Agent-native Autonomous Testing Platform**  
**架构角色：Autonomous Testing Control Plane**

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
2. **Test Planner**：基于当前状态、Policy、Coverage Gap 和历史，回答“下一步应该做什么”。
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

---

## 10. Agent Harness Interface

HyperTest 定义统一 `AgentHarness` 抽象，具体实现包括 `CodexAdapter`、`ClaudeCodeAdapter`、`OpenCodeAdapter`、`PiAdapter`。上层仅理解 `AgentSession`、`TestMission`、`AgentEvent`、`AgentResult`，Provider-specific CLI 参数、事件与 Session 格式由 Adapter Normalize。

---

## 11. Test Mission Protocol

Test Mission Protocol 是 HyperTest 控制 Agent 的核心协议。Mission 至少包含 Mission ID、Mission Type、Objective、Target、Context References、Constraints、Acceptance Criteria、Expected Output Schema。

Agent 不再被要求“帮我搞定测试”，而是“完成 Mission M-203”。

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

## 14. HyperTest MCP

HyperTest 应对 Agent 提供领域 MCP Server。读取工具包括 `get_requirement`、`get_risk`、`get_test_case`、`get_execution`、`get_evidence`、`get_coverage`；写工具采用 Proposal 语义，包括 `propose_requirement`、`propose_risk`、`propose_test_case`、`propose_implementation`、`report_finding`、`request_execution`。

Agent 默认只能：

> **Read Facts, Propose Changes.**

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

用户输入 PRD、Git Repository、Branch / Commit、Test Environment 后，HyperTest 创建 TestRun，并依次执行：

1. **Snapshot**：固定 PRD Hash、Repo Commit、Environment Fingerprint。
2. **Requirement Analysis**：创建 `ANALYZE_REQUIREMENTS` Mission，Agent 形成 Requirement Proposal，HyperTest 验证并落库。
3. **Risk Analysis**：基于 Requirement 创建 `ANALYZE_RISKS` Mission，形成 Requirement → Risk。
4. **Test Design**：基于 Coverage Gap 创建 `DESIGN_TESTS` Mission，形成 Risk → TestCase。
5. **Test Implementation**：创建 `IMPLEMENT_TESTS` Mission，Agent 生成测试代码，形成 TestCase → Implementation。
6. **Official Execution**：HyperTest Runner 在明确环境正式执行，产生 Execution → Evidence。
7. **Failure Diagnosis**：失败后创建 `DIAGNOSE_FAILURE` Mission，Agent 基于代码、日志、指标和 Evidence 形成 Finding Proposal。
8. **Verification**：Verifier 检查 Evidence 是否充分、Finding 是否可复现、Coverage 是否充分。
9. **Verdict**：Gate 形成 RELEASE_READY 或 RELEASE_BLOCKED 等最终结论。

---

## 21. HyperTest Runtime Loop

```python
while not run.finished:
    state = load_test_state()
    mission = planner.next(state)

    if mission.requires_agent:
        result = agent_gateway.execute(mission)
        proposal = verifier.validate(result)
        state.apply(proposal)

    if mission.requires_execution:
        evidence = runner.execute(mission)
        state.apply(evidence)

    verdict = gate.evaluate(state)
    persist(state, verdict)
```

复杂的 Think / Tool / Observe / Edit / Retry Agent Loop 交由 Codex / Claude Code 自身完成。HyperTest 不重复实现。

---

## 22. Web 产品形态

HyperTest 的核心 UI 不应该是聊天框，而应该呈现 Requirements、Risks、Test Cases、Automation、Execution、Coverage、Findings、Evidence、Verdict。Agent Activity 只是其中一个辅助面板。

用户感受到的是“测试平台正在工作”，而不是“我正在和 AI 聊天”。

---

## 23. 推荐技术架构

第一阶段建议：

```text
Frontend:       Next.js / Ant Design / TanStack Query
Backend:        FastAPI
Database:       PostgreSQL
Agent Gateway:  Node.js / TypeScript
Agent:          Codex SDK / Claude Agent SDK
Queue:          Redis / PostgreSQL Queue
Runner:         Docker
Future Runner:  Kubernetes Job
Artifacts:      S3 / MinIO
Streaming:      SSE / WebSocket
Observability:  Prometheus / Grafana / Loki
```

---

## 24. Workspace 模型

每个 Mission 或 TestRun 拥有隔离工作区：

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

长期可迁移到 Kubernetes Job。Control Plane 长期运行，Agent / Runner Worker 短生命周期。

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

第一阶段不做复杂多 Agent Blackboard、自研 LLM Agent Loop、复杂 Workflow DSL、跨公司通用测试 Ontology、完全无人值守 Release。

---

## 26. 第二阶段

逐步增加 Claude Code Adapter、Multiple Harness Selection、Playwright、Performance Testing、Kubernetes Runner、Coverage Engine、Evidence Graph、Finding Classification、Historical Comparison、Regression Selection、Test Asset Reuse。

---

## 27. 长期阶段

长期目标是 **Autonomous Testing System**，逐渐支持需求变化检测、Impact Analysis、自动回归范围选择、自主实验、Failure Hypothesis、Dynamic Test Generation、Test Coverage Convergence、Agent Collaboration、Cross-version Learning、Cross-project Testing Knowledge、Continuous Quality Evaluation。

Blackboard / Event-driven Collaboration / Specialized Testing Agents 可以作为长期实验方向，但不应成为当前架构前提。

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
