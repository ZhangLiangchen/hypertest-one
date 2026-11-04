# Cloud 异步会话修复（2026-11-04）

## 问题与实现

指定任务的实际原因是 REPORT_CONTENT_REJECTED，旧页面将 RECOVERY_REQUIRED 和 Worker OFFLINE 统一显示为会话断开。按用户要求修正异步行为，而非仅替换文案：

- 普通消息先持久化 QUEUED，不依赖 Worker 在线，不在发送事务切换执行状态。Worker 领取时发现待投递消息，内部恢复原 Attempt 的 Harness 会话；无待投递消息的旧任务不会因部署自动执行。
- 已发送未确认的消息不重放；新的不同文字仍可保存，后续投递等待原消息确认。浏览器自动查询保存失答的原 key，用户无需接管、重连或手动核对。
- 明确未冻结且未提交的归档格式、内容和文件错误仅退回对应贡献；修正说明通过原 SDK 消息管道单次投递，Agent 对话继续。已冻结/UNKNOWN、权限和路径边界保持。
- 页面分别展示执行、消息处理与归档问题；结果仍来自归档报告，不以对话或投递状态推定 PASS。

## 验证与部署

消息、恢复及领取边界的 38 个直接相关回归用例通过；Web 消息 journal/组件 17 项通过，Next typegen、TypeScript 和机械检查通过。归档与 SDK/Worker 的 125 项直接相关回归通过，Ruff 和差异检查通过。已合入同期部署的 bca2112 会话归组/传输修复，原 key 重发路径由本轮异步领取替代；冲突解决后的恢复模块 14 项通过。已推送并部署 `93d201c902d14cd65077c8e8527054450636173a`（`codex/cloud-async-session-20261104`），保留同期已部署改动。复用既有专用 hypertest_test 数据库和依赖环境，不向业务库写入 fixtures。

浏览器访问宿主不可用，未进行真实浏览器视觉检查；组件渲染回归及部署后的实际 API 只读检查分别记录，不替代业务验收。

原 SDK resume_session 的通用 JSON-RPC 异常没有稳定的 missing/busy 细分码，因此保持通用退避；明确的宿主工作区缺失、身份错配、配置无效和恢复后 cwd 缺失按永久原因处理。没有按异常文本猜测或绕过 SDK 写锁。

## 用户验收

USER_OWNED：真实业务发送、Harness 继续执行及修正报告由用户验收。本轮不主动发送业务消息、运行模型或 SUT，不改写指定任务原结果及历史。

## 实际部署结果

- 时间：2026-11-04 13:07（UTC+8）。API `hypertest-mac-api:93d201c` / `sha256:bcf4f2fb36a743d7026fd59c9a65959197f8b2c94940ff0225e84b3837a5a074`；Web `hypertest-mac-web:93d201c` / `sha256:012d8d1243103968da656ee03b3182b5cac2c9a5c79e75ce9253d1464ba55af3`，两者健康。
- 宿主 Worker PID `55505`；本轮9个Cloud模块来自上述固定提交。既有 LaunchAgent、SDK/profile、WireGuard、BFF、TLS、数据库及独立知识服务配置保持。schema 仍为 `0048_concurrent_claim_slots`，本轮无需迁移。
- 通过实际 Web BFF 只读检查指定任务：v13 / RECOVERY_REQUIRED / NOT_RUN，7条既有消息；会话投影为 PAUSED、ASYNC、can_send=true、can_reconnect=false，具体原因 REPORT_CONTENT_REJECTED。任务页 HTTP 200。没有创建项目、任务、凭据或提交业务消息。
- 旧的中断记录不会因部署伪装成正在执行；后续普通消息先保存，由 Worker 内部处理原会话。可修正归档错误不中断的新行为已由回归验证，真实业务验证仍为 USER_OWNED。
- 宿主操作记录：`~/.local/share/hypertest-mac/cloud-async-session-20261104/deployment.json`、`readback.json`及构建日志。没有把浏览器不可用记为通过。
