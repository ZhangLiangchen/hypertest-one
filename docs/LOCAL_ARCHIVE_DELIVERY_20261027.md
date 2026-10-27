# Local 显式 CLI 与 Skill 归档交付（2026-10-27）

更新：2026-10-27（UTC）。本轮按用户确认的 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)实施本地 Agent 后置归档，替换测试过程中的 MCP/Hooks 同步。开发任务见[重构计划](LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)，操作说明见[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。

**实现、测试服务器部署和 cli-v0.1.0 公开发行已完成；USER_OWNED 功能验收未执行。部署健康、自测与实际用户测试分别记录。**

## 交付状态

| 维度 | 本轮记录 |
| --- | --- |
| 源码实现 | 已完成归档 API/模型、配对授权、统一 CLI、显式 Skill、PC Web、旧接入退休及只读恢复 |
| 固定 Git 来源 | 首片实现/CLI 源码 `d02ab1dd893200eb2eee398d795f9b96a41ab768` 已提交并推送；API/Web 构建来源另记 |
| API/Web 部署 | 2026-10-27 04:21 UTC 前，已从推送并 fetch 固定的 `1512d11f99c5e500e4fc56c685410ffa9e533530` 构建部署；新入口与旧写退休已生效 |
| Schema | 业务库已从0029依次向前应用0030/0031，当前 `0031_cli_authorization`；旧业务与历史未转换 |
| CLI/Skill 发行 | [cli-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0) 已公开；四资产公开下载摘要一致，Linux/Python 3.13 安装/版本/Skill 安装冒烟通过 |
| USER_OWNED | 未执行。真实本地安装、网页授权、归档体验及业务结果由用户验收 |

API/Web 和固定 ops 来源采用本轮新身份；独立 Cloud Worker 与 legacy Worker 源码/镜像保持原身份。旧 `local-v*`、`mcp-v*` 资产及其验收记录保持原义。

## 已实现的用户流程

1. 本地 Agent 使用项目现有工具完成测试，保留计划、用例和原始报告。测试阶段不需要平台 Task、Hooks、MCP、SessionStart 或常驻同步进程。
2. 用户在全局「CLI 授权」页查看安装指导并复制 `hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default`。CLI 发起短时配对，网页核对短码后一次批准既有上传身份、明确的项目、归档权限和期限。
3. CLI 核验固定授权并保存用户级 profile 后退出，可跨目录和会话复用。全局安装不代表全部项目授权，命令和 Skill 不包含 token 或 Operator key。
4. Web 创建或选择归档任务，按需添加子任务，复制明确的 `$hypertest-archive` 指令。每次上传必填 Project ID、Task ID，Subtask ID 可选；省略时使用 Task 根空间，不补造默认子任务。
5. Skill 整理获准产物清单，CLI 读取文件、冻结请求并单次提交，核对回执及完整固定版本后返回任务链接。未知结果只查询原 key；测试 reported result 不由上传成功改写。
6. Web 查看原文、结构化用例、来源声明、资产修订、提交与管理历史，并显式发布任务整体汇总。汇总固定根及所选子任务的版本和资产引用，展示未纳入与未完成项。

首片支持 UTF-8 PLAN/REPORT 与结构化 CASE，单请求 2 MiB，文本、条数与步骤均受协议上限约束；超限或不支持的二进制产物整批拒绝，不隐式截断、拆分或声称本地路径已上传。截图、视频、压缩包的二进制归档仍不在本片范围。

## 实现范围与边界

| 层 | 已实现内容与主要源码 |
| --- | --- |
| 领域与 API | 独立 LocalArchiveTask/Subtask/Submission/AssetRevision/Publication，根与子任务分别推进 archive_version；任务管理 version、上传 owner、复合归属与只追加修订。见[领域模型](../src/hypertest/domain/local_archive.py)、[归档服务](../src/hypertest/application/local_archive.py)、[接口](../src/hypertest/api/archive_routes.py) |
| CLI 配对授权 | CREATE/APPROVE/REDEEM 分阶段固定 key/正文；私有 verifier、预存 credential、项目 allowlist、独立 archive scopes、授权期限、撤销与原 key 回执。见[授权服务](../src/hypertest/application/cli_authorization.py)、[接口](../src/hypertest/api/cli_authorization_routes.py) |
| CLI 与传输 | `auth`、`profile`、`doctor`、`archive`、`status`、`reconcile`、`skill install`；严格 HTTPS、用户私有配置、TaskSyncCore/冻结账本、完整读回、JSON 与明确退出码。见[统一入口](../src/hypertest/cli/__main__.py)、[归档实现](../src/hypertest/cli/archive.py) |
| 显式 Skill | `hypertest-archive` 随 CLI 分发；Codex 关闭隐式调用，支持用户级安装；读取明确文件范围、不从目录推断目标、不扫描聊天、不启动测试、不自动重试 UNKNOWN。见[Skill](../skills/hypertest-archive/SKILL.md) |
| PC Web | 全局 `/cli-authorizations`，任务 `/archives/{taskId}?projectId={projectId}`；归档列表/创建、子任务、上传身份、固定版本原件、历史、显式汇总和指令复制。新 Local 入口不再引导 native 绑定或 Hooks。见[授权页](../web/app/cli-authorizations/page.tsx)、[归档详情](../web/app/archives/[taskId]/page.tsx) |
| Web 权限与恢复 | 独立归档开关、同源 JSON/Origin 检查、服务端 Operator key、现有严格 TLS/CA/UDS；浏览器只管理，不冒充上传者。新增独立 IndexedDB archive/auth stores，保留旧 stores、并发预留和原 key 恢复。见[BFF](../web/lib/archive-server.ts)、[操作账本](../web/lib/archive-operation.ts) |
| 迁移与容器 | 0030/0031 仅新增表与相关独立 scope 约束；旧业务表/历史不转换。新增独立归档 Web overlay 与路由，不启用 Cloud 执行或扩权。见[0030](../alembic/versions/0030_local_archive.py)、[0031](../alembic/versions/0031_cli_authorization.py)、[Compose overlay](../ops/container/compose.archive.yml) |
| 独立发行 | 固定完整 Git、干净 checkout 构建无需第三方依赖的 zipapp；安装器校验产物摘要、保留受管安装身份与冲突。页面在真实发行元数据填入后才提供固定链接和校验命令。见[构建脚本](../scripts/build-cli-release.py)、[安装器](../scripts/install-cli-release.py)、[页面发行元数据](../web/lib/cli-release.ts) |

CLI zipapp 的运行条件为 Linux/macOS、Python 3.12 或更高版本；新包不包含 MCP server、Hooks、native bridge、daemon 或 Cloud SDK。此运行条件不等于各宿主/操作系统真实功能验收已通过。Skill 全局自动安装首片明确支持 Codex；其他宿主不从通用 CLI 可用性推定其技能安装已验收。

上传者由有效授权确定；原 provider/session/测试时间等仅是逐资产来源声明，不被展示为独立核验的 native 身份。`task:sync`、`cloud:work`、Memory scope 不自动获得 `archive:read/write`。接受后的任务 owner 不可被另一个上传者替换；无效或跨 Task 的子任务明确拒绝，不回退根空间。

任务整体状态/结果由明确 Publication 更新。根空间归档不改 Task 整体结果，子任务状态更新须明确出现；归档成功、Task 完成、reported PASS 与独立 VERIFIED/RELEASE_READY 分别保持原语义。

## 旧接入退休与历史保全

代码默认关闭旧 Local 会话新写准入，明确退休 CREATE/BIND/SYNC/协作等新意图；原已接受 key 和固定版本仍按原合同可读。旧 Hook 入口退休后不再读取产物或连接同步服务，新 MCP Local 写入口返回退休说明。保留其他 profile/独立 Memory 或 Cloud 仍需的共享库与历史解释，不按文件名批量删除共享实现。

`hypertest legacy retire --directory ... --host ...` 按既有安装收据精确清理自有 MCP、Hook、bridge 和受管 Skill 配置；配置漂移时拒绝并保留原件。停止自有旧 runtime 前验证身份，不按 PID 或进程名批量终止。没有在本轮自测中操作用户真实本地宿主配置。

`hypertest legacy reconcile --config ... --request-id ...` 对显式选择的既有 SYNC/BIND/协作账本只执行原 key GET 和固定版读回，不启动 MCP/Hooks/daemon、不重放 POST、不修改旧 journal。旧 compact 记录缺少原完整正文时只报告 `LEGACY_ACCEPTED_READBACK`，不宣称已对照原请求完成恢复。旧 Web CREATE 请求继续由浏览器原 IndexedDB 提供只读恢复入口，CLI 不索取 Operator key 代办。

凭据、CA、源文件、冻结请求、未决 key、旧任务/报告/回执、原 FAIL/UNKNOWN、其他插件和用户自定义配置均保留。用户需要在自己的安装位置显式执行迁移；服务端切换不能证明每台本地机器都已清理旧配置。

## 本轮验证

以下分别记录各模块最终定向检查，不将重跑或包含关系重复累加为总测试成绩。测试数据均为开发用合成材料；ASGI 集成使用专用 test DB，不写业务验收项目、授权或任务。

| 检查范围 | 结果 | 主要边界 |
| --- | --- | --- |
| 归档后端 | 12 passed | 根/子任务、跨目标与授权拒绝、版本、same-key/UNCHANGED、原文与历史 |
| 旧客户端退休/恢复 | 13 passed | 精确配置清理、其他配置保留、漂移拒绝、runtime 身份、原 key 只读与旧原件 |
| CLI | 17 passed | 文件与 manifest、私有状态、发送前冻结、UNKNOWN/固定读回、Skill 安装 |
| CLI → ASGI API 集成 | 2 passed | 合成配对与明确批准后归档至 Task 根空间、指定 Subtask 的实际接口合同 |
| CLI 授权后端 | 6 passed | 凭据/proof 边界、明确项目授权、分阶段 key、拒绝及恢复 |
| 服务端退休 | 2 passed | 旧 accepted receipts 可读、新意图拒绝、退休 Hook 无读取/联网 |
| 受影响旧接入合同 | 95 passed + 8 passed（绑定模块只选择 MCP 相关项，其余 39 项未运行） | 历史安装/协作 fixture 显式启用兼容；当前 MCP 新写退休、零 POST、原 key 查询和底层 caller 拒绝仍受检查 |
| Web 定向组合 | 110 passed | 新授权/归档页面与 BFF、原 key/持久账本、受影响创建/历史，以及共享 HTTPS 隔离 |
| 相关 ops 检查 | 26 passed（既有 Cloud/Memory 25 项 + 新归档独立传输 1 项） | 验证 archive-only 暴露受限 Web 传输且不启用 Cloud/Memory，以及既有生成/配置契约；不重复运行或累计同一结果 |
| Web 类型与静态检查 | 通过 | TypeScript、相关差异检查；设计机械检查无告警 |

跨组件核对发现 Web 分页读回最初把最后一页 `next_offset` 当作数值。已按实际 API/CLI 合同修正为最后一页必须 `null`，未完成页才核连续数值 offset，同时核总 Unicode 字符数、目标和固定版本；更新原 fixture 后，相关 3 项 BFF 检查通过，已包含于上述 Web 范围，不另计。

这些结果不等于全量后端/Web 回归、真实模型/SUT 测试、全部宿主矩阵或 USER_OWNED 功能验收。浏览器安装/网页操作的用户验收尚未执行。

## 部署与发行记录

服务器复用已有干净 Git checkout，从已推送历史 fetch 并固定提交；仅构建 API/Web，沿用容器网络守卫启动。构建成功包含 Web 类型检查与新页面生成，无本地/服务器重复完整回归。

- API/Web 与固定 ops 完整 Git SHA：`1512d11f99c5e500e4fc56c685410ffa9e533530`。实现源及 CLI 包来源为前序 `d02ab1dd893200eb2eee398d795f9b96a41ab768`，后两提交接入真实发行元数据并更新对应测试。
- API image：`sha256:65c0a2be39fd5bea2ed05efb99365260b774055e98c7d3c42b7e9d94509f27dc`。
- Web image：`sha256:aa45c064d8a64fc9c7fe3b8dbb1600963b804963a537c0714bb2b7fc8d9759cd`。
- schema：`0031_cli_authorization`，迁移前已保存逻辑 DB 备份 `/opt/hypertest/backups/archive-20261027-1512d11/database.dump`；未重置业务库、删数据卷或运行业务 fixtures。
- `HYPERTEST_ARCHIVE_WEB=enabled`；新归档 BFF 使用既有受保护 TLS/CA/Unix socket。运行配置未启用旧 Local 写开关；在线 capabilities 确认 retired 且不再展示旧 Local 新写工具。新私有路由外的公开 HTTPS listener/白名单保留原字节，包括现有手工 allow 条目。
- nginx 配置语法通过；守卫启动后五容器 healthy，API health 与 `/cli-authorizations` 均 HTTP 200；归档/授权 setup 为 configured；新 Web BFF 经 TLS socket、Operator 边界到 API 成功读取 typed actor list（只读，无新授权/任务）。
- `cli-v0.1.0` 源码：`d02ab1dd893200eb2eee398d795f9b96a41ab768`；独立发行不修改旧 local/mcp tag，也未改变仓库全局 Latest。
- zipapp SHA-256：`c96c8bb0380658d9eee2efd890eee6de95e9fbec11ec6d3255ba49448334713e`（39205 字节）。
- installer SHA-256：`20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95`。
- manifest SHA-256：`ac3833587b35a29d1ef0278112dc530bf68f1474fe047fd1f5dd733a0d156145`。
- 四个公开资产（含 SHA256SUMS）均下载核对实际摘要；同字节 zipapp 在独立临时安装位置完成安装、`--version`、显式 Skill 安装，随后清理该临时位置。未读取本机既有授权或操作用户 Agent 配置；macOS/真实宿主仍待用户验收。
- 独立 Cloud Worker 未部署/重启，仍 active，进程启动时间保持 `2026-10-23 16:29:49 UTC`；legacy Worker image 仍 `sha256:ff650c8a9f59d311f51614a3183f4327bd1125f4d9e6edd511b8b7ff96e3bf4c`。现有 Cloud/Memory 配置保持 enabled，权限、凭据和网关上游未修改；不据服务健康宣称业务重新验收。
- PostgreSQL image 仍 `sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c`；nginx image 仍 `sha256:8f59ff5046a70e421d35ed7d1e862a963215c9689b36cb8f64a6c42f9cf2955d`。守卫启动按现行规则重启应用栈，未更换无关镜像。
- 本轮新增合成 test DB 容器与临时安装位置已移除；保留 CLI 发行资产、旧镜像、迁移备份及构建记录。结束时磁盘约14 GiB可用。

剩余工作继续由[当前 TODO](TODO.md)统一跟踪。用户真实验收保持 USER_OWNED，部署健康和客户端发行完成均不自动关闭该项。
