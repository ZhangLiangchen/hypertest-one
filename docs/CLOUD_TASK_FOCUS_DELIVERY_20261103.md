# Cloud 任务职责精简交付（2026-11-03）

## 变更范围

按 [ADR-038](architecture/ADR-038_TASK_FOCUSED_CLOUD_INPUTS.md)，移除项目资源页和独立资源配置新写。项目详情编辑两个仓库；创建与编辑草稿必须提供 MR/PR 地址及当前 Project 版本，服务端保存内部仓库快照。GitLab 项目组中的具体被测仓库由范围内 MR 地址确定。

MR 用于 Agent 检索改动，测试环境由任务 prompt 描述；新快照不含环境或预期部署版本。源码检出引用可省略，独立记录实际源码身份，不表示 SUT 部署身份。任务生命周期、下发、产物与原 key 恢复保持。

旧任务、报告、凭据及冻结快照未删除；CONFIGURE 新写返回 410，历史 GET 只供原请求读回。本轮无 schema 迁移。部署整合已经在运行的原生 Worker Memory 接线（原提交 `166f28878960246753de92678a9099797a801c04`），防止更新 Worker 时遗漏现有功能。

## 验证与部署

- 后端直接相关回归 126 项通过；Native Worker/SDK 单测 40 项通过；历史 SSH 权限 23 项通过；补充确切 `.git` 仓库范围拒绝后，MR/项目输入文件 25 项通过（替代此前该文件 24 项结果）。共 190 项不同测试。覆盖 MR/仓库范围、Project 版本、原 key、无环境解析/下发、历史授权拒绝、Worker 领取恢复及 Memory 接线。
- Web 相关回归 74 项通过；最后的草稿授权更新后重跑受影响的创建/编辑 18 项通过。TypeScript、Impeccable 检测（无发现）、Ruff 和差异检查通过。
- 后端数据库测试仅使用本轮临时 `hypertest-task-focus-test-db` 的 `hypertest_test`，业务库未写入 fixture。
- 旧手动 acceptance 脚本停止创建项目/资源/任务及新解析/下发，保留已记录请求的原 key 读取与恢复；新工作使用当前任务页面。
- 该旧脚本的直接调用回归 117 项通过：退休的新创建零 POST，历史 UNKNOWN 保持原 key GET。后端及控制器合计 307 项不同测试通过。

临时测试容器和本轮测试临时目录已清理。部署尚未执行，最终 Git SHA、镜像在完成后更新。

## 功能验收边界

本轮不创建业务验收任务、不触发模型或 SUT，也不更改已有任务。浏览器控制连接不可用（browser access host unavailable / cgWindowNotFound）；相关自动回归和部署健康不代替 USER_OWNED 页面及业务验收。
