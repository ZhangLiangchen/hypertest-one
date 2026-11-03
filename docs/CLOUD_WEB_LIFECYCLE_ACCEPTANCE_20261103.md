# Cloud 网页主流程实际验收记录

日期：2026-11-03（Asia/Singapore）。**实际网页闭环已完成：创建草稿 → 双仓解析 → 下发 → 结果与原文查看 → 独立复测 → 删除及历史查看。** 两轮真实原生 pytest 各 3 项通过；过程中发现的问题已修复并部署，原失败与未知记录保留。

本轮由用户明确要求实际操作网页验证。复用项目 `01a19fb1-63e9-7f0c-9ee2-595f30993abe`，通过网页创建任务 `01a1a064-4f27-7302-89e8-f8c51ef89fcf`。SUT 与 framework 都固定到已推送提交 `640d46166697e3997f963ddce47d7c2ea3e74b63`；范围仅为该版本 `tests/test_prepare_macos_cloud_worker.py` 的 3 项现有测试，复用本机 `.venv`，不访问数据库或外部业务 SUT，不安装依赖、不修改源码。冻结输出为 ANALYSIS、DESIGN、CASE、IMPLEMENTATION、REPORT 五类资产，以及真实 Run、JUnit 和原始测试日志；不能用预期结果代替本次执行。

此前通过 BFF/API 完成的实际闭环另见[领取恢复交付](CLOUD_WORKER_CLAIM_RECOVERY_DELIVERY_20261103.md)，不将其代替本轮网页按钮交互。

浏览器连接 host 不可用，本轮使用本机有界面 Chrome / Playwright CLI，在 1600×1000 PC 窗口中操作。创建、解析、下发、复测、删除全部通过页面按钮提交；另读取浏览器已经取得的固定版本、回执并核对历史，没有用 API 写入替代网页验收。最终领取状态使用 Worker 专用只读接口核对。

## 已修复与部署

网页删除按钮仍把任何 `RECOVERY_REQUIRED` 输入解析视为阻塞，即使服务端已核对完全撤权并返回 `management.can_delete=true`。提交 `225ec8cb35ae90f9ff9383d1f5e415b263f494eb` 移除这项前端重复判断，沿用服务端实时准入、当前版本及提交时重新核验；不改变解析恢复状态或原未知事实。

本机只停止、构建和更新 `web-wireguard`，复用仓库及缓存。部署镜像为 `hypertest-mac-web:225ec8c`，ID `sha256:3be8f63dbb5ea60206cde32eb5494572cba3ca39e9a166a09d3002c878fdac65`，OCI revision 与推送提交一致。使用 API 当前完整 Compose 链并追加 `cloud-web-20261103/compose.json`，仅覆盖 Web 镜像；WireGuard `10.66.66.3:3000`、BFF socket/TLS、授权挂载及 origins 保持。

API 保持 `hypertest-mac-api:640d461` / `sha256:98dfb4bf7e0e7b5c514f1721546f5331d3445e67a2c957b3939e1dd10b28d128`，schema 保持 `0044_cloud_worker_claim_state`。API、BFF、数据库容器 ID 与启动时间未变，无迁移。Web/API healthy，首页、项目 Cloud 页面及 API `/api/v1/health` 均 HTTP 200。网页实际 reload 后，同一恢复解析、同一服务端删除准入的任务，删除按钮由旧版禁用变为可点击；最终删除结果见下文。

首轮完成后还发现旧解析异常被提示成当前“输入解析需要处理”。提交 `b129c14a9b8e5a189a957909fe415ca7e01b946e` 区分当前与历史解析提示，保留未知原记录。最终 Web 镜像为 `hypertest-mac-web:b129c14` / `sha256:e4afa3759bde094bf9e94f1abf236ced4867f80851e3f116da744ef1a33b2246`，追加 `cloud-web-20261103/history-compose.json`。本次只重建 Web，第二轮 SDK 工作未中断；页面刷新后已实际显示“历史输入解析异常记录已保留”。

宿主 Worker 的后续修复分别已推送：

- `a08e2d478c93f5ba357bd26e017a95c7046be349`：普通 SHA/分支输入解析只获取所选 commit 身份，采用 `--depth=1 --filter=tree:0`；MR 父关系校验及实际工作区 checkout 保持原要求。双仓总租约窗口超时明确记录 `RESOLUTION_TIMEOUT`，不接受半份解析结果。
- `77245636b4987a734b81e9b7d9d24fa229e182ff`：保留有限 Git operation、exit code 等安全诊断，不保存原始 stderr、URL、凭据或环境内容。
- `e68e4e5a5333825af3bf4be340c9f2ccd50a28c3`：补充有限传输中断分类；认证、证书、host key、缺失引用等永久失败优先拒绝，不因混合错误文本进入重试。

这些修改只重载宿主 Worker，未重建 API/Web。最终 Worker PID `57805` 于本地时间 `16:14:45` 启动；原 SDK/runtime 配对、profile 与凭据沿用。

## 输入解析阻塞调查

原 Worker PID `50517` 跨越先前 `640d461` API 部署而未重启；API 版本不能代表宿主长驻进程已经重新加载代码。它在本轮 Git 解析失败后退出，Web 部署开始前已无 PID、last exit code 为 1。旧解析及领取按原身份封口/撤权，原未知事实保留，没有重放失败任务或 SDK 工作。

现场只读 Git 探针观察到：单仓全量 fetch 耗时 `70.27` 秒，而双仓解析共享 `85` 秒窗口；仅加 depth 1 的探针仍在 `90` 秒超时。仅取 commit 身份的 depth 1 / tree 0 探针在 `2.48` 秒成功，后续双仓探针分别为 `1.98` 和 `4.15` 秒。以上支持缩小输入解析传输范围，不证明前三次失败均由同一种网络瞬断造成，也不补造已丢失的具体错误原因。

同一任务的前三次解析保留为 `RECOVERY_REQUIRED`，每次后续解析均为页面显式发起的新操作：

| 次数 | 输入解析 ID | 本轮已知结果 |
| --- | --- | --- |
| 1 | `01a1a064-ad8b-7536-b2fe-e69bf4c9828f` | RECOVERY_REQUIRED，原未知事实保留 |
| 2 | `01a1a06a-8440-7db1-bd45-3a895115bdac` | RECOVERY_REQUIRED，原未知事实保留 |
| 3 | `01a1a074-51e5-7fa8-a956-f17f62f79a69` | RECOVERY_REQUIRED，原未知事实保留 |
| 4 | `01a1a079-b493-7c56-be31-21891a881bd4` | ACCEPTED，Task v6，双仓均为完整冻结 SHA `640d46166697e3997f963ddce47d7c2ea3e74b63` |

## 真实网页执行与管理

通过网页下发，v7 创建 Attempt #1 `01a1a07a-19f8-7c8a-949c-25dc60d4d069`。页面观察到领取、准备及完成，最终 v16 / `COMPLETED / PASS`。在“产物与结果”展开最终报告和 Run，确认五类资产、三个用例、实际命令、起止时间及退出码 0；逐项点击“读取原文”，查看 JUnit、stdout 和空 stderr。JUnit 为 3 tests / 0 failures / 0 errors / 0 skipped，stdout 为 `3 passed in 0.18s`；直接 SDK 退出记录 returncode 0。

随后在“尝试历史”查看首轮记录，在“输入与控制”点击“新建执行尝试”，重新填写本次目标、范围、步骤、精确入口及副作用限制，核对授权并勾选两项确认后点击“下发重试”。v17 创建独立 Attempt #2 `01a1a082-74a4-75d9-a7b8-efae43e4ee8c`，最终 v28 / `COMPLETED / PASS`。第二轮报告、Run、JUnit 和日志同样通过网页展开/读取：3 tests / 0 failures / 0 errors / 0 skipped，stdout 为 `3 passed in 0.19s`，Run 和直接 SDK 退出码均为 0。“尝试历史”同时显示两轮已完成/通过，两个独立 Run 与六份原始附件均保留。

点击“删除任务”及确认浮层的“删除”，取得 v29 接受回执并自动返回项目列表；列表不再包含本任务。重新打开原链接，页面明确显示“已从任务列表移除”，新执行入口消失、删除按钮禁用，原两轮历史仍可查看；再次点击第一轮 JUnit 的“读取原文”成功。

浏览器完整读回的 v16、v28、v29 对比确认：原 Attempt、资产、Run、用例结果、附件、解析记录及冻结输入没有被复测改写；删除也没有修改两轮记录。第二轮 manifest 的 `retry_of_attempt_id` 指向首轮。前三次解析仍为原 `RECOVERY_REQUIRED`，未改写为成功或未执行。

最终 Worker PID 57805 仍运行；2026-11-03 16:32:09 +08 只读领取状态为 sequence 2077 / `EMPTY / closed=true`。两次完成均保留宿主其他进程与外部操作的未观察边界；这些 reported PASS 不升级为独立 VERIFIED Evidence 或 RELEASE_READY。

## 已完成的相关回归与证据

Git 相关回归 41 项、输入解析超时 2 项、主循环诊断 1 项、删除及 Cloud 客户端回归 33 项通过；历史提示修改后相关现有回归 30 项通过。Web typecheck、两次构建、变更页面设计检测（`[]`）、相关 Ruff 与差异检查通过。自动回归与上文真实网页操作分别记录，没有将 fixtures 写入业务数据库。

- 网页操作、固定版本和截图：仓库本机 `output/playwright/cloud-web-20261103/`。
- Web 部署身份、完整 Compose 链、构建/启停与健康检查：本机私有 `~/.local/share/hypertest-mac/cloud-web-20261103/`，主要文件为 `deployment.json`、`health.json`、`compose.json`、`build.log`、`stop.log`、`start.log`。
- Git 只读探针及有限诊断：本机私有 `~/.local/share/hypertest-mac/native-worker/diagnostics/`；没有将 SDK 聊天、思考日志或凭据作为产品证据。

最终 Web 部署证据另存 `history-deployment.json`、`history-health.json` 和对应构建/启停日志；原 225ec8c 记录未覆盖。网页记录包括固定 v16/v28/v29、历史比较、两轮 JUnit、删除后列表及原链接截图。此范围内未再观察到阻塞；其他项目、远程业务写操作、Codex/Claude、原会话续接与所有异常分支不在本轮实际验收范围。
