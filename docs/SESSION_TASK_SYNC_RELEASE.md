# Session task management — 0.2.0

> **历史或兼容资料：** 本文中的实施计划、配置步骤和部署/验收状态仅适用于所述 profile 与记录时点，不代表当前部署。现行入口见[文档导航](README.md)和[当前 TODO](TODO.md)；新 Local 接入见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)及 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。旧合同、事实和恢复边界按各自范围保留。

本发行新增 Codex 会话任务管理：一个实际会话对应一个任务，共享 Project，保存计划、用例修订、原始报告修订与来源明确的提交结论。平台不执行测试，既有 Runner、Harness、Gate 与执行历史保持各自语义。

MCP 新增 `hypertest_sync_task` 与 `hypertest_get_task`，仅需单独签发的 `task:sync` 项目授权。写入采用稳定幂等 key 与 expected version；发送后失答只查原 key。读取使用固定版本、有界分页，原文不截断，旧工具消息限制不扩大。新会话建立自己的任务，并显式链接历史任务及剩余工作。

源码由 Git 提交固定，发行 tag 为 `mcp-v0.2.0`。CI 检查 Python、数据库迁移与 Web；发行 workflow 从精确 tag 构建 wheel，manifest 记录源码提交、版本、大小和 SHA-256。部署者还须在远端测试环境核验目标服务与实际管理同步；构建通过不代表 SUT 测试已重新执行。具体执行状态以该次 CI 和部署验收记录为准。

只发布通用产品源码、规范、测试和安装资源。私有 SUT 的任务快照、原报告、执行原件、认证材料、主机私有路径及浏览器运行日志不包含在发行中。用户授权的测试资产同步使用目标环境实际 Project 映射和独立意图，不复用隔离环境的 UUID。

使用方法见 [Codex session task sync](CODEX_SESSION_TASK_SYNC.md)，架构决策见 [ADR-018](architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md)。
