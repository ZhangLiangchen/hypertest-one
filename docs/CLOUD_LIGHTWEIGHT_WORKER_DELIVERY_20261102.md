# 轻量 Harness Worker 本机交付（2026-11-02）

[ADR-032](architecture/ADR-032_LIGHTWEIGHT_HARNESS_WORKER.md) 记录快速原型阶段的职责取舍，以及未来全容器化项目资源隔离方向。本文只记录本轮本机部署和检查，不把部署健康、合成验证或 SDK 配置检查视为真实测试验收。

## 交付和运行身份

- 源码：已推送 `dafffd59a5e7e6fe39cd11d6a09c4d01257ff3d0`。
- API 镜像：`hypertest-mac-api:dafffd5`，`sha256:9609f86813071c455a52471407136a529a750a7520cf8aab264b51ec7c2b40c0`；Web 镜像：`hypertest-mac-web:dafffd5`，`sha256:b753495d869ebb2f28bc13ff24191a420b7035df68c85588c50258fbdc236dc9`。两个镜像 revision 均为上述 SHA。
- 本机 macOS LaunchAgent `com.hypertest.cloud-native-worker` 使用同一提交的宿主 Worker / DeepSeek SDK 适配器和单独的 Worker 身份；旧 Docker Cloud Worker 已停止，没有删除其容器或持久卷。数据库 schema 为 `0040_cloud_agent_auth`，本轮无需迁移。
- 本机部署 overlay 为 `~/.local/share/hypertest-mac/native-worker-dafffd5.compose.json`，与现有 Compose/BFF/WireGuard/Cloud API overlay 一起使用；Worker 配置和状态位于 `~/.local/share/hypertest-mac/native-worker/`。Worker 独立 bearer 通过受限 TLS 入口认证，值不进入仓库、Agent prompt 或交付记录。
- 在已有用户 `~/.dsh` 中初始化了 `sdk` profile 并安装固定 SDK/runtime `0.2.1rc2`；解析到 provider 和 model 配置，但**未验证模型认证、真实请求或插件是否可用**。`sdk` 是独立 profile，不自动证明用户已有 `web` / `desktop` profile 的插件已经装入。Git/gh/glab、SSH agent、网络和项目工具由宿主用户环境管理。

## 检查及边界

- 独立临时 PostgreSQL 测试库完成合成集成：领取、版本解析、下发、宿主 Worker 与模拟 SDK handoff、报告提交及固定版本读回；合成结果为 `NOT_RUN`。另验证失租 fence 后原回执仍可读、错误 capability 被拒绝。临时测试容器已清理，未向业务库写入 fixture。
- 本轮直接相关 Python 检查 55 项通过；Cloud Web 24 项与 TypeScript 类型检查通过，Ruff 和差异检查通过。API/Web 镜像构建、API 健康、WireGuard Web HTTP 200 与 Worker 专用认证拒绝/目标不存在路径通过。
- 原生 Worker 已由 launchd 启动，API 观察到空闲 claim 请求成功。旧容器 Worker 停止；切换前没有活动或待领取的 Cloud Attempt/Resolution。本轮没有创建或下发真实任务，没有调用模型或被测系统，也没有进行用户功能验收。
- 宿主进程不构成项目间强隔离。原生完成记录只观察直接 SDK 进程退出；其他本地进程为 `UNKNOWN`、外部操作为 `NOT_OBSERVED`，reported result 不自动成为独立 Evidence。原领取或写入失答必须核对原身份和原 key，不自动重试。
- LaunchAgent 运行异常后不自动重启，避免在未知领取后继续工作；重启前应核对 `state/claim-pending.json` 和原服务端记录。既有 shell 中临时设置的 token 不一定进入 launchd 环境；应使用该用户已有登录或单独配置服务环境，不能凭服务已启动推断 Git 或模型认证有效。

后续用户验收：在合适的实际项目与已配置 Harness profile 上，由用户确认 Git 访问、Harness 插件与模型、实际测试及报告回传。公司环境发行和未来项目资源隔离的全容器化仍需各自设计、实施和验证。
