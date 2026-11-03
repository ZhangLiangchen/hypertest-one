# Local 任务状态独立管理：实现与验证（2026-11-03）

本轮按用户最新要求将任务进度与汇总发布解耦。顶部“修改状态”可直接保存现有状态枚举和可选原因，不填写或发布汇总。测试结果只读显示；COMPLETED 不代表 PASS，不完成子任务或修改用例。原“发布汇总”独立保留。

## 合同与实现

[ADR-037](architecture/ADR-037_LOCAL_TASK_STATUS_MANAGEMENT.md)、领域 §56.4、TMP §51.1 和技术架构 §50 同步定义 `UPDATE_STATUS`。新增 `POST /api/v1/local-archive/tasks/{id}/status`，仅接受 project_id、idempotency_key、expected_task_version、status、reason（可选，最多16000字符）。复用 Operator 权限、Origin 边界、管理版本、原 key 账本与 Audit/Outbox。

状态操作只改变 Task.status、version、updated_at，并追加固定管理回执及审计。回执保存 actor_ref、created_at、from_status、to_status、reason。旧历史不回填；reported_result、目标、原报告/范围/限制、用例、子任务、Publication、归档版本及内容均不变。同 key 同输入返回原固定结果；异输入或旧版本拒绝。网络失答先查询原 key，不重复提交。

Web 确认回执及账本后立即回写页面缓存，再刷新当前读模型；拒绝或未知不显示成功。未决时表单和保存按钮禁用，刷新仍恢复未决 key。发布表单回显最近汇总正文和原引用，引用已不在当前版本范围时明确提示，不能静默删除。明确重新打开管理操作时加载当前版本，适用于冲突后的“刷新→重新打开”。

迁移 `0045_local_archive_status` 只扩展 LocalArchiveOperation 的操作类型 CHECK；无数据清理。已有 UPDATE_STATUS 历史时拒绝不兼容 downgrade。

## 修改文件

- 前端：`web/app/tasks/archive-task-detail.tsx`、`web/lib/archive.ts`、`web/lib/archive-operation.ts`、`web/lib/archive-server.ts`。
- 后端：`src/hypertest/api/archive_routes.py`、`archive_schemas.py`、`src/hypertest/application/local_archive.py`、`src/hypertest/domain/local_archive.py`。
- 迁移：`alembic/versions/0045_local_archive_status.py`。
- 回归：`tests/test_local_archive.py`、`web/tests/archive-status.test.cjs`、`archive-operation.test.cjs`、`archive-boundary.test.cjs`。
- 规范：ADR-037、ADR-027 增补、领域模型、TMP、技术架构及文档索引。

## 自动回归与部署

专用临时 PostgreSQL 完整迁移至0045，相关后端4项通过；临时数据库已移除，没有向业务库运行自动回归 fixtures。相关前端35个唯一测试通过（包含后续新增的未决按钮禁用断言），typecheck、Ruff、差异检查和界面检测通过。未运行全量平台回归或手动CI，不将其记为通过。

实现提交 `872d3ee4297dd3b85143ebf7acfbc0e8ebc80748`；失答实测发现按钮显式 disabled=false 覆盖 Form 的禁用态，账本仍阻止重复 POST，已由 `a7e344c442241cb93a1997c5b1e395acbae6a5e7` 修复。`33f0d6bb83e8b190f7905e26da1e9e993d7f6917` 恢复重新打开时载入当前值。已合并同时进行的 Memory 更新，避免回退现场功能；Memory 本身的验证不归本轮。

最终部署：

- Web Git `33f0d6bb83e8b190f7905e26da1e9e993d7f6917`；镜像 `sha256:79203f7fd9c8fbb4a31023d53a65bfec1f8bad1c651658d37eda9ae1784208eb`，构建及类型检查通过，Web healthy、WireGuard首页和API health均HTTP200。
- API Git `a405ec55ba35e596a84a3e602ce8d79c716b0a5f`；镜像 `sha256:80bb676af96b6d5791de2fb242d86046afc46b73e01e574dc69f2db9e5501c88`。其 archive 源码与本轮872d3ee一致，包含并行 Memory 更新。
- Schema `0045_local_archive_status`。初次更新API/Web并迁移，后续修复只更新Web；BFF、数据库容器、WireGuard/TLS/授权配置及宿主Worker保持。
- 构建及健康检查记录位于 `~/.local/share/hypertest-mac/local-status-20261103/`；运行模块覆盖固定提交源码，API继承原依赖层及wheel RECORD，未声称重新安装完整wheel。

## 用户授权的专用任务实际验证

项目 `01a1808b-e73f-7eeb-a0f9-253d3576c7c6`（Synthetic local deployment acceptance）。以下均为显式标注的合成验证任务，不执行外部 SUT，不代表真实业务测试结论。只对本轮新建的三个任务及一个子任务写入；未修改用户指定的 MR !1157 已完成任务或归档产物。

| 样本 | Task ID | 独立状态变更及持久化 | 汇总/归档 |
| --- | --- | --- | --- |
| FAIL | `01a1a0ab-2a98-793e-8867-1da2ea64383d` | IN_PROGRESS→COMPLETED，结果保持FAIL；v3→v4，刷新读回一致 | 状态变更前后原Publication和根v2完整快照逐字段相等；NOT_RUN用例及DRAFT/NOT_RUN子任务不变 |
| BLOCKED | `01a1a0ab-2adb-7af2-a36f-65ee6b152e96` | 竞争请求v2→v3，旧表单409；随后状态请求v3→v4已接受但响应丢失，原key恢复COMPLETED/BLOCKED | 原汇总、根v1、历史前缀不变；恢复零POST、一次GET |
| NOT_RUN | `01a1a0ab-2b0f-7d1f-b8fd-b61e31e69e7f` | DRAFT→COMPLETED，结果保持NOT_RUN，v1→v2；刷新后原key恢复成功 | 全过程Publication数量0，根v1不变；一次POST、一次原keyGET，没有重复历史 |

FAIL样本的范围与限制报告、一个NOT_RUN用例通过 `hypertest-archive` Skill 和CLI 0.1.2、现有 `cli-validation-20261101` profile 明确归档；receipt为ARCHIVED、accepted_version=2、readback_complete=true，Submission `01a1a0ab-b6b6-7d34-a35d-a18541c637a2`。原文明确未执行外部SUT，合成FAIL不能解释为真实失败。

真实HTTP拒绝验证：旧版本409、同key不同原因409、缺Origin403、非法状态/额外reported_result字段422、无Operator凭据401；前后任务与历史完全相等。已接受原key的相同POST返回原回执，不重复记录。

浏览器使用用户明确批准的Playwright专用Chrome，1600×1000 PC宽屏。Codex内置浏览器已打开，但其自动化host不可用；未假称通过内置浏览器自动验证。实际检查顶部入口、当前状态/结果回显、直接保存、即时更新、刷新持久化、版本冲突保留草稿且无成功提示。用 `route.fetch()` 让请求真正被服务器接受，再丢弃响应模拟失答；NOT_RUN样本确认禁用保存按钮、刷新后仍锁定、只查询原key恢复。原key `26e0a562-8839-4268-af25-a55327c57edc`，一次POST、一次GET、管理历史仅追加一次。BLOCKED样本原key `148f2fac-ee23-4683-b88d-fad40acf8e27` 也只通过GET恢复。最终Web版本实测“刷新→重新打开”恢复当前COMPLETED值并清除未保存的原因草稿，该检查零写入。

完成状态保留比对后，单独在FAIL样本执行原发布汇总流程：已有正文、FAIL和原产物引用正确回显，显式发布成功，管理v4→v5并新增第二条Publication，第一条汇总及归档v2完整保留。这个新增汇总属于单独的发布回归，不是状态保存的副作用。

## 截图与原始记录

截图位于 `output/playwright/local-status-20261103/`：

- `before-overview.png`、`before-publication.png`：修改前顶部和原发布流程。
- `after-overview-final.png`、`after-status-form.png`、`after-status-form-final.png`：明确状态入口、独立表单、首次回显与最终当前值及只读报告结果。
- `management-history.png`：原历史完整保留，新增状态操作显示操作者、时间、前后状态及原因。
- `after-refresh.png`：保存后刷新，COMPLETED/FAIL、根v2。
- `conflict.png`：实际409、草稿保留、无成功提示。
- `unknown-disabled.png`、`not-run-reconciled.png`：未决禁用及刷新后原key恢复。
- `publication-prefilled.png`：原汇总原文/范围/限制与引用回显。

API基线/读回、CLI回执及拒绝结果保存在本地 `output/local-status-20261103/`；截图、浏览器脚本和故障注入记录保存在上述Playwright目录。记录保留了发现问题的初次失答尝试与修复后通过的尝试，不将初次失败重标为通过。
