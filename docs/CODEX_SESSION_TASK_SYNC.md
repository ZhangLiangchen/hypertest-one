# Codex 会话测试任务同步

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。


现阶段，一个 Codex 会话对应 HyperTest One 中一个测试任务。Codex 继续使用真实 SUT 的已有框架进行测试，通过 MCP 同步任务、计划、用例和原始报告；平台提供持久管理、查询和版本历史，不执行测试。

本文针对 [ADR-018](architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 新入口。旧受管任务、原生材料准入、Runner、Gate、源码传输或设备执行绑定均不是同步准备条件。实际部署版本、授权与验收环境由操作者核验；源码存在不证明目标环境已经升级。

**当前操作边界：** 下列安装、`hypertest_sync_task` / `hypertest_get_task` 和私有客户端流程继续有效。[ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) 已接受 Hooks 自动触发与 MCP 共用同步协调器的设计；该协调器、自动触发、Claude Code / DeepSeek harness 适配及统一发行 / 安装均 **NOT IMPLEMENTED**，见文末设计章节、[本地实施计划](LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)与[统一发行安装设计](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。本次文档修订不安装 Hooks、不修改全局默认技能、不启动上传；现有 XBlock 流程继续只使用已授权的原生同步 / 查询工具。

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

## HTTP 对照与页面

| 用途 | 入口 |
| --- | --- |
| scoped 同步 | `POST /api/v1/interactive/tasks/sync` |
| scoped 会话查询 | `GET /api/v1/interactive/tasks/by-session?project_id=…&provider=…&session_id=…` |
| scoped 原 key 对账 | `GET /api/v1/interactive/tasks/syncs/by-key?project_id=…&idempotency_key=…` |
| 管理任务列表/详情 | `GET /api/v1/tasks?project_id=…`、`GET /api/v1/tasks/{task_id}` |
| 版本/原始报告读取 | `GET /api/v1/tasks/{task_id}?version=N`、`GET /api/v1/tasks/{task_id}/reports/{report_id}` |

Web 任务页查询这些管理记录，不显示启动测试、Runner 或 Gate 操作。旧 Run 页面与旧数据继续保留为历史兼容入口。开发检查、远端测试验收、真实测试资产同步和发布的完成范围由各自记录注明；本文管理命令不会执行 SUT 测试。

## 未来设计：Hooks 自动触发与 MCP 共用协调器（ADR-020，未实现）

本节描述未来受控启用后的行为，**不是现有安装步骤**。Local 仍是 ADR-018 SessionTask，Cloud 仍按 ADR-019 六步流程与官方 Python SDK 独立推进；同一 Project 可同时保存两类任务，Hooks 不增加第三种模式。

```text
Harness Hooks（自动触发） ─┐
                          ├→ 统一本地同步协调器 → 既有私有客户端 / typed API / journal
MCP（显式提交与查询） ─────┘
```

协调器作为唯一语义 writer 收集本次正式资产、合并基线、冻结请求并核对读回。未来 Hooks 不直接构造 POST，也不和 MCP 各起一个提交进程抢版本；现有 IPC 锁只覆盖既有请求处理，不能据此认定跨基线读取与提交的协调已经实现。客户端协调锁 / generation 不成为新的服务端 lease 或 wire 字段，服务端保留原 owner、事务锁和 expected-version 规则。

### 身份、产物与状态

- 使用真实 Provider / 父 session ID 和已授权的既有 Project；未取得身份或 Project 映射时保留缺口，不从 cwd、Hook 次数、子代理 ID 或聊天标题猜测。子代理交回父会话，由父协调器统一汇总；新父会话按前述接续流程建立自己的 SessionTask。
- 只读取用户选定正式清单中的分析、设计、用例、原始报告和代码引用；不把整个聊天、隐藏推理、任意工作区或认证目录变成同步资产。`source_ref` / `artifact_uri` 仍是引用元数据，不自动上传附件或让服务端抓取路径。
- `Stop`、`SessionEnd`、工具成功和进程结束只表示触发时机，不设置任务 COMPLETED 或测试 PASS。进度和 reported result 来自正式内容的明确声明；pending / dirty / coalesce 是本地观察，不增加 SessionTask 状态。同步 UNKNOWN 不改变报告原 PASS / FAIL。

### 完整合并与一次意图

现有 `sync` 会更新任务全部标量字段。协调器必须固定版本完整分页读取基线，再合并本次明确变化；局部 Hook 意图区分“字段缺省”与“显式清除”，缺省保留计划与 reported result，显式 CLEAR 经授权和校验后物化为原有完整请求。既有 MCP 完整 payload 的显式空值仍保留原含义；不得改写已冻结的 payload / key / version。旧 case / report key 与原 FAIL 历史保留；自动触发没有实质变化不创建新版本，显式 MCP 新 key 完整请求仍按原契约接受。

重复触发可合并尚未发送的新意图；发送前固定完整请求、稳定 key 与 expected version，并由私有客户端保存查询身份和 digest。正式来源快照需要时单独私有保留，journal 不反复复制计划 / 报告正文。请求一旦已发送或可能已发送，只 GET 原 key；NOT_FOUND、网络恢复、Hook 重跑和用户再次调用同一意图都不授权重 POST / 换 key / 建替代任务。未决操作未解决时，同任务后续写入暂停，明确保留新的变化。

有效 ACK 与接受版本完整分页读回均完成后才显示同步成功。ACK 后读取中断继续读取原接受版本，不能重新上传或把最新版本冒充原接受版本。expected-version 确定拒绝后先读新基线，再按明确新意图准备更新；不同于 UNKNOWN 时绕过原 key 重试。

### 能力、退出与兼容

Hook 为 best-effort，断线、退出或强制关闭不保证上传完成；后台队列不能成为重试已发送未知请求的理由。配置只保留非秘密映射和私有配置引用，token 继续通过原客户端通道使用，不进入 Hook 参数、提示词或报告。

未来禁用自动触发保留 MCP 显式提交 / 查询、私有账本、待发送正式来源和已接受历史；不自动取消测试、删除任务或丢弃未知 key。Cloud 关闭 / 不可用也不影响本地 MCP。当前 Codex MCP 仍可使用，Codex 自动触发以及 Claude Code / DeepSeek harness 的 provider、MCP 与事件适配必须按各自实际版本独立探针、实现和验收；不能因另一宿主具有某种 Hook 就假定本机已支持。DeepSeek 本地真实父会话只同步自己的 SessionTask，云端指挥官或子代理不能借此另建本地任务。

后续交付按 [L0–L4 本地实施计划](LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)推进，先收口可靠协调器，再启用 provider Hooks。设计接受不修改现有 XBlock 默认技能中“只用原生工具、不新建 Hook / 上传进程”的操作边界；只有受控启用已验收新版 adapter 后才调整默认策略。本轮不提供新 Hook 配置或可执行安装命令。

## 未来复用：本地设计反哺云端报告（ADR-021，未实现）

[TaskSyncCore](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) 将正式资产清单、明确语义进度、尚未冻结意图处理、请求冻结、幂等对账与固定接受版本读回做成共享库。LocalSyncCoordinator / LocalSyncAdapter 保留上文 ADR-018 的实际身份、actor / Project、`task:sync`、完整 snapshot / 有意空值和分页语义；本次不修改任何现有命令、请求字段或默认技能。

CloudTaskReporter / CloudSyncAdapter 则由当前 CloudAttempt Worker 持权报告进度与产物，使用独立 CloudTask / Attempt、`cloud:work`、lease / fencing 和领域 typed 操作。主 / 子 Agent 只交付结构化内容，SDK 继续负责执行控制；共享核心不把云端任务改成 SessionTask，也不普遍套用 Local 完整请求 / 版本递增规则。两种模式不共用 token、全局 journal 或状态；Cloud 镜像可复用兼容库，无需本地 bootstrap、三宿主配置或完整 Local release。计划分别由 Local L1、Cloud P2 / P3 接入，任一模式验收不替代另一模式的真实报告验证。

## 未来交付：统一 release 与一键安装（未实现、未发布）

MCP、私有客户端 / journal、SyncCoordinator、三个宿主的来源 / 事件 adapter、安装 / doctor / 升级 / 卸载工具及最小使用资产统一版本发行。项目页未来生成固定 bootstrap / payload、可校验、只含非秘密 Project / API / 宿主上下文的一条安装命令；已有目标 Harness、满足 manifest 依赖基线的机器可选择 `claude-code`、`codex` 或 `deepseek-harness` 安装本包。入口由已发布资产生成，不能把尚未安装的 CLI 或虚构 URL 当作现有一键命令。

发行 manifest 同时固定 TaskSyncCore / LocalSyncAdapter 版本与兼容边界；它是 Local 包内的共享库，并不把云端运行或授权装进终端。

安装器只合并所选宿主本包拥有的 MCP / Hook 配置，保留其他项目、MCP、Hooks 与技能；不强退当前会话，不承诺热加载。缺项目 `task:sync` 授权时明确受阻并安全引导，不要求 Agent 获取 Operator key。旧 setup 的设备配对 / 受管执行 scope 不是本地管理同步的授权捷径，旧 `mcp-v0.1.0` 发行仍按其原验收范围解释。

配置 / 项目授权检查和真实父会话首次 ACK / 固定接受版本完整读回分别报告；安装不会创建假会话或上传历史聊天。升级 / 回退 / 卸载保留 client 身份、未知请求账本、正式来源、用户会话、项目目录和平台历史；未知请求仍只查询原 key。具体支持矩阵、bootstrap 信任、OS 边界与验收见[统一发行与安装设计](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。上文现有 Codex MCP 可执行步骤保持不变。

## 2026-10-22 源码候选实现补充

本轮已在源码增加 `hypertest.sync_core`、`hypertest.local_sync` 与 Project 页“接入本地模式”引导；安装、诊断和私有 manifest 的具体命令见[Local 实现状态与候选操作](LOCAL_MODE_IMPLEMENTATION_STATUS.md)。它补充上文既有 MCP 流程，不改两个工具的完整请求 / 幂等语义，也不修改原可执行安装正文。上文“未来设计 / 未实现”章节保留原设计记录；本补充只说明已出现源码的范围，未完成部分仍按实现状态页分项列明。

默认不启用 Hooks。已有私有 `task:sync` 配置的操作者可审阅源码后运行 `python -m hypertest.local_sync install` / `doctor`，再通过 `submit-manifest --config <私有配置>` 显式提交所选正式产物；该提交复用同一私有 IPC、来源 coordinator 与 journal，不伪造宿主事件或父 session，不启动模型或测试。私有配置的变更须由正确 daemon 实例重读，单独重载宿主不会自动刷新已经运行的 daemon。

统一正式 release、一键 bootstrap、真实三宿主 / 自动事件 / 首次同步验收仍未完成；候选安装收据和 doctor 不代表在线授权或同步已通过。本次不自动安装当前机器、修改全局技能或接入 PowerContext admin token。
