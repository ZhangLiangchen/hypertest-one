# ADR-036：薄 Worker 领取失答恢复

日期：2026-11-03（Asia/Singapore）。状态：Accepted；实现、部署与实际验收分别记录。

## 问题与范围

ADR-032 的宿主薄 Worker 在发送领取前保存本地 `claim-pending.json`，但旧记录的 `local_key` 未传给服务端，也未保存完整领取身份。一次空闲网络故障可能留下无法自动核对的记录并使 Worker 退出；直接清空记录或重新领取又可能掩盖已接受的原领取。

本决定为 Worker 与平台之间的领取操作提供有界恢复，不恢复 SDK 会话，不重新执行输入解析、测试或模型请求，不改变 CloudTask / CloudAttempt 的身份、报告、授权和原外部操作账本。

## 服务端领取状态

- `CloudWorkerClaimState` / `cloud_worker_claim_states` 按稳定的 `worker_id` 保存**单行、单调递增的 sequence 高水位**，并保存当前 `request_key`、规范化完整请求的 digest、kind、closed、目标 Project/Task/Attempt 或 Resolution、generation 及时间。没有每轮空闲轮询追加一条领取历史；该表不保存 lease/work token 原文，也不是测试结果或任务业务版本。
- 初始 sequence 为 0，kind 为 EMPTY 且 closed。新领取必须是当前 sequence + 1，且原槽已 closed；当前序号内的 key、digest、目标和 generation 不可变，closed 不可重新打开。数据库约束禁止删除或回退高水位，不得通过清表、降级或更换 Worker 身份绕过待恢复领取。
- 领取与租约、work grant、目标引用及高水位在同一事务提交，含首行不存在时的互斥。当前 sequence 的操作必须匹配原 key 和完整请求 digest；完整请求包括 `worker_id, sequence, request_key, lease_seconds, supports_attempt_manifest`。
- 初次成功 `/claim` 响应只返回一次领取 capability。重复 `/claim` 不重新交付响应、能力或工作；同 key 异正文冲突。`/claim/state` 与 `/claim/reconcile` 均只返回非秘密状态，不返回 capability，不启动 Harness、Git 或项目测试。

## 私有 Worker 协议

以下入口沿用独立 Worker 认证及既有 TLS/BFF 访问边界，不能由 Agent 或普通 Project grant 调用：

| POST 入口（`/api/v1/cloud/worker` 下） | 请求与结果 |
| --- | --- |
| `/claim/state` | 请求 `worker_id`；返回当前 `worker_id, sequence, request_key, kind, closed`。无记录时为初始 sequence 0；不创建领取 |
| `/claim` | 完整原请求；首次接受返回上述身份和一次性的 `claim`，可能为 ATTEMPT、RESOLUTION 或已关闭的 EMPTY |
| `/claim/reconcile` | 与原 claim 相同的完整请求；只封口或关闭原领取，返回原序号/key 的关闭状态，不返回 `claim` |

reconcile 与 claim 使用同一互斥边界。对于尚未接受的下一序号，reconcile 原子记录 `ABANDONED / closed=true`；迟到的原 `/claim` 因而不能再领取。单纯查询不存在或网络返回 5xx 不能替代这个封口事务。对于当前已领取目标，reconcile 核对原目标、Worker 和 generation，隔离其写入权；未完成的目标进入或保持恢复状态，不自动重新排队。已终结 Attempt、已接受或失败的 Resolution 保持原事实，只关闭领取槽。

低于持久高水位的旧序号返回 `RETIRED / closed=true` 及 `current_sequence`。**RETIRED 只说明该旧序号不能再领取，不证明旧请求未到达、未被接受或未执行。** 单行状态不保留该旧序号的请求 digest；返回的旧 key 是调用方提供的标识，不是服务端重新核验的旧接受回执。它不能替代旧任务、原件、操作回执或外部账本。

## 客户端恢复

- Worker 在私有 state 目录持有进程级 `flock`，覆盖领取、执行、恢复和认证观测的整个 run。v2 pending 文件在任何领取 I/O 前持久保存完整请求及 digest；新 `/claim` 仅发送一次。
- 启动发现任何 v2 pending 时，先校验身份与摘要，随后只对该原请求调用 reconcile；**即使原响应曾返回，也不再次调用 resolve/execute 或交付 SDK**。恢复不依赖 SDK 安装，也不先启动 Harness 配置/认证探针。收到身份匹配的关闭结果后才能清理本地 pending。
- 无本地 pending 时先读取服务端高水位。服务端槽未关闭而本地完整意图丢失时明确拒绝，不能猜 key、参数或目标继续执行。正常 EMPTY 响应可关闭本地 pending；正常任务结束后也需 reconcile 关闭原槽，关闭失答只重试关闭，不再次执行任务。
- 空闲 state、首次 claim 失答后的 reconcile，以及正常完成后的关闭遇网络未知或 5xx 时，保留原 pending 并有界退避；不能以重发 `/claim` 或换 key 实现重试。`--once` 可以明确失败退出并保留 pending。认证拒绝、身份冲突、损坏记录和不支持的旧记录不自动清理。
- 实际 resolve/execute 发生 runtime 异常时，按原 key 关闭领取后仍停止 Worker，避免连续领取更多任务；关闭尚未确认时保留 pending。LaunchAgent 不因此启用自动重启。领取关闭不接受报告、不续接 SDK、不证明其他宿主进程或外部操作已经停止，也不改写 UNKNOWN、测试结果或旧预算。

## 旧记录切换

无 sequence、无服务端 key 的旧 pending 无法用新协议推导对应领取，客户端必须原样拒绝，不能补造序号、自动删除或标记 EMPTY。受控人工退役须先停用旧无 key 领取入口及旧进程/在途 handler，再核对旧 Worker 的授权、lease 和目标归属；存在有效旧写权时先按其原身份处理。保留或归档原记录及本次核对依据，保持请求到达与执行情况 UNKNOWN；“未发现活动授权”不等于原请求未执行。不自动重发旧任务，也不清除无关授权、凭据、工作区或外部账本。

本决定替代 ADR-032 中空闲 transport 失答只能让 Worker 长期停止的运行限制；其他 runtime 故障、原 key 恢复、授权隔离和报告真实性合同继续有效。领域 §51、TMP §46 和技术架构 §45 分别拥有持久状态、线协议和组件边界。

## 验证边界

必要回归覆盖原序号和异正文冲突、并发领取、空响应失答、封口后的迟到领取、已领取目标的原身份 fence、旧序号 RETIRED、重启零执行重放、关闭失答、进程互斥及旧/损坏 pending 拒绝。数据库 fixture 仅写专用测试库；模拟网络和 SDK 的结果不证明真实模型或 SUT 执行。迁移、部署身份、旧记录退役及实际空闲恢复另记交付事实。
