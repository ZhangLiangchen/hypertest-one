# Cloud Git 集成与测试服务器交付记录（2026-10-23）

**部署状态：`DEPLOYED_AVAILABLE_FOR_USER`；用户验收：`PENDING / USER_OWNED`。** C4 API / Worker及后续6d49 Web已部署，可从[既有受控入口](https://155.138.206.106:8080)操作。功能验收由用户执行；除非用户明确要求，不擅自开展验收。必要构建、组件回归、doctor、迁移、基础健康及部署路由检查分别登记，不称为用户验收。本轮未创建用户验收业务数据、未启动新的模型或SUT执行；组件测试中的合成fixtures按各自回归范围记录。

## 交付身份与当前证据

服务器为用户单人专用测试环境。交付沿已 push 的 Git 完整 SHA 构建，不使用未提交工作树替代正式来源；默认流程见[服务器操作](SERVER_OPERATIONS.md#当前环境与默认交付流程)。下表依据本轮公开部署回执登记，不额外执行服务 / 业务请求。

| 项目 | 当前事实 | 证明范围 |
| --- | --- | --- |
| C4 Git | `d065ae2e27b6ff37c87a8ebe0c549a96dda45a73` | API / Worker交付身份；Web-only后续身份单列 |
| C4 Git tree | `2675f5af9c46a33d00a7e85bb936aa12dea59cd0`，clean=true | C4部署源码树身份，不替代后续Web物理Git |
| Worker image | `sha256:ff1130be30aeced1e30bebe3132ac1a96351b9a2bc344b4f4e61164d7c641a77` | 实际构建及 rootfs 导出成功，不代表模型 / Task 执行 |
| Worker 启动 doctor | `ADMITTED`；Codex required / enabled，云端 OAuth 与固定 payload 检查通过 | 启动准入，不是上游模型调用、原生委派或 SUT 通过 |
| 数据库 | 当前库已备份，`0023_project_task_management` 向前升级至 `0026_cloud_ssh_operations` | 当前库迁移；本轮没有restore演练 |
| API / Web / nginx | guarded stack 五角色健康；BFF setup / capabilities / task 目录读取均 200 | 部署检查；原legacy Worker / PostgreSQL也保持healthy |
| Web → Cloud API | 实际 UID 1000 经 UDS、TLS 1.3、CA / IP SAN 校验后 GET 200 | 仅部署路由检查；保留既有 wrong-SAN 拒绝原件，不追加验收 |
| 当前数据保全 | 15 Projects / 14 SessionTasks / 9 管理修订计数一致；Cloud 待执行 Task / Attempt / resolution 为 0 | 本次只读计数观察，不替代逐项业务验收 |
| 常驻 Cloud Worker | `hypertest-cloud-worker.service` active / running、`IDLE_READY`，未自动enable | Codex=true / SSH=false、cap0 / NnP、2 GiB / 0 swap / 256 pids；pending 前后 0，无 SDK / model 子进程，不代表新 Task 已执行 |
| 本轮用户验收业务数据 / 新模型与SUT | 未创建用户验收业务数据，未启动新的模型或SUT执行 | 组件回归的合成fixtures不属于用户验收业务数据；不复用旧fixture成绩作为本轮新执行证据 |
| Web-only步骤显示修正 | 物理Git `6d496890013614de5f216a9e672b4e915fd66550` 已部署，Web healthy / root 200 / Cloud setup 200、configured=true | 仅Web后续更新；API / Worker / schema不变，用户验收未执行 |

API image仍为 `sha256:2e20377e8af61bc5ebe42666ecb68475c26ff48c0d7b27be64f094e058f81405`。C4首次部署时，API与当时Web image `sha256:7fcae540c62e8c3d286cdd1be0ef7862c52f91691325efdff43c409181e63a70`的物理构建Git均为C3 `9b45ae994c2cd246d0c2ff1ca66af771afad1615`；对C4确认应用输入闭包零差后物理复用，未重建或重贴身份。此后仅Web替换为下节6d49新镜像，不回填为C4构建产物。原legacy Worker image仍为 `sha256:7796433173907d7b4d3aa62f55a24dedc49af8ac91f959b3b1999a13a1c47f60`，不要与独立Cloud Worker混同。

原Bridge active，既有origin / 端口 / VPN未变；旧release、备份和UNKNOWN记录保留。UDS为101:101 / 0666，父目录101:1000 / 0710，Web UID1000经该受限目录使用socket；未新增公开监听或放宽TLS校验。代码开关默认仍false，服务器当前显式启用Cloud / Codex，固定SSH关闭。

部署原件为 `/var/lib/hypertest-cloud/delivery/20261023-fe4c4348/deployment-c4.json`，SHA256 `41bc5d77428202d44da09be6d30e3b8a52821470d617ad3b02de5a221459d590`；公开投影SHA256 `47c089149134885707e6fc54a5e46a304a703ff8d9062f59d3abda0512f86117`，类型为 `DEPLOYMENT_CHECKS_NOT_USER_ACCEPTANCE`。迁移前0023备份1533663字节，SHA256 `d34563d5ea7034c2ac8dcb05daec4f33d496765ab4bd93201a18f6c5df65c8c6`；备份 / 当前只读计数一致，未做restore测试。

正式迁移链为 `0023_project_task_management → 0024_local_task_binding → 0025_cloud_tasks → 0026_cloud_ssh_operations`。旧隔离验收的 `0023_cloud_tasks` / `0024_cloud_ssh_operations`、source pins、接受版本与历史结果不重新编号或改写。

## Web-only后续部署

Cloud详情对null或早期FAILED / CANCELLED状态误勾Harness步骤的修正commit为 `3419c660310cf1c459b00b847150b974517ff7b8`。合入后从干净Git `6d496890013614de5f216a9e672b4e915fd66550` / tree `874d110be36fc64cd4f3f813050548a3a947d3e7` 构建，cloud-client单文件回归 **17 passed / 0 failed / 0 skipped**，正式Web build exit0。

实际新Web image为 `sha256:da14c5738094488683df8205a3fad53d3a19fab4567f1b24b5fb17743652e0aa`；仅替换Web容器及其公开image配置，部署后Web healthy、root HTTP200，Cloud setup HTTP200 / configured=true。API / legacy Worker / PostgreSQL / nginx容器ID和image、Cloud Worker PID均前后一致；没有再次迁移，schema保持0026。未创建用户验收业务数据、未启动新的模型或SUT执行。

补充原件为 `/var/lib/hypertest-cloud/delivery/20261023-fe4c4348/web-followup-6d496890/deployment-web-supplement.json`，SHA256 `a1345bdb388145a916019d76e428bd8f5dd8cbcdc9a727b820af53558b76c6f3`。该部署检查与下面早期guide loader的17项分别记录，不合计，也不称用户验收通过。

## 本轮失败与修订保留

| 检查记录 | 实际结果 | 边界 |
| --- | --- | --- |
| C1 首轮后端 | 768 passed / 6 skipped / 1 failed | 取消 DRAFT 失败保留；跳过不计通过 |
| 首轮 Web | 201 passed / 1 failed | 原失败保留，不重标为后续成绩 |
| 修复后针对性组件回归 | 76 passed | 仅相应修复范围，不表示首轮全量重跑 |
| guide loader 所选复验 | 17 passed | 不证明真实 native bind 或本轮用户验收 |
| C4 ops 所选复验 | 42 passed | 文件、context、权限与失败保留等工具契约；不运行模型 / SUT |
| 6d49 Web-only cloud-client所选复验 | 17 passed / 0 failed / 0 skipped | 不与上方guide loader的17项合并；Web build exit0，基础健康另记 |

上述轮次由本轮主控分别登记，保持各自scope，不合计为一个总通过数；当前各组件部署身份由C4回执及6d49 Web补充回执分别固定。

- C1 新隔离库升级至 `0026` 成功；首轮后端结果为 **768 passed / 6 skipped / 1 failed**。失败发生于取消未下发 DRAFT：解析查询先自动 flush `CANCELLED`，随后时钟查询又 flush 版本，数据库正确拒绝终态后修改。六个跳过实例来自该检查镜像缺少 Docker CLI，不计为通过。
- `a69a0660748c65091bb385c7578e59d2bb02f9e8` 将取消状态、版本与更新时间合并到一次 flush，保留终态触发器、原 key 回执与旧接受版本。该修订经C3 `9b45ae994c2cd246d0c2ff1ca66af771afad1615` 合入，针对性复验76项通过，不重标C1原结果。guide loader的测试适配另以17项所选复验记录，不称真实native bind通过。
- 首次实际 Worker 构建失败：服务器 legacy Docker builder 未采用 Dockerfile-specific ignore，导致 wheel-pair lock 被 API 根 ignore 排除；原失败 release 保留，当时没有成功 image / rootfs。`umask 077` 下运行根目录权限不足也纳入修正。
- C2的lock纳入修正经 `e0e63db2108a414a2624924b0b5753e360d5ad5f` 合入，但首次实际legacy builder仍失败，原结果保留。C4的 `c28bcd3cfbe07f089fce2e047ebe3aed926a49b5` 增加独立最小 Worker context，以 Worker ignore 作为 context 根 `.dockerignore`，保留完整 Git source 原件；source / context / rootfs 根目录显式为0755，外层release保持0700。42项ops所选复验通过，随后从C4合并Git在新release叶实际构建 / 导出成功；两种事实分别记录。

各轮计数分别保留，不把所选回归相加称为一次全量通过。只对本次实际验证的 Git / image / scope 形成结论。

## 既有严格 fixture 验收继续保留

已有 r6 严格直接原件验收，以及 source30 Worker / source29 helper 的 r8 canonical 固定 SSH 专项，保持各自原 Task / Attempt / 接受版本。source31 对同一 r8 v19 固定快照的 `SNAPSHOT_REASSESSMENT` strict PASS 和独立只读重放 19 项通过继续保留；快照重评没有新的 current GET、模型 / SSH / SUT 执行或 canonical 写入。

旧 source30 NON_PASS、r7 UNKNOWN / HELD、其他失败原件与原接受结果均保留。Codex 贡献来源仍为 official-plugin-runtime-reported，不升级为独立 writer 证明、legacy VERIFIED 或 Gate。完整原件 / SHA / 轮次见[实现状态](CLOUD_IMPLEMENTATION_STATUS.md)，不迁移为 C4 常驻部署的新执行成绩。

## 部署完成与用户验收边界

上述API / Web / nginx / Cloud Worker部署身份、schema、基础健康及现有入口路由已记录。配置值、doctor、进程存活、每Attempt执行与用户验收是不同事实。本轮不为交付追加用户功能验收、验收用业务 / 凭据fixture或模型执行；必要组件回归可使用合成fixtures。用户可自行操作，验收保持 `PENDING / USER_OWNED`。6d49 Web-only显示修正的Git / 构建 / 基础健康已单独记录，不回填为C4物理Web镜像。

统一创建入口与Local绑定的交付由[独立管理记录](UNIFIED_TASK_CREATION_DELIVERY_20261023.md)拥有。本记录不凭页面构建或Cloud Ready宣称真实native bind已通过，也不改写已发布Local包及其验收历史。

## 保持的能力边界

Cloud / Local 共享 Project，身份、权限、账本与任务生命周期分别保持；API 仅运行管理与加密凭据处理，官方 SDK / 模型执行留在独立 Worker。部署配置值与实现支持不代替实际准入或执行证明。

Claude Code 继续占位；一般远端 shell、通用 SUT Web / HTTPS / SSH / CI 尚未因此验收或开放。固定 SSH 诊断仍是显式 opt-in、精确目标 / 动作的受控 profile，真实业务环境与取消 / 失联矩阵需各自证明。

XBlock staging 需要 SSH / 服务器日志时走用户 Mac 经 Workbench 的 Local 模式，166dev 内网自建链仅 Local；纯 Web / API 的 Cloud 访问仍待独立实现及验收。不复制本机登录或环境秘密，不扩大网络 / 工具授权。详见[环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。
