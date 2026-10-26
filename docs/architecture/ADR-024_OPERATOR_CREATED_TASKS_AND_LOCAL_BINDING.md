# ADR-024：统一任务创建与 Local 预创建显式绑定

**2026-10-26 增补：[ADR-026](ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)通过显式 ENABLE、精确成员授权与 JOIN 扩展已 BOUND 的 Local 任务；初始 BIND 来源仍一次性不可变。下文“一个任务不能绑定两个来源/新会话需独立任务”仅继续约束初始 BIND 与未启用协作的旧合同，不阻止新 profile 的参与关系。原授权链、caller fence、历史与 UNKNOWN 原 key 对账保留。**

**状态：Accepted design（2026-10-23，Asia/Singapore）；实现、远端验收与客户端发行分别记录。**

**决定方：项目负责人。范围：同一 Project 内的创建入口与 Local SessionTask 绑定，不接管独立 Cloud 实施。**

## 背景与约束

项目页需要“创建测试任务”入口，允许选择 Cloud 或 Local。CloudTask 是平台云端任务，Local 使用真实父会话的 SessionTask；二者共享 Project，不共享任务身份、写权限或执行生命周期。Cloud 的 ADR-019 和未合入候选由独立会话维护，不能把云端 Task/Attempt ID 填进 Local session_id，或以 SessionTask 表单代替 Cloud 创建/下发。

ADR-018 原同步以真实 `(provider, session_id)` 首次提交创建任务。ADR-020 的 SessionStart 只建立私有 root context，批准产物出现后才同步；Hook 与显式 MCP 使用同一协调器。现在需要先在平台取得明确 Task ID，再由本地真实父会话绑定，避免来源错位或两条入口各自建任务。现有自动同步任务及其历史必须可继续读取、对账与 resume。

本决定对 ADR-018 的“首次同步创建”增加明确的 Operator 预创建路径，对 ADR-020 新 Local 会话增加首次产物前绑定门槛；旧源码/发行/验收证明保持原样。领域 §50.5、TMP §45.4 拥有具体字段与接口。

## 决定

### 1. 一个创建入口，两种有类型的任务

UI 的 Cloud/Local 选择只路由到各自领域接口，不设置排他的 Project 模式，也不建立通用 Task 根表或通用 dispatch/sync API。列表和链接使用 `(task_kind, task_id)`；进入详情、修改、下发或绑定时仍按原类型鉴权。选择 Local 不要求云端 Git、模型或环境凭据；绑定不运行本地 Agent、SUT、Runner 或 Cloud Worker。

Cloud 保留创建 DRAFT、解析/冻结输入、显式下发和 CloudAttempt 所有权。不能把“创建成功”显示为已经下发或执行，Cloud 未接入/关闭时也不能退回 Local 冒充云端任务。该部分实现合同仍由 Cloud 所有者交付。

### 2. 在现有 SessionTask 上增加 UNBOUND → BOUND

采用同一 SessionTask UUID，不新增跨表 LocalReservation 或任务别名。新增 `binding_state`、`binding_required`、`creator_actor_ref`、`intended_actor_ref`、`bound_at`：

- Operator 预创建记录为 `UNBOUND`、`binding_required=true`，初始 `version=1`、DRAFT / NOT_RUN。provider、session_id、owner_actor_ref、source、last_synced_at、bound_at 均为空，不造占位会话或 Agent 同步。
- creator_actor_ref 是创建操作者，不能自动成为 Agent writer owner。intended_actor_ref 是已授权、允许绑定的 integration actor；不是凭据。
- BIND 一次性将真实 provider / 父 session_id、当前授权 actor owner、BOUND 和 bound_at 原子写入同一记录。绑定不改业务进度、reported result、用例或报告；source 和 last_synced_at 仍为空，直到首次真实产物同步。
- 成功绑定后 Project、来源对、owner 不再改变，不提供解绑后换会话。软删除不释放来源唯一性，恢复不改绑。新原生会话需要独立任务并显式关联旧工作，不能复用旧 source ID。
- 既有真实自动同步记录迁移为 BOUND、binding_required=false，保留原 ID、来源、owner、结果、版本及全部历史；不得重分配历史身份。

UNBOUND 是连接状态，不是新的任务进度或测试结果。DRAFT/IN_PROGRESS/BLOCKED/COMPLETED/CANCELLED 与 NOT_RUN/PASS/FAIL 等仍分别表达原有含义。

### 3. 绑定授权不依赖“知道 Task ID”

Operator 创建时可以选择 Project 中有当前有效 `task:sync` 授权的 intended actor；仅有一个可用 actor 时允许默认选定。显式空值保持未授权。没有指定 actor 的任务可以保存为 UNBOUND，但绑定必须拒绝；Operator 可在 UNBOUND 下携当前 expected_version 设置/清除 intended_actor_ref，写 AUTHORIZE 审计与历史。

BIND 重新检查 integration actor/client/Project grant 的当前有效性，要求 actor 精确等于 intended_actor_ref，并确认 Project/Task 未删除。Task UUID、session ID、客户端 root metadata 和创建者身份都不是绑定凭据；不采用任意 Project actor 先到先得，不为此次绑定另外签发 Operator key 或新 claim token。

Local MCP 必须已有受支持宿主建立的真实私有 native root context，核对 Project/provider/父会话/workspace/policy/artifact目录。模型传入的 provider/session 不能覆盖该上下文，子代理不能独立绑定。该上下文负责来源选择，不提升为当前调用者的宿主执行证明或新的安全能力。

存在父root记录不足以授权当前调用写入。新BIND与手动已绑定Task的显式MCP同步，必须核对本次宿主提供的caller来源；不能先把child解析成parent后丢掉调用来源。当前源码仅对Codex CLI `0.144.6`接入宿主逐调用注入的`_meta.threadId`：MCP从request context读取，使用独立的私有IPC `native_caller_context`传至协调器，与所选SessionStart root及实际写入来源一致后才允许POST。模型arguments、环境自报session或CLI参数不能覆盖该字段，也不将它加入服务端请求、冻结业务载荷或幂等摘要。

缺失、错配和未实现的宿主适配分别明确拒绝。Claude Code与DeepSeek当前没有已实现的可信逐调用caller适配；新MCP绑定及手动已绑定任务的显式MCP新写入应fail closed，不能沿旧三宿主自动任务证明宣称支持。CLI bind-task同样不能凭自报parentID取得caller资格。已有确认的legacy auto任务resume、授权GET及未决操作的原key只读对账保持兼容。该fence防止正常宿主中的child仅填父ID借用父任务，不防御任意同用户代码另造客户端，也不向平台引入签名、nonce、宿主凭据或独立身份认证。

### 4. 同一版本与独立回执

CREATE、AUTHORIZE/其他管理、BIND 和实际 sync 共用 task.version。每个新接受变更递增；同值 AUTHORIZE/管理 PATCH 不制造版本。绑定和授权修改、删除、同步竞争时按聚合锁与 expected_version 串行接受，不用“最后写入覆盖”。数据库同时约束 UNBOUND/BOUND 字段组合、严格版本和全局 `(provider, session_id)` 唯一，防止两个任务抢同一来源或一个任务绑定两个来源。

CREATE/BIND 有独立 operation receipt，BIND 冻结接受时的 task snapshot；不伪造 SyncReceipt，不推进 last_synced_at。管理 CREATE/AUTHORIZE 和后续管理快照、绑定快照、原同步快照共同支持每个固定版本读取。CREATE 的回执和管理快照如果同时记录同一版本，必须对应完全相同的接受状态。last_managed_at 表达人工管理，bound_at 表达来源绑定，last_synced_at 只表达真实 Agent 同步。

每次 CREATE/BIND 写前固定完整请求、稳定 key 和预期版本；原 key 查重在当前版本检查前进行。同 key 同输入返回原接受结果，同 key 异输入拒绝。SENT/失答/UNKNOWN，包括原 key GET 返回 NOT_FOUND，只允许继续原 key 查询，不重新 POST、换 key、另建任务或发新凭据。MCP 提供绑定原 key 查询入口；查询仍检查当前授权，不因 Task 后来删除或版本前进改写原接受身份。

Web Local CREATE 使用独立 IndexedDB store 保存完整冻结请求、原 key 与 expected_version=0；事务占据同 Project 的 Local 创建流，跨标签不能各自发新 key。它不借用 Cloud 的元数据账本或权限。旧 sessionStorage 记录事务迁移成功后才移除，有冲突则保留所有原 key；存储失败禁止新 POST。有效 CREATE 回执后完整读取同 Task 固定接受版本并核对请求，才按原 key 完成；SENT/UNKNOWN/失答/NOT_FOUND 始终只 GET 原 CREATE key。用户清除站点数据、浏览器驱逐或私密模式结束不承诺客户端保留。

### 5. 新 Local 会话先绑定，再同步

新 Local 客户端在首次批准产物上传前必须选择并绑定明确 Task ID；未绑定时返回 `TASK_BINDING_REQUIRED`，保存允许的本地材料，不 POST sync、不自动建 SessionTask。Hook 和 MCP 共用当前 root、目标 Task ID、writer 锁、绑定/同步账本与恢复状态，不产生另一个 writer。若已有 SENT/UNKNOWN 操作，先对账原 key，不能越过它绑定另一个任务。

绑定完成后，读回同 Task ID 的当前/固定版本，实际 sync 必须携 `task_id` 并同时匹配 Project、真实 provider/session、owner、binding_state 和 expected_version。目标不存在、未绑定、删除或任一身份不匹配时明确拒绝，不能忽略目标 ID 后按来源另建记录。绑定/查询不是 sync；首次真实 sync 才产生 SyncReceipt、AGENT_REPORTED 来源与同步时间。

服务端保留旧自动创建 wire 的兼容路径，仅适用于 legacy 自动任务；新客户端不能将其当未绑定失败的 fallback。已经确认原 Task ID、来源和 owner 的旧自动根可 resume，保留 journal/key/完整原件。已知 ID 不能仅因配置为空而重新分配。

### 6. 已有来源冲突与安全关联

如果当前真实会话已自动创建 Task A，用户又要求绑定预创建 Task B，BIND 返回409；只在调用者有权读取 A 时提供 existing_task_id。不改 A/B 的主键或来源、不搬运用例/报告、不合并版本、不将 A 的 FAIL 覆盖为 B 的草稿。不同 Project/actor 的冲突不泄露无权读取的任务内容。

用户可明确选择继续已有 A，并删除仍未绑定的 B；或由宿主建立真实新会话绑定 B。需要关联前序任务时保存明确的计划/报告来源引用；关联不改变原 ID、归属、权限、回执或原始历史。不能将409自动解释为已绑定到另一个 ID。

## 取舍

| 方案 | 结论 |
| --- | --- |
| 扩展 SessionTask 为 UNBOUND/BOUND | 采用；同一 ID、列表、版本和回收站，代价是显式修改领域约束、nullable读取、绑定回执与客户端兼容逻辑 |
| 独立 LocalReservation，再物化/关联 SessionTask | 不采用；能保留旧NOT NULL，但引入两套ID/版本/历史、跨表唯一性及列表去重，既存autoTask还需要别名处置 |

没有占位 session、借 CloudTask/Attempt ID 充当来源、复用 Web operator 为Agent owner或静默跨会话接管的兼容方案。

## 必须覆盖的验收

1. 同一 Project 的Cloud/Local创建路由和有类型详情正确，两种权限/生命周期相互隔离。
2. UNBOUND 的真实来源、owner、source和同步时间为空，初始NOT_RUN；没有SyncReceipt、执行Job/Attempt或测试副作用。
3. intended actor 的省略/显式空/唯一默认、多候选、撤权、过期、错actor/Project均按规则处理；Task ID不授予读取/绑定权限。
4. 真实父会话可以绑定，假root、子代理、上下文不一致、无root或未知宿主被拒绝；Hook/MCP共享同一目标。
5. 两会话抢一Task、两Task抢一来源、管理编辑与BIND并发，最多一个接受，失败不留下部分身份/历史。
6. CREATE/管理/BIND/sync版本连续，source/同步时间仅在实际sync出现；任一固定版本可完整重建。
7. CREATE/BIND同key重复、异输入、失答、重启、UNKNOWN/NOT_FOUND只原keyGET；回执固定原Task/接受版本，撤权不能绕过。
8. 未绑定新Local产物返回TASK_BINDING_REQUIRED且平台零POST；绑定后漏task_id、错ID/来源/owner/版本均不得新建替代任务。
9. 已有autoTask冲突409且原A历史不变，旧根resume复用ID；原FAIL、用例/报告修订和原key回执不被覆盖。
10. 已删除Task/Project拒绝新绑定；BOUND及软删除后不能改绑，恢复保留身份；普通读与原key对账保持各自授权边界。

上述是待执行断言，不是验收通过声明。新功能不自动加入既有 `local-v0.1.0` 的固定包或三宿主证明；源码、远端测试、真实宿主与新客户端发行须分别记录。HyperTest平台开发不自动映射为XBlock测试任务。
