# 2026-10-23 本地分支与工作区整合记录

本次以 `55de50e` 为已有集成基线，将 native 实现、正式验收原件、0918 原工作区和 preintegration 归档纳入本地 main 历史。保留所有工作区、分支和原始文件，不推送远端、不部署、不执行测试。

[逐路径清单](manifest.json)覆盖原来的 419 个 dirty 路径，保存原 HEAD、SHA-256、可恢复的 source commit、main 对应路径与逐项处理原因。413 个正式文件均有字节精确的提交原件；6 个 `.playwright-mcp` 浏览器临时文件仍保留在原工作区，不进入 Git。

当前 main 新增 161 个正式验收及交接文件，均为原样导入；未覆盖任何原有同路径文件。其余重复或较早的实现/规范保留在合并祖先中，当前实现继续采用基线已有的 Project 生命周期、Local 原生绑定、Cloud 原键对账、TLS 与分页校验。旧 Cloud migration 0023/0024 对应当前 0025/0026；不重复注册。历史归档合并表达原文保全，不表示旧快照运行资格，也不升级测试结果或证据来源。

主要历史材料：

- [原生框架报告](../../acceptance/native-framework-20261021/REPORT.md)
- [原生 API 与交接报告](../../acceptance/native-platform-20261021/REPORT.md)
- [原生 MCP 报告](../../acceptance/native-mcp-20261022/NATIVE_MCP_REPORT.md)
- [会话同步正式报告](../../acceptance/session-task-sync-20261021/CURRENT_OFFICIAL_REPORT.md)
- [原交接记录](../../handoffs/CODEX_SESSION_TASK_SYNC_20261021.md)

较早版本的默认 XBlock 工作流和 native 验收说明可用 `git show 9b8bf79:docs/CODEX_SESSION_TASK_SYNC.md` 与 `git show 9b8bf79:docs/architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md` 恢复。它们对应当时的流程与观察，当前入口以 main 现行规范为准。
