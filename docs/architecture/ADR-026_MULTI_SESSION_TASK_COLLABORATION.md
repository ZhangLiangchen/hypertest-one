# ADR-026：Local 测试任务的多会话参与与并行贡献

**适用范围：旧 Local SessionTask 协作与历史合同。** [ADR-027](ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 的独立归档 Task/Subtask 和显式 Skill/CLI 已实现并部署，见[归档交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)。本文的 participant、contribution、native JOIN 与 PRIMARY 合同继续解释旧会话任务及历史；不得将这些 ID/角色重标为新归档子任务或上传身份。

**状态：Accepted design / 首片源码已实现（2026-10-26，Asia/Singapore）。** 用户已要求实现测试任务与本地会话的一对多绑定；源码、自动回归、部署、Local 发行与 USER_OWNED 功能验收分别记录，见[本轮交付](../MULTI_SESSION_LOCAL_DELIVERY_20261026.md)。

**范围：同一 Local SessionTask 由多个真实独立会话参与；贡献可以并行准备和提交，任务整体状态由一个当前主会话汇总。**

初版 `0985289` 仅记录 Proposed 设计，未实现能力；本次按用户指令接受并实施。下文只替代显式启用协作 profile 的 Local 任务规则；未启用任务及已公开旧客户端继续使用 ADR-018/024 单会话合同，不自动迁移为多会话写入。标准 A2A adapter、跨 actor 协作、真实模型/SUT 与用户功能验收不包含在本轮实现范围。

## 1. 背景

一项测试任务可能需要多个独立会话分别完成分析、接口测试、界面测试、失败诊断和交叉复核，也可能在原会话结束后由新会话继续。任务目标和已接受产物应能持续存在，各会话应保留自己的真实来源与贡献。

当前 Local 将任务与一个真实父 `(provider, session_id)` 一次性绑定。原生 child 可以回交父会话，但独立 root 不能加入同一任务。现有 `hypertest_sync_task` 提交完整任务字段，并按任务内稳定 key 保存用例与报告；它不是成员贡献的 PATCH。仅放宽 BIND 或把 session 改为数组，会让多个客户端争写整体计划、进度和 reported result。`expected_version` 能拒绝旧版本，却不能判断读回新版本后再次提交的完整快照是否在语义上覆盖其他会话的成果。

因此，本提案将稳定的业务任务、参与会话、贡献修订和当前汇总责任分别建模。Agent 继续在项目已有工具链中完成测试；平台管理授权、产物接受、历史和汇总结论，不新增通用 Agent Loop 或测试执行引擎。

## 2. 替代范围与规范归属

| 现行规则 | 多会话合同的目标变化 | 保留边界 |
| --- | --- | --- |
| ADR-018 / 领域 §50：一任务只有一个来源会话 | 一个 SessionTask 可有多个真实 root 参与者 | 原 UUID、Project、初始来源、owner 和历史不改写；首版同一来源仍只能属于一个任务 |
| ADR-024：第二个会话不能绑定已 BOUND 的任务 | 第二个会话通过独立的授权与 JOIN 成为参与者 | 原 BIND 仍只建立初始绑定，不通过重绑更换来源 |
| ADR-020：child 回交父会话、一个 root 一个协调器 | 独立 root 各有协调器，分别提交自己的贡献 | child 不自动成为独立 writer；Hook/MCP 仍共用各 root 的目标、锁与账本 |
| ADR-018 / TMP §45：完整任务同步 | 增加有类型的成员、贡献、汇总与交接操作 | 旧 full sync 不自动变成多写者接口；原 key、原件、版本和回执语义保留 |
| ADR-021：Local/Cloud 分别适配 | Local adapter 可消费新增协作合同 | 不合并 Task 实体、权限、执行控制或 journal；Cloud writer 边界不变 |

本 ADR 在显式启用的 `local-task-collaboration/v1alpha1` 合同内 supersede 上述一任务单来源限制，初始 BIND 来源仍一次性不可变。字段、协议和组件分别由以下规范拥有；本次同步适用范围，不通过单独删除数据库约束或客户端拒绝逻辑实现协作：

- [领域模型 §50、§52、§53](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)：实体、来源唯一性、角色、版本、历史和持久化约束。
- [TMP §45、§47、§48](../protocol/TEST_MISSION_PROTOCOL.md)：协作 profile、操作载荷、错误、能力协商、幂等与读回合同。
- [技术架构 §46、§47](HYPERTEST_TECHNICAL_ARCHITECTURE.md)：协调器、服务接受边界及两个 adapter 的隔离。
- [白皮书 Local 入口](../foundation/HYPERTEST_WHITEPAPER.md)：任务独立于参与会话的产品语义；同步更新 `AGENTS.md` 的适用规则。

## 3. 任务身份与参与关系

沿用现有 SessionTask，不新增通用 Task 根表、跨模式任务别名或自动合并机制。增加以下逻辑对象，具体持久化合同见领域 §50.6：

| 对象 | 目标职责与约束 |
| --- | --- |
| TaskSessionParticipant | 稳定 participant ID、Task/Project、真实 provider/session、actor、角色、分工、成员状态及加入/撤销历史；来源不可改写 |
| ContributionRevision | Task、participant、贡献类型、成员内稳定 key、递增 revision、完整内容或获准引用、基线版本、原 reported result、来源与接受时间；修订只追加 |
| 协作管理与操作回执 | ENABLE、成员授权/JOIN/撤销、汇总、交接的完整非秘密请求身份、原 key、接受版本、冻结快照及审计；与现有 SyncReceipt 分开 |
| 当前汇总责任 | 当前 primary participant 与严格递增的 primary generation；它表达可交接角色，不替代初始绑定来源或 owner |

初始绑定的 provider/session、owner、bound_at 和既有 BIND 回执始终保留。新参与者加入、退出或成为主会话均不覆写它们。任务为 UNBOUND 时仍没有真实参与者；首个主会话先按 ADR-024 完成真实绑定，再进入协作合同。

一个任务可以有多个参与者；首版一个真实 `(provider, session_id)` 仍至多属于一个 Local 任务，软删除或成员撤销均不释放其历史来源。实施时必须由同一个数据库约束边界覆盖初始绑定与全部参与来源，不能在两张表各自 UNIQUE 后留下跨表重复。旧来源映射为同一任务的初始参与者时，只建立可追溯关系，不制造第二个任务或重写历史版本。

已有 Task A 的会话不能借 JOIN 合并到 Task B。需要关联前序工作时保存显式引用，原任务、失败报告、版本和回执各自保留。

## 4. 成员授权与真实调用来源

首版限制所有参与者使用任务既有 `owner_actor_ref`，并继续核验当前 integration actor/client/Project `task:sync` 授权。跨 actor 协作及其历史读取 ACL 留待后续决定；成员登记不自动开放其他 owner 或 Project 的数据。

Operator 明确授权目标 Task、精确 actor 和拟加入的 provider/root session；拟加入来源在 JOIN 前只是授权意图，不得显示为已核验的参与会话。JOIN 由该真实 root 的受支持宿主 adapter 发起，同时核对授权意图、native root、当前调用来源、workspace 和批准产物策略。授权、JOIN 和撤销分别留历史，不以知道 Task ID、父 session ID 或成为 A2A 通信对象代替授权，不另行给 Agent 发 Operator key。

本地逐调用 caller fence 继续适用，模型参数不能覆盖宿主上下文。当前已核对的 Codex CLI `0.144.6` 路径不自动扩展成其他版本或宿主资格；缺失、错配或未实现的 adapter 明确拒绝新 JOIN/贡献/汇总，不退回旧自动任务创建。该 fence 仍是正常宿主内的本地来源约束，不提升为服务端独立的原生会话身份证明。

原生 child 保持父 root 内部委派身份，向父会话交付产物，可以保留 delegation/source metadata，但不能填写父 ID 取得独立参与者或汇总权限。独立 root 加入同一任务时保留自己的来源，不伪装成原父会话。若宿主未来支持 child 独立参与，须另行定义其归因、授权和生命周期合同。

成员撤销阻止其新贡献、普通协作读取和汇总，既有贡献及回执不删除。只读对账继续核验当前授权和原提交身份；已失权时保留未决账本，由获授权恢复路径处理，不能为了对账自动恢复成员权利。

## 5. 并行贡献与单一汇总责任

PRIMARY 与 CONTRIBUTOR 是任务内角色。同一时刻至多一个有效 PRIMARY；首次启用时由初始绑定会话承担。安全撤销主会话后可以暂时没有 PRIMARY，此时贡献者仍可按当前授权提交贡献，但整体汇总暂停。

| 能力 | CONTRIBUTOR | 当前 PRIMARY |
| --- | --- | --- |
| 在授权范围读取任务、分工和已接受产物 | 允许 | 允许 |
| 提交自己的计划建议、用例、原始报告和复核意见 | 允许，使用自己的贡献命名空间 | 允许，同样保留来源 |
| 修改其他成员的贡献修订 | 拒绝；可以提交引用原修订的复核或替代建议 | 拒绝覆写原件；可以明确采纳或合并为新修订 |
| 修改整体 title/objective/plan/status/reported_result | 拒绝 | 通过受当前角色与 generation 约束的汇总操作提交 |
| 授权、撤销成员或交接主会话 | 无自动权限 | 无自动权限；由既有 Operator 管理授权执行 |

贡献至少以 `(task_id, participant_id, kind, stable_key)` 标识，修订在该范围内递增。同名文件或相同 case/report key 不自动属于同一共享资产。并行贡献先分别保存，汇总操作引用准确的贡献 ID/revision，明确采纳、合并或保留分歧，并给出共享用例/报告 key 的映射；不引入隐式文本合并。

首片以 ContributionRevision 和 TaskPublication 保存原贡献与显式映射，不将 PUBLISH 的引用物化为旧 CaseRevision/ReportRevision；旧资产与新协作贡献分别展示。需要合并正文时，先由当前会话提交一份保留前序引用的新贡献，再显式发布准确修订，不能把 MERGED 标记解释为平台已执行内容合并。

来源同时记录原贡献者与汇总提交者。汇总不得把所有产物归于主会话，也不能把独立复核意见改写为原测试执行。原 FAIL、UNKNOWN、被替代内容和不同判定口径保留可查询；新 PASS 可以形成新报告或汇总结论，不能删除失败历史。

成员进度、任务进度、贡献中的 reported result 和整体 reported result 分别表达。成员完成、所有会话 idle、Hook Stop 或 A2A completed 都不自动令任务 COMPLETED/PASS。整体完成必须由主会话明确提交依据，列明仍有的缺口、分歧和未决事项。相关 UNKNOWN 必须先对账或明确保留为阻塞，不能以换会话洗掉；未决事项不阻止保存无依赖的其他贡献。

以上仍为管理产物接受与提交者报告，不自动产生 legacy VERIFIED Evidence、正式 Verdict 或 RELEASE_READY，也不要求平台执行或独立 CI 证明后才保存贡献。

## 6. 接受版本、幂等与协调器

协作 profile 为 `local-task-collaboration/v1alpha1`，区分 ENABLE、AUTHORIZE、JOIN、REVOKE、CONTRIBUTE、PUBLISH 与 HANDOFF；操作及固定版本读取的精确 wire 由 TMP §45.5 拥有。已有公开 Local 包不因平台新增接口自动具备这些能力。

首版复用 PostgreSQL 任务聚合锁和严格递增的 `task.version`。成员变更、贡献接受、汇总及交接都在同一接受事务中追加对应历史、固定任务快照、回执与 Audit/Outbox。固定版本读取必须重建当时的成员、主会话代次、贡献修订和整体结果，不能用最新 roster 或最新报告拼装过去。

每次新变更使用当前任务版本（wire 字段为 `expected_version`）；贡献另核所属稳定 key 的预期 revision，汇总与交接另核 primary generation。不同会话可以并行计算和上传允许的材料，服务端按版本串行接受。版本冲突先明确拒绝；只有已确认未接受的操作，才可读取新基线，形成真实的新提交意图。不能自动重基并重放被冻结请求。首版接受此并发竞争成本，不引入分支状态库、CRDT 或复杂调度器。

新操作沿各自有类型的操作命名空间使用稳定 key，绑定 Task/participant/actor/操作类型、完整输入摘要、预期版本及适用 generation。原 key 查重先于当前版本/角色检查，在当前有效的对账授权下，同输入返回原固定接受回执，异输入冲突；原已接受结果不因后来交接或撤销变成一次新写入。

请求发送前冻结完整输入并持久记录意图。SENT、UNKNOWN、失答及原 key NOT_FOUND 只继续原 key 查询；不换 key、换会话、换任务、修改 generation 或自动再次 POST。有效 ACK 后须完整读取固定接受版本，核对真实来源、贡献引用和内容，才确认交付完成。同步 UNKNOWN 不改写任何 reported result。

每个真实 root 继续复用自己的 LocalSyncCoordinator、Hook/MCP writer 锁和私有 journal，账本额外区分 Task、participant 和操作。会话锁只能协调该 root，跨 root 一致性由服务端聚合锁和角色/版本约束保证；不通过共享全局 journal、扫描其他会话目录或复制认证实现协作。

## 7. 主会话交接与迟到请求

主会话是可交接的责任角色，初始绑定来源和 task owner 保持不变。交接由 Operator 明确选择同一任务的 ACTIVE 参与者，核对当前授权、expected_task_version 和原 primary generation，在同一事务中递增 generation、切换 PRIMARY、追加交接快照及回执。旧主会话可以保留 CONTRIBUTOR，或在同事务中被撤销，但不再提交整体快照。

整体汇总请求必须同时匹配当前 participant、PRIMARY 角色、generation 和任务版本。旧主会话在途新写若先被接受，交接的旧版本请求必须冲突；交接先被接受，旧角色/代次的新汇总必须拒绝。已经接受的原 key 仍只返回原接受结果，不复活旧写权。

正常交接前先对账相关未决写。旧主会话失联或安全撤权时，允许先 fence 其新写入并保留无主状态；不能因无法确认旧进程停止而放任其继续写。交接到新主会话也不能删除或重新发送旧 UNKNOWN，新主会话须读取接受历史与未决交接清单，仅推进不依赖未知结果的工作，不能据此宣称原副作用已停止或相关工作已完成。

交接清单只汇集明确提交的交接材料、已有回执及服务端已知操作，并注明完整性与未观察范围；平台不能从接受回执枚举旧 root 私有 journal 中的全部发送意图。旧 root 失联、无法提供完整清单时，未观察到记录不证明没有未决操作，相关工作范围保持阻塞，新主只推进无依赖工作，不扫描其他 root 私有目录补造清单。

首片实现结构化交接清单的保全、任务版本与角色代次 fence；不实现跨 root 私有 UNKNOWN 自动枚举或从自由文本解析工作依赖的引擎。各客户端继续保全自己原 key 并阻止越过本 root 未决写；交接材料和 completion_basis 是提交者声明，不能据此声称已自动证明旧副作用停止或所有依赖已解决。

交接本身同样使用冻结请求、原 key 查询和固定接受版本读回。交接失答时不得另选成员再发一次交接或替换 generation。平台管理角色切换不恢复原生会话、不启动模型、不取消或重跑 SUT；测试工具链和外部副作用仍按其原授权分别处理。

## 8. 旧任务与客户端兼容

既有任务默认继续单会话合同。启用多会话必须显式选择支持协作的 profile，在当前版本下确认初始主会话及成员授权；不能因发现多个目录、A2A 消息或安装新版包而自动启用。

原 SessionTask UUID、Project、初始来源、owner、case/report 修订、管理历史及 CREATE/BIND/SyncReceipt 保持原义。新增参与者索引可以引用旧初始来源，但不能为过去版本补造 JOIN、同步时间、贡献者或新验收事实。软删除不删除成员历史或来源唯一性，已删除 Task/Project 拒绝新加入与新贡献，恢复不更换原身份。

对未启用协作的任务，旧 `hypertest_sync_task`、读取和原 key 恢复继续按原合同工作。对已启用协作的任务，旧 full sync 的新写入必须明确拒绝并指明需要协作 profile，避免没有 participant/generation 的旧客户端覆盖整体状态；同一旧 key 的历史查询/已接受结果仍按原身份处理。当前多会话视图使用新 profile，不能静默把全部贡献标成初始会话来源；旧固定历史版本和获授权原回执继续可读。

新版协作能力应明确报告支持的操作。若首片未实现交接，必须返回未支持，不能回退为重绑、修改 session ID 或重新建任务。关闭协作写入口保留历史与原 key 查询，不把已启用任务自动降回旧 full sync 合同。安装、升级、回退和卸载继续保留来源、源产物和未决 journal；旧包无法解释新账本时明确阻塞，不静默丢弃。

`local-v0.1.0`、`local-v0.1.1-rc.1` 及既有三宿主证明不因本提案升级资格；新 API、客户端发行与真实宿主能力分别验证和记录。

## 9. A2A、Cloud 与产品边界

多会话参与和标准 A2A 接入分别交付。A2A 的 `contextId` 可以关联多个 Task/Message，协议中的 task/context 标识用作带 provider/endpoint 的外部来源映射，不等同于 HyperTest 的 Task ID、平台成员资格或宿主身份。[A2A 官方任务生命周期说明](https://a2a-protocol.org/latest/topics/life-of-a-task/)可作为 adapter 设计参考；具体接入须冻结协议版本与实际宿主能力，不预设所有 Agent 都实现同一种 A2A。

A2A、宿主子代理能力或人工启动的独立会话都可以交付协作成果。平台只接收批准的结构化意图和正式产物，不扫描聊天、思维链、认证目录或完整原始工具事件来恢复状态；首版不实现 Agent 发现市场、通用消息总线或自动分派执行。

本提案首片只针对 Local SessionTask。Cloud 可在未来用参与者视图展示 delegation 来源，但仍由当前 fenced Worker 经 CloudSyncAdapter 唯一提交，根/子 Agent 不持平台 writer token、Operator key 或 DB 权限。CloudTask/Attempt 与 Local Task 不转换、不合并，不共享凭据、journal 或执行权；共享 Project 不改变这些边界。

Web 详情需区分初始绑定、当前主会话、参与成员、分工、原贡献和汇总结论，展示交接与来源历史。界面实现继续只覆盖 PC 宽屏，中英文、键盘、焦点及可读性要求沿用现行约束。

## 10. 取舍与实施顺序

| 方案 | 取舍 |
| --- | --- |
| 多 root 共同调用现有 full sync | 不采用；整体字段和共享 key 容易语义覆盖，旧版本检查不能表达分工与责任 |
| 一个 root 的内部 child 协作 | 保留；适用于宿主内委派，不能覆盖多个独立 root 或跨会话接力需求 |
| 每个会话建任务，再自动合并 | 不采用；任务身份、失败历史、授权和原 key 无法由自动合并安全替代 |
| 多参与者追加贡献，单一主会话汇总 | 采用；接受服务端版本串行化成本，保留来源、明确整体写入责任 |

建议先实现：规范与协作能力合同、参与者及数据库约束、窄贡献操作和固定版本读取、主会话汇总、客户端协调与 PC 详情展示。显式交接和 A2A adapter 可以分别交付，未交付操作明确拒绝。涉及 TaskSyncCore 的改动须验证 Local/Cloud adapter 隔离，不要求迁移 Cloud runtime 或扩大真实业务测试范围。

本轮按本 ADR 实现管理链路；部署、客户端发行和 USER_OWNED 功能验收分别记录。当前进度由[TODO](../TODO.md)与[本轮跟进](../FOLLOWUP_DELIVERY_20261023.md)维护。

## 11. 后续实现必须覆盖的断言

1. 两个获授权独立 root 可加入同一 Task，并行贡献不覆盖对方；两个 root 同时争取初始主绑定仍最多接受一个。
2. 同一真实来源不能进入另一 Task；初始绑定与参与关系的跨表竞争、软删除及撤销后唯一性均受数据库约束。
3. 未授权、错 actor/Project、撤权、缺失或错配 caller、原生 child 冒用父 ID、未知宿主均拒绝新写，不自动建替代任务。
4. 贡献命名空间隔离；同名 key、原 revision 冲突、复核建议及明确合并保留原文、作者、旧 FAIL 和分歧。
5. CONTRIBUTOR 不能更新整体字段；任何新汇总必须匹配当前 PRIMARY、generation 和版本；旧 full sync 不能绕过协作合同。
6. 成员、贡献、汇总与交接的任一固定版本可完整重建；绑定、成员加入、贡献和汇总各自时间与来源不混记。
7. 同 key 同输入返回原接受结果，异输入冲突；失答、重启、UNKNOWN/NOT_FOUND 只原 key GET，不重基冻结请求、不换会话重发。
8. 汇总与交接竞争、旧主会话迟到写、交接失答、主会话撤销及相关未决写均保留原件与回执；新角色不能清除未知副作用。
9. 旧单会话任务继续工作；多会话启用显式、回退不开放旧写入，旧 ID、owner、来源、历史与发行资格不变。
10. 成员完成、A2A completed、SDK idle 和上传成功不自动成为任务完成、PASS 或独立执行证明；协作管理不启动模型/SUT。
11. Cloud 关闭或故障不影响 Local 协作与历史；Local 新增能力不向 Cloud Agent 暴露 writer 凭据，不改变 Cloud lease/generation。

以上是相关实现必须覆盖的回归范围，实际结果以本轮交付记录为准；这些断言本身不是宿主验收或每次测试服务器部署的额外 Gate。
