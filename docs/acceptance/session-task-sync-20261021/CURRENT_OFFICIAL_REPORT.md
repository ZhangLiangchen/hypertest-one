# 正式远程测试环境：官方0.2管理同步验收

本报告只证明既有测试资产的管理同步与内容保存一致。HyperTest没有执行SUT测试；两份原报告及其PASS/FAIL保持来源明确的Agent reported结果。

## 已验证结论

- 实际入口：[XBlock测试任务](https://155.138.206.106:8080/tasks/01a15de5-9aca-76b4-bd57-c673112f2e92)，Task `01a15de5-9aca-76b4-bd57-c673112f2e92`，version1。
- 正式Project `XBLOCK` = `01a15de2-205e-76e6-bfad-7468a724f886`。不是旧候选Project UUID。已知GitLab根入口为 `https://gitlab.charprotocol.com/`；Project repository_url未设置，未推断子仓库或branch。
- 来源是真实SUT Codex会话 `01a143f4-4ec0-7451-ab23-8e59c6deb223`，不是当前HyperTest开发会话；捕获时仍active。平台任务为 `IN_PROGRESS/FAIL`，不宣称该源会话最终完成。
- 实际接受稳定key `uc18-real-session-current-20261021-v1`，expected_version0→version1；实际Task POST一次。原key GET回执与接受结果一致。
- 固定version1的3页，共61,137字符，拼接完整current-only JSON；task标题/目标/状态/完整计划/结果等全部输入字段、15项case的全部输入字段、2项report的全部输入字段与原始Markdown逐字段/逐字节一致。未把摘要或hash当执行证明。
- 自动12项保留10PASS/2FAIL（CASE-002/009 FAIL）；已设计但未给出逐项观察的CASE-013/014/015为UNKNOWN，未推断NOT_RUN/PASS。独立业务报告11PASS/1FAIL单独保存，不覆盖自动失败。
- 此正式同步没有重跑SUT、创建Run/Job、请求Runner或Gate；SDK脚本的SUT执行计数为0，实际数据库前后计数由后端独立记录，不以脚本自报替代。

## 原件与时序

冻结来源为 `../UC18_REMOTE_SOURCE_BUNDLE_V2.json`，SHA256 `278f5003a287746b5abba528eed1f04f2d1f31122f0b8fea5e39c37601662f3c`，原本机12项与远端候选15项历史快照均保留。本批没有刷新活跃SUT文件或报告。

正式写前实际 `2026-10-21T17:58:09.329337+08:00` 对冻结plan及两份原报告核对凭据模式，0疑似；未打印匹配值、未改原文。正式SDK完成时间 `2026-10-21T17:58:12.018334+08:00`。早先候选的二次核对发生在写后，原有时序未改写。

- [官方SDK实际观察](current/OFFICIAL_MCP_OBSERVATIONS.json)
- [SDK运行日志](current/official-sdk-attempt-1.log)
- [新Mac grant远端只读核验](current/MAC_CLIENT_READONLY_OBSERVATIONS.json)
- [新grant只读运行日志](current/mac-grant-readonly-attempt-1.log)
- [Mac安装与静态配置元数据](current/MAC_MANAGEMENT_CONFIGURATION.json)
- 实际远端私有源、意图与观察目录 `/var/lib/hypertest-a18-client/sdk/`；私有配置/授权/Journal留在同级0700目录，不收录秘密。

新Mac grant的只读检查完成于 `2026-10-21T17:59:31.429990+08:00`：同actor/project下，以新client token GET原回执及3页固定version1任务，验证Task ID、来源session、owner `interactive:01a15de2-20b7-702b-9bdd-32f27d89fb57` 与全部task字段。该分支Task POST=0，没有创建新的Task或key。

## 发行与真实传输

发布源码 `5c03e4d90bed69b6420238849cbb3a8bae2f4c42`，tag `mcp-v0.2.0`。[PR22](https://github.com/ZhangLiangchen/hypertest-one/pull/22) 已合并；[精确main CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39573509731)与[发行workflow](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39574028721)通过。CI Python1049 passed/21 skipped/57warnings；Web129 passed、typecheck/build通过。CI是远端发行验证，不是Mac测试。

[官方0.2发行](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/mcp-v0.2.0)的wheel为 `hypertest_one-0.2.0-py3-none-any.whl`，369859 bytes，SHA256 `d7e7bfdbb5a5a25bab343bf695185cc9587c745605c667ba28a9d23d336a6dd3`。远端实际非editable安装，SDK1.30.0，实际解释器 `/opt/hypertest/deployments/adr018-20261021/official-client/venv/bin/python`。

真实路径是远端官方MCP SDK → 原wheel stock stdio（python -I，无autostart）→ 官方IPC/Service/Journal（公开构造器注入transport）→ 显式CA、hostname严格校验的真实TLS-over-private-UDS → 同正式数据库的临时独立ASGI API进程。stock daemon CLI本身没有UDS配置项；不是声称未改CLI原生支持UDS。非mock HTTP、非伪造scheme/X-Forwarded-Proto，不放宽原VPN ACL或allow_insecure_loopback=false。

当前Docker API与此临时ASGI listener是不同PID；相同源码/数据库身份、负向CA/hostname、方法路径allowlist、正式部署/迁移及清理证据由后端发布记录独立提供。后端交接已实证schema22与源5c03，数据库OID16384/system_identifier7697580503987753003与原PG相同；本SDK观察不替代该连接身份核验。

两次客户端进程实际exit0，LocalServer/stdio context关闭，remote-state仅保留client.sqlite3/ipc.token/daemon.lock，无interactive.sock。运维owner收到只读完成后负责停止临时TLS listener；不得将该短期UDS配置作为后续Mac长期入口。

## Mac管理连接：已配置，待新会话加载

该Mac连接未做本机验收。新根目录 `~/.local/share/hypertest/codex-session-management-20261021/` 0700，config/token0600，state0700且配置时为空。只安装官方wheel及GitHub发行smoke已测版本的Mac/Python3.13 binary依赖，未从旧editable项目导入模块或本机构建。配置工作没有启动应用、stdio、daemon、SDK、浏览器或任何测试/lint/build。

仅新增 `mcp_servers.hypertest_management`，保留原Codex配置字节并保存0600私有完整备份。使用官方venv绝对Python、-I、private cwd、空PYTHONPATH/PYTHONNOUSERSITE防stock autostart子进程的cwd/环境影子；标准入口 `https://155.138.206.106:8080/api/v1`，使用原公有ingress CA，loopback例外false。新Mac token已在远端独立GET核验后私有传输，没有Operator/device/execution授权。

官方bundled hypertest-interactive skill已安装，另有PROJECT_BINDING.md说明此profile只用于XBlock真实来源，不把HyperTest开发/Blockchain/其他聊天默认归XBlock。框架路径本身不能区分SUT。未来其他Project须另核验授权。

官方0.2服务在task:sync下实际仍广告20工具（旧执行9项在内），不是只广告2个；服务端scope独立限制权限。Codex此新entry配置 `enabled_tools=["hypertest_sync_task","hypertest_get_task"]`，控制管理profile可见工具；当前会话未热加载/验证它。配置键依据先本机metadata盘点、后实际打开[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)（含cwd/env/enabled_tools）。

## 跨会话与未完成范围

新会话先GET旧Task完整固定版本，再用自身真实session_id和独立稳定key创建新Task；plan_markdown/source_ref明确旧Task URL、原sourceSession、report引用和剩余工作。不要复用旧sourceSession伪装原聊天继续。新的有意更新先读当前version，失答只按原key GET；保留所有Journal、旧失败和原文。

当前未决SUT结果：源聊天最终报告未重新获取；CASE-002/009原失败未因同步被修复；CASE-013/014/015无逐项执行观察。管理保存成功不关闭这些项。Mac连接加载/公网客户端握手未在本机验证；不得把静态配置当已连通。远端UI实际覆盖和独立数据保全范围见对应owner的报告，不以本报告冒称公网browser E2E。

过去本机12项v2、远端隔离候选15项v1、此次正式库15项v1身份互相独立。私有bundle、真实报告、raw观察、handoff不在PUBLIC GitHub发行内容中。

### 授权到期与续期

Mac管理grant为30日授权，精确expires_at `2026-11-20T09:54:23.105383+00:00`（新加坡时间2026-11-20 17:54:23.105383+08:00），grant ID `01a15de2-2102-798d-aa38-f1794aa77fdc`；client_instance_id `e43fb03f-e7aa-4a5b-8a9b-d54b65d9fd20`。续期由管理员显式安排，保留actor_identity_id `01a15de2-20b7-702b-9bdd-32f27d89fb57`、该client ID、Project `01a15de2-205e-76e6-bfad-7468a724f886` 与仅task:sync范围；不要临时更换任务owner、默认Project或扩大scope。到期不是自动签新token、换key或重发Task POST的授权；原UNKNOWN仍仅以原key GET对账，保留Journal。远端本轮短期client expires_at2026-10-22T09:54:23.052698+00:00，短期TLS配置只作历史，不是长期Mac连接。非secret原始授权元数据见current/AUTHORIZATION_METADATA.json。

时间分列：源材料冻结 `2026-10-21T15:33:54.750222+08:00`；平台同步SDK核验完成 `2026-10-21T17:58:12.018334+08:00`。后者是实测完成时间，不能冒称数据库created_at；如需精确数据库接受时间以正式任务行原件为准。

旧本轮Mac开发MCP daemon PID55116经UID、解释器、argv与旧8101配置逐项静态核验后按授权SIGTERM，后查PID及socket消失，旧client.sqlite3仍保留；新management state为空，未启动新客户端。见current/MAC_OLD_DEV_PROCESS_CLEANUP.json。

## 后端与UI独立事实补充

平台任务实际数据库 `created_at` 与 `last_synced_at` 均为 `2026-10-21T09:58:10.890320+00:00`（新加坡时间17:58:10.890320）。这是后端实际DB直读、UI保存JSON的last_synced_at亦一致；与源冻结15:33:54.750222及SDK完成17:58:12.018334分列。

[76表实际计数对照](current/CURRENT_TASK_SYNC_COUNT_COMPARISON.json)的基线在Admin bootstrap后、首次Task POST前，终点在SDK及Mac新grant只GET后：SessionTask0→1、CaseRevision0→15、ReportRevision0→2、SyncReceipt0→1、Audit897→898、Outbox892→893；其余表计数不变，明确包括旧Job、绑定、Execution、Evidence、Verdict及native各表。旧表不是全0，计数对照也不单独证明所有旧列值不变；维护前后行/列/FK/原件保全以独立后端发布报告为准。

[真实TLS正负例](current/TEMPORARY_TLS_VERIFICATION.json)：正确CA与hostname通过、错误CA/hostname握手失败，缺Bearer401；旧execution/Web/admin/不允许method403；原生Uvicorn SSL的https scheme，不使用proxy_headers。均GET/HEAD无业务写。连接同原PG的database_oid16384/system_identifier7697580503987753003。

[临时TLS实际清理](current/TEMPORARY_TLS_CLEANUP.json)：PID3688162已不存在，监听停止，root0600的自有stale socket移除，client IPC sockets也不存在；私有文件/token/Journal保留。有Uvicorn application shutdown/finished process日志，但wrapper stop record缺失，未声称显式engine.dispose已证实。后端另已精确核验并停止旧候选API18101/Web13101及daemon，保留候选数据库/源/Journal/授权。

UI独立owner已审阅远端Linux实际Playwright/Chromium桌面1440与手机390的4张截图和browser-check.json，APPROVE无P1/P2。只覆盖internal `http://127.0.0.1:3000`：实际Task v1、状态/来源分列，15case/2report显示，报告endpoint与DOM原文比对，无横溢、console/page errors，全部GET且无外部origin或写请求。展开case内容只检查第一项；全部15项字段的exact来自SDK，不冒称UI逐项展开覆盖。新Project legacy_runs=0只验入口/空态，旧全平台历史由DB保全证据承担；public HTTPS browser E2E未测。原件在Mac私有 `~/.local/share/hypertest/session-sync-dev-20261021/formal-remote-20261021/ui-review-20261021T100422/`，UI独立报告由UI owner维护。

UI/TLS/当前DB计数独立只读评审已完成APPROVE，精确报告：[INDEPENDENT_UI_AND_TRANSPORT_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/formal-remote-20261021/ui-review-20261021T100422/INDEPENDENT_UI_AND_TRANSPORT_REVIEW.md)。其原文保留internal/public边界、第一项case展开覆盖与全部15项SDK字段核对区别、旧数据保全另据部署证据、cleanup失败历史与engine.dispose marker未确认。

最终后端发布/健康/保全已完成，无待处理阻塞；精确原件：[CURRENT_RELEASE_SERVER_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/formal-remote-20261021/CURRENT_RELEASE_SERVER_REPORT.md)。后端实际10:18:22Z五服务healthy、Bridge active，原PG身份/start/卷及SSH/VPN/auth保护项一致，维护锁可获取；60旧业务表7874原PK保留，逐列比对仅一Harness节点四项运行观察列变化，182 FK validated/0 orphan，采集范围内文件/metadata exact。此处引用其实际结论，不新增验证、不把有记录的运行列差异改称全库不变；历史失败与cleanup缺失finally marker仍保留。最终保全JSON在该报告同目录final-evidence/。
