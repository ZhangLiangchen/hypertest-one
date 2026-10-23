# Web 工作台操作指南 / Web workbench guide

## Cloud 云端模式与 Local 本地会话同步模式

**一个 SUT 对应一个长期 Project，同一 Project 可同时包含 CloudTask 与 SessionTask。** 产品提供两种模式，不按模式拆项目，也不在项目级切换二选一：

| 模式 | 用户入口和职责 | 实现边界 |
| --- | --- | --- |
| Cloud 云端模式 | 云端 Web / API 创建或复用 Project、配置资源、创建任务；云端 Worker 通过官方 Python SDK 驱动 DeepSeek 和项目工具链执行 | [ADR-019](architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md) 设计已接受，CloudTask / CloudAttempt 及下述共存视图**尚未实现** |
| Local 本地会话同步模式 | 本地 Agent 选择已有授权 Project，同步会话任务、状态和正式测试产物；目标设计为 Hooks 自动触发、MCP 显式操作共用协调器及统一发行 / 安装 | 保留 [ADR-018 Codex MCP 同步](CODEX_SESSION_TASK_SYNC.md)；[ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 协调器、自动触发、Claude Code / DeepSeek harness 适配及统一发行**尚未实现** |

项目内任务列表拟默认显示全部任务，并列标记 Cloud / Local 与来源，支持按模式筛选；详情按任务类型显示原状态、结果、报告和操作。模式由任务类型派生且创建后不可变，不能把 SessionTask 转成 CloudTask、换标签重写历史或用相同裸 ID 混淆两类详情。共享 Project 不合并同步与云端执行权限；列表 / 筛选 / 查看不会发起任务执行。这些共存 UI 是待实施设计，分阶段交付与验收见[实施计划](CLOUD_TEST_IMPLEMENTATION_PLAN.md)。

## Local 本地会话同步流程（当前仅 Codex）

1. 在本地 Agent 中配置已有 MCP 接入，选择平台上已有且获授权的 Project；需要项目时在云端创建，不在本机建立另一套独立项目。
2. 本地 Codex 使用项目已有工具链完成工作，经 `hypertest_sync_task` 保存版本化计划、用例、原始 Markdown 报告及 reported result；一个真实会话对应一个 SessionTask。
3. 经 `hypertest_get_task` 完整分页读回被接受版本，在平台查看任务与报告；保留原 scope、幂等、expected-version 和失答只查询原 key 的语义。

同步不启动或接管本地 Agent，不要求 Project 配置云端 token / SSH 密钥，也不要求执行绑定。Local 表示会话来源与协作流程，Agent 可调用已获授权的远端环境或 CI；它不证明测试物理位置或执行来源可信。云端执行关闭或不可用时，现有 Local 同步和历史读取仍独立可用。

## Local 自动同步目标流程（ADR-020，尚未实现）

以下是未来经受控发布并启用 adapter 后的流程，不提供现有可执行 Hook 配置或一键命令，不改变上面的 Codex MCP 操作步骤：

1. 选择已有授权 Project，核对真实 Provider / 父会话来源，选定正式分析、设计、用例、报告和代码引用清单；不选择整聊天、隐藏推理或认证目录。一个父会话保留一个 SessionTask，子代理结果由父会话汇总。
2. Harness Hooks / 已核验事件在生命周期或资产变化时机通知本地同步协调器，MCP 继续提供显式提交与查询；两个入口共用一个 writer、私有客户端、typed API 与 journal，不各自上传。Codex / Claude Code / DeepSeek harness 的事件和父会话能力按实际版本独立验收，未支持项不显示为可启用。
3. 协调器完整读取固定版本基线，合并本次明确变化，防止稀疏事件清空计划 / FAIL；仅自动触发无实质变化时不新增版本。显式 MCP 完整请求保留原空值语义。尚未发送的新局部意图可合并；冻结请求、key 和 expected version 后不再改写。
4. 显示本地“待同步 / 同步未知 / 已接受待读回 / 已确认读回”等传输观察，任务进度与测试结果单独保留。它们不是服务端新状态；`Stop` / `SessionEnd` / 成功工具 / 退出均不能显示业务已完成或测试 PASS。已发送或 UNKNOWN 只查询原 key，NOT_FOUND 不自动重发、换 key 或建新任务。
5. 有效回执与该接受版本的全部分页核对完成后才显示同步成功。退出或断线不保证上传完成；再次打开后先对账，保留未发送意图与原 key。禁用自动触发保留 MCP、私有账本、正式资产和历史，不取消业务测试或删除任务。

Hooks 是 Local 触发机制，不是第三模式；同 Project 的 CloudTask 与 SessionTask 身份、权限和生命周期保持独立。关闭 Hooks 与关闭云端运行分别验收，均不得阻断当前 Codex MCP。当前 XBlock 默认技能继续只调用现有原生管理工具；这次文档变更不安装 Hook、不修改全局技能、不开始上传。交付和退出条件见[本地 L0–L4 计划](LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)，与[云端 P0–P4 计划](CLOUD_TEST_IMPLEMENTATION_PLAN.md)独立推进。

上述正式资产清单、明确进度、幂等提交和固定接受版本读回也适用于云端任务，按 [ADR-021 TaskSyncCore](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) 由两种模式分别适配。未来页面应分别显示“Agent 当前活动”“已接受的语义进度 / 资产检查点”“仍待对账或读回的提交”及“测试结果”；SDK 活动、子代理回答或传输成功不能代替业务完成和 PASS。这是待实现的报告能力，不改变当前 MCP 操作。

## Local 统一发行与一键接入目标（尚未实现、未发布）

项目页拟增加 **本地模式接入**：选择 `claude-code`、`codex` 或 `deepseek-harness`，显示固定 HyperTest Local release、实际支持版本与能力，并复制一条不含秘密的项目安装命令。MCP、Hooks 适配、协调器、私有客户端及安装管理工具同包发行，不让用户分别拼装。这里是新入口设计；现有 **Create test run → My computer** 继续属于旧受管 Run 安装流程，`mcp-v0.1.0` 不改称已支持新 SessionTask / Hooks。

1. 将项目生成的命令交给当前 Agent，校验固定 bootstrap 与 payload 后，在用户私有目录隔离安装，仅合并所选宿主本包拥有的配置，保留其他 MCP / Hooks / 技能。实际发行尚不存在时不提供可运行命令，不显示“安装成功”。
2. 检查已有项目 `task:sync` 授权 profile；缺失则显示等待安全授权，不把 token 放进命令 / 聊天，也不要求 Agent 获取 Operator key。需要宿主重载时提示用户按宿主方式操作，不强退当前会话或声称热加载。DeepSeek 需明确所选 home / profile。
3. doctor 分别展示发行校验、宿主配置、项目授权、真实父会话映射和自动触发状态；MCP-only 必须明确标记。安装不会创建示例 Task、伪造 session 或自动上传历史聊天。
4. 当前真实父会话产生正式测试产物后，取得有效 ACK 并完整读回固定接受版本，另行标记本次同步已核验。配置就绪不等于同步成功，任一成功不等于任务完成或测试 PASS。

三宿主分别验收；不能用 Codex 成功填充 Claude / DeepSeek 的支持状态。升级 / 回退保留原 client 与未知 journal；卸载只移除本包拥有配置，不删用户会话、项目目录、其他 MCP / Hooks 或平台历史。发布资产、可信校验、兼容矩阵与分阶段安装验收见[统一发行与安装设计](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。本节不执行安装、发布或历史上传。

## 云端测试六步流程（设计已接受，尚未实现）

以下项目创建、任务创建和执行都在云端 Web / API / Worker 链路内完成；不能据本节寻找现成 Cloud 按钮或上传真实凭据。

| 步骤 | 计划提供的用户流程 | 需要显示和保存的结果 |
| --- | --- | --- |
| 1. 创建或复用项目并配置资源 | 在云端 Web 创建 Project，或复用同一 SUT 已有 Project；添加 SUT Git 与测试框架 Git（允许同仓），录入并选择持久保存仓库 token、环境私钥或 SSH 连接方式 | 共享 Project、资源元数据、加密凭据引用、权限与可用性；不回显秘密 |
| 2. 创建测试任务 | 选被测 branch / feat / MR / SHA、测试框架版本和环境，提供 PRD、测试目标、基本流程与操作 / 预算范围；`feat/*` 可按分支解析，需求标签需关联源码 | 独立 CloudTask 草稿与版本；不冒用 Codex session ID |
| 3. 核对并下发 | Worker 先解析 / 预检；用户核对精确双 SHA、MR base/head 和实际 head / merge SHA、PRD 版本、环境引用和授权后接受 dispatch | 冻结输入、队列与 CloudAttempt；预检受理 / 连通不等于实际测试，环境部署身份逐轮观察 |
| 4. 接取与分工 | Python Worker 通过官方 Harness Python SDK 驱动 DeepSeek harness，自行参与或委派 Codex / Claude Code | 当前阶段、委派状态、预算、待答与失败原因；子代理不逐个索取项目登录 |
| 5. 查看阶段产物 | 逐阶段阅读分析、设计、用例及自动化代码；查看框架仓库 commit 或完整 patch | 原文与历史修订、代码出处、附件上传并读回后的实际内容；push 按任务授权 |
| 6. 执行并复核 | Agent 调用项目已有框架 / CI，查看每轮用例 actual / result、原始日志 / 报告及最终结论；允许与第 5 步迭代 | 实际代码 / 测试版本、环境出处和执行来源；旧 FAIL / ERROR / BLOCKED 不被后续重跑覆盖 |

用户选择一次任务资源授权，约束 DeepSeek 指挥官及其子代理；Provider 身份由云端预配，Git / SSH 凭据运行时按范围注入。缺少新授权时进入持久 `WAITING_INPUT`。每个 Attempt 独立 runtime / 工作区 / `dsh_home`，取消需由 Worker 停止整个受管进程树；父会话 idle 或 SDK 一轮结束不能显示任务已完成，须等待外部委派终态并回收原件。

云端在执行中通过 CloudTaskReporter / CloudSyncAdapter 复用 TaskSyncCore，持续将明确阶段进度和选定产物检查点交给平台；用户不必等待最终 SDK 回答才看到正式产物。主 / 子 Agent 结构化交付给当前持权 Attempt Worker，只有该 writer 使用云端 typed 接口、`cloud:work` 与 lease / fencing 写入。Cloud 不伪造本地 session、不使用 Local `task:sync` 或全局账本，也无需安装终端 Local 全包；本地协调器仍按原 SessionTask 契约独立运行。

阶段进度通过现有 `SubmitCloudAssets` 保存为非最终 `kind=REPORT` 修订，以稳定 key 保留阶段、里程碑、阻塞和已接受资产引用；现有 Attempt checkpoint 可关联该修订。进度报告不自动改变任务状态或测试结果，最终报告仍单独明确指定，不能拿一次中途检查点充作任务已完成。

进度 / 资产提交失答时仅对账原 key，ACK 后读回固定接受版本 / 检查点才显示对应内容已确认；未读全保留缺口，不用最新修订替代原接受内容。取消时分别展示受管进程 / 远端 CI 或 SSH 的停止观察，以及在途报告的接受 / 读回结果；传输结束不代表测试已停止。两类任务共用 Project 列表，各自 UNKNOWN、权限错误或取消不能改写另一类任务的状态 / 结果。

任务状态与 reported result 分开：工作完成可以有 FAIL 或 BLOCKED，报告 PASS 不自动成为 legacy VERIFIED / RELEASE_READY。相同冻结输入的显式复测追加 Attempt，修改输入建立关联新 CloudTask；待恢复 / UNKNOWN 的原操作先对账，不能点击重试重复执行。会话同步的旧入口仍只保存管理产物，不因新增云端模式转为执行入口。

Cloud creates projects / tasks and executes through cloud Web / API / Worker; its six-step flow is accepted design, **not implemented**. Local currently uses Codex MCP source support; ADR-020's automatic events and explicit MCP will share one coordinator and one future HyperTest Local release, with separate Claude Code / Codex / DeepSeek acceptance. The unified package and one-command bootstrap are not implemented or published. The planned combined task list keeps immutable kinds, mode labels, filters, separate permissions and actions. Local is a collaboration mode, not proof of where tests ran. Cloud uses the official Harness Python SDK rather than ACP or the model HTTP SDK. The steps below retain legacy Run operating instructions and acceptance history; ADR-015 / ADR-016 `CLOUD / LOCAL` execution choices are not these new product modes.

## 历史交付基线与既有工作台

以下基线来自 ADR-015 当次交付；本次文档修订未巡检服务器。后续交付见 [ADR-016 生产记录](ADR016_PRODUCTION_DEPLOYMENT.md)及[安装发行记录](MCP_INSTALLATION_DELIVERY_20261020.md)，实际运维以[服务器文档](SERVER_OPERATIONS.md)及对应发布记录为准。

ADR-015 当次生产应用为 `63bd6cc`，原 Host Bridge 为 `95e92c5`，数据库为
`0018_harness_selection`。ADR-014 的 CLOSED 后治理与 ADR-015 双模式均已包含在发布中；
各自隔离验收仍独立保留。严格外部 TLS 已核验，线上本地 Connector 核心周期已通过。
该次发布和限制见[生产部署记录](ADR015_PRODUCTION_DEPLOYMENT.md)，历史治理结果见
[会话关闭后 Gate 验收](POST_SESSION_GATE_ACCEPTANCE.md)。

The historical ADR-015 delivery used application `63bd6cc`, the retained Host Bridge `95e92c5` and schema0018.
ADR-014 and ADR-015 are included in the deployed application. Strict external TLS is verified;
the online local-Connector core E2E is verified. Separate historical acceptance remains linked
from [that production record](ADR015_PRODUCTION_DEPLOYMENT.md).

## 结果复核与修复后复测 / Result review and retest

PR #10 的实现与隔离真实验收见[结果复核与新轮次验收](WEB_RESULT_REVIEW_RETEST_ACCEPTANCE.md)。
生产基线及是否已部署以[服务器操作交付](SERVER_OPERATIONS.md)为准。

- 点击需求、风险或测试用例标题，查看完整说明、前置条件和预期结果，并沿关联按钮追溯。
  在自动化实现中点击文件名，读取平台已接受的测试源码；服务端会核验 Run 的项目与快照
  归属、Artifact 路径和 SHA。已有仓库测试只显示其固定提交及文件信息。
- 概览的“阅读已保存报告”及完成任务的报告入口可直达报告。报告汇总已接受记录；
  正式质量结论仍以 FINAL Verdict 及可信 Evidence 为准。
- CLOSED / FAILED / CANCELLED 会话不能重开。使用“基于本次运行创建新轮次”，进入
  同一 Project 的草稿，选择“核对沿用的输入”；原 SHA、PRD、上下文、环境请求及完整
  Policy 被预填。检查原 SHA，选择需要验证的修复提交和服务入口，再按五步流程确认。
  保留原 SHA 也可以显式创建独立复测轮次。新轮次使用新请求身份、Binding 与原生会话；
  原运行、失败、报告和 Verdict 保留。
- 策略默认“沿用完整原策略”，包括表单未提供的字段；选择“重新配置并替换策略”才
  改用 Web 表单规则。环境只沿用请求，创建时重新核验实际镜像；归档或未绑定环境需
  显式新建并选择当前受控环境，不会静默升级。
- 读取旧输入失败时不替换草稿；已有草稿需要明确选择替换。关闭和语言切换保留同页
  草稿，刷新页面不承诺恢复未提交内容。保存输入的前导U+FEFF、换行和空配置保留。
- RECOVERY_REQUIRED 先核验原会话；恢复后通过原失败任务显式重试。源码准备阶段尚无
  Binding 的失败同样从原任务创建关联重试，不另建周期绕过历史。未知提交结果仍按原
  请求标识核对。已关闭会话中的原执行任务不能恢复；独立 Gate 任务采用下节的治理与关联重试入口。
- Finding 后续处置不会改写旧 FINAL 或报告。本分支按 ADR-014 提供 CLOSED 后独立 Gate 重评，
  仅使用已有正式事实，不恢复模型会话；验证代码修复仍需创建新轮次。

Open a requirement, risk, case or implementation to review the accepted testing asset and its links.
Use **Read saved report** from Overview or a completed task. After a session ends, choose
**New round from this run**, review the saved inputs, select the repaired SHA and service, then
confirm a new round. The full original policy is retained unless you explicitly replace it;
current trusted images are resolved again. Old runs and decisions remain in history. Input-load
failure preserves the current draft, and retrying failed work keeps its original task lineage.

## 会话关闭后的发现处置与门禁重评 / Post-session disposition and Gate reassessment

此入口已包含在当前生产应用中；[ADR-014](architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)
和领域模型 §23.8 定义规则，真实验收进度以[专门记录](POST_SESSION_GATE_ACCEPTANCE.md)为准。

1. 在“发现”中打开条目，先查看诊断、关联测试用例与可信 Evidence。选择合法下一状态，
   填写必需的处置原因；进入 RESOLVED 还需选择解决方式。平台检查原 `row_version`，
   并发冲突时刷新发现、核对状态后再决定，不会覆盖另一操作者的更新。
2. 在同一抽屉查看“处置历史”：状态、解决方式、版本、时间和原因分别保留。
   当前显示最近 50 条事件；更早记录或过长原因会明确提示截断。历史刷新失败会保留
   已加载内容与当前处置草稿，不阻止继续核对发现。
3. 仅当 Binding 与原主 AgentSession 均为 CLOSED、同 Run/Binding 已接受报告且没有
   冲突中的活动工作时，使用概览、“发现”或“质量判定”中的“重新评估质量门禁”。
   对话框说明此操作不会启动或恢复智能体、Bridge、Runner、Git 或新的正式执行。
4. 填写非空“重评原因”，最长 2,000 字符，不能含 NUL；首尾空白去除后保存。
   原因进入后台任务与 Audit/Outbox，不参与质量事实 hash，也不能覆盖策略。
   关闭对话框或切换中英文保留同页草稿，刷新或离开页面不承诺保存未提交内容。
5. 选择“提交重评任务”，查看已持久化 Job 的原因、状态及结果，用“打开已记录判定”
   进入对应 Verdict。刷新或关闭页面不取消任务。提交结果不确定时按原幂等请求身份核对；
   任务失败后使用“检查并重试门禁任务”，追加保留原 payload/reason 的关联重试。
6. 概览显示最高序号的 FINAL / TEST_RUN 判定。正式状态变化会追加新 sequence；连续
   相同状态复用最新匹配判定，每次请求仍保留独立原因、任务和结果审计。即使决策文字
   仍为 RELEASE_BLOCKED，也可能因处置状态变化产生新判定。
7. “持续会话与报告”展示原报告引用的 Verdict；其与最新正式结论不同时显示历史差异。
   原报告内容、SHA、旧 FINAL 和关联证据保持完整，不会为重评重新调用模型生成报告。

**关闭发现不代表代码已经修复。** 解决方式仅记录处理决定；已有正式 FAIL 不因 CLOSED、
FIXED 或 RISK_ACCEPTED 而变为 PASS，重评仍会阻止发布。验证修复需选择“基于本次运行创建
新轮次”，核对原输入、明确修复 SHA 后执行新的完整周期。ACTIVE、WAITING_INPUT、
RECOVERY_REQUIRED、FAILED、CANCELLED，以及没有报告的 CLOSED 不适用此独立 Gate 例外。

Open **Findings**, inspect the evidence, record a permitted disposition and its reason, then review
**Disposition history**. For a reported CLOSED binding and its original CLOSED session, select
**Reevaluate quality gate**, enter a nonblank reason of up to 2,000 characters, and choose
**Save reevaluation task**. Inspect the durable task and open its recorded Verdict. Failed work uses
**Review & retry gate task** with linked history; uncertain submissions retain their request identity.
The same-page draft survives dismissal and language switching. History refresh errors retain loaded
records and the form. Reassessment uses fixed policy and verified existing facts, calls no Agent or
Runner, and keeps the session closed. The latest FINAL is the current formal decision; the original
report retains its own Verdict and marks later decisions separately. Closing a Finding does not
waive an official failure or prove a fix. Verify repaired code in a new reviewed testing round.

API: `POST /api/v1/test-runs/{id}/jobs`，
`{operation:"EVALUATE_GATE", idempotency_key, payload:{finalize:true, reason}}`；
`GET /api/v1/findings/{id}/history?limit=50`（上限 100，返回 `events` 与 `truncated`）。
没有 Binding 的旧运行继续使用其原有 Gate 兼容契约；已绑定运行不能用同步端点绕过准入。

## 历史等待输入功能的交付记录

WAITING_INPUT 问题持久化、Web 回答及同一后台任务恢复已在本地和服务器通过真实模型 / Docker 验收，数据库迁移为 `0009_mission_inputs`。其 345 后端 / 31 Web 回归及检查、同 Job / Attempt / 原生 thread 恢复身份见[问答验收](WAITING_INPUT_ACCEPTANCE.md)。PR #6 已合并，服务器同步为 `a48bc96`；原真实执行身份仍为 `8e01ac5`，不改写成合并版本重新运行。见[合并部署记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr6-deployment-2026-10-18.md)。以下既有文件导入、测试链及 VPN/SSH 记录保留各自身份。

## 历史文件导入两阶段版本与验收状态

历史阶段1 `73dff989b87fa7349d9b36bd8416ece948a82212` 当时已部署，VPN 公网 `http://155.138.206.106:8080` 当时已激活精确来源的双层白名单，并保留 SSH 隧道。本地9实际PRD文件/15UI检查、20前端回归及生产HTTP Project/Run/Job创建、导入编辑稿原文/hash均有实际证据。

生产首轮Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5` 为BLOCKED：10Req/6Risk/8Case中2Case错误要求测试Runner内部功能，实际模型如实返回PARTIAL/6实现提案；平台拒绝并保留6条未接受Proposal，Canonical Implementation/Execution/Evidence/Verdict均0，不能称完整通过。

阶段2新增provider-independent `testing_scope`，区分被测应用行为/产品自身约束与如何测试的操作指令；[领域§12](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement)/[TMP§9](protocol/TEST_MISSION_PROTOCOL.md#9-mission-context)明确其规则。后端runtime/codex及回归已变化；新冻结工作树的303后端检查（3 warnings/48.70s）及fresh Web20/typecheck/build/audit0、Ruff/0008已通过，manifest `4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90`；最终提交/部署SHA与相同605字节PRD的新Project真实链统一见[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)。不得沿用阶段1“后端等d20/302”作为当前补丁已验证的证据，也不预写新链成功。

## 界面语言

在右上角选择 **中文** 或 **English**。默认中文，语言选择保存在当前浏览器的 Cookie 中，刷新与页面跳转后继续生效。切换不会清空当前表单或正在查看的页签，Ant Design 的表单、分页、确认框和日期显示也随语言更新。

界面语言不改写 PRD、项目名称、Agent 生成的需求/用例/诊断、测试源码或证据原文。质量门禁的固定系统理由提供中文展示，并保留可展开查看的判定记录原文；原始记录、ID 和 Hash 不变。

Choose **中文** or **English** in the upper-right corner. The browser remembers the language across navigation and reloads. Switching preserves the open form and selected result tab. Requirements, Agent output, generated code and evidence retain their original content.

## 从项目到结果

1. **创建项目**：填写项目名称、唯一标识及默认分支。仓库地址可预填后续运行。项目名会建议一个可编辑的标识；标识已存在时可以直接打开原项目。
2. **创建测试运行 → 源码**：填写仓库的 origin 源地址。GitHub HTTPS 来源可输入分支/标签并选择“解析并固定提交”，也可手工填写完整 40/64 位提交 SHA。解析不创建 Run，也不修改仓库；同名分支/标签需明确 `refs/heads/...` 或 `refs/tags/...`。修改源地址或参考版本后必须重新解析。正式测试始终使用固定 SHA，分支后续移动不会改变已有输入。
3. **需求**：粘贴 PRD，或导入 UTF-8 `.md` / `.txt` 文件并编辑正文。导入限 8 MiB，需求限 2,000,000 字符，配置限 100,000 字符；最终序列化请求须不超过 10 MiB。配置可使用纯文本或 JSON，留空按空文本原样保存。 本轮修复要求：只做一次 fatal UTF-8 解码，空文件、纯空白、仅 BOM、非法 UTF-8、NUL 或超限内容拒绝导入并保留原 PRD；有效内容保留原有空白和换行。带 BOM 且有正文的有效 UTF-8 可导入，BOM 按 UTF-8 解码处理，不把仅 BOM 当作需求。本地9文件/15项实际浏览器检查已通过，详见下方证据；生产链独立登记。
4. **执行环境**：选择预置 Python/pytest 或隔离 ASGI API 环境。API模式填写应用入口（如 `examples.api_sut.app:app`）、health path和启动时限。目录检查仅表示API主机镜像可用，服务会在Runner执行时实际启动和探测。不可用时保留草稿并重试目录，不自动换环境。
5. **策略**：选择全局和按风险类别的设计维度，以及阻止发布的缺陷级别。功能维度与阻断级缺陷的底线规则由平台保留。
6. **确认**：检查源码 SHA、PRD 原文和策略。创建后形成不可变输入；新的需求或代码版本应创建新 Run。关闭向导会在当前页面保留草稿和步骤；离开页面或刷新不提供草稿恢复。
7. **运行测试周期**：GitHub HTTPS 来源可选择“自动准备固定源码并运行”，一次持久任务完成检出、Agent Mission、Docker 执行及 Gate。其他来源选择 Worker 主机上的匹配 Git 检出；其 HEAD 和 `git remote get-url origin` 必须与本次输入一致。Worker 独立处理任务，关闭浏览器不会取消工作。环境绑定由创建时固定；受控profile仅Docker执行，正式执行不联网安装依赖。
8. **查看结果**：后台任务显示状态、错误、周期步骤和重试历史。被拒绝的 Mission 也保留已完成步骤与关联身份；展开尝试记录可查看 Agent 摘要、未决事项和完整原始结果，不能将其当作正式事实。检出失败会在操作窗口显示错误与任务入口。通过任务详情可直达阶段、执行、证据、发现或质量判定。页面自动刷新数据，暂时读取失败会保留已加载内容和页签。
9. **查看判定依据**：在“最新质量判定”中打开详情，再沿关联查看证据和问题发现。证据详情展示实际内容、采集来源与 SHA-256；失败运行可查看诊断结果。确认或解决 Finding 属于受控操作，需要填写原因，不能用“任务完成”代替质量结论。
10. **报告后处置与重评（本分支）**：按上节记录 Finding 处置，再显式提交带原因的独立 Gate Job；查看新旧判定与原报告差异。该入口不重新执行测试。

**仓库源地址与检出目录不同。** 创建 Run 时的 repository 应等于已有检出的 `git remote get-url origin`；不能将任意 checkout 目录冒充 origin。本地 Git 路径只有本身就是 origin 值时才适用。运行时填写的 workspace 则是 Worker 主机上干净且匹配固定提交的检出目录。浏览器本机路径不会上传源码。自动检出仅支持 URL 中不包含凭据的 GitHub HTTPS 仓库；私有仓库授权需预先配置在 Worker 主机。

仓库地址不能嵌入密码或 HTTPS 用户信息；使用主机上预先配置的 Git 认证。平台会在创建输入和启动 Agent 前检查，校验错误不返回提交的原始字段值。完整周期还会先检查实际 Runner 和可信镜像是否可用；这一步失败时不会调用模型或检出仓库。运行前检查不代表已经产生测试执行事实，最终以 Execution、Evidence 和 Verdict 为准。

Create a project, pin repository/commit inputs, provide the PRD, choose the execution environment and policy, then review the immutable snapshot. Then submit a **Run test cycle** task using a matching checkout on the Worker host. Follow Tasks → Executions → Evidence → Findings → Verdicts. Local paths refer to the Worker host; entering a laptop path does not upload a repository.

GitHub HTTPS origins can resolve a branch/tag to an immutable SHA and prepare that source within the same durable test-cycle task. Other origins use a manual full SHA and an existing matching checkout. Attempt details show the original Agent summary and unresolved items separately from accepted proposals and trusted execution evidence. The controlled catalog provides Python/pytest and a prebuilt FastAPI/uvicorn/httpx ASGI profile; workloads install nothing at execution time. Legacy unbound Runs retain their configured original Runner.

Repository addresses must not embed credentials. Configure Git authentication on the host. The complete cycle checks the actual Runner before model calls or source preparation; a successful preflight is readiness information, while formal execution facts still come from the Runner.

## 受控依赖与 API 环境 / Controlled dependencies and API environments

环境选择与 PRD/configuration 原文分开。`python-pytest-v1` 提供标准pytest；`python-api-v2` 预装完整锁定的FastAPI、uvicorn、httpx等依赖。运维先构建可信镜像，Web不接受任意requirements/pip、Shell、Dockerfile、镜像名、外部URL或凭据。详情可核对依赖版本、锁和launcher摘要。切回基础profile不会发送隐藏的服务参数。API-v2 明确隔离仓库 pytest 配置/conftest，生成模块内的 fixtures 必须自包含；历史 API-v1 按原身份只读展示，不能静默升级。

创建Run时固定实际imageID、依赖与服务定义。修改目录或镜像tag不会改变已有Run，缺少固定镜像时明确失败；新环境或依赖需要新Run，不能在执行表单临时覆盖。旧环境NULL显示旧运行语义，未知/损坏绑定不可降级绕过。周期和独立执行窗口只读显示绑定，受控环境强制Docker。

ASGI服务只在Runner隔离容器内启动，固定 `127.0.0.1:8765`。Runner执行HTTP200就绪探测，再向pytest注入 `HYPERTEST_BASE_URL`；该地址不是浏览器访问入口，不暴露宿主端口。生成测试使用真实HTTP请求，无TestClient/mock替代。执行详情展示实际镜像/平台和环境指纹，Evidence可查看有界服务日志、启动/健康/退出/清理和JUnit；服务“已就绪”不表示测试通过，质量以正式Verdict为准。

The environment step selects an approved profile and freezes its actual image/dependency/launcher identity with the SourceSnapshot. For ASGI, enter only a Python module/attribute, local readiness path and bounded startup time. The platform starts the service; tests use the injected `HYPERTEST_BASE_URL` for real HTTP. That URL is container-local. Inspect execution identity, service evidence and the final Verdict. An unavailable image preserves the form draft and fails closed; neither the Web nor an Agent installs packages or silently replaces a bound environment.

[规范与验收](CONTROLLED_ENVIRONMENT_ACCEPTANCE.md)区分自动化、真实模型和部署身份；该历史环境增量未改变当时的服务器访问边界。

## 历史文件导入与 HTTP 创建验收

原生 Chrome 已真实复现：已有需求草稿导入 `empty.txt` 后被空内容覆盖，进入下一步才出现 required 错误。[缺陷截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-empty-bug-2026-10-17.png)。这更新了此前“扩展禁止本地文件访问，只检查 chooser”的历史限制。修复后用真实系统选择器完成9文件/15检查全部通过，没有注入File/Input或修改Chrome文件访问权限。

本轮输入修复以“先校验、后替换草稿”为准：无效文件显示导入错误，旧正文不变；有效文件清除先前字段错误，用户可检查内容后继续。[九文件浏览器矩阵](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-browser-matrix-2026-10-17.json)已通过合法中文/英文/emoji、BOM+CRLF、无效文件保留正文/文件名、取消/重选、编辑后重开、中英切换及Review/回退。该本地验收没有新建Run或调用模型。生产上另建一个独立Project/Run，核对导入后编辑正文/hash并执行真实Agent/Docker/Evidence/Verdict；实际结果以[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)为准，不从本地picker通过推断整链成功。

普通 HTTP 页面可能没有 `crypto.randomUUID()`。本轮请求身份改用可用的原生 randomUUID，或 `crypto.getRandomValues()` 生成的 UUID v4；不使用 `Math.random()`，没有密码学随机源则不生成身份。这只是浏览器兼容修复，不改变 Job / Run 幂等契约。三入口均有UUID回归，阶段1已实际通过公网HTTP创建Project / Run / Job；后续scope修复的完整模型链另由最新交付登记记录。

Invalid PRD imports preserve the current draft and filename. Native Chrome/macOS acceptance passed 9 real fixtures and 15 UI checks, without creating a local Run or calling a model. The production HTTP Project/Run/Job entries passed in Stage 1. Its first model cycle correctly rejected PARTIAL output; a fresh-Project scope-fix cycle and exact runtime identities are maintained separately in the latest delivery record. HTTP request UUIDs use a cryptographic fallback.

## 任务状态与质量结论

| 展示 | 含义 |
|---|---|
| 任务已完成 / Task completed | Worker 完成了该次操作；测试是否通过以正式执行和质量判定为准 |
| 通过 / Pass | 对应正式执行或用例通过 |
| 可发布 / Ready for release | 当前规则所需设计覆盖、正式执行和可信证据齐全，且没有策略阻断的已确认缺陷 |
| 阻止发布 / Release blocked | 已观察到失败或存在策略阻断的已确认缺陷 |
| 受阻 / Blocked | 当前流程或判定受阻；展开原因检查缺失事实、覆盖或运行状态 |
| 等待重试 / Awaiting retry（RETRYING） | Mission已停止并等待显式重试，不表示Worker当前正在执行；查看原Attempt/拒绝原因 |
| 已中断 / Interrupted | 先查看已保存的状态和外部资源，再显式重试；旧历史保留 |

后台任务提交具有幂等身份。响应丢失时，Web 先查询相同请求是否已保存；无法确认时保留同一请求标识供重试。创建 Run 的同一标识不能绑定不同的实质输入，平台返回 409 并保留原记录；分支参考标签不改变 SourceSnapshot 的身份。

**Task completion is not a passing quality verdict.** Inspect official execution facts and the final verdict. Requests preserve identity across uncertain submissions; retries retain prior history.

## 任务活动与等待诊断 / Task activity and waiting

### 源码准备失败 / Source preparation failure

自动准备固定源码失败时，打开原后台任务详情查看“源码准备诊断”：失败阶段、错误分类、平台说明和下一步建议。分类区分 Git 认证、仓库不可用或无权限、网络/代理、证书、固定提交不可用、存储、超时、Git 缺失、输入不支持、检出校验及未知错误。它是受控运行诊断，不是缺陷、测试结果或最终根因证明；Web 不展示原始 Git stderr、命令、认证 URL 或 Provider 内容。旧任务没有记录时会说明无法确定原因。

修复 Worker 的现有 Git 凭据/代理、网络、证书信任或存储条件后，从该失败任务的“检查并重试”显式创建关联新 Job；原输入和失败记录保留。不要关闭证书校验或把凭据填进仓库 URL。若需要换仓库/SHA，使用“从本次新建一轮”审阅输入并创建新轮次；原快照不可修改。已有会话要求恢复或已终结时，遵循原恢复/新轮次入口，不能用源码重试绕过绑定。

Open the failed task to inspect its source preparation stage, category, explanation and suggested next step. These are bounded platform observations; raw Git output, commands, credentials and Provider text are excluded. Repair the configured Worker environment, then explicitly retry the original task to create a linked Job with the same frozen input. Use **New round from this run** to review a different repository or SHA. Existing session recovery rules still apply. Historical failures without a recorded diagnostic remain unknown.

在后台任务详情中查看辅助活动区。它展示已知的当前阶段 / Mission / Attempt、最近 Provider 信号、本 Job 的 Worker 心跳和最近成功刷新；活动类型提供中文和英文，不展示模型原文、命令或推理。

- **Worker 心跳**说明负责本任务的 Worker 仍在续租，不等于模型有新进展。其他 Worker 的在线状态不能替代本 Job 的心跳。
- **Provider 信号**说明平台最近接收了外部事件，不证明测试已完成。长时间未收到信号时模型仍可能正常工作；可检查任务期限与已有状态，按需要使用现有取消操作，不应仅因沉默盲目重试。
- **等待你的回答**按 WAITING_INPUT 显示，不当作模型卡死。回答恢复后仍为同一 Attempt，但本轮信号与等待前的一轮分开计算。Runner 执行和任务终态也不显示模型静默警报。
- **近期活动**每 Attempt 最多保留 200 条，约 2 秒内同类信号可合并计数，可按需查看更早记录；不承诺完整会话日志。刷新失败时保留已加载内容并提示尚未更新，不能把旧活动时间当成实时状态。

活动记录是运行观察信息，不能替代已接受的 Proposal、可信 Evidence 或 FINAL Verdict，不显示百分比或预计完成时间，也不触发自动取消、重试、重新规划或质量判定。[本轮活动验收](MISSION_ACTIVITY_ACCEPTANCE.md)区分自动化、真实模型检查和部署状态。

## 等待输入、回答并继续 / Waiting for input, answer and continue

当智能体需要澄清时，运行概览会显示“需要你的回答”，主操作变为“回答问题”。也可从测试任务详情、后台任务详情或“问题与回答”页签进入。此时后台任务为 `WAITING_INPUT`，表示流程暂停，既不代表失败，也不代表操作或测试通过；等待期间保留此 Run 的任务位置，但不占用 Worker。

1. 打开问题，阅读智能体问题原文。建议回答只是填入草稿的快捷入口，不会自动提交，也不限制自由文本。
2. 填写 1–12,000 个字符的非空白回答，不能含 NUL 空字符。正文保留原空白与换行。关闭面板、重开或切换中英文时，当前页面内的草稿会保留；离开或刷新页面不保证未提交草稿恢复。
3. 选择“提交回答并继续”。保存回答与原 Job 的 `WAITING_INPUT → QUEUED` 在同一事务完成。Worker 用新 lease 领取该任务，继续原 Mission、Attempt 和 AgentSession；不新建 Job，不改写原 Job payload 或 Mission spec。
4. 查看原后台任务的后续状态和正式产物。`ANSWERED` 表示回答已保存；`CONSUMED` 表示已供恢复任务使用，均不表示提议被接受、执行通过或可发布。正式结论仍以最高序号、`FINAL` 且 scope 为 `TEST_RUN` 的判定及其证据为准。

网络或状态刷新失败时，已加载问题和草稿会保留。请先刷新；提交结果不确定时，再次提交相同回答会复用原幂等标识和原 `row_version`，避免重复恢复。另一页面已回答或任务状态改变时，服务返回 409；查看保存的答案和任务记录，未提交的不同草稿仍可在面板中查看，不能覆盖原答案。

需要停止等待时，进入原后台任务详情并“取消任务”；Mission 的“管理暂停任务”会引导到该 Job。取消会保留问题及已记录回答，不能回答已取消的问题来重开任务。不要发起新周期或普通重试来绕过待答问题。

回答只补充任务上下文，不改变冻结 PRD、仓库提交、Mission 契约或被测范围。若澄清实际需要变更需求或源码，请另建输入正确的 Run；回答本身不是 Canonical Requirement、Runner Evidence 或质量决策。

The overview and **Questions & answers** section expose each recorded question. Suggestions fill an editable draft; free text is always allowed. **Submit answer & continue** atomically saves the answer and queues the same paused Job. A new Worker lease resumes the same Mission, Attempt and AgentSession. A failed read keeps loaded content; an uncertain same-body retry retains its original request key/version. Cancel the original Job to stop waiting. Answers remain context and do not modify frozen inputs, authorize a different testing scope, or establish test facts. The local real Web/Codex same-thread/Docker continuation path has passed; exact identities and separate server verification are tracked in [current acceptance](WAITING_INPUT_ACCEPTANCE.md).

API reference: `GET /api/v1/test-runs/{run_id}/input-requests`, `GET /api/v1/input-requests/{id}`, and `POST /api/v1/input-requests/{id}/answer` with `{answer, expected_row_version, idempotency_key}`. Successful answer submission returns HTTP 202 `{input_request, job}`; conflicting state or a different immutable answer returns 409. See [README API details](../README.md#human-input-api).

| 展示 | 含义 |
|---|---|
| 等待输入 / WAITING_INPUT | 同一后台任务暂停，等待回答；保留 Run reservation，不占用 Worker |
| PENDING | 问题待回答；Worker 安全暂停后才可提交 |
| 回答已保存 / ANSWERED | 原问题已记录答案，原 Job 已重新入队 |
| 智能体已接收 / CONSUMED | 回答已用于恢复过程，不代表已产生正式测试事实 |
| 已取消 / CANCELLED | 问题历史保留，不能再提交回答或据此重开任务 |

## 白名单 Web 入口 / Allowlisted Web access

Web 唯一路径是经已配置跳板出口访问受限入口。先连接获准网络，再打开运维交付中的
Web 地址；出口地址、CIDR 和连接资料只放在受保护配置中，不写入产品指南。
实际服务监听、nginx 来源限制及宿主 / Docker 入口规则见[服务器运维](SERVER_OPERATIONS.md)。
API、Web 后端和 PostgreSQL 不提供绕过入口的公网访问。

SSH 仅用于管理与人工恢复，已禁用转发；不再提供 Web SSH 隧道或本机回环备用入口。
管理别名、密钥认证、主机校验及密码恢复访问按运维文档保留。共享获准出口仍属于网络许可，
不等同于应用登录、个人身份或 RBAC。

常规发布检查现有白名单规则仍生效，并执行服务内部就绪检查；无需每轮重新请求用户连接
VPN、使用手机或逐条探测外部网络。首次开放、监听或访问边界变更时，再专项验证允许与
拒绝来源、Host/Origin 和转发头约束。前述及其他历史验收记录中的 SSH 隧道描述仅代表历史策略，
不是当前访问操作。

The only Web path uses the configured allowlisted jump-host egress. Connect to the approved network
and use the Web address from the protected operator handoff. SSH remains for administration and
manual recovery, with forwarding disabled; no Web tunnel or loopback fallback is supported.
Routine deployments verify the access rules and internal readiness. Separate allowed/denied-source
connectivity checks are required for initial activation or changes to the access boundary, rather
than every ordinary release. Shared-egress permission does not provide individual login or RBAC.
