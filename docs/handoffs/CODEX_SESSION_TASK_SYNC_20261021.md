# Codex 会话任务同步交接（2026-10-21）
最新结果：官方0.2已发布，正式远端任务已保存为v1；[实际Task](https://155.138.206.106:8080/tasks/01a15de5-9aca-76b4-bd57-c673112f2e92)。Mac管理路径现已按后续明确授权完成本地官方SDK/stockMCP直连公网HTTPS验证；2026-10-22当前原生目录与直接调用已验证，详情见最新原生验收小节。下方初始缺口/候选阶段按历史保留；前轮发布见[正式验收报告](../acceptance/session-task-sync-20261021/CURRENT_OFFICIAL_REPORT.md)，2026-10-21SDK直连见[管理验证报告](../acceptance/session-task-sync-20261021/LOCAL_DIRECT_MCP_REPORT.md)，2026-10-22原生调用见[最新原生验收](../acceptance/native-mcp-20261022/NATIVE_MCP_REPORT.md)与文末最新小节。

**当前产品职责以 [ADR-018](../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 为准：一个Codex会话对应一个测试任务，Codex同步任务/计划/用例/原始报告，HyperTest不执行测试。用户要求远程环境优先；最早本机开发检查仅为历史。后续明确授权的Mac MCP管理直连已完成，见最新小节；SUT测试仍不在本机执行。**

用户已提供实际远程入口 `http://155.138.206.106:8080/`。主控实测其308跳转到同主机8080的HTTPS。起初本Mac缺少专用SSH别名/key/known-host；这一初始缺口保留在历史中，随后主控已按运维文档固定fingerprint核对一致，建立本Mac独立key/alias并实际公钥登录，远端健康10项通过；旧授权、密码恢复与VPN白名单保全。

已找回公有CA证书并完成`openssl verify_ip`链验证与`curl --cacert`正式HTTPS health200核验。Mac公有证书路径 `~/.local/share/hypertest/session-sync-dev-20261021/server-trust/ingress-ca.crt`（0600，父目录0700），本轮本地独立读取的SHA-256 fingerprint为 `9B:3C:F1:B7:92:FC:14:BE:C8:84:03:47:57:CB:7D:DA:95:AB:8C:BA:0E:94:6C:D2:36:CB:9A:53:1A:1D:67:E6`。无需全局OS信任、跳过TLS或SSH forwarding。登录凭据不进入本文、bundle或JSON证据。

历史阶段（正式发布之前）：current API仍为schema0020，没有新管理接口且尚未升级。同服务器隔离候选以独立空库完成0001→0020→0022迁移，相关86项回归与实际官方SDK管理同步已通过；其源码/运行身份与正式current分开登记，候选成功不意味着正式服务已经切换。

**远端实际同步（2026-10-21 16:05:37 +08:00）**：候选Project `01a15d7d-a1d1-7cbd-a773-450708ed9094`，Task `01a15d7e-7a28-7d0d-9044-cfecc3174199` version1，原session不变。15cases=10PASS/2FAIL/3UNKNOWN，两份原报告原样保存；原key GET回执一致，固定version共3页重建61,137字符JSON并逐字节核对原文。无SUT重跑；正式current未切换，候选UUID不是未来正式映射。见[远端验收](../acceptance/session-task-sync-20261021/REMOTE_REPORT.md)与[机器观察](../acceptance/session-task-sync-20261021/REMOTE_MCP_OBSERVATIONS.json)。停止新增业务写，本轮一个真实候选Task v1已足够。

补充只读检查已逐字段核对全部15个用例与任务完整计划/标题/目标/状态/结果，原观察保留。候选写前后只有管理表新增1Task/15CaseRev/2ReportRev/1Receipt/1Audit/1Outbox，其余76表counts不变（基线已有兼容fixtures，非零）。远端Web通过129测试/build/typecheck，3HTML+24静态HTTP200且proxy实际JSON相同；未做远端browser交互。API/Web PID3551094/3553680，UID999，loopback18101/13101；完整归档SHA4036ba150bf743db317bf51b13ae28363c46b49c5eae5098576ee6e703e50f4b为未提交editable候选，非正式wheel，详见远端验收的独立原始证据。

正式保全不是“全库不变”：61表中58表严格一致，harness_nodes/runtime_control_requests/worker_heartbeats有动态差异，现有基线不能证明具体节点只变心跳列。正式current/schema和正式容器身份/受保护配置metadata保持。该未观测边界不被候选同步成功消除；见[正式对照](../acceptance/session-task-sync-20261021/remote/production-preservation-comparison.json)。

## 已完成

AGENTS、白皮书v1.6、架构/TMP/领域v0.8已明确当前管理同步优先，ADR-017与旧Runner/Gate/受管Harness数据及结论保持历史语义。使用说明见 [CODEX_SESSION_TASK_SYNC.md](../CODEX_SESSION_TASK_SYNC.md)。

MCP沿现有private stdio/daemon/HTTPClient/Journal增加 `hypertest_sync_task`、`hypertest_get_task`。有效项目integration grant的 `task:sync` scope即可使用，不需要execution bind、device/host证明、源码上传、Job、Runner、Gate或CI证明。token只留本机私有文件；源会话ID是来源引用，不是执行身份或授权。

SessionTask共享Project，`(provider,session_id)`唯一，owner/Project固定；用例/报告revision与同步回执保留历史。expected_version防旧状态覆盖；same key异input冲突；失答只GET原key，NOT_FOUND不授权自动重发。reported PASS/FAIL原样保存，sync UNKNOWN不修改测试结论。Report原Markdown存在PostgreSQL，artifact_uri/source_ref只作元数据，不宣称附件已经上传。

真实UC18资产经官方SDK stdio实际同步到隔离本机：Task `01a15d61-87f5-7f9a-adac-4a226f23a7bb`，Project `01a15d61-85ef-7ded-8371-81ce7675f1fb`，version2/12cases/2reports，IN_PROGRESS/FAIL。自动10PASS2FAIL和独立业务11PASS1FAIL分别保存，原文逐字节读回；省略cases没有删除已有资产，version1报告仍可读取。旧执行各表计数前后一致，没有新SUT执行。完整证据见[本机检查](../acceptance/session-task-sync-20261021/REPORT.md)。

## 远程同步所需的确定步骤

1. 使用操作者实际提供/核验的远程访问配置；不要猜旧Mac凭据，不复制私钥或把秘密写进报告。远程版本/schema/API/工具能力须实际核验，源码存在不代表线上有新接口。
2. 远端使用[15项管理资产V2](../acceptance/session-task-sync-20261021/UC18_REMOTE_SOURCE_BUNDLE_V2.json)，保持真实session `01a143f4-4ec0-7451-ab23-8e59c6deb223`、case/report keys与原文。该bundle无目标Project UUID。CASE013/014/015从15:33:54已冻结的03a定义补入，均UNKNOWN并注明无逐项结果；没有刷新活跃SUT文件或原报告。本机原[12项快照](../acceptance/session-task-sync-20261021/UC18_SOURCE_BUNDLE.json)及既有回执独立保留。
3. 查用户授权的现有XBlock Project与同session任务；如已有任务，读取当前version和原同步key。只有目标环境确实支持且授权具备后，再形成明确的下一次同步。不要盲POST创建重复Project或session。
4. 原始捕获时间15:33:54 +08:00、源会话仍active；本机开发检查导入12执行项。远端V2派生于15:51:38 +08:00，保存全部15设计项，其中12项保留自动10PASS/2FAIL，3项UNKNOWN；两份报告字节不变。任务保持IN_PROGRESS，不把completion.json或报告标题当作聊天已结束。
5. 远程同步必须独立记录目标/实际授权范围、稳定幂等key、版本、实际回执与原文读回；写失答保留原journal，只GET原key。测试结果已存在，不重跑SUT来证明平台同步。

候选验收当时没有完成远程部署或正式schema升级。若远端尚无当前管理接口，先报告具体能力缺口并形成可审阅的最小变更，不把本机成功叙述成线上已完成。

主控已安排同服务器隔离候选，正式current/数据库不由本验收改动。实际候选路径/授权准备完成后，Mac官方SDK可经受控SSH命令承载远端MCP stdio（无forwarding），由远端私有daemon访问候选loopback API；正式连接仍遵守实际HTTPS/CA。执行入口和边界见[同步说明](../CODEX_SESSION_TASK_SYNC.md#远端运行与验收环境)。候选SDK脚本保存独立外层intent，失答重启仅GET原回执；分页固定version，15用例与2份报告完整拼接核对。

## 本机状态与保全

历史本机API `http://127.0.0.1:8101/api/v1`，Web `http://127.0.0.1:3001`（后续已停止）；实际SDK配置在 `~/.local/share/hypertest/session-sync-dev-20261021/mcp-config.json`，token、journal、bootstrap intent与runtime.env同目录私有保留。配置不含device/host执行能力。进程由后端/UI执行者维护，当前PID和只读重启验证以各自最新回报为准，不按历史PID随意kill。

新隔离数据库/现有数据均保留；不要删除volume、worktree、私有journal或原报告。不重复运行旧native材料验收来推进当前管理任务，不绕过原UNKNOWN对账，也不重解释旧正式结论。开发工作不默认含生产部署、迁移或访问策略变更。

## 2026-10-21：正式发行身份与远端接续（本节优先）

用户已明确授权继续发布并同步；随后再次要求这台服务器作为测试环境，不在 Mac 执行测试。新的 lint、test、build 与 SDK 验收只在 GitHub CI 或远端运行。此前本机开发检查保留其历史身份；本机 API8101/Web3001 已由远端运维负责人协调停止，数据保留。

**工作区分开保留：** 当前聊天原 cwd `/Users/zhangliangchen/PycharmProjects/hypertest-one` 仍为 `codex/native-framework-evidence@5a68dd1bd6375fad0b271b2b86af48bdf857fe31` 加原有 dirty/private 材料，包含旧 `pyproject` 0.1.0。不要从该目录直接重新发布或以 `uv run` 声称官方0.2客户端。公开发行工作区为 `/Users/zhangliangchen/.codex/worktrees/session-management-release/hypertest-one`，当前为干净的 `main@5c03e4d90bed69b6420238849cbb3a8bae2f4c42`。原发行分支 `codex/session-task-management` 的 head `d23dee74c82494b86f9974b9529799a9081969ed` 已经 PR22 合并并保留分支引用。实际部署源使用合并后的5c03（相同公开源码树），不是旧4036候选快照。

GitHub 仓库实际是 PUBLIC。PR22 仅54项通用源码/规范/测试/安装资源，经独立只读公开安全评审后推送，未包含真实SUT bundle、报告、acceptance原件、私有handoff或浏览器运行日志。原件仍在本机受控目录。PR：https://github.com/ZhangLiangchen/hypertest-one/pull/22 。

- PR精确head CI39569871679通过；合并精确SHA CI39573509731也通过：Python1049 passed/21 skipped/57 warnings，lint与迁移通过；Web129 passed、typecheck/build通过。原日志在 `docs/acceptance/session-task-sync-20261021/release/`，不公开私有验收目录。
- 官方 tag `mcp-v0.2.0` 指向 `5c03e4d90bed69b6420238849cbb3a8bae2f4c42`；发行 workflow39574028721通过并在09:04:11Z发布。发行：https://github.com/ZhangLiangchen/hypertest-one/releases/tag/mcp-v0.2.0 。wheel为 `hypertest_one-0.2.0-py3-none-any.whl`，369859 bytes，SHA256 `d7e7bfdbb5a5a25bab343bf695185cc9587c745605c667ba28a9d23d336a6dd3`。这是GitHub远端构建及独立安装smoke，不是Mac测试。
- 固定Git源码包 `release/hypertest-one-0.2.0-5c03e4d90bed.tar.gz`，2056952 bytes，SHA256 `8ed633ea37ad295730d2420149b9744552cf873d6bbd57682962db6c63e2bf52`；458文件，tree `1996cf7161222f7ec4359f1831774735adba8eb6`。旁边verified manifest记录逐文件身份与精确main CI。后端负责人是唯一远端发布/备份/保全owner；本节不代表切换已完成，须引用其实际发布报告。

### 正式管理同步的传输边界与当前待办

服务器本身访问公开HTTPS能验证旧CA/hostname，但被现有VPN来源ACL拒绝403；正式API的 `allow_insecure_loopback=false` 继续保留。不能为验收改白名单、关闭TLS要求、SSH转发、伪造X-Forwarded-Proto或修改wheel。

用户授权范围内已由主控明确批准一个临时、私有的真实TLS-over-UDS管理listener：独立短期CA/server cert（SAN localhost），socket预绑定0600、目录0700，仅开放新task/capabilities的明确方法和路径，同最终源码及正式数据库但为不同进程。监听器由后端负责人管理，schema22/正式API ready后方可用于业务同步。其实际创建、负向CA/hostname测试、路由拒绝及删除/停止状态以远端原件为准。

私有脚本 `docs/acceptance/session-task-sync-20261021/accept_official_uc18_sync.py` 仅在远端以官方wheel venv的 `python -I` 运行。它通过公开构造参数注入真实 `httpx.AsyncHTTPTransport(uds=…,verify=CAcontext,trust_env=False,retries=0)`，复用官方 `ApiClient → InteractiveService/Journal/LocalServer`，由官方SDK启动原wheel的stock stdio（不autostart）。准确称为“官方0.2库/stdio + 私有transport bootstrap”；stock daemon CLI没有原生UDS配置点。preflight GET使用同一真实TLS transport。既无mock HTTP，也不伪造scheme/认证。

正式SDK启动之前的历史待办：等待后端API切换ready、实际Project映射和独立task:sync私有授权，当时尚未在正式库写入本任务；已完成状态见文末最新小节。优先复用已核验的现有XBlock Project；不得用隔离candidate UUID作正式身份，也不得猜GitLab子仓库路径。正式intent使用独立稳定key并先GET目标版本；SENT/UNKNOWN之后只GET原key，不重发。

源材料继续冻结为 `UC18_REMOTE_SOURCE_BUNDLE_V2.json`，SHA256 `278f5003a287746b5abba528eed1f04f2d1f31122f0b8fea5e39c37601662f3c`，15用例/两份原报告。源会话是 `01a143f4-4ec0-7451-ab23-8e59c6deb223` 的真实SUT测试聊天，**不是当前HyperTest开发聊天**。保留12项自动结果10PASS/2FAIL，另外3项无逐项结果为UNKNOWN；独立业务11PASS/1FAIL口径在原报告中单独保留。任务IN_PROGRESS/FAIL是Agent reported状态；正式管理同步验收成功不会改写业务结论，也不表示重跑SUT。

正式写前脚本在远端核对冻结plan/两报告中的疑似凭据模式；任何疑似值只私下复核，不打印秘密、不静默改原文。单次实际MCP写入后查询原key瘦回执，并固定接受version读取全部分页，核对所有task/case/report字段及原始Markdown。最终实际Task URL/ID、Project映射、同步时间和证据文件在完成后补充，不能以候选结果代替。

### 后续新会话接续

1. 下一会话先使用已发布源码工作区/精确commit；阅读本节与后端正式发布报告，核验实际服务版本及授权路径。Mac不运行测试，远端为测试环境。
2. 对原SUT任务用有效的项目授权GET实际source session任务，完整读取固定version全部分页与原报告。保留Task URL/ID、source session、版本和未决原key。
3. 新会话必须使用自身真实session_id，创建自己的SessionTask（expected_version0与独立稳定key）。在plan_markdown明确原Task URL/ID、原source session、原report引用、剩余工作和当前session。不得复用旧source session假装原聊天继续；移交材料不是新执行结果。
4. 旧任务存在未知同步时只按旧key对账，不能通过新Task重发旧副作用。尚无新结果则新任务reported_result为NOT_RUN；转引旧报告明确为历史来源，并保留原结果/来源。

### 安装前Mac管理连接盘点（只读静态元数据，未启动客户端）

`~/.codex/config.toml` 存在，但没有HyperTest MCP entry；`~/.codex/skills`、`~/.agents/skills`、项目skills未发现已安装HyperTest skill；PATH没有 `hypertest-interactive`。原repo `.venv` 的dist-info显示 `hypertest-one==0.1.0` editable，不能当官方0.2安装。历史私有 `~/.local/share/hypertest/session-sync-dev-20261021/mcp-config.json` 指向已停止的 `http://127.0.0.1:8101/api/v1`，只属先前演练；未被Codex全局登记，保留原state/journal和token，不改指向。

待正式Project映射和独立Macclient授权完成后，在全新 `~/.local/share/hypertest/codex-session-management-20261021/` 安装已发布官方0.2wheel并保存private config/token/state。标准目标为 `https://155.138.206.106:8080/api/v1`，使用已核验的原ingress CA文件；`host_adapter`为unsupported，`allow_insecure_loopback`为false，无device/source/execution授权。新Codex entry拟为 `mcp_servers.hypertest_management`，使用官方venv绝对Python路径，`-I -m hypertest.interactive_client stdio --config <新私有配置> --autostart`。安装官方bundled skill，保留所有其他Codex配置。Mac只安装/配置管理连接，不调用SDK/tools或运行local测试，不宣称热加载或连接已验收。远端临时TLS-UDS与bootstrap的配置绝不写入Mac，也不交给后续会话当长期入口。

### Mac profile的项目与工具边界

新全局连接仅绑定真实XBlock Project/来源工程，不能把HyperTest开发聊天、Blockchain或其他测试会话默认同步为XBlock任务。实际Project映射/actor/client由正式环境核验后写非secret本地binding说明；其他项目需各自授权与配置。本SUT源会话的冻结材料与当前开发会话身份分开。

官方0.2的 `InteractiveService.tools()` 合并capabilities的全部interactive与execution tool定义，**不按task:sync scope缩小广告面**（静态为20项，其中旧执行工具9项）。新scope仅限制服务端授权。Codex新entry将使用 `enabled_tools = ["hypertest_sync_task", "hypertest_get_task"]` 限制此管理profile对Agent暴露的工具，不改旧managed profiles或wheel。该字段已先检查本机已安装Codex二进制关键字，再实际打开[官方配置说明](https://learn.chatgpt.com/docs/config-file/config-reference)与[官方MCP示例](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)，其类型为工具名数组白名单。安装完成后仍准确注明“已配置，待新会话加载；该Mac连接未做本机验收”。

### 源测试工作的明确剩余项（管理同步成功不关闭这些项）

- 冻结时源SUT聊天仍在进行中；本批为capture快照，不能声称已取得该聊天最终完成结论。后续如经授权取得更完整报告，须以明确新意图同步修订并保留本批原件；新聊天则创建自己的任务并引用原Task，不能冒充原source session。
- 自动报告的CASE-002/CASE-009失败继续保留；独立业务报告的11PASS/1FAIL属于另一判定口径，不能覆盖自动失败。具体业务问题与处理状态应回到两份原报告及源任务核对，不由平台同步验收推定已修复。
- CASE-013/CASE-014/CASE-015只有设计定义，冻结来源没有逐项结果，当前为UNKNOWN。不得凭摘要、未列入旧自动报告或平台保存成功推断NOT_RUN/PASS；取得实际新材料后按真实来源记录。
- Mac新管理连接即便安装配置完成，也没有在本机启动或验收。后续新会话可加载已配置的管理工具；测试/验收执行位置继续遵从操作者指定的远端环境。不得以配置文件存在声称该Mac已建立成功连接。


## 最新完成状态：正式远端发布与管理同步（2026-10-21，本节优先）

**已发布官方0.2并在用户远程测试环境完成真实任务同步。** 实际任务：[XBlock UC18](https://155.138.206.106:8080/tasks/01a15de5-9aca-76b4-bd57-c673112f2e92)，正式Project XBLOCK=`01a15de2-205e-76e6-bfad-7468a724f886`，Task=`01a15de5-9aca-76b4-bd57-c673112f2e92`，version1。不是前述候选Project/Task。后端实际交接current源5c03/schema22，同原PG数据库OID16384/system_identifier7697580503987753003；部署/备份/保全原件由后端owner提供，不以客户端hash冒称部署证明。

正式SDK在远端以官方0.2wheel非editable安装运行，一次实际Task POST；原key `uc18-real-session-current-20261021-v1` GET回执一致，3页固定v1共61137字符重建JSON，task/case/report全部字段及两份Markdown原文核对一致。15用例=10PASS/2FAIL/3UNKNOWN，独立业务11PASS/1FAIL另保留；任务IN_PROGRESS/FAIL。写前17:58:09+08凭据模式复核0疑似，17:58:12+08完成管理验收；SUT执行0。完整结果：[正式管理验收报告](../acceptance/session-task-sync-20261021/CURRENT_OFFICIAL_REPORT.md)，原件在其current/子目录。该成功是内容同步证明，不是新的业务测试执行结论。

17:59:31+08，新的Mac client grant在远端仅GET原key与固定v1分页，验证同Project/owner/sourceSession/Task与全部task字段；没有第二次Task POST。两client独立token、同owner `interactive:01a15de2-20b7-702b-9bdd-32f27d89fb57`，仅task:sync。Project repository_url实际未设置，仅用户GitLab根URL已知，不推断子仓库/branch。官方SDK的20项广告工具记录在原观察；本管理路径仅使用2项。

临时TLS-over-UDS真实API仅用于远端验收，同正式DB但不同于当前Docker API PID；官方Service公开transport构造与stock stdio组合，不是stock daemon CLI新增UDS选项。客户端context和stdio已退出，remote-state保留Journal但无interactive.sock；后端收到完成后已发SIGTERM关闭临时TLS listener，其最终socket消失证据由后端owner记录。不要将私有UDS/短期CA配置用作下一会话长期连接。

**Mac已配置，待新会话加载；该Mac连接未做本机验收。** 新私有root `~/.local/share/hypertest/codex-session-management-20261021/`，官方0.2wheel及已测版本Mac binary依赖；新config/token0600、state0700且配置时为空。标准公网HTTPS8080与原永久ingress CA，loopbackfalse；无执行/device/Operator权限。原dev配置/Journal/数据未改。`~/.codex/config.toml`只追加hypertest_management，原字节及0600完整备份保留；备份路径在新root/backups/。新entry用绝对Python-I、private cwd、空PYTHONPATH避免autostart子进程影子，enabled_tools仅hypertest_sync_task/hypertest_get_task。

官方bundled skill装于 `~/.codex/skills/hypertest-interactive/`，相邻PROJECT_BINDING.md明确仅XBlock，不把本HyperTest开发/Blockchain或其他聊天默认为XBlock；框架路径本身也不能区分SUT。所有Mac工作仅安装/静态配置/metadata，未启动MCP/SDK/测试/lint/build/browser。token先在远端以新grant只读核验后私有传输；不出现在文档/仓库。

下一会话遵守上文接续步骤：GET实际旧Task后，用新会话自身真实session_id创建自己的Task（expected_version0），在plan_markdown/source_ref显式链接上述TaskURL、源session01a143f4-4ec0-7451-ab23-8e59c6deb223、两原报告与剩余项。不复用旧session冒充源聊天，也不把保存成功当用例通过。源chat最终结论/原失败/3项UNKNOWN仍未关闭。原dirty工作区@5a68与干净发布工作区main@5c03继续分别保留，后续发行从明确发布源进行。

### 授权到期与续期

Mac管理grant为30日授权，精确expires_at `2026-11-20T09:54:23.105383+00:00`（新加坡时间2026-11-20 17:54:23.105383+08:00），grant ID `01a15de2-2102-798d-aa38-f1794aa77fdc`；client_instance_id `e43fb03f-e7aa-4a5b-8a9b-d54b65d9fd20`。续期由管理员显式安排，保留actor_identity_id `01a15de2-20b7-702b-9bdd-32f27d89fb57`、该client ID、Project `01a15de2-205e-76e6-bfad-7468a724f886` 与仅task:sync范围；不要临时更换任务owner、默认Project或扩大scope。到期不是自动签新token、换key或重发Task POST的授权；原UNKNOWN仍仅以原key GET对账，保留Journal。远端本轮短期client expires_at2026-10-22T09:54:23.052698+00:00，短期TLS配置只作历史，不是长期Mac连接。非secret原始授权元数据见../acceptance/session-task-sync-20261021/current/AUTHORIZATION_METADATA.json。

时间分列：源材料冻结 `2026-10-21T15:33:54.750222+08:00`；平台同步SDK核验完成 `2026-10-21T17:58:12.018334+08:00`。后者是实测完成时间，不能冒称数据库created_at；如需精确数据库接受时间以正式任务行原件为准。

旧Mac本轮开发MCP daemon55116（旧8101配置）已按精确PID/argv核对后SIGTERM并确认PID/socket消失，旧Journal保留；没有停止其他服务。新Macmanagement state仍空，未启动客户端。

最终独立补充：平台DB created_at/last_synced_at实际2026-10-21T09:58:10.890320Z（17:58:10.890320+08），SDK完成17:58:12分开登记；76表中只有Task+1/CaseRev+15/ReportRev+2/Receipt+1/Audit+1/Outbox+1，旧执行/Job/Evidence/Verdict/native表计数不变但不据此假称全列不变。正式临时TLS PID3688162/监听已消失，自有stale socket已移除，client sockets不存在，私有材料保留；无wrapper finally record，不声称engine.dispose已证明。旧远端候选API18101/Web13101/daemon也由后端核验停止，源/库/Journal/授权保留。远端internal Web桌面1440/手机390实际browser检查经UI独审APPROVE；public HTTPS browser E2E未测。具体限制与原件见正式管理报告及后端/UI独立报告。

UI/TLS/当前DB计数独立只读评审已完成APPROVE，精确报告：[INDEPENDENT_UI_AND_TRANSPORT_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/formal-remote-20261021/ui-review-20261021T100422/INDEPENDENT_UI_AND_TRANSPORT_REVIEW.md)。其原文保留internal/public边界、第一项case展开覆盖与全部15项SDK字段核对区别、旧数据保全另据部署证据、cleanup失败历史与engine.dispose marker未确认。

最终后端发布/健康/保全已完成，无待处理阻塞；精确原件：[CURRENT_RELEASE_SERVER_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/formal-remote-20261021/CURRENT_RELEASE_SERVER_REPORT.md)。后端实际10:18:22Z五服务healthy、Bridge active，原PG身份/start/卷及SSH/VPN/auth保护项一致，维护锁可获取；60旧业务表7874原PK保留，逐列比对仅一Harness节点四项运行观察列变化，182 FK validated/0 orphan，采集范围内文件/metadata exact。此处引用其实际结论，不新增验证、不把有记录的运行列差异改称全库不变；历史失败与cleanup缺失finally marker仍保留。最终保全JSON在该报告同目录final-evidence/。

## 最新后续授权：本地MCP管理直连已验证（18:37+08）

用户明确允许本地仅MCP管理验证后，实际从本地Codex工具启动官方0.2 SDK→配置stock stdio(--autostart)→默认daemon→标准公网HTTPS8080/严格原CA，先原key+完整v1 GET，再原ACK key/完整原body/expected0一次幂等sync，再原key与完整固定v1 GET。原Task/v1、15cases/2reports及整个current-only JSON的IDs/revisions/timestamps完全不变；保留10P2F3U、业务11P1F，未新Task/newkey/v2、未刷新SUT、未运行本地SUT/pytest/lint/build/browser。详细原件与精确时序见[本地直连报告](../acceptance/session-task-sync-20261021/LOCAL_DIRECT_MCP_REPORT.md)。

实际Darwin UID501，SDK58031祖先CodexCLI92407/ChatGPT92294，stockstdio58045接默认daemon50014（不声称daemon一定本轮新启）；同daemon lsof至155.138.206.106:8080 ESTABLISHED。原CA指纹一致，无SSH/远端UDS/HTTPfallback/TLS例外；本机正常stock IPC仍为UDS。早先未验配置阶段原文保留历史。当前ALL_TOOLS无hypertest，未证明桌面native工具热加载，只确认实际Codex启动官方SDK/MCP管理路径。服务端POST与旧状态独立对照由后端现有日志/快照补充，不为取证重复写。

本地直连最终独立证据已到：Nginx现有VPN peer45.76.149.233于10:37:55.658Z恰一POST200，当前5c03 API亦记录同POST200，原key与v1分页GET均200；走公网SSL入口与既有反向代理，无远端临时UDS。76表counts零delta，75表全行列对照一致，仅worker heartbeat一last_seen_at变化；Task/case_history/report_history/receipt全部字段、原v1、timestamps/digest不变。source日志有一条body-buffer warning曾被首次通用过滤误计为access，按真实peer格式纠正，原误读保留且无请求重放。详见LOCAL_DIRECT_MCP_REPORT文末及local-direct/两份独立JSON；后续不再重复验证。

最终独立交付：[SERVER_DIRECT_MCP_OBSERVATION_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/SERVER_DIRECT_MCP_OBSERVATION_REPORT.md)；[INDEPENDENT_LOCAL_DIRECT_MCP_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/INDEPENDENT_LOCAL_DIRECT_MCP_REVIEW.md)。UI/运输/持久化独立评审APPROVE，无P1/P2；没有要求新增验证或重发请求。Mac管理链路的已验时间为2026-10-21，当前native工具热加载仍未证明；不假设stock daemon本轮新启。

## 最新：2026-10-22原生MCP已加载并直接调用

root今日实际目录出现mcp__hypertest_management__hypertest_get_task/sync_task并直接调用get8/sync1，没有启动外部SDK/stdio或直接HTTP脚本。原key/原完整body/expected0经已ACKED分支在线GET原receipt；实际公网日志9GET0POST全200，不称今日新POST。两组固定v1全部3页重建61137字符，所有Task/case/report字段与原Markdown bytes、整对象ID/revision/timestamp/source、原完整历史均相同；Task仍v1/15cases/2reports/1receipt、IN_PROGRESS/FAIL及10P2F3U，两报告独立业务口径保留。

76表count零变化，75表原PK/列值对照一致，仅worker heartbeat一last_seen_at正常变化，Audit/Outbox同。原生调用身份由root工具原件、网络行为由现有Nginx/API日志分别证明；没有清Journal/换key/签token/改配置或SUT测试。旧未验/SDK阶段原件保持历史时点，不以昨日PID冒充今日进程。首get02:48:27.937Z只是并行文档和GET都返回后的捕获上界，精确请求时刻据Nginx；sync await窗口02:52:26.256→02:52:28.052Z，最后结果02:53:02.442Z。

原生完整报告：[NATIVE_MCP_REPORT.md](../acceptance/native-mcp-20261022/NATIVE_MCP_REPORT.md)。wire正文与apply_patch导出txt的额外末LF区别已注明，原件未改，报告Markdown原字节exact。仅原生可用/调用证据已确认，加载触发机制未单独观察，不声称无重启热更新。继续保持其他Project独立授权、新会话真实来源与旧keyUNKNOWN只GET原则。

2026-10-22最终原生验收已由root接受PASS，独立评审[INDEPENDENT_NATIVE_MCP_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/INDEPENDENT_NATIVE_MCP_REVIEW.md) APPROVE/无P0/P1/P2，服务端[SERVER_NATIVE_MCP_OBSERVATION_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/SERVER_NATIVE_MCP_OBSERVATION_REPORT.md) PASS；无待审批/待验证项。至此当前原生工具目录可见、直接get8/sync1、ACKED sync在线GET与全部资产原文/历史不变均有实际证据；停止新增调用/测试，保留所有旧阶段历史和授权边界。

## 2026-10-22：全局默认 XBlock 管理工作流（文档与静态交付）

用户已授权真实XBlock测试工作默认同步，不要求每次显式提HyperTest。全局规则已实际加载到当前主控上下文；installed skill入口由相邻负责人更新，详细流程已安装为 [DEFAULT_WORKFLOW.md](/Users/zhangliangchen/.codex/skills/hypertest-interactive/references/DEFAULT_WORKFLOW.md)，仓库用户说明为 [CODEX_SESSION_TASK_SYNC.md](../CODEX_SESSION_TASK_SYNC.md)。这是Agent阶段义务，不是后台聊天监听或SessionEnd上传保证；本HyperTest One开发/验收会话不创建XBlock Task。XBlock测试分析/设计/用例/报告即使仅形成文档也触发，普通非测试文档、Blockchain、其他产品和不明目标不误绑。

真实当前父session为唯一串行writer；子代理只交产物。一session一Task，resume先私有intent/Journal原key对账与完整head读回，新真实session文本链接旧Task/报告。阶段intent使用稳定seq/key与冻结完整请求，UPDATE承接Task全部标量、只提交真实case/report增量，完整预期为上版全部资产加本阶段delta。新执行attempt独立report key，CaseRevision/原报告与旧FAIL/UNKNOWN保留；默认同步不授权补跑SUT、链写或部署。阶段未请求/未执行写明原因，缺逐项真实观测仍UNKNOWN。

**本轮review修正已落规则：** 官方0.2 by-session可能把普通404等拒绝泛化为 `PLATFORM_REQUEST_REJECTED`，不能据此确认不存在。先lookup，成功就复用；只有能独立确认首次管理当前真实父session且无既有Task映射/任何已发或未决intent时，依据已授权默认流程形成一次独立expected0初始意图，服务端唯一性/version检查防覆盖。该授权不来自lookup错误。已知Task/resume读取失败阻塞，旧写UNKNOWN或原key NOT_FOUND只GET原key，不换key/重POST；泛化错误也不得猜成typed409后自动覆盖。

每次接受后及逻辑完成/交接前，固定接受version完整分页，逐字段/UTF-8原文对照完整合并预期，保存原件；再GET无version的head。head变化只保留原版本已验事实并读取新head、协调writer，不混页/自动补写。MCP仅有每key当前资产投影，不声称返回所有history；旧历史以服务端追加约束和私有每阶段原件/快照保全。

当前真实UC18 v1的15cases/2reports、10PASS/2FAIL/3UNKNOWN及旧原key只用作本次**静态流程推演**，文档owner未再调用MCP/API/SDK/SSH；本轮未创建或修改任何Task、未执行SUT。先前已验原生get8/sync1仍是上一小节的独立事实；真实新session首次create、阶段update、UNKNOWN/冲突恢复与跨会话常态化本轮没有实跑，不把文档设计称作E2E验收。私有交付报告：[DEFAULT_WORKFLOW_DELIVERY_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/default-workflow-20261022/DEFAULT_WORKFLOW_DELIVERY_REPORT.md)。

指定model owner仅远端格式/引用检查已PASS：2026-10-22T03:29:31Z，官方quick_validate单次exit0（Skill is valid!、stderr空），5相对链接存在，最终reference `4ff9117a9e897e63663ccc621197763c05d618592c80182a10c39ba9c7afdf2f` 与安装副本逐bytes相同。远端证据目录 `/opt/hypertest/deployments/adr018-20261021/skill-format-20261022T032741Z/`；本机只读副本在上述交付报告链接中。未安装依赖、无业务调用/数据或配置变更；格式通过不证明阶段业务流程。
