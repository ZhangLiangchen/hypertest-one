# Local 模式项目入口部署记录（2026-10-23）

> **历史部署与验收记录。** 下述 MCP/Hooks 页面与 `local-v*` 包是当时的旧 Local 接入，不是现行安装指引。新接入采用 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 的显式 CLI/Skill 归档；请查 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)、[当前 TODO](TODO.md) 和 [服务器操作](SERVER_OPERATIONS.md)。旧任务、回执及原 key 恢复边界仍需保留；此记录不证明当前部署或用户验收状态。

2026-10-23 曾将“项目页 → 本地会话任务 → 接入本地模式”入口部署到当时的 Web。用户当时可选择 Claude Code、Codex 或 DeepSeek harness，查看显式 MCP 与 Hooks 自动同步两种接入命令。页面提供的是原有固定版本安装包；本次没有升级 Local runtime、后端、Cloud Worker 或生产数据库结构。

PR [#23](https://github.com/ZhangLiangchen/hypertest-one/pull/23) 合并为 `b27c8c14c80dce46bc21a02c83daba7070cf8292`，合并树与已审查 head `10de445c813dbad9e37201f1210d8595a35e206b` 一致。[CI #121](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39895747568) 的两个 job 均核对到该 head：Python **1180 passed / 21 skipped**（89 warnings），Web **140 passed**，TypeScript 检查及构建通过。CI 中的迁移验证不代表生产执行了迁移。

生产 Web 镜像为 `sha256:559c62b7b394fd30bbe34aaf91dc3bbea05ffbe5a1480051d2ab5679cd4f1c2b`，来自合并后的 68 个 Web 源文件，源码归档 SHA-256 `06dc406678b4a63986b91f842f9ef2cc2cfbafb2fdc016e1719b7b488f7aa6a7`；Node 基础镜像固定为 `node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`。构建收据的 `deployed=false` 仅记录构建阶段，实际部署以独立切换收据为准。

Web-only 切换发生于 **03:52:44–03:53:13 UTC**，35 项保护检查全部通过（独立重算 34 项快照检查，另 1 项是已审查的运行时配置字节断言）。API、Worker、数据库和入口容器未替换；在 Web 切换窗口 before/after 中，被比较的 74 张表行数与完整行摘要保持一致，比较明确排除 `worker_heartbeats` 与 `runtime_control_requests`。配置、schema、访问策略、运维/Bridge 源码及历史会话材料保全。历史 legacy 宿主 nginx 的 `failed` 基线保持原样，不能据此宣称该历史服务已修复。本轮沿用既有 ADR-016 配对备份/隔离恢复边界，**未新做冷备、未做数据库恢复**；只允许回退 Web 镜像，实际未触发回退。

**03:56:28 UTC** 的单 SQL 补证在切换后执行：同一数据库快照同时返回 `QUEUED / PROVISIONING / RUNNING / COLLECTING` 四类计数，均为 0；`test_executions` 共 11 行，完整行 SHA-256 `5f95fa6ea87a604afc0f096cd075d3e03e190141cdb7b4c43695cc5de930f918`，与切换前、切换后记录相等。这是切换后补证；直接的切换前状态查询遗漏仍保留，不能倒写成已执行的 pre-gate，maintenance lock 也不等同数据库写入围栏。

实际远端生产页面交互通过：只发出 50 个 GET，请求未触发业务写入；三个宿主共六种命令均可展示，1440px 与 390px 宽度无横向溢出，页面与控制台错误均为 0。页面读到原 Codex Task v3，任务 `BLOCKED / FAIL`、1 条 FAIL 用例和 1 份原始报告均保留。该页面检查没有执行安装命令。

另由外部 Mac 进行严格 CA、主机名及证书校验：生产 HTML、21 份引用 JavaScript，以及现有 Project/Task API 共 24 个 GET 最终全部返回 200；原只读 SSL EOF / 重试原件保留，最终完整 24 个 GET 通过；最终通过轮次含一次 JS GET 重试，不据此声称历史仅一次错误。固定 release pins 匹配，原始报告 **792 字节**，SHA-256 `0e1e7ab07e0914e31dbd957108dd59892eb6bdf3f5869b4c205654d38c7ab36b`，用例与任务仍为 FAIL。此项未在 Mac 启动浏览器；HTML shell/JavaScript/API 核验与上述远端页面交互分别取证，**不宣称公网浏览器 E2E**。

[HyperTest Local `local-v0.1.0`](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.0) 的包、tag/source 和 pins 均未改动；正式目标仍仅为 **Darwin arm64 / CPython 3.13**，Linux x86_64 / Python 3.12 为 candidate。CLI 版本限 Claude Code 2.1.218、Codex 0.144.6、DeepSeek harness 0.1.5-rc.1；既有 latest 仍为 `mcp-v0.2.0`。Hooks 默认关闭，显式选择并核验后才启用。DeepSeek 的实际 headless bundle 已观察；跨进程恢复使用官方 Registry API `agents.resume` 和受限验收驱动，未新增通用可安装的 headless resume CLI 或 SDK wire method；旧 SDK 双 turn 证据独立保留，产品 Stop handler 次数未独立计量。所有 fixture FAIL 仅是管理同步验收数据，**业务 SUT 未运行**。

三个宿主的 producer 清理完成：停用本轮 metadata observer/专用 profile、正常停止自建 daemon，3/4/4 条同步 intent 均完成读回，0 pending；Codex 10 条自建 trust keys 已删除，其他 17 条保留。原会话、journal、绑定、快照、工作区及失败原件保全。

生产部署及清理的独立复核为 `PASS_WITH_EXPLICIT_LIMITS`，原收据 SHA-256 分别为 `da9b954bb1a14e50c163452912c83e567a785bc5f8cc48715c5fa31b6091ae44` / `876fa30fa9070d6b962239486005e4ed6b15c696bca2aa97ac737fb7d5ddc3e9`。固定 readiness 的通用 VPN 全边界、所有应用数据、真实测试周期和 Connector TLS E2E 四个未验证标记仍为 false，不用本轮局部验证代替。

本轮临时授权已收尾：三个 grants 各仅撤销一次，均返回 HTTP 200 / REVOKED；各原 Bearer 不带 Operator，经严格 CA 对原 key GET 均返回 403。三份证明齐全后，仅删除三个本轮 token 文件和本机/远端两份原始 token 载体；40 个 state 文件摘要完全保留。三次 grant 撤销及其审计写入发生在 Web 切换保全窗口之后，是单独授权的预期差异，不声称整个收尾期间所有表恒等。之后对 Project、三宿主 Task / case / report 再次 GET：Codex v3、Claude v4、DeepSeek v4 与原报告字节一致；五容器 healthy、restart 0，四个非 Web 容器身份及三个 current 入口保全。固定运维 readiness 的 10 项检查通过；标准健康包装脚本仍因历史 legacy 宿主 nginx failed 返回非零，该历史状态没有修改。

本记录的[脱敏 JSON](local-acceptance/local-web-production-deployment-20261023.json)保存源收据摘要、准确身份和各阶段边界；[三宿主矩阵](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)与 2026-10-22 资格 JSON 保持冻结历史。README 与当前 Local 状态中的上线补记覆盖其中“待 merge / 待 gate”的冻结时点字句。**实际运行的 Web 源码始终是上述 `b27c8c14…`，后续纯文档提交不代表重新构建或部署 Web。**

早期私有只读探针的失败保留：原始 HTML 不含客户端 hydration 后的入口文字，修订探针只核 HTML shell 与引用脚本，交互另由实际浏览器验证；HTTPS 过程中出现 SSL EOF，严格 CA 不放宽，仅 GET 有界重试后通过。最初补充闲置 SQL 的引号错误也是只读失败；最终补证来自保留的单语句同快照收据，不回写执行顺序。

回退继续遵循[Web-only 运维边界](CONTAINERIZED_DEPLOYMENT.md)：同维护锁、空闲与网络保护检查下，只恢复旧 Web image `sha256:c4f1ce4ef9d2a61b246999a7bf680f89dfa9e060018722f68d74898309714529`，经固定 Compose 的 `--no-deps --no-build --pull never web`、健康检查及原 nginx `-t` / reload。不得重启全栈、恢复数据库或改网络 / SSH / TLS。本轮未触发回退。本文不包含入口 IP、私人绝对路径、secret 或原始工具聊天。
