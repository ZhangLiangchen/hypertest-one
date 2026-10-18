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

服务器已独立完成真实 Web / Codex / Docker 问答闭环，实际执行版本为 `8e01ac5e46b83e8bce950915892f2b74d16c140a`，数据库 `0009_mission_inputs`。之后 PR #6 已合并并部署 main `a48bc96`，部署前后 32 表 / 1,219 行、41 产物引用 / 16 Evidence 完全一致；见[合并部署记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr6-deployment-2026-10-18.md)。不将该同步冒称为重跑模型。原服务器完整后端检查为 **345 passed / 3 既有 warnings**，31 Web tests / typecheck 通过，精确提交的两个 CI 作业通过。8e01 只修正一个既有测试的 heartbeat 行锁竞争：使用真实 FencedAsyncSession 隔离被测 controller，保留 Run / Job 两项 NOWAIT 断言及独立 Worker 测试；生产源码、Web / 配置 / lock 与 e511 相同，复用 e511 fresh npm ci 后成功生成的生产构建，不冒称重新构建。

| 身份 / 结果 | 服务器实际记录 |
|---|---|
| Run | `01a14b53-4988-737e-8316-4b285c92e11c`，COMPLETED |
| 同一 Job | `01a14b53-73af-71b5-915e-a304348141f8`，第 2 次领取后 SUCCEEDED / VERDICT_FINALIZED |
| 同一提问 Attempt | `01a14b53-7b6e-749d-9827-973b24d322c8`，Attempt No.1 |
| 同一 AgentSession | `01a14b53-7b6d-79ea-af92-d889c4d4b307` |
| 同一原生 thread | `01a14b53-7f46-7821-868c-62715aab8a93`，与暂停前记录一致 |
| 问答 | `01a14b53-961c-7734-b773-25cfaf835048`；真实提问、WAIT 期间 API / Worker 重启、Web 键盘提交、CONSUMED / version 3 |
| Canonical / Runner | 2 Requirement / 5 Risk / 5 Case / 1 Implementation；4 Mission 完成；1 OFFICIAL Docker PASS / 4 VERIFIED Runner Evidence / 0 Finding |
| JUnit | 1 pytest 函数 / 0 failures / 0 errors / 0 skipped；该函数的多项断言覆盖 5 个 Canonical Case |
| Verdict | `01a14b58-4001-7423-9c94-edfed68a0b95`，FINAL / TEST_RUN / #1 / RELEASE_READY |
| 独立终态采集 | 15 项检查全通过，44 条完整关系连接，53 Audit / 53 Outbox 按实体与动作配对；输入、spec、执行、证据字节和判定 manifest 均校验 |

部署前旧 30 张业务表的 **1,029 行**逐字段多重集比较全部保留，34 个原产物引用 / 27 个独立 blob 的 SHA / size 匹配。最终配对备份 `/var/backups/hypertest/20261017T193526Z` 已恢复到独立库和目录：schema0009、32 张表完整逻辑哈希、41 个产物引用 / 32 个独立 blob、16 Evidence、1 个已消费问题均通过。正式库未做恢复或降级。已有输入历史，不可直接回退到旧 schema / 不支持 WAIT 状态的应用。

API / Worker / Web 实际目录均为 8e01 release；单 Worker 可用、活动任务为 0，公网白名单入口与 SSH 隧道健康均 200。45.76.149.233/32 的 UFW + nginx 双层限制、API / Web 后端 / PostgreSQL 回环绑定及 OAuth 保持。见[服务器最终报告](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-server-acceptance-2026-10-18.md)和[只读终态原始证据](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-server-final-2026-10-18.json)。

## 仍需继续的产品能力

本轮完成白皮书的人机协作 Web 闭环，不将单函数 stdlib / pytest 的成功泛化为任意 API / SIT 项目。受控依赖与服务环境、长时模型活动和停滞诊断仍应优先完善；当前仍为单可信操作人，白名单不替代多人身份与权限。完整领域 MCP / 第二 Harness 是后续能力，历史失败诊断保留其原始版本和 Run，本轮没有重跑该失败链。
