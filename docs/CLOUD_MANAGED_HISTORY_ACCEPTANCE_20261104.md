# Cloud 原任务身份显式历史查询交付（2026-11-04）

本轮扩展现有受管 QUERY，默认 main 不变，显式 `collection=history` 才读取 XBLOCK 固定历史 scope。未复制知识库、开放 raw Sources 或恢复旧 18443。实现、负向回归、实际模型检索、知识使用及客户端认证分别记录。


## 最终交付边界

- 实现/部署、原任务受管检索、真实模型更正链使用、精确引用、预算与关键拒绝回归：PASS。
- 第十一轮真实任务和完整Gateway关联证据：PASS；下述附加目录提示单列，不把Task Completed本身作为通过依据。
- 附加冻结提示“不得列上级目录”：FAIL。模型仅列出自己Attempt workspace的`.hypertest-cloud / framework / sut`三个名称，未读取框架/SUT内容、跨Attempt或写出transport；原工具结果保留。
- 部署后Codex真实main→history回归：PASS。Claude Code：BLOCKED，本机未登录，实际认证失败和后续状态保留；未以假SDK代替。
- SUT测试、交易、业务数据修改、产物上传/归档和memory写入：NOT_RUN，符合本次仅知识检索范围。

当前实际API为 `93d201c902d14cd65077c8e8527054450636173a`，包含本轮已推送实现与修复 `c331ad6`、`d71aff5`、`59b5e52`、`87f6fa4`。实际API镜像 `sha256:bcf4f2fb36a743d7026fd59c9a65959197f8b2c94940ff0225e84b3837a5a074`；宿主Worker PID `55505`，相关实际文件按执行期快照核验，不能把整体overlay树等同Git HEAD。Web保留`4dbeb61`、schema`0048`；18543服务、18443停止/卷保留、Gateway4秒、Bridge5秒/60000字节均保持。并行会话的更新已合入交付分支，未覆盖共享工作区修改。

最终任务：[`01a1a4f9-9cfb-7522-8e29-1527d6bfcd52`](http://10.66.66.3:3000/cloud-tasks/01a1a4f9-9cfb-7522-8e29-1527d6bfcd52?projectId=01a181ac-ba63-7c24-b695-bfb498829b63)，Attempt `01a1a4fc-eb7a-7f86-a33f-3dfc29a51587`。证据根目录的 `RESULT.md` 提供最终索引；前十轮原始失败、范围偏离和日志缺口全部保留，未用复测覆盖。

## 实现与初始部署

- 已推送并部署 API/Worker Memory 文件：`c331ad6991c09f4b98ed3d2eb09133f7b8eeb5fd`，分支 `codex/managed-history-release-20261104`。
- API 镜像：`hypertest-mac-api:c331ad6` / `sha256:416125809231a4c277b8de90d88eccdddf3dd9ade1531af8c055cc12dbbf5f28`。
- 首次 Worker：PID `17311`，2026-11-04 11:16:46 Asia/Singapore 启动；保留既有 Native/SDK/Cordis/会话检查覆盖层，仅更新 `cloud/memory.py`、`cloud/manifests.py`、`interactive_client/memory.py`。实际源码路径与逐文件摘要见部署收据。
- 本轮初始 schema 为 `0046_native_session_restore`，本功能无迁移。使用干净 checkout 与既有依赖进行回归，未纳入其他会话修改的续接/领取槽功能。随后并行会话部署 API `c69af66b9b14154c7aee7977e9c0c9f7aa2cb3df`、Web `27bbce9d034dcbff9bce2724bab9e2f2ecebc97d`、schema `0048_concurrent_claim_slots` 和 Worker PID `24985`。实际文件 hash 与运行时 schema 核验表明本轮 Gateway 和 Worker memory 文件保留，见 `concurrent-deployment-observation.json`。初始部署收据不是当前完整平台版本。
- Gateway origin 仍为 `https://host.docker.internal:18543`；实际 Gateway 4 秒、Bridge 5 秒、Bridge 响应 60000 字节，均未放宽。Web/BFF/18543 PowerContext/TLS 容器身份未变，旧 18443 容器保持停止、卷保留。

运行时注入 Project、原 Task/Attempt 和接受版本，私有头承载当前 Worker lease/generation/work proof 与独立 memory grant。模型不能提供 scope、context、其他项目或凭据。Gateway 在检索前后重新加载授权/任务/租约/代次/映射，修复 ORM identity map 可能掩盖途中失效的问题；Bridge 在请求前后及文件交付前再次核原身份。任务删除使用独立 CloudTaskDeletion 表。

历史仅按服务端固定 main/history 映射及精确 `hypertest-project-history` external reference 选库。响应 `history_results` 保留完整正文、原日期、旧编号、分片、更正提示及 ref/revision/content_digest；按完整条目裁减并明确 PARTIAL，不裁正文。超时、空结果、上游故障和拒绝不会伪造历史或改变任务报告结果。请求 UUID 用于非敏感关联日志，不构成授权。

## 调用示例

模型在当前工作区发布现有受管 intent（下面 Task/Attempt 由实际任务 envelope 提供，不得借用示例身份）：

```json
{
  "profile": "hypertest-cloud-memory-handoff/v1alpha1",
  "task_id": "<当前 Task UUID>",
  "attempt_id": "<当前 Attempt UUID>",
  "key": "history-question-1",
  "operation": "QUERY",
  "payload": {
    "collection": "history",
    "query": "历史上交易主单失败后资金仍冻结的调查，最初解释后来有哪些更正？",
    "limit": 8
  }
}
```

路径取当前 envelope 的 `memory_contract.query_protocol` 示例及绝对 `memory-ready` 目录，文件名为 `history-question-1.json`，读取同 key 的 `memory-responses`。共享框架 cwd 下不能改用相对目录。省略 `collection` 仍为 main。scope 与实际身份由 Bridge/Gateway 处理，模型不调用 standalone browse 或直接 PowerContext。

## 回归边界

专用合成库 `hypertest_memory_test_20261104` 位于复用的 ADR-016 测试 PostgreSQL，未在业务库写 fixtures。100 项相关检查通过；旧采用既有 scope 的测试因重复运行固定 fixture ID 冲突，改用唯一测试 scope 后单独复测 1 项通过，原失败日志保留。覆盖默认 main、合法原身份 history、错项目/Attempt/版本/lease/generation、身份和 scope 覆盖、错历史绑定、撤销 memory/work grant、查询途中取消/失租/代次变化/删除/映射漂移、超时/空/超预算/上游故障、失败后正常报告提交。上游负向 fixture 仅用于隔离回归；不作为真实 Worker 正向验收。测试库已删除，复用测试容器恢复停止。

## 真实 Worker 轮次与证据

证据根目录：`/Users/liangchenzhang/.local/share/hypertest-mac/managed-history-20261104/`。包含变更前备份、部署收据/文件指纹、真实模型工具请求、返回正文及摘要、API/Gateway request ID、grant 与 generation 关联、模型公开回答、接受报告及最终固定读回；不复制模型推理或凭据。

Project：`01a181ac-ba63-7c24-b695-bfb498829b63`。main：`scp_2bazwr3gd1w0ztxwf3q2hrmgh0`；history：`scp_6512953hj3xac93ad5j9cbzbpb`。任务问题不预塞历史正文、答案、候选 artifact 或旧编号，后续精确查询只使用模型从前一响应取得的更正引用。

首轮 Task `01a1a48f-8bd1-70bb-b82d-17e03517b4b5`，Attempt `01a1a48f-a9ae-7187-8c23-bd43e83f07a5`，SDK session `cloud-01a1a48f-a9ae-7187-8c23-bd43e83f07a5`，官方 SDK `0.2.2a2`，provider/model 为 `deepseek-official/deepseek-flash`。Task 最终 `COMPLETED v7 / NOT_RUN`；0 Runs、0上传 Artifact，仅有正常 markdown REPORT。

首轮结论分别为：检索链路 PASS、核心更正理解 PASS、回答合同 FAIL。实际 1 次 main 返回 5 条 external，3 次 history 返回 8、9（PARTIAL）、10 条；第三次 API 的 10 条被 Bridge 裁减为 9 条完整记录，模型识别缺失后继续查询获得更正。所有 32 条返回记录（含重复）按原 canonical `{schema,kind,text,creation:null}` JSON 摘要核对一致。早期验收脚本误用原始正文 hash，其失败快照与修正说明均保留，未把脚本错误当作内容损坏。

首轮模型正确处理 3205→3208→3211→3213→3214：撤回悬挂冻结误报，区分不确定结果的预留与后来查明的确定性拒绝，把“测试侧未适配”更正为双边签名契约单边发布，指出 537 字符长度吻合不能判别根因，并保留当前环境未知边界。但报告过长，并将后来才收到的 3211 误归给首次 history 响应。因此保留原件并用新专用任务复测简短回答及逐响应归属，不改写首轮。

首轮证据：`run-1/evidence-20261104T032222Z/REVIEW.md`、`gateway-correlation.json`、`model-tools.json`、`accepted-report.md`。平台 Native 完成只记录实际 SDK 进程已退出，外部操作 NOT_OBSERVED、其他本地进程 UNKNOWN，不从 COMPLETED 升级为 SUT PASS 或独立执行证明。

第二轮 Task `01a1a495-9c3c-7a60-8ed2-f7df3c390161`，Attempt `01a1a495-bcd5-7878-9559-162befd16f03`，最终 `COMPLETED v7 / NOT_RUN`。6 次真实 QUERY、48 条 main/history 返回记录摘要一致，最大响应 58732 字节。简短回答格式及引用归属改善，但报告将原文“566 字符”误写为“566 字段”，回答精度 FAIL；查询前还向其他旧 Attempt 工作区搜索协议代码/文档，超出仅知识查询任务范围，范围遵守 FAIL。未观察到凭据读取、直接 PowerContext/数据库检索、SUT 用例、交易或知识写入。原报告的“仅QUERY”声明与真实发现动作不符，以工具原件为准。完整记录见 `run-2/evidence-20261104T033236Z/REVIEW.md`，未覆盖首轮或本轮失败。

针对第二轮的实际问题，Worker 已部署后续提交 `d71aff5f99a4fa30b95c2369a22c7b52a7887ff2`，PID `22572`，2026-11-04 11:35:38 Asia/Singapore 启动；API 仍为上述 c331ad6。启动模型前安全预建查询/响应目录，写入 `.hypertest-cloud/memory-protocol/query.json` 当前 Task/Attempt 的完整 QUERY 示例，同时嵌入模型 envelope；入口缺失须报告不可用，禁止从宿主或其他任务搜索替代。该非敏感文件不是授权凭据，不能覆盖 Bridge 的真实身份，亦不宣称宿主同 UID 提供文件系统强隔离。27 项相关检查通过，包括目录/协议路径符号链接拒绝。重载前再次确认原 claim EMPTY/closed、无活动 SDK；备份与部署收据见 `worker-affordance/`。

第三轮 Task `01a1a4a0-e344-7228-b136-e463e035e0be`，Attempt `01a1a4a1-0226-7394-82f9-b14216df5a0d`，实际 SDK session `cloud-01a1a4a1-0226-7394-82f9-b14216df5a0d`，Worker/driver/SDK PID `22572/22818/22825`。最终 `COMPLETED v7 / NOT_RUN`，5 次真实 QUERY，10 条 main 和 33 条 history 摘要全部一致，最大 58413 字节。超预算响应按完整条目裁减并披露，模型继续查询取得更正。22 次实际工具调用仅访问当前 Attempt 受管目录、报告及回执，未再出现第二轮的跨目录发现动作。

第三轮检索链路、精确引用、任务范围和简短格式 PASS；核心更正链理解正确，但限制段把 3211 已否定的“公钥配错”误归为该记录原判断，因此**完整知识使用仍为 FAIL**，不得因主要结论正确而忽略该归属错误。接受报告未修改；原审核及澄清均保留在 `run-3/evidence-20261104T034117Z/`。随后自然语言提示仅收紧报告结构及逐句核对否定/归属要求，未塞入历史内容、记录编号或答案。

第四轮 Task `01a1a4a7-f156-74ac-a049-dab0efbf7baa`，Attempt `01a1a4a8-1095-747d-919b-5cfca1398bae`。此时运行的是上述并行会话部署后的 Worker `24985`。Task 最终 `RECOVERY_REQUIRED / NOT_RUN`，reason `WORKER_RUNTIME_FAILED`；SDK/检索/知识使用均 NOT_RUN。SUT 只完成平台正常版本预检，framework 工作区 HEAD 尚未生成、FETCH_HEAD 为空；约 90 秒后 Worker 槽中断，与实际 Git fetch 超时预算一致。精确异常未由 Worker 留存，因此“Git 超时”是基于阶段和时间的推断。无 native identity、prompt-intent、RUNNING 开始时间或对应模型 session，未启动模型。原操作 key、任务身份和失败证据保留于 `run-4/failure-20261104T034735Z/`，未重放原任务或声称任何外部动作已经恢复。

## 客户端回归

本机已有独立 XBLOCK memory:read 授权经现有 TLS Gateway 使用，不新建凭据、不接触 PowerContext 管理 token。为本轮回归使用临时进程级 stdio adapter，未改用户常驻配置；这只证明本机客户端经合法显式入口的能力，不等同于另一台 Mac 原插件配置验收，也不替代上述受管 Worker 检索。

Codex CLI `0.166.0` 真实模型回归 PASS。首轮实际 session `01a1a494-3ab7-7a81-b385-ead914172bdd` 经 1 次 main 和 3 次 history 查询理解更正链；第三轮 Worker 验收后的独立复核 session `01a1a4a5-861b-7031-9185-f6bb57146114` 精确执行 default main→explicit history，均经 Gateway 返回，main 无 history_results 混入，模型使用的历史日期/ref/revision/digest 与响应相同。证据：`client-regression/RESULT.md` 与 `client-regression/final/RESULT.md`。

Claude Code `2.1.207` 为 **BLOCKED**。实际启动 session `b447e32c-11f5-4da5-8209-21e415e580bf` 返回 `authentication_failed / Not logged in`、exit 1、零模型 token/查询；验收后再次核验 `loggedIn=false/authMethod=none`。未复制其他用户或机器的登录、未用 fake SDK 代替。只有本机 Claude 合法模型认证是该客户端回归的具体阻塞，不能把未执行的检索标 PASS。

## 后续运行时变化与独立失败保全

第四轮之后，第五轮新 Task `01a1a4b0-2690-7b0e-9184-4abd568d9a83` / Attempt `01a1a4b0-4ed3-779d-87cf-642aeb73a67f` 已通过仓库预检、记录原会话身份并进入 RUNNING，随后 46 毫秒内触发通用 `WORKER_RUNTIME_FAILED`，最终 `RECOVERY_REQUIRED v5 / NOT_RUN`。未发现 SDK 会话或 QUERY；模型知识检索 NOT_RUN。原 key、锚点、进程版本、空响应及失败阶段分别保留，不重放本 Attempt。纯离线检查证实当时身份校验、driver 导入/输入读取及会话桥接启动骨架可通过；这些排障 fixture 不是实际 Worker 正向验收。

并行会话在 04:00 UTC 部署 `b08782f008bc44ad8b39061189b9dc361da9bbdb`，Worker PID `32548`，将 SDK 工作目录切到共享框架项目，原 Attempt workspace 继续保留受管 transport。本轮保留其变更，核对 memory 协议路径被转成该 Attempt 的绝对路径；不回退并行功能。该后续文件变化发生在第五轮失败之后，不能归因成第五轮的根因。

第六轮 Task `01a1a4bf-51af-7b14-a63e-e328c6e77aaa` / Attempt `01a1a4bf-7fe6-783f-b6fb-87b87f448cb7` 在加入安全诊断后复现启动失败，最终 `RECOVERY_REQUIRED v5 / NOT_RUN`，仍无模型 session/QUERY。新增 `99c8707ded050626e74676ee5eb4b23658dcb7e4` 仅输出固定异常类别、允许错误码和有限模块行号，不含异常正文/参数/locals/凭据；4 项直接相关检查通过。实际错误为 `BrokerFailure / CLOUD_OPERATION_REJECTED`，栈定位到 `conversation/poll`。

现场确认 18444 私有 BFF 挂载的精确 Worker 路由列表漏掉新部署的 conversation 接口，返回 404、请求未到达 API；当前 API 实际已注册相应受鉴权路由。这是并行会话功能部署后的真实启动阻塞，不是历史检索或模型理解失败。修复提交 `486e9c13f9d3c341a7dcbe427aed6e87ca35edd5` 已推送并渲染部署，精确补 7 个 conversation 路径及同一现行协议遗漏的 `resume/identity`，不开放通配路由。保留 POST-only、TLS、Host 检查、专用 bearer 和 Operator header 清空；不更改 18543 知识 Gateway。6 项路由契约检查通过；真实 nginx -t 通过、reload 后全部未认证 POST 返回 401、GET 返回 403、未知/额外路径返回 404。配置原件与摘要、原镜像身份保存在 `conversation-bff-fix/`。未调用任何旧任务续接。原第五、六轮的启动意图和失败记录保留，未重放。

第七轮 Task `01a1a4c4-d49e-7abe-b796-258fce508e15` / Attempt `01a1a4c5-0cfe-7bf6-a663-dd384e4c241a` 在 BFF 修复后启动了真实 SDK（Worker/driver/runtime `34982/36572/36582`），但 SDK 工作目录改为共享 framework 后，写入位于目录外的原 Attempt transport 被 `FS_SANDBOX_DENIED` 拒绝。没有受管 QUERY/响应，因此检索与知识使用 NOT_RUN、运行条件 BLOCKED。模型随后尝试被拒绝的权限扩大、符号链接绕行和配置探测，范围遵守 FAIL；26 个真实工具调用及原错误完整保留于 `run-7/evidence-20261104T042054Z/REVIEW.md`。我通过正常 CANCEL_ATTEMPT 原 key 撤销该轮执行权限，Task `RECOVERY_REQUIRED v6 / NOT_RUN`。直接 SDK 进程已退出，API 的 STOP_UNCONFIRMED 未被改写为万能停止证明。环境/config 返回未观察到凭据字段或已知 token，审查只记录字段名、布尔值和 hash。

这一失败由框架目录与 Attempt transport 的写权限不一致触发。[官方固定 SDK ce7073d 的沙箱合同](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/docs/subsystems/sandbox.md)中的 `sandbox-policy.additionalWritableRoots` 同时由 FS 与 macOS Seatbelt 执行；后续修复只在单次运行的私有 overlay 中授权本 Attempt `.hypertest-cloud` 目录，不改变 workspace-write 模式、全局 profile、Gateway 或任务身份边界。第七轮失败保留，不以临时配置检验替代下一轮真实模型验收。

第七轮关闭后，Codex 再次真实回归 PASS：session `01a1a4c9-aba0-74a2-ba8f-0f14fe17a830`，04:20:42–04:21:08 UTC，精确 main→history 两次调用均通过，引用元数据与内容摘要一致；Claude 认证仍 BLOCKED。独立证据为 `client-regression/post-run7/RESULT.md`，不覆盖前轮，也不将客户端成功升级为第七轮 Worker 成功。

## 当前部署与 transport 修复

并行会话于 04:19 UTC 部署 API/Web `4dbeb61354223381bbeefdc17257eb5b35719df3`（ADR-041）；本轮合并保留该提交及文档，不恢复旧 native anchor 或 resume identity gate。本功能原任务的 lease/generation、独立 memory grant 和 Gateway 前后验证继续有效。

最新 Worker/BFF 修复提交 `59b5e5244b7e5fa664ebd18c9f6efd9e031e9cd6` 已推送并于 04:38 UTC 部署。Worker PID `39560`，只更新 `native_selection.py`、`native_cordis.py`、`native_sdk_driver.py`；前述 memory 文件和并行 Harness 简化实现均保留。重载前 5 个 claim 槽均 EMPTY/closed 且无 SDK 子进程，备份实际文件及部署入口。只从有界的真实 SDK config 投影模型和已知沙箱字段，拒绝任意表达式/未知字段/无沙箱模式；保留既有规则，仅将规范、非符号链接、当前用户私有的本 Attempt transport 加入临时 overlay。官方 SDK 的 FS 与 Seatbelt 自行执行该精确目录许可，不设置全局权限或审批替代。

直接检查最初 59 PASS、1 个并行4db已变更合同的旧工作目录断言 FAIL；按当前允许已有不同 worktree 的合同更新 fixture，4 项针对性复测及1项父目录符号链接检查通过。没有削弱原 Attempt transport 归属检查。Ruff/diff检查及实际固定SDK无模型配置解析通过；不是正向验收。BFF按现行API移除已撤销的 resume/identity，仅保留精确 conversation 路由，12项直接契约检查通过，实际nginx检查/重载及未授权拒绝保持。证据分别为 `transport-sandbox/`、`transport-config-preflight.json`、`transport-sandbox-validation.json`、`bff-shell-alignment/`。

第八轮 Task `01a1a4d9-bc1b-7784-8c9f-bfaed6b6e02e` / Attempt `01a1a4d9-e219-7e71-a209-900b958a433d` 已正常启动真实 SDK，成功写入精确 transport，证明第七轮沙箱阻塞已解除；但模型把 `KEY.json` 当作字面文件名，与 envelope 的 `key=query-1-main` 不同，Bridge 明确拒绝 `MEMORY_HANDOFF_INVALID`，未进入 Gateway。随后并发 conversation poll 返回500，实际 PostgreSQL 证实 Task→Attempt 与 Attempt→Task 反向加锁形成死锁，SDK被中断，最终 `RECOVERY_REQUIRED v4 / NOT_RUN`。本轮检索和知识使用 NOT_RUN，运行失败保留于 `run-8/evidence-20261104T044253Z/REVIEW.md`；6次工具均限本Attempt transport，未收到历史内容。SDK进程PID未在退出前捕获，明确 NOT_CAPTURED，不追补虚构；真实session id及原prompt接受回执、SDK消息id、内容摘要和冻结任务身份已交叉核验。

后续协议说明改用具体 `query-1.json` 示例，并明确文件名必须等于 `envelope.key + .json`，无权改变Task/Attempt或私有proof。29项直接关联检查通过。后续提交 `87f6fa49056b83773e607a5fc6bdd2ccb47a2d8e` 将 `active/original_read` 统一先锁 Task 再锁 Attempt，原身份和授权判断不变。专用真实 PostgreSQL/API 并发回归用旧两处锁参数稳定复现2项失败；修复版 conversation 与 worker API 共14项通过，包含 append/poll、renew/poll 有界并发及授权拒绝。旧实现探针只在隔离测试进程还原两参数，不用于正向 Worker 验收。测试库已删除、复用测试容器恢复原停止状态；原API/PG死锁日志保留在 `lock-order-validation/`。下一轮独立结果见后续记录。


`87f6fa4` 已于 04:50:35 UTC 部署为 API 镜像 `hypertest-mac-api:87f6fa4` / `sha256:35151cfb936598b3f8d4a7e6bee25eed40d11f9fdaeb9150c251460a615691fd`，Worker PID `47477`。schema `0048`、Web `4dbeb61`、现有BFF/18543及旧18443退役配置保留。本次只覆盖Worker memory/manifests两文件，59b5沙箱修复与其余并行代码均核hash保留。首次部署脚本对 `launchctl bootout` 的立即PID检查撞到异步卸载，安全停止于API变更之前；记录 `lock-order-fix/failure.json` 后，补4秒有界卸载观察，在独立 `lock-order-fix-retry1/` 完成部署，不覆盖原失败。


## 第九轮：实际部署后的独立验收

[任务 `01a1a4e5-7b59-7c8c-a383-3b1db3eefd0c`](http://10.66.66.3:3000/cloud-tasks/01a1a4e5-7b59-7c8c-a383-3b1db3eefd0c?projectId=01a181ac-ba63-7c24-b695-bfb498829b63)，Attempt `01a1a4e5-afbd-7a30-a0ad-1c067252ad47`，真实 SDK session `cloud-01a1a4e5-afbd-7a30-a0ad-1c067252ad47`。04:52:09–04:56:50 UTC 正常运行，最终 `COMPLETED v6 / NOT_RUN`，报告修订 `01a1a4ea-5fba-72c7-b95a-71e60d8ff922`。实际进程链为 Worker `47477` → driver `48555` →官方 SDK runtime `48628`；早期进程快照捕到配置探针，单独纠正并保留，模型进程以 `live-native-processes.json` 为准。

模型实际先以 main 查询，返回5条 external、0条平台已发布结果、0条历史；随后8次显式 history QUERY，共返回53条历史条目（含重复）。query-2及query-9因60000字节预算按完整条目裁减，分别保留8和7条，最大响应59457字节，模型继续检索了后续更正；总计58条main/history记录逐条验证canonical digest。精确更正链3205→3208→3211→3213→3214及3215均从本轮实际响应获得，未向任务预塞编号、答案或正文。

模型接受报告含4句、240个中文字的实质回答与6条精确引用：撤回“冻结零释放即缺陷”；将测试侧归因更正为服务端双边签名契约单边发布；将“vault未实现”更正为已有分支但未合并部署；保留3214对长度证据无判别力及确定性拒绝被包装成UNKNOWN的更正。明确修复后复跑与该单冻结最终处置未取得，不把历史作为当前事实、平台审核、测试证据或执行授权。逐响应归属和日期/ref/revision/digest以实际返回核对，不再出现前轮单位/归属错误。

本轮发生一次报告误投：模型将SUBMIT_ASSETS写到memory-ready，Bridge按原合同拒绝MEMORY_HANDOFF_INVALID，未发生memory写入；模型随后自行移动到正常ready，报告接受后正常完成。原工具调用、拒绝响应及修正保留，不把它隐藏成“全程无错误”。完整30个工具调用审查发现另一范围偏离：seq231未切换目录而临时在共享框架根写了complete-1.json，seq239再移入本Attempt ready并列出框架根检查残留。检索、知识使用和报告提交PASS，但冻结提示的严格目录约束FAIL；不将该轮标为全项通过。0 Runs、0上传Artifact，未观察到SUT/交易/业务修改/框架源文件内容或凭据访问。平台仍只观察直接SDK进程退出，外部操作NOT_OBSERVED、其他进程UNKNOWN；知识检索验收不等于独立业务执行证明。

正式证据：`run-9/evidence-20261104T045723Z/`，含真实工具投影、公开回答、9次Gateway请求关联、当前原任务/授权/代次非敏感证明、58条固定返回、接受报告及最终读回。ADR-041下以真实session header、framework注册、冻结Task/Attempt/Project、原prompt receipt及SDK消息id/摘要核验身份；不伪造已取消的旧anchor。


## 第十轮：功能通过，独立服务日志未保全

Task `01a1a4ef-15e7-7dd5-83db-5725df69fd91` / Attempt `01a1a4ef-2ec6-77a7-89d8-6991ac1f21d0`，SDK session `cloud-01a1a4ef-2ec6-77a7-89d8-6991ac1f21d0`，05:02:29–05:06:38 UTC，最终 `COMPLETED v6 / NOT_RUN`。该轮实际运行于并行部署 `bca2112df0e1dca20e56c97466819128660e76a2`（包含87f6），Worker/driver/runtime为 `52380/53494/53579`；执行期05:05:06已保存7个实际源码hash，不能套用后来93d源码。

7次真实QUERY（main1/history6），10条main和41条history、共51条canonical digest均核对一致，核心报告242中文字/4句、6条精确引用，更正链及适用边界正确。11个模型工具调用全部使用原Attempt绝对transport路径，无框架目录误写/列出或SUT/业务/归档/memory写入。首次报告因允许的ready目录尚不存在报FileNotFoundError；随后仅创建该允许目录并正常提交，原错误保留，未扩大权限或绕过认证。

检索、知识使用、精确引用、目录范围和报告提交PASS；完整服务日志证据BLOCKED。并行会话在05:07:37部署 `93d201c902d14cd65077c8e8527054450636173a`，移除了该轮bca API容器；部署未保留其请求日志。本轮实际响应、request IDs、SDK工具及执行期身份仍在，但不能将其冒充已丢失的服务端memory_query日志。新collector严格拒绝把93源码当bca执行身份，该拒绝和随后基于执行期收据的历史采集均保留。未恢复旧容器，也未从数据库/PowerContext另取答案替代Worker检索。日志核查见 `run-10/api-log-preservation-check.json`。

93d已现场核验保留本轮Memory实现、模型QUERY提示和Task→Attempt锁序；实际新Worker PID55505。部署后独立Codex session `01a1a4f5-1c22-7c11-aa2d-f31c8dfdb081` 于05:08:09–05:09:01实际main→history回归PASS，Claude仍认证BLOCKED，见 `client-regression/post-run10/RESULT.md`。前次post-run9客户端跨越bca部署，不用作精确93回归。

为满足完整Worker→Bridge→API→Gateway关联证据，将另建专用任务并在启动前持续保存仅该任务的安全memory_query日志；不重放第十轮，不覆盖其证据缺口。


## 第十一轮：实时保全后的最终验收

Task `01a1a4f9-9cfb-7522-8e29-1527d6bfcd52` / Attempt `01a1a4fc-eb7a-7f86-a33f-3dfc29a51587`，真实SDK session `cloud-01a1a4fc-eb7a-7f86-a33f-3dfc29a51587`，官方SDK0.2.2a2 / deepseek-official/deepseek-flash。05:17:20.273–05:20:37.880 UTC正常运行，最终 `COMPLETED v6 / NOT_RUN`，接受REPORT修订 `01a1a500-577c-790d-9fdc-6e72b6097007`。实际进程链 `55505 → 57436 → 57464`；执行前和执行期7个真实源码hash匹配已推送93，原Task/Attempt、SDK原prompt receipt/message id和冻结输入分别核验。

启动前05:16:09.955至终态后05:21:20.229持续读取该实际API容器的安全memory_query事件，只保存本Task的非敏感身份/Scope/ref数据，无query正文、headers或凭据。4条原服务事件与4个Bridge响应request_id、原Task/Attempt/version/generation、独立memory grant、scope及精确refs逐一关联；原JSONL、container/image/revision及脚本hash封存，期间容器未更换。第一轮预启动采集误用Docker不支持的`--since now`，尚未START且0事件即失败；改用精确UTC后才启动任务，原失败保存在`capture-attempt-1/`。

真实模型先main（10 external、0平台已发布），再3次history（8、5、5条）。首轮history因预算将20条裁为8条完整记录并披露省略12条；模型据更正说明再显式检索取得3211/3213/3214。最大模型响应52821字节，所有28条记录（含重复）的canonical摘要一致。报告4句、239个中文字，6条原日期/ref/revision/digest准确，区分3205旧诊断、3208误报更正及3211→3213→3214服务端签名契约/发布顺序/方法学更正；说明旧判断与环境数值不能直接当作当前事实或执行授权。知识使用PASS。

18个实际工具调用无SUT执行、交易、业务改动、源码内容检索、跨Attempt、归档或memory写入。保留额外提示偏离：seq118列了自己Attempt workspace的三个子目录名称，用于检查缺失handoff目录；未进入这些子目录，也没有写出transport。因此原用户核心验收PASS、附加“禁止列上级目录”提示FAIL分列。正常报告被接受后由原Attempt完成；外部操作仍NOT_OBSERVED、其他本地进程UNKNOWN，不从本轮检索验收生成SUT PASS或独立执行Evidence。

证据目录：`run-11/evidence-20261104T052131Z/`，重点为 `REVIEW.md`、`review-status.json`、`accepted-report.md`、`model-tools.json`、`memory-exchanges.json`、`request-correlation.json`、`gateway-correlation.json`；`run-11/gateway-events.jsonl`、`capture-metadata.json`与执行期源码/进程收据为原始保全材料。

之后实际Codex session `01a1a501-c732-7c33-b202-967e7d1c408b` 于05:21:59–05:22:27 UTC执行main→history，调用/精确日期/ref/revision/digest及更正说明核对PASS；API93、Worker55505及部署清单前后不变，未重复全健康矩阵。Claude2.1.207仍未登录，BLOCKED；只复查认证，原实际authentication_failed保留。见 `client-regression/post-run11/RESULT.md`。此本机临时只读客户端适配器与既有grant不替代Native受管验收，也不宣称恢复了另一Mac的旧客户端配置。
