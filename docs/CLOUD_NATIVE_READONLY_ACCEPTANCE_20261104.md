# Cloud 原生查看页只读部署与实际验收（2026-11-04）

原生 Harness Web 查看 Cloud 会话现使用只读历史与持续观察，不再因打开页面激活 Agent、取得原会话写锁。用户要求的“先保持原生页面打开，再离线保存消息并恢复 Worker”，以及归档拒绝、自动反馈、修正接受和继续对话，已在指定原任务上实际验证。范围是 HyperTest 平台会话与归档，不代表原 SUT 业务测试通过。

## 实现与边界

旧原生 `session/follow` 在返回历史快照后会后台 `promote`，继而 `resolveObservedAgent/resume` 并持有写锁；仅打开历史页就可能阻塞宿主薄 Worker。此前通过启动顺序释放旧锁的操作事实保留在[前轮异步会话验收](CLOUD_ASYNC_SESSION_ACCEPTANCE_20261104.md)，本轮针对查看路径替代该临时处理。

- 使用独立 Cordis 插件 `hypertest-cloud-readonly-view`，从固定 Git 提交安装到既有 Web profile；没有修改官方 `app.asar`、会话日志或 SDK。
- 范围由精确 `cloud-UUID` 根及原生 `parentSession` 父链确定。Cloud 子会话不能因名称不同绕过只读限制；其他个人会话保持原生行为。
- Cloud 查看完全不调用原 `follow`。复用原生地址校验、分页和纯内存投影，通过官方 `open(..., "read")` 读取已持久化记录；每个会话共享一个 500 ms 观察器，向所有打开的页面提供外部 SDK 新追加的记录和投影。
- 不把尚未闭合的 turn 合成为中断、idle 或完成，不发布伪 Session，不写 seed，不取得写 handle。已有来源状态、消息序号和原生父链保留；身份、父链或已观察日志前缀改变时停止观察，不回退到恢复 Agent。
- 原生页面通过官方 Composer block 扩展禁用 Cloud 输入，提示回 HyperTest 发送。服务端同时拒绝 Cloud 显式写入和隐式 Agent lookup/context 激活；未知 SDK 投递仍不重发。
- 所包装的原生方法按实际 App 实现固定指纹，使用 Cordis 原始 Service 方法核对。指纹不匹配时 Cloud 观察和写入入口保持拒绝，不卸载后退回可写 `follow`。

这项修复解决所部署 Web profile 的 Cloud **查看路径占写锁**。它没有新增通用跨进程 writer attach 协议，也不声称可以抢占其他真正执行中的原生写入者。

## 固定部署

| 项目 | 记录 |
| --- | --- |
| 已推送源码 | `e13fed71be94f8ce7d5d39675460c9b2132fd334`，分支 `codex/cloud-native-readonly-20261104` |
| 原生宿主 | 系统 LaunchDaemon `com.liangchenzhang.dsh-web`，既有 `10.66.66.3:3080` Web 服务 |
| 安装位置 | `~/.local/share/hypertest-mac/cloud-native-readonly-20261104/releases/e13fed71be94f8ce7d5d39675460c9b2132fd334/` |
| profile | `~/.dsh/profiles/web/cordis.patch.yml`；仅加入本轮服务端插件、配套客户端及 package manifest |
| 实际 App | `0.2.1-rc.5`；`app.asar` SHA-256 `8dad52f295bdbe9fa71948fdf38ac2ce3c910213d3b89c37174b2af77db9fb31` |
| 服务端插件 SHA-256 | `2f86310f938b1b9e7236317aeebbee04184aa2ba93fb47b8e5f22e42f4b3013a` |
| 部署完成 | `2026-11-04T06:40:56Z`；原生 Web PID 从 `64403` 更新为 `72402` |
| 重启方式 | 一次正常 SIGTERM，由现有服务管理器启动；没有暂停新宿主以安排 writer 先后顺序 |
| 访问边界 | 未认证请求仍返回 `401`；既有 WireGuard、端口及凭据配置未改变 |

本轮部署只更新原生 Web 插件，不构建平台容器，不做数据库迁移。后续验收的 Worker 停启是明确的离线恢复验证；原生 Web PID `72402` 自上述部署完成起，在下面已记录的验收链路中持续运行，没有依赖再次重启查看宿主让位。

## 自动回归

本轮直接相关 **15 项通过**，与下节真实任务验收分别记录：

- 后端适配器 9 项：根/子身份、原生父地址校验、未闭合 turn、共享观察器与外部追加、原生读 handle 关闭/取消、只读拒绝、非 Cloud 保持原行为、方法指纹不匹配及身份变化不回退。
- 原生客户端 5 项：只读输入提示、父链覆盖、个人会话、列表变化与扩展清理等。
- 实际 App Web 与固定 SDK `0.2.2a2` 双宿主 1 项：使用临时合成会话，先保持原生 `follow`，再由独立 SDK 恢复原 session；打开页面不改日志字节，两次元数据追加均可见且最终标题投影正确，Cloud `rename/prompt` 被拒绝，个人会话仍可改名。合成 provider 请求数为 `0`。

对应 `tests/test_harness_readonly_sessions.mjs`、`tests/test_harness_readonly_sessions_client.mjs`、`tests/test_cloud_native_readonly_web_sdk.py`。真实 App 回归使用实际安装的 Controller，不以 SDK 中的相似实现代替。以上结果不代表模型、SUT 或用户业务验收。

## 指定原任务实际观察

- Project：`01a181ac-ba63-7c24-b695-bfb498829b63`；Task：`01a1a0e9-8db8-7be9-8a7c-43c42518a6b6`。
- 原 Attempt：`01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`；原 Harness session：`cloud-01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`。
- 没有创建替代任务或替代会话。测试消息要求只确认平台恢复与归档纠错，不重跑旧业务。

下表全部为 UTC，日期均为 2026-11-04。

| 时间 | 操作与观察 |
| --- | --- |
| 06:51:28 | 对目标原会话建立持续的原生 WebSocket `follow`，收到历史快照，cursor `1472`；保持同一观察流打开。真实 Chrome 同时打开目标原生标题页，Cloud 输入框显示只读提示并禁用。 |
| 06:52:27 | 在原生查看页和持续观察流保持打开时 bootout Worker。此时旧 SDK PID `64494` 仍在退出，因此不把这一瞬间误记为锁已释放。 |
| 06:52:57 | 确认旧 SDK writer 已退出，目标 session lock 没有打开的文件持有者；原生查看页仍打开，Web PID 仍为 `72402`。这一步直接验证查看页没有补占写锁。 |
| 06:53:59 | 在 HyperTest 实际页面发送消息，原 key `web:e09a998f-7f23-41c0-bbae-b63f6130d150` 保存为 `QUEUED`；此时 Worker 离线。 |
| 06:54:09 | bootstrap Worker，原生 Web 及查看页继续保持。没有关闭原生页、重启原生宿主或发送第二条消息来唤醒第一条。 |
| 06:54:27 | 同一 Attempt / 原 Harness session 以 generation `55` 恢复并回复 `B-RESUMED`；原生页面实时显示后续内容。 |
| 06:55:09 | 经同一 Web BFF 的 `send_once.py` 提交较长的归档纠错指令，原 key `web:8027c980-4201-42c1-9caa-4bc80d44c80b`。这条不是浏览器按钮发送。 |
| 06:55:30 | 坏贡献 `ht-native-view-20261104-b1-invalid` 得到 `LOCAL_REJECTED` / `HANDOFF_PAYLOAD_INVALID`，`platform_operation_submitted=false`。 |
| 06:55:54 | Agent 收到 Worker 自动反馈后发布修正并回复 `CORRECTED`；修正贡献已取得 task v43 的 `ACCEPTED` 收据和独立 REPORT revision 1。 |
| 06:56:50–06:56:53 | 在真实 HyperTest Chrome 页面再次输入并发送，原 key `web:0a2ce46e-b74a-4408-8f95-9976ad07314e` 为 `DELIVERED`，Agent 回复 `B-STILL-ALIVE`，仍为同一 Attempt / session。 |
| 06:57:23 | 锁检查对应 Worker `73941` / SDK `73949` 执行链，目标锁没有原生 Web 持有者；Web PID 始终为 `72402`，没有再次重启。 |
| 06:58:39 | 验收结束后主动正常关闭额外的只读 WebSocket 观察进程，Chrome 原生 tab 仍打开；只是结束观察，不是停止 Harness 会话或标记任务完成。 |

HyperTest 与原生页面的浏览器可访问性树均实际显示恢复、坏贡献发布、修正、继续存活四个验收标记。原生 Cloud composer 始终只读禁用，验收期间没有 reload 页面来取得更新。首次恢复消息及最后继续对话消息由真实浏览器输入并点击发送；中间较长归档指令经同一 Web BFF API 提交，不把三条都记作浏览器按钮发送。

额外的原生 WebSocket 观察从 `06:51:27Z` 持续至 `06:58:39Z`，仅有一个初始 snapshot，cursor 从 `1472` 连续推进至 `1571`，记录中 `stream_error` 和远端 `end` 均为 `0`。结束时由验收方主动关闭观察器，未用重开流或刷新页面掩盖中断。

三条消息按各自原 key 读回 `DELIVERED`，SDK message ID 分别为 `fb41f09d-8ce2-4d1d-b190-5104a726921d`、`2026a64d-06e5-4991-bfcf-a4660444c340`、`a52651ce-0450-413c-a5dd-988d9ae46fc0`。没有重发未知投递，没有创建替代原会话。

已确认：原生查看先持续存在，Worker 离线时普通消息仍保存；Worker 返回后继续同一原会话，原生查看同步收到更新。此链路不依赖“Worker 先获得锁，再打开查看页”的启动顺序。

## 归档纠错与最终读回

原 Agent 发布独立平台验收 REPORT，先使用 key `ht-native-view-20261104-b1-invalid`，收到 Worker 自动反馈后使用新 key `ht-native-view-20261104-b1-corrected` 修正；坏贡献及其拒绝记录保留。

- 坏贡献：`LOCAL_REJECTED` / `HANDOFF_PAYLOAD_INVALID` / `platform_operation_submitted=false`，没有伪造平台接受收据。
- 自动纠错：反馈 ledger 只有一条对应记录，状态 `DELIVERED`，SDK message ID `6a2cfbac-28ac-4082-9a93-d6e4fedcbeee`。没有手动重连、接管或重复投递来推进修正。
- 修正收据：`ACCEPTED` / task v43，平台 operation key `c:f32b155b5fb4dba0ff95fd921678043d92908c9bb468d51d1d98ccc055ab2882`。
- 接受资产：独立 REPORT `01a1a557-babf-71a1-8be5-885ecb5ce8f4`，revision `1` / `NOT_RUN`。完整 task readback 已核对该报告的正文、身份和固定版本，报告只记录本次平台验收，不替换原业务结论。
- 最终平台快照：task v43 / `RUNNING` / `NOT_RUN`，runs `0`、attempts `1`、assets `17`；本轮新 REPORT 只有一条 revision `1`。原 Attempt / session generation `55`，会话 `AWAITING_REPLY` / `ASYNC` / `READY`，`can_send=true`、`can_reconnect=false`。归档修正后真实网页继续消息得到回复，没有把任务改为 COMPLETE 或 PASS。

这轮实际验证覆盖原生只读查看持续打开时的消息恢复、贡献局部拒绝、反馈驱动修正和后续对话。原 SUT 业务测试、交易或其他外部业务动作未由这些平台结果获得通过结论。

## 本机证据

证据目录为 `~/.local/share/hypertest-mac/cloud-native-readonly-20261104/`：

- `deployment.json`、固定 release 的 `installation.json`：部署 SHA、插件校验、profile、原生 App 与 PID。
- `acceptance/reader-first.json`：原生页保持打开、旧 SDK 退出、锁无持有者的先后记录。
- `acceptance/native-follow-view-b-20261104T065127Z.jsonl`：持续原生观察流。
- `acceptance/observations.jsonl`、`final-conversation.json`、`original-message-1.json` 至 `original-message-3.json`：对应时点的平台会话状态、消息原 key 及最终投递读回。
- `acceptance/archive-request.json`、`archive-receipt.json`：归档验收指令及其消息提交记录；消息保存与贡献接受是不同事实。
- `acceptance/invalid-local-rejection.json`、`archive-feedback.json`、`corrected-accepted-receipt.json`：坏贡献拒绝、唯一纠错反馈及修正接受收据。
- `acceptance/final-readback.json`、`final-summary.json`、`result.json`：固定接受版本及最终平台状态；`result.json` 已完整读取并核对上述最终断言。
- `acceptance/independent-worker-lock-20261104T065723Z.json`：Worker/SDK 与原生 Web 的进程、锁归属。

运行时认证仅在内存使用现有凭据，不将 token/cookie 写入仓库或验收交付物；不读取或公开隐藏推理、原始工具正文来补造结果。
