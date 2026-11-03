# 宿主原生完成后的管理闭环交付（2026-11-03）

本轮修复 ADR-032 宿主薄 Worker 正常完成后无法复测、删除的问题。原生完成只能观察直接 SDK 进程退出；其他进程及外部范围保持 UNKNOWN/NOT_OBSERVED，不能因此推定存在已知未决操作。合同见 [ADR-035](architecture/ADR-035_NATIVE_COMPLETION_MANAGEMENT.md)。

## 行为与边界

- 服务端核对同 Task/Attempt 的已接受原生完成回执、最终报告、完成清单及退出观察；旧 writer 已 fence，且没有已知未决 key、SSH/HTTPS/受控动作、容器或委派时，允许重新确认范围和授权后创建独立 Attempt，或按墓碑协议移出列表。
- 完成但 reported FAIL 的任务也提供新执行尝试入口；完成不等于测试通过。旧 Attempt、原件、结果、预算及 UNKNOWN/NOT_OBSERVED/false 原值不变，不把删除或复测当作停止证明。
- Web 使用版本匹配的 live `management` 准入；缺失、读取失败、版本不一致或服务端阻断时不提交。POST 仍在事务中重新检查，保留原 key、预期版本和独立执行快照。
- Legacy false、无接受回执的伪 marker、未 fence、已知未决操作仍拒绝。恢复操作仍仅处理 RECOVERY_REQUIRED，不通过改写已完成终态来解锁。
- 保持本机薄 Worker → 官方 SDK → Harness 架构；未更换 SDK/profile、访问边界或 Worker 领取逻辑，没有建立任务容器或平台 Agent Loop。

## 回归

- 专用临时 PostgreSQL 中，后端直接相关回归 **17 项通过**，包含 native handoff、NOT_RUN/FAIL 完成后的复测与删除、原报告和固定版本保全，以及 pending key、伪 marker、fence、旧 HELD/false、已知外部动作与容器未收尾拒绝。
- 修复原生集成测试的 `cloud_context` 加载和 FakeAdapter 缺少 `interaction_enabled` 参数的问题，恢复真实 API/Worker 与模拟 SDK 的报告闭环回归。
- 相关 Web **33 项通过**；TypeScript 检查、Ruff、差异检查通过。界面沿用现有布局与控件，设计规则扫描无发现。
- 测试库明确独立于业务库，迁移到 0043 后仅写合成 fixture。测试结束已清理本轮 tmpfs PostgreSQL 容器；复用现有 checkout、依赖和构建缓存。

以上是自动回归，无真实模型/SUT 执行，未替用户下发新业务尝试或删除既有业务任务。

## 部署

代码已推送至 `codex/native-completion-lifecycle`，部署源码为完整 Git `df42ef18e89670e0555baa60b24a717570d8d01f`。

| 服务 | 镜像 | 镜像 ID |
| --- | --- | --- |
| API | `hypertest-mac-api:df42ef1` | `sha256:14458ac65bdc2420283c4fd9c20b4e9af41ac45138f17bb2160583a72bee3841` |
| WireGuard Web | `hypertest-mac-web:df42ef1` | `sha256:da40872cbb8022e348fbdb50639b47f1e5c5312604e14e1a20c2d962181f9537` |

本轮先停止受影响服务，再用已推送提交构建、启动。API 复用 `4e6203b` 的依赖层，覆盖该固定提交应用源码；原 wheel RECORD 仍为继承记录。运行模块 SHA-256 与提交源码一致。Web 使用现有 Dockerfile 和依赖缓存构建；镜像 revision 均为上述完整 SHA。

Compose 在现有 overlay 链末尾追加 `~/.local/share/hypertest-mac/native-completion-df42ef1/compose.json`。无需迁移，实际 schema 仍为 `0043_deleted_cloud_recovery`。API/Web healthy；API health、任务页面及 BFF summary 均 HTTP 200。实际 summary 已返回 `management`：本轮先前取消且无 Attempt 的验证任务可删除、不可复测；历史已完成任务可复测/删除，其 version 15 和 reported PASS 保持。

数据库卷、WireGuard、BFF、TLS、PowerContext 及宿主凭据未更改。镜像构建和冒烟记录位于本机 `~/.local/share/hypertest-mac/native-completion-df42ef1/`；回归记录位于 `acceptance-cloud-mainflow-20261103/native-lifecycle-fix-regression.txt`。

## 未完成的独立事项

本机薄 Worker 当前仍无 PID，原 `claim-pending.json` 的 SENT/UNKNOWN 领取记录保持，未删除、伪造确认或自动重发。该领取恢复问题与本轮完成后的管理修复分开处理；不能因 API/Web 健康宣称云端执行主流程恢复。

真实 SDK/模型 → 项目框架 → 新报告回传及真实浏览器功能验收未执行。已有浏览器连接不可用，本轮仅完成相关组件回归和页面 HTTP 检查。正常完成后的复测/删除实测使用专用合成数据库，不代表真实业务执行验收。
