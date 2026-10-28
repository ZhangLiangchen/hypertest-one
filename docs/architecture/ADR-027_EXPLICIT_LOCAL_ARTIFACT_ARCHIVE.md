# ADR-027：Local 显式 Skill 与 CLI 后置产物归档

> **2026-10-28 增补：** [ADR-028](ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 取代本 ADR 对被新实现替代且不兼容的旧 Local 客户端、入口、SessionTask 数据和恢复路径的无条件兼容与保留要求。相关旧实现及对应旧数据可定向移除；现行归档合同与无关授权、源文件、服务仍适用。此增补不表示清理已实施。

日期：2026-10-27（Asia/Singapore）。状态：**架构决定已采用，首片产品实现完成**。部署、CLI/Skill 发行及 USER_OWNED 验收分别见[本轮交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)；源码与自动回归不替代用户功能验收。

用户决定将 Local 模式改为测试完成后显式归档：移除该模式现有 MCP、Hooks 和常驻同步依赖，新增 HyperTest One CLI 与 `hypertest-archive` Skill。本决定拥有新流程及旧入口退出范围；实施任务见[重构开发计划](../LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)。本文中的命令、实体和接口已有首片实现。旧客户端机器仍须显式执行受管退休；不据源码完成推定用户机器配置已移除或部署、发行已经完成。

## 1. 改造原因

当前 Local 安装器注册 `PostToolUse`、`Stop` 等事件；批准产物目录模式会在事件到来时读取文件、计算摘要、进入协调器，并可能读取服务器完整基线后才返回 UNCHANGED。MCP 指引又允许 Agent 在工作过程中主动同步。即使没有新增报告版本，也可能付出进程启动、IPC、文件读取、网络与模型工具调用成本。来源见 [Hook 注册](../../src/hypertest/local_sync/installer.py)、[文件观察](../../src/hypertest/local_sync/sources.py)和[协调器](../../src/hypertest/local_sync/coordinator.py)。此处是源码行为分析，没有端到端耗时测量，不声明具体提速比例。

现有预建、BIND、JOIN、SessionStart、逐调用 caller 与宿主版本耦合，增加首次接入和跨会话归档成本。用户实际需要本地 Agent 自主完成测试，随后把计划、用例、原始报告和真实 reported result 持久保存。归档无需平台在测试期间持续在线，也无需原测试会话在上传时仍存活。

MCP 本身支持读写工具调用和 HTTP 传输，频繁同步来自当前触发策略。采用 CLI 的依据是明确的调用时机、按需进程、确定的文件输入、统一的恢复机制及较少的宿主接入配置，不能把改造理由表述为“MCP 只能 pull”。参见 [MCP Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)与[传输规范](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)。

## 2. 产品决定与适用边界

1. 新 Local 流程以 **用户显式指令 → Skill → CLI → HTTPS 归档 API** 为唯一正式接入路径；不保留新的 Local MCP 接入选项，不注册任何 SessionStart、PostToolUse、Stop 或子代理事件。
2. 测试开始前无需创建平台 Task、绑定来源、安装 Hook 或保持平台连接。Agent 使用项目既有工具完成测试；首次归档时才需要 CLI、Skill 和有效授权。
3. 用户在 Web 创建或选择 Project 下的 Local 归档任务，按需创建子任务，再在本地指定产物范围调用 Skill。每次上传必填 Project ID、Task ID，Subtask ID 可选；省略时归档到 Task 本身。也允许显式归档阶段性材料；归档不以测试成功为前提。
4. CLI 在用户级全局安装和授权，可跨工作目录、Agent 会话复用；新配对默认授予现有和未来全部项目的归档读写权限，且不设授权到期时间。CLI 是可独立使用的短命进程，无 daemon、定时任务、后台监听或自动刷新。Skill 只在明确归档请求中加载完整指引和执行 CLI。
5. 新 profile 为 `local-artifact-archive/v1alpha1`。新增 Local 专用归档实体，沿用 Project；不共用 CloudTask/CloudAttempt，不新增跨 Local/Cloud 的通用 Task 根表。
6. Local 的产品职责为测试资产归档、查询与汇总，测试仍由本地 Agent 和项目工具完成。Cloud 执行能力、Memory 独立权限及旧执行领域保持各自边界。

本决定替代 ADR-020 在**新 Local 接入流程**中的自动 Hooks/MCP 默认方案，以及 ADR-024/026 在该新归档 profile 中的 native BIND/JOIN 前置条件。旧 SessionTask 记录、绑定、参与关系、回执和历史仍按原合同解释。切换前已部署旧版本继续受旧合同约束；实际部署版本、旧写准入切换及客户端发行身份由本轮交付记录拥有，不改写下方旧版历史。

## 3. 用户流程与组件职责

```mermaid
flowchart LR
    A[本地自主测试并保留原始文件] --> B[Web 选择项目与任务及可选子任务]
    B --> C[复制明确目标的归档指令]
    I[CLI 授权页与一次全局绑定] --> F
    C --> D[显式调用 hypertest-archive Skill]
    D --> E[整理获准文件与 manifest]
    E --> F[hypertest CLI 校验并提交 HTTPS]
    F --> G[确认接受版本和完整读回]
    G --> H[返回任务链接并退出]
```

| 组件 | 职责 |
| --- | --- |
| 本地 Agent | 按用户要求完成测试，保存项目原有正式产物；归档时补充清单与结构化映射 |
| `hypertest-archive` Skill | 解释明确上传指令、解析目标 ID 和文件范围、整理 manifest、调用 CLI、解释结果 |
| `hypertest` CLI | 私有配置、HTTPS、文件读取与校验、冻结请求、账本、提交、回执核验、固定版本读回和原 key 恢复 |
| HyperTest One API | 认证及目标授权、父子关系检查、版本约束、原子接受、历史与回执 |
| PC Web | 全局 CLI 授权页、安装/绑定指导、项目授权与撤销；创建任务/可选子任务、复制指令、查看原件/来源/修订、显式汇总 |

每次归档明确指定 Project ID、Task ID 和产物路径或清单；Subtask ID 可选。不指定子任务时使用 Task 根归档空间，不创建默认子任务；指定无效或越权子任务则拒绝，不回退到根空间。CLI 不从 cwd、profile、上次上传或唯一子任务猜测目标；命令与 manifest 的目标必须一致。关键词只表达用户意图，不进入鉴权协议或成为 CLI 必填字段。所有目标 ID 都是地址，不是凭据。

原会话结束后，用户可以在新会话或终端归档已有文件。归档发生时不补造 SessionStart、caller context、BIND/JOIN 或测试执行记录；尚未留存的原件不能从摘要、对话记忆或散列中恢复。

## 4. 任务与来源模型

领域字段、关系和状态由[领域 §56](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#56-adr-027-local-显式后置归档目标合同)拥有。

新建项目须登记 SUT 仓库与测试框架仓库（可相同），创建 Local 任务时分别选择分支；服务端将当时的两个地址和所选分支固定为任务声明。API 对旧客户端允许未指定分支，历史项目的空仓库字段保留。项目创建不再要求填写默认分支；旧 Project 默认分支为兼容数据，旧任务不补造仓库或分支。分支并非解析后的 commit 或独立执行证明；新的声明不改变本 ADR 的后置归档、Uploader 授权、原 key 恢复及 reported-result 边界。归档 Prompt 如附任务声明，以数据而非指令呈现，仅纳入受限安全格式；历史不安全地址省略并提醒，不改原始记录。这一过滤不是任意路径内容的秘密扫描。Cloud 仍按独立资源修订和任务 selector 冻结，不随 Project 修改重写既有 Cloud 输入。

| 新对象 | 职责 |
| --- | --- |
| LocalArchiveTask | 一次业务测试需求，所属 Project、管理创建者、owner_uploader_actor_ref、管理版本、根归档版本、状态及显式汇总 |
| LocalArchiveSubtask | 工作项或归档分组，所属 Task、authorized_uploader_actor_ref、独立归档版本和 reported result；由用户按需创建，可按会话划分 |
| LocalArchiveSubmission | 一次不可变归档请求、原 key、接受结果与固定版本；同内容提交也有可恢复的回执 |
| LocalArchiveAssetRevision | Task 根空间或指定 Subtask 内按 kind/stable_key 追加的计划、用例和原始报告修订 |
| LocalArchivePublication | 任务整体汇总，冻结 Task 根归档版本、所采用的子任务版本与产物引用 |

子任务 ID 不复用 participant ID、contribution ID 或宿主 session ID。同一子任务可以追加多次提交，同一会话可以为多个业务工作项提供来源材料；来源字符串不承担写入权限或全局唯一约束。

上传者由认证信息确定，Web Operator 创建者与 integration uploader 分开记录。未指定 uploader 的 Task 可保存草稿，全项目 CLI 授权可归档该任务；定向授权须匹配 owner。首次接受归档后 owner 不可改写。`origin_provider`、`origin_session_ref`、测试发生时间和报告生成时间是可选的逐资产来源声明，平台接受时间由服务器生成。同一批多会话材料分别保留各自来源。UI 分别展示上传者和原测试来源，不将材料声明展示为已核验 native 会话。报告中的 PASS/FAIL/UNKNOWN 原样保留；归档成功与整体测试完成分别表达。

所有上传均使用目标空间的 `expected_archive_version`：Task 根空间和各 Subtask 的 `archive_version` 分别推进；Task 的管理 `version` 与根归档版本分开，避免根上传与子任务上传相互争用。任务元数据、子任务目录/授权调整和汇总使用 `expected_task_version`。整体汇总在同一事务验证 Task 根归档版本及明确的子任务版本向量，之后的新上传不改写旧汇总。

## 5. 授权与可靠交付

新权限为 `archive:read` 与 `archive:write`；CLI 完整归档需同时具备两者。沿用 integration actor/client/Project 的私有授权设施，服务端核 Project 和父子关系；定向授权还核 Task owner 和指定子任务的 uploader。全项目 CLI 授权可归档任意 Local 任务与子任务，但提交与修订使用真实上传 actor，不改历史 owner、来源和结果。

`task:sync`、`cloud:work` 和 Memory scope 不自动获得归档权限。Web 使用其既有 Operator 管理边界批准项目授权；CLI 不取得 Operator key，也不自助扩大授权。凭据仅由客户端从私有配置读取，不写入 Skill、manifest、命令参数、日志或响应；私有文件不被宣称为同 UID 进程隔离。

**2026-10-27 授权入口增补：本段替代首片要求用户选择既有上传 actor 的规则。** 新配对批准核对短码和客户端；2026-10-28 起默认全部项目、归档读写权限和永久有效。服务端按稳定的 `connector_operator_identity` 解析专用 CLI 上传身份，首次有效批准时在同一事务创建 integration actor 和不可变 `CliArchiveUploader` 映射；同一 Operator 跨设备复用该 actor。映射以 `operator_ref` 唯一、`actor_identity_id` 唯一外键约束，不按昵称、主机名、客户端自报身份或历史 ACTIVE 列表推断关联。专用 actor 或客户端已撤销时拒绝新批准，不能另建身份绕过撤销；全项目授权覆盖以后新增的项目；符合条件的存量 CLI 绑定也通过独立升级记录获得全项目永久授权，原批准与 grant 不改写，已整体撤销绑定不复活。

PC Web 增加全局「CLI 授权」页，提供版本明确的安装/升级指引、无秘密的一键绑定命令、已授权客户端/项目/期限与撤销入口。已实现的绑定命令为 `hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default`；可选 `--project-id` 仅预选项目，不产生权限。具体操作见[CLI 授权指南](../CLI_AUTHORIZATION_GUIDE.md)。

CLI 发起短时配对，用户在既有 Web 登录下核对短码、客户端并一次确认默认全部项目的 `archive:read/write` 永久授权；批准结果同时冻结服务端解析的专用 actor。CLI 完成原请求兑换、确认并保存全局 profile 后退出。短码/URL 不能兑换凭据，命令不携带 token；不需要本地回调服务。CLI 在发送前私有持久保存高熵 credential、独立配对 verifier 和原 key，服务端只接收必要验证材料；失答后凭原 key 确认固定授权，无需重新签发或取回明文 secret。精确配对/恢复合同由 TMP§51.4、领域§56.5拥有。全项目授权动态覆盖当前及以后新增的 Project；访问时按项目解析独立 integration grant 并映射到该配对（写事务提交时持久化，只读请求回滚），各 grant 保持独立、唯一的 `token_hash`，不会把同一 credential hash 写入多个 grant。归档鉴权仍按显式 Project 和当前 actor/client/grant 状态、scope 与可选期限校验。

profile 固定规范化 server、client、uploader actor 及批准范围，不与仓库绑定；凭据按服务器与身份隔离，不因切换目录/任务自动换 profile。全项目授权自动覆盖以后新增项目；符合条件的存量绑定按领域 §56.5 升级，新批准不接受调用者选定 actor。旧 APPROVED/BOUND 请求、grant、Task owner 和接受回执保持原 actor，不自动改写归属。旧带 actor 的 APPROVE 正文仅用于已接受原 key/原正文的精确回执恢复，没有原回执的新写明确拒绝；旧 `/cli-authorizations/actors` 列表返回 410。任务创建页不要求选择上传身份，创建请求省略 owner 字段；服务端在项目仅有一个有效归档 actor 时自动指定该 actor，否则保持未指定。归档任务详情的 owner 管理仍按项目有效归档授权（包括全项目授权）运行。服务端撤销和本机退出分别表达，保留已接受档案与私有未决账本；只有命令存活期间为配对完成做有界查询，不后台轮询或续签。

上传仅从显式批准的清单读取文件，文件内容为数据，不能驱动 shell 命令或授权。首片支持 UTF-8 计划/原始文本报告与结构化用例，保留原文和稳定业务 key。接口按条数、字符数及总字节有界，超限明确拒绝，不截断、不隐式分批；截图、视频和压缩包的二进制存储协议独立后续设计，不以本地路径或 URL 引用冒充已上传文件。

每次请求明确 upsert 所选资产的完整内容/结果/来源，省略旧资产不删除；子任务状态/结果只更新明确出现的字段，不将缺省或 null 当作清空。根归档不接受 `subtask_update`，也不更新 Task 整体状态/结果；整体汇总仍由 Web 显式发布。CLI 依据固定基线冻结本次预期合并结果，读回完整接受快照；这属于新归档协议，不改变旧 full sync 的含义。

复用 TaskSyncCore 的冻结、账本、回执和读回机制，通过新的 ArchiveAdapter 接入。请求、文件字节、目标、结果、来源和预期版本在发送前固定；POST 前持久化 SENT。失答、UNKNOWN、NOT_FOUND 只查询原 key，不改正文/版本、不换 key 重发。

幂等 key 绑定 actor、Project、Task、target_kind、可空 Subtask、profile 与完整请求。当前授权检查后先查原 key，再检查新请求版本；同 key 同输入返回原结果，异输入拒绝。同内容且当前版本匹配的新意图返回 UNCHANGED，仍保存可恢复的 Submission/回执，业务版本和资产修订不增。一次新的测试活动须保留新的来源发生记录或明确资产 key，不能仅按文件 hash 抹掉它。

只有回执字段和固定接受版本的完整内容核对一致，CLI 才返回归档完成。上传传输状态不覆盖 reported result，也不升级 legacy VERIFIED、Verdict 或 RELEASE_READY。

## 6. CLI 与显式 Skill

协议由 [TMP §51](../protocol/TEST_MISSION_PROTOCOL.md#51-adr-027-local-显式归档协议目标合同)拥有。首版公开命令为 `hypertest auth`、`profile`、`doctor`、`archive`、`status`、`reconcile` 、`skill install`，以及用于旧安装维护的 `legacy retire/reconcile`。`archive` 是一个主动作，不要求用户依次运行多个内部准备命令。`--dry-run` 完成所需校验并预览目标/产物，不提交业务变更；`--json` 返回稳定结构，日志写 stderr 且不含凭据。

已实现的调用形式（须使用实际目标和获准产物）：

```bash
hypertest archive --profile default --project-id PROJECT_UUID --task-id TASK_UUID \
  --manifest ./archive-manifest.json --json

# 需要归档到子任务时才增加 --subtask-id SUBTASK_UUID
```

Skill 随 CLI 同一受控版本分发，名称为 `hypertest-archive`。在支持显式调用策略的宿主上关闭隐式调用，例如 Codex 的 `allow_implicit_invocation: false`；Web 给出包含显式 Skill 引用、Project ID、Task ID 和可选 Subtask ID 的可复制指令。支持用户级 `hypertest skill install --global --host codex`，其他宿主仅按核验能力提供全局安装；不在各项目植入自动同步指令。其他宿主采用各自明确的 Skill 选择方式，未核验的能力不标支持。自然语言“测试完成”本身不自动启动归档，也不推导 PASS。机制依据见 [OpenAI Skills](https://learn.chatgpt.com/docs/build-skills)。

Skill 不监听聊天、修改测试指令、定期读取状态或扫描整个工作区；由用户在归档调用中指定正式产物范围。CLI 结果 UNKNOWN 时引导原请求查询，REJECTED 时报告具体拒绝原因，不启动自动重试循环。用户明确给出的归档指令已经授权该范围提交，不再增加固定二次确认。

CLI 与 Skill 采用独立 `cli-vSEMVER` 发行线及固定来源/资产摘要，新安装只提供归档所需依赖。已有 `local-v*` 和 `mcp-v*` 保留原版本身份；新升级入口识别旧安装并执行受管配置迁移，不把旧 tag 内容替换成 CLI 包。

## 7. MCP 和 Hooks 移除与历史兼容

| 范围 | 目标处置 |
| --- | --- |
| 新 Local 包和安装入口 | 不安装 MCP server、Hooks、native event bridge、daemon/IPC；提供 CLI 和归档 Skill |
| 已有受管宿主配置 | 按安装收据精确移除 HyperTest 自有 MCP 项、Hook 组和插件 bridge；其他服务/配置保持，配置漂移时保留原件并明确指出冲突 |
| 旧接入 Skill 和自动同步提示 | 从新包与默认安装中移除，以显式归档 Skill 替代；精确升级自有文件，保留用户修改的冲突副本 |
| 本地旧进程和状态 | 停止自有同步触发/daemon；保留私有授权、journal、冻结请求、源文件及安装/迁移收据 |
| 旧服务端写入口 | 在新链路可用后的明确切换点关闭新 CREATE/BIND/full-sync/ENABLE/JOIN/CONTRIBUTE/PUBLISH 等 Local 会话写入准入；已接受回执与固定版本读取继续可用 |
| 旧请求恢复 | `hypertest legacy reconcile --config FILE --request-id KEY` 对明确旧账本的 SYNC/BIND/协作原 key 只读查询及固定版本读回；CREATE 保留原 Web journal 恢复，不重放旧 POST，不合并 namespace，不扫描其他 root |
| 旧业务记录与发行物 | 保留 SessionTask、成员、贡献、报告、回执、失败原件、tag/digest；不自动转换为归档实体，也不重标旧验收 |

旧 compact journal 未保存完整原正文时，CLI 只报告 `LEGACY_ACCEPTED_READBACK` 与 `original_request_verified=false`；不得从接受快照重建或宣称比较了不存在的原请求。完整冻结请求恢复核对原内容后才报告 `LEGACY_RECOVERED`。原 journal 不改写，恢复记录单独保留。

切换前在途且已经进入服务端事务的请求按原协议完成接受或拒绝，结果仍可按原 key 查询。已在本地冻结但未决的记录不因卸载或切换被清除；无回执不能推断未执行。无需等待所有历史 UNKNOWN 消失才发布新流程，也不得把它们重发至新归档接口。

“移除”适用于当前 Local Agent 接入产品和其安装/运行依赖；其他插件的 MCP、Cloud 内部工具、独立 Memory 服务和历史执行系统不因名称包含 MCP/Hook 被批量删除。依赖审查后只删除没有兼容读回/恢复消费者的旧实现；共享库不能随入口一起移除。旧读恢复也不要求重新安装 MCP/Hooks。

## 8. 开发顺序与完成条件

1. **领域和 API**：实现新表、CLI 配对授权及撤销、任务/可选子任务管理、根及子任务原子归档、幂等回执、固定版本读取和显式汇总；迁移保持旧表和历史。
2. **CLI**：增加统一入口和 ArchiveAdapter，复用私有配置/账本；提供全局 profile、一次绑定、JSON、诊断、授权/归档原 key 恢复及旧账本只读兼容。
3. **Skill 与 PC Web**：实现全局 CLI 授权页与操作指南、全局显式 Skill、任务/可选子任务创建、复制指令及原件/版本/来源展示，取消旧 native 会话绑定与 Hook 信任步骤。
4. **退出旧接入和发行**：移除新包 MCP/Hooks/daemon 依赖，完成精确配置迁移、旧写准入退休及独立 CLI 安装发行。
5. **部署与交付**：按仓库测试服务器流程从已推送 Git 构建、非破坏迁移和最小冒烟；代码自测、部署、客户端发行、USER_OWNED 功能验收分别记录。

上述领域/API、CLI、Skill、PC Web、轻量发行构建和旧入口退休代码均已完成；`0030_local_archive` 与 `0031_cli_authorization` 为新增迁移。服务端新旧写准入错误为 `LOCAL_SYNC_RETIRED_USE_EXPLICIT_ARCHIVE`，既有回执查询保留。部署、发行和 USER_OWNED 状态以[本轮交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)逐项记录。

关键自动化验证集中在本次新增授权/跨目标拒绝、版本冲突、same-key/UNKNOWN、原文与失败历史保全、旧配置精确移除和原 key 只读恢复；普通命令与文案不另建全量宿主矩阵。本轮规范状态更新只检查文档差异；产品代码自测与部署记录另列，不触发额外业务验收。

交付完成应同时满足：新 Local 测试过程中无 HyperTest 自动同步；可在测试结束后以项目/任务 ID 和可选子任务 ID 显式归档；CLI 与 Skill 可独立安装使用；旧自有 MCP/Hooks 配置可安全移除；历史与未决原请求仍可读回；官方新入口不再引导用户启用旧同步。
