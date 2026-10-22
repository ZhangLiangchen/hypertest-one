# HyperTest Local 统一发行与一键安装设计

**日期：2026-10-22，Asia/Singapore。状态：Accepted design / NOT IMPLEMENTED / NOT RELEASED。**

本地模式将 **MCP、Hooks 适配和同步协调器作为同一个 HyperTest Local release** 交付，用户可把项目页生成的一条非秘密安装命令交给 Claude Code、Codex 或 DeepSeek harness 执行。安装目标分别为 `claude-code`、`codex`、`deepseek-harness`；一个版本可以包含多个 OS 资产，所有组件复用同一提交链路 / 私有账本边界。

**目前没有统一包或可用的一键命令。** 本文定义未来交付与验收契约，不提供虚构下载地址、可立即运行的 bootstrap 或已发布版本。当前 ADR-018 Codex SessionTask 源码能力按[会话同步指南](CODEX_SESSION_TASK_SYNC.md)接入；历史 [`mcp-v0.1.0` 安装交付记录](MCP_INSTALLATION_DELIVERY_20261020.md)属于旧受管 Run 发行，其实际固定源码不能因当前构建脚本变化而被重标为支持 SessionTask、协调器、Hooks 或三宿主自动同步。当前源码能力、旧正式发行、未来统一包是三个独立状态。

## 1. 发行单元

[ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 的两入口共用一条链路：`Hooks / 显式 MCP → SyncCoordinator → 私有客户端 / journal → 既有 scoped HTTPS → SessionTask`。安装与升级不得把它们拆成竞争 writer。

按 [ADR-021](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md)，其中 TaskSyncCore 作为共享同步库，由 LocalSyncCoordinator / LocalSyncAdapter 使用，并可被云端 CloudTaskReporter / CloudSyncAdapter 复用。HyperTest Local release 固定所含共享库及 Local 适配器版本；每个真实来源保留独立身份、授权和账本 namespace，不将多个宿主或 CloudAttempt 合成全局 journal。

| 同一 release 的内容 | 交付要求 |
| --- | --- |
| MCP server、私有客户端和 journal | 保留现有工具、完整请求、原 key、expected-version 与固定版本分页读回语义；旧授权不自动升级 |
| TaskSyncCore、LocalSyncCoordinator / LocalSyncAdapter | 固定版本共享同步库及本地适配；同父会话唯一语义 writer，合并正式资产、串行提交、保全 FAIL、无变化不自动增版本、UNKNOWN 原 key 对账 |
| 三宿主 adapter 与触发模板 | 覆盖安装目标识别、真实父会话映射、MCP 配置及已验证的自动事件；逐项记录可用性，不假设三者均有原生 Hooks |
| 安装管理 CLI | `install`、`doctor`、`upgrade`、回退及 `uninstall`；用户目录隔离安装，按所有权合并 / 移除配置 |
| 最小使用资产 | 对应宿主所需的命令说明 / 最小技能资产与正式产物 manifest 说明；不复制聊天或替换用户已有全局技能 |
| 发行与兼容资产 | 固定源码、bootstrap、payload、manifest、摘要 / 签名、安装说明和逐宿主验收记录 |

新发行线采用拟议标签 `local-vMAJOR.MINOR.PATCH`，版本对应不可变源码 commit。此命名是新交付约定，未创建 tag 或 release。manifest 至少列出版本、源码 commit、所有资产的固定 URL / 大小 / SHA-256、bootstrap 与 payload 的验证方式、可信签名身份 / 证明引用、依赖闭包或锁定依赖、支持的 OS / 架构 / Python 与宿主版本、MCP 契约、journal 格式及可升级 / 可回退范围、各宿主各能力的状态和实际验收材料引用。不以 `latest`、`main`、浮动依赖或三个组件的任意版本拼装作为稳定发行。

manifest 同时固定 TaskSyncCore / LocalSyncAdapter 的版本与兼容关系。Cloud 运行镜像可独立固定兼容的共享库 / CloudSyncAdapter；**不执行本地 bootstrap、不安装完整 Local 包或宿主配置，也不等待三宿主发行验收**。Cloud 使用独立 `cloud:work`、CloudTask / Attempt 与 lease / fencing，复用库不复用 Local `task:sync` token、来源身份、状态或账本。云端报告通道不是把 SessionTask 安装到服务器上；两模式分别发布和验收。

### 安装宿主与来源身份分开

`--harness` 是安装目标，不是 SessionTask `provider` 的直接赋值规则。已有 `provider=codex` 保持；Claude Code 和 DeepSeek 的来源映射需在实现中明确并独立验收，不能仅因服务端接受某字符串就宣称支持。默认只选择当前明确宿主；识别不到或有多个候选时要求明确选择，不能猜父会话或静默配置全部宿主。用户可显式选择多个目标；`all` 仅代表展开为三个目标的请求集合，不是第四个宿主 / provider。每个目标分别预检、备份、安装、给出收据及诊断；缺失 / 未支持 / 受阻目标不得被静默剔除，部分成功不显示三宿主整体 READY。

DeepSeek harness 的本地真实父会话同步为 Local SessionTask，与 ADR-019 云端任务指挥官 / CloudAttempt 不同。它委派的 Codex / Claude 子代理只贡献本地父任务的正式产物，不另建 SessionTask，不获取平台 writer 凭据。事件 API 是否能触发 adapter、MCP 就绪时机、父子映射与退出限制均按实际版本验证；**不承诺未经核验的原生完整 Hooks**。

官方固定源码 `687f282e8625c6b8d11ff58211a90524be2e4317` 提供 [MCP client plugin](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/mcp/mcp-client/README.md#L30-L69) 和实验性 [Claude Code command bridge](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/experimental/hooks-claude-code/README.md#L168-L183)、[Codex command bridge](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/experimental/hooks-codex/README.md#L169-L178)。这些不是原宿主所有事件的等价实现：Claude bridge 无 SessionEnd、子代理事件 ID 指向 child，Codex bridge 无 SubagentStart / Stop；transcript 字段也不能当作可用来源。因此必须有 DeepSeek 专用身份与事件 adapter，不能直接套用 Claude / Codex 模板。

DeepSeek 安装还须显式选择私有 `DSH_HOME` / `dsh_home` 和 profile，按[官方 profile 加载行为](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/boot/app-boot/README.md#L48-L61)核验配置；部分配置只在启动时 patch，需报告等待重载 / 重启，不强退当前 Agent 或保证热加载。固定源码探查不等于已发布包验收；最终 manifest 必须钉实际发行版本并完成 L0 / L3b 实测。

## 2. 兼容矩阵与支持承诺

一个 release 必须列出三个安装目标，但支持等级独立。当前新统一包的状态如下，不能借用现有 Codex MCP 或旧发行的验收填充新能力：

| 安装目标 | 现有 Local MCP / 来源适配 | 统一包与父会话映射 | 自动触发 | 新发行真实同步验收 |
| --- | --- | --- | --- | --- |
| `codex` | ADR-018 Codex MCP 已有；仍须核对具体部署 / 授权 | 待实现 / 验收 | 待能力核验与实现 | 未执行 |
| `claude-code` | provider / MCP 适配待实现 | 待实现 / 验收 | 按宿主版本核验后实现 | 未执行 |
| `deepseek-harness` | provider / MCP 适配待实现 | 待实现 / 验收 | 官方实验性 command bridges 存在，实际版本 / 事件 / 身份兼容待核验 | 未执行 |

首版验收基线为 **macOS / Linux**，具体 OS、架构、Python 和宿主版本须写入实际 manifest；当前没有新统一包的 OS 兼容通过记录。Windows 未验收，首版不标为支持。安装器只检查已有模型 CLI / Harness，不自动安装模型工具、搬运模型登录、安装全局工具、提权或改变系统 SSH / TLS。

可先发布标记清楚的 beta 并逐宿主开放能力，但未通过的目标必须显示阻塞 / 不支持，不得显示 READY 或静默降级后宣称安装了自动同步。仅 MCP 已验收时，可显式选择 MCP-only 并标明自动同步不可用。正式承诺三者均支持前，三者都须完成真实父会话端到端验收；任一宿主的成功不覆盖另两者。

## 3. 一条命令的用户流程

未来在 **Project → 本地模式接入** 选择宿主，复制该项目的安装命令交给当前 Agent。该入口待实现，与旧 **Create test run → My computer** 的受管执行安装入口分开。命令只含平台 API、Project UUID、宿主、固定版本和校验信息，不含 token、Operator key、环境私钥、模型凭据或授权兑换秘密。

面向**目标 Harness 已安装、尚未安装 HyperTest Local 的机器**，单次 bootstrap 必须由已发布 release 与项目页生成；运行依赖仍须满足 manifest 基线。生成所需字段如下；缺少固定资产 / 可信校验材料时页面不得显示“可安装”命令：

| 非秘密字段 | 用途 |
| --- | --- |
| 固定 release 版本、源码 commit | 可核对的安装目标 |
| 固定 bootstrap URL、大小、SHA-256 / 受信任签名 | **先验证 bootstrap，再执行**，不能先执行下载脚本再验证自身 |
| 固定 manifest 与 payload URL、大小、摘要 / 签名关系 | bootstrap 校验实际安装内容，验证依赖来源与完整性 |
| HTTPS API、Project UUID、`--harness` | 指定项目及单一安装宿主 |
| 用户私有安装目录、已有授权 profile 引用（可选） | 隔离安装并复用明确获授权身份；引用本身不携秘密 |

单次 bootstrap 的目标步骤是：

```text
待生成、不可直接运行：下载固定 bootstrap → 对照可信 digest / 签名验证 → 执行已验证 bootstrap（固定 release + API + Project + harness）
```

不使用无校验的 `curl | sh`。与 payload 一起从不可信位置下载的 checksum 只能检测内容一致，不能认证来源；信任根来自独立确认的发行摘要、已受信任的项目入口或可信发布者签名。TLS 仍须校验系统 / 显式私有 CA；禁止跳过证书验证。发行记录须说明采用哪一种信任路径，不能把尚未建立的签名体系写成已存在。

以下仅是 **bootstrap 安装包后调用的拟议内部 CLI**，不是在尚未安装 HyperTest Local 的机器上可执行的一键命令；CLI、参数和下列路径均尚未实现：

```text
hypertest-local install --harness <claude-code|codex|deepseek-harness> --api-url <HTTPS_API> --project-id <PROJECT_UUID> --release <FIXED_LOCAL_RELEASE> [--auth-profile <EXISTING_PRIVATE_PROFILE_REF>]
```

安装器应完成：

1. 识别或按显式参数选择宿主 / 目标集合，核验 OS、架构、运行依赖、宿主版本、MCP / 自动事件与配置作用域；能力不明即报告，不安装猜测模板。多目标逐项检查和报告，不把安装集合当来源身份。
2. 下载并验证固定发行资产及锁定依赖，在用户拥有的私有版本目录隔离安装；不使用 `sudo` 或污染全局 Python / 模型工具。
3. 为所选宿主配置制作私有备份，记录本包拥有的配置片段，仅合并本包 MCP、已验收事件和最小使用资产。保留其他 MCP、Hooks、技能与项目设置；冲突明确显示并停止覆盖。
4. 绑定已选 Project 与当前有效 `task:sync` actor / client / grant；复用已授权私有 profile 时先核验目标与 scope。认证通过受保护客户端 / 文件引用处理，秘密不进入命令、聊天、普通 MCP / Hook 配置或日志。
5. 执行分级 doctor，输出实际版本、宿主、配置、授权及未通过项。需要宿主重载 / 重启时显示等待重载，不强退当前会话或宣称已经热加载。多 Project / 宿主只修改本包 namespace，分别保留配置与授权引用。
6. 在获授权的真实父会话有正式产物后，通过同一协调器取得 ACK 并完整读回接受版本，另行标记该会话的同步验证。安装本身不上传旧聊天，不为 doctor 伪造 session、自动创建示例业务 Task 或执行 SUT / 新模型任务。

一键安装表示安装动作可以由当前 Agent 完成，不消除宿主权限、必要重载或项目授权缺口。没有有效授权时保留已安装状态并明确“等待项目授权”，给安全引导而不自动签发、更换 actor / client 或提高 scope。未来若需要简化授权的 enrollment 流程，须另行设计和验收；本文不声明已有此 API。

### 与旧 setup 的边界

历史 `setup` 使用部署管理员的设备管理 Operator key，建立 Connector / 受管执行所需的设备与项目授权。它的行为与现有范围继续保留，**不能作为新 Local `task:sync` 安装的默认实现**。新安装器不要求 Agent 获得 Operator key，不复用旧设备配对来隐式授予新 scope；项目管理员仍通过现有受控注册机制单独安排授权。发行安装与签发授权是两个可分别受阻的步骤。

## 4. doctor 与真实同步的分级结果

下面是拟议诊断维度，不是服务端 Task enum；必须按当前宿主 / 当前版本逐项输出，不用一个 READY 掩盖缺项：

| 观察 | 通过证明的范围 |
| --- | --- |
| 发行已验证 | 固定来源、bootstrap / payload 及依赖校验通过 |
| 宿主配置就绪 | 指定宿主配置合并正确，MCP 可被宿主加载；需重载时仍为等待重载 |
| 项目授权就绪 | 当前 actor / client / Project 的 `task:sync` 可用；不增加执行权 |
| 父会话已映射 | 来自真实宿主上下文，父子来源明确；不是模型生成或配置中的占位 ID |
| 自动触发就绪 | 本宿主实际事件到达 coordinator，已独立验收；MCP-only 必须显示此项未启用 |
| 本次同步已核验 | 同一真实父会话、正式资产、有效 ACK 和该接受版本的全部分页原文核对完成 |

“配置就绪”不等于“同步成功”，“同步成功”不等于任务 COMPLETED 或测试 PASS。doctor 默认只检查安装与获准连接；业务测试结果保持原来源。丢失响应后沿原 journal 只 GET 原 key；NOT_FOUND、重新安装或重载宿主均不授权重 POST。

## 5. 重复安装、升级、回退与卸载

- 同版本重复安装应复用现有私有目录、actor / client 身份和单账本，核验文件与配置所有权，不重复追加 Hook / MCP 条目或签发凭据。多宿主安装共用同一可靠提交逻辑，不为同一父会话开启第二 writer。
- 升级前先停止新触发、处理当前 writer 归属并盘点 pending / SENT / UNKNOWN；备份私有配置和 journal，验证格式兼容后原子切换包入口。不能清空未知意图、换 client、重置发送状态或把旧 payload 重新发送。
- 回退只允许 manifest 声明可读当前 journal / 配置的版本；不兼容时停在明确受阻状态并保留材料。不能恢复旧数据库来覆盖已接受平台修订，不自动重放未知写。
- 卸载先关闭本包触发与进程，再仅移除本包拥有、且未被用户改写的配置片段和包入口；用户改写冲突要保留并说明。其他 MCP、Hooks、模型配置、会话、项目目录、正式产物和平台历史不删除。
- 私有身份、授权文件、pending 来源与 journal 默认保留，并说明如何重新接入 / 查询原 key。卸载不自动撤销授权或删除未知账本；需要撤权或另行清理时由用户明确选择且不得隐藏未决操作。

## 6. 交付与验收

按[本地 L0–L4 实施计划](LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)交付。L0 核验三个宿主和 OS 兼容；L1 接入 TaskSyncCore 并收口本地协调器 / 账本；L2、L3、L3b 分别接入 Codex、Claude Code、DeepSeek harness；L4 构建统一 release 和项目命令入口，并独立完成三个目标的真实安装 / 同步证明。Cloud P2 / P3 对共享核心及云端适配的验收由云端计划（独立设计参考，本 Local 源码分支未包含该文档）负责，本地安装通过不证明云端进度 / 产物同步已可用。

L4 至少覆盖已装目标 Harness 但没有本包 / 本包配置的干净机器、已有 MCP / Hooks 机器、多个宿主共存、重复安装、升级、兼容回退、卸载与配置保全；校验失败、权限 / 授权缺失、需重载、宿主不支持、断网 / 崩溃、UNKNOWN / NOT_FOUND、撤权和首次真实父会话 ACK / 全量读回。验收材料记录 release / 宿主 / OS / 实现 commit、调用序列与原回执，不上传秘密、整聊天或非请求范围的文件。

本设计不改变同一 Project 中 CloudTask / SessionTask 共存、云端六步官方 Python SDK 流程、现有 MCP 契约或默认 XBlock 原生工具流程。本段原为设计阶段边界；当前源码和验收状态单独记录于[实现记录](LOCAL_MODE_IMPLEMENTATION_STATUS.md)和[固定版本发行接口](LOCAL_MODE_RELEASE_BUILD.md)，不能从设计文本推定已安装、发布或完成同步。

## 7. 可选项目经验适配（ADR-022，Proposed / NOT IMPLEMENTED）

ADR-022（独立设计参考，本 Local 源码分支未包含该文档） 提议未来在同一固定 Local release 中交付可选 Memory Adapter / 显式检索与候选工具，经私有客户端连接 HyperTest Memory Gateway；Cloud Worker broker 复用该 Gateway，不依赖用户终端包。独立 PowerContext 服务的部署 / 检索与产品集成分别记录，见服务运行记录（独立设计参考，本 Local 源码分支未包含该文档）与集成计划（独立设计参考，本 Local 源码分支未包含该文档）。当前无该 adapter、Gateway、安装选项或可执行命令；本节不把它们增加到已承诺必选发行内容。

安装器不得放入 PowerContext admin token、自动签发 memory 授权或把 `task:sync` 当 memory 权限；Scope 也不提供授权隔离。项目经验的查询、候选与确认发布分别核验，来源保原 owner，人工确认脱敏后才共享，原报告与引用读取仍鉴权。根 / 子代理不直接带服务 key；经验失答使用独立操作 / 恢复记录，不占任务 journal 或阻断显式同步。

默认不安装原生自动 memory 插件、recall / capture Hooks 或扫描历史。固定版本即使 `CAPTURE_PROMPTS=false`，recall 仍可能发送完整当前 prompt；仅关闭 capture 不能满足最小化输入要求。初版只传显式受控 query 和获准经验，外部 Generation / Embedding 默认关闭。doctor 若未来提供 memory 检查，应单列可选能力 / 权限 / 服务连接，不因其未安装或故障降低原 MCP / 同步状态，不伪造记忆写入或业务任务。
