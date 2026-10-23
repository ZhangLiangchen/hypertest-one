# HyperTest 白皮书

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](../LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](../local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。


**版本：v1.8（Cloud 官方 Python SDK；Local Hooks + MCP 协调器及统一发行 / 安装设计）**
**本次修订：2026-10-23，Asia/Singapore；云端部分实现、默认关闭、尚未更新测试服务器常驻Cloud服务。source-r23新独立Task已固定读回v20 COMPLETED / reported PASS，ANALYSIS与DESIGN均直接引用当前child原件；source-r24只读验收器对同v20严格PASS，独立只读重放8项与原件 / 实际文件 / host日志关联通过。旧source-r22 v17仍保留DESIGN直接引用NON_PASS，原RECOVERY / HELD历史不变；SSH固定诊断默认关闭，source30 Worker的r8 canonical专项PASS，source31对同v19固定快照strict重评PASS；旧source30 NON_PASS保留（不是新的current GET，精确证据见实现状态），故障矩阵与真实staging未验收；Claude占位，CI / 一般远端shell和生产未准入。source-r21所选535通过 / 1跳过、source-r22针对性169、source-r23所选201、source-r24所选231分别登记于[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)，不作为同轮全量结果；自动Hooks / 统一安装包的独立状态不由此更改。**
**产品职责修订：2026-10-20，依据项目负责人明确的功能分层**
**定位：Agent-native Autonomous Testing Platform**
**架构角色：Autonomous Testing Control Plane**

### 两种产品模式：Cloud 云端模式与 Local 本地会话同步模式

HyperTest One 面向两种产品模式：**Cloud 的项目创建、任务创建与任务执行都在云端完成；Local 将本地 Agent 会话任务、状态和正式测试产物同步到 HyperTest One。** Local 当前可用入口是 [ADR-018](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 的 Codex MCP 同步；已接受 [ADR-020](../architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 的改进设计：Hooks 自动触发、MCP 显式提交与查询，共用一个本地同步协调器和现有私有客户端。Cloud 继续采用 [ADR-019](../architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md) 的官方 Python SDK 设计。

| 模式 | 任务与执行职责 | 状态 |
| --- | --- | --- |
| Cloud 云端模式（ADR-019，`cloud-harness-task/v1alpha1`） | 云端 Web / API 创建或复用 Project、配置资源并创建 CloudTask；云端 Python Worker 通过官方 Harness SDK 驱动 DeepSeek harness，自行参与或委派 Codex / Claude Code，调用项目原有框架 / CI | **部分实现 / 默认关闭 / 尚未更新测试服务器常驻Cloud服务**；HTTPS Git / 工作区fixture已有source-r18正式reported PASS及Codex原生推理 / 文本贡献，新source-r23 Task的直接双原件与六步已由source-r24严格验收并独立重放8项；旧v17直接引用NON_PASS / HELD保留；r8固定SSH专项PASS，source31对同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与staging待验收；Claude占位、CI不支持，P0未全退出；[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md) / [计划](../CLOUD_TEST_IMPLEMENTATION_PLAN.md)分别记录 |
| Local 本地会话同步模式（ADR-018 / ADR-020） | 一个真实本地 Agent 父会话对应一个 SessionTask，使用已有授权 Project；Hooks 提供自动触发时机，MCP 提供显式操作，统一协调器保存版本化任务、计划、用例、原始报告与 reported result | Codex MCP 同步保留；协调器、自动触发与 Claude Code / DeepSeek harness 适配、统一发行与安装均 **NOT IMPLEMENTED**，按[本地实施计划](../LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)分别验收 |

**一个 SUT 对应一个长期 Project，同一 Project 可同时包含 CloudTask 和 SessionTask。** 项目不按模式拆分，也没有项目级二选一模式开关。项目内统一任务列表拟默认并列显示全部任务，提供 Cloud / Local 来源标签和模式筛选，详情保留各自操作与结果语义；这一共存视图随云端能力实施，不能据本文认定已上线。模式由任务类型派生且创建后不可变，不能把历史任务跨模式重标；项目共享不合并任务身份、写入权限或执行授权。

Local 表示会话来源与协作方式，不证明测试发生在用户电脑：本地 Agent 仍可调用已获授权的远端环境或 CI。Local 不在本机创建另一套独立 Project，不自动接管本地 Agent，不要求配置云端仓库凭据或环境密钥；本地测试权限仍由实际工具链提供。

Hooks 是 Local 的触发机制，不是第三种产品模式，也不产生新的服务端任务类型。关闭 Hooks 或云端执行，均不应影响现有 Codex MCP 同步、原 key 对账和历史读取。设计接受不安装全局 Hooks、不修改现有默认同步技能；未来经版本化 adapter 的受控启用才提供自动同步。

[ADR-021](../architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) 将本地可靠同步设计提炼为 **TaskSyncCore**（共享库与 Cloud 接入已有增量源码，完整验收未完成）：两种模式复用正式资产清单、语义变化判定、请求冻结、幂等对账与接受版本读回能力。Local 由 LocalSyncCoordinator / LocalSyncAdapter 接入，Cloud 由 Worker 内的 CloudTaskReporter / CloudSyncAdapter 接入；共享的是库和同步语义，各自保留任务身份、权限、writer 与生命周期。

**跨会话项目经验方向：** 用户已选择在独立云主机部署 PowerContext，使不同 Agent / 会话可复用经验。[ADR-022](../architecture/ADR-022_PROJECT_MEMORY_WITH_POWERCONTEXT.md) 提议通过 HyperTest Memory Gateway 让 Cloud / Local 在同一授权 Project 内检索、贡献并经人工确认发布经验；**Gateway 与产品集成为 Proposed / NOT IMPLEMENTED**。独立服务部署与真实检索另见[服务运行记录](../POWERCONTEXT_SERVICE.md)，不能据服务可用认定已接入 HyperTest。

### Local 的统一发行与一键安装

MCP、私有客户端 / journal、同步协调器、三宿主适配与触发模板、安装 / doctor / 升级 / 卸载工具和最小使用资产，应作为**一个 HyperTest Local release** 交付。目标安装宿主为 Claude Code、Codex、DeepSeek harness；用户从项目页取得固定版本、非秘密的项目安装命令，交给当前 Agent 完成校验、隔离安装、所选宿主配置合并和项目授权检查。安装不得运行 SUT、启动新模型任务或上传历史聊天；缺少授权时明确等待安全授权，不自动签发 Operator key 或扩大权限。

统一包固定其 TaskSyncCore 版本；Cloud 镜像可复用兼容版本的共享库，无需安装本地终端 bootstrap、宿主配置或完整 Local 包，也不以三宿主安装发行完成为云端交付前提。

统一包不等于三宿主已经支持：MCP、真实父会话映射、自动事件和首个实际 ACK / 完整读回分别验收，未通过能力不得显示 READY 或静默降级。DeepSeek 本地父会话与云端指挥官保持不同任务身份；自动事件按实际 Harness 版本确认。安装配置就绪不等于同步成功，更不等于测试 PASS。

固定发行应校验 bootstrap 与实际 payload，保留其他 MCP / Hooks、私有身份和未知 journal；升级、回退、卸载均不得丢弃未决写或用户会话 / 项目目录。具体安装信任、兼容矩阵与尚不可执行的一键命令契约见[统一发行与安装设计](../LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。现有 `mcp-v0.1.0` 保留原历史，不改称包含 Hooks 的新发行；本轮不创建 release 或实际安装。

云端 one-shot 指用户提供完整输入并下发一次任务，由 Harness 推进分析、设计、代码和执行闭环；遇到授权、输入或环境缺口仍应等待或受阻。任务完成与测试通过分别记录，平台不承诺一次模型调用或全程无需人工介入。

### 保留能力：Codex 测试任务与产物管理（ADR-018）

**一个 Codex 会话对应一个测试任务。Codex 将生成的任务、计划、用例、原始测试报告及 reported result 同步到 HyperTest One；HyperTest 本身不承担测试执行。**
该同步入口提供持久管理与查询，不以执行材料准入、平台 Runner、独立 CI 证明或 Gate 为保存报告的前提。平台显示提交者报告的 PASS/FAIL 等及其来源；它们不自动成为正式发布判定，也不因没有平台执行而被强制改成 UNKNOWN。
[ADR-018](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md)明确共享 Project 的 SessionTask、用例/报告修订、幂等同步与旧版本保护；优先于下文对当前新入口的宽泛治理要求。ADR-017 与旧受管 Harness/Runner 的实现和历史结论继续保留，不作为本阶段同步的依赖。生产部署不包含在默认开发范围中。

> **HyperTest One 管理测试项目、下发测试任务、记录测试结论。**
> **Agent 执行测试分析、测试设计、测试实现，并调用被测对象已有的测试框架执行测试。**

HyperTest 持久管理计划、用例、执行记录、证据、缺陷与结论，把分散在不同 Agent
会话中的质量保障工作串联起来。测试框架、测试环境与既有 CI 属于被测项目的工具链；
HyperTest 不承担测试执行框架或通用执行引擎的产品职责。

### v1.5 最小迁移决定与实施边界

[ADR-017](../architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md)保留历史 `native-framework-intake/v1alpha1` 的材料治理与顺序贡献者交接。该兼容 profile 不增加平台执行引擎，不自动提升材料可信度；当前 Codex 任务、用例及报告管理按 ADR-018 同步，私有执行与验收原件不随产品源码分发。

下面记录 v1.4 于 2026-10-20 修订时的历史边界；其中“尚未实现 / 后续 ADR”是该时点的状态，不抹去 ADR-017 新切片，也不把目标能力全部宣称已交付。

v1.4 当轮只修正白皮书的产品方向和架构职责，并提供[新 Mac 开发交接 Prompt](../handoffs/MAC_NATIVE_TEST_FRAMEWORK_HANDOFF_20261020.md)。
**v1.4 修订时原生测试框架接入、跨会话接续及新的执行结果契约尚未实现。** ADR-017 随后定义的最小材料接入与贡献者交接不等于完整可信执行 / 原生会话接力已完成。
[技术架构](../architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)、[TMP](../protocol/TEST_MISSION_PROTOCOL.md)、
[领域模型](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)、`AGENTS.md`、代码及 schema
仍包含旧 Runner / 单主会话约束。后续核心变更必须先用新的 ADR 明确替代范围，并在同一变更中
同步这些规范、兼容和验收方案；不能只依据白皮书修改数据库约束、扩大权限或重解释旧协议。

现有 ADR-013 / ADR-015 / ADR-016 及其生产结果继续作为历史事实保留：

| 已记录实现 | 历史证据与实际边界 |
| --- | --- |
| 服务器与本地 Connector 两种受管 Harness | [ADR-013 生产记录](../ADR013_PRODUCTION_DEPLOYMENT.md)、[ADR-015 生产记录](../ADR015_PRODUCTION_DEPLOYMENT.md)；既有授权、数据、会话和访问边界需要保全 |
| 当前 Agent 的 MCP 接入 | [ADR-016](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)及[生产记录](../ADR016_PRODUCTION_DEPLOYMENT.md)；本地 Agent 推进任务，正式测试仍走平台 Docker / pytest，属于待纠偏的实现 |
| 已发布 MCP 与 Web 安装指引 | [安装交付记录](../MCP_INSTALLATION_DELIVERY_20261020.md)；固定发行 `mcp-v0.1.0`，PR #19 源码 `980f27a`，安装不等于任意 Agent 原生框架接入已完成 |
| 最近已记录后端与验收 | API / Worker `c7cd43ad6346d8ce6c85564f7838afbb017f2da4`、schema `0020_interactive_tool_inbox`；967 passed / 21 skipped，生产33项 HTTP 测试与五份 Evidence 属于该旧架构周期 |

以上是交付记录中的版本快照，不是对当前服务器或新 Mac 的即时巡检。隔离27项周期、生产33项
周期、MCP 安装验证及真实私有 SUT 验收各自独立，不相互替代。未来迁移保留原 Execution、
Evidence、Verdict、报告和审计，不删除或回填历史来宣称符合新架构。

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

### 1.1 实际使用单位与工作归属

- 一个 SUT（被测系统）对应一个长期 Project；同一系统的 feat / MR、CloudTask 与本地 SessionTask 在同一项目内组织。Project 是系统身份，仓库 URL 或任务模式不替代它，不为 Cloud / Local 分建项目。
- 一次测试活动使用所选 profile 的任务身份：ADR-018 为 SessionTask，ADR-019 为 CloudTask / CloudAttempt，旧执行路径保留 TestRun。需求、源码版本、测试范围、Policy 及实际执行环境应有明确、可追溯的版本身份；云端同冻结输入显式复测追加 CloudAttempt，改变输入建立关联新 CloudTask，不覆盖旧结论。
- HyperTest 管理测试计划、用例及覆盖关系，发布目标、范围、约束和验收要求，记录任务进度、执行出处与结论。Agent 完成分析、设计、实现、框架调用和失败诊断。
- 测试代码优先留在被测项目自己的测试资产中，遵守该项目已有框架、fixtures、配置与启动方式。平台记录实现引用和版本，不把所有项目统一成平台指定的测试文件或语言。
- 同一 Agent 会话可以连续完成任务，也可以由不同会话经过明确交接依次贡献。任务和测试资产的连续性由平台状态保障，原生聊天会话不再是产品层面的唯一连续性载体。
- 接力必须关联原任务、输入、已接受产物、未决操作及贡献者，明确当前写入责任，隔离已失效授权。ADR-017 新 native profile 以私有 writer capability 与 generation 支持显式顺序贡献者交接；现有受管 Run 的单主会话约束和真实 Provider 身份保持原语义，不允许并发多写者。
- 关键歧义、权限与外部副作用通过明确授权和持久问答处理。缺陷可关联项目既有问题单流程，提单不自动成为缺陷确认或质量结论。

产品 Cloud / Local 表示上述两种协作流程；Agent、项目测试框架及被测环境的实际位置另行记录。
Local Agent 可在拥有项目工具链的 Mac 上调用原生测试入口，也可使用已授权的远端环境或既有 CI；
模式标签不构成执行地点或来源认证证明。认证留在实际使用方，连通平台不扩大 Git、问题单或执行权限。

ADR-015 / ADR-016 历史 `CLOUD / LOCAL` 执行位置选择与本节产品模式分属不同 profile；旧模式测试仍走服务器 Runner，该旧含义及
`harness_mode` / `execution_driver` 组合继续解释已有请求和历史，不能冒称已符合上述新目标。
平台登记测试活动不应普遍要求上传全量源码或重建项目工作区；需要的版本、源码和产物验证范围
由实际任务与后续证据契约确定。

### 1.2 云端测试任务的六步流程（ADR-019，部分实现）

本流程的项目创建、任务创建与执行调度均经云端 Web / API / Worker 完成；已有同一 SUT 的 Project 直接复用，可与其 Local 任务共存。

| 步骤 | 用户输入与平台职责 | 持久交付 |
| --- | --- | --- |
| 1. 创建或复用项目并配置资源 | 在云端 Web 创建或选择已有 Project，手动添加被测对象 Git 仓库、测试框架 Git 仓库、仓库 token，以及测试环境私钥或 SSH 访问方式；两个仓库允许相同。资源可保存复用，分别关联项目授权 | 共享 Project、仓库 / 环境元数据、加密凭据引用及审计；秘密不进入普通配置和报告 |
| 2. 创建测试任务 | 选择被测分支、feat、MR 或 SHA，提供 PRD、测试目标、基本流程；确定测试框架版本、环境和允许的操作 / 时间 / 费用范围。`feat/*` 可按分支解析，feature 需求标签须关联可解析源码引用 | 独立 CloudTask 草稿及版本；不创建伪造的 SessionTask |
| 3. 下发任务 | Worker 侧解析 / 预检访问与环境连通性，接受执行 dispatch 前冻结 SUT 与框架精确 SHA、MR base/head 及实际测试的 head 或 merge SHA、PRD 版本、环境引用；API 引用已解析结果入队，准备独立工作区和执行尝试 | 不可变输入快照、CloudAttempt、预检记录；每轮观察实际部署身份，无法核实时明确 UNKNOWN / 缺口，禁止把仓库 SHA 当作部署证明 |
| 4. 接取与分工 | Python Worker 通过官方 `deepseek-harness-sdk` 启动 `dsh --profile sdk`、提交任务并收集事件；DeepSeek 自行参与或委派 Codex / Claude Code | Attempt 内 Harness 身份、委派关联、进度与操作记录；主指挥官统一回写平台 |
| 5. 保存测试产物 | 分阶段保存测试分析、设计、用例及自动化测试代码；代码落在测试框架仓库工作区，保留 commit 或完整 patch，push 受任务授权约束 | 带来源和版本的分析 / 设计 / 用例 / 代码资产；附件须真正上传并读回核验，单一 URI 不表示原件已保存 |
| 6. 执行并汇报 | Agent 调用项目已有框架 / CI，逐轮保存结果、日志、原始报告、实际版本 / 环境出处与用例 actual / reported result | 各轮执行记录、原始报告和最终测试结论；第 5、6 步可迭代，原 FAIL、ERROR、BLOCKED 与未完成记录继续保留 |

### 1.3 项目凭据与一次授权

项目资源的名称、地址、连接参数和 credential reference 属于普通管理数据；Git token、环境私钥、SSH 密钥等秘密由加密存储或 Secret Store 持久管理，密钥与密文分离。用户可以录入一次并在后续任务中复用、轮换或撤销，任务快照固定非秘密引用和授权范围，运行时才向 Git helper、SSH agent 或实际使用的工具注入所需凭据。

DeepSeek、Codex 和 Claude Code 的 Provider 身份由云端执行环境预配。用户为任务批准的项目资源范围可覆盖该任务的主代理和子代理，无需逐个子代理登录；模型服务身份与 Git / 测试环境授权仍分别配置、分别撤销。委派不能扩大网络、仓库写入、环境操作或费用范围，也不能从用户电脑静默复制既有登录和密钥。

原文秘密不进入 Git URL、PRD、提示词、普通数据库字段、SDK 事件、报告、补丁、日志或产物附件。旧会话同步仍只接收管理产物，不要求上传源码、环境密钥或 Provider 登录。

### 1.4 SDK 托管与结果边界

采用的是官方 **Harness Python SDK**，不是 DeepSeek 模型 HTTP API SDK，HyperTest 与 DeepSeek harness 的此路径不采用 ACP。SDK 和 `dsh` runtime 配对版本须先固定并完成兼容探针；选择 SDK 是接入与维护决策，不据此宣称测试运行更快。

每个 CloudAttempt 使用独立 runtime、workspace 和 `dsh_home`。首版按 SDK 当前限制设计：不能依赖单会话 cancel / close 或实时权限审批；Worker 执行预授权、预算与资源边界，超时 / 取消需终止该 Attempt 的完整进程树并核验清理。本地进程停止不证明远程 SSH / CI 或业务副作用停止，未决操作须保持待恢复并对账。缺少授权进入持久 `WAITING_INPUT`，不能默认放行；超出冻结授权或预算上限须创建关联新 CloudTask。恢复依据已保存输入和授权，由兼容探针确认安全恢复能力，不承诺原地 SDK 会话恢复。

DeepSeek 是任务指挥官，Codex / Claude Code 是其子代理；仅有一个有效平台 writer。委派必须收尾并回收原件后才可完成，父会话 idle、模型一轮结束或 Worker 存活都不等于整个任务完成。执行中断、未知外部副作用和失答必须先查询原操作并对账，不能自动重发测试、CI 或写操作。

云端任务进度与 `reported_result` 分开，reported PASS / FAIL 保留来源和原报告；它们不自动成为 legacy VERIFIED Evidence、FINAL Verdict 或 RELEASE_READY。平台保存与校验产物，项目框架产生执行结果；Hash、Agent 摘要、SDK 事件和进程退出码各自不能单独证明产品行为通过。当前 SessionTask 的 scope、幂等、expected-version、结果及 UNKNOWN 语义完整保留。

规范字段由[领域模型](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)拥有，通信与回传由[TMP](../protocol/TEST_MISSION_PROTOCOL.md)拥有，运行与凭据边界由[技术架构](../architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)拥有。分阶段依赖和退出条件见[实施计划](../CLOUD_TEST_IMPLEMENTATION_PLAN.md)；增量源码与隔离验收见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)，不据此宣称生产部署、真实凭据上传或 SUT 测试执行完成。

### 1.4.1 固定 SSH 环境诊断的独立扩展

[ADR-023](../architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)增加默认关闭的固定SSH诊断设计；source30 Worker / source29 helper的r8 canonical专项已通过；source31对同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与staging待验收。根 / 子代理只调用host窄代理，不得到SSH / 签名 / 平台密钥或一般网络；冻结精确目标与host key，只允许无参数、有限时间 / 输出的只读动作。远端操作单独持久登记和按原ID对账；本地停止或模型drain不能证明远端停止，未知继续RECOVERY_REQUIRED / HELD。该扩展不改变Local、项目框架归属或管理SSH访问。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。通用SSH只在隔离fixture中实施，不改变Project共享双模式；见[执行环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

### 1.5 Local 自动同步流程（ADR-020，待实现）

Local 保留 SessionTask 及现有 MCP / typed API / journal 契约，在客户端增加语义协调层：

```text
Harness Hooks：自动触发 ─┐
                        ├→ 统一本地同步协调器 → 现有私有客户端 / typed HTTPS API / journal
MCP：显式提交与查询 ────┘                                      ↓
                                               同一 Project 下的 SessionTask 与版本历史
```

用户选择已有授权 Project，并取得真实 Provider / 父会话 ID。协调器仅收集用户选定的正式分析、设计、用例、原始报告和代码引用，不上传整段聊天、隐藏推理、任意工作区或认证目录。子代理交回父会话汇总，不为每次 Hook 或子代理另建任务；新父会话仍按 ADR-018 建立新任务并引用旧任务。

Hooks 捕捉生命周期或正式资产变化的时机，减少阶段同步依赖模型主动记住调用工具；它们不替代业务判定。`Stop`、`SessionEnd`、工具成功或进程结束均不代表任务 COMPLETED 或测试 PASS。只有正式资产明确提供的任务进度与结果才可提交；本地 pending / dirty / coalesce 只描述待同步工作，不新增服务端状态。

Hooks 和 MCP 共用同一会话写入责任：先完整读取固定版本基线，再合并本次明确变化，保留任务计划、结果和历史资产；自动触发在有实质变化时才形成新更新。现有同步会更新全部任务标量字段，不能用稀疏状态事件清空计划或覆盖 FAIL；显式 MCP 完整请求仍保留有意空值和原接受语义。写前冻结完整请求、稳定 key 与 expected version；已发送或 UNKNOWN 的操作只 GET 原 key，NOT_FOUND 不授权重发或换 key。确认同步成功需要有效接受回执与接受版本的完整分页读回。

Hook 是 best-effort 触发，断线、退出或强制关闭没有上传完成保证。尚未发送的新意图与已发送未知操作分开保存和展示；前者经核验可以首次提交，后者只能对账，不能用后台队列盲目重试。关闭自动触发保留私有账本、正式资产和平台历史，MCP 继续可用。Codex、Claude Code、DeepSeek harness 的实际事件 / MCP handler 和真实父会话能力先分别探针，不从另一 Harness 或实验性 bridge 的存在推定已支持。

本地设计、兼容探针、统一协调器、Codex / Claude Code / DeepSeek harness 独立适配和统一发行安装验收见[本地同步分阶段实施计划](../LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)。它与云端 P0–P4 独立推进，不以云端执行交付为前置条件。

### 1.6 两种模式共享任务同步能力（ADR-021，Cloud 部分实现）

云端任务同样需要在工作进行中保存进度和阶段产物，不能只在 SDK 最终返回后上传一段总结。TaskSyncCore 复用本地设计中形成的可靠同步规则：只处理选定的正式资产清单和明确语义进度，合并尚未冻结的局部意图，在各域操作范围内冻结请求 / 稳定 key / 版本条件，保留精简对账记录，校验 ACK 后完整读回其固定接受版本或检查点。已发送或可能已发送的 UNKNOWN 只按原 key 对账，NOT_FOUND 不授权重 POST；任务进度、测试结果和传输状态分别保存。

| 模式接入 | 写入责任与目标 | 保持的边界 |
| --- | --- | --- |
| LocalSyncCoordinator + LocalSyncAdapter | Hooks / MCP 汇入真实父会话的唯一协调器，再走既有 SessionTask 同步 | 原 Provider / session、actor / Project、`task:sync`、完整请求及版本语义不变；本地协调锁不变成服务端 lease |
| CloudTaskReporter + CloudSyncAdapter | DeepSeek 与子代理将结构化进度、正式资产 / 结果交给当前 CloudAttempt Worker，由持权 writer 持续报告 | 独立 CloudTask / Attempt、`cloud:work`、lease / fencing 和类型化操作；SDK 负责执行控制，子代理不获得平台凭据或各建 SessionTask |

Cloud 的明确语义进度先落在现有 `SubmitCloudAssets` 的 `kind=REPORT` 非最终报告修订：用稳定 key 保存阶段、里程碑、阻塞与已接受资产引用，CloudAttempt 的现有 checkpoint 可引用该修订。它不自动改变 Task / Attempt 状态或 reported result，最终报告仍须明确指定并完成收尾；无需另加进度端点、profile、状态枚举或表。

共享核心不统一 token、全局 journal、任务状态或后端端点；队列 / 账本按各自来源与 Attempt 隔离，由适配器决定合法变更与读回范围。Local 的完整 SessionTask snapshot 不能套给 Cloud 的所有进度事件，Cloud 附件上传能力也不隐式增加 Local 的二进制上传接口。SDK 活动通知只可触发核对，不能凭 idle、子代理回答或上传成功推定实质进度、测试 PASS 或产物交付完整。两种模式都只保存正式产物，不收集整聊天、隐藏推理或秘密；原 reported / VERIFIED 边界不变。

共享契约与库供 Local L1、Cloud P2 / P3 分别接入和验收；两条产品路径独立发布，任一模式故障不得污染同 Project 的另一类任务。Cloud 不依赖本地 Hooks 或统一安装包，其运行镜像仅复用需要的共享组件。具体实施与故障验收见[云端计划](../CLOUD_TEST_IMPLEMENTATION_PLAN.md)和[本地计划](../LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)。

### 1.7 项目经验跨模式复用（ADR-022，Proposed）

项目经验面向方法、排障和适用条件的复用。Canonical Testing State 保存任务与原报告；TaskSyncCore 管可靠同步；PowerContext 托管获准经验和检索索引。经验带固定接受修订 / 确切来源、适用代码 / 框架 / 环境版本、观察时间、限制与确认者。候选保留原 owner 权限，确认脱敏后才可 Project 共享；共享正文不开放不可读原报告，来源引用分别鉴权。历史经验和模型自述不证明当前环境可用、缺陷已修复或测试 PASS，检索结果也不成为指令或执行授权。

固定评估基线 PowerContext 1.4.0 的静态 Bearer 共用 `admin`，Scope 不是项目授权；当前独立服务仅面向可信单操作者。拟议 Gateway 独立校验检索、候选与确认发布权限，既有 `task:sync` / `cloud:work` 不自动包含这些权限；根 / 子代理不取得服务管理员 token。Cloud 由 Worker broker 接入，Local 未来通过统一 release 的可选 adapter / 显式工具接入；memory 队列、版本和故障与任务同步账本分开，失效 / 停用不得阻断测试、同步或改写结果。

首版 SQLite Basic / `fts` 不要求外部 Generation / Embedding；外部模型默认关闭，不安装原生自动记忆插件、不扫描历史会话，只提交显式受控 query 和获准经验。关闭 `CAPTURE_PROMPTS` 仍不能阻止上游 recall Hook 外发完整当前 prompt，不能据此承诺无采集。先完成独立服务，再评审 Gateway 隔离、双模式适配和经验修订 / 失效 / 撤回，见[分阶段集成计划](../POWERCONTEXT_INTEGRATION_PLAN.md)；本节不新增现有协议字段、scope 或任务状态。

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

用户关联 PRD、SUT 仓库版本和已有测试环境。HyperTest 管理项目、计划和用例，向 Agent 下发
测试任务并记录结果；Agent 使用被测项目已有工具链完成从分析到测试执行的工程工作。
平台让这些工作形成可查询、可交接、可追溯的质量活动。

### 4.2 面向产品市场：Agent-native Autonomous Testing Platform

HyperTest 服务于 Codex、Claude Code、OpenCode、Pi 等可替换的通用 Agent。
Agent 与测试框架能力的增长应直接增强平台，而不要求平台复制这些能力。

### 4.3 面向架构：Autonomous Testing Control Plane

| 层次 | 职责 |
| --- | --- |
| HyperTest One | 管理测试项目、计划与用例；下发测试任务；保存执行记录、证据、缺陷和质量结论；维护权限、版本、历史、追溯及策略验收 |
| Agent | 执行测试分析、测试设计、测试实现；调用 SUT 既有测试框架 / CI；分析失败，提交结果、证据及结论建议 |
| 被测项目工具链 | 按项目原有测试语义运行断言，管理相应测试环境和依赖，产生原始日志、报告及其他执行产物 |
| MCP / 集成通道 | 传递任务与状态、提交产物引用和证据；提供范围受限的通信，不接管 Agent 推理或复制测试框架 |

HyperTest 对正式状态和结论的校验职责，不等于必须亲自运行测试。

---

## 5. 产品范围边界

HyperTest 的投入集中在 Testing State、Testing Semantic Model、任务契约、证据治理和质量结论。
Agent 提供已有的 LLM Loop、Tool Calling、Shell、Filesystem、Code Editing、Context Management
及 Subagent 能力；SUT 已有框架 / CI 提供测试执行能力。

平台不另建通用 Agent Loop、测试框架、通用测试执行引擎或项目环境管理体系，也不以增加
Runner backend、语言运行镜像和 SUT 启动器矩阵作为产品扩张方向。将这些能力改名为适配层，
不会改变其维护成本或职责归属。

平台可以为真实项目需要接入现有报告格式和 CI 结果，但接入目标是保留执行出处、证据与追溯，
不是重新实现测试发现、断言、fixtures、执行调度或 SUT 部署。既有自有 Runner 在迁移期间
作为旧路径保留，兼容范围和退出步骤另行决策，不成为新产品架构的必经组件。

Web 和 MCP 都是领域工作台入口；平台价值来自长期测试资产，不能只保存终端文本或聊天摘要。

---

## 6. 核心设计原则

### 6.1 Agent 可以消失，Testing State 不能消失

会话可以结束，Agent 和模型可以替换；Project、计划、Requirement、Risk、TestCase、
Implementation、Execution、Evidence、Finding、Verdict 及交接记录应长期存在。
下一会话通过平台获得已完成工作、剩余风险、未决问题及证据缺口，不依赖转抄整段聊天。

### 6.2 Agent 完成测试工程工作

Agent 负责需求与风险分析、测试设计、代码实现、调用项目测试框架、观察结果和诊断失败。
它根据任务契约自主选择工程动作，平台管理目标、授权和产物验收。

### 6.3 项目工具链产生执行事实

测试框架、已有 CI 和真实测试环境产生 Exit Code、JUnit、HTTP 响应、指标、数据库状态、
Trace、截图和日志。Agent 可通过授权通道提交这些原始产物及其引用；结果必须关联实际
源码、测试实现、环境和执行出处。平台自有 Runner 不是事实进入系统的唯一合法来源。

### 6.4 HyperTest 记录并治理质量结论

HyperTest 基于固定 Policy、覆盖、已接受产物、执行证据和 Finding 校验并记录结论。
Agent 摘要不自动成为事实；原始文件的 hash 证明完整性，身份认证或签名证明相应来源属性，
它们各自都不能单独证明测试真实发生或产品行为正确。证据不足时明确记录缺口和不确定性。

> **Agent performs testing work.**
> **Project test tools produce execution results.**
> **HyperTest connects testing state, evidence and conclusions.**

---

## 7. 总体架构

```mermaid
flowchart TB
    UI[Web 工作台]
    HT[HyperTest One<br/>项目 / 计划 / 用例 / 任务 / 证据 / 结论 / 历史]
    SYNC[Local：现有 Codex MCP<br/>ADR-018 SessionTask 同步]
    FUTURE[Local 未来触发适配<br/>Harness Hooks / MCP 显式操作]
    COORD[未来统一本地同步协调器<br/>Hooks 与 MCP 共用唯一 writer]
    CORE[TaskSyncCore 共享库 / 语义<br/>各模式独立实例，Cloud 部分实现]
    W[Cloud 增量实现：云端 Python Worker<br/>独立 CloudTask / CloudAttempt]
    REPORTER[CloudTaskReporter / CloudSyncAdapter<br/>当前 Attempt 持权报告]
    D[DeepSeek harness<br/>官方 Harness Python SDK]
    A[DeepSeek 自行参与 / Codex 或 Claude Code 子代理<br/>分析 / 设计 / 实现 / 框架调用 / 诊断]
    SUT[被测项目已有测试框架与 CI<br/>原生测试入口 / fixtures / 环境 / 报告]
    UI --> HT
    SYNC -->|原 task:sync / 版本化管理产物| HT
    FUTURE -.->|ADR-020 待实现| COORD
    COORD -.->|复用私有客户端 / API / journal| HT
    COORD -.->|LocalSyncAdapter 复用| CORE
    HT -->|冻结输入、范围、资源引用| W
    W -->|SDK 会话 / 事件| D
    D --> A
    A -->|分阶段产物 / 原始报告| W
    W --> REPORTER
    REPORTER -.->|复用同步能力| CORE
    REPORTER -->|cloud:work / lease：校验、上传、回读| HT
    A -->|调用项目已有入口| SUT
    SUT -->|执行结果、日志、报告| A
    HT -->|经校验的质量状态与结论| UI
```

两种模式汇入同一 Project，独立保留各类任务；图中表示完整目标；Cloud 链路、共存视图与共享库已有默认关闭的增量源码，完整运行和生产未验收，Local 组件另行记录。TaskSyncCore 的连线表示组件复用，不是两种模式共用一个进程、凭据或全局账本。Local 实线表示现有 Codex MCP 同步；未来适配后由协调器路径取代该客户端的直接提交，Hooks 和 MCP 不形成并发 writer。旧受管路径继续保留。测试执行留在 Agent 与项目工具链之间。HyperTest 的数据接入、校验和报告解析围绕真实项目
需要建立；它不在这条链路中插入自有测试引擎。Agent 会话变化通过持久任务和可审计交接关联。

---

## 8. HyperTest 核心组件

1. **Project / Test Asset Management**：管理 SUT 项目、计划、需求、风险、用例、实现引用及长期质量资产。
2. **Task / Mission Management**：根据计划、策略和覆盖缺口发布任务，记录责任、输入、进度、人工问题和交接。
3. **Mission Contract / Agent Access**：通过稳定、类型化 MCP / API 提供目标、上下文、约束和验收要求，接收 Agent 的结构化贡献。
4. **Execution Record / Evidence Intake**：关联项目已有框架或 CI 的执行出处、版本、原始产物及其校验信息，维护证据链。
5. **Verifier / Quality Governance**：校验 Proposal、权限、版本、完整性、覆盖和证据充分性，按策略记录质量结论。
6. **History / Reporting**：保存 Finding、报告、Verdict 和历次贡献，供后续会话接力、审计与复测使用。
7. **Cloud Task / Resource Access（ADR-019，部分实现）**：共享 Project 的仓库与环境配置、加密凭据引用、版本预检和 CloudTask / CloudAttempt 生命周期；独立 Python Worker 通过官方 SDK 托管 DeepSeek harness，收集阶段产物与原始结果。它不复制 Harness 的 Agent Loop 或项目框架。
8. **Local Session Sync Coordinator（ADR-020，待实现）**：在客户端统一 Hooks 触发和 MCP 显式操作，完成正式资产选择、完整基线合并、单 writer、版本和原 key 对账；复用现有私有客户端与 typed API，不是新的 Agent Loop 或测试执行器。
9. **TaskSyncCore / 模式适配（ADR-021，Cloud 部分实现）**：共享正式资产、语义进度、冻结提交、幂等对账及固定接受版本读回；LocalSyncAdapter 保留 SessionTask 契约，CloudSyncAdapter 由当前 Attempt writer 报告云端进度与产物，不合并两类任务的权限或执行控制。

计划编译、覆盖检查和策略计算属于控制平面能力。自有 Runner、通用 Shell 和框架执行调度
不列入目标核心组件。以上组件是产品职责划分，不要求按组件数量新增独立服务。

---

## 9. HyperTest 与 Codex / Claude Code 的关系

HyperTest 向 Agent 提供测试任务、已有质量状态和验收标准；Agent 决定如何在项目工具链中
完成分析、设计、实现、执行和诊断，并通过 MCP / API 提交结构化贡献及原始产物引用。

平台掌握任务与测试资产的持久身份，不需要掌握 Provider 的推理循环或把某个 native session
作为质量活动永久身份。一次会话可以完成完整任务，也可以在保存工作状态后交接给下一会话。
交接需保留贡献者、输入、已接受结果、未决副作用和当前写入责任，不能冒用旧会话或重发未知操作。

ADR-013 的单持续主会话和 ADR-016 的当前会话绑定属于现有实现约束。其历史继续保留；
ADR-017 新 profile 独立定义材料接入 / 贡献者交接，旧约束及原生会话身份不被回写或静默解除。

---

## 10. Agent 接入与 Harness 兼容

目标接入围绕任务领取、上下文读取、Proposal、执行记录、证据及结论协作建立，不要求平台
为每个 Provider 重做通用 Harness。MCP / API 是 Agent 与外接测试管理平台之间的通信接口。
平台认证、项目授权和写入责任必须明确；连接 ID、模型自报会话名不能代替身份或权限。

服务器 Harness 与本地 Connector 受管模式继续作为已实现的兼容路径保留。当前服务器 UDS
Bridge、本地 WSS Connector 和交互式 stdio / HTTPS 各有既有协议与生命周期，不能混用或
因新目标删除原会话、设备授权和历史。具体实际限制见 ADR-015 / ADR-016 和客户端说明。

ADR-015 / ADR-016 原模式中，本机可用的 Git、模型和问题单授权留在使用它们的节点，不复制到平台镜像或任务上下文。
设备配对、项目权限、来源采集和问题单操作分别授权；已有登录不意味着任何平台动作都获准。
ADR-017 新贡献与交接契约由真实框架场景约束，不从当前 Codex 适配推定所有 Agent / MCP 已支持。

ADR-019 的项目凭据是用户单独录入并选择持久保存的云端资源，不改变上述本地授权归属。官方 Harness Python SDK 是首个云端适配；Codex / Claude Code 子代理由 DeepSeek harness 编排，不逐个绑定为旧 Run 的主会话，也不各自创建 SessionTask。

ADR-020 的 Local provider adapter 分别适配身份与事件：当前 Codex MCP 已可用，不意味着 Codex 自动 Hooks 或 Claude Code 会话同步已交付。它们均使用原 integration actor / client / Project 授权和 `task:sync`，不从 Hook payload、session label 或当前目录推定写入权限。

---

## 11. Test Mission Protocol

TMP 表达 HyperTest 下发什么测试任务，以及 Agent 应提交哪些可验收结果。
Mission 至少有任务身份、目标、范围、上下文引用、约束、验收标准和输出契约。

任务可以包含测试分析、设计、实现、调用已有框架执行和失败诊断。ADR-017 接入契约按真实材料分层验收。框架、现有测试入口及
产物格式来自 SUT 的实际工具链；平台提供治理约束，不把某种语言或通用 Shell 命令固定为所有任务的语义。

Mission / Attempt 记录一次工作及其验收，不等同于新建或永久绑定一个 Agent 原生会话。
ADR-017 / TMP v0.7 已明确首版材料接入的领取、顺序贡献交接、幂等回传和迟到写入拒绝；它不证明真实 Provider 会话恢复。现有 TMP wire / profile 继续解释
已有请求和历史，新契约必须独立版本化并与领域规范一起实现。

---

## 12. Agent Result Protocol

Agent 的最终产出遵循所选 profile 的结构化管理契约。ADR-018 与 ADR-019 保留原始 Markdown 报告及其 reported result，代码、执行和附件各有可读取的版本与来源；Markdown 不替代结构化关系或正式执行证明。旧 Mission 的 Machine-readable result 要求保持原义。

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

## 14. MCP 与任务协作入口

MCP 的目标是让 Agent 读取项目、计划、用例和已有结论，接收测试任务，提交分析、设计、
实现引用、执行记录及证据，查询进度和报告。Agent 使用自己已有的工程工具调用 SUT 测试框架；
MCP 不需要成为通用远程 Shell 或测试启动器。

写入采用 Proposal / 验收语义，平台按身份、Project、任务范围、输入版本和当前写入责任
校验并审计；读取按对象范围鉴权。具体工具名、字段和事务边界由后续 TMP / 领域规范确定，
本节不把规划能力冒充为已发布工具。

问题单操作关联批准的项目、Finding、Evidence 和操作意图，结果引用须可核验。超时或断线后
先查询原操作，不能盲目重复创建；设备、Git 或已有 MCP 登录不自动授予提单权限。

> **Read shared testing state. Propose traceable contributions.**

### 14.2 Local 自动触发与显式操作共用提交逻辑（ADR-020）

Hooks 负责触发，MCP 保留主动提交与查询，两者进入同一本地语义协调器后再调用现有私有客户端和 typed HTTPS API。协调器覆盖从固定版本基线读取、正式资产合并、冻结新意图、提交到回执与完整分页读回的写入责任；不能把现有 IPC 锁等同于这段事务，也不能让 Hooks 与 MCP 各自抢版本。

同步配置只保存非秘密映射和私有配置引用；现有授权 token 仍通过私有客户端通道使用，不写入 Hook 配置、参数、提示词或产物。失败和退出保留待同步意图及原 key 账本，不擅自换 Project、签发凭据、重跑测试或把同步 UNKNOWN 改写成测试 UNKNOWN。实施和回退条件见[本地计划](../LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)，当前操作仍见[Codex 会话同步指南](../CODEX_SESSION_TASK_SYNC.md)。

### 14.1 已发布交互 MCP 的实际边界与待迁移点

[ADR-016](../architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md) 已实现
stdio MCP → 私有 daemon → typed HTTPS API，提供九个交互入口，并在当前 Agent 显式绑定后
复用九个 TMP 工具，共18个工具。旧 `request_execution` 经原 Job Worker 调用 Docker Runner；
Implementation 仍绑定 Python / pytest，LOCAL 当前只改变 Agent 的位置。这些是实际限制，
不是新的产品分层目标，不能用重命名接口来掩盖差异。

“创建测试运行 → 我的电脑”已提供项目专属安装 Prompt、设备管理密钥来源和配对指引。
[正式发行与上线记录](../MCP_INSTALLATION_DELIVERY_20261020.md)包含固定 wheel、源码与校验身份。
独立 `setup` / `doctor` 使用私有文件或隐藏终端输入；管理 key 不进入 Agent 聊天或 MCP 配置。
安装不会隐式授予来源、问题单或执行权限。

首版支持 macOS/Linux：通用 stdio 宿主可提交 / 读取及请求 CLOUD；当前-Agent 执行仍受控于
Codex Desktop 的真实宿主证明和单 native / Run 绑定。这里没有宣称 Windows、任意 Agent 原生
测试框架或跨会话接力已可用。旧短期执行 grant、设备绑定与 inbox 规则继续按现有规范执行。

可复用的运输经验包括稳定请求 key、提交前持久意图、有界响应和原请求查询对账。UNKNOWN
结果保持待核对，不因为断线、NOT_FOUND 或换会话就自动再次 POST；新协作契约继续保留该原则。
平台范围撤权不等同于终止用户整个聊天或任意原生工具，取消与框架实际停止必须分别核实。

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

Evidence 使执行记录能够支撑质量结论。来源可以是 SUT 原生测试框架、已有 CI、真实测试环境
及其授权采集通道，包括原始测试报告、Exit Code、HTTP 请求 / 响应、日志、指标、Trace、
数据库状态、截图、测试代码与 Git Diff 等。

证据应关联任务、用例 / 实现、实际源码和测试版本、执行环境、时间、执行出处及产物摘要。
接入形式可采用受保护上传或可验证的外部引用，依真实场景决定；平台不读取任意路径 / URL，
也不因接收结果而取得额外项目权限。ADR-019 云端资源凭据须经独立配置与授权，不能夹入结果附件。字段、大小限制、来源准入和事务边界由各 profile 契约明确。

Agent 自述、聊天截图中的结论或单个 PASS 字符串不自动成为正式 Evidence。接收文件、
验证 hash、验证来源和确认足以支持质量结论是不同的检查。Hash 只证明相应内容完整性，
配对或签名也不单独证明真实执行；来源、版本或执行关联不足时明确记录缺口，按 Policy
决定可采纳范围。校验证据不以平台再次运行同一测试作为唯一方法。

现有 Runner 产生的 Evidence 保持原来源、校验状态和历史解释，不回填为新的外部来源。

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

以下是纠偏后的产品目标流程。ADR-017 已明确首版材料接入与顺序贡献者写入契约；完整语义覆盖、可信原生 CI 与正式 native PASS 仍需独立实现 / 验收：

1. **项目与计划**：用户关联 SUT、需求、确定代码版本及已有框架 / 环境；HyperTest 管理测试计划、范围、用例和验收要求，创建可追溯测试任务。
2. **任务下发**：HyperTest 经 MCP / API 向获授权的 Agent 提供任务与已有状态。Agent 领取职责、核对实际仓库和工具链；不要求平台先复制仓库或启动自有 Runner。
3. **测试分析与设计**：Agent 分析需求和风险，读取已有测试，提交计划 / 用例及覆盖关系；平台校验并记录版本与追溯。
4. **测试实现**：Agent 在项目原生测试体系中新增、修订或复用测试；向平台关联实际测试代码、版本和入口，不强制生成平台专用 pytest 模块。
5. **原生框架执行**：Agent 调用项目已有测试入口或已授权 CI。框架按项目配置执行，产生真实结果、日志和报告；平台不承担测试引擎、依赖安装或 SUT 启动器角色。
6. **执行记录与证据接入**：Agent 提交实际版本、环境、执行出处、状态及原始产物 / 引用；平台校验身份、关联、完整性和来源，保留失败、未知与证据缺口。
7. **失败诊断与协作**：Agent 分析失败、关联 Finding，必要时提问或按授权推进项目既有问题单流程。修复后的再执行保留新的执行事实，不覆盖旧失败。
8. **结论记录**：Agent 提交分析和结论建议；HyperTest 结合已接受事实、覆盖和 Policy 校验并记录质量结论、报告和依据。
9. **完成或交接**：会话结束前保存已接受产物、剩余任务及未知操作。后续获授权会话在明确交接后继续；平台保留所有贡献和结论历史。

阶段可在一个会话内完成，也可顺序接力；不能通过换会话改变冻结输入、丢弃失败记录或重复外部副作用。

---

## 21. HyperTest 的任务管理循环

```text
管理项目、计划与用例
  → 固定任务输入、范围和验收要求
  → 向获授权 Agent 下发任务
  → 接收分析、设计、实现与实际框架执行记录
  → 校验并关联证据、覆盖、Finding 和结论
  → 保存已完成工作、缺口、问答及交接状态
  → 后续会话接续或新轮次复测
```

这是任务状态与质量治理循环。Think / Tool / Observe / Edit / Retry 由 Agent 自身驱动；
测试发现、fixtures、框架调度和断言由被测项目工具链承担。

平台任务下发、权限、幂等、问答、当前写入责任与审计属于 Operational State；被接受的领域
产物、执行事实和结论属于持久测试资产。跨会话接力不放弃单次写入责任和迟到提交防护，
但不应把原生会话不可恢复直接等同于整个质量活动必须丢弃或重新开始。

断线后先对账已提交结果和未知副作用，再明确继续或交接；不因重连自动重跑测试、重新提单
或改派另一 Agent。会话关闭不是测试取消，平台请求取消也不证明项目框架或 CI 已停止。
实际停止、已完成结果和未决操作分别记录。改变需求、代码或测试环境后如何建立新轮次，
继续依不可变输入和历史语义制定后续规范。

ADR-013～016 的 Job / lease / epoch / native 绑定继续约束旧 profile。ADR-017 在独立 native 轮次内采用新权限和交接，不把旧记录移入新身份，也不伪造原生会话来模拟接力。

---

## 22. Web 产品形态

工作台围绕测试项目、计划、任务、用例、覆盖、执行记录、证据、Finding、质量结论与报告组织。
用户应能看到：本轮测什么、谁在做、哪些用例已实现 / 执行、结果来自哪里、结论依据是什么，
以及下一会话需要继续处理什么。Agent Activity 和聊天摘要是辅助信息。

同一 Project 的任务列表拟默认显示 CloudTask 与 SessionTask，按 Cloud / Local 筛选并显示模式 / 来源；详情沿用各自状态、权限、结果和操作，不提供跨模式转换。该设计不增加 Local 同步的凭据或执行绑定前提。

Local 的未来同步观察需分开显示本地待处理 / 同步未知 / 已确认读回与任务进度 / reported result；前者是客户端传输状态，不成为 SessionTask 新枚举。关闭自动触发不删除待处理账本或平台历史，也不影响 MCP 显式查询。

任务位置展示应区分 Agent 所在位置、项目测试框架 / CI 的实际执行环境和 SUT 位置。
“我的电脑”应能指导用户在已有工程环境的 Mac 上使用 MCP；平台不要求所有项目都迁移到
统一 Runner 镜像。在线、已配对、命令结束、产物上传和质量通过是不同状态，必须分别表达。

现有页面已经提供服务器 / 本地 Connector 的受管入口和 MCP 安装指引；该表单仍创建受管
Harness Run。原生框架材料、顺序贡献者交接和新状态页面没有由白皮书修订自动上线；ADR-017 首版 API / 本机客户端与旧 Web/MCP 分开验收，不能从现有控件推定完成。

---

## 23. 推荐技术架构与现有运行基线

目标控制平面继续使用现有 PostgreSQL 关系状态、审计及 transactional outbox，按实际需求
保留任务 Worker、Web、API 和 Artifact Store。Worker 承担任务分发、领域校验与异步治理，
不以重新实现测试执行引擎为职责。报告解析和集成优先服务首个真实 SUT 的现有产物。

Agent 运行在已经具备工程工具链和授权的本地或远端环境，通过 MCP / API 与平台通信。
项目自行维护测试框架、依赖和测试环境；HyperTest 记录环境身份、可用前提和实际结果，
不因此建立统一镜像构建 / SUT 部署服务。通信或产物存储有明确需求时再增加组件，
不预先引入 Kafka、Graph DB、完整事件溯源或通用 Workflow DSL。

以下是最近交付记录中的现有实现，仍需兼容和保全：

| 组件 | 已记录基线 |
| --- | --- |
| 平台 | nginx / Next.js / FastAPI / Task Worker / PostgreSQL Compose 容器；持久数据库卷和 Artifact Store |
| 服务器受管 Harness | UDS Host Harness Bridge、Provider CLI / SDK、原生会话和授权 |
| 本地受管 Harness | WSS Connector、本机专属 Harness、受控源码传输和问题单适配 |
| 当前 Agent MCP | stdio / 私有 daemon / scoped HTTPS / 原 Job typed inbox；受控 Codex Desktop 绑定 |
| 旧正式执行 | 平台 DockerRunner / Python / pytest、固定受控 API profiles；它是待迁移的旧执行路径 |

v1.4 修订当轮没有变更任何部署、schema 或权限。ADR-017 本机增量和验收另行记录，不包含生产发布 / 迁移。后续演进保留现有数据、授权、两种受管模式、
TLS / SSH / VPN 边界和历史结果；不把旧容器化验证当作新原生框架流程的验收。
精确镜像与访问状态由[服务器运维材料](../SERVER_OPERATIONS.md)及实际巡检维护。

---

## 24. 源码、工作区与测试资产

工程工作区由执行测试工作的 Agent 与项目工具链管理。Agent 优先使用已有 SUT 仓库、
测试框架、测试数据与运行入口；HyperTest 保存任务输入身份、测试实现关联、产物和交接信息。
平台登记计划、用例或结论，不普遍要求全量源码上传、平台 checkout 或独占托管工作区。

追溯仍需明确实际 SUT 版本、测试代码版本及必要变更。测试实现可来自已有仓库测试、Agent
新编写的测试或其他项目资产，不以语言、`tests/*.py` 或 pytest symbol 定义所有实现。
本地修改不能伪装成原提交；有必要的 diff / 产物摘要与版本关联应通过后续契约明确。
现有不可变 Snapshot、Artifact 和历史字段不在本节原地改写。

源码或产物确需传输时，先核对目的、范围、来源及权限，排除凭据和无关文件。
Git 授权、Provider 凭据与项目秘密留在实际使用环境；文件 hash 只证明内容完整性，
源码来源与结果可信度分别核验。现有 ADR-015 的源码接收路径保留原校验和授权语义，
不再作为所有目标工作流的必经步骤。

跨会话接力传递的是可追溯状态和工作成果，不复制整段 Provider 对话或认证目录。
工作区变化、贡献者接力、重新执行与新测试轮次分别记录；不能混淆为同一未变化的执行事实。

---

## 25. 纠偏后的首个实战范围

下一阶段在具有真实 SUT 测试框架的 Mac 上，从一个已有项目、一个明确变更版本和一条
实际可运行的原生测试入口开始。先观察项目如何安装依赖、使用 fixtures、启动环境和输出报告，
再决定 HyperTest 需要怎样的最小结果契约；不先建一个演示 Runner 来替代实战。

首个闭环应证明：

1. HyperTest 能管理该项目、计划和用例，并下发范围明确的测试任务。
2. Agent 使用项目原生框架完成分析、设计、实现及真实测试调用，框架配置不被平台替换。
3. 实际正向 / 失败结果、源码与测试版本、环境和原始产物能被关联、校验和记录。
4. 平台的测试结论可追溯到用例与证据，缺证据不能被描述为通过。
5. 保存交接状态后，后续会话能在明确授权和写入归属下读取并接续；此能力必须实际验证。

既有 Python / pytest、Docker、27项隔离周期及33项生产 HTTP 周期保留其真实历史价值，
证明的是旧路径，不替代真实私有 SUT、项目原生框架或跨会话接力验收。
MCP 发行与安装验证也不证明这些目标已经完成。

v1.4 当轮只更新白皮书和交接材料。ADR-017 现已按新 Mac 真实盘点记录决定并同步技术架构、TMP、领域模型和 Agent 指导；代码及实际平台接入验收另行记录，不能把本机框架断言通过等同平台可信质量结论。

---

## 26. 后续演进

根据首个真实 SUT 的需要完善计划 / 用例管理、任务下发、框架结果接入、证据关联、质量结论
和顺序会话交接。先复用项目已有代码、报告和 CI，再抽象重复需求。

后续价值集中在覆盖缺口、Finding 分类、历史比较、回归选择、测试资产复用及不同 Agent 的
可追溯贡献。增加报告格式或集成须有真实场景；扩大 Runner backend、构建语言镜像矩阵、
自研 SUT 启动器不作为默认路线。

---

## 27. 长期阶段

长期积累需求变化、版本差异、覆盖、失败模式和测试历史，支持影响分析、回归范围选择、
质量趋势、测试资产复用与跨项目知识。Agent 能力持续增强，平台通过稳定任务与质量资产承接它。

多 Agent 并发协作、Blackboard 或复杂调度只在真实需求与冲突治理方案明确后另行决策。
跨会话顺序接力本身不要求这些机制，也不要求引入通用 Agent Runtime 或测试执行平台。

---

## 28. 复用 Agent 与项目工具链

Codex / Claude Code 等 Agent 已提供推理、工具调用、代码编辑、上下文管理和工程执行能力；
被测项目通常已有测试框架、依赖、fixtures、环境和 CI。HyperTest 复用两者，
把投入集中在项目、任务、用例、证据、结论及长期质量状态。

> **复用 Agent 完成测试工作，复用项目工具链执行测试，专注持久测试管理与质量治理。**

维护测试执行引擎或自研通用 Harness 不构成当前目标。新增平台能力应先回答：
它解决了哪一个真实项目中的测试管理或质量追溯问题，已有 Agent / 项目工具链为何不足。

---

## 29. Agent Orchestration 的含义

HyperTest 下发和管理 Testing Mission：测试分析、测试设计、测试实现、框架执行、
失败诊断与 Finding 调查。平台管理任务身份、范围、输入、责任、进度和验收；
Agent 决定工程方法并调用已有工具完成工作。

一个任务可以由同一会话持续推进，也可以经过明确交接顺序接力。质量状态由持久领域资产
承载，不依赖某个 Provider 对话永久在线。既有单主会话实现仍按原 profile 运行；新 native 任务的贡献者交接按 ADR-017 执行，不通过伪造会话、修改旧绑定或丢弃历史迁移。

ADR-019 云端任务由 DeepSeek harness 自行参与或分发工程子任务；子代理可按文件责任并行工作，但平台侧只有一个获授权主 writer，SDK/runtime 生命周期由 Python Worker 监督。是否并行和如何分工属于 Harness；HyperTest 不重新编写通用多代理推理循环。

> **HyperTest manages testing missions; Agents perform the testing work.**

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

> **用 HyperTest 管理测试任务，让 Agent 复用项目工具链完成测试，留下可追溯的质量结论。**

产品 slogan 保留：

> **One Input. One Mission. One Complete Test Cycle.**

完整测试周期描述质量工作的闭环，不要求全部工作发生在一个 Agent 会话中。

---

## 35. 对技术社区的介绍

> HyperTest One is an agent-native testing control plane that manages test projects and missions, connects evidence, and records quality conclusions. Agents perform the testing work using each project's existing test tools.

中文：

> HyperTest One 是面向 Agent 的测试控制平面，管理测试项目、下发测试任务、关联证据并记录质量结论；Agent 复用被测项目现有工具链完成测试工作。

---

## 36. 对企业客户的介绍

> HyperTest One 将分散在 Agent 会话中的测试计划、用例、执行记录、缺陷与质量结论串联起来。平台管理项目与任务；Agent 完成分析、设计、实现并调用企业已有测试框架和 CI，平台保存可交接、可审计的质量状态与证据链。

---

## 37. 核心架构原则总结

- **HyperTest One 管理测试项目、下发测试任务、记录测试结论。**
- **Agent 执行测试分析、测试设计、测试实现，并调用被测对象已有测试框架执行测试。**
- **测试框架、环境与既有 CI 属于项目工具链，平台不重复构建测试执行体系。**
- **计划、用例、执行记录、证据、Finding 和 Verdict 独立于 Agent 会话长期存在。**
- **Agent 提议，HyperTest 校验并记录；Agent 摘要不自动成为正式事实。**
- **执行来源、版本、完整性和证据充分性分别核验，不以平台自有 Runner 为唯一事实通道。**
- **任务下发与质量治理属于平台，工程动作与测试框架调用属于 Agent。**
- **跨会话接力明确贡献、授权和当前写入责任，不推导并发多写者或重放未知副作用。**
- **一个 SUT 一个 Project，Cloud 与 Local 任务共存；模式属于任务来源，身份、权限及历史分别保留。**
- **本地认证留在原节点；云端凭据由用户独立录入、加密持久保存并在运行时按范围注入，一次任务授权约束主代理和子代理。**
- **保留 Local 的 ADR-018 Codex MCP 会话同步，新增 Cloud 的 ADR-019 CloudTask / CloudAttempt；云端实现状态与设计决定分别记录，不重标旧 LOCAL / CLOUD 执行历史。**
- **Local 的 Hooks 自动触发与 MCP 显式操作共用一个同步协调器和 writer；生命周期事件不产生业务完成或 PASS，设计与实际交付分别记录。**
- **Local Hooks、MCP 与协调器统一版本发行、一键安装；三宿主分别验收，安装 / 授权 / 同步 / 测试结果分别呈现，保全其他配置与未决账本。**
- **原受管 Harness、Runner、Snapshot、协议及执行历史在明确迁移前保留原语义。**
- **新产品边界与已实现能力分别说明，以真实 SUT 验收推动最小必要演进。**

---

## 38. 最终定义

HyperTest One 是面向 Agent 时代的持久测试管理与质量治理控制平面。

> **平台管理测试项目、下发任务、记录结论；Agent 完成测试工作，调用项目已有框架执行。**

它把不同 Agent 会话中分散的测试分析、设计、实现、执行、诊断与结论关联为持续的质量活动，
保留从需求、风险、用例到实现、执行证据、Finding 和 Verdict 的可追溯链路。
平台价值来自这些状态、关系、证据和历史，而非测试执行框架的数量或自有 Runner 的能力。

> **HyperTest = Test Project & Mission Management + Test Assets + Evidence & Conclusion Governance**

长期资产：

> **Testing State + Testing History + Testing Knowledge**

愿景：

> **让 Agent 在项目原生工具链中完成测试，让质量状态与结论跨越会话持续存在。**
