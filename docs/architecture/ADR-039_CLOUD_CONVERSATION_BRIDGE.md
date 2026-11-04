# ADR-039：任务内对话与多会话宿主薄 Worker

日期：2026-11-04（Asia/Singapore）。状态：Accepted；实现、部署和用户验收分别记录。

## 对话合同

Agent 的阶段说明、阻塞原因和本轮回复不以最终报告或任务完成为回传前提。用户可在任务页发送普通文字；Worker 桥接官方 Harness SDK，Harness 继续负责推理、工具和团队编排。

- 消息绑定 Project/Task/Attempt/session/generation，拥有独立提交顺序游标，不逐条推进 Task.version。仅保存根会话 assistant/message 的用户可见 text；不保存 reasoning、工具原始负载、系统提示或子会话正文。对话是执行沟通，不自动成为正式测试资产、PASS 或独立执行证明。
- 完整文字通过秘密检查后才能进入私有 spool 和平台；单条拒收显示空正文及固定原因，其余消息继续。验证不可用时有界内存缓存；无法保存的正文记 CONVERSATION_GAP，不伪称已归档。
- 用户消息经 cloud:control、原 key/摘要和目标检查后保存 QUEUED；Worker 原子单次领取 DELIVERING，SDK session_prompt 返回 messageId 后记 DELIVERED。入队不证明已处理；失答 UNKNOWN 不自动重发，迟到的原 SDK 回执可追加确定观察。
- 输出 append 和 SDK ack 只幂等补送不可变观察。匹配的原 capability 在 fence 后可补齐所属 generation 历史，不能发送消息、写报告、改变 Task/result 或恢复执行权。普通输入和原业务 mutation 的 UNKNOWN 规则不变。
- Worker 重启后的私有 spool 补送使用宿主 Worker 认证与服务端已存在的原 Project/Task/Attempt/generation grant 关联核对，不落盘执行 token。recover-append/recover-ack 仅补齐原观察，既不取回 work capability，也不领取输入或调用 SDK；无原授权记录或目标不匹配则拒绝。
- 普通文字不走可解释命令的 session/query。现有结构化提问保留其原问题及回答协议，在同一界面呈现。
- 正常 idle 且无正式完成 handoff 时保留 SDK client，等待期间不调用模型。独立 AWAITING_REPLY 不冒用已停止的 WAITING_INPUT。正式完成先接收最后输出并关闭该 runtime，再走原完成合同；异常/取消/失租保留对话并显示系统事件。

## 多会话领取

一个 supervisor 默认维护四个独立槽，容量由宿主配置；各槽有独立 SDK client、工作区、通道、lease 和 reporter。一槽等待或任务级故障不阻止其他槽；容量满则排队，不宣称无限并发或 OS 强隔离。

CloudWorkerClaimState 主键扩为 (worker_id, slot_id)，各槽保留单调 sequence、原 key/digest、closed 和目标绑定。锁及本地 pending 按槽隔离；Task 行锁和唯一未终态 Attempt 保持。旧单槽映射 legacy，原正文/digest/高水位不改；旧协议只恢复原领取，不再新领。重启先处理所有遗留 pending，包括缩容后槽，不重 execute。检查与执行在同一 Attempt/session 互斥，不封锁整个 Worker。

## 原会话续接

RESUME_ATTEMPT 是 Operator 显式控制：原 owner 已 fence、原 key/已知外部操作/委派已收口且有停止观察，才能将同 Attempt 转 PREPARING，固定原 Worker 和新 generation。采用 PRE_PROMPT_ANCHORED，或明确授权 OPERATOR_ADOPTED。

人工接管从本次核对起建立基线，记录操作者、时间、原 session/工作区/home、源码及 runtime/profile 指纹和历史锚点缺失事实。不补造原始 anchor、原 prompt 回执或过去停止证明。Worker 核对原目录/会话/旧 inbox，先固定本次身份并读回，再恢复原 session、仅发送新的 continuation。不 checkout、不发送原任务全文、不创建替代会话；旧输入或提交未决时拒绝继续。冻结输入、旧结果及已接受产物不变。旧固定预算 profile 未纳入本轮续接，明确拒绝而不跳过其结算合同。

历史消息只从明确关联的原会话补读公开内容，标记 IMPORTED_HISTORY 及补录时间；不触发模型，不充当原身份认证。

## 替代范围

本决定覆盖 ADR-032/036 的全 Worker 单槽限制、任务级异常必须停止整个 Worker，以及领域 §51、TMP §46、技术架构 §45 中续接一律未支持的旧声明。原 key、fencing、已知 UNKNOWN、授权及报告真实性继续有效；Local/Memory 独立权限不变。验证限消息/领取/续接相关回归；真实业务测试和用户验收单独记录。
