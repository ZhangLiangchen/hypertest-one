# P0：Web 未决保全与 Cloud 安全收尾

**P0-1 / P0-2 实现与部署完成；功能验收 PENDING / USER_OWNED，由用户负责。** 本轮未创建线上验收项目、Task 或凭据，未触发真实模型或 SUT。真实 SDK 原会话续接、通用 HTTPS/SSH/CI、Cloud Claude、Local 新宿主绑定与 PowerContext 集成仍是独立待办。

## 本轮开始时的实际环境

2026-10-23 核对时，工作区干净，HEAD 为 `55de50e215961ee4a1061b32f86670bd23259324`。远端 main 为 `b55a1fb64fc3ed6b6bed41a102f332e509a81265`，差异为已保留的归档历史和原件；工作区只作 fast-forward，没有 reset、覆盖或删除旧工作。

API、legacy Worker、Web 的镜像 revision 与独立 Cloud Worker release 均指向 `55de50e`，五容器 healthy、Cloud Worker active，schema 为 `0026_cloud_ssh_operations`，API health 正常、Web HTTP 200。只读观察未发现 CloudAttempt。旧 C4/6d49 文档是先前轮次的历史，不能替代本轮实际部署身份。

## P0-1

Web 使用 IndexedDB 独立 Cloud / Local CREATE stores，通过 readwrite 事务在同 Project、同模式内占据未决流；广播与页面聚焦只刷新视图，不授予 POST 权限。响应只按原 key 的冻结身份更新或移除自身记录。关闭标签页后从持久账本恢复，多个标签不能各自为同一流创建新 key 并发发送。

Cloud 仅保存恢复所需的非秘密身份、key、version、摘要与传输状态，禁止持久保存秘密、PRD 或请求正文；Local CREATE 保留完整冻结请求及 expected_version=0。旧 sessionStorage 成功事务迁移后才移除，冲突原 key 全部保留。存储失败禁止 POST，失答/UNKNOWN/NOT_FOUND 只查询原 key；有效 ACK 后完整读回固定接受版本，再结算对应账本。

持久性受浏览器站点数据保留策略约束：用户清除数据、浏览器驱逐及私密模式结束可能移除账本；不能据此推断旧请求未执行或自动重发。

## P0-2

复用原取消、lease expiry、fencing、RECOVERY_REQUIRED 与 RECONCILE_ATTEMPT。当前运行端不支持原 SDK 会话续接，能力响应、控制 API 与 Web 一致表达 `SDK_RESUME_UNSUPPORTED`；不把 SDK 方法存在当作可用恢复能力，不自动重放 prompt。

Web 区分取消请求、停止待确认、待对账与终态。人工收尾入口受当前权限、最新版本及服务端 canonical 前置条件约束；旧 owner 必须已 fence，原未决 key、远端操作或活动委派不能由声明清除。操作者提供停止/对账观察和声明，其来源为 `OPERATOR_ATTESTATION`，明确不构成独立停止或模型 drain 证明。人工 FAILED/CANCELLED 保留 reported_result、checkpoint、原件、旧回执及 HELD/preparation hold，不结算模型预算。

Worker 重启遇既存 runtime 不重放；超时、失租、取消与失答先阻断普通写入并安全 fence，再执行限域清理与原 key 对账。失权 Worker 不再发送普通平台 mutation，历史终态保持不可变。

## 回归、构建与部署

实现、相关回归与固定 Git 部署均已完成。代码已推送 main，服务器 fetch 后固定完整 SHA `e6493b33e619abd7eadfa0d452cbc7903e439a52`，干净源码构建 API、Web 与独立 Cloud Worker。无新增领域表或 schema 迁移。相关规范同步见 TMP §45.4/§46.6–7、领域 §51.5/§53.2、架构 §45.6、ADR-019 §6 与 ADR-024 §4。

| 部署项 | 固定身份 / 结果 |
| --- | --- |
| 应用部署 Git | `e6493b33e619abd7eadfa0d452cbc7903e439a52`；本记录部署后补充为纯文档变更，不重建镜像 |
| API image | `sha256:b10a45b2e1461912f283a8f77b6dd62711e8e107bf7b8acb44384cb453342c5e` |
| Web image | `sha256:15374e2ec59306994371987dd3c1871c1075ba826265b10ae547176e0d990adb` |
| 独立 Cloud Worker image | `sha256:fbdd46c6e5e9884831b5c6c7e04a11e57e7a321036241ebf2daa247c42a506d7` |
| Cloud Worker release | `/opt/hypertest-cloud/releases/e6493b33e619abd7eadfa0d452cbc7903e439a52`；manifest SHA-256 `86e1ffa092d94a342cdc8569bc850de03d3adfe226a66442a586bdd1377efd2f` |
| legacy Worker | 保留 `55de50e` 来源及 image `sha256:ff650c8a9f59d311f51614a3183f4327bd1125f4d9e6edd511b8b7ff96e3bf4c` |
| 构建 | API / Web / Cloud Worker 均成功；Web 正式 Next build 成功 |
| 迁移 | 无；schema 保持 `0026_cloud_ssh_operations` |
| 启动与健康 | 五个容器 healthy，独立 Cloud Worker active；API health、Web 根页 HTTP 200 |
| 本次关键读取路径 | Web BFF → 既有严格 TLS Cloud API capabilities HTTP 200，核对 resume=false、reconcile=true、OPERATOR_ATTESTATION / KEEP_HELD |
| 访问边界 | 既有 ingress guard protected；原 TLS、VPN/端口、SSH 访问及凭据路径保留 |

本次仅停止和替换 API、Web、独立 Cloud Worker；PostgreSQL、legacy Worker、nginx 保持运行。仅更新 compose.env 的 API/Web image 键，保留数据库/卷、源产物、会话、私有 runtime 与 journal/key、历史和旧 releases；未执行清理或恢复演练。Worker 保持 Cloud/Codex 启用、固定 SSH 关闭，未改动 PowerContext 或其他服务。

构建与部署回执：`/var/lib/hypertest-cloud/delivery/20261023-p0-e6493b33/build.json`、`deployment.json`，各组件构建日志在同目录；它们是部署检查，不是功能验收。组件镜像使用既有固定摘要 Python/Node/Docker CLI bases，精确值保留在 build.json。独立 Worker 经原启动准入后运行，没有运行真实模型或 SUT。

| 检查范围 | 最终结果 |
| --- | --- |
| 后端 `test_cloud_runtime/tasks/ssh_authority/worker_diagnostics/delegation/ssh_worker` 六文件 | 184 passed / 1 skipped，18.02s；跳过既有可选 SDK 测试，因临时环境未安装 `deepseek_harness`，不计通过 |
| P0-1 Web `cloud-client`、`local-task-creation`、`operation-journal` | 48 passed / 0 failed / 0 skipped |
| Cloud Web `cloud-client`、`cloud-recovery`、`cloud-bff` | 37 passed / 0 failed / 0 skipped；与上一行的 17 个 cloud-client 用例重叠，不能相加为一次检查 |
| Next typegen / TypeScript | 通过 |
| 六个修改 Python 源文件与四个修改 Python 测试 Ruff | 通过 |
| 三个 UI 改动文件 Impeccable detector | `[]` |

回归覆盖关闭重开、双标签事务竞争、旧记录迁移冲突、存储不可用、sessionStorage 拒绝后原 key 恢复、失答/NOT_FOUND/原 key 冲突不重 POST、ACK 后固定版本读回与跨页迟到响应。后端新增故障回归覆盖重启、超时、取消、失租/续租失答、报告失答、先 fence 再清理、失权拒写、原 key 读取、人工前置条件及声明来源白名单与 HELD/历史保全。开发中暴露的旧同步测试适配及事务通知竞态已修复后按上述范围复验；不将中间失败改称首次全通过。

后端回归使用专用临时 tmpfs PostgreSQL，已删除本轮创建的临时容器，没有接入线上数据库或留下测试端口。本轮全部结果为自动化回归，不是用户功能验收或真实 SDK/模型/SUT 故障演练。

仍存在的限制：真实 SDK 续接未实现；已知原 key 或 UNKNOWN/活动委派缺少可核验终态材料时，人工收尾保持阻塞，不提供绕过。浏览器持久性限制见上文。
