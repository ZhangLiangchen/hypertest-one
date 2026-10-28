# Host Harness Bridge

> **历史或兼容资料：** 本文中的实施计划、配置步骤和部署/验收状态仅适用于所述 profile 与记录时点，不代表当前部署。现行入口见[文档导航](README.md)和[当前 TODO](TODO.md)；新 Local 接入见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)及 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。旧合同、事实和恢复边界按各自范围保留。

ADR-013 的本机 Bridge 实现使用 `hypertest.harness-bridge/v1alpha1`、`hypertest.tmp/v1alpha2`、`run-persistent-harness/v1`。它只托管宿主 Codex 原生会话与受控工具传输，不连接 Canonical PostgreSQL，不运行 Docker，不读取 GitLab 凭据。

生产配置和迁移步骤见 [容器化部署](CONTAINERIZED_DEPLOYMENT.md)。启动命令为 `python -m hypertest.harness_bridge`；配置仅读取 `HYPERTEST_BRIDGE_*` 显式环境变量，不加载应用 `.env` 或 `get_settings()`。

## Worker 接口

`hypertest.agent.bridge.BridgeClient.from_files(socket_path, execution_key_file, management_key_file)` 使用两把不同的至少 32 字节密钥。文件只授予受信 Worker 和 Bridge，不能挂给 API、Web 或测试容器；socket 目录只授予这两个服务的组，目录挂载保证服务重启后 socket 可替换。

| 操作 | 授权 | 语义 |
| --- | --- | --- |
| `capabilities()` | management | 显式返回 transport / wire / profile / Provider / 固定工具 / 并发容量 |
| `create_session(context)` | execution | 注册唯一 Run / Binding / primary Session / 受控目录，尚未启动外部 turn |
| `start_call(context, contract, call_id, resume)` | execution | 先持久登记调用再启动 Codex；原生 session 建立事件立即持久化 |
| `get_call(context, call_id, cursor)` | execution 或 management | 查询同一调用的安全活动、原生 session ID、待处理工具和终态 |
| `renew(context, call_id)` | execution | 延长短期执行授权，不能恢复已过期授权或已结束调用 |
| `respond_tool(context, call_id, tool_call_id, result)` | execution | 返回 Worker 已验权执行的领域工具结果；重复异文拒绝 |
| `restore_session(context)` | management | 只读核验受控目录及原生 session 文件，不启动模型 |
| `interrupt(context, call_id)` | management | 撤销该调用工具能力、停止该历史调用，返回是否确已停止 |
| `recover(context, call_id, new_epoch)` | management | 仅允许已静止且原生会话存在的失联绑定递增一个代际；不启动模型 |
| `close(context, call_id, terminal=True)` | management | 显式终结整个绑定的 Bridge 会话；不删除 Canonical、原生历史或目录 |

`ExecutionContext` 包含 `run_id`、`binding_id`、`logical_worker_id`、`session_id`、`workspace_id`、`harness_host_id`、`job_id`、`claim_token`、`binding_epoch`、Unix 秒 `expires_at`；可携当前 `mission_id` / `attempt_id`。Worker 必须在签发执行授权前核验数据库 claim，并使到期时间不超过当前 lease 和 120 秒上限。Worker 在长时间领域工具 / Runner I/O 期间仍需独立续约；工具请求和提交结果前再次核验当前 Binding / claim。

管理请求不要求原 lease 仍有效。它仍需准确的 Binding / Session / Job / call / 历史 epoch；可使用 `claim_token="management"` 和 `expires_at=0`。历史代际的查询、中断不能关闭新代际会话或启动新工作。取消须先在平台撤销领域权限，再调用管理中断。普通人工等待恢复不递增 epoch；失联进程接管才做显式 fenced recovery。

`workspace_id` 仅允许 32 位小写十六进制 ID，路径固定为 `HYPERTEST_BRIDGE_WORKSPACE_ROOT/<workspace_id>/repo`。目录必须真实存在且任何受控父目录不能是符号链接。Worker 提供此前从固定源码复制和校验的无凭据工作副本；工具读取时继续校验源文件。Bridge 不接受外部工作路径或可执行命令。

## 原生会话与领域工具

`contract` 仅有 `prompt`、`tools` 和 `timeout_seconds`。工具必须来自固定名单：`get_state`、`request_mission`、`complete_mission`、`request_execution`、`ask_user`、`evaluate_gate`、`submit_report`、`request_gitlab_issue`、`get_issue`。Worker 提供每个工具的 MCP `inputSchema`。Bridge 只验证传输及固定名单；领域授权、输入 schema、依赖、幂等、Proposal 验证、正式执行及 Gate 决策仍由平台负责。

Codex 通过固定受信 Python stdio relay 调用第二个 UDS。relay 只持有当前 call 随机能力，不能新建 / 恢复 / 关闭会话、修改 Run 身份或持有原 Job claim。每 call 同时只允许一个待处理领域调用。工具请求写入 Bridge journal 后进入 `get_call().pending_tools`；Worker 返回结果后才交付给原 MCP 调用。跨 Run token、旧 call token 和已撤销 token 拒绝。

Worker 工具响应预算为 500 KB UTF-8 JSON。`get_state` 的 Canonical 集合默认 30 条，按 `collections.<name>.next_offset` 继续；实际响应达到预算时会减少条数并调整 cursor。较大单行带 `_truncated` 和 `_detail`，使用 `resource=entity`、`collection`、`entity_id` 读取完整原始记录。较大 Mission 契约同样提供 `resource=contract`、`mission_id`；原始 targets、验收规则、上下文和输入均可读，摘要不能代替完整契约。

`prd`、`configuration`、`source`、`evidence` 按 Unicode 字符 offset 返回文本；`entity`、`contract`、`coverage`、`human_inputs`、`operations` 返回 `encoding=json` 的文本页，按 `next_offset` 顺序拼接 `content` 后可解析完整 JSON。每页最多 24,000 字符。大型 PRD 不再复制到每次 Mission 响应中；输入摘要显式指向后续页。响应限制不修改 Canonical 内容、冻结 Mission spec 或已接受结果。

Bridge 启动前以实际 CLI `--version`、`features list` 和 `exec resume --help` 检查所需禁用项与恢复参数，不把不存在的 CLI 能力报告为就绪。

Provider 子进程环境只保留宿主 HOME / CODEX_HOME、PATH、临时目录、locale、明确 Provider 代理 / 证书变量及实际使用的 Provider API key；不继承平台数据库、Bridge key、GitLab、Python 注入或动态链接环境变量。认证文件仍留宿主原路径，不复制进镜像或 Prompt。

首版 capability 明确 `native_shell=false`、`native_filesystem=false`。Codex 强制关闭 shell、unified_exec、多 Agent、apps、plugins、browser、computer-use 和 web search；忽略用户 config / exec rules，仅配置固定 HyperTest MCP。源码与 Evidence 通过 Worker `get_state` 的受控资源读取提供；测试源码通过 Proposal 提交，正式执行通过 Runner。单独的 read-only sandbox 并不阻止宿主敏感文件读取，所以不能在同 UID 部署中去掉这些限制后声称隔离仍成立。后续开启原生 shell 需独立 OS 身份 / 文件系统隔离和真实负向验收。

唯一 HyperTest MCP 使用 `required=true` 与 server 范围的 `default_tools_approval_mode="approve"`，使平台已经约束和授权的工具可在非交互 CLI 中执行。外部提单权限仍由 Worker 的固定策略判断。全局 `--ask-for-approval never` 不意味着 MCP 工具默认允许；未配置 server 策略时，真实 CLI 会返回工具被取消。配置语义见 [官方 Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)和[命令参考](https://learn.chatgpt.com/docs/developer-commands#codex-mcp)。

## 断线、恢复和保留

每个调用先写私有 journal，再启动 Provider。相同 call ID / 同输入只返回已有调用；异输入冲突。Worker 遇到连接错误或 ACK 丢失得到 `OUTCOME_UNKNOWN`，应以固定 call ID 管理查询，不自动重发模型 turn。Provider 原生 ID 首次收到后固定，后续 resume 必须精确匹配该 UUID 且原会话文件存在。

Bridge 每 250 ms 检查 call deadline / grant 到期，失联停止并标记 `OUTCOME_UNKNOWN` / recovery required。Bridge 重启把遗留 RUNNING journal 标为未知，不自动重放。生产 systemd 必须使用默认 control-group 进程终止语义；管理清理只在 Linux PID 和进程 starttime 精确匹配时终止遗留进程。无法证明原进程静止时保持恢复阻断；不能用一个新 native session 假装接续。

Journal 是 Operational 记录，包含调用、输入摘要、脱敏固定活动、原生 ID、工具请求 / 响应及生命周期；不保存原 claim token、Provider stdout / stderr / reasoning 或 Bridge key。工具输入输出可能含 PRD / 源码等业务内容，因此 state 目录为 0700，单文件 0600，纳入业务数据保留策略。活动只保留最近 256 条，单 call 工具最多 256 次，传输上限 4 MB；这些限额不裁剪 Canonical Evidence 或 Audit。

调用查询另返回 `created_at`、`finished_at`、`elapsed_seconds`。只有确认原进程已停止才固定终止时间；重复查询或清理不会继续累加已停止调用的时长。它是原生调用活跃墙钟时间的治理依据，包含工具等待时间，不代表模型计费 token 或精确推理耗时。Worker 按 Run 保存预算及未确认调用的预留；Bridge 无法确认停止时不能把预留当作已释放。

首次绑定把 `harness_max_seconds` 固定为 Run 的总原生调用预算；后续问答、配置更改和新 Job 都不能重置它。每次调用先预留全部剩余额度，确认停止后按向上取整的活跃秒数结算。未知调用保留全部预留，只有显式恢复取得 Bridge 已停止证明才释放未用部分；预算耗尽不再启动下一 turn。阶段 `max_steps` 和 Runner 单次 timeout 同样采用首次固定值。这是墙钟治理，尚未实现按 Provider 计费 token、金额或账号剩余额度的硬限制。

Codex 自身仍会把原生会话历史写入宿主 `CODEX_HOME/sessions` 等 Provider 目录，以便精确 resume。它可能包含 PRD、源码、工具输入输出和 Provider 原始消息；Bridge 的脱敏日志策略不会自动删除这份原生历史。该目录与 OAuth 文件只允许服务身份访问（目录 0700、文件 0600），不得挂入 Web/API/Runner、发布为 Artifact、复制到测试报告或无筛选日志。平台不读取或展示其原始 reasoning，也不把其中内容当作正式 Evidence。会话仍可恢复时应保留原文件；终态后的归档或删除应由操作者按业务保留期限执行，并与 OAuth 凭据分开处理。排障只取固定错误分类和已脱敏事件，避免导出完整会话文件。

## 验收边界

`tests/test_harness_bridge.py` 使用真实 UDS 和替代 Provider 边界测试，验证会话复用、串行 / 跨任务容量、执行与管理授权、过期 grant、旧 owner 拒绝、重启不重放、受控路径与工具，以及环境过滤。它不替代真实 Codex → Canonical → Runner → Evidence → Gate 全链路验收。

`tests/test_persistent_runtime.py` 使用专用测试 PostgreSQL、真实 Git 固定源码副本、实际 Worker 与领域工具，注入 Bridge 和 Docker fingerprint。它验证 run / mission 两类人工问题的回答恢复沿用原 Session、原 workspace 和原 attempt，慢工具期间授权续约，ACK 丢失不重放，native / 源码丢失阻断，以及显式恢复 epoch 递增。报告完成测试单独注入已接受报告记录，只检验 Runtime 的关闭条件，不宣称模型或 Runner 成功；取消测试验证旧工具结果不会交付。

提问 intent 提交后、暂停事务前的崩溃也有独立 Runtime 用例：显式恢复保留问题为 run scope，旧失败 Attempt 保持失败，新 Job 展示原问题；收到回答后同一 native session 在新 epoch 继续。

`tests/test_harness_tools.py` 直接调用实际领域工具、Verifier 和 Gate，验证四种 typed mission 的 Proposal 接受与原子拒绝、状态和源码读取、报告引用及状态新鲜度、Artifact 缺失拒绝，以及 STARTED 操作按原记录对账。失败诊断已接受后可形成最终负向 Verdict 并提交报告，不能因准入检查重复开启诊断；提前请求 Gate 也不能擅自创建诊断 Mission。测试中的 Execution / Evidence 明确是数据库与内容库 fixture，用于检查 Gate 和报告契约，不计作真实 Docker 或模型验收。

本机真实 Codex 0.144.1 传输 smoke 已验证两个 turn 使用同一 native session，且每个 turn 都实际通过 MCP 请求 `get_state`、接收 Worker 回复，再恢复和关闭。该 smoke 使用独立临时工作区；没有创建 Canonical 测试事实或替代完整产品验收。

本分支随后完成本地真实 Codex → Canonical → Docker → Evidence → Gate 的成功链（`RELEASE_READY`），以及失败诊断、Web 显式恢复后的负向报告。Mission / Run 两类问题也已在原 Job、原 Session、原 epoch 下消费回答，随后完成成功报告。逐项运行证据、故障与修复经过、未完成范围见 [ADR-013 验收记录](ADR013_ACCEPTANCE.md)。这些结果不表示生产已迁移：生产仍为 `0a2af9c` / `0012`；本分支 additive migrations 为 `0013_run_bindings` / `0014_harness_operations`。真实 GitLab 提单、其他 Provider 与生产部署分别验收。


## GitLab 受控配置

Worker 的 `HYPERTEST_GITLAB_POLICY_FILE` 指向只读配置；不要把该文件或 token 挂给 Bridge / Web / Agent。配置示例默认关闭实际创建：

```json
{
  "version": "hypertest.gitlab-policy/v1",
  "projects": {
    "<HyperTest Project UUID>": {
      "base_url": "https://gitlab.example.com",
      "project_id": 42,
      "assignees": {"responsible-developer": 7},
      "allow_create": false,
      "token_file": "/run/secrets/gitlab-project-token"
    }
  }
}
```

实际发送需操作者明确授权后设置 `allow_create=true`，并提供项目范围 token（文件不得 world-readable）。没有配置、创建未授权或负责人别名未映射时，工具返回 `DECISION_REQUIRED` 交给持久人工决策；Agent 回答不能修改配置或扩权。

`request_gitlab_issue` 仅接受当前 Run 已接受的活动 Finding，且必须关联同 Run 已校验的 Runner Evidence；Evidence 的 Execution 必须为 `OFFICIAL`，且源码 SHA 与本 Run 的固定输入一致；发送前再次验证 Artifact 内容 hash。平台补入完整 SHA、Finding、Evidence/hash 与稳定 `HTISSUE-<operation UUID>` 关联标记。Agent 提供的描述会转义 GitLab quick actions 和提及，不能通过 `/assign`、`/close` 或 `@其他人` 绕过固定责任人策略。创建协议依据 [GitLab Issues API](https://docs.gitlab.com/api/issues/)。

操作先在 PostgreSQL 保存 PENDING 及授权配置 hash，再发送一次 POST；HTTP 过程中不持有聚合行锁，响应入库前重新验证 claim。超时、断线、服务端失败、重定向或不可信成功响应均保留 UNKNOWN；重新请求同 Finding 不会重复 POST，只按原固定 GitLab 项目和关联标记 GET 对账。找不到或多个匹配仍保留 UNKNOWN。协议不承诺外部 exactly-once；网络客户端禁用重定向，远端错误正文和 token 不写入操作记录或活动。

若工具自身的 STARTED journal 在响应前中断，重复原输入先按 Binding + Finding 找到已持久操作并校验原 input digest，只调用 GET 对账。没有已确认操作时保持 UNKNOWN，不补发 POST。`get_state resource=operations` 提供安全的 operation ID、Finding 引用、状态与已经核验的成功 URL，供 `get_issue` 继续对账；不输出 token、授权配置或完整 draft。

成功仅回写验证过的 Issue iid / 同源 HTTPS URL 与 Finding.external_issue_ref，保留原 Finding 状态及 Gate 决策。`tests/test_gitlab_integration.py` 使用真实 PostgreSQL 和注入 HTTP transport 验证上述路径，未向真实 GitLab 创建 Issue。
