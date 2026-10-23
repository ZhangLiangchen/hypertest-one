# Codex 会话测试任务同步

现阶段，一个 Codex 会话对应 HyperTest One 中一个测试任务。Codex 继续使用真实 SUT 的已有框架进行测试，通过 MCP 同步任务、计划、用例和原始报告；平台提供持久管理、查询和版本历史，不执行测试。

本文针对 [ADR-018](architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 管理入口，字段与交互遵循 [TMP §45](protocol/TEST_MISSION_PROTOCOL.md) 和 [领域规范 §50](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)。旧受管任务、原生材料准入、Runner、Gate、源码传输或设备执行绑定均不是同步准备条件。实际已发布版本、连接和验收范围以对应交接记录为准；本文不因展示命令而执行安装、测试或部署。

## 默认的 XBlock 测试工作流

用户真实目标是 XBlock 测试时，即使只请求测试分析、设计、用例或报告文档，也默认管理同步，不要求用户再次说“HyperTest”。普通非测试文档/知识问答、Blockchain、HyperTest One 开发或验收、其他产品不自动映射 XBlock。共享框架路径、提及 XBlock、历史报告或唯一可用 Project 都不是目标证明。含糊或混合目标先具体澄清，并继续不依赖映射的工作；默认同步不会扩张 SUT 执行、链写入或部署授权。

已安装 skill 的详细执行规则是 `~/.codex/skills/hypertest-interactive/references/DEFAULT_WORKFLOW.md`。Agent 使用既有原生 `hypertest_sync_task` / `hypertest_get_task`，不新增 API 客户端、Hook、Runner 或自动测试任务。正常阶段检查点与逻辑完成前主动同步；强制关 App/失网不能保证最后一刻上传，resume 必须先恢复对账。

1. **确认真实父会话与绑定。** 从可信运行上下文取得当前顶层 Codex session ID，读取实际 XBlock Project/actor/scope 绑定。resume 沿用该 session 的任务；新真实会话使用新 ID 并引用旧 Task/报告。标题、cwd、旧源会话、随机或子代理 ID 不能替代。父会话是唯一串行写者，子代理只交产物，不各自写同任务。
2. **恢复私有账本并先读。** 先检查本 session 的 manifest、不可变 payload/intent、回执与官方 Journal 的合法恢复材料；不清空或编辑官方 Journal。凡已发/可能已发/UNKNOWN 意图，只 GET 原 key；原 key NOT_FOUND 不能授权重放或换 key。随后按当前 session 查询任务，成功则完整分页恢复并固定 task_id/owner/current head。
3. **区分首次管理与读取失败。** 当前官方0.2可能把 by-session 普通404等错误统一返回 `PLATFORM_REQUEST_REJECTED`，不能据此声称任务不存在或猜测HTTP状态。只有能独立确认是首次管理当前真实 session、无既有任务映射且无任何已发/未决意图时，才依据用户已授权的默认流程形成一个稳定初始 key、冻结完整请求，以 `expected_version=0` 调用一次；该授权不来自lookup错误。服务端唯一性和expected0阻止覆盖已存在任务。已知任务/resume读取失败、身份或首次条件不明时停写并报告；创建错误或冲突不自动重试。
4. **按真实阶段冻结新意图。** 有意义的分析/设计写入目标/计划或原报告，case保持业务稳定key；实现只记录真实实现引用；执行仅在本次另已授权的真实远端环境调用已有框架/CI后，提交真实命令、环境、时间与逐项actual/result/原文证据。不为填“执行阶段”补跑测试，未请求阶段明确未执行/不适用原因。已知未执行可NOT_RUN，缺逐项观测仍UNKNOWN，分析/设计完成不自动PASS。
5. **保护旧内容和并发版本。** UPDATE先完整读取最新N，承接 `title/objective/status/plan_markdown/reported_result` 全部Task标量，再显式应用本阶段变化；全部写入请求，避免schema默认值清空计划或回退已有FAIL。cases/reports只提交真实新增/变化条目，条目字段也从原件承接；省略旧key不删除。新执行attempt使用独立稳定report key，修复用例追加revision，旧FAIL/UNKNOWN保留。新业务意图有新seq/key，以expected N冻结请求和“完整基线+delta”的预期状态，先持久标记可能发送，再仅调用一次；收到正确关联ACK并完整读回后才推进检查点。
6. **结束前全量核对当前接受快照。** 固定回执版本N，保存全部分页并按Unicode offset拼接JSON。直接逐字段比较完整合并后的Task、全部cases/reports以及报告UTF-8原文，不只比本次提交子集或摘要/hash。当前MCP投影是 `{task,cases,reports}` 的每key当前资产，不包含全部revision history；历史靠服务端追加约束和每阶段私有原件/快照保全。再不指定version GET当前head；只有H=N才可称截至该观察仍是当前版本。H>N时保留vN已验事实，完整读取H并协调，不能混页、自动覆盖或把vN冒称最新。

Task状态与reported result分开：请求范围已完成可以是 `COMPLETED + NOT_RUN/FAIL`，管理保存成功不代表业务通过。原报告包含秘密时原件私下保留，提交明确标识的脱敏副本及来源边界，读回比实际提交副本，不谎称未脱敏全文一致。

### 私有每会话恢复材料

Agent可用普通文件操作保存，无需新增helper。目录0700、文件0600，拒绝symlink/错误所有者；完整写入持久化后才调用工具。不得把token、整个聊天或隐藏推理放入产物。

| 材料 | 必要内容 |
| --- | --- |
| `manifest.json` | `format=hypertest.agent-session-workflow/v1`；真实provider/session/身份来源、Project/owner/绑定来源、唯一writer、task_id或null、固定key namespace、next_seq、last_accepted、last_verified/head、open_intent、阶段与阻塞。 |
| 不可变 `intents/<seq>/intent.json` 与 `payload.json` | seq/stage/CREATE或UPDATE、稳定原key、expected_version、基线readback引用、完整typed请求、来源引用与文件完整性摘要；摘要不是服务端digest或执行证明。 |
| 只追加events与原始receipts/observations | PREPARED→调用前持久MAY_HAVE_SENT→实际ACK/UNKNOWN/拒绝→读回；保留每次失败，不用后一次结果覆盖。 |
| `readbacks/vN/` 与来源原件 | 每片envelope、完整content/解析JSON、完整合并预期与逐项比较、末尾head观察、原Markdown/日志/来源和脱敏关系。 |

`MAY_HAVE_SENT`之后崩溃按可能已发处理，只GET原key；仅PREPARED且可证完全未进入调用才可第一次发送。旧意图必须明确解决后才可为新内容分配新key；泛化拒绝不能被Agent擅自补成typed409后自动重发。私有恢复格式只属于Agent文件，不改官方Journal schema。

## 手动开发安装与私有配置（非默认工作流）

以下保留通用开发配置参考；已安装的正式管理profile不需重复安装、设备配对或起本机API。遵守操作者当前“远端执行测试”的限制，不将此参考当成本机测试授权。

在此仓库的 Python 3.12+ 虚拟环境安装当前源码：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[interactive]'
```

项目管理员通过现有 `POST /api/v1/interactive/registrations` 签发仅含 `task:sync` scope 的项目集成授权。它绑定 integration actor、client instance 与 Project；旧安装发行及旧 grant 不自动升级权限。新增授权由管理员单独安排，Agent 不接收 Operator key；不要为管理同步运行旧 setup 的设备配对/源码流程。

将授权 token 保存在操作者安排的私有文件（0600），配置与 state 目录保持私有（目录0700、配置0600）。使用绝对本机路径，示例内容不含秘密：

```json
{
  "api_url": "https://your-authorized-platform/api/v1",
  "state_dir": "/absolute/private/hypertest-session-sync/state",
  "integration_token_file": "/absolute/private/hypertest-session-sync/integration.token",
  "host_adapter": {"kind": "unsupported"}
}
```

仅在另已授权的隔离开发配置中，协议支持显式 `allow_insecure_loopback: true` 与 `http://127.0.0.1:<port>/api/v1`；这不是默认连接，也不授权启动本机测试服务。实际远端管理入口使用HTTPS并验证证书，私有CA使用 `ca_file`。无需 `device_token_file`、node、workspaces、host proof 或 execution grant。

打印 Codex MCP 配置（只包含解释器及配置文件路径）：

```sh
.venv/bin/python -m hypertest.interactive_client print-client-config \
  --config /absolute/private/hypertest-session-sync/config.json --format codex
```

把输出用于操作者指定的 Codex MCP 配置。运行命令为当前源码解释器的 `-m hypertest.interactive_client stdio --config <私有配置路径> --autostart`；独立本机 daemon 保存 scoped token 和 SQLite journal，stdout 只承载 MCP。不要把 token 放入 MCP 参数、环境示例、聊天或仓库。既有个人 MCP 配置的修改与重启须根据当前操作者环境处理，不假定此聊天工具目录会热加载。

## 两个工具

`hypertest_sync_task` 接受一次原子更新：

```json
{
  "project_id": "PROJECT_UUID",
  "provider": "codex",
  "session_id": "ACTUAL_AVAILABLE_CODEX_SESSION_ID",
  "idempotency_key": "session-assets-001",
  "expected_version": 0,
  "title": "测试任务标题",
  "objective": "当前测试目标与范围",
  "status": "IN_PROGRESS",
  "plan_markdown": "已形成的测试计划原文或适当节选",
  "reported_result": "FAIL",
  "cases": [{
    "key": "CASE-001", "title": "用例标题",
    "steps": ["复用实际用例步骤"], "expected": "预期结果",
    "actual": "本次观察结果", "reported_result": "FAIL",
    "implementation_ref": "SUT中的已有测试引用"
  }],
  "reports": [{
    "key": "automatic-report", "title": "原始测试报告",
    "markdown": "原始报告Markdown内容",
    "source_ref": "现有测试报告文件或受控来源引用",
    "reported_result": "FAIL"
  }]
}
```

真实 session reference 从当前可用的宿主上下文或已授权会话查询取得；不编造旧会话身份，不上传整段对话或隐藏推理。它只作来源关联，项目授权由私有 token 确定。

新建用 `expected_version: 0`，但必须满足上面的独立首次管理条件；后续有意更新先完整读取当前版本，承接全部Task标量，再用新的稳定幂等key和该版本。相同case/report key内容变化才追加revision；相同内容保持修订、未提交的旧key保留。新执行attempt与不同判定口径（如自动断言与独立业务复核）用独立稳定report key并写明来源，原始失败历史保留。`status` 是任务进度，不等于测试通过；进行中的任务可以已经报告FAIL。

`hypertest_get_task` 有两种互斥查询：

```json
{"project_id":"PROJECT_UUID","provider":"codex","session_id":"ACTUAL_SESSION_ID"}
```

```json
{"project_id":"PROJECT_UUID","idempotency_key":"session-assets-001"}
```

第一种以固定版本分页读取当前任务、用例与原始报告；第二种只查询瘦回执。首片返回 `task_id/version/offset/total_chars/next_offset/content/complete`，format为`application/json`、source为`AGENT_REPORTED`，`content`是current-only `{task,cases,reports}` JSON片段。后续调用使用同Project/provider/session与首片version、next_offset；limit默认/最大24,000字符。按顺序拼content直到complete，再解析JSON并核对来源和原文，不能只读第一页就宣称报告完整。示例续片：

```json
{"project_id":"PROJECT_UUID","provider":"codex","session_id":"ACTUAL_SESSION_ID","version":1,"offset":24000,"limit":24000}
```

offset>0未指定version会拒绝，避免新修订夹入读取；不要自行猜offset，应使用实际next_offset。全历史通过Web任务详情及版本读取查询，不在MCP每片重复附带。服务端保存报告原始Markdown并可完整读回；摘要和hash只辅助关联/完整性，均不能替代报告或充作执行证明。报告是来源明确的提交结果，不自动成为legacy VERIFIED Evidence或发布Gate判定；独立CI核验不作为管理保存的条件。

## 历史候选环境的 SSH stdio 验收参考

此节描述经单独授权的历史隔离验收方式，不是当前默认公网HTTPS管理连接，不据此重新启动候选服务或验收任务。

macOS/Linux客户端支持通用管理提交/读取；`host_adapter: unsupported`不限制这两个管理工具。经操作者授权，可由Mac的官方MCP SDK使用 `command: ssh`，以 `-T -o BatchMode=yes -o PreferredAuthentications=publickey -o StrictHostKeyChecking=yes hypertest-one` 在同一服务器执行候选venv的绝对Python路径：`-m hypertest.interactive_client stdio --config <服务器私有配置路径> --autostart`。

这条SSH连接只承载管理命令的MCP stdin/stdout，不使用TCP/Unix/TUN forwarding，不启动SUT测试或Provider。服务器侧stdio/daemon同UID，配置、scope token与journal保留服务器私有目录；来源session仍来自任务数据，不声称Mac原生会话执行身份得到远端宿主证明。实际命令入口名是`hypertest-interactive`，也可用明确的`python -m`，不存在假定的`hypertest-interactive-client`脚本。

隔离候选daemon可显式使用同服务器loopback HTTP例外；这不授权远端HTTP传token，不改变正式入口HTTPS/CA、SSH host-key或VPN白名单。该模式只证明同服务器隔离候选的管理闭环，不等于现有正式current已升级。可复用[远端验收脚本](acceptance/session-task-sync-20261021/accept_remote_uc18_sync.py)；必须由实际环境准备者提供候选路径、Project映射和私有配置，脚本不创建授权/项目、不迁移部署、不刷新源报告。

## 新会话接续已有测试工作

当前通过文本引用关联任务，没有结构化 parent-task 字段或跨会话接管动作。

1. 使用对原任务有效的授权调用 `hypertest_get_task`，提供原Project/provider/session_id；读取返回的task ID/版本、计划、用例和原报告引用。读失败时先处理具体授权或读取缺口，不编造旧记录。
2. 从新会话的可信上下文取得**新父**session_id。它必须与原session不同；先恢复该新session自身账本并查询它是否已经有Task，已有则复用。读失败不等于不存在；只有符合默认流程的独立首次条件才可创建，不能用旧ID或子代理ID冒充来源。
3. 首次意图设置`expected_version: 0`与独立稳定key并冻结全部字段，在`plan_markdown`写明：`关联原任务：<原Task URL/ID>；来源会话：<原session_id>；原报告：<原report key/ID/URL>；接续范围与剩余工作：…；当前会话：<新session_id>`。原任务有未知同步时保留原key对账要求，不在新任务重发旧副作用。
4. 单次调用`hypertest_sync_task`后按原key/固定版本完整读回，并核对末尾head。只发生交接、尚无新结果时用NOT_RUN；原先缺观测的UNKNOWN保持其历史语义，不改称本任务执行。转引旧报告保持原Markdown与来源（若涉秘密则显式脱敏），计划/标题注明“历史来源报告，非本任务新执行”。原任务不改session或历史。

例如新同步的关键字段为：

```json
{
  "project_id": "AUTHORIZED_PROJECT_UUID", "provider": "codex",
  "session_id": "ACTUAL_NEW_SESSION_ID", "idempotency_key": "new-session-handoff-001",
  "expected_version": 0, "title": "接续测试工作", "status": "IN_PROGRESS",
  "reported_result": "NOT_RUN",
  "plan_markdown": "关联原任务：<原Task URL/ID>\n来源会话：<原session_id>\n原报告：<原report key/ID/URL>\n剩余工作：<具体范围>\n当前会话：<新session_id>",
  "cases": [], "reports": []
}
```

以上是可执行的管理同步步骤，不启动测试、恢复聊天或证明新会话具有旧会话的执行身份。

## 写入失答与版本冲突

daemon 在发送前持久保存查询身份与完整请求 digest（不在 journal 反复复制计划/报告），发送后失答返回 `status: UNKNOWN, query_required: true`。这表示同步状态未知，不把报告的 PASS/FAIL 改成 UNKNOWN。保留原私有 journal，调用 `hypertest_get_task` 查询原 key；再次调用同一 sync 时客户端也只 GET 原回执。404/NOT_FOUND 不能证明旧 POST 未执行，不自动重发、换 key 或创建替代任务。

同 key 不同内容拒绝；expected version 过期拒绝。先读取当前任务和原回执，再根据操作者真实新意图形成下一次更新，不能覆盖另一个会话/客户端已经提交的状态。没有收到授权不能重新签发 token 或改变任务所有者。

## HTTP 对照与页面

| 用途 | 入口 |
| --- | --- |
| scoped 同步 | `POST /api/v1/interactive/tasks/sync` |
| scoped 会话查询 | `GET /api/v1/interactive/tasks/by-session?project_id=…&provider=…&session_id=…` |
| scoped 原 key 对账 | `GET /api/v1/interactive/tasks/syncs/by-key?project_id=…&idempotency_key=…` |
| 管理任务列表/详情 | `GET /api/v1/tasks?project_id=…`、`GET /api/v1/tasks/{task_id}` |
| 版本/原始报告读取 | `GET /api/v1/tasks/{task_id}?version=N`、`GET /api/v1/tasks/{task_id}/reports/{report_id}` |

Web 任务页查询这些管理记录，不显示启动测试、Runner 或 Gate 操作。旧 Run 页面与旧数据继续保留为历史兼容入口。本机开发验收、真实测试资产同步和生产发布的实际完成范围由各自验收记录注明；本文命令不会执行 SUT 测试。
