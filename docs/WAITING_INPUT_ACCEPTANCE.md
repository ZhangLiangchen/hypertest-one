# WAITING_INPUT Web 闭环验收（2026-10-18）

本轮补齐白皮书的人机协作与可操作 Web 缺口：真实 Agent 提问 → 平台持久等待 → Web 回答 → 原任务、原会话恢复 → 正式 Runner → 可信证据 → 平台判定。领域 [§23.2](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#232-持久人工输入与原任务恢复)、[TMP §29](protocol/TEST_MISSION_PROTOCOL.md#29-human-input) 和技术架构的 Gateway / Harness 边界为权威；问题和回答是运行交互，不升级为 Canonical Testing State。

## 已完成的实现与检查

| 项目 | 结果 |
|---|---|
| 持久暂停 | Job / Mission / AgentSession 为 WAITING_INPUT；同一 Run 保留活跃预约，但清除 lease / Worker，占用不随用户等待延长 |
| 回答与恢复 | 保存一次原文回答并将同 Job 入队；新 lease 恢复同 Mission / Attempt / AgentSession / 原生 Codex thread，不创建替代会话冒充恢复 |
| 重复及并发 | row_version、幂等 key、数据库行锁与唯一约束；相同回答重发可查询既有结果，异文或取消后的新回答拒绝 |
| 异常和取消 | 丢失原会话 / 副本明确失败；已持久 checkpoint 保留；暂停提交前后检查租约；等待及答复排队期间取消关闭所属交互和执行历史 |
| Web | 运行概览、任务入口、问题与回答、建议选项、自由文本、同页草稿、双语、原 Job 进度与可信证据入口 |
| 迁移 | 0009_mission_inputs；旧状态列从 varchar(7) 扩至 32，增加交互表与状态 / 所有权 / 历史保护，不回填或重写旧记录 |
| 必需检查 | Ruff、alembic upgrade head、**345 pytest passed / 3 既有 warnings**；独立 npm ci、**31 Web tests**、typecheck、production build、audit 0 |
| 备份恢复 | 0008 备份恢复到新独立库再升 0009：**31 历史业务表 / 951 行全字段逻辑哈希相同**，新交互表为空；14 项核验通过 |

检查针对本轮冻结工作树，后端源清单 SHA 为 `8bd033e86942b466d7d6d73be06a76a764bdf3e6d911272dbb1473a4f0e5d73a`；Web 源清单 SHA 为 `bc087c52f3c3bd197fede3d74f1797239d2f7c418a1cefb2f1f19295a7fc190e`，不是 Git commit。

## 本地真实模型验收

全程使用真实 Codex CLI / 模型与 Docker，没有注入模拟 Agent 结果。由 Web 创建独立 Project、固定 pypa/sampleproject 的完整提交 `621e4974ca25ce531773def586ba3ed8e736b3fc` 并提交 PRD；PRD 中明确保留一个必须向操作人澄清的负整数支持问题。模型提出问题后实际重启 API / Worker，数据库仍保留待答问题；在 Web 中选择、编辑回答，通过键盘提交，随后恢复执行。

| 身份 / 结果 | 实际记录 |
|---|---|
| Run | `01a14b35-6191-70bd-99ea-4886dc3d0ca9` |
| 同一 Job | `01a14b36-62b3-788f-9b0d-21e93b9259d0`，领取 2 次；暂停时 lease / worker 为空，恢复使用新 token |
| 同一提问 Attempt | `01a14b36-7105-7797-9303-2ebff8ee6e91`，Attempt No.1 |
| 同一 AgentSession | `01a14b36-7105-7d64-a324-3dc4e557c5ef` |
| 同一原生 thread | `01a14b36-71f7-75c2-9fe8-bf561c56458b`，等待与恢复前后实读核对 |
| 问答 | `01a14b36-b236-7614-919a-2c3aaf1be28c`，PENDING → ANSWERED → CONSUMED，row_version 1 → 2 → 3 |
| Canonical | 2 Requirement / 5 Risk / 5 Case / 1 Implementation；所有四个 Mission 通过 Verifier |
| Docker | OFFICIAL `01a14b3c-18e6-73a9-8d8d-1f327554aa67`，COMPLETED / PASS / exit 0；5 Case PASS |
| JUnit | 1 个 pytest 函数含多项断言；1 test / 0 failures / 0 errors / 0 skipped，不能把 5 个 Canonical Case 说成 5 个 pytest 实例 |
| Evidence | 4 份 RUNNER / VERIFIED，Web 实际打开 JUnit 原文 |
| Verdict | `01a14b3c-1b8b-7157-a87c-2fd448292c88`，FINAL / TEST_RUN / #1 / RELEASE_READY |

本地运行经历了上述迁移宽度、租约边界及移动端计数布局的实际修复。开始提问、恢复执行和最终静态检查的源清单分别保留，不将开发过程的模型执行冒称为未来 Git SHA。正常路径完成不替代取消、丢失会话、过期租约与重复请求的 PostgreSQL 回归，也不代表第二种 Agent / Runner 已验收。

本地原始记录：[暂停身份](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-local-paused-2026-10-18.json)、[恢复身份](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-local-resumed-2026-10-18.json)、[Web 检查](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-web-checks-2026-10-18.md)、[迁移恢复演练](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-local-migration-rehearsal-2026-10-18.md)、[独立后端复核](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-backend-review-2026-10-18.json)。

## 服务器验收登记

本地真实链已通过；该提交创建时服务器仍为 `1b199f9` / schema0008，正在做配对备份、候选发布及相同问答路径验收，不能以本地结果推定服务器已完成。本轮继续保留现有数据、45.76.149.233/32 双层白名单、后端数据库回环绑定与 SSH 隧道；不改变 OAuth 或扩大公开入口。最终远端 SHA、迁移、旧数据 / Artifact 保全、实际进程目录与远端真实 Run 以部署交付记录为准。
