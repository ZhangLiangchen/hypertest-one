# 辅助任务活动与等待诊断验收

本轮对照白皮书 §22、TMP §21、技术架构 §33 和领域模型 §23.3，补齐长模型任务的可观察性。活动只是辅助面板，Canonical 链与 Runner / Gate 信任边界保持。

## 实现边界

- Adapter 将真实 Provider 事件投影成固定类型；不保存或返回推理、命令、消息、路径、PRD、回答或认证内容。
- 独立 Operational 表 `mission_activity_events`，迁移 `0010_mission_activity`；固定键计数器和单写入器、约 2 秒合并、每 Attempt 最近 200 条，支持只读分页。
- Provider 信号、平台本地控制事件和 Worker 心跳分开。人工等待和恢复保持原 Attempt，当前领取的信号不借用旧领取时间。
- 新短事务校验租约、数据库时钟、Job / Attempt 归属；取消 / 失效后不写迟到遥测，不持锁跨 Provider I/O。活动繁忙或故障不改变正式 Result。
- Web 中英文活动视图保留已加载内容，区分等待回答、模型信号、可信 Runner、终态和读取失败；不伪造百分比、ETA 或停滞结论，不自动重放。

## 自动化与迁移

2026-10-18 本地冻结工作树已通过：

| 检查 | 实际结果 |
|---|---|
| Ruff / pytest | **384 passed / 3 existing warnings / 40.97s**；96 后端输入 manifest `0780cd9464991cbccb622b06d1d31f1b66b1cdf97c22263a894ce6c1f988d426` |
| Web | 独立 `npm ci`、**41 tests**、typecheck、production build、audit **0 vulnerabilities**；39 输入 manifest `3276fe55d8488354ffeb333f3a4109150feaf453164267a8bae68efc8e1d4284` |
| PostgreSQL 迁移 | 测试库 head0010；独立配对备份恢复 0009→0010 **13 checks**；本地应用升级 **9 checks**，32 旧表 / 1,144 行和 128 旧产物保持 |
| 并发与生命周期回归 | 真实 PG 验证 ownership / claim / expiry fence、锁忙与超时、取消、写入器清理、有界合并/裁切、分页及只读快照；模拟 Provider 仅用于契约回归 |
| Web 交互回归 | 当前领取信号、Worker 心跳、等待/终态提示、读失败保留、陈旧分页响应与计数合并；中英桌面及 390px 移动端实看，修复等待提示按钮挤压正文 |

最初完整检查中的四项失败来自旧测试仍要求原始 Provider 类型/错误诊断；已改为断言安全投影、固定错误码和原始解析恢复能力，原失败日志保留。首次隔离恢复的收集器在迁移后因 PostgreSQL char→JSON 转换失败，原记录保留；修复收集器后在新的隔离数据库重做得到 13 项通过，不将收集器故障描述成迁移故障。

[后端检查](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-backend-full-v2-2026-10-18.log) · [Web 检查](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-web-checks-2026-10-18.md) · [隔离迁移](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-migration-rehearsal-v2-2026-10-18.json) · [本地升级](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-local-migration-2026-10-18.json)

## 真实 Web / Codex / Docker

本轮在 Web 创建独立 Project，粘贴 885-byte PRD，固定 `pypa/sampleproject` commit `621e4974ca25ce531773def586ba3ed8e736b3fc` 后提交完整周期。此轮验证粘贴输入与活动功能，不冒称再次执行原生 PRD 文件导入；文件导入实测保留原验收身份。实际配置使用官方 Codex CLI **0.163.0**，无模拟模型结果注入。

| 验收项 | 实际结果 |
|---|---|
| 新 Run / Job | Run `01a14e54-62c0-73e5-b79d-baa8f6b7f5bd`；Job `01a14e54-b588-7bf1-b428-24c0504e447f`，claim2 后 SUCCEEDED |
| 运行中可见性 | 在任务结束前实读 Provider 及控制面事件；当前 Attempt、最近 Provider 时间与独立 Worker 心跳均可见 |
| 等待与重启 | 真实模型就负整数范围提问；WAITING_INPUT 期间 API / Worker 重启，6 条活动及正式状态原样保持；人工等待超过 5 分钟无模型静默误报 |
| Web 回答与恢复 | Web 提交回答；原 Mission / Attempt No.1 / AgentSession / native thread 保持。新 claim 首个快照为 PLATFORM_WORK 且 Provider 时间为空，随后恢复事件和当前 claim 新信号出现，不借用旧信号 |
| Canonical / Runner | **2 Requirement / 5 Risk / 8 Case / 1 Implementation / 1 OFFICIAL Docker Execution / 4 RUNNER VERIFIED Evidence / 0 Finding / 1 FINAL Verdict**；JUnit **8 passed / 0 failures / 0 errors / 0 skipped** |
| 最终判定与追溯 | FINAL `RELEASE_READY`，Verdict `01a14e5f-7775-7574-b8b8-fbccf5e88787`；44 条完整关系连接、56 Audit / 56 Outbox 配对；Web 可达正式判定与 JUnit 原文 |
| 活动与隔离 | **42 安全活动**（claim1=6、claim2=36），全页读取无重无漏、全部归属/类型检查通过；Web 实点“读取更早活动”后显示全部42条、无剩余游标，并从活动面板跳转正式判定；终态无活跃回合或静默时钟；活动不进入 Canonical snapshot，读取前后 Gate hash / manifest / 原 Verdict 不变 |
| 历史保全 | 排除可变 Worker 心跳、版本表及新活动表，**31 旧业务表 / 1,132 行逐字段多重集原样保留**；128 旧 Artifact 逐文件重新读取 SHA-256 全通过 |

正式链、终态活动、恢复的独立只读收集器分别 **15 / 15 / 10 checks 全通过**。本次真实活动未触发同窗口合并或 200 条裁切；该压力边界来自 PostgreSQL 回归，不冒称模型真实触发。平台时间与计数不是原生 Provider 时间、模型推理、完整日志或唯一工具次数。

运行中的 API / Worker 对应  src + alembic 输入 manifest `d5e49ac01ed89d6fd892e1e7d910824650d62d44d51424e60aabdbf37a28d7bf`；完整测试另含测试/配置输入。最终 Git SHA 与 PR 在[本轮交付记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-delivery-2026-10-18.md)登记，不把未来提交冒充进程启动时身份。旧问答真实链仍保留 `8e01ac5`。

[正式链原始记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-local-final-2026-10-18.json) · [活动与保全](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-observability-acceptance-2026-10-18.md) · [暂停重启](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-paused-restart-2026-10-18.json) · [中文运行中截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-live-resumed-zh-2026-10-18.png) · [最终判定](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-final-verdict-2026-10-18.png) · [JUnit](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-final-junit-2026-10-18.png)

## 部署与未完成项

生产服务器仍为已合并部署的 `a48bc96` / schema0009；本轮未执行服务器升级。服务器数据、45.76.149.233/32 双层白名单、SSH 隧道及 OAuth 未触碰。本地 API / Worker 留在 head0010，可操作新 Run；升级前数据库与 Artifact 的[配对备份](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/mission-activity-local-backup-2026-10-18.json)保留。

受控依赖 / 服务型 API 环境和多人身份权限仍是单独产品能力，不据本轮活动面板宣称第一阶段所有场景完成。
