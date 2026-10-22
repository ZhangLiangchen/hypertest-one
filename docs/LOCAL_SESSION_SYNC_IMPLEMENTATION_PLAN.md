# 本地会话同步分阶段实施计划

**日期：2026-10-22，Asia/Singapore。状态：Accepted design / NOT IMPLEMENTED。**

本计划交付 [ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 的 Local 改进：**Harness Hooks / 已核验事件自动触发，MCP 显式提交与查询，统一本地同步协调器复用现有私有客户端、typed HTTPS API 和 journal；统一 HyperTest Local release 提供一键安装。** [ADR-018](architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 的 Codex MCP 同步继续可用；协调器、自动触发、Claude Code / DeepSeek harness 适配、统一发行与安装均尚未实现，尚无新包可用安装命令。发行与安装契约见[统一指南](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。

Local 仍使用 SessionTask：一个真实 Provider / 父会话对应一个任务，复用已有授权 Project。同一 Project 可同时承载 ADR-019（独立设计参考，本 Local 源码分支未包含该文档） CloudTask；Hooks 不增加第三种模式、不改变 `task_kind` / `product_mode`，不改 legacy Run、HarnessMode 或执行历史。Local 代表会话来源与协作方式，Agent 可以使用另行获授权的远端测试环境 / CI；同步本身不启动、接管或授权测试。

[ADR-021](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) 将这里形成的可靠同步语义抽为 **TaskSyncCore**，由 LocalSyncCoordinator / LocalSyncAdapter 与云端 CloudTaskReporter / CloudSyncAdapter 复用。共享正式资产清单、语义进度、冻结意图、幂等对账与固定接受版本读回；各模式分别落实合法 typed 操作、任务状态、身份、授权和 writer。Local 保持原 SessionTask / `task:sync`，Cloud 保持 CloudTask / Attempt / `cloud:work` 与 lease / fencing，不共用 token、全局 journal 或一个 daemon。

本次只修订文档，不安装 Hook、不创建上传进程、不修改全局技能、不触发资产上传，也不运行测试、迁移或部署。当前 XBlock 默认技能继续按其现有边界只调用原生同步 / 查询工具；未来只有受控发布、明确启用新版 adapter 后才切换自动策略。以下退出条件均为未来验收要求，不能据本文认定已经通过。

## 顺序、依赖与共同边界

```text
L0 规范、三宿主与 OS / 安装能力矩阵
  → L1 TaskSyncCore 与本地协调器 / 适配器（先收口现有 MCP）
     → L2 Codex Hooks 独立启用与试点
     → L3 Claude Code provider / MCP / Hooks 独立适配与验收
     → L3b DeepSeek harness provider / MCP / 事件独立适配与验收
  → L4 统一 release / 一键安装、故障矩阵与同 Project 兼容验收
```

L2 / L3 / L3b 都依赖 L1，可独立推进，同步写入责任收口之前不启用 Hook writer。各 adapter 完成独立退出条件后进入 L4；installer 候选开发可提前，实际 READY 不能先于相应宿主验收。统一包必须列明三个目标 `claude-code|codex|deepseek-harness`；可分批 beta，但未通过能力不得显示支持、静默降级或由另一宿主验收覆盖。正式承诺三宿主支持前，三者分别通过 L4。云端 P0–P4 与本地 L0–L4 独立推进，Local 无需等待云端 SDK、凭据或 Worker；混合 Project 实测于云端可用后单独记录，不补造通过。

TaskSyncCore 的共享契约 / 库是 Local L1 与 Cloud P2 / P3 的共同前置能力，两者各自接入和验收，任一整条产品路径的上线都不是另一条的前提。Cloud 镜像可固定兼容共享库及其适配器，不安装终端 Local bootstrap / 完整包；本地统一 release 仍固定所含共享库版本，不能因 Cloud 升级而浮动替换本机组件。

共同约束：

- **身份与范围：** 使用可核验的真实 Provider / 父 session ID 和获授权的既有 Project；未知或映射冲突时受阻。每次 Hook、不相关工作区和子代理不各建 Task。新父会话建立自己的 SessionTask 并引用旧任务，不冒用旧来源。
- **正式资产：** 仅收集用户选定清单中的分析、设计、用例、原始报告与代码引用；不扫描或上传整段聊天、隐藏推理、全工作区、认证目录或凭据。正式资产内容是数据，不作为 Hook 脚本或命令执行。现有 `source_ref` / `artifact_uri` 仍是元数据，不自动变成附件上传。
- **语义：** 生命周期通知只提供同步时机。`Stop` / `SessionEnd` / 成功工具 / 空闲 / 退出码不生成 COMPLETED 或 PASS。任务进度、reported result 和同步观察独立；本地 pending / dirty / coalesce 不加入服务端状态枚举。
- **写入：** 每个目标父会话只有一个语义 writer。Hooks 与 MCP 的写操作必须在同一协调边界内读取完整固定版本基线、合并明确变化、校验、冻结请求并提交；不能各走一条上传路径。现有 daemon IPC 锁不证明已实现这段跨读写协调；协调器的锁 / generation 仅为客户端归属，不新增 SessionTask wire lease 字段或服务端 writer-lease 迁移。跨客户端最终由原服务端 owner / expected-version / 事务锁约束，不能宣称跨设备 exactly-once。
- **保全：** `sync` 更新全部任务标量字段，局部 Hook 意图按字段 presence 合并，未提供的计划 / 结果不能变为空值或 NOT_RUN；显式 CLEAR 仅是客户端意图，须经授权、校验后物化成现有完整请求，不新增服务端字段。既有 MCP 完整 payload 的显式空值含义保留，不把它误当缺字段；已冻结 payload / key / version 不重写。省略旧 case / report key 不能删除历史。稳定 key 内容变化追加修订；自动触发对相同正式内容不产生无实质变化的新版本，显式 MCP 新 key 完整请求仍按 ADR-018 接受。FAIL 与后续 PASS 均保留来源与原报告。
- **可靠性：** 明确尚未发送的新意图与已发送 / UNKNOWN 操作。前者冻结请求、稳定 key、expected version 后可首次发送一次；后者只 GET 原 key，重连、进程重启、重复事件和 NOT_FOUND 都不授权重 POST、换 key、建替代任务或重新签发凭据。
- **确认：** 有效 ACK 须匹配原 key、Project / Provider / session、Task、契约和接受版本；再完整分页读回该固定版本的任务、用例与报告。回执接受与原文读回未完成分别显示，未读全不宣称同步成功。同步未知不改测试 reported result，不重跑测试。
- **私有状态：** journal 保留查询身份、请求 digest 与传输对账信息，不反复复制计划 / 报告原文；为首次提交所需的正式来源快照单独私有保存并固定内容，状态不明时不得从已变化文件拼出“原请求”。授权凭据仍通过既有私有客户端使用，Hook 配置只含非秘密映射与配置引用。
- **触发与恢复：** Hook 是 best-effort；退出 / 断线 / 强制结束不保证上传完成。未发送工作可被合并，已发送请求不可被新事件改写；未知操作未对账前，同一任务的后续写入暂停。保留明确的新意图供核验，不建立盲目重试旧请求的后台队列。
- **关闭：** 关闭自动触发保留 MCP 显式操作、私有账本、正式来源和历史。关闭云端 dispatch / Worker 不影响本地同步；关闭 Hooks 不表示取消业务测试或删除 SessionTask。既有授权 / scope 和测试执行边界不扩大。
- **安装：** Hooks、MCP、协调器、adapter 和管理 CLI 统一固定版本 / manifest，验证 bootstrap 与 payload 来源及内容；用户目录隔离安装，仅合并所选宿主的本包配置。安装 / 授权 / 真实同步 / 测试结果分级，安装不造 Task、不上传历史、不启动 SUT 或模型、不自动签发凭据；升级 / 卸载保留身份、未知 journal、用户会话与其他配置。

## L0：规范、三宿主与安装兼容能力探针

**依赖：** ADR-020 与四规范对齐；明确受控探针环境、可用宿主版本和测试材料。需要实际 provider 会话或授权的探针另按环境规则安排，不由本文自动执行。

**交付：**

- 对齐白皮书 v1.8、架构 / TMP / 领域 v0.10，明确 ADR-020 只扩展客户端同步机制，不修改 ADR-018 原 wire、身份、owner、授权、状态和结果语义。记录与现有客户端版本及当前默认技能的兼容边界。
- 分别记录 Codex、Claude Code、DeepSeek harness 的发行版本、运行形态、真实父 session ID 来源、事件名称 / payload / 时序、子代理辨识、超时与退出限制。分别核验 MCP、身份映射、自动触发和真实同步的前置能力；不因 MCP 接通或官方存在实验性事件包就认定自动同步已支持。
- 固定 macOS / Linux 的 OS、架构、Python、宿主版本和配置作用域矩阵；Windows 未验收不支持。核验现有宿主、profile、配置位置与重载要求，安装器不自动装模型 CLI、搬运登录或提权。DeepSeek 原生 Hooks / plugin 事件的真实可用性按[官方固定源说明](LOCAL_MODE_RELEASE_AND_INSTALLATION.md#安装宿主与来源身份分开)进一步探针，不把两类实验性 bridge 等同原宿主全部事件。
- 核对 Hook 的生命周期事件与正式资产变化如何关联；明确重复、乱序、无事件、强制退出和 child 事件的缺口。需要读宿主会话元数据时限定授权与字段，不把 transcript 当正式资产来源。
- 固定非秘密正式资产清单及来源快照要求、计划 / 设计映射、稳定 case / report key、任务状态的显式提供方式与有效内容校验；大文件按现有限额明确阻塞，不截断、不扩大通道限额或隐式上传。
- 与 Cloud P0 对齐 TaskSyncCore 契约和兼容矩阵，区分共同可靠性语义与各域 operation / version / receipt / readback。Local 完整请求、显式空值和 expected-version 属于 LocalSyncAdapter；不把它们普遍套给云端事件，也不因共享库向 Local 增加二进制上传、lease 或新 API。
- 固定统一 release 的 manifest、安装目标 enum、配置所有权、可信校验与依赖闭包、doctor 分级、journal 升级 / 回退契约和最小使用资产。现有旧 setup 的 Operator 配对 / run scope 不等同新 Local `task:sync` 自助授权；若需新 enrollment，标为另行拟议，不虚构已有端点。
- 给出启用和关闭设计：受控版本化 adapter、按 provider / 会话范围启用、MCP 保留、私有凭据引用及失败诊断；本阶段不提供未经发布验证的可执行 bootstrap。

**可核验退出条件：** 三个候选宿主分别有明确版本、官方能力出处、实际事件 / 身份 / 安装材料与逐 OS / 能力矩阵；缺失项明确阻塞。证明 Hook 事件不会直接生成业务完成、PASS 或新任务身份。能力未确认的 adapter 不进入启用阶段；规范静态检查不能代替真实事件探针。

**风险与回退：** 事件接口漂移、父子身份不明、目标宿主没有可用 Hook。保留原 MCP 显式同步与查询，将缺失能力标为阻塞；不改用聊天扫描、伪造 session ID 或强装全局插件绕过。

## L1：TaskSyncCore 与本地语义协调器 / 适配器

**依赖：** L0 的身份、资产和授权契约及 ADR-021 共享接口；当前私有客户端 / typed API / journal 的明确版本。此阶段先收口已有 Codex MCP，不启用任何新 Hook writer；无需等待云端实现或本地三宿主 release。

**交付：**

- 提取 TaskSyncCore 的资产清单 / 语义变化、未冻结意图处理、冻结请求、精简提交记录、原 key 对账与固定接受版本读回能力；以 LocalSyncAdapter 绑定既有 SessionTask typed API / owner / `task:sync`，LocalSyncCoordinator 负责本地唯一语义 writer。Cloud P2 / P3 可复用兼容库，其 lease / `cloud:work`、现有 `SubmitCloudAssets` 的非最终 REPORT 进度修订及 checkpoint 接受 / 读回留在 CloudSyncAdapter，不能在核心中硬编码 SessionTask snapshot 或全局账本。
- 新增会话级协调器，将显式 MCP 写入和未来 Hook 触发都收口到同一语义 writer；查询与原 key 对账保留现有接口。建立完整基线读取到结果核验的协调边界、崩溃可识别的 owner 和串行提交，不把现有 IPC 单请求锁称为该事务。
- 从固定 task version 完整拼接基线，合并本次选定资产和明确标量变化，保留计划、reported result、稳定 key 与原失败。首次创建无基线时仍需完整合法正式输入；缺来源、字段冲突或缺页时受阻，不能使用 schema 默认值补造用户意图。
- 显式 MCP 完整 snapshot 的有意空值保持原语义；只有新的局部 Hook 意图按字段 presence / 明确 CLEAR 合并，已固定 payload / key / version 不重写。
- 定义仅客户端的待处理、内容变化和事件合并观察；自动触发的重复无变化不提交，尚未固定的新局部意图可合并，显式 MCP 新 key 完整请求保留原接受语义。形成请求后冻结内容、key 与 expected version，发送前私有持久化；正式来源快照与对账 journal 分工明确。
- 区分尚未首次发送、已发送待确认、有效 ACK 后待读回、已读全和确定拒绝。对于是否发送不确定的崩溃按可能已发送处理；已发送 / UNKNOWN 只查询原 key，NOT_FOUND 保留未知。对账未完成禁止后续请求绕开；确定版本拒绝后才可读取新基线并按明确新意图准备新更新，不能无条件自动改 key 重试。
- 完整校验 ACK 及固定接受版本的所有分页、连续 offset、来源、原计划 / 用例 / 报告。读取中断只续读同版本；读回失败不误报同步完成，也不重发已接受请求。
- 保持私有 token / config / journal 权限、撤权与跨项目拒绝、输入限额、秘密过滤和可读诊断；不将凭据放入 Hook 参数或普通日志。现有 `task:sync` 不获得云端能力或测试执行权。

**可核验退出条件：** 在隔离管理链路验证完整合并保留计划 / FAIL、stable key 修订、自动触发无变化不增 version、显式 MCP 完整请求原接受语义、MCP 并发串行、跨 client 版本拒绝、请求冻结前后崩溃、失答仅 GET、NOT_FOUND 不重 POST、错误 ACK、分页中断 / 混版拒绝与恢复读回。记录 TaskSyncCore / LocalSyncAdapter 兼容版本，证明核心未混用 Cloud 身份、凭据、账本或状态；共享契约检查不能代替未来 Cloud 真实报告验收。记录实际 API 调用序列和服务端版本 / 回执 / 原件，证明未产生 Job / Harness / Runner / Gate。现有 Codex MCP 工具调用与历史读回继续通过。

**风险与回退：** 错误合并、默认值覆盖、双 writer 或账本迁移损坏。保持 Hook 入口关闭，保留账本和正式来源，使用兼容读取路径先对账；回退经验证的 MCP 客户端版本，不删除未知请求或自动重发。已接受历史和服务端 schema 不回滚。

## L2：Codex Hooks 适配与受控试点

**依赖：** L1 可靠协调器通过；L0 已核验目标 Codex 宿主事件能力与真实父会话映射。宿主不支持时该阶段受阻，MCP 仍可用。

**交付：**

- 将经过核验的 Codex 生命周期 / 正式资产变化时机映射为协调器触发，Hook 不自行构造稀疏 POST。配置仅引用非秘密 Project / 会话映射、选定资产清单与私有客户端配置；按指定版本和明确试点范围启用，不自动修改其他项目或默认技能。
- child 事件只通知父协调器核对正式产物，不创建 child SessionTask；真实身份缺失、无授权 Project、未选定产物或未完成写文件时保留明确待处理原因。
- 对重复 / 高频事件进行客户端合并；MCP 显式提交与事件同时到达时仍只存在一个请求意图。停止 / 退出事件仅尝试触发，强杀 / 断线保留可恢复账本，不能标成最终任务完成。
- 展示待同步、未知、待读回和已确认结果；支持独立关闭自动触发，MCP 继续进入同一协调器，保留未发送工作及待对账 key。

**可核验退出条件：** 在真实且版本固定的 Codex 父会话中，正式分析、设计、用例和报告变化可自动到达同一 SessionTask，且 MCP 显式操作并发不重复写；验证 child、无变化、重复事件、退出中断、断网后重开与禁用 Hooks。有效回执和完整固定版本读回分别留证；生命周期结束不改业务状态或结果。没有实际事件材料和原文读回不得称自动同步成功。

**风险与回退：** 事件漏发、子会话误绑定、迟到事件越过新状态。关闭 Codex 自动触发，保留账本 / 来源 / 版本历史；经现有 MCP 查询原 key，确定新意图后才提交。不能通过清空 pending 或改任务来源“修复”。

## L3：Claude Code provider / MCP / Hooks 独立适配

**依赖：** L1 可靠协调器通过；L0 明确 Claude Code 实际版本、身份、授权和事件能力。Codex 试点结果不能替代本阶段验收。

**交付：**

- 独立实现 Claude Code provider 对真实父会话 ID、子代理归属和 Project 授权的映射；不因服务端接受 provider 字符串就宣称已支持 Claude Code，不把 Codex session ID 套用为 Claude 来源。
- 验证 Claude Code MCP 显式 `sync` / `get` 接入同一协调器、私有凭据通道和 journal；再启用对应 Hook 触发。若目标版本支持原生 MCP-tool Hook，只作为同一协调器的一个触发适配，不增加旁路 writer；能力不支持时明确限制，不虚构替代命令。
- 复用正式资产清单、基线合并、冻结意图、UNKNOWN 原 key 对账和固定版本读回；父 / 子事件、生命周期、Hook 故障和关闭逻辑分别适配，不假定与 Codex 同名或同义。

**可核验退出条件：** 真实 Claude Code 父会话与独立授权身份完成显式同步 / 查询及自动触发原文读回；Codex 与 Claude 的任务来源不混淆，重合 session 字符串按 provider 分别识别。重复事件、双入口并发、child、版本拒绝、失答、撤权、退出与禁用均有实际调用和历史保全证据；当前 Codex MCP 不受影响。

**风险与回退：** provider 适配只做字段改名、私有配置泄露、事件与子代理归属错误。独立关闭 Claude 自动入口或未通过的 provider；保留已有材料与回执，仍已验收的 Codex MCP 继续服务。Claude MCP 若尚未独立验收，不能作为可用回退冒称交付。

## L3b：DeepSeek harness provider / MCP / 事件独立适配

**依赖：** L1 通过；L0 固定 DeepSeek 的真实发行版本、`dsh_home` / profile、MCP、父子身份和事件能力。L2 / L3 的通过不替代本阶段，云端 SDK 接入也不证明本地同步可用。

**交付：**

- 实现本地 DeepSeek 来源 adapter，明确真实父会话与 provider 映射；本地父会话对应 SessionTask，不能借用 CloudTask / CloudAttempt 或云端指挥官身份。子代理只交回正式产物，由父协调器写入，不各建 Task。
- 在显式选择的私有 home / profile 配置 MCP、来源映射和已核验的触发机制；只修改该 profile 本包拥有片段，报告需要重载 / 重启，不强退当前会话或声称热加载。显式 MCP 与事件共用 L1 协调器、私有凭据和单 journal。
- 官方实验性 command Hook bridges 的事件范围、父子字段和退出行为按实际发行验证；不能推定原生完整 Hooks、用 transcript 补造来源、依赖不存在的 SessionEnd / subagent 事件，或把 child session 当 parent。映射不足时明确 BLOCKED；MCP-only 只有单独验收并明确选择后才可使用。

**可核验退出条件：** 固定版本 / home / profile 下的真实 DeepSeek 父会话完成 MCP 提交 / 查询、可用事件 → coordinator → ACK → 固定版本全部原文读回；父子归属、重复事件、MCP 并发、退出 / 重启、UNKNOWN 原 key 查询、禁用和多 profile 配置保全有独立证据。不启动云端执行、不为 child 建 Task，不以 Codex / Claude 结果或 SDK mock 替代。

**风险与回退：** 实验性 bridge 漂移、profile 不生效、父子映射或生命周期缺口。关闭该宿主自动触发并保留 journal；仅已验收的 MCP 能力可明确作为回退，未通过则报告阻塞，不静默换宿主、造 session 或强装全局插件。

## L4：统一 release / 一键安装、故障与双模式兼容验收

**依赖：** 待发布能力的 L0 / L1 与相应 L2 / L3 / L3b 通过；固定发行、兼容 journal、私有配置和诊断设计具备。统一包列出三宿主支持等级；稳定三宿主支持须分别全部验收。发布 / 安装 / 默认策略切换另按目标环境受控执行。

**交付：**

- 从固定源码构建一个 HyperTest Local release，标签采用拟议 `local-vMAJOR.MINOR.PATCH`，内含固定版本 TaskSyncCore、LocalSyncCoordinator / LocalSyncAdapter、MCP、私有客户端 / journal、三宿主 adapter / 触发模板、installer / doctor / upgrade / 回退 / uninstall 和最小使用资产。manifest 记录 bootstrap / payload 的来源及摘要 / 签名、锁定依赖、共享库 / adapter、OS / Harness / wire / journal 兼容和逐宿主验收材料；校验缺失或资产未发布时不生成“可安装”命令。Cloud 复用共享库不要求安装此完整包。
- 提供 Project 本地模式的非秘密一键 bootstrap，默认选择 / 检测单一宿主，显式多目标 / `all` 按请求集合逐宿主检查与报告，不静默剔除受阻目标或混淆来源身份。校验 bootstrap 再执行并校验 payload，隔离安装后备份 / 合并所选宿主配置，复用有效私有授权 profile 或明确等待授权。不索取 Agent Operator key、不复用旧 setup 配对冒充 `task:sync`、不自动新增 scope / client、不上传历史、不运行 SUT / 新模型任务。需要重载只提示，不强退当前会话。
- 在已装目标 Harness、满足 manifest 依赖基线的干净机器（无本包 / 本包配置）与已有配置机器分别验收 macOS / Linux：首次安装、同版本重复安装、多个 Project / 宿主共存、升级、兼容回退和卸载；核对其他 MCP / Hooks / 技能与用户会话 / 项目目录完整保留。升级 / 卸载保留 actor / client、pending 来源和 SENT / UNKNOWN journal，不能通过换身份、清账本或重放恢复。
- doctor 按发行校验、宿主配置、项目授权、父会话映射、自动触发、真实同步分级；默认只读，不造 Task 或假 session。三个宿主各有首个真实父会话的正式产物、有效 ACK 和接受版本全部分页读回；安装 READY 不冒充同步成功或测试 PASS，未通过目标显式标明阻塞 / 不支持，beta 分批也不能静默降级。
- 完成网络断开、Hook 超时 / 异常 / 未执行、进程退出 / 强杀、重复 / 乱序事件、同时显式提交、跨 client 冲突、原件变化、分页中断、ACK 不匹配、NOT_FOUND、撤权与越项目的故障矩阵；核对 API 调用序列，UNKNOWN 没有重复 POST 或替代任务。
- 在同一 Project 保持 SessionTask 与可用 CloudTask 的有类型身份、独立状态 / 结果 / 权限 / 历史；Cloud 未实现时明确混合实测未完成，先证明未配置云端资源与关闭 Cloud 不阻塞当前同步。云端上线后按两计划补充混合详情 / 筛选验收，不因此阻止独立 MCP 保留。
- 在两种模式都可用后，以各自固定兼容的 TaskSyncCore / adapter 验证并发进度与正式资产提交：一侧 UNKNOWN、读回中断或 Cloud 旧 lease 不污染另一侧身份 / 版本 / 结果，账本与凭据保持隔离。Cloud 中途检查点、子代理归并及取消在途报告 / 远端执行的分别对账由 Cloud P2 / P3 验收，本地真实事件与安装仍按本计划独立证明。
- 固定客户端 / adapter / Harness 版本与来源，提供仅适用于已验收版本的启用、禁用、诊断和账本保留说明；默认技能 / 项目策略更新列为显式发行变更，不由 Hook 安装悄悄替换。按 provider / Project 小范围启用，展示未支持能力，不以静态文档或旧验收替代新路径验收。
- 验证独立关闭 Cloud、独立关闭 Hooks，以及关闭二者时的当前 Codex MCP 显式同步、原 key 对账、接受版本原文和既有历史读取；未发送意图保留可核验来源，已发送未知继续只查询。关闭 Hook 不取消本地测试、不清除授权或删除记录。

**可核验退出条件：** 固定发布资产、可验证的一键命令和每个已宣称支持的宿主均有真实安装 → 父会话映射 → 事件 / 显式 MCP → 单 writer → 有效 ACK → 固定版本全量读回证据。三宿主正式支持必须分别通过；干净机 / 已配机、重复安装 / 升级 / 回退 / 卸载、校验失败 / 授权缺失 / 重载 / 故障保全可复核，无非请求上传。故障中保留计划与原 FAIL，未支持 / 阻塞 / 未观察项独立列出。当前 Codex MCP、两类历史及 managed / native 路径兼容；混合 Cloud 实测单独留证或明确尚未完成。

**风险与回退：** 默认自动上传范围失控、发行不兼容、凭据或资产误收集。立即关闭受影响自动触发 / adapter，保留原 MCP、对账和历史；秘密按实际影响处理，不能删除历史或清空账本冒称恢复。回退不自动重放未决写，不改变其他项目的 Hooks、SSH、网络或凭据配置。

## 每阶段记录与规范归属

每阶段分别记录实现 commit / 发行与 Harness 版本、受控环境、输入及授权范围、实际检查命令 / 调用序列、原 key 回执、固定版本原文和通过 / 失败 / 阻塞 / 未观察范围。源码存在、进程成功、模型摘要或旧验收数字不替代自动同步链路证据；本计划不提供无依据工期。

字段、状态、owner 与服务端事务以[领域模型](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)为准，工具 / API / 回执与分页以[TMP](protocol/TEST_MISSION_PROTOCOL.md)为准，协调器边界以[技术架构](architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)为准，产品定位以[白皮书](foundation/HYPERTEST_WHITEPAPER.md)为准。当前可执行 MCP 流程见[会话同步指南](CODEX_SESSION_TASK_SYNC.md)；云端六步 / Python SDK 设计继续按云端计划（独立设计参考，本 Local 源码分支未包含该文档）独立交付。
