# 指定原会话异步对话与归档纠错实际验收（2026-11-04）

用户明确要求使用既有任务发送消息，验证继续原会话、可修正归档错误不中断对话。本轮已实际执行，不以健康检查替代。范围只包括平台对话和归档，不代表原 TRON 业务测试通过。

## 对象与结果

- Task：`01a1a0e9-8db8-7be9-8a7c-43c42518a6b6`，Project：`01a181ac-ba63-7c24-b695-bfb498829b63`。
- 原 Attempt：`01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`；原 Harness session：`cloud-01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`。未创建替代任务或会话。
- 最终读回：task v41 / RUNNING / NOT_RUN；会话 AWAITING_REPLY / ASYNC / can_send=true / can_reconnect=false。
- 成功恢复后的 generation 始终为 53；从首条消息交付到最后回复未出现新的 INTERRUPTED。任务未 COMPLETE，也未被改为 PASS。

## 实际链路（UTC+8）

| 时间 | 操作与观察 |
| --- | --- |
| 13:32:49 | 经实际 Web BFF 提交一次验收消息，持久化 QUEUED；禁止原业务测试、交易及旧待办。 |
| 13:54:51–13:55:02 | 处理原生宿主持锁后，Worker 自动投递原 key；Agent 返回 `ASYNC-ACCEPT-20261104-A-RESUMED`，说明原任务与此前工作上下文。用户随后发送的“当前阻塞在哪里”也取得原 SDK 回执。 |
| 13:55:20 | 发送第二条消息，要求 Agent 自己发布一份专用 REPORT 贡献，故意留空 markdown，再等待 Worker 反馈后修正。 |
| 13:58:00 | `ht-async-archive-20261104-a1-invalid` 被本地拒绝：LOCAL_REJECTED / HANDOFF_PAYLOAD_INVALID / platform_operation_submitted=false；没有伪造 ACCEPTED 收据。 |
| 13:58:02–13:58:37 | Agent 返回 BAD-PUBLISHED；Worker 纠错反馈取得 DELIVERED 回执，Agent 用新贡献 key 发布修正版，返回 CORRECTED。期间没有重连、接管或重新发送验收消息。 |
| 13:58:34 | 修正版 `ht-async-archive-20261104-a1-corrected` 被接受，task v41。独立 REPORT `ht-platform-archive-check-20261104-a1`，asset `01a1a523-45dc-70b4-916d-e1a6e1a43a57`，revision 1 / NOT_RUN；正文明确只记录平台验收，不替代业务报告。已通过完整 task readback 核对正文、身份与结果。 |
| 14:00:49–14:00:52 | 通过真实 Chrome 页面输入并点击“发送消息”，保存后自动交付；Agent 回复 `ASYNC-ACCEPT-20261104-A-STILL-ALIVE`，确认同一原会话仍可继续。 |
| 14:02:51 | Web 更新后刷新真实页面，仍显示上述回复、“等待你的回复”和可用输入框；空正文的 Worker 传输状态不再刷入聊天。 |

三条验收消息的原 key 依次为 `web:9bbe6734-af70-4663-9388-629ac4d0b861`、`web:f4492ca3-06eb-4f33-9911-10bb002a9c51`、`web:14ad606f-bfa7-496c-a186-6f0ca0ccf55e`；全部按原 key 读回 DELIVERED，SDK message ID 分别为 `2f51e847-64e8-484f-9194-15d1b0ce25f0`、`04f1af24-4486-4eb7-970c-d0d363d33ec3`、`755d5fcd-ffa5-4433-9d52-f45b362821c5`。没有重发结果未知的请求。

纠错反馈的私有 ledger 为 DELIVERED，SDK message ID `4f2c6190-d233-49cb-8120-599202c67b69`。原坏贡献文件与本地拒绝记录保留；修正使用新 key。反馈在原轮运行期间进入 Harness 原生队列，因此本轮证明运行中纠错不中断，不单独宣称覆盖了所有 idle 唤醒时序。

另有实际变化：Worker 也投递了原先的 REPORT_CONTENT_REJECTED 反馈，Agent 将旧脚本贡献修正后以 `04b-upload-e2e-script` 归档，artifact `01a1a521-edff-75b4-8ece-c97aff3ea29e`（v40）。因此本轮不能描述为“既有文件和产物完全未变”；旧拒绝贡献及反馈保留，没有将其未知提交直接重发。Agent 报告未执行原 TRON 交易，本轮没有独立核验原业务结论。

## 真实故障与限制

首次消息只保存成功，原会话恢复失败。核对官方实现与实际锁持有者，发现本机 `com.liangchenzhang.dsh-web`（3080）的原生历史页 follow 会激活 Agent 并长期持有 session 写锁。来自 WireGuard 客户端的页面会自动重连，所以普通服务重启后又先于 Worker 取得写锁。

已部署两项故障修复：固定官方 JsonRpcError / -32603 / 当前 session 的完整 owned 错误映射 SDK_SESSION_BUSY，Worker 内部退避；Fence 与对话 append/recover-append 共用固定原因类型，修正实际发布时的 422。任意异常文本不作为公开状态透传，不删除锁或复制会话冒充恢复。

本次操作先通过官方只读 API 确认原生宿主没有运行中 Agent/jobs；随后正常 SIGTERM，并短暂暂停替换宿主启动，让 Worker 先获得原 session，再恢复原生 Web。没有修改登录、WireGuard、权限或历史文件；没有要求用户执行接管或重连。初次关闭桌面窗口不能释放独立 Web 宿主锁，未将该无效尝试记为修复。

**限制：现有官方 SDK 不支持附着到另一个活跃写入者。本次既有写锁通过受控服务启动顺序释放，不能把这一步描述为 Worker 已能自动释放任意原生查看页的锁。** Worker 此后持有原会话，普通消息与归档纠错均已由 Worker 自动处理。若未来再次被独立原生宿主占用，Worker 会保留消息并退避；跨进程写入者协作仍需 Harness 能力支持。

## 交付与检查

- API：`3f58cad3900225b73a27af89c8ed347b2e1fc3d3`，镜像 `hypertest-mac-api:3f58cad` / `sha256:0c5af4c78251662a2f5ff2eca14144afe39355aa1177cb1a15464d1eede093ae`。
- Web：`d30d0962d548cbac839a5b0e1f453c3dcf96043d`，镜像 `hypertest-mac-web:d30d096` / `sha256:58b2a3d0deadcd12efa5d49245b71f71e272e7195384eedc8d370301104e87e6`。
- 本轮4个 Worker 模块来自 `1df0fdb52f8a33c77a176fa7c9471606ec25b916`；后两个提交未改 Worker。Worker PID 64379；schema 仍为 0048_concurrent_claim_slots，无迁移。
- 96 项相关运行时/桥接/Worker 回归、2 项专用测试库 fence/退避回归、4 项真实 HTTP 对话发布与恢复回归通过；Web 17 项及 TypeScript、Ruff、diff 检查通过。业务库没有自动回归 fixtures。
- API 叠加旧镜像构建触发 Docker max depth，已恢复旧服务后改用该推送 SHA 的仓库 Dockerfile 完整构建；没有继续累积失效层。后续 Web 单独部署，未重启已恢复的 Worker/API。
- 浏览器连接器不可用，最终改用原生 Chrome UI，完成真实发送及页面读回。首两条消息经与网页相同的 BFF 路径发送，不能声称三条都由浏览器按钮发送。

本机操作证据位于 `~/.local/share/hypertest-mac/cloud-async-session-20261104/acceptance/`：`result.json`、`final-conversation.json`、`final-readback.json`、本地拒绝记录、纠错 ledger、接受收据与受控重启记录。部署身份见相邻的 `busy-deploy/`、`reason-contract-deploy/`、`chat-view-deploy/`。认证凭据未写入这些证据文件。
