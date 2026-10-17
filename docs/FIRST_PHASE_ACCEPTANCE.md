# HyperTest One 第一阶段验收

## 当前增量：等待输入、回答与原任务恢复

新增迁移 `0009_mission_inputs`，本地与 Debian 服务器均已通过真实 Web 提问 → 持久等待 → API / Worker 重启 → 回答 → Codex 原会话恢复 → 正式 Docker → Evidence → FINAL RELEASE_READY；完整必需检查 **345 后端 / 31 Web tests** 通过。服务器运行候选 `8e01ac5`，PR #6 未合并；旧 1,029 行历史 / 34 个产物引用保留，最终配对备份和隔离恢复已通过，45.76.149.233/32 白名单及 SSH 隧道保持。见[本轮逐项验收](WAITING_INPUT_ACCEPTANCE.md)。下方 PRD / 旧版本的数量、运行身份及当时缺口保留为历史，以本节为当前问答能力状态；不以旧失败链路代替本轮实测，也不据此宣称任意 API / SIT、第二 Harness 或多人权限已完成。

## 本轮两阶段交付：已部署73d与后续范围修复

阶段1执行版本为 `73dff989b87fa7349d9b36bd8416ece948a82212`，已部署并激活VPN公网白名单，SSH备选保留。[阶段1部署记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr4-deployment-2026-10-17.md)与[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)保存实际CI/目录/协议与数据保全身份。d20/302、298模型执行manifest及更早Run继续作为历史证据，不改写为本轮范围修复后的模型执行。

| 阶段 | 已证实结果 | 边界 / 后续登记 |
|---|---|---|
| 1：PRD导入 | 原生Chrome/macOS选择器 **9实际fixtures/15UIchecks全通过**；无效文件保留正文/原文件名；合法UTF-8/BOM/CRLF、编辑/重开、取消/重选、中英切换与Review通过 | [浏览器矩阵](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-browser-matrix-2026-10-17.json)；本地没有新建Run或调用模型 |
| 1：HTTP/自动化 | CSPRNG UUID三入口在公网实际创建Project/Run/Job；**20 Node回归（14decode+6UUID）**及fresh npmci/typecheck/build/audit0通过 | 阶段1的86后端输入等d20/302；历史114输入manifest为`0d58f4c0990f87d50b49c15b9148c72bdbe3957e5093d5f91a8626e6476d2c07`，不代表后续scope补丁 |
| 1：白名单 | 公网精确155.138.206.106:8080，UFW /32+nginx peer45.76.149.233双层ACL已激活；允许HTTP/13静态资源、Host/Origin、非允许peer及伪造头检查通过；SSH隧道与后端PG回环保留 | 用户手机非VPN访问失败及同窗UFW BLOCK属于关联证据，不冒称精确手机IP归属；实际完整边界见阶段1部署记录 |
| 1：真实模型失败 | Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5`接受 **10Req/6Risk/8Case**，其中2Case错误要求被测pypa仓库之外的Runner guard功能 | 实现Agent返回PARTIAL/6提案，Verifier以`RESULT_NOT_COMPLETED`拒绝；Job FAILED/MISSION_REJECTED、Run BLOCKED，**6条未接受实现Proposal保留，0Canonical Implementation/Execution/Evidence/Verdict** |
| 2：范围修复 | Runtime从trusted SourceSnapshot提供provider-independent `context.testing_scope`，四阶段明确产品行为/产品约束与测试实施指令；Codex仅遵循该范围 | 领域[§12](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement)、TMP[§9](protocol/TEST_MISSION_PROTOCOL.md#9-mission-context)为权威；不删除合法产品CONSTRAINT，不禁止显式真实Runner-SUT，不放宽PARTIAL或Gate |
| 2：新源码检查 | 后端runtime/codex与回归已改变，不再沿用“86后端未变化”结论；无新迁移，head仍0008 | 新冻结工作树 **303 passed / 3 warnings / 48.70s**、Ruff、独立测试库0008及fresh Web20/typecheck/build/audit0全部通过；后续提交SHA/CI/部署与真实模型语义验收以最新交付登记为准 |
| 2：同输入真实复验 | 在新的独立Project以同 **605 UTF-8 bytes** PRD、同源码/配置/Policy内容重做真实模型/Docker链 | PRD SHA `6fcb51e70880f59ee084bc7fecdb4f6d7f0f8c8a711bee3e8d32e82e32a51ce9`；最终Project/Run及结果以最新登记为准，不预写成功 |

首轮[失败完整记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-first-attempt-2026-10-17.json)保持原Canonical、Proposal、Attempt和Mission历史。Requirement/Risk/Case按SourceSnapshot共享，同Project同输入新Run会继承原错误Case；此次新Project是有意隔离复验，不是修改旧Snapshot/PRD、退役Case、接受PARTIAL或绕开Gate。`RETRYING`界面显示“等待重试 / Awaiting retry”，不表示Worker正在执行。

scope修复冻结输入manifest为`4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90`，源于73d之上未提交工作树，并非73d本身；4份foundation与CI Hash另有记录。完整结果见[冻结检查报告](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-checks-2026-10-17.md)。后续精确运行版本、部署及同输入真实链结果统一见[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)。以下记录保持既有执行版本，不据历史成功推断这次范围修复已通过。

## 上一轮实现与历史验收记录（298 / 302）

核对日期：2026-10-17（Asia/Singapore）。上一轮开发与部署切换前的产品基线为 main `79d329299d038ff9e6a3fe1659fb27bf589062c1`，包含双语 Web、提交幂等性修复；该基线后端 **223 passed / 3 warnings**，合并提交 [CI 39033073576](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39033073576) 的 test / web 均 SUCCESS。服务器同步后，64 个读 API 资源路径、8 份 Evidence 与 4 份输入 Artifact 的身份和原始字节保全；Worker 心跳按运行数据单独核对。

第一阶段 Codex / pytest / Docker 的 stdlib 后端支持链已由本地及 Debian 13 服务器的四条真实模型链路验收。其执行代码仍登记为 `89d15aeb73230d313809296de2343b8eddc6d6b6`（本地分析前段为 `5b1b7ce6920624e2724172431c7879f9f2fa10fd`），下方保留原 Run、数量、hash、拒绝/重试和版本记录；旧执行身份不能改写为当前提交。

上一轮在 79d 基线上继续完善 Web 自主入口、运行输入传输、输入安全和失败恢复信息。冻结产品源码已通过 **302 passed / 3 warnings（32.87s）**、Ruff、独立测试库 Alembic `0008_job_ownership`、23 个 Web 输入 Hash 不变，复用已通过的 typecheck / production build 与 npm audit 0。检查包含 79d 之上的未提交工作树，不能以 HEAD 79d 单独代表上一轮已测源码；精确源文件清单及 Hash 见下方报告。**新入口已通过本地完整真实模型 / Docker 链路，最终提交与服务器同步记录见上一轮交付报告**。模型链使用 298 项检查冻结源码；随后仅追加 URL 解析拒绝错误脱敏及四项回归，最终 302 项通过。两次源码身份分开登记，不改写执行历史。

## 上一轮 302 项检查与真实链路逐项矩阵

| 第一阶段规范项 | 79d 基线 / 既有真实证据 | 上一轮改进与未完成项 |
|---|---|---|
| 固定 PRD、repo commit、配置与 Policy | 不可变 SourceSnapshot / PolicySnapshot，bootstrap 同输入复用、不同输入冲突；四条真实链保留原文/hash | 已物化配置缺失或损坏时在创建 Agent Session 前阻断；hash-only legacy 保持可选上下文；origin 的 HTTP(S) userinfo / URL password 在创建入口拒绝，旧 Snapshot 也在 Runtime 注入前阻断。相关回归已纳入最终 302 项检查 |
| PRD → Requirement | Typed Proposal、Verifier 原子接受；本地及服务器真实模型 Requirement 已归档 | 新 Web Run 真实接受 7 个 Requirement，后续 6 Risk / 9 Case / 9 Implementation 经平台提交，完整链已通过 |
| Requirement → Risk | 显式 RequirementRisk、来源和去重；四条真实链及 SQL 追溯已验收 | 不声明风险语义完备 |
| Risk → Case / 设计覆盖 | 固定 Policy 与确定性 required dimensions、RiskTestCase；模型补齐缺口 | 维度覆盖仍不等于正式执行通过或语义完整 |
| Case → Implementation | 真实 Codex 生成 Python/pytest 源码、内容 hash 与关系；不覆盖应用 tracked 源码 | 其他语言和任意第三方依赖不能据此泛化 |
| OFFICIAL Execution | 可信 Docker Runner 独立执行；固定 source/spec/environment/image 身份，正式/探索结果分离 | 新入口实际 OFFICIAL Docker PASS，9 Case 全通过；JUnit 34 tests、0 failures/errors/skipped |
| Execution → Evidence | metadata/JUnit/stdout/stderr、RUNNER/VERIFIED、读时与 Gate 校验 SHA-256；原始 Artifact 已保全 | 签名、对象存储与其他 Collector 不作为本阶段前提 |
| 失败 → Diagnosis → Finding | 实际 FAIL 后真实模型诊断，绑定可信 Evidence；本地受控分诊/确认，服务器 Finding 保留 NEW | 自动修复/复测不是第一阶段必需终点；上一轮未重复消耗模型额度运行失败链，保留并复核既有本地/服务器真实失败证据 |
| Report / Verdict | Gate 基于 Policy、Canonical State、最新正式事实；append-only FINAL、state hash 与 manifest，历史保留 | 缺少事实仍应 BLOCKED；新完整周期 FINAL RELEASE_READY，4 份可信 Evidence 原始 hash/size 复核通过 |
| 领域 §42 硬约束 | UUID PK、FK、Unique Fingerprint、row_version、Mission/Execution 幂等、Evidence hash、Proposal separation、Audit/Outbox 已有真实 PostgreSQL 测试和关系证据 | 无新增迁移，head 仍为 0008；上一轮完整 302 项检查已通过，精确源码 manifest 与执行身份分别记录 |
| 可替换 Harness / TMP | 当前五类 Mission 的 Codex 结构化最终结果、隔离会话和 Proposal 边界已真验 | 大输入改走官方 CLI stdin，保持 schema / final-response 文件通道及 read-only sandbox；传输回归不证明模型上下文容量。完整 MCP 域工具、WAITING_INPUT/回答/resume 仍未实现 |
| Planner / 持久 Worker / 自动检出 | 确定性 Planner、有界周期、单 Run 活跃请求、显式恢复；原 PREPARE_WORKSPACE 可单独使用 | 周期先只读检查实际 Runner daemon / 可信镜像或 local 显式启用，失败不启动 Git / Agent；一个 ADVANCE_RUN 可选择 prepare_workspace:true，在同 Job 内准备固定 GitHub checkout 后继续。预检及 Git I/O 不持 Run/Job 行锁，后续重新 fence；不拉取镜像或制造正式事实。新 UI 真验通过；同 Job 自动准备目录并完成真实周期 |
| 失败任务与不可变历史 | 原失败 Job、Attempt、Proposal 保留；租约失效显式中断且不自动重放 | MISSION_REJECTED / MISSION_FAILED 受控停止可在 FAILED Job result 保存已持久步骤、相关 ID 与 workspace；旧 payload 缺省 false 仅在内存规范化，原历史不改写 |
| 可直接操作的双语 Web | 已实测 Project → 中文粘贴 PRD + SHA → Run → 真实 Gate Job；无执行事实时 FINAL/BLOCKED。已有模型结果仅用于只读导航 | 新的自动检出入口真实 Run 完成整链，Risk 阶段取消后显式重试，旧 Job/Attempt 保留；任务 → 判定 → JUnit 与中英 Attempt 摘要已实际查看；当时文件导入受 Chrome 扩展本地文件权限限制，仅审查源码与 chooser；本轮原生 Chrome 修复后的9文件/15检查及独立生产登记见顶部 |
| 服务器与运维交付 | 79d 已部署、单 Worker、SSH 隧道/回环、备份恢复及历史数据保全 | 上一轮提交及切换后的实际就绪、数据保全结果见交付报告；不能沿用 79d 就绪结果声明新提交已上线 |
| 阶段边界 | 单个可信 Operator、Codex、Python/pytest、预制可信 Docker 镜像的后端支持路径 | 企业登录/RBAC/多租户、其他语言/镜像、外部 SIT 网络、完全无人值守发布及长期语义自治均未泛化验收 |

上一轮输入基线证据：[Web 产品验收](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/web-product-acceptance-2026-10-17.md)、[main 同步保全](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/pr2-main-sync-preservation-2026-10-17.md)、[main 服务器部署](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-main-pr2-deployment-2026-10-17.md)。上一轮回归位于 `tests/test_mission_input_transport.py`、`tests/test_runtime_input_integrity.py`、`tests/test_cycle_preparation.py`、`tests/test_cycle_preflight.py`、`tests/test_repository_origins.py`；全部必需检查见[冻结源码检查报告](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-checks-2026-10-17.md)。上一轮真实链见[新 Web 链路原始记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-live-2026-10-17.json)；最终提交及部署身份见[上一轮交付报告](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-delivery-2026-10-17.md)。

## 上一轮冻结检查与新 Web 真实链路进度

最终检查针对 79d 之上的冻结工作树，源输入 manifest SHA-256 为 `6ea1934a8a4a577d6990e38eda11a49c1727b9505b333d416d961b207f68e85f`，不是 Git commit。源清单包含 86 份后端源码/测试/迁移/配置及 23 份 Web 源码/配置/lock 输入；检查前后无产品源码输入变化，文档补录不在该清单内。

| 上一轮检查 | 实际结果 |
|---|---|
| Ruff / diff check | 通过 |
| Alembic upgrade / current | 独立 `hypertest_test`，`0008_job_ownership (head)`；无新增迁移 |
| pytest | **302 passed，3 warnings，32.87s**，无失败/跳过 |
| npm ci | 独立 Web 目录 lockfile 安装通过；最终验证 package / lock Hash 不变后复用该安装 |
| Web typecheck / production build | 通过，Next 15.5.28；4 条页面路由 |
| npm audit | **0 vulnerabilities**，仅表示本次依赖审计结果 |
| Runner preflight 回归 | 实际 fingerprint 代码的受控子进程响应验证 daemon / image / CLI 不可用时 0 Git / 0 Agent / 0 Mission / 0 Execution / 0 Evidence；锁释放、lease 失效、重新 admission、local opt-in 与 Gate-only 独立性均通过。此为回归测试，不是新增真实 Docker 执行 |
| Origin 与请求错误回归 | 27 项覆盖凭据拒绝、真实 ASGI 422 脱敏、拒绝 bootstrap 无新输入产物，以及旧 Snapshot 在 Agent Session / Attempt 前拒绝；不改历史 |

新 Web 真实 Run 为 `01a149ff-2749-7ecc-b5f4-5a02307cb7b0`。在真实 Chrome 创建项目、粘贴中文 PRD、解析 `pypa/sampleproject` 的 main 为 `621e4974ca25ce531773def586ba3ed8e736b3fc`，再通过 Web 提交自动准备源码周期。模型链由实际 Codex CLI 输出、HyperTest Verifier 提交，未注入模拟结果。

| 上一轮真实登记 | 实际结果 |
|---|---|
| 输入与源码 | 不可变 Source `01a149ff-2744-7497-a74e-c8a5a7372b78`；PRD/config/Policy hash 独立复核，managed checkout HEAD/origin 匹配且 git status 干净 |
| Canonical 数量 | 7 Requirement / 6 Risk / 9 Case / 9 Implementation / 1 OFFICIAL Execution / 4 Evidence / 0 Finding / 1 FINAL |
| 原周期与恢复 | 原 Job `01a149ff-fa39-7483-a12a-37cef6c6bdd9` 在 Risk 长时无新事件后由 Web 取消；已接受 7 Requirement 保留；显式 retry Job `01a14a12-7562-785f-8b09-3ceee08f5324` SUCCEEDED / VERDICT_FINALIZED，无自动重放或历史覆盖 |
| 实际 Runner | Execution `01a14a15-64f3-748b-ba1c-b0ed6a918caf`，Docker OFFICIAL / COMPLETED / PASS / exit0；9 Case 全 PASS；JUnit **34 tests / 0 failures / 0 errors / 0 skipped** |
| 可信证据 | metadata/JUnit/stdout/stderr 均 RUNNER / VERIFIED，4 份原字节 hash 与 size 全匹配；source/spec/environment/Policy/manifest 独立复核通过 |
| 判定 | `01a14a15-6817-788c-897f-eb44e2c5d556`，FINAL / #1 / RELEASE_READY；state `18ba3fd92d71190ce0cd197964dc7d6755105ea473c23766d6b4d23a9017e1f0`；manifest `18d15b3ca5250aeb591902208a5be72d4e441de7341190efe54d6cb79baa7953` |
| 实际 Web | 任务步骤 → 正式判定 → JUnit 原文可达；Attempt 摘要、未决字段、平台接受状态与 Agent 自报状态分开展示，中英界面均实看 |
| 执行源码身份 | 298 项检查冻结工作树：`0a34e3356d1b2f37b2731b160730747b5dcfa49e9e549c59ad94c8c7e29f1273`。之后仅 URL 拒绝分支脱敏与四项 API 回归补丁，最终源码另由 302 项检查验证；正常 GitHub 路径不变，不把未来提交冒充已运行进程版本 |

[原始记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-live-2026-10-17.json)、[正式判定截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-verdict-2026-10-17.png)、[JUnit 原文截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-junit-2026-10-17.png)、[Attempt 摘要截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-attempt-2026-10-17.png)。取消原因不构成认证失效或模型输出质量结论；本次未重跑既有失败链，其真实诊断证据继续保留在历史部分。

以下为历史接管与四条真实链路证据，时间、执行提交及数量均保留，不能当作上一轮新增检查结果。

## 验收范围与依据

[白皮书 §25](foundation/HYPERTEST_WHITEPAPER.md#25-mvp-范围)规定第一阶段打通 PRD + Git → Requirement → Risk → Case → Test Code → Execution → Evidence → Report / Verdict，支持一个 Codex Harness、Backend/API 测试、pytest 和 Docker。失败时还必须验证可信 Evidence → DIAGNOSE_FAILURE → Finding → 阻断结论。

领域字段、关系、生命周期及数据库约束以[领域规范](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)为准；Agent 契约以 [TMP](protocol/TEST_MISSION_PROTOCOL.md)为准；服务边界以[技术架构](architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)为准。保留以下边界：

- Agent proposes. HyperTest commits. Agent 会话和供应商事件属于运行数据。
- Runner produces facts. 正式事实由受控 Runner 采集，模型的测试自述不能作为执行证据。
- HyperTest produces decisions. 确定性 Planner、Verifier 与 Gate 分别负责工作选择、Canonical 提交和质量结论。
- PostgreSQL 关系数据、Audit 和事务性 Outbox 保存状态及追溯；快照不可变、重试追加历史、FINAL Verdict 不原地覆盖。

下方历史部分的“自动化通过”表示对应执行提交的 PostgreSQL 测试、静态检查或构建已通过。测试中的 provider fixture 不构成真实模型验收，镜像烟测也不构成完整正式执行验收。

## 历史接管阶段进度（5b1b7ce / 89d15ae）

| 阶段 | 当时结论 | 历史证据 |
|---|---|---|
| A 代码接管与规范核对 | 已完成 | 导入并完整接续 `cc3f4dc` 及前述四个交接提交；已读 HANDOFF、AGENTS、四份奠基文档及运行文档；接管前本地工作树干净 |
| B 本地环境与服务 | 已完成 | Python 3.12、Node 22、PostgreSQL 17、Docker 与可信 Runner 镜像就绪；实际启动 API、独立 Worker、Web；健康、数据库读取和 Worker heartbeat 通过 |
| C 必需检查与修复 | 已完成 | 89d 当时干净数据库 0001→0008、Ruff、**212 项**后端测试、Web 安装/类型检查/构建、npm audit 0；`89d15ae` 后端/Web CI 均 success |
| D 真实模型成功及失败诊断 | 已验收（本地；服务器见 E） | 正确 commit：Docker PASS、FINAL RELEASE_READY；错误 commit：Docker 实际 FAIL、真实诊断 Finding、FINAL RELEASE_BLOCKED；均保留首轮拒绝及显式 retry 历史 |
| E 服务器部署与操作交付 | 已完成 | 首次真实模型验收时 `89d15ae` 实际运行；用户 OAuth 已验证；服务器真实两链、单 Worker、回环/隧道、非空数据配对备份及隔离恢复通过 |
| F 第一阶段判定 | 支持范围内验收通过 | 本地和服务器均以真实 Codex / 模型 / Docker 完成成功与失败诊断；后续路线单独列出，不扩大为其他语言/镜像或语义覆盖证明 |

## 历史真实链路逐项矩阵

| 白皮书目标 / 架构约束 | 当时实现与检查 | 真实验收条件 | 历史验收结论 |
|---|---|---|---|
| PRD + 固定 Git 输入 | `bootstrap.py` 保存 PRD Artifact、不可变 SourceSnapshot/PolicySnapshot；Web 创建向导；快照与幂等测试通过 | 实际输入、快照、commit 一致；刷新不重复创建 | 本地已验收；成功 Run 由 Web 创建；失败 bootstrap 重发返回原 Run；两个应用 checkout 均保持原 commit/干净 tracked 内容 |
| Requirement | `ANALYZE_REQUIREMENTS`、Typed Proposal、Verifier 与来源记录；Canonical loop 测试通过 | 真实模型输出经 Verifier 接受并保留来源 | 本地已验收；成功 7、失败 8 个 Requirement，均由真实 Codex Proposal 接受 |
| Risk | `ANALYZE_RISKS`、`requirement_risks` 显式关系；Planner 测试通过 | Requirement → Risk 可经关系追溯 | 本地已验收；成功 5、失败 6 个 Risk，SQL/关系核对通过 |
| Case 与覆盖 | `DESIGN_TESTS`、`risk_test_cases`、确定性维度评估及固定 Policy hash；覆盖测试通过 | 模型补齐请求维度，平台独立计算覆盖 | 本地已验收；两条链各 9 个 ACTIVE Case，所需维度满足。维度满足不证明语义完整 |
| Test Code | `IMPLEMENT_TESTS`、源码 Artifact/hash、`implementation_test_cases`；生成代码与快照测试通过 | 模型生成 pytest、关联 Case，禁止覆盖应用 tracked 内容 | 本地已验收；两条链各接受 9 个实现；首轮 PARTIAL 拒绝后显式 Attempt 2 接受，源应用保持不变 |
| 正式 Docker Execution | `executions.py`、`DockerRunner`、固定 commit/spec/environment fingerprint | 实际 OFFICIAL Docker 执行、镜像身份及逐 Case 结果 | 本地已验收；两条链各 1 次：成功 9 Case PASS（30 pytest 实例通过）；失败 6 Case FAIL / 3 PASS |
| Evidence | metadata/stdout/stderr/JUnit 独立采集、SHA-256 存储及显式关系 | RUNNER/VERIFIED、实际 artifact 读取及 checksum 复验 | 本地已验收；每条链 4 份 Evidence；metadata/JUnit/输出 hash 与关系核验通过 |
| 失败诊断与 Finding | `DIAGNOSE_FAILURE`、可信 Evidence 引用、受控 Finding 状态机 | 实际 FAIL 后真实模型诊断，Finding 绑定可信证据 | 本地已验收；真实诊断产生 1 个 PRODUCT_DEFECT/MAJOR Finding；随后在真实 Web 以 reason/expected row_version 完成 NEW→TRIAGED→CONFIRMED，未 Resolve |
| Report / Verdict | `canonical-gate/v1`、state hash、Evidence manifest、append-only FINAL | 根据正式事实作出可追溯结论 | 本地已验收；成功 FINAL RELEASE_READY；失败先形成第 1 份 FINAL RELEASE_BLOCKED，Finding 确认后追加第 2 份；同状态重评复用原 Verdict |
| Canonical State 归 HyperTest | Verifier 原子提交 Canonical、links、Proposal acceptance、Audit/Outbox | 实际 Proposal/实体/关系一致，供应商会话不拥有状态 | 本地已验收；失败链初轮 SQL 45 条完整连接行；追加第 2 份 Verdict 后 90 条；拒绝的首轮未写入实现，原历史保留 |
| 确定性 Planner 与可替换 Harness | Planner 按缺口规划，bounded controller 委派既有服务 | 按真实状态继续工作，不接管模型 reasoning | 当前 Codex 支持路径已验收；首轮完成的 Requirement/Risk/Case 在显式 retry 后复用；未声称第二 Harness 已验收 |
| 可操作完整 Web | Project/Run 表单、状态/产物/证据/决策/Tasks；类型检查及生产构建通过 | 浏览器创建/观察真实 Run，工作不依赖聊天会话 | 本地支持路径已验收；成功 Run Web 创建、持续观察/FINAL 截图；失败 Finding 实际 Web triage/confirm、Gate Job 与追加 Verdict，均有证据 |
| 持久任务与可审计恢复 | PostgreSQL Job、Worker、lease fencing、显式 retry、归属 FK | 重发幂等、冲突拒绝、历史可读、不静默重放 | 本地显式 retry/幂等已验收；两条原 FAILED Job 与 REJECTED Attempt 保留；失败链同 key 不同输入及活跃 Run 冲突均 409；租约故障边界另有自动化测试 |
| 服务器可操作交付 | 真实 Debian13 部署、用户 OAuth、完整 Web、单 Worker、正式 Docker 与备份/恢复 | 实际服务器就绪、回环/隧道、用户 OAuth、备份及真模型任务 | 已验收；生产 Web 创建、运行与刷新可直接操作 |

## 历史环境、迁移和检查（89d15ae）

最初真实集成验收在 macOS Darwin 25.5.0 / Apple arm64 验证。宿主 Python 3.12.10，Node.js 22.22.0 / npm 10.9.4，Docker CLI/Engine 29.4.0（OrbStack，linux/arm64 daemon），PostgreSQL 17.11。API/Worker 使用数据库 `hypertest`，后端测试使用单独的 `hypertest_test`；数据库未清空、删除或重建。该次修复无新增领域迁移。

两个新建本地数据库都完整执行：

```text
0001_foundation → 0002_agent_canonical_loop → 0003_risk_planner
→ 0004_test_design → 0005_delivery → 0006_immutable_contracts
→ 0007_durable_jobs → 0008_job_ownership (head)
```

| 实际命令 / 检查 | 89d15ae 时的结果 |
|---|---|
| `.venv/bin/ruff check src tests alembic` | 通过 |
| `.venv/bin/alembic upgrade head` / `.venv/bin/alembic current` | 通过，head 为 `0008_job_ownership` |
| `.venv/bin/pytest -q` | 基础修复 208 passed；真实集成修复后最终 **212 passed，3 warnings，26.41s**；无跳过 |
| `cd web && npm ci` | 新 lockfile 可重装，安装成功 |
| `npm run typecheck` | `next typegen && tsc --noEmit` 通过；无既有 `.next` 的独立源码目录也通过 |
| `npm run build` | Next 15.5.28 生产构建通过 |
| `npm audit` | **0 vulnerabilities**；表示本次依赖审计结果，不表示产品完成公网加固 |
| `bash scripts/dev.sh --check` | 真实迁移和 API/Worker imports 通过 |
| `bash scripts/dev.sh` + HTTP/DB/heartbeat | 实际启动；API health、projects 数据库读取、Web HTTP 200；Worker available 为 true |
| `git diff --check` | 通过 |
| `89d15ae` GitHub Actions | [run 39025576616](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39025576616)：后端与 Web job 均 success |

三条 pytest warning 为两条已有 `TestRunCreate` 导入收集提示，以及一条上游 Starlette/httpx TestClient 弃用提示。

可信镜像 `hypertest-runner:py312` 已由官方 `python:3.12-slim` 和宿主下载的 pytest wheels 构建；镜像内依赖安装使用 `--no-index`。本地镜像身份为 `sha256:0a672dd19ac3cd2d19402ef38f2b65a91c5b65b2225c3dbb2feb45141b5d1605`。在禁网、只读 root、non-root、drop capabilities 与 writable `/tmp` tmpfs 条件下，烟测确认 Python 3.12.15 / pytest 8.3.5。服务器架构或重新构建后应另行记录实际镜像身份。

## 历史集成修复

提交 `5b1b7ce6920624e2724172431c7879f9f2fa10fd` 包含：

- 为 Requirement/Risk Mission 补齐 Typed 输出契约；Codex Adapter 生成供应商专用严格 Schema，使用官方 `--output-schema` / `--output-last-message` 通道，工具保持 read-only sandbox；不再要求模型写结果文件。
- 增加 Worker 的官方 CLI binary、可选 model 和显式 ignore-user-config 配置，避免修改用户全局 CLI 设置；认证文件不进入仓库或验收报告。
- 修复 macOS 临时目录 `/var` 与 `/private/var` 规范化误判；保留对实际源代码修改、删除、symlink 的拒绝。
- 使用 Python 监督 API/Worker/Web 进程组，兼容系统 Bash；Compose 端口绑定回环。
- 测试 workspace/artifact 与操作者配置隔离，支持单独测试数据库；保留生产路径验证。
- 将 Web 升级至 Next 15.5.28、React/DOM 19.3.1，加入 Ant Design 官方 React 19 补丁及 PostCSS 8.5.30 override；适配 route params 和独立类型生成，消除本次 audit 报告的 critical/high 依赖项。

提交 `89d15aeb73230d313809296de2343b8eddc6d6b6` 追加该次真实集成修复：

- 明确 Agent 完成的是 Proposal，正式测试验证由 HyperTest Runner 在接受实现后执行；不因 Agent 的 read-only workspace 无法写测试或未安装 pytest 而把完整 Proposal 自报为 PARTIAL。
- 将现有 `test_*` / `TestClass::test_function` symbol 校验规则同时暴露在 Schema，不接受 class-only symbol；没有改变既有规则含义。
- 为每次 Session 的 Proposal key 添加固定前缀，避免显式 retry 重用被拒绝 Attempt 已占用的 key；不改写旧 Proposal，也不放宽 Canonical 去重。
- stdout JSONL 分块读取，telemetry 单行上限 2 MB；超限丢弃并继续读取正式 final-response 文件，修复默认 64 KiB 行上限误阻断合法结果；三项独立目标回归覆盖正常大行、超界后恢复与 EOF。

TMP 与运行排障说明随实现同步更新；这两次修复均无 schema migration，未变更 Canonical 状态所有权、正式执行信任模型或 `0008_job_ownership` head。

## 历史本地真实模型验收记录

两条链的全部最终 Agent Proposal 均来自实际官方 Codex CLI 0.163.0，使用既有本机认证、`ignore-user-config=true` 及 CLI 默认模型；该次未指定模型名，不推测其具体名称。未注入 fixture/mock 结果，未直接写 Canonical State。独立 Worker 驱动 Mission，HyperTest 验证并提交，正式事实由 Docker Runner 产生。

样例是内存态 checkout 后端：`submit_order(key)` 对相同非空字符串 key 的重复/并发提交只能保存一个订单，不同 key 分别保存；`order_count()` 返回已接受唯一 key 数。PRD 明确排除 HTTP、认证、持久化与非法 key 处理；只使用 stdlib/pytest。此验收证明该支持路径的完整闭环，不扩大为这些未覆盖领域的验收。

| 登记项 | 正确应用 commit / 成功链路 | 错误应用 commit / 失败诊断链路 |
|---|---|---|
| 归档结论 | **本地真实链路通过；FINAL RELEASE_READY** | **本地真实失败诊断通过；FINAL RELEASE_BLOCKED** |
| Repository 身份 | `/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/local-runtime/workspaces/live-checkout-20261017/source` | 同左 |
| 完整 source commit | `1eb284beaa45b2f2b878dc0e89a40c9de5709f51` | `9d7624fbf5039f784207ad33b16ff045bafac4aa` |
| HyperTest 执行代码 | 分析阶段 `5b1b7ce6920624e2724172431c7879f9f2fa10fd`；显式 retry / Runner / Gate `89d15aeb73230d313809296de2343b8eddc6d6b6` | 同左；最终归档 HEAD 为 `89d15aeb73230d313809296de2343b8eddc6d6b6` |
| Project ID | `01a14965-7380-75ab-a040-ee6264e3dd9a` | `01a14965-6a09-75d6-8b1b-6c66cf9f423d` |
| Run ID | `01a14965-e429-7885-8f4c-59ae148f3c53`，最终 COMPLETED | `01a14965-6a2c-72e8-970f-f9f0d0a0171d`，最终 BLOCKED |
| 原始 FAILED Job | `01a14966-1ddc-729d-a225-aa82be4a963c` | `01a14965-6a49-7183-baef-7193da8e7b77` |
| 关联 retry Job | `01a1496f-1d62-78fa-aa82-a0ae6c6de1f6`，SUCCEEDED / VERDICT_FINALIZED | `01a1496f-b6c3-790a-8144-6633d6528193`，SUCCEEDED / VERDICT_FINALIZED；质量结论仍为阻断 |
| Mission / Attempt | 4 类 Mission 完成；IMPLEMENT_TESTS 的 Attempt 1 REJECTED、Attempt 2 ACCEPTED | 5 类 Mission 完成，包含实际 `DIAGNOSE_FAILURE`；实现 Attempt 1 REJECTED、Attempt 2 ACCEPTED |
| Canonical 数量 | 7 Requirement / 5 Risk / 9 Case / 9 Implementation / 1 Execution / 4 Evidence / 0 Finding | 8 Requirement / 6 Risk / 9 Case / 9 Implementation / 1 Execution / 4 Evidence / 1 Finding |
| OFFICIAL Docker Execution ID | `01a14970-2a32-70c3-8dff-eb2a263dda6d` | `01a14970-a88e-7e9f-bfde-034aee7fd5f0` |
| 执行结果 | COMPLETED / PASS / exit 0；9 个 Canonical Case 均 PASS；JUnit **30 tests / 0 failures / 0 errors / 0 skipped** | COMPLETED / FAIL / exit 1；9 个 Case 中 **6 FAIL / 3 PASS**；参数化后 JUnit **10 tests / 7 failures / 3 passed** |
| 镜像与隔离 | `sha256:0a672dd19ac3cd2d19402ef38f2b65a91c5b65b2225c3dbb2feb45141b5d1605`；network none / read-only / non-root / dropped capabilities | 同一可信镜像；execution spec / environment hash / source commit 复核通过 |
| Evidence | metadata、JUnit、stdout、stderr 全部 RUNNER / VERIFIED；4 份 artifact checksum 读取复验通过 | 同左；证据内容与大小核验通过，可信证据支撑实际失败与 Finding |
| Finding | 0 | `01a14971-2778-7f2b-892b-6f7fc66e0fd7`；PRODUCT_DEFECT / MAJOR；Agent 接受后 NEW，之后由操作者在真实 Web TRIAGED→CONFIRMED；row_version 3，未 Resolve |
| FINAL Verdict | `01a14970-2dae-7389-b24f-dc4159e7a6ea`，sequence 1，RELEASE_READY | 原 `01a14971-27db-7030-890d-f9dba2217134`，sequence 1；确认 Finding 后追加 `01a14974-aad4-72d6-b432-bec454adc695`，sequence 2；两份均 FINAL RELEASE_BLOCKED |
| 关系核验 | RequirementRisk 14、RiskTestCase 9、ImplementationTestCase 9、ExecutionTestCase 9、ExecutionEvidence 4、VerdictEvidence 4 | 首轮 1 份 Verdict 时 SQL 有 **45 条完整连接行**；确认并追加 Verdict 后 **90 条**，由两份 Verdict 扩展连接行，并非 90 个不同测试事实 |
| 幂等与历史 | 重发 retry key 返回同 Job；同状态重评 Gate 返回同 Verdict；应用源未改变 | bootstrap/Job/retry/execution/Gate 同状态重发复用身份；不同输入同 key、活跃 Run 冲突 409；原 FAILED / REJECTED 历史保留 |
| 主要证据 | [成功 JSON](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/live-pass-2026-10-17.json)、[实际 Web Verdict 截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/live-pass-verdict-2026-10-17.png) | [失败 JSON](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/live-failure-2026-10-17.json)、[失败验收说明](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/live-failure-2026-10-17.md)、[实际 Web Finding 截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/live-failure-finding-2026-10-17.png) |

首轮真实 IMPLEMENT_TESTS 曾返回 PARTIAL，并被平台以 `RESULT_NOT_COMPLETED` 拒绝。Agent 把后续 Runner 的验证职责误解为自己必须在 read-only 工作区运行 pytest；失败链原 Proposal 还包含 class-only symbol。平台当时未写入 Implementation。修复职责说明、向 Schema 暴露既有 symbol 规则并增加 Session Proposal key 前缀后，操作者显式 retry，创建关联新 Job 和 Attempt 2；没有把旧结果改为成功，没有抹掉旧 Proposal 或重复已完成的分析状态。最终采用的仍是真实模型重新提交的结果。

失败链诊断定位到锁内无条件 append 导致同 key 重复接受。第 1 份 RELEASE_BLOCKED 在 Finding 仍为 NEW 时即由正式 FAIL 独立支撑。之后操作者实际在 Web 提供证据核验 reason 与 expected row_version，执行 NEW→TRIAGED→CONFIRMED；未执行 RESOLVED。Web 再次提交 EVALUATE_GATE Job `01a14974-a996-7ce1-9a80-5951f6999b63`（`JOB-01A14974A9967F069A68694A42F42ED0`）成功，状态变化后追加第 2 份 FINAL，旧第 1 份保持不变。Agent 没有直接确认 Finding 或决定 Verdict。

| 可信内容 / 决策摘要 | 完整 SHA-256 |
|---|---|
| 成功 metadata `01a14970-2d8b-7a53-a17a-79fbcbc4b03c` | `1de573b4edd77f171e1ce4dc59ccb6bf5c53478eccc627cf297c88f4d8824ccf` |
| 成功 JUnit `01a14970-2d89-71ba-b3a1-f69c2e408efc` | `a94f9f9f0391f7fc2195a43a66fa83628e8edca2c2d89d0f7dc2ba1237bd059a` |
| 成功 FINAL state hash / manifest | `261039423ce11ec4b1b68aa51e95a6d736f8ac44fd2ecdb1e271c49660c9b600` / `47800e769749d2b030694f353c2183da3d656ddbfaee2930ce06cddb5a1788d7` |
| 失败 metadata `01a14970-ab92-78e3-b07b-aad00f587e05` | `25843ef2dc00c44fb7b393c105f47bde703e243361f4a93fe9357dfdba5f7e03` |
| 失败 JUnit `01a14970-ab90-74e9-b67d-71c91e44396a` | `69d5b5ed0b3d02c4664e25e2ea82d05d9bc3ec61c0820cc8020b3d8177054877` |
| 失败第 1 份 FINAL state hash | `5e4358cffd3cbdde31bc0d5991196e03753c9154443fd438549beb8e1556296b` |
| 失败第 2 份 FINAL state hash | `c9edb637dd0dddc99a6b7e7e0ba9a14d6b52c4565f19170b352a9bb2fc356bcd` |
| 两份失败 FINAL 的 evidence manifest | `283aaef9c4f3eda1592ace3e7c2ddb4cf6d33a0c4a4de054febc1c4cf26bee0b` |

## 历史首次服务器交付与真实模型记录（89d15ae）

服务器实际执行了完整成功与失败诊断两条链路，所有 Mission 都在第一次 Attempt 完成，没有预设 Agent 输出或替代真实模型。先前缺少事实时的 BLOCKED 是真实 Gate 决策；事实齐全后追加新 FINAL，没有重写历史。

| 服务器登记项 | 实际记录 |
|---|---|
| 主机 | `155.138.206.106`，Debian 13.7 x86_64、2CPU、3915MiB RAM；已有约7.7GiB swap保留 |
| 接管前状态 | 本机SSH成功；无HyperTest服务、数据库或应用数据；仅SSH22公网监听；未要求重复改防火墙 |
| 首次真实验收部署代码 | `/opt/hypertest/current` → `/opt/hypertest/releases/89d15aeb73230d313809296de2343b8eddc6d6b6`；API/Worker/Web实际cwd及clean tracked状态已核对 |
| 服务账号和存储 | `hypertest`，home `/var/lib/hypertest`；共享 `/etc/hypertest/hypertest.env`、Artifacts和workspaces；未复制或记录认证内容 |
| Runtime | Python3.12.15、Node22.23.3、PostgreSQL17.11、Docker26.1.5、官方Codex0.163.0；CLI默认模型已实际执行 |
| Runner镜像 | `sha256:a8f6f769b6b6a34ed6e6968b6c9816c17d860fbb38445c2473d3544addd20b56` / amd64；网络none、只读root、nonroot、drop capabilities、资源限制 |
| 数据库和必需检查 | 正式库首次0001→0008；独立测试库212 passed / 3 warnings / 142.49s，Ruff通过；Web npm ci/typecheck/build通过。89d相对5b Web输入逐文件无差异，核对产物hash后复用 |
| 服务与端口 | systemd API/独立单Worker/生产Web/nginx实际就绪；8000/3000/8080/5432均127.0.0.1，仅SSH22公网开放 |
| OAuth | 用户亲自在hypertest账号完成；只读`codex login status`返回Logged in using ChatGPT / exit0；随后真实任务证实模型可用 |
| Web与持久性 | 生产Web创建Project/Run、提交cycle；升级后身份不变；刷新继续观察同一后台Job；同Job/Execution/Gate重发均复用原ID |
| SQL追溯与审计 | pass核心关系JOIN 92行、fail核心56行；含Finding的完整失败链15行（均为连接结果，不代表独立事实数）；pass 62 Audit/62 Outbox、fail 69/69，逐实体事件配对差异0；Job归属异常0、accepted Proposal缺实体0 |
| 备份与恢复 | `/var/backups/hypertest/20261017T110027Z` 配对dump/Artifacts均SHA通过；实际恢复到独立库 `hypertest_restorecheck_20261017110028`，含2Run/2Execution/8Evidence/3FINAL/1Finding/3Job；从新解包目录验证15个引用/12个唯一Artifact（含生成源码、PRD/config），正式库未覆盖 |
| 运维与源码材料 | [服务器操作](SERVER_OPERATIONS.md)；原始交接保留，Debian13衍生部署包固定89d；两个真实源commit的Gitbundle已导出并校验 |

| 服务器真实链路 | 正确commit / 成功 | 错误commit / 失败诊断 |
|---|---|---|
| Source commit | `3654e6b656b6ae70301de797a533382b210fd0e5` | `8baa49cbb67956e99bd8c6a9a732ff81db9105e2` |
| Run ID | `01a14972-ca09-7f60-9b75-a63ae8bdc74e` | `01a14977-32df-7db6-9a45-9038dfd85981` |
| cycle Job ID | `01a14977-b489-7cab-8c4f-d171e53f20de` / SUCCEEDED | `01a14978-12b6-7722-bf8b-ed53052c970e` / SUCCEEDED |
| Requirement / Risk / Case / Implementation | 7 / 7 / 11 / 1（一个参数化实现关联11个Case） | 8 / 8 / 12 / 2 |
| Mission | 四类均Attempt1接受 | 五类均Attempt1接受，含DIAGNOSE_FAILURE |
| Official Docker Execution | `01a1497a-c4a2-7f10-b3f3-b144f2098e14` / COMPLETED / PASS / exit0 | `01a1497d-d175-7be9-b3de-d8da18383566` / COMPLETED / FAIL / exit1 |
| 实际JUnit | 14 tests、0失败/错误/跳过 | 11个pytest实例：5失败、6通过、0错误/跳过；12个Canonical Case按Implementation聚合为10FAIL/2PASS |
| Evidence | 4份RUNNER/VERIFIED，原字节SHA/size全部通过 | 4份RUNNER/VERIFIED，原字节SHA/size全部通过 |
| Finding | 无 | `01a1497e-33eb-7387-8aa8-0bf05a8b6c1b` / PRODUCT_DEFECT / MAJOR / NEW；保留给操作者分诊，模型未直接确认 |
| FINAL Verdict | `01a1497a-d92c-7405-b8a3-aaefde8df54f` / #2 RELEASE_READY；#1 BLOCKED保留 | `01a1497e-35c3-76bd-ab23-cb7d8f93a003` / RELEASE_BLOCKED |
| State hash | `432c9af714cfee97877e6fe88fc21e855600135bd9fba1edfe439ec5e9326630` | `7193d443949d6ef54cdca28ff8ee05d3bebdf40040a918694160fd53a7476034` |
| Evidence manifest | `e427466812e745cafb62d3fcd0017f385fd87dec67fe5efdea9a4da6558b4350` | `c199f65e18ac382255c33dfcc2fec817bc26524692f52846bd4c48953dd926a6` |

正式事实来自真实Docker Runner：通过链14项pytest全部通过；失败链检出固定错误源的重复订单行为，真实诊断结合代码和可信Evidence生成Finding。服务器只运行一个Worker，两Run串行消费；单Job成功不代表测试PASS。所有测试源码来自实际Codex Proposal，源应用checkout保持完整SHA和clean tracked状态。

[服务器成功JSON](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-live-pass-2026-10-17.json)、[成功说明](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-live-pass-2026-10-17.md)、[服务器失败JSON](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-live-failure-2026-10-17.json)、[失败说明](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-live-failure-2026-10-17.md)保留Attempt、Proposal、正式执行、Artifact校验和幂等证据；独立服务器SQL/审计核对见服务器验收记录。

访问地址：[生产工作台](http://127.0.0.1:8080)。本机通过 SSH 隧道访问；连接命令如下（仅本机监听，使用前检查现有连接）：

```bash
ssh -p 22 -N -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:127.0.0.1:8080 root@155.138.206.106
```

## 证据索引与阶段边界

以下为本机交接目录中的实际文件。便携移交副本为 [验收包](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/hypertest-one-acceptance-2026-10-17.zip)，包含允许清单内的报告、四Run证据/原始Artifacts、SHA清单、源fixture Gitbundle和截图；不含认证、连接资料或环境配置。

- [完整交接依据](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/HANDOFF.md)。
- [首次接管本地检查与安全来源](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/local-checks-2026-10-17.md)。
- [基础修复后端检查日志（208 passed）](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/local-pytest-final.log)；[最终真实集成修复检查（212 passed）](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/local-pytest-live-fixes.log)。
- [独立增量审查与有界 telemetry 修复证据](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/integration-review-2026-10-17.md)。
- [npm audit 最终 JSON](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/local-npm-audit-final.json)。
- [接管版本的静态产品/架构核对](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/product-audit-2026-10-17.md)：其初始缺口是修复前基线，应结合本记录的修复提交阅读；不作为当前尚未完成的缺口直接复述。
- [首次真实验收配对备份的隔离恢复证据](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-final-restore-2026-10-17.json)；[首次验收后的服务状态](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-final-state-2026-10-17.json)。
- [服务器验收记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-acceptance-2026-10-17.md)：包含实际部署、回环监听、SQL追溯、配对备份和隔离恢复。

[旧 cloud 诊断](CODEX_RUNTIME_TROUBLESHOOTING.md)保留 EROFS 与 CONNECT 403 的历史来源，不能据此断言上一轮本机或服务器认证失效。上一轮以实际环境和上面的验收登记为准。

本阶段运行边界为受控环境内的单个可信操作者。更多 Harness/语言、Playwright/k6/Kubernetes、语义覆盖、自动修复与回归选择、跨 Run 知识、定时调度、Outbox 外发、对象存储/签名、登录/RBAC/多租户和公网加固属于后续路线，不在上一轮尚无证据时标记完成。上述四条真实模型链执行的集成修复提交为 `89d15aeb73230d313809296de2343b8eddc6d6b6`；上一轮切换前部署基线为 `79d329299d038ff9e6a3fe1659fb27bf589062c1`。上一轮最终 302 项检查与 298 项冻结源码上的真实 Web 整链已登记；最终 commit 及服务器切换身份见交付报告。第一阶段核心支持链已验收的结论不扩展为完整 TMP 工具层、所有后续能力或完全无人值守发布。
