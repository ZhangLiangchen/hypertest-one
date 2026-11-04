# Cloud 使用框架项目并归档原产物（2026-11-04）

## 结果

按用户纠正，Cloud 与本地采用相同的框架测试流程：Agent 直接在测试框架项目内工作，自主组织测试，产物留在框架原目录；HyperTest 传递任务/用户消息并归档 Agent 明确提交的原文件。相关决策见 [ADR-040](architecture/ADR-040_FRAMEWORK_PROJECT_SESSIONS.md)。

已先读取当前 xblock 框架的 AGENTS.md、docs/codex-sut-operating-rules.md、README.md、Makefile。框架已有 artifacts/allure-results、artifacts/logs、docs/usecases、docs/reports；不建立平台专用测试产物目录，不为归档调用会重新执行 pytest 的 make report。

## 实现与部署

- 已推送并部署代码：`b08782f008bc44ad8b39061189b9dc361da9bbdb`，分支 `codex/framework-session-project-20261104`；包含已上线的会话对话和并发 Worker 改动。
- 新 SDK 会话的原始目录和实际 cwd 都是复用的框架仓库；项目以完整仓库身份区分。首次准备后不自动覆盖已有分支/修改，是否使用 Git 工作树由 Agent 决定。
- xblock 框架目录：`~/.local/share/hypertest-mac/native-worker/framework-projects/6a0d6d8e8bdfc0556158992ec2e4380359db1c947b8f727d72bfadb3fa57a7dd/hypervise_pure`，初始来源 SHA `5122a6bf29e739d78d2938981fee17ed744bf9ad`。源码初始化没有执行测试或模型。
- 官方原生项目名 `hypervise`，ID `8f0e20ee-5236-4af7-8b12-d20fd36a19a3`。桌面 Harness 单宿主维护分组；已实际观察侧边栏显示该项目。独立 SDK profile 不并发写项目 registry。
- Worker 按固定提交更新所需模块，重载后 PID `32548`，源文件摘要核对一致。桌面 Harness 重载了归组适配。API/Web/数据库未重启，schema 保持 `0048_concurrent_claim_slots`，访问配置与凭据保持。
- Agent 明确提交的产物路径相对于框架根目录，Worker 直接读取原文件；消息/回执仍使用内部独立路径。既有会话继续按原目录恢复，不改变其身份。

## 检查和剩余事项

8 项框架目录/原文件归档检查、49 项恢复/身份/运行时关联检查、5 项宿主插件检查通过。固定官方 SDK 的单个集成检查通过：真实创建临时根会话与子会话并归入 hypervise，假 provider 请求数为 0。均属于自动回归，没有新增 Cloud 业务任务或执行 SUT 测试。

尚未进行新 Cloud 业务任务的用户验收。旧会话没有官方跨目录改组接口，本轮没有修改旧 header 或搬动日志；旧会话仍可能出现在未分组，不能宣称历史归组已经完成。

原执行 `01a1a117-9488-75d9-9cd0-830202d5e38c` 与 xblock 执行 `01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba` 仍为 RECOVERY_REQUIRED / NOT_RUN，已有接受记录保持；本轮没有续发原提示、重跑测试或重发未知操作。

现场记录：`~/.local/share/hypertest-mac/framework-session-20261104/deployment.json`；`CURRENT_DEPLOYMENT.json` 增加 `native_worker_framework_project_overlay`，保留其他部署记录。
