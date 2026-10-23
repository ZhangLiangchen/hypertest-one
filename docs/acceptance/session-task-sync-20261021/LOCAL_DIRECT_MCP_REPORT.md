# 本地Codex → 官方MCP → 公网HyperTest One管理验证

**已验证：这台Mac上的Codex工具启动官方MCP SDK，经配置的stock stdio连接官方默认daemon，通过严格原CA校验的公网HTTPS8080读取并幂等同步真实XBlock任务。** 当前会话ALL_TOOLS中没有hypertest工具名，因此未证明桌面native tool已热加载；没有本地SUT测试或其他测试/lint/build/browser操作。

## 实际对象与语义

- [原XBlock任务v1](https://155.138.206.106:8080/tasks/01a15de5-9aca-76b4-bd57-c673112f2e92)，Project01a15de2-205e-76e6-bfad-7468a724f886，source session01a143f4-4ec0-7451-ab23-8e59c6deb223。
- 首次云端导入DB时间2026-10-21T09:58:10.890320Z；本轮没有刷新活跃源chat或冻结材料，source仍2026-10-21T15:33:54.750222+08快照。原任务IN_PROGRESS/FAIL，15项用例10PASS/2FAIL/3UNKNOWN，两原报告自动10P2F与独立业务11P1F分别保留。
- 用户后续明确允许本地仅MCP管理验证；早先“Mac配置未验/不运行本机验证”的历史结论保留，不能拿本轮授权倒改过去时序。
- 先GET原key回执和固定version1全部3页，61137字符，核对Task全部输入字段、15case全部字段、两份report全部字段及Markdown原始字节。成功后一次调用hypertest_sync_task，使用已ACK原key `uc18-real-session-current-20261021-v1`、完整原body、expected_version0。
- 这是经明确审定的已知成功操作的幂等重放验证，不是UNKNOWN写重试。原body取后端RR快照before.json的receipts[].request_payload，与官方SessionTaskSync模型规范化冻结bundle完全相等，input_digest `a3be2c5222fb7ac223297bc25f9907da60d1f06de2194d9a1453dd508395d10f`。不使用新key、新session或无意义v2。
- MacJournal本轮读后原intent不存在；sync之后ACKED且digest相同，服务实现的新PENDING分支会POST，已ACK分支则只GET。MCP返回原ACCEPTED回执，仍同Task/v1；sync前后再完整GET并直接比较整个current-only JSON，含所有record IDs/revisions/timestamps均完全相等。服务端真实POST次数/HTTP状态由既有Nginx日志独立核对，不以client journal或摘要代替。

## 时间与实际进程/连接

只读阶段2026-10-21T10:35:54.714714Z→10:36:01.014722Z；幂等sync阶段10:37:50.364097Z→10:37:57.906656Z。两阶段均实际exit0。

Mac sys.platform=darwin/UID501；sync SDK PID58031的祖先是实际CodexCLI92407（/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex）及ChatGPT92294。SDK启动stock stdio58045，参数-I/-m/stdio/--autostart与已配置profile相同，连接默认daemon50014；不推断该daemon一定由本轮新启动。daemon按官方原样自身不带-I，保留已配置private cwd/空PYTHONPATH/PYTHONNOUSERSITE，不修改wheel/daemon。

同daemon的实际lsof记录TCP198.18.0.1:52546→155.138.206.106:8080 ESTABLISHED。198.18.0.1只是本机接口记录，不推断物理出口或声称绕过现有VPN。API为标准公网HTTPS TCP；本机stock stdio↔daemon仍使用正常私有Unix IPC。未使用SSH、远端TLS-UDS、forwarding、HTTP fallback、自定义HTTP transport、伪造header或关闭验证。

配置CA永久副本server-ca.crt与原server-trust/ingress-ca.crt解析后的DER指纹同时严格匹配 `9b3cf1b792fc14bec884034757cb7dda95ab8cba0e946cd236cb9a531a1d67e6`。官方默认ApiClient构造真实SSLContext，check_hostname/CERT_REQUIRED默认开启，HTTPX trust_env=False/follow_redirects=False；没有注入transport。成功管理响应、同PID TCP目标与服务端实际公网访问日志共同定位连接路径；未额外捕获TLS cipher/version或修改信任链。

## 原始材料与边界

- 私有脚本accept_local_direct_uc18_sync.py；只调用hypertest_get_task/hypertest_sync_task，官方service实际广告20工具，未调用旧执行工具。
- [只读观察](local-direct/read-observations.json)、[同步观察](local-direct/sync-observations.json)，其中包含窄化进程链/lsof、原回执、Journal前后状态与完整字段核对。
- local-direct/*-receipt.json、*-page-*.json、*-full-task.json为SDK实际返回内容，保留3页原件与前后完整Task；原body及密钥不输出stdout，原body仅从受控快照读取。
- local-direct/read-stdio-stderr.log、sync-stdio-stderr.log及stock-daemon.log为实际日志（默认daemon日志可能为空，按实际保留）；命令stdout元数据由本轮Codex执行工具原输出保留，没有为重新拍证据再调POST。
- local-direct/original-key-idempotent-intent.json持久化SENT_OR_UNKNOWN→ACKED；未来不确定时只GET该原key，不自动POST/newkey/签新token。
- 后端独立before/after、计数及既有Nginx访问日志已完成，见文末；不以client自报宣称旧全库不变。

本轮未创建新Task或有意新revision，未修改云端部署、认证、VPN/ACL、CA或source文件；没有SUT执行。业务原FAIL/UNKNOWN不被管理验证PASS覆盖。Mac管理授权仍仅task:sync、同actor/project，有效至2026-11-20T09:54:23.105383Z；续期保持原actor/client/project并由管理员明确安排。

当前已验证本地官方SDK/stock MCP管理路径。Codex配置enabled_tools两项和skill binding仍保留，当前原生工具目录未出现HyperTest，因此下一会话的native工具加载状态不能以本轮SDK替代。

## 独立服务端对照已完成

- [实际公网Nginx与当前API日志](local-direct/public-nginx-api-log-observations.json)明确：既有VPN出口peer45.76.149.233，恰好一次POST /api/v1/interactive/tasks/sync，HTTP200，Nginx记录2026-10-21T10:37:55.658008913Z，当前source5c03 API记录10:37:55.655788001Z。原key GET与每次固定v1三页均200。该POST是实际网络提交，不是本机ACK缓存GET；没有第二次POST。
- 实际既有路线为公网155.138.206.106:8080 SSL入口→现有Nginx→127.0.0.1:8000当前API；标准反向代理内部HTTP不是客户端HTTP fallback。临时远端TLS socket不存在。本轮未改Nginx、VPN、证书、API配置或授权。
- 原日志有一条请求body落临时buffer文件的Nginx warning，包含同一POST文字；后端首次泛化过滤曾误归为access line，随后按真实peer格式分开解析。同一份既有日志重读，无请求重放；误读历史仍在原JSON，不能据warning再计一次POST。
- [服务端RR前后快照对照](local-direct/server-before-after-comparison.json)：before10:31:17.393871Z、after10:40:19.529349Z；数据库identity/schema一致，Task、完整case_history、report_history和receipts全部字段相等，版本均1，created_at/last_synced_at/originaldigest不变。76表counts零delta，75表全行列对照一致，仅worker_heartbeats一条last_seen_at正常运行观察列变化；Audit/Outbox全行也一致。没有新Task、用例/报告修订、receipt、Job、执行或结论记录。
- 这些快照及hash用于持久化完整性对照，不是SUT执行证明；实际SUT测试仍为0，原业务FAIL/UNKNOWN继续保留。

backend原始before.json、after.json与取证文件保留于Mac私有 ~/.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/。此后不再调用MCP/API或重发同步来补拍证据。

最终独立交付：[SERVER_DIRECT_MCP_OBSERVATION_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/SERVER_DIRECT_MCP_OBSERVATION_REPORT.md)；[INDEPENDENT_LOCAL_DIRECT_MCP_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/INDEPENDENT_LOCAL_DIRECT_MCP_REVIEW.md)。UI/运输/持久化独立评审APPROVE，无P1/P2；没有要求新增验证或重发请求。Mac管理链路的已验时间为2026-10-21，当前native工具热加载仍未证明；不假设stock daemon本轮新启。
