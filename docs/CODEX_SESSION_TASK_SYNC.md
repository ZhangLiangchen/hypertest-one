# Codex 会话测试任务同步

现阶段，一个 Codex 会话对应 HyperTest One 中一个测试任务。Codex 继续使用真实 SUT 的已有框架进行测试，通过 MCP 同步任务、计划、用例和原始报告；平台提供持久管理、查询和版本历史，不执行测试。

本文针对 [ADR-018](architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 新入口。旧受管任务、原生材料准入、Runner、Gate、源码传输或设备执行绑定均不是同步准备条件。实际部署版本、授权与验收环境由操作者核验；源码存在不证明目标环境已经升级。

## 客户端安装与私有配置

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

本机隔离 API 可以显式设置 `allow_insecure_loopback: true` 并使用 `http://127.0.0.1:<port>/api/v1`；远端必须 HTTPS 并验证证书，私有 CA 使用 `ca_file`。无需 `device_token_file`、node、workspaces、host proof 或 execution grant。

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

新建用 `expected_version: 0`；后续有意更新先读取当前版本，再用新的稳定幂等 key 和该版本。修改相同 case/report key 会追加 revision；未提交的旧 key 保留。原始失败历史不能被后续通过结果覆盖删除。不同判定口径（如自动断言与独立业务复核）使用不同 report key 并写清来源，不伪造用例执行历史。`status` 是任务进度，不等于测试通过；进行中的任务可以已经报告 FAIL。

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

## 远端运行与验收环境

管理 MCP 可运行在 macOS/Linux，使用 `host_adapter: unsupported` 不限制这两个工具。测试与验收进程须在操作者指定的测试环境运行；当远程服务器是测试环境时，官方 MCP SDK 与 stdio 客户端也在远端私有目录运行，不以本机测试替代。

如实际连接需要 SSH stdio，使用经核验的 host-key、非交互公钥认证与远端绝对解释器路径执行 `-m hypertest.interactive_client stdio --config <远端私有配置路径> --autostart`。SSH 仅承载管理命令 stdin/stdout，不要求 TCP/Unix/TUN forwarding，不运行 SUT 测试。实际命令入口为 `hypertest-interactive`；不要假定存在 `hypertest-interactive-client`。

stdio 与 daemon 保持同 UID；配置、scope token、journal 留在私有目录。任务 session 是声明的来源引用，不构成宿主执行证明。正式远端 API 使用 HTTPS 并校验系统 CA 或明确配置的私有 CA；仅操作者显式授权的同服务器隔离 API 可用 loopback HTTP 例外。不得通过跳过 TLS 校验、转发或放宽文件权限解决连接问题。

验收使用操作者批准的任务与报告材料、目标 Project 映射、当前版本和独立稳定 key。先读取目标任务，再提交一次；读取瘦回执与固定版本全部分页，核对任务字段、每项用例和报告原文。失答只查询原 key。不要上传整段聊天、认证目录或真实秘密，不以管理同步读回作为业务测试的新执行证明。

## 新会话接续已有测试工作

当前通过文本引用关联任务，没有结构化 parent-task 字段或跨会话接管动作。

1. 使用对原任务有效的授权调用 `hypertest_get_task`，提供原Project/provider/session_id；读取返回的task ID/版本、计划、用例和原报告引用。读失败时先处理具体授权或读取缺口，不编造旧记录。
2. 从新会话的实际可用上下文取得**新**session_id。它必须与原session_id不同；新会话创建自己的SessionTask，不用旧ID同步来假装仍是旧来源。
3. 为新任务设置`expected_version: 0`与独立稳定key，在`plan_markdown`写明：`关联原任务：<原Task URL/ID>；来源会话：<原session_id>；原报告：<原report key/ID/URL>；接续范围与剩余工作：…；当前会话：<新session_id>`。如果原任务已有未决同步，保留原key和对账要求，不在新任务重发旧副作用。
4. 以新session调用`hypertest_sync_task`。只发生交接、尚无新结果时，任务reported_result为NOT_RUN；不要把旧报告PASS/FAIL当新任务已执行。确需转引旧报告时保持原Markdown，`source_ref`指向旧Task/report，并在标题/计划明确“历史来源报告，非本任务新执行”。用`hypertest_get_task`读取新session核对，原任务保持原session及全部历史。

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

## Web人工管理与回收站

项目和任务的管理入口支持编辑、手动状态调整、软删除与恢复。这是本分支的管理能力；实际目标环境是否已部署仍需核验，操作不会启动测试。

- 在项目列表编辑名称、说明、仓库和默认分支，或在ACTIVE/ARCHIVED之间调整状态。项目key保持固定；配置变化不改变历史任务的来源、源码快照或报告。
- 在任务列表或详情编辑标题、目标、计划和进度。可将COMPLETED/CANCELLED任务重新设为IN_PROGRESS继续管理工作；reported result、用例和报告保持原样。例如FAIL任务改为COMPLETED后仍显示FAIL，重开不表示执行过一次新测试。
- 删除后记录进入回收站，原ID、会话身份、用例、报告、同步回执及人工修改历史保留。项目中有未删除会话任务或任何旧受管/原生测试轮次时不能删除；可先归档，或处理会话任务。旧测试轮次不会被连带删除。
- 显式显示已删除记录后可恢复原对象。任务所属项目已删除时须先恢复项目；恢复不自动改变任务进度或结果。相同session不能通过再同步新建替代任务。

已删除项目不能接收新任务、源码传输、上传或新的集成授权，也不能继续下发新的源码采集请求。旧记录和原回执保留供核对；删除本身不表示已经取消此前发出的外部操作。

人工写入带当前项目row_version或任务version；实际保存、删除或恢复后版本递增，同值任务编辑不制造新版本。其他页面或Agent已更新时服务器返回409，先刷新并核对当前值，再按真实意图提交。人工修改版本可在任务的管理历史中追溯，固定旧版本仍可读取；最近人工管理时间与最近Agent同步时间分别保存，不会伪造新的同步、case/report修订或重写原SyncReceipt。网络失答时先刷新确认已保存状态，不盲目重复写入。

普通查询隐藏已删除对象；Agent新同步会拒绝已删除项目或任务。原key对账在当前有效授权下继续返回原接受回执，不能把该旧回执当作对象仍未删除的证明。新的有意同步先读当前版本；人工操作与Agent共享版本保护。管理API、前置条件与状态含义见[TMP§45.3](protocol/TEST_MISSION_PROTOCOL.md#453-operator-项目与任务管理-api2026-10-23)和[领域规范§50.4](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#504-人工编辑进度调整与软删除2026-10-23)。

## HTTP 对照与页面

| 用途 | 入口 |
| --- | --- |
| scoped 同步 | `POST /api/v1/interactive/tasks/sync` |
| scoped 会话查询 | `GET /api/v1/interactive/tasks/by-session?project_id=…&provider=…&session_id=…` |
| scoped 原 key 对账 | `GET /api/v1/interactive/tasks/syncs/by-key?project_id=…&idempotency_key=…` |
| 管理任务列表/详情 | `GET /api/v1/tasks?project_id=…`、`GET /api/v1/tasks/{task_id}` |
| 版本/原始报告读取 | `GET /api/v1/tasks/{task_id}?version=N`、`GET /api/v1/tasks/{task_id}/reports/{report_id}` |
| 人工编辑任务 | `PATCH /api/v1/tasks/{task_id}`，`{expected_version,title?,objective?,plan_markdown?,status?}` |
| 软删除/恢复任务 | `DELETE /api/v1/tasks/{task_id}?expected_version=N`、`POST /api/v1/tasks/{task_id}/restore`，恢复body为`{expected_version}` |
| 项目编辑/删除/恢复 | `PATCH /api/v1/projects/{id}`、`DELETE /api/v1/projects/{id}?expected_version=N`、`POST /api/v1/projects/{id}/restore`；写入匹配项目row_version |
| 回收站列表 | `GET /api/v1/projects?include_deleted=true`、`GET /api/v1/tasks?project_id=…&include_deleted=true` |

Web 任务页查询这些管理记录，不显示启动测试、Runner 或 Gate 操作。旧 Run 页面与旧数据继续保留为历史兼容入口。开发检查、远端测试验收、真实测试资产同步和发布的完成范围由各自记录注明；本文管理命令不会执行 SUT 测试。

## Local 统一发行与自动触发

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。


原管理步骤与契约保持不变。新增 Local 协调器、三宿主接入及固定摘要安装入口见 [Local 状态](LOCAL_MODE_IMPLEMENTATION_STATUS.md)与[发行构建](LOCAL_MODE_RELEASE_BUILD.md)。
