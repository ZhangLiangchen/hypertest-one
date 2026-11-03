# Cloud 一键开始测试交付（2026-11-03）

已实现并部署一次“开始测试”：服务端持久保存开始意图，自动准备仓库版本，成功后在同一事务固定输入并创建唯一执行尝试。关闭页面不影响后续下发。创建仍保留任务名称、MR/PR 地址和可选测试说明，保存后进入草稿。

## 实现

- 新 `START_TASK` 操作复用原 key 回执保存意图；已有当前有效解析时直接下发，否则排队准备，Worker 接受解析后自动入队。接受开始请求不代表 Agent 已运行。
- 保留版本、摘要、当前授权及 Worker grant 检查；重复原 key 和重复接受不会新增 Attempt。取消、修改、撤权、过期或关闭 Cloud 后不允许晚到下发。旧 `RESOLVE_INPUTS` 及独立复测 `DISPATCH` 保持原合同。
- 任一未决准备（包括 `RECOVERY_REQUIRED`）阻止新的开始请求；确定失败后可显式重新开始，不自动重放旧操作。
- 详情页删除独立“准备源码上下文”操作，仅保留“开始测试”；SHA 放在默认折叠的代码版本详情中。任务输入意图删除旧“框架入口”展示；不改写历史输入，复测及尝试历史仍按其原合同展示。
- 保留并发上线的通用 E2E 模板提交 `73e621aa17e5ce5ba25b1f9de2585747b2e70d73`。

## 必要回归

- 后端：`tests/test_cloud_task_start.py` 及 `tests/test_cloud_tasks.py` 中相关解析、复测、取消用例，26 项通过。补充接受回执关联 Attempt 后，12 项 START 用例复查通过。Ruff 通过。
- 前端：`cloud-client.test.cjs`、`cloud-task-legacy-budget.test.cjs`、`cloud-task-edit.test.cjs`，38 项通过。覆盖单次开始、无自动页面提交、准备/未知状态阻止重复操作、原 key 回执读回及旧字段退出展示。
- 复用已有依赖和 PostgreSQL，仅在专用 `hypertest_test_start_20261103` 库写入合成测试数据；该库已删除。未执行真实 Git、模型或 SUT 业务验收。
- Web Docker 构建及其中的类型检查通过；API 镜像导入检查通过。

## 本机部署

已推送源码：`c3562917794c9b0d4ccda43170e2b70fe76f6834`，分支 `codex/cloud-one-click-start-20261103`。

| 服务 | 镜像 | 镜像 ID |
| --- | --- | --- |
| API | `hypertest-mac-api:c356291` | `sha256:72b9959f6cbac85a8900d55ae4fe70a6ad75a28a79e53b14a0370aeac57c0785` |
| Web | `hypertest-mac-web:c356291` | `sha256:e60109f9d09801c2b59a44d88162292f97b38ea2619bc7f7ca4fb16053614f53` |

仅更新 API/Web 镜像，完整 Compose 链追加 `~/.local/share/hypertest-mac/cloud-start-20261103/compose.json`。无迁移，schema 为 `0045_local_archive_status`。BFF/数据库容器保持，WireGuard/TLS 和其它配置未改变。未修改 Worker 源码或操作 LaunchAgent；部署前采样无 PID，后采样 PID 为 7620，未声称进程身份不变。

API/Web healthy；指定任务页与 API health 均 HTTP 200。实际交付脚本已包含开始操作及折叠版本详情，任务输入意图区段无 `framework_entrypoints`。初次静态资源检查范围过宽，命中复测/尝试历史字段；收窄到本次目标区段后只读检查通过，无应用代码变更或重复构建。

证据：`~/.local/share/hypertest-mac/cloud-start-20261103/deployment.json`、API/Web 构建日志、`task-before.json` 与 `task-after.json`。本机 README 与 CURRENT_DEPLOYMENT 已更新。

## 用户任务与验收边界

指定任务 `01a1a0e9-8db8-7be9-8a7c-43c42518a6b6` 在部署前后均为 `DRAFT v2 / NOT_RUN`，没有 Attempt；原解析仍为 `RECOVERY_REQUIRED`，`start_requested=false`。升级不自动恢复或启动该任务。

浏览器控制返回 host unavailable / `cgWindowNotFound`，未实际点击页面；真实业务测试和 USER_OWNED 功能验收未执行。上述自动回归、构建与健康检查不代表 TRON 业务测试完成或通过。
