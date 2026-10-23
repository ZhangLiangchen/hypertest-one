# 项目与会话任务管理功能测试环境部署记录

日期：2026-10-23，Asia/Singapore。状态：**Test Environment Deployed / Remote Management Verified / Historical Preservation Verified / Observation Completed**。

**环境定位订正（用户2026-10-23明确）：`hypertest-one` 是单人专用测试服务器，用于云端任务执行验证，
不是生产环境，没有多人依赖，允许开发过程中的服务中断和重启。** 此前将该机器称为“生产”并默认采用
工作树打包上传、维护窗口、配对冷恢复和固定15分钟观察，是对环境定位及交付要求的过度解读。
本文保留当时实际执行的动作、结果、hash、日志和路径；`PRODUCTION` 文件名、已有 `production`
技术标识和受保护证据目录不重命名，不伪改历史。原 `Production Deployed` 状态措辞不代表真实生产等级。
今后默认本地修改→commit/push Git→服务器取指定commit/branch构建、按需迁移及重启→远端相关测试；
纯文档只静态校验后commit/push。详见[当前交付流程](SERVER_OPERATIONS.md#当前环境与默认交付流程)，
下面这一次已经做过的高保障流程不构成未来部署的审批或固定测试门槛。

项目和会话任务的编辑、人工状态调整、软删除及恢复已于 **2026-10-23 05:49:04.189567 UTC** 开放测试服务器入口，线上浏览器管理 canary、最终历史保全、标准巡检及实际15分30秒观察均通过。本次只更新 API / Web，现有库从 `0022_session_task_sync` 向前迁移到 `0023_project_task_management`；原 Worker、nginx、PostgreSQL、Bridge 和固定运维包保留。独立核验确认原 **14个 Project、13个 SessionTask** 及其历史保留；D快照时刻75张旧业务表的8037条原行无缺失、无修改，之后仅1条Worker的last_seen_at发生合法观测变化。本轮新建fixture已软删除，记录和失败历史继续保留在回收站。

本记录仅公开源码身份、hash、计数和验收边界。原任务内容、访问地址、凭据、完整数据库逐行摘要和备份保存在受保护的发布目录。它是平台管理功能发布记录，不是 SUT 测试执行、Runner Evidence 或 Gate 验收。

## 发布身份与回归

| 项目 | 已核验结果 |
| --- | --- |
| 源码基线 | `5c03e4d90bed69b6420238849cbb3a8bae2f4c42` 上的未提交工作树快照；不是已合并的 CI release |
| 冻结源码 manifest | `f44339205d21af642d18696b013ed62b6212182bdb7fdb432e884f17bd1fec3b`，404个文件；逐文件内容、大小及模式核对一致 |
| 源码归档 SHA-256 | `c80e016b2ba925886ca2d202a983cc1606a69a85b86c2533e7b7fdbe9fc6e9ce` |
| API 镜像 | `sha256:7ef772cd313515834cad1e414987eeadacb6eb0a110143c0d0d1eef1864ae636` |
| Web 镜像 | `sha256:bd4d7e56e995dd750230e0cfa8a686869bc419f8f0447979df8aa777c86861a0` |
| 保留的 Worker 镜像 | `sha256:7796433173907d7b4d3aa62f55a24dedc49af8ac91f959b3b1999a13a1c47f60`；原容器 stop/start，没有升级 Worker 源码或依赖 |
| PostgreSQL | 原 PG17.11 容器、镜像、数据卷、启动时间、重启计数及 mount 保留，全程没有停止数据库 |
| 固定运维 manifest | `61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d`；实际安装内容通过 `sha256sum -c` |
| 正常运行时 import | Python3.12.15、UID999；实际从 `site-packages/hypertest` 导入，157项源码及 Alembic 文件 hash 与冻结 manifest 一致 |
| Linux / 独立 PG17 回归 | 收集1082项，**1055 passed、27 skipped、59 warnings**，189.80秒；另行先执行的2项 sanity 均通过 |
| Web 验证 | 133项测试、TypeScript 检查和 production build 通过；本地独立 PostgreSQL 上完成真实 UI/API 管理闭环 |

Linux 回归使用隔离内部网络和独立 PG17.11，不挂载服务器运行 env、认证或 Docker socket。27个 skip 分别是20项显式真实 Docker 场景、1项真实 nginx parser、5项缺 Docker CLI 的 Compose parser，以及1项缺 OpenSSH daemon 工具的检查，不宣称这些场景已由 pytest 执行。Mac / Python3.13 首轮全套中的3项 symlink 诊断失败保留为该环境的实际结果；同一冻结源码在服务器对应的 Linux / Python3.12 全套中包含这3项并通过。本轮新增项目/任务管理与 source tombstone 场景也在该全套中执行。

本文件和 `SERVER_OPERATIONS.md` 的本次发布登记在源码冻结后单独交付，不混入上述404文件 manifest、镜像或源码归档。

## 两次维护窗口

| 窗口 | 实际结果 |
| --- | --- |
| 第一次，05:33:35 UTC 开始 | 冷态捕获76表/8036总行，其中75业务表/8035行；配对备份与隔离恢复的原行及内容检查通过。恢复归档的安全 data filter 去掉所有者，保留的0700目录成为 root 所有，非 root 应用 reader 被拒绝。05:35:39 UTC 停止，正式迁移、image/env/source入口切换均未开始，自动恢复原软件及健康入口，服务器 schema 仍0022，PG身份不变。失败、备份及原恢复目录全部保留。 |
| 权限修复离线验证 | 从该次已恢复 Artifacts 新建独立 reader 副本，复制时不跟随 symlink，只将新树 owner 改为999:999，不 chmod 原服务器文件、原恢复目录或发布目录。原恢复树完整 metadata 未变；副本的内容、类型、链接及模式相同。旧/新应用以 UID999、只读 mount 读取205条摘要，完全相同且0错误。 |
| 第二次，05:43:51 UTC 开始 | 采用新 attempt 目录、新基线、新配对冷备、新恢复目录和新验证数据库；正式迁移及 API/Web 切换成功，05:49:04 UTC 开放入口。没有覆盖或改写首次失败证据。 |

第一次控制器 SHA-256 为 `27f9283c6a0fa8398d0a8b0a543caf4744e3bff83ff14fd44d257a669b4ee5f2`；第二次为 `9d7181faae2d52283d3ef4ea59811ab7dde2c77739bc166e5e50b973d43684e1`。后者只增加独立 attempt 目录和上述 reader 副本准备，候选产品源码及镜像未变。

## 正式冷备、迁移与 C 入口前保全

此前热 `pg_dump` 预演的75业务表/8035行与205条旧/新应用读取摘要完全一致，不能替代下面的正式配对冷备。

第二次冷态 **A** 是本次正式切换锚：76张表/8038总行，其中75张原业务及运行控制表共 **8037行**。首次恢复健康检查追加的控制及心跳记录保留在该新基线，没有将正常追加当作原数据修改。A包含原14个项目、13个会话任务、计划、用例与报告修订、SyncReceipt，以及既有 legacy/native 历史。

配对备份目录为 `management-f44339205d21-20261023T054444Z`，具有 COMPLETE 标记；manifest SHA-256 为 `2e5e87f2d6fa47b98708f4725da4e331bb93cdc7319839a3003edbbd72395e13`。在全新数据库及文件目录恢复后，原75表每个 PK 的行和列 hash 精确相同；归档内容及链接核验通过。原库没有被 restore 覆盖、drop 或 downgrade。

恢复 clone 与服务器现有库分别执行0023。**B** 中原75表按明确的旧列投影逐行完全一致，clone与服务器现有库投影相同。原表仅新增 nullable `projects.deleted_at`、`session_tasks.deleted_at`、`session_tasks.last_managed_at`，新增不可变 `session_task_management_revisions` 表；开放入口前该表为空。恢复后的旧/新应用 reader 使用上述独立权限准备副本，205条记录精确相同、0错误：Evidence51、Implementation50、PRD13、configuration13，以及13个任务各自的任务、用例、用例历史、报告、报告历史和同步历史。metadata URI 不作为内容地址抓取。

新应用内部就绪后的 **C** 再逐个核对原PK及原列，8037条原始记录无缺失、无修改；新增仅1条成功的运行控制记录和1条无活动 Job 的 Worker heartbeat。183个外键均已验证、孤儿数为0。控制器只允许节点连接观测与心跳的合法单调变化，本次 C 比较中原行连这些观测差异也没有出现。13个非终态 SessionTask 是保留的管理进度，没有被改成空闲或取消。

文件清单覆盖 **8659个原普通文件**：Artifacts85、workspaces8533、Bridge state13、原生 sessions28，不含 `__pycache__`。原文件按内容 SHA-256、大小、uid/gid、mode和mtime_ns比较；清单内目录保留类型、uid/gid和mode，不比较目录size/mtime，不能将此描述为所有临时文件或目录时间均未变化。归档恢复的内容保全、reader派生副本的owner调整与服务器原文件权限保全分别检查。配对备份不复制 OAuth 或 Provider 原生会话；原位 sessions清单及认证metadata保全不等同整机灾难恢复备份。

整个关闭入口、确认执行工作为空、冷备、恢复、迁移、切换及异常恢复受同一 `/run/lock/hypertest-maintenance.lock` 覆盖。没有调用整栈 restart 或停止 PostgreSQL。原 Worker/nginx 容器及镜像保留；compose.env 只替换API/Web两个image键，保留uid/gid/mode。固定ops、Bridge源码入口、受保护配置、TLS/SSH/VPN/UFW/Docker守卫及backup timer保留。

独立只读 unit 核验覆盖05:21:54与05:50:53 UTC：6份实际 unit/drop-in文件、2份固定ops脚本及bridge.env metadata完整一致，effective依赖关系一致。Bridge仅位于stack的Wants/After，不在Requires/BindsTo/PartOf；stack及定时备份使用同一维护锁，停止Bridge不会传播为整栈ExecStop。没有仅凭主unit文件存在推断drop-in和实际依赖。

## 线上 canary、D 保全与观察

canary限定为本轮新建的管理fixture：Project `01a1674f-5e47-7ab9-a28d-d1ac8844cc50`、SessionTask `01a16750-1e30-745d-8232-ebd486504b43`。它们不代表真实SUT测试或旧任务的重新执行。原14个项目和13个任务不作为编辑、删除或状态调整对象。

实际 Chrome 通过既有可信入口验收项目编辑及ACTIVE→ARCHIVED→ACTIVE、任务编辑、COMPLETED后重开、删除/恢复、回收站详情刷新，以及有未删除任务时拒绝删除项目、父项目未恢复时拒绝恢复任务。两个自有页面串行制造版本冲突，409后未提交输入保留；刷新不会自动覆盖服务器最新值，需显式重新打开后提交。保存期间的重复操作禁用也有实际UI记录。严格HTTPS读回使用CA及hostname校验，没有改变浏览器信任设置。

05:57:50 UTC最终只读结果为Project **v7 / ACTIVE / 已软删除**、Task **v10 / IN_PROGRESS / reported FAIL / 已软删除**。任务有连续v2..v10共9个人工修订、1个原sync receipt、各1个case/report修订。独立比较初始、COMPLETED、已删除、已恢复及最终五阶段：case/report与其完整历史、原sync逐字段相同，所有既有人工作业快照保留，last_synced_at不因人工修改推进。报告原文SHA-256为 `a5e3b4de0dbcd656a83717061d3de184421383262064ba0b359c23b6170ecf0c`。最后按任务→项目顺序软删除本轮fixture，物理记录及历史留在回收站，没有hard delete。

06:04:43 UTC的最终 **D** 保全通过：旧75表/8037原行逐个PK及旧列hash均保留，原观测行差异也为空；原8659文件清单及目录权限保留，没有新增文件条目。新增仅本轮Project1、Task1、case1、report1、sync receipt1、人工修订9、Audit16、Outbox16，以及成功的运行控制2和空闲heartbeat1。新行均校验归属于本轮fixture或明确允许运行观测；原Audit/Outbox没有被排除。case/report完整字段与原SyncReceipt的请求相同，全部人工快照的身份、source、reported result、创建时间及last_synced_at保持原值。Run、Job、Execution、Evidence、Verdict等执行Canonical表无新增。

D首次分类器将已批准的Alembic主键0022→0023误判为业务新增，未输出通过；原D快照、脚本及失败日志保留。v2读取同一快照，明确验证版本表各一行、列值hash恰为批准的0022/0023后，仅排除该版本表的新增分类，没有扩充业务白名单或重新采样掩盖差异。

线上尚未执行“软删任务后新的来源同步写入被拒绝”这一负向写场景，没有为验收扩大helper或签发来源凭据；相应tombstone拒绝和原key对账由本地及服务器隔离回归覆盖，不能称线上已测。

## 标准巡检与实际稳定观察

`ops/check-remote.sh` 首次于05:58:27 UTC返回1，在执行readiness之前发现旧宿主 `nginx.service` 为failed。独立诊断确认其MainPID为0、UnitFileState仍enabled，失败时间为 **2026-10-22 07:00:18 UTC**；此前journal有20条bind地址占用记录，早于本轮两个维护窗口。06:04:22 UTC经明确授权仅执行 `systemctl reset-failed nginx.service` 清除遗留失败记账，成为inactive/dead、Result=success；没有start/restart/enable/disable该宿主服务。前后监听、服务器nginx/PG身份、访问策略及受保护配置完全相同，unit文件和enabled状态未改；不能将这次修复描述为已禁用旧服务或整改其开机策略。首次失败与独立重检证据均保留，重检实际exit0，readiness为 **10/10通过**。

稳定观察由两段有限进程完成：首55点从05:50:02.239807至06:04:04.189664 UTC，实际841.95秒；补段7点从06:04:05.642348至06:05:32.239934 UTC。合计 **62点、930.000127秒（15分30秒）**，最大采样间隔16.064607秒。首样在入口开放58.05秒后，不能宣称从开放瞬间连续采样。全部采样API/Web/nginx均200、五容器healthy，id/image/启动时间/重启计数均与C相同，错误数0，API/nginx自入口开放后的HTTP5xx计数均0。首段摘要的admission时长不能代替其实际采样时长；本结论依据两段原始采样合并，不覆盖原首段摘要。

标准巡检后的独立复核于 **06:07:37 UTC** 通过：74张非运行观测表/4211行与D逐行摘要多重集完全一致，包含全部业务、Audit、Outbox和人工修订；其余3张运行观测表单独校验。仅新增1条CAPABILITIES / SUCCEEDED / error=null控制记录，旧控制记录保留；节点稳定配置及单调观测、Worker空闲心跳通过。末态API/Web/nginx均200，原PG与C后全部容器身份、策略、受保护配置保持，13类执行/等待/UNKNOWN计数全0。严格CA/hostname的外部只读health及Web也于06:01:33/34 UTC均为200。

标准readiness保留 `real_testing_cycle_verified=false`、`connector_tls_e2e_verified=false` 等范围声明；这些管理与健康检查不作为新SUT周期或新Connector执行验收。本轮没有变更访问策略，没有重复完整白名单允许/拒绝矩阵。

06:09:58 UTC收尾核验确认两个有限monitor及其sample子进程均退出；仅清理本轮确权、没有持久挂载的独立测试PG容器及其唯一internal网络。服务器五容器、PG、访问策略和受保护配置与清理前相同，原镜像、所有冷备、失败产物、恢复目录及服务器内验证数据库均保留，磁盘剩余20.58GiB。06:09:56 UTC末态五容器均healthy，容器身份/启动时间/重启计数与C相同。D之后的最终live observation另行验证节点集合不变、Worker所有稳定列不变，仅1条last_seen_at递增；不能把D的“原行无修改”延伸为后续观测时间也必须冻结。

## 恢复与验收边界

0023是增量schema，但旧API只识别SyncReceipt版本且忽略tombstone，不能完整解释人工管理后的任务历史。本轮一旦接受人工修订或软删除，恢复必须关闭admission、保留已接受记录并使用兼容版本向前修复；不能直接回退旧API、降级schema、覆盖恢复现有库或清除新历史。

人工状态只调整管理进度，允许重开，保留reported result；软删除可以恢复，不释放session或Project key，不级联删除资产。项目有未删除会话任务或任何legacy/native run时拒绝删除；source授权/接受与Connector新采集也检查项目未删除，原key只读对账保留。字段和生命周期见[领域规范](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#504-人工编辑进度调整与软删除2026-10-23)，HTTP契约见[TMP](protocol/TEST_MISSION_PROTOCOL.md#453-operator-项目与任务管理-api2026-10-23)，用户操作见[管理说明](CODEX_SESSION_TASK_SYNC.md#web人工管理与回收站)。

本次没有新增登录/RBAC、扩大Agent权限、重跑旧测试或开展SUT业务测试；CAPABILITIES等检查仅证明旧Worker与新API的控制面兼容。既有真实执行证据保持原解释，不因本次管理验收升级为新的VERIFIED Evidence或RELEASE_READY。

## 证据索引

受保护服务器目录根为 `/opt/hypertest/deployments/project-task-management-20261023-f44339205d21`；第二次位于同名加 `-attempt2` 的独立目录。

| 证据 | 位置与含义 |
| --- | --- |
| 源码与实际import | 首目录 `source/SOURCE_MANIFEST.json`、`candidate-effective-import.json`；第二次 `C-effective-import.json` |
| Linux回归 | 首目录 `linux-pg17-test-result.json`、`linux-pg17-full-tests.log` |
| 热预演 | 首目录 `hot-preflight-result.json`、`hot-preflight-old-new-readers.json`；明确是hot备份 |
| 首次失败及离线修复 | 首目录 `cutover-result.json`、`phases.jsonl`、`failed-attempt-derived-reader-verification.json` |
| 正式冷备/恢复/迁移 | 第二次 `A-cold-database.json`、`A-cold-files.json`、`restore-rehearsal.json`、`B-clone-database.json`、`B-migrated-database.json` |
| 旧/新应用读取 | 第二次 `reader-copy-permission-preparation.json`、`clone-application-readers.json` |
| C及入口 | 第二次 `C-ready-database.json`、`C-history-comparison.json`、`C-admitted-host.json`、`cutover-result.json`、`phases.jsonl` |
| 服务器UI与严格HTTPS读回 | 本机私有 `project-task-management-prod-20261023-f855` 目录的 `readback-{initial,completed,deleted-task,restored,final}.json`、`original-records-final-comparison.json`、`ui-observations.json` 及两张UI截图；`readback-final.json` SHA `ca6e03360a0621dbcb8256e3bb1acafbe4a29255d43735cc107e70784a8d7118` |
| D最终保全 | 第二次 `D-final-database.json`、`D-new-row-classification.json`、`D-fixture-full-field-preservation.json`、`D-original-files-preservation.json`、`D-final-host.json`、`D-final-preservation-result.json`；最后一项SHA `e93dc42fc91107a07089b7c80106e8f17c42ed11e3b7c2bb9fd7b0800101a81f` |
| 遗留nginx诊断及修复 | 第二次 `legacy-nginx-failed-preflight.json`、`legacy-nginx-prior-failure-journal.jsonl`、`legacy-nginx-{before-reset,after-reset,reset-result}.json`；标准巡检 `standard-check-first.log` / `standard-check-recheck.log`，分别保留exit1与exit0 |
| 实际观察 | 第二次 `health-samples.jsonl`、`health-extension-samples.jsonl`、`health-combined-result.json`；合并摘要SHA `403e59a709e6ceb4c38e4d6c88f3ee6243e0fb624a7d87190d3de5ec38941851`；首段 `health-observation-result.json` 只对应55点 |
| 巡检后独立末态 | 第二次 `post-standard-check-canonical-projection.json`、`post-standard-check-final-host.json`、`post-standard-check-result.json`；最后一项SHA `49d48bec9772bd7b0838d53db4ef0f96c105aee6225da9bb112a2e8766760b21` |
| 最后观测及清理 | 第二次 `post-standard-check-live-observation-validation.json`、`owned-test-resource-cleanup.json`、`post-cleanup-final-host.json`、`standard-check-results.json`；清理摘要SHA `c6a9935b7f27c01c332c32a24df47c1d8c5ec85eba0c9aefaec3619aa1cbae8e` |
| C独立摘要锚 | `cutover-result.json` SHA `053e32c8a770426ca482e41a0745cc2f6892eeb77a59d98930c795a5a7a2c597`；`C-history-comparison.json` SHA `e41a821c3c7909aafda27e2c66f75da6e44e6063423fbc062bea299a1a4b2c2e` |

独立systemd原始只读记录及比较保存在本机受保护审计目录 `hypertest-management-independent-review-20261023`，前后摘要均由原始JSON直接比较完整整数metadata；运行时ExecStart/ExecStop中的PID/时间不作为静态配置hash。原始完整证据留在上述私有目录，公开摘要不包含真实入口或原任务内容。
