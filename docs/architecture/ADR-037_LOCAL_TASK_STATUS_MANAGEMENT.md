# ADR-037：Local 任务状态独立管理

**Status:** Accepted  
**Date:** 2026-11-03（Asia/Singapore）  
**Deciders:** 项目负责人于本轮明确要求独立保存任务状态。

## Context

ADR-027 首片把任务整体进度与报告结果都放在 Publication 中修改。用户仅调整进度时也必须发布汇总，入口不直观且容易混淆进度与测试结论。

## Decision

新增 Operator 管理操作 `UPDATE_STATUS` 和 `POST /api/v1/local-archive/tasks/{id}/status`。只接受显式 `status`、可选 `reason`（最多 16000 字符）、`project_id`、`expected_task_version`、`idempotency_key`。沿用既有五种任务状态，不增加执行或归档权限。

仅更新 Task.status、管理 version 与 updated_at；追加 LocalArchiveOperation、Audit/Outbox。回执及管理历史记录 actor_ref、created_at、from_status、to_status、reason；旧记录不补造这些字段。测试结果、目标、子任务、用例、原始报告、已发布汇总、归档版本及内容不变，不生成 Publication。

当前权限核验后按原 key 对账，同 key 同请求返回固定响应且不重复历史，异请求冲突；新请求必须匹配当前任务管理版本。状态合法性由既有枚举约束，未知或失答只查询原 key。COMPLETED 不代表 PASS 或执行通过。同状态的显式管理请求可记录原因并推进一次管理版本，不产生测试事实。

`PUBLISH` 保留原行为：明确发布新的汇总，校验根/子任务归档版本与资产引用，同时保存显式状态和 reported_result。两个入口分别命名为“修改状态”和“发布汇总”。本决定替代 ADR-027 中“任务进度只能经汇总变更”的限制；报告结果仍由显式汇总管理。

## Options Considered

| 方案 | 影响 |
| --- | --- |
| 快捷入口跳转到发布汇总 | 改动小，但仍要求汇总，无法满足独立管理要求。 |
| 独立 UPDATE_STATUS（采用） | 增加一条受限路由与操作类型；复用现有授权、版本和幂等账本。 |

## Consequences

用户可以单独管理进度；汇总记录的是当时发布状态，可能与当前进度不同，历史不回填。迁移仅扩展管理操作 CHECK 枚举，不删除或转换旧记录。实现、部署、回归与实际界面验证分别记入交付记录。
