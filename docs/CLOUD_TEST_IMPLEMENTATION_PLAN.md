# 云端测试任务分阶段实施计划

**当前增补：** P0与PowerContext已独立实现/部署，受控公开HTTPS首片与框架冻结按[ADR-025](architecture/ADR-025_CLOUD_CONTROLLED_HTTPS_READS.md)开发，默认关闭；最新剩余范围由[当前TODO](TODO.md)拥有。下文“候选/待部署/Memory Proposed”是原Cloud轮次冻结计划，保留历史，不替代当前交付或USER_OWNED验收。

## 当前交付范围与集成顺序

本候选正式迁移文件已接续管理路径的 `0024_local_task_binding`：先 `0025_cloud_tasks`，再 `0026_cloud_ssh_operations`。旧隔离 fixture 的 `0023_cloud_tasks` / `0024_cloud_ssh_operations`、source pins 和接受记录保持历史身份，不以新编号改写。ADR-024 平台预建 Local ID / MCP 绑定已合入当前候选；新空库升级及现有管理 `0023` 库向前升级到 `0026`、最终合并树和统一入口仍待相关远端验证，本段不声明已迁移或部署。服务器是允许中断的单人专用测试环境，按本地修改 → Git commit/push → 服务器拉固定完整 SHA 构建、向前迁移、重启 → 一次相关远端验证交付；纯文档变更只做静态检查，不额外要求生产维护窗口或恢复演练。

当前只交付 DeepSeek Harness + Codex；Claude Code 为占位，不开展具体实现或真实委派验收，也不作为本次候选上线前置。下文完整 P0–P4 包含长期目标，未完成故障矩阵另列，不能据旧 fixture 或将来目标阻止本次已授权的测试环境串行集成。

ADR-022 的 Memory Gateway 是独立 Proposed / NOT IMPLEMENTED 提案，不在本次 Cloud 交付中。经验服务与 Canonical 测试状态、TaskSyncCore 分离；`task:sync` / `cloud:work` 不授权经验访问，服务管理 key 不进入 Agent，外部 Generation / Embedding 默认关闭。

**更新：2026-10-23，Asia/Singapore。部分实现、默认关闭；尚未更新测试服务器常驻Cloud服务。r8固定v19 COMPLETED / reported PASS、canonical固定SSH专项PASS；source31对同v19原接受快照的SNAPSHOT_REASSESSMENT strict PASS，无新的current GET / 模型 / SSH / SUT执行或canonical写。旧source30 NON_PASS与旧任务历史保留；受控19项只读重放、备份 / 隔离服务退场完成，不等于独立writer、legacy VERIFIED / Gate或全P0。**

本计划交付 Cloud 云端模式：[ADR-019](architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md) 的 `cloud-harness-task/v1alpha1`。项目创建 / 配置、任务创建及执行都在云端 Web / API / Worker 链路内完成；共享既有 Project，新增 CloudTask / CloudAttempt，由 Python Worker 通过官方 `deepseek-harness-sdk` 托管 DeepSeek harness，完成六步流程。

Local 本地会话同步模式经 MCP 选择已有授权 Project，同步本地 Agent 的计划、用例、原报告和结果，保留 ADR-018 契约；已发布 Local 0.1.0 的 Claude Code / Codex / DeepSeek harness 适配与独立矩阵不由本 Cloud 计划重验或改变。一个 SUT 的同一 Project 可同时包含 CloudTask 与 SessionTask，不按模式拆项目或设置项目级二选一开关。Local 不创建本机独立 Project、不接管本地 Agent、不要求云端凭据；测试仍可由本地 Agent 调用获授权的远端环境 / CI，Local 标签不证明实际执行位置或来源。

[ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 另接受 Local 的 Hooks 自动触发、MCP 显式操作共用一个本地语义协调器，并复用现有私有客户端 / typed API / journal；Local 0.1.0 的实际交付与真实矩阵按[本地状态](LOCAL_MODE_IMPLEMENTATION_STATUS.md)独立记录。Hooks 不是第三种模式，不改变云端六步 / 官方 Python SDK 或 SessionTask 契约。本地协调器先于 Hook writer 启用，但本地交付不以云端 P0–P4 完成为前置条件；反向也不把 Claude 本地适配作为云端交付的隐含前提。

[ADR-021](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) 将本地设计反哺云端：TaskSyncCore 共享正式资产清单、语义进度、意图合并、冻结提交、幂等对账和固定接受版本读回；CloudTaskReporter / CloudSyncAdapter 在当前 Attempt Worker 内承载云端报告。SDK 保持执行控制职责，主 / 子 Agent 只交付结构化进度和产物，由持权 Worker 写平台。Cloud 不调用 SessionTask sync，不借用 Local token / 全局 journal，也不依赖本地 bootstrap 或三宿主 release。

下列 P0–P4 退出条件仍是完整方案的验收要求，不能从局部代码或隔离 fixture 测试推定已经满足。当前增量不包含生产迁移 / 部署或私有SUT执行；真实模型使用另行授权的云端预配身份，不复制本机登录。现有 [ADR-018 会话同步](CODEX_SESSION_TASK_SYNC.md)继续保留，其 scope、幂等回执、expected-version、分页原文读回、reported result 和失答只查询规则保持原义。

## 当前增量：实现与证明范围

2026-10-22 开始实现后，历史隔离源码已经加入独立 Cloud 领域 / typed API、原编号 `0023_cloud_tasks` additive migration、加密凭据、双仓解析 / 冻结、fenced Worker、SDK 执行边界、阶段报告与 Web 入口。它们仍由单独默认关闭的准入控制，不把旧 Run 的 Provider 或 SessionTask 同步变成执行入口。

| 阶段 | 当前已加入的实现 | 当前证明及剩余边界 |
| --- | --- | --- |
| P0 | 固定官方SDK / runtime `0.2.1rc2`、wire `0.0.1`，doctor / 无模型探针及官方Codex bundle / CLI | 新公有fixture Task固定v20 COMPLETED / reported PASS，ANALYSIS / DESIGN均直接引用子原件，source24严格PASS、独立8项重放通过。旧v17直接引用NON_PASS保留；DeepSeek完整自行路径与故障矩阵仍待，Claude按用户要求占位，**P0完整退出条件未满足** |
| P1 | Project 资源 / 加密凭据元数据和版本、独立权限、输入解析与冻结、操作回执及约束迁移 | 独立 PostgreSQL 迁移与控制平面 fixture 验收已运行；真实私有仓库、凭据轮换 / 环境操作仍须各自验收，不能据合成材料宣称可执行 |
| P2 | 独立Worker、lease / generation、host模型broker、专用隔离、HELD / SETTLED累计预算与原key恢复 | 专用非root systemd / namespace及真实Task整树停止、所有broker drain已观察；r22预算SETTLED41=ROOT36+CODEX5 / 193秒，原56预留保留。真实取消 / 超时 / 撤权 / 失联矩阵、旧会话恢复与外部动作对账仍未全验收，不自动重发prompt |
| P3 | CloudTaskReporter / CloudSyncAdapter与隔离TaskSyncCore账本、REPORT checkpoint、typed资产 / 原件 / Run | r23新Task直接双原件引用与完整Run / case链经r24严格PASS，独立8项重放与raw / diff / 实际文件 / host日志联核。r22 transitive-only / NON_PASS历史不变；真实断言FAIL→合法修订与更多项目范围仍另验，不升级legacy VERIFIED / Gate |
| P4 | Cloud页面 / BFF、资源与秘密录入、任务创建 / 解析 / 下发、混合目录与任务控制；服务启动准备模板 | Web所选152项、origin增量8项、TypeScript / build与1440px / 390px资源 / 草稿截图分别通过。真实Task由独立controller / Worker执行，尚不等于Web全部状态与故障路径验收；服务文件临时doctor ADMITTED，未启动长期生产Worker |

此前里程碑分别登记：source-r21所选 **29文件、535 passed / 1 skipped / 86条既有warnings（51.44秒）**及Ruff通过；source-r22仅澄清handoff契约 / 测试两个文件，针对性 **7文件、169 passed（15.39秒）**与两文件Ruff通过，其他400文件不变，未重跑535项全量。r22 Task `01a16551-0b71-7fa5-83ee-f864f842e447`固定v17 COMPLETED / reported PASS，host ROOT36 / CODEX5全HTTP200完整、namespace / broker停止drain、SETTLED41 REQUEST_CREDITS；独立只读重放9项与本Task实现原件关联通过。DESIGN.artifact_id=null，只通过ANALYSIS传递关联child原件，**strict PRDv3直接双引用要求未全满足**；不改接受结果或旧失败 / RECOVERY / HELD历史。完整source、原件摘要和观察边界见[实现状态](CLOUD_IMPLEMENTATION_STATUS.md)。

第一阶段最新收口：source-r23新Task固定v20 COMPLETED / reported PASS，ANALYSIS与DESIGN直接引用当前child原件；source-r24只读checker对同接受版本strict PASS，独立重放8项与raw / diff / host文件日志联核通过。source-r23所选201、source-r24所选231通过与Ruff分别保留，不将其写成535全量重跑；旧v17直接引用NON_PASS及全部失败 / HELD历史不变。下一阶段仅推进[ADR-023固定SSH诊断](architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)的受控fixture；实现和验收尚在进行，默认关闭，真实staging / 生产未准入。

固定SSH小片的source25已完成独立DB迁移0024和所选32文件685 passed / 1 skipped，原4个Ruff I001失败保留；source26仅4文件导入排列后，SSH所选三文件91 passed及broad Ruff通过，不与685合计，也不是全量重跑。source29独立合成transport及后续r8 canonical SSH专项已通过；source31对同v19快照strict重评PASS、旧source30 NON_PASS与取消、撤权、失联、后代矩阵分别记录。SSH动作截止提前原总截止30秒，仅scope清理、模型与Task预算不延长；默认关闭、未生产准入。

首次真实transport因fixture服务PrivateTmp遮蔽固定配置而在监听前退出，单个START保留UNKNOWN；原ID的NOT_FOUND或票据到期不释放未决状态。source27独立探针实际通过认证 / helper / action exit0，但因systemd清空完成unit的ControlGroup、helper缺少持久原组，第二操作仍UNKNOWN。source29新增action启动前实际原组记录和严格收口，独立新transport已观察两个terminal、host原组empty与stopproof、四项原key / hostpin检查通过；无SDK / 模型 / 正式CloudTask。两次旧UNKNOWN与行政stop历史保留，不补terminal / remote_closed；随后canonical r7未收口、r8 SSH专项通过，证据分别保留。详见[实现状态](CLOUD_IMPLEMENTATION_STATUS.md#ssh实施回归与transport试点)。

source28未测试；source29加入host固定版本wrapper选择以保留旧闭包。首轮111 passed / 1 failed、Ruff未执行，已确认测试profile遗漏`/tmp` exec导致准入正确拒绝；恢复原挂载后同一源码 / 校验独立复验 **112 passed（8.76秒）与broad Ruff通过**，保留首轮结果、不合计计数。随后CloudWorker source26 / helper source29的r7未通过收口，source30 Worker的r8 SSH专项通过；source31对r8同v19快照strict重评PASS，transport试点未代替两轮真实Task。

canonical r7已实际执行但未通过：固定v17 RECOVERY_REQUIRED / NOT_RUN，唯一SSH原操作UNKNOWN，恢复原因SSH_RECONCILIATION_REQUIRED；模型 / namespace停止与已接受Run不越过远端账本门禁，72credits / 900秒保持HELD。当前先定位Worker / transport与独立root probe的差异，按原ID查询保留证据；签票清理须操作者明确下一步，不重START / prompt、不因UNKNOWN自动新建Task或reconcile。原r6严格PASS、source29独立transport通过与本次未通过分别保留。

该差异现已由keyless同image / UID997复现为缺本地NSS记录，OpenSSH在连接前退出；source30新增SSH开启时claim前UID / 主GID解析，默认关闭路径不查询NSS。新pinned image中合成997:988身份与该门禁的远端回归已运行，不改root执行、不挂host `/etc`；后续另行创建关联失败r7的新独立Task，旧UNKNOWN / HELD与原请求继续保留，不把新结果写回旧Attempt。

NSS-only新pinned image已完成合成997:988身份与keyless pwd / ssh-G验证，既有SSH / payload清单不变。source30该image所选32文件 **717 passed / 1 skipped / 86条既有warnings（41.37秒）**及broad Ruff通过；Node前置跳过不计通过，Local兼容快照不冒称当前三宿主全链重验。新r8以独立ledger / 单元 / 授权 / 预算运行，保留旧r7关联，没有重放旧Attempt。

r8固定v19 COMPLETED / reported PASS，canonical固定SSH专项PASS；source31对同一v19固定快照的只读SNAPSHOT_REASSESSMENT实际strict PASS / failures=[]，没有新的current GET、模型 / SSH / SUT或canonical写。source30旧NON_PASS及两码ACTUAL_RUN_EXECUTION_MISMATCH、READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID永久保留；有限checker合法表示修正经独立语义审查、117项controller测试与两文件Ruff通过，非717项重跑。实际ROOT30 / CODEX5停止drain、namespace停止，SETTLED35 REQUEST_CREDITS / 238秒不表示供应商计费。独立双层RO replay19项通过、树不变、raw log / child / code / diff关联；私有dump / catalog通过、未restore演练；owned daemon / API / 精确PG停止、空网络移除，其余数据及旧UNKNOWN / HELD保留。物理Worker30 / helper29 / checker31身份分开，仍非独立writer、legacy VERIFIED / Gate或全部P0。详见[完整证据](CLOUD_IMPLEMENTATION_STATUS.md#r8ssh专项与固定快照严格验收)。

### 当前后续执行顺序

各阶段实现已交错推进，退出条件保持下文原义。下一步按以下顺序收尾，不能把已通过的fixture或代码覆盖扩大为生产准入：

1. r6严格直接原件与r8固定SSH专项已通过；source31对同v19固定快照strict重评PASS，旧source30 NON_PASS及全部旧任务历史保留。正式候选迁移已顺接 `0025` / `0026`，先远端验证新空库和已有管理 `0023` 的向前升级，再按允许中断的专用测试服务器流程更新常驻服务并做一次相关远端验证。后续补取消 / 失租 / 撤权 / 后代矩阵，DeepSeek完整自行路径另补；Claude继续占位，待另行启用授权后独立实现 / 验收。XBlock staging SSH与166dev仅Local，纯Web / API Cloud需之后另接HTTPS adapter。
2. 补P2真实模型活动中的取消 / 超时 / 撤权 / lease失效 / UNKNOWN对账及持久问答矩阵，保留整树停止、broker drain与HELD证据；不自动重放旧prompt或POST。
3. 在单独授权的staging实际项目补P1 / P3私有双仓、依赖 / 入口 / 环境身份和真实FAIL→合法修订原件；SSH / CI / 一般网络先完成窄adapter准入与独立验收，再展示为可用。
4. 完成P4真实Web全流程与长报告 / FAIL / 等待 / 恢复、多窗口持久账本和混合Project兼容验收；Local交付状态由其独立计划负责，不以Cloud增加Local新功能。
5. 常驻测试服务器更新按本地修改→Git commit / push→服务器拉固定SHA构建 / 迁移 / 重启→一次相关远端验证执行。该服务器是允许中断的单人专用测试环境，不新增生产维护窗口或完整恢复演练门槛；未来release信任 / 恢复等可靠性目标另行完成。正式 Git 候选已包含管理路径 `0023_project_task_management` / `0024_local_task_binding` 和后续 `0025_cloud_tasks` / `0026_cloud_ssh_operations`，最终合并树仍待相关远端验证；原隔离验收history / source pins不重写。当前尚未更新常驻Cloud服务。

第二轮独立远端后端检查为 **115 passed**，并完成空库向前迁移；它只覆盖本轮选择的 SDK / Cloud / 同步兼容链路，不是全仓所有测试或六步 E2E。第三轮采集的完整工作树快照为 466 个文件，摘要 `24793481179afa43ca8b82a9f3958d9e2316a8092c5902238efeacf60f8ad60d`；后续定点修复须有新的快照与检查记录，不能沿用此摘要声明新内容已测。

当前受控验收包括 **HTTPS Git、工作区内项目测试及隔离fixture固定SSH诊断专项**；Codex官方原生委派为显式opt-in并使用云端host OAuth。source31对r8同v19快照strict重评PASS；真实远端SUT、CI、Git写入未准入，Claude为placeholder，capability / Web必须显示各自范围。项目可以预先保存其他访问方式的资源，但保存配置不表示具备执行能力；不满足范围时拒绝准入。未支持的环境访问、Claude及其余可靠性验收仍属于待交付项。Web当前仅用`sessionStorage`保存同标签页的原key / 版本 / 摘要；关闭标签页后保全、跨标签页协调和持久恢复仍是待交付项，不把该增量认定为生产级提交账本。

SDK 探针、私有可执行临时目录前提、CLI 退出码和已证明 / 未证明范围详见 [DeepSeek Harness SDK 接入](DEEPSEEK_HARNESS_SDK.md)。

现有远端主机上一次性隔离 Docker 容器内的真实 bubblewrap 沙箱探针因无法创建非特权 user namespace 返回 **BLOCKED**；未放宽主机权限或改用普通进程绕过隔离。官方 runtime 在 4 GiB 地址空间限制下的无模型初始化通过，不能覆盖该阻塞。第三轮旧 Web 快照 148 项测试、TypeScript 和 production build 通过。最终所选后端 153 passed（39.61 秒），远端 Ruff 通过；第四轮最终 Web 152 项测试通过、0 失败（165.39 秒），TypeScript 与 production build 通过，回执已取回；真实资源配置与任务创建 POST / 固定读回已观察，1440px / 390px 资源和草稿截图已只读核验无阻塞或页面横向溢出；详情另记于实现状态，构建与草稿成功不等于完整执行验收。

Worker 领取前须验证已配置的专用 cgroup v2：有限的聚合 memory + swap ≤ 4 GiB、pids ≤ 256，并能核验当前 PID 归属；root-only的RLIMIT_AS=4GiB、native Codex为16GiB，均为每进程虚拟地址而非RSS / 聚合资源限制；当前实际cgroup仍精准2GiB / 0swap / 256pids。最终代码清单摘要与 SSH 中断后的浏览器已验收范围 / 带标签验收资源清理状态，统一记于[实现状态](CLOUD_IMPLEMENTATION_STATUS.md#当前证据与未完成项)。

### Web 授权与网络配置

新 Cloud Web BFF 使用服务端授权，浏览器不接收 Operator key。默认关闭；受控部署须显式设置 `HYPERTEST_CLOUD_WEB_ENABLED=true`，并配置私有 `HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE`（优先）或服务端 `HYPERTEST_CLOUD_WEB_OPERATOR_KEY`。原始秘密不进入参数、构建公共变量、浏览器存储或日志。

Cloud API 要求 HTTPS；配置独立的 **`HYPERTEST_CLOUD_API_ORIGIN`** 指向可信 HTTPS API 入口，优先于既有 `HYPERTEST_API_ORIGIN`，不改变后者服务的原 Web rewrites。现有容器默认 `http://api:8000` 不能满足该 Cloud HTTPS 契约，不能仅因提供了服务端 key 就放行。

代理场景须配置独立 `HYPERTEST_CLOUD_WEB_ORIGIN` 为浏览器可见的规范 http(s) origin，生产使用可信 HTTPS；它不同于 Cloud API origin。不信任客户端转发头建立站点身份，缺失 Origin / 跨站继续拒绝，错误配置闭锁。首次真实浏览器 POST 被旧同源判定以 403 拒绝且未写 API；新增 canonical origin 修正后 8 项 BFF 回归通过（3.43 秒），TypeScript / production build 再次通过；真实资源配置 POST200并显示已接受及完整读回。原第四轮 152 项通过不覆盖该后续变更，浏览器随后完成 DRAFT / NOT_RUN / version 1 创建与原输入固定读回，Worker 关闭、dispatch disabled；资源 / 草稿两页的 1440px / 390px 截图已核验。该浏览器草稿验收未覆盖dispatch / 模型执行；后续受控六步由独立API控制器 / Worker完成，其Task结果与Web覆盖分别登记。

仅在独立验收环境可显式启用既有 loopback 测试例外，并使 BFF / API 共享网络命名空间、经 `127.0.0.1` 连接，不发布新端口。此例外不扩大生产入口、VPN 白名单、TLS 或 SSH 规则。生产 Web 仍沿用既有访问边界；BFF 的同源写入检查、固定 route allowlist、原 key 对账及固定版本原件核验分别保留。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。固定 SSH 诊断仅在隔离 fixture 中实施；通用 SSH 仍不支持，不改变Project共享双模式；见[执行环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

## 实施顺序与固定边界

```text
P0 规范对齐与 SDK 兼容探针
  + TaskSyncCore 共享契约 / 库（与 Local L1 分别接入）
  → P1 项目资源、加密凭据、版本冻结与授权
  → P2 独立 Attempt / SDK 生命周期与委派收尾
  → P3 测试资产、项目框架执行与原始结果闭环
  → P4 两种模式的项目任务视图、故障验收与受控上线
```

SDK 指官方 **Harness Python SDK**，不是模型 HTTP API SDK；此云端路径不采用 ACP。不得先假设某个 SDK / `dsh` 版本可用，再根据假设实现恢复与完成逻辑。首版不引入自研 Agent Loop、Runner backend / 语言镜像矩阵、Graph DB、Kafka 或新通用测试引擎；测试继续调用各项目已有框架 / CI。

**共享前置能力：** 先固定 TaskSyncCore 契约与模式适配接口，由 Local L1 和 Cloud P2 / P3 复用兼容实现，分别验证后独立交付。核心不强制共同端点、Task enum、token、daemon 或全局锁；Local 保持完整 SessionTask 请求，Cloud 依其类型化操作确定合法合并、版本条件、ACK 与检查点读回范围，不普遍套用 Local 的 `expected_version + 1`。运行镜像只纳入所需共享库及云端适配器，不安装终端 Local 全包。

实施优先使用隔离 CI、受控测试环境与合成凭据。真实 SUT 试点须另有项目资源及执行授权，优先 staging，先完成分析、用例和可观察性设计，再运行用例。检查记录分别说明源码、SDK/runtime、迁移、环境、原始产物、结果与未覆盖边界；基础设施健康不等于测试通过。

隔离机制不能笼统标为未通过：默认一次性Docker容器的bubblewrap仍因非特权user namespace返回BLOCKED / NAMESPACE_SETUP_FAILED，该历史保留；专用非root systemd RootDirectory / 独立cgroup已通过生产namespace、官方SDK与真实任务。后续Code Mode有限AS4 / 8GiB触发SIGTRAP、16GiB成功的单变量对照支持V8虚拟地址兼容性修正，聚合物理2GiB / 0swap / 256pids及权限未变；这不涉及OAuth失效或放宽隔离。

## P0：规范对齐与 SDK 兼容探针

**依赖：** 本次四份基础规范、ADR-019 / ADR-021 接受；明确探针使用的隔离环境和 Provider 身份。

**交付：**

- 对齐白皮书 v1.8、架构 / TMP / 领域 v0.10 的身份、状态、字段、权限、幂等及结果语义。明确 Cloud / Local 产品模式及同项目共存；模式由不可变任务类型派生，旧 ADR-015 / ADR-016 `LOCAL / CLOUD` Run 执行位置不重解释。记录哪些约束是平台要求、哪些来自已验证 SDK 能力；ADR-020 本地触发改进独立推进，不能借此扩展当前 SDK 或本地权限。
- 固定 SDK、`dsh` runtime、Python、插件及 Codex CLI 的实际版本与锁文件 / 摘要；Claude Code 不在本次实现范围，保存兼容矩阵和可重复探针材料。此阶段先验证接口，不承诺生产版本或日期。
- 以小任务验证 SDK 启动 `dsh --profile sdk`、会话创建、提交、事件读取、最终结果、异常和 runtime 关闭；本次分别验证 DeepSeek 自己处理与真实 Codex 委派；Claude Code 仅占位，未来独立授权后才另行实现与验证。能力不可用要明确标为阻塞，不能用 stub 成功替代。
- 实测 `wait()`、idle、异步通知和外部 CLI 子代理的完成边界；检查进程树、委派终态、文件写入结束与原件回收。验证每 Attempt 独立 workspace / `dsh_home`，以及无单会话 cancel / close / 实时审批时的替代控制。
- 给出恢复能力表：能否通过 SDK 恢复准确会话、Provider 身份要求、丢失上下文时的失败路径；会话恢复不等于恢复 shell、浏览器或测试进程。
- 固定 TaskSyncCore 的共享语义及 CloudSyncAdapter 的目标身份、typed 操作、版本 / lease 条件、幂等回执和固定接受版本 / 检查点读回接口。语义进度复用 `SubmitCloudAssets` 的 `kind=REPORT` 非最终报告修订与 CloudAttempt 现有 checkpoint，不新增操作 / profile / enum / 表。明确 SDK 活动通知与正式语义进度的差别；结构化阶段产物才进入报告通道，不收集 transcript、隐藏推理或原始工具 payload。

**退出条件：** 两类委派及自行处理均有真实调用身份、终态、可读原件与清理证据；版本配对可重现。取消 / 超时能停止完整受管进程树，外部副作用边界有明确记录。探针不满足时留在 P0，不把 SDK 一轮结束解释为完整任务完成。

**风险与回退：** SDK 与 runtime 或插件接口漂移、凭据环境被清理、外部委派晚结束。保持云端入口关闭，修订配对版本或收窄明确展示的支持范围；保留探针失败和材料，不能静默改用 ACP 或伪装成现有 SessionTask 同步。

## P1：项目资源、加密凭据与冻结输入

**依赖：** P0 的版本与能力结论；凭据加密密钥 / Secret Store 的部署归属和恢复方式明确。

**交付：**

- 在同一 SUT 的共享 Project 下增加云端 SUT / 测试框架仓库、环境访问元数据及凭据引用；已有 Project 直接复用，不按 Cloud / Local 重建。支持同仓、独立仓库凭据、可选持久复用、轮换与撤销。元数据和 refs 可普通持久化，token / 私钥加密保存，密钥不与密文共同进入数据库备份；未配置云端资源不得阻塞 Local 同步。
- 增加 CloudTask 草稿、不可变下发快照、CloudAttempt 和操作回执的 additive schema / API / 审计；不重用 SessionTask 的 `(provider, session_id)` 身份或旧 TestRun / Binding。
- 实现 branch / SHA / MR 来源解析，`feat/*` 分支解析为 SHA，feature 需求标签关联可解析源码引用。Worker 侧完成版本解析 / 预检，API 引用已解析不可变结果；执行 dispatch 接受前冻结 SUT 与框架精确 SHA、MR base/head 和实际测试的 head 或 merge SHA、PRD 版本、目标 / 流程、环境引用、资源操作范围及预算。异步预检已受理不等于执行 dispatch 已接受。
- 预检实际仓库访问、固定提交可取、测试框架入口、环境连接、SSH host key 和 Provider 可用性；检查只产生预检观察，不冒充执行通过。实际部署身份按每次执行观察，未知时明确保存 UNKNOWN / 缺口；项目要求身份一致时受阻，不能用 Git SHA 补造环境证明。
- 密钥只通过授权的运行时通道供 Git helper / SSH agent / 工具使用；Agent 上下文仅有资源引用和范围。实现错误投影、SDK 事件与报告脱敏，防止秘密进入 Git URL、日志、补丁和附件。

**退出条件：** 隔离数据库验证约束与迁移、同仓 / 双仓、MR head / merge 区分、移动分支不改变冻结输入、旧版本冲突、重复 dispatch 与失答原 key 对账。凭据越项目使用、撤权后注入、SSH host-key 不符、秘密回显全部拒绝。用合成 canary secret 检查 API / 日志 / 提示词 / 产物；加密备份恢复后可核验解密权限，缺钥安全失败。

**风险与回退：** 凭据泄漏、源码与环境版本混淆、schema 双写。禁用新资源使用 / dispatch，撤销云端注入能力；保留 Task / Attempt / 回执 / 审计，恢复上一兼容应用版本。已接受历史不删表、不回填旧数据，泄漏按实际受影响凭据轮换，不能通过删日志冒称已解决。

## P2：独立 SDK 执行尝试与生命周期

**依赖：** P1 固定输入与授权；P0 已证明的 SDK 适配能力；TaskSyncCore 共享契约和可供 CloudSyncAdapter 接入的兼容实现。无需等待 Local 宿主适配或统一安装包交付。

**交付：**

- Python Worker 领取云端任务，每 Attempt 独立 runtime、workspace、`dsh_home`、凭据注入和进程组；固定冻结输入、版本与指挥官身份。API 请求只入账和排队，不在请求进程内启动 Harness。
- 建立租约与单调 fencing generation。每 Task 最多一个未终结 Attempt，含 `WAITING_INPUT` / `RECOVERY_REQUIRED`；stale Worker 和迟到委派产物不能绕过当前 owner 写入。
- Worker 执行任务预授权、网络 / 文件 / 工具 / 时间 / 费用限制。仅在提示词中要求遵守范围不算控制；无法由执行环境落实的权限不宣称受限。Provider 身份由平台预配，不逐个子代理向用户要 Git 或 SSH 登录。
- DeepSeek 主指挥官自行处理或委派 Codex，主链统一汇总产物；Claude Code 保持占位。子代理没有平台管理凭据，不各建 Task。保存委派身份、责任、终态与产物引用，等待所有相关委派收尾并回读原件后才完成。
- 由 CloudTaskReporter 经 CloudSyncAdapter / TaskSyncCore 在执行中报告明确阶段进度和产物检查点；子代理结构化贡献只汇入当前父 Attempt writer。此阶段实现最小 `SubmitCloudAssets` 的 `kind=REPORT` 原文 / 修订接受与读回：稳定 key 可按 Attempt 命名，完整原文包含阶段、里程碑、阻塞与已接受资产 refs。未来可选 `checkpoint_report_key` 只选择本批正式 REPORT key，在同一原 key / Task version / lease generation 事务内接受或复用 revision 并绑定 Attempt 既有 checkpoint；省略不变，不接受任意 ref / 隐式清除，回执与固定版本读回均核对绑定。P3 再扩展全部资产种类、二进制附件和框架轮次。非最终 REPORT 不自动改变状态 / reported result，也不冒充 `final_report_revision`，P2 的中途报告验收不依赖 P3；此字段属于未来 Cloud 契约，不增加 Local 字段。
- 报告通道使用 `cloud:work` 及当前 lease / fencing，不把 SDK 事件直接当 Task 状态，也不套用 Local 的 source、`task:sync` 或完整 snapshot。队列 / journal 按 Attempt 与来源隔离，旧 generation 不可因缓存意图或迟到 ACK 恢复写权；恢复后有权 writer 的新报告须按 Cloud 恢复契约准备，不能改写旧冻结请求。
- 对正式报告操作按领域契约冻结请求、key、版本 / generation 条件并保存精简对账材料；已发送 / 可能已发送的 UNKNOWN 仅查原 key，NOT_FOUND 不授权重 POST。ACK 后只续读该接受版本 / 检查点，上传或读回故障不改测试结果、不盲目重新执行测试。
- 实现持久 `WAITING_INPUT`，SDK 无实时审批时提前暂停在缺少权限的动作之前；回答只补充上下文或明确原上限内授权，不能修改冻结输入，超出原授权 / 预算上限或改变凭据版本须关联新 CloudTask。是否能恢复原会话使用 P0 结论，不能新建会话冒称原会话恢复。
- 超时 / 取消先 fence 写权，再终止 runtime 和全部受管后代，核验清理、停止心跳并保存原因；本地进程结束不证明远程 SSH / CI / 业务副作用停止。Worker 崩溃、孤儿子代理和未决外部操作进入 `RECOVERY_REQUIRED`。显式恢复原 Attempt 增加 generation，不恢复原 shell / 浏览器 / 测试进程。
- 同冻结输入的显式 rerun 追加新 Attempt，继续受原 Task 累计预算约束；变更输入创建关联新 CloudTask。终态 Task 由最新 Attempt 投影，旧 Attempt 的终态和结果不变；未终结 Attempt 未处理前禁止 rerun。

**退出条件：** 在两个隔离任务并发时互不读写对方状态 / 凭据；取消一个任务不影响另一个。验证超时、撤权、待答、Worker/runtime 故障、迟到子代理、陈旧 lease、显式恢复和 rerun。真实 SDK 执行未结束时已有一份明确阶段进度与正式资产检查点完成 ACK / 固定版读回；子代理贡献由当前 writer 归并且无独立平台凭据。覆盖报告失答 UNKNOWN、重连只查原 key、旧 lease 拒绝及取消时在途报告对账；进程 / 远端执行停止与同步接受分别核验。`wait()` 返回、root idle、进程 0 退出均不能越过外部委派终态 / 原件检查；失答或 UNKNOWN 阻止重复测试、重复 CI / push。

**风险与回退：** 孤儿进程、共享认证目录、陈旧 writer 和副作用重复。停发新任务，按 Attempt 逐一核对 / 终止已属本平台的进程；保留未知状态与工作区供对账。不得自动重启测试或切换 Provider，保留原同步与旧执行服务。

## P3：阶段资产、项目框架与结果闭环

**依赖：** P2 可监督的运行、CloudTaskReporter / CloudSyncAdapter 与单 writer；可核验的原件上传 / 读取路径及 TaskSyncCore 兼容版本。

**交付：**

- 版本化保存分析、设计、用例、代码资产、执行轮次、用例 actual / reported result、原始报告和日志；关联 CloudTask / Attempt、冻结输入、实际测试代码和环境出处。
- 扩展 P2 的非最终进度 REPORT / checkpoint 闭环：分析、设计、用例、实现和每轮执行分别形成明确语义进度与正式资产清单，运行中即可提交，不等最终 SDK 文本；完整 / 局部意图按现有 Cloud typed 操作适配并保留已有失败、版本与来源，不因缺省字段清除资产。SDK 心跳、工具成功、子代理回答只触发核对，不能补造阶段完成或 PASS；`final_report_revision` 仍须明确指定并满足领域 §51.6 收尾条件。
- 测试代码写入测试框架仓库工作区，保持原框架 / fixtures / 配置习惯；保存可读 commit 或完整 patch / untracked 文件原件。push / MR 创建须任务明确授权，并有独立操作身份和失答对账；首版可用 patch 完成交付。
- 由 Harness 调用项目已有测试入口或获授权 CI，记录调用来源、开始 / 结束、退出、原始框架结果、源码 / 测试资产 / 环境身份。框架执行、CI 提交和状态查询分别记录，不重新构建测试调度引擎。
- 上传附件原字节，绑定摘要和长度，持久接受后重新读取核验；URI、hash、摘要和“上传成功”自述均不能替代原件读回。上传失败 / 缺片 / 超限保留缺口并阻止宣称交付完整。
- 支持第 5、6 步迭代，失败、setup 错误、诊断、补充代码、重跑及报告修订各自保留。区分任务工作完成、reported result 和 legacy 正式质量判定；既有 Gate 不接受这些记录自动成为 VERIFIED / RELEASE_READY。

**退出条件：** 在至少一个真实已有框架的受控项目中，经完整六步产生可追溯分析 / 设计 / 用例 / 代码 / 实际运行 / 原报告，并在长任务中查看已确认的中途检查点。正例保留框架 PASS 原件；负例含断言 FAIL 与环境 ERROR / BLOCKED，后续修订不覆盖原失败；日志 / 报告矛盾明确阻塞。双仓版本、代码改动、全部已提交用例和执行轮次按接受版本 / 检查点完整读回，分页中断后继续原版，不与后续修订混读。验证报告接受、附件原字节核验、测试结果与任务终态分别成立；平台记录不以仅保存 SDK 最终文本代替。

**风险与回退：** 报告解析误标、实际测试树不完整、被测部署身份未知、产物遗漏或秘密夹带。禁用相应执行 / 上传入口并保存缺口；完整原件和历史不得删改。新来源未经单独设计与验收，不能借用 legacy Gate 信任。

## P4：产品入口、故障验收与受控上线

**依赖：** P1–P3 退出条件通过；隔离迁移与恢复演练完成，正式发布另获授权。

**交付：**

- 云端 Web / API 按六步提供 Project 创建 / 复用、资源 / 凭据管理、任务输入与冻结预览、下发、进度 / 预算 / 委派、阶段产物、每轮结果和取消 / 待答 / 恢复，执行留在云端 Worker。采用 profile 明确的新云端接口，保留 Local 的 `hypertest_sync_task` / `hypertest_get_task` MCP 管理入口，不用同步工具触发云端执行。
- 同一 Project 任务列表默认并列显示 CloudTask 与 SessionTask，提供 Cloud / Local 标签、来源与模式筛选；`product_mode=CLOUD|LOCAL` 由 `task_kind=CLOUD_TASK|SESSION_TASK` 派生，统一只读查询按 `(task_kind, task_id)` 区分身份。详情保留两套状态、结果与合法操作；不新增可变模式列、不把 Project 变成模式开关、不重标旧任务。字段和查询契约按领域 §51 / TMP §46 实施。
- 展示资源授权范围、凭据可用性而非秘密，任务进度与 reported result 分开，区分预检、正在执行、等待输入、待恢复、失败、取消和工作完成。无法部署或未支持的能力不显示为可运行选项。
- 完成新接口幂等 / expected-version、撤权、跨项目、未决写只读原 key、网络失答、重复点击、多窗口、上传中断、进程取消 / 清理和恢复的故障验收；补充同一 Project 两类任务的并列 / 筛选 / 分页 / 详情身份与权限隔离，Local scope 不获得云端 dispatch 或凭据访问，Cloud 提交不覆写 SessionTask。
- 在同一 Project 并行推进 Local 正式资产同步与 Cloud 阶段报告，验证各自固定兼容的 TaskSyncCore / adapter 仍分别路由身份、授权、版本、账本与结果；一侧 UNKNOWN / 读回中断 / 陈旧 writer 不污染或阻塞另一类任务。取消 Cloud 时先 fence 在途写入，原 key 读回对账、未发送意图保留和远端 CI / SSH / 业务执行对账分别留证，不以“同步结束”推定测试已停止。
- 与本地计划核对独立开关：未启用或关闭 Hooks 时现有 Codex MCP 与待对账账本保持，关闭 Cloud 时本地同步继续。已发布的 Local Hooks / MCP 和真实矩阵保留原资格；本次在混合 Project 中验证 Cloud 关闭或失败时 Local 写入 / 历史仍独立，不重跑三宿主安装或模型。
- 发布包含 additive migration、兼容应用版本、SDK/runtime/插件配对、Secret Store 配置、feature flag、并发 / 费用限制和保留策略；准备数据库与产物成对备份、密钥独立恢复及不删除任务历史的回退步骤。
- 小范围启用指定项目和受控环境，观察资源越界、孤儿进程、凭据泄漏、回执未知、原件缺失、结果矛盾与既有同步回归；达到任一发布停止条件即停发新云端任务并处理已有 Attempt。

**退出条件：** 用户可从云端 Web 完成已授权的完整六步与一次失败诊断 / 迭代，原件完整可读，所有委派已收尾，取消 / 待答 / 恢复可操作且有证据。同一 Project 同时存在 CloudTask 和本地 Codex SessionTask，默认全部、模式筛选、分页与各自详情均可核验；Local MCP 同步单独真实调用验证。关闭云端 dispatch / 停止云端运行组件后，Local 同步、原文读回和两类历史读取继续可用，云端资源缺失不阻塞 Local。部署身份、当前能力和未覆盖场景登记；不能将本轮文档评审或旧生产成绩算作新模式验收。

**风险与回退：** 发布破坏原管理链路、缺失加密密钥、版本不兼容或费用失控。立即关闭云端 dispatch，停止 / 对账活动 Attempt，保留只读记录；回退应用仍需读取新增历史，数据库不做破坏性降级，旧 SessionTask 同步继续服务。网络白名单、SSH 管理访问与已有账号不得随本功能顺带变更。

## 每阶段的兼容验收与证据要求

每阶段开发变更都必须回归 ADR-018；仅有 P0 文档修订时做规范 / 链接静态检查，不能声称代码回归已通过。实际回归使用隔离环境，现有重点测试包括 `tests/test_session_tasks.py`、`tests/test_session_task_mcp.py`、`tests/test_session_task_pages.py`，并补足受影响链路；命令与范围由实施时变更决定，本计划不要求在本机运行 SUT、pytest、lint、build 或浏览器。

| 保护项 | 必须证明 |
| --- | --- |
| 真实会话身份 | 仍一会话一 SessionTask；CloudTask / Attempt 不写入或伪造 `session_id`；共享 Project 不共享执行授权 |
| 同项目两种模式 | 同一 Project 同时保存 CloudTask 与 SessionTask；列表默认全部、Cloud / Local 筛选 / 分页与详情保持 `(task_kind, task_id)` 身份；切换筛选不触发执行或跨模式改写，旧任务来源不变 |
| 原文与历史 | 计划、用例和原始 Markdown 报告写入并完整分页读回；版本与 reported result 保留，FAIL 不被后续 PASS 删除 |
| 幂等与并发 | 原 key 同请求复用，异请求冲突；expected-version 阻止旧客户端覆盖，云端引入不改变旧回执摘要 / 唯一身份 |
| 未决传输 | 同步 UNKNOWN 仅 GET 原 key，NOT_FOUND 不自动重 POST / 换 key / 新建任务；与测试 result.UNKNOWN 分开 |
| 共享同步核心 | LocalSyncAdapter 与 CloudSyncAdapter 各自固定兼容 TaskSyncCore；各域合法操作、ACK / 固定接受版本或检查点读回不混用，Cloud 无需本地 bootstrap |
| 云端中途报告 | SDK 长任务仍运行时确认结构化进度 / 正式资产检查点；子代理仅归并父 Attempt；陈旧 lease、取消在途同步及远端执行分别对账 |
| 权限与无执行副作用 | 旧 `task:sync` 撤权 / 跨项目拒绝，写读不创建 Job / Harness / Runner / Gate，不要求凭据、执行 binding 或源码传输 |
| 独立可用性 | 未配置云端资源、关闭云端 dispatch 或停止云端运行组件时 Local 同步和原文读回继续可用，两类已保存历史仍可读；同步授权不派生云端执行 / 凭据权限 |
| Local 触发兼容 | ADR-020 Hooks 独立启停；未启用时保留现有 Codex MCP，停用不删除私有 pending / 原 key 账本或历史。Hooks / MCP 共用唯一 writer，Cloud 操作不新增 Local 写入者；未交付能力明确标为未观察，不替代实际验收 |
| 历史模式 | 旧 TestRun / NativeTestRun、两种受管 Harness、交互绑定、Evidence / FINAL Verdict、授权和访问边界不被回填、迁移重解释或删除 |

每阶段记录实现 commit / 工作树身份、运行环境、实际检查命令、原始回执与产物位置、通过 / 失败 / 阻塞 / 未观察范围及剩余风险。计划完成比例、模型摘要和旧验收数字均不替代这些记录。

## 官方 SDK 参考与规范归属

- [Harness Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)：Python 调用与 runtime 关系，具体配对版本在 P0 固定。
- [SDK 协议与限制](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)：当前控制能力边界须在配对版本中复核。
- [SDK Client 完成语义](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/client/README.md)：等待与通知不能替代外部 Codex / Claude 子代理终态和原件检查。

字段 / 关系 / 状态以[领域规范](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)为准，任务 / 事件 / 回传以[TMP](protocol/TEST_MISSION_PROTOCOL.md)为准，服务与运行边界以[技术架构](architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)为准，产品意图以[白皮书](foundation/HYPERTEST_WHITEPAPER.md)为准。实施偏离这些规则时，须先明确新的 ADR 并同步规范，不能仅在代码里决定。
