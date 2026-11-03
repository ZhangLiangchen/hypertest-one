# Cloud 原生会话命名与历史读取排查（2026-11-03）

用户反馈原生 Harness Web UI 载入历史失败（提示 gateway），且 Cloud 创建的会话显示未命名。目标为 Task `01a1a0e9-8db8-7be9-8a7c-43c42518a6b6`、Attempt `01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`。

## 标题修复

此前 Worker 只传 session ID 与 prompt，未设置原生标题。现在 `task.title` 经 adapter/driver 进入每次调用的 Cordis 配置，在首个 prompt 之前由根 Agent 创建回调调用官方 `sessionTitle.rename`。原生标题使用用户来源并固定，既有会话 ID 与子 Agent 名称保持，不调用标题生成模型。每次调用的标题字节上限为 2048，覆盖任务名允许的 512 Unicode 字符；不修改共享 profile。

合并并保留实际部署的 Cordis 补丁 `baef8985260890a82b99f6e25cc7ba1b5eb08ceb` 后，修复已推送为 `c5a2fb09c2df3020f4fb107cf44766b3cb81b351`。23 项直接回归通过，包含固定 SDK、临时合成 home、loopback fake provider 与长中文标题；额外两项预检回归确认预检显式使用探针名称，失败时不领取新工作。Ruff、diff 检查通过，未运行全量或 DB suite。

更新既有 Worker 源码目录中的 `native_worker.py`、`native_sdk_adapter.py`、`native_sdk_driver.py`、`native_cordis.py`。部署前四个文件与已合并基线完全匹配，原 claim sequence 5488 已关闭、本地无待恢复 claim，Worker 已退出。固定 runtime 预检通过后启动 Worker，PID 44624；原 Task 仍 v12 / RECOVERY_REQUIRED / NOT_RUN，未重放原测试。没有重启 API/Web、改动 schema 或共享 Harness 配置。`CURRENT_DEPLOYMENT.json` 保留既有记录，增加 `native_worker_title_overlay`。

现存唯一目标会话也已通过原生 Web `session.rename` 精确改为“记录 TRON 带宽费并提供统计接口”，只提交一次，projection 读回一致；seq 1200 → 1201，仅追加一条 `session/title`，没有 prompt、turn/start 或工具调用，两个 inbox 均为空。

## 历史载入排查

- 3080 由 DeepSeek Harness Desktop `0.2.1-rc.5` 提供；Cloud 使用 SDK `0.2.2a2 / ce7073d`。两者使用同一个 `~/.dsh`，均支持 Session format v4。
- 沿用原生合法登录入口，只在内存使用认证信息；不打印或保存 token/cookie。实际读取 `session/projections` 成功，非空尾页 `session/page` 成功；只检查记录类型和计数，未输出历史正文或工具载荷。
- 旧 Desktop 的 follow/rename 会恢复 Agent 对象，不能仅按方法名推断会执行 prompt。静态核对显示恢复路径没有直接提交 prompt；维护逻辑仅在明确 wake 且 inbox 有待处理项时唤醒。原 SDK 已停止、两个 inbox 为空且无活动 goal 后，执行一次合法原生 follow，snapshot 成功，立即取消订阅。seq 1199 → 1200 仅增加 `session/end-seed`，无测试回合或工具执行。诊断中初次 assistantStream=false 请求因当前接口仅接受 true/省略而被边界拒绝，不作为用户 gateway 错误的复现证据。
- 这次未再复现用户看到的 gateway，不能宣称已确认其原始根因。实际读取证明当前会话可以被此 Desktop 打开，不能笼统归因为 CLI/Desktop 历史格式不兼容；版本不同也不足以单独证明兼容或不兼容。浏览器连接不可用，未观察用户页面刷新后的实际显示。
- 原生 Web 的会话恢复、SDK 执行和同一 Session 的写所有权仍需区分；本次没有改变原生 UI，也未验证 SDK 正在执行时由另一进程实时旁观的能力。

另一个独立问题：原任务 RECOVERY_REQUIRED 的原因是 `REPORT_CONTENT_REJECTED`。Agent 上传的源码包含 PEM header 字符串字面量，被当前内容规则拒绝；已有分析/设计/用例修订，尚无 Run/报告。本轮没有放宽该规则或续接该业务测试，也不将历史读取成功表述为测试恢复或通过。

本机部署证据位于 `~/.local/share/hypertest-mac/native-session-title-20261103/deployment.json`。
