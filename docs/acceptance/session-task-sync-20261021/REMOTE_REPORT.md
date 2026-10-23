# Codex 会话任务同步：远端隔离候选验收

**结论：真实管理同步通过。** 2026-10-21 16:05:37 +08:00，Mac官方MCP SDK通过受控SSH stdio，将既有UC18测试任务、全部15个已生成用例和两份原始报告保存到同服务器隔离候选，并按原key查询回执、固定version分页完整读回。**原SUT整体reported result仍为FAIL；本验收没有执行或重跑SUT测试。**

正式current/API schema0020尚未切换。本报告只证明隔离候选的管理同步，不是正式入口已升级、发布通过或新的业务测试结果。候选Project UUID不能视作未来正式Project映射。

## 实际环境与对象

| 对象 | 已核对身份 |
| --- | --- |
| 源Codex会话 | `01a143f4-4ec0-7451-ab23-8e59c6deb223`，「xblock异步接口能量购买供应商接入」 |
| 源捕获 | 2026-10-21 15:33:54 +08:00，来源会话仍工作，任务保持IN_PROGRESS |
| 远程源bundle | [UC18_REMOTE_SOURCE_BUNDLE_V2.json](UC18_REMOTE_SOURCE_BUNDLE_V2.json)，15:51:38 +08:00从冻结材料派生；没有刷新活跃SUT文件或原报告 |
| 候选标签 | `remote-isolated-final-4036ba150`；独立候选源码/venv、UID999 API、独立数据库角色；以空库迁移0022后运行兼容fixtures与真实同步，正式current未变 |
| SDK传输 | Mac官方MCP SDK → `ssh -T`管理命令stdin/stdout → 远端私有stdio/daemon → 同服务器候选loopback API；无TCP/Unix/TUN forwarding |
| 授权 | 单独Project-scoped integration `task:sync`，没有device绑定/执行grant；token只在服务器私有文件 |
| 候选Project | `01a15d7d-a1d1-7cbd-a773-450708ed9094`，XBLOCK |
| 候选Task | `01a15d7e-7a28-7d0d-9044-cfecc3174199`，version1，source=AGENT_REPORTED |
| 唯一同步key | `uc18-real-session-remote-20261021-v1`，expected_version0 |

SSH使用本Mac独立公钥与已核验host key，BatchMode/publickey/StrictHostKeyChecking均启用。候选仅使用显式loopback HTTP例外；正式入口仍按实际HTTPS/CA验证，不修改TLS、SSH转发策略或VPN白名单。Mac公有CA fingerprint与正式health核验见[交接](../../handoffs/CODEX_SESSION_TASK_SYNC_20261021.md)。

## 同步内容与读回断言

1. 使用冻结的真实session、原case/report keys和原文创建一个管理Task，没有建立legacy TestRun、Job、Runner、Binding或Gate。
2. 全部15项设计用例已保存。原执行报告对应的12项为10PASS/2FAIL，CASE-002/CASE-009保留自动FAIL；CASE-013/014/015有设计定义但冻结来源没有逐项结果，保存UNKNOWN并在actual明确缺口，不推断已执行、NOT_RUN或PASS。
3. 原自动报告与独立业务复核报告以两个稳定report key保存。独立业务11PASS/1FAIL与自动10PASS/2FAIL分别保留；AT03自动FAIL没有被业务复核覆盖。
4. 瘦回执核对ACCEPTED、Project/provider/session、原key、task UUID、version1和AGENT_REPORTED；再用原key单独GET，返回同一回执。没有在成功后发送第二个业务同步。
5. `hypertest_get_task`读取固定version1，按实际next_offset取得**3片**，每片固定task ID/version/total与source。拼接61,137个Unicode字符的current-only JSON，再核对任务Project/provider/session、IN_PROGRESS/FAIL、15项用例和两份报告。
6. 两份Markdown分别与冻结原文逐字节比较，source_ref与reported result一致。分页不截断原文，不重复带全历史，不调整旧1MiB通道上限。

补充只读核验分别在16:11:45与16:13:59 +08:00完成：15用例的全部提交字段（key/title/steps/expected/actual/reported_result/implementation_ref）逐项等于冻结V2；任务的provider/session/title/objective/status/plan_markdown/reported_result全部一致，Project/task ID/source亦匹配。见[用例逐字段读回](REMOTE_CASE_READBACK.json)与[任务逐字段读回](REMOTE_TASK_READBACK.json)。原16:05实际SDK观察未覆盖。尝试只从首片截取task时，校验脚本误假设JSON键顺序而失败；随后按完整固定版本JSON重建纠正，失败和时间另记，没有业务POST。完成后停止重复读取。

以上是任务/产物已保存并能读回的管理证明，不是SUT测试被再次执行的证明。source仍为AGENT_REPORTED，不转换成legacy VERIFIED Evidence、FINAL Verdict或RELEASE_READY；hash只指明捕获内容完整性。

直接执行记录见 [REMOTE_MCP_OBSERVATIONS.json](REMOTE_MCP_OBSERVATIONS.json)；真实SDK命令结果工具chunk `2a4e5c`，执行脚本为 [accept_remote_uc18_sync.py](accept_remote_uc18_sync.py)。脚本在Mac私有目录持久保存外层intent，远端daemon也保留原journal；失答/重启只GET原key，不自动POST、换key或创建替代任务。脚本不创建Project/grant，不部署、迁移或运行SUT命令。

## 检查、失败历史与时序

- 新管理客户端已验证严格回执相关性、异常UNKNOWN只GET、保留原有效task ID、compact journal，以及有界固定version分页；相关客户端组合37项通过。远端候选运行14项API与MCP/旧兼容组合，**86项通过，54条distinct相关弃用警告保留**，见[原始pytest输出](remote/remote-backend-tests.txt)。远端Web的129项测试、typecheck和build通过，见[Web测试](remote/web-tests.txt)、[typecheck](remote/web-typecheck.txt)、[build](remote/web-build.txt)。代码检查与实际SDK管理同步分别记录，不以pytest成功替代实际runtime读回。
- 候选最初以UID999运行时，`GET /projects`出现500。环境执行者定位为继承/root HOME，使asyncpg探测默认pgkey路径时触发权限错误；配置独立HOME后重启，GET恢复200。该失败发生在Project/grant业务POST之前，没有靠重发未知写恢复；没有读取root私钥或放宽私有文件权限，不是SUT缺陷。
- 本机最初只同步12项执行用例的历史仍保留；远程V2后来从冻结03a定义补3项设计用例。原本机bundle、回执及原报告没有覆盖。
- 初次冻结时验收脚本已对选取材料做凭据模式检查。主控的二次核对指令在SDK已发送调用后到达，追加扫描因此是**写后检查**，不能描述成写前。该次对冻结plan与两份报告检查PEM/Bearer/实际secret赋值/带凭据URL/认证目录，未发现疑似真实秘密或需遮蔽内容；只输出布尔/类别，没有打印匹配值或改写冻结原文（chunk `b53193`）。

## 三份状态的区别与剩余工作

| 环境/材料 | 结果与边界 |
| --- | --- |
| Mac本机历史 | 12cases、2reports、Task version2；开发检查，[原记录](REPORT.md)及原bundle冻结保留 |
| 远端隔离候选 | 15cases、2reports、Task version1；本报告实际SDK管理同步通过；无SUT重跑 |
| 原正式current | schema0020、旧受管能力和历史保留，尚未切换；不能从候选成功推定正式入口已有新功能 |

## 远端独立计数、Web HTTP与正式保全

SDK READY前已经完成Project/grant准备并冻结候选基线，随后对照真实同步后各表：仅新增 **1 SessionTask、15 CaseRevision、2 ReportRevision、1 SyncReceipt、1 Audit、1 Outbox**，其余76表计数不变，包括原TestRun/Job/Execution/Binding/Evidence/Verdict/native记录。基线含先前兼容测试fixtures（例如TestRun10、Job10、Execution1），**不能声称全库为零**。见[写前计数](remote/candidate-before-real-sync-counts.json)及[前后对比](remote/candidate-real-sync-count-comparison.json)。SDK初始观察中的“独立计数待补”保留其当时时序，这两份后续证据补齐该项。

远端Web 13101代理读到的实际Task JSON与API18101完全一致；3个HTML与24个静态资源HTTP200。见[HTTP读回](remote/remote-web-http-readback.json)。**没有远端浏览器交互验收**，不能把这些HTTP结果称为browser E2E。

运行身份见[候选runtime](remote/candidate-runtime-identity.json)：API PID3551094、Web PID3553680，均UID999且只监听127.0.0.1:18101/13101；Next BUILD_ID `KaWP3J0XFrLF0YqbgaUHW`。安装是未提交源码的editable候选，非正式MCP wheel。原始325文件归档SHA-256 `4036ba150bf743db317bf51b13ae28363c46b49c5eae5098576ee6e703e50f4b`，base commit `5a68dd1bd6375fad0b271b2b86af48bdf857fe31`；构建另修改`web/tsconfig.tsbuildinfo`，源码归档、构建产物和运行时不混为同一身份，见[源码身份](remote/final-source-identity.json)。

正式current/schema、受保护配置metadata及五个正式容器身份/启动/重启计数/mounts保持；61表中58表count+整行digest严格一致。`harness_nodes`、`runtime_control_requests`、`worker_heartbeats`三表存在动态差异；基线不是列级快照，**不能证明节点变化仅限心跳列，也不声称全部正式数据逐行未变**。具体边界见[正式保全对照](remote/production-preservation-comparison.json)。这不是测试执行证明。

后续远端浏览器查看、正式发布、正式库迁移/Project映射与正式入口同步由主控分别决定、记录，不重复本轮候选POST，不沿候选UUID盲写正式库。原raw报告、失败、业务复核、原UNKNOWN与恢复局限继续保留。
