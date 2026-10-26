# 绑定、同步与完整读回

当配置、真实 root 和 caller 路径均已核实，或恢复既有 Task 时读本文件。以下符号表示实际读回值，不是可直接发送的 payload：P=Project UUID，T=原 Task UUID，S=当前真实父 session，N=当前版本，KB/KS=分别持久冻结的绑定/同步 key。

## 查询不要混用选择器

`hypertest_get_task` 每次只选一条：

| 用途 | 参数 |
| --- | --- |
| 原 Task | `{project_id:P, task_id:T, version?, offset?, limit?}` |
| 已确认来源 | `{project_id:P, provider, session_id:S, version?, offset?, limit?}` |
| 原 SYNC key 对账 | `{project_id:P, idempotency_key:KS}`，不附版本或分页参数 |
| 原 BIND key 对账 | **另用** `hypertest_get_task_binding({project_id:P,idempotency_key:KB})` |

Task ID 查询不同时传 provider/session；原 key 查询不传 task_id/provider/session/version/offset/limit。`limit` 为 1–24000；`offset>0` 必须固定 `version`。工具的 MCP server 前缀依安装名而异，先读取实际目录，不能因名称不同新建连接。

## 1. 完整恢复基线和唯一 writer

先读原账本全部未决项，只按原操作 key 恢复。再完整读取 T 的当前快照 `{task,cases,reports}`，确认 Project、intended actor/owner、绑定来源、当前版本及既有资产。首片未固定版本时，从其返回版本固定所有续片。

- UNBOUND：当前授权 actor 必须精确等于 intended actor，且当前 root 尚无其他 Task；满足后才准备 BIND。
- BOUND 且来源/owner 与本父会话匹配：恢复原目标和账本，不再次 BIND。
- 已绑定到其他来源：单会话合同让原真实 writer 接续或明确来源阻塞；只有显式启用协作并授权本 root 时才转到下节 JOIN，不可改绑、复制其 session ID 或让新会话冒用。`SESSION_ALREADY_HAS_TASK` 也不授权自动合并或创建替代 Task。
- 其他 writer 或未决 key 尚未协调时，不继续写入；保留可独立准备的私有材料。

## 2. 冻结并调用一次 BIND

完整请求字段为 `project_id=P, task_id=T, provider, session_id=S, expected_version=N, idempotency_key=KB`。N 至少为 1，来自当前读回。KB 不与 CREATE 或 SYNC key 混用；key 格式为 `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`。

发送前私有持久保存完整请求和来源，再记录 PREPARED/可能已发送状态。只有选定原生主会话调用 `hypertest_bind_task` 一次。caller context 由宿主提供，不属于请求字段或幂等摘要。

接受回执必须匹配：`status=ACCEPTED`、`operation=BIND`、`profile=codex-session-task-sync/v1alpha1`、原 Project/Task/provider/session/key、当前 actor、`binding_state=BOUND`，`version=N+1`。回执的 source 如返回应为 null；固定 Task 快照的 source/last_synced_at 仍为空。绑定不提交 cases/reports，也不修改业务结果。

保存原回执，查询原 KB，完整读取该固定接受版本，并确认绑定身份及原 Task 业务字段保留。只有这些核验完成，才准备实际 SYNC。v1→v2→v3 只是无其他管理写时的例子，不能预设版本。

## 3. 合并正式资产再冻结 SYNC

从最新完整快照构造本次完整预期状态，再冻结 SYNC 请求：

- 总是明确传 `project_id/task_id/provider/session_id/expected_version/idempotency_key`。
- 从快照承接全部 Task 可写字段：`title, objective, status, plan_markdown, reported_result`，只应用本次真实变化。省略会触发 schema 默认值，可能清空目标/计划或回退状态；不能只传 cases。
- Case 按稳定 `key` 合并 `title, steps, expected, actual, reported_result, implementation_ref`。报告按稳定 `key` 合并 `title, markdown, artifact_uri, source_ref, reported_result`。只发送真实新增/变化条目；省略旧 key 不删除资产，完整比较仍须包含全部旧资产。
- 服务器管理 `id/revision/task_version/created_at/source`，不将这些返回字段直接塞回输入。新资产 revision 应为 1，内容不变不应制造修订；原 FAIL/UNKNOWN、报告口径及来源历史继续保留。
- 报告必须显式选择真实 `reported_result`，schema 默认 UNKNOWN；确无执行的新设计才用 NOT_RUN。不要把同步失答解释为测试 UNKNOWN，也不要把未知历史改成 NOT_RUN。

KS 是本次新意图的稳定 key，N 是合并前读回的实际版本。私有持久保存完整请求、完整合并预期及来源，记录可能已发送后，原生 `hypertest_sync_task` 调用一次。

SYNC ACK 核对 `status=ACCEPTED`、`profile=codex-session-task-sync/v1alpha1`、`source=AGENT_REPORTED`、原 key/Project/provider/session/Task 与 `version=N+1`。无匹配 ACK 一律保留未决，只查原 KS。

## 4. 固定接受版本读回

以有效 ACK 的 Task ID 和接受版本 V，从 offset=0 开始分页 GET：

1. 每片核对 `task_id/version/format/source/total_chars` 一致，按响应 `next_offset` 连续取下一片，禁止混入 current head 的页面。
2. `content` 的 offset 按 **Unicode 字符**计数，不是 UTF-8 字节。拼接至 `complete=true`、`next_offset=null`，确认累计字符数等于 `total_chars`，再解析完整 JSON。
3. 直接比较 Task 全部可写标量、全部 case/report 字段和保留的旧资产；Markdown 按实际提交字符串的 UTF-8 字节比较，包含原换行/空格。不以摘要或哈希代替内容比较。
4. 检查新/改资产的 ID、revision、task_version 与 source，保存服务器字段。固定快照不等于完整修订历史；保留历次冻结请求和快照，不宣称本次 GET 读完所有历史。
5. 再发不带 version 的 current GET。head=V 只表示该次观察仍为当前版；若 head 前进，完整读取新 head 并协调差异，不自动补写或把 V 称为最新。

## 5. 对齐 Hook 的正式产物

显式 SYNC 与 Hook 共用 coordinator。先在批准槽外准备私有草稿，避免未审阅内容触发同步。接受并读回后，将**接受版完整 plan**及报告原文写入真实 root 给出的 `artifact_directory` 中对应 policy 文件名，不能复制旧 initial plan 覆盖已有标量。

新增报告首次提交前，对齐已批准槽的 key/title/result；已有同 key 报告由在线 baseline 保留 metadata，不能为对齐旧 policy 改报告结果，也不要对同一份报告换 key 制造重复。内容未变则不另造意图；投影后检查账本无新增未决项，并观察 current head。源码的 UNCHANGED 分支、配置/信任、某次真实 Hook、四项 Hook 全部 E2E 是不同证据，不互相替代。

当前[协调器实现](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/coordinator.py)在每次 Hook 观察时在线读取当前 baseline：已有 Task 时承接其五个可写标量，不再套 policy 的 `initial`；只有没有 baseline 才使用 initial。已有同 key 报告的文件观察只更新 Markdown，title/result/source_ref/artifact_uri 保留最新 baseline。因此不必另存一份本地 baseline，也不要为“对齐 initial”修改 policy；policy digest 改变会使原 root 不再匹配。核对实际观察使用的 baseline 和报告 metadata 与接受版一致；head 已前进则完整读取新 head，缺基线或内容不一致时保留阻塞，不继续新增写入。内容 canonical 相等时协调器返回 UNCHANGED，不因 initial 仍为 DRAFT/NOT_RUN 而把既有 FAIL/UNKNOWN 改回去。

## 6. 未知写入只查询

| 观察 | 后续 |
| --- | --- |
| SENT/UNKNOWN/超时/失答/回执不匹配 | 保留 payload/key/version，按原 BIND 或 SYNC key GET；不重 POST |
| 原 key NOT_FOUND | 仍未决；不换 key、不新 Task、不重建凭据或清账本 |
| 明确版本或归属冲突 | 读原 key 和当前完整 Task，协调 writer；旧意图明确终结且有真实新业务变化后才另起新意图 |
| 401/403/过期、root 或 caller 不符 | 保留私有材料，报告具体缺口；不换 owner、降低 TLS 或扩大 scope |
| ACK 已接受但读回不完整/不符 | 继续该固定版本只读核查，不用另一次 SYNC 修补读回 |

规范：[会话同步指南](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/CODEX_SESSION_TASK_SYNC.md)、[输入和 GET schema](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/api/task_schemas.py)。

## 7. 显式多会话协作（ADR-026）

本节仅适用于服务端与客户端均支持 `local-task-collaboration/v1alpha1` 的 Task。旧 `local-v0.1.0` 和 `local-v0.1.1-rc.1` 的不可变资产不因源码更新获得协作能力；先核验实际安装的工具和能力。默认任务不自动启用协作。

Operator 先 ENABLE，并对拟加入的精确 actor/provider/真实独立 root session AUTHORIZE。当前首片同一 owner actor；Agent 不取得 Operator key。AUTHORIZED 只是授权意图，不代表已 JOIN。使用 `hypertest_get_task_collaboration` 带 `project_id/task_id/provider/session_id` 读取当前或固定版本，续页 `offset>0` 必须携 `version`。AUTHORIZED 与 ACTIVE 可按当前授权读取；REVOKED 拒绝。旧不带来源的 Task GET 遇到 `COLLABORATION_PROFILE_REQUIRED` 时切换新 GET，不继续 full sync。

- **JOIN：** `hypertest_join_task` 传 `project_id/task_id/provider/session_id/expected_version/idempotency_key`，可显式传 profile。必须由匹配的真实 root 调用，宿主 caller context 不属于 arguments。JOIN 原 key 对账并完整读回 ACTIVE participant 后才提交贡献；已是 ACTIVE 不再 JOIN。
- **贡献：** `hypertest_contribute_task` 另传 `contributions`。每项含 `kind=PLAN|CASE|REPORT|REVIEW`、`stable_key`、`expected_revision`（首次为0）和 `content` 对象。CASE/REPORT 内容采用旧对应输入字段但去掉 `key`，报告明确 reported_result；PLAN/REVIEW 保存批准的正式 JSON。只追加自己的贡献，不将其他成员同名 key 当作自己的基线。
- **汇总：** 当前 PRIMARY 的 `hypertest_publish_task` 另传 `primary_generation` 与 `summary`。summary 明确承接 `title/objective/status/plan_markdown/reported_result`，`contribution_refs` 每项固定 `contribution_id/revision/disposition`（ADOPTED/MERGED/DIVERGENCE/DEFERRED）及可选 `shared_key`，另含 `completion_basis`、`unresolved_items`。COMPLETED 必须给出完成依据；采纳映射不隐式物化旧 CaseRevision/ReportRevision。所有原贡献和 FAIL 保留，成员完成不自动完成整体任务。
- **角色交接：** 由 Operator 选择 ACTIVE participant 并核验版本与代次。原主失去整体写权后仍按当前角色贡献，不修改原 session 或替旧 root 重发未决 key。

每次写都冻结完整规范化 payload、Task/source/operation、原 key、expected_version 及适用 generation/revision。各操作共享服务端 actor/Project 的 key 唯一范围，不能跨操作重用 key。明确版本拒绝后可读取新基线形成真实新意图；已发送或未知请求只 GET 原 key，绝不自动重基或重放。

原协作 key 查询用 `hypertest_get_task_collaboration({project_id,task_id,provider,session_id,idempotency_key})`，不混入 version/offset/limit。当前授权下验证原身份、operation、request_digest、participant、版本和代次；本地协调器持有原快照时继续完整固定版本读回，逐字段核对 operation_history 原 request/response、来源、贡献原文和 publication。没有本地原快照的只读回执不宣称已比较原请求。

同一 root 的 Hook/MCP 共用锁和私有账本，跨 root 由服务端串行接受。批准的计划文件成为该成员 `PLAN/approved-plan`，报告成为该成员原 stable_key 的 REPORT。文件观察保留该成员已有报告 metadata/result，只更新 Markdown；不把共享整体计划回投到另一个成员的槽。manifest 含整体 title/objective/status/reported_result 变更时明确要求显式 PUBLISH，Hook 不代发。旧 full sync 新写明确拒绝；启用前原 key 和固定历史仍按原合同恢复。

协作来源实现与输入：[协作 schema](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/api/task_collaboration_schemas.py)、[Local adapter](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/collaboration.py)。
