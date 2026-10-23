# Cloud P2 独立后续设计与缺口核对

日期：2026-10-23（Asia/Singapore）。状态：只读审计与后续设计；四项执行能力尚未因此交付或启用。本文件不改变现有状态机、运行能力响应、旧结果与历史验收身份。

## 核对基线与本次范围

- 只读解析 `/opt/hypertest/ops-current`，实际指向 `/opt/hypertest-cloud/releases/e28d23cd58cd868a9a672be9f9ab6f608416c5c7/source`。这是部署源码路径观察，不用工作区的新文档提交替代实际部署 SHA。
- Cloud SDK/runtime 固定 `0.2.1rc2`；源码参考固定上游 commit `687f282e8625c6b8d11ff58211a90524be2e4317`。同时只读核对部署 release 中安装的 Python SDK `api.py` / `client.py` 的恢复方法。未启动该 runtime、发送 prompt、读取模型登录或探测凭据。
- 规则依据：[ADR-019](architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md)、[ADR-023](architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)、[TMP §46](protocol/TEST_MISSION_PROTOCOL.md)、[领域 §51](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)与[环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。XBlock SSH/日志/操作及 166dev 继续仅 Local；本设计不改变路由或访问限制。
- 本切片仅更新本文及平台回归 CI 配置，不修改 SDK/Worker/SSH/委派运行代码，不创建 Project、Task、凭据或 grant，不触发远端 Actions、模型、SUT、CI pipeline 或 SSH 命令。当前状态总表另由本轮交付负责。

| 独立事项 | 已有可复用能力 | 实际缺口 | 本次可完成且不需要外部执行的部分 |
| --- | --- | --- | --- |
| 原 SDK 会话续接 | 原 attempt runtime 文件、独立 report journal、fence/lease、HELD、原 key 对账 | 新 claim 碰已有目录即拒绝；任意 checkpoint 与 resume 请求仍拒绝；没有原会话恢复准入和 prompt 回执恢复闭环 | 恢复准入设计；后续可写无模型恢复材料验证器及故障 fixtures |
| 平台回归 CI | 现有 PostgreSQL fixture、完整 pytest、完整 Web helper 测试/typecheck/build | 最小 API Memory 依赖轮廓未单独检查；SDK 实包元数据检查与新增 ops lint 缺失 | 本次补齐三个定向检查，保留已有完整测试发现，避免重复执行 |
| SUT CI adapter | 项目框架执行及独立 Cloud typed 接受链 | `ci:execute` 未被当前 sandbox 准入；没有 CI provider 操作身份、调度/取消/原运行对账 adapter | 契约与无网络 transport fixtures 的后续实现；目标选择前不触发真实 CI |
| 一般 SSH | 固定诊断 target、签名票据、canonical 远端 ledger、原 ID QUERY/STOP | 只支持无参数固定动作；任意 argv/shell、文件传输、跳板、一般远程框架均未实现 | 新受限 profile 的设计与解析器/授权 fixtures；不放开旧 profile |
| Cloud Claude | DeepSeek 指挥官、官方子代理生命周期模式、fenced writer 与结果收集 | 只有 Codex payload/profile/observer/broker/预算；Claude 仍是 PLACEHOLDER | 云端 Claude 子代理设计、payload 锁定与无模型协议 fixtures；缺云端身份时保持关闭 |

## 原 SDK 会话续接

### 官方能力与平台能力须分开

固定版本的 `DeepSeekHarness.resume_session(id)` 会启动并初始化客户端，再调用底层 `HarnessClient.resume_session(id)`；底层发出 `session/resume`。这是恢复持久会话的明确 API；`start_session(id)` 是另一个行为，不等于恢复。官方要求复用原 persistence home 和工作区，原会话不存在、不可读、不兼容或已占用时拒绝，不创建替代会话；恢复本身不发送新输入，也不恢复 shell、浏览器或其他外部进程。[官方 SDK 说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/python/sdk/README.md)、[Python API 源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/python/sdk/src/deepseek_harness/api.py)、[底层 client 源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/python/sdk/src/deepseek_harness/client.py)。

`session/prompt` 回执只确认 durable enqueue，`messageId` 不是测试完成身份。`session/wait` 只观察 root/managed descendants 的运行边界，不能替代外部副作用对账或业务完成。当前 wire 提供 `session/resume`，没有可直接拿来恢复本平台整条任务执行的通用 API。[固定协议方法与语义](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/sdk/protocol/README.md)。

本仓库有四处实际闭锁，不能只删除其中一个异常：

1. `application/cloud_tasks.py` 的 `RESUME_ATTEMPT` 明确返回 `SDK_RESUME_UNSUPPORTED`；当前 Web 能力因此准确显示不支持。
2. `cloud/worker.py:execute` 先用独占创建建立 `attempt-UUID`。目录已存在时 fence 并拒绝，保留原目录，不把旧运行当成一次新 prompt。随后还会拒绝非空 checkpoint。
3. `cloud/sdk.py:run_official_sdk` 拒绝 `config.resume`，正常路径只 enqueue 新 prompt；当前 `sdk_driver.py` 也只有这一条业务运行入口。
4. host 目前在发送前保存 `prompt-intent.json=SENT`，SDK enqueue 后获得的 `message_id` 尚未形成 host 持久回执。进程在 enqueue 与回执交接间失联时，不能从缺文件推导“没发过”。

### 建议独立交付的恢复边界

先提供恢复材料的只读 preflight，再实现真正的恢复入口；在后者完成前保持 `supports_resume=false`。

- 绑定原 CloudTask/CloudAttempt、input digest、原 session ID、原 workspace/home、SDK/runtime/profile 与已接受的 checkpoint；这些身份由受信 Worker 的材料校验，Agent 填一个 session 字符串不足以通过。
- 原 owner 失权，原本地进程范围和模型 broker 已核对停止；外部 SSH/未来 CI 操作、委派和平台/report journal 均按各自原 ID/key 对账。任何 UNKNOWN 保留，不借恢复清空 HELD。
- 沿用并核验原工作目录的权限、路径、源版本及正式产物状态。不得删除目录、重新 checkout 覆盖产物、重新建空 home、换 session ID，或把“能够打开原目录”当成已恢复原会话。
- 新 fencing generation 和短期 writer capability 仅用于合法接续，旧 generation 普通写入继续拒绝。旧终态不重写；需先由领域规范明确允许恢复的非终态与新 generation 转移。
- 按原 Task 累计预算重查剩余时间、模型额度和未结算预留。时间截止、未知模型消费及原 HELD 不因 Worker 重启重新获得额度；不能为续接偷偷重建完整预算。
- 在发送任何新消息前持久化该新意图的独立 key 与恢复材料。恢复历史、确认旧 prompt 是否入队，以及用户授权的“继续”新输入是三个步骤。缺少可靠入队材料时只读恢复，不能自动重放原 prompt，也不能用新 prompt 替换未知的旧操作。
- 必须分别记录 `SESSION_RESTORED`、新输入 durable enqueue、运行边界和业务报告接受；方法存在、恢复 RPC 返回或 SDK idle 均不能提升为 Task COMPLETED/PASS。

已有外部 Codex 子代理仍是一次性任务；恢复 DeepSeek root 不会恢复它的原生 thread。固定官方 Codex bundle 每次使用 fresh process/thread/turn，不接受 follow-up/resume；必须保留原委派结果与未知项，不自动再派同一任务。[官方 Codex bundle](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/subagent/subagent-codex/README.md)。

可以自主完成的下一代码片：恢复材料模型/纯校验器、原路径/版本/owner/预算拒绝矩阵、原 report key 只读恢复，以及用 inert transport 验证“restore 不调用 prompt”；之后才做固定 SDK 的无模型持久会话跨进程回归。当前本文未实现这些运行代码。真实续接功能验收应另行提供一个允许续接的原会话及新输入意图；未决外部动作和预算不足继续阻塞。

## 平台回归 CI 与 SUT CI adapter

### 本次平台回归配置变更

`.github/workflows/ci.yml` 原来已有 `pytest -q`，以及 Web 的 `npm test`、typecheck、build；新 Cloud/Memory/P0 测试文件本来就会被发现。重复列一组相同测试不会增加覆盖，因此本次仅补实际遗漏：

- 原 Ruff step 新增 `ops/container/stack.py`，覆盖 Memory/Cloud overlay、UDS 与私有文件校验的 Python 代码。
- 在完整 Python 依赖安装后，单独运行 `inspect_sdk()` 元数据检查，核 exact SDK/runtime pin、公开配置契约和方法存在，明确 `supports_resume=false`、`model_started=false`；不创建 SDK 客户端或进程。
- 新增 `memory-api-profile` import-only job，安装与 API 镜像一致的 `[cloud-crypto,memory]` extras，不装 dev/interactive/Cloud SDK；确认 API Memory route 与 adapter 可导入，SDK/runtime/MCP 未进入该轮廓。该 job 没有数据库 service，不启动 app lifespan，不访问 Gateway 或外部模型。

没有新增 secret、部署权限、`workflow_dispatch` 入口或 SUT 操作。原 PostgreSQL 测试仍使用已有的临时 service fixture；没有接入测试服务器数据库。本文编写时只做本地 YAML 与两个 inline Python 代码块的语法/结构检查、Ruff 与差异检查，**未远端观察 Actions 运行**；不能记为远端 CI PASS，更不等于 SUT CI 能力。

### SUT CI 的独立缺口与设计

当前 `cloud/sandbox.py` 仍不允许 `ci:execute`，Agent namespace 没有一般网络或 CI credential。`application/gitlab.py` 与 Local Connector 的 GitLab 能力管理 Issue 操作，并非 pipeline dispatcher；不能借它们已有的 token 或 ledger 宣称 Cloud CI 已接通。

建议第一片只实现一个明确选择的 provider，通过 host broker 调用已有项目测试 workflow/pipeline，建立独立外部操作 ledger：先冻结 provider/origin、Project/仓库、workflow/pipeline ref、源码 SHA、输入 schema、runner/environment、最长执行窗口和限额，再持久 SENT，只允许一次调度。收到 provider 原 run/pipeline ID 后固定保存；失答只按该原 ID 或确实可核验的原业务关联信息查询，不换 key 再触发。没有足够身份可证明第一次结果时保留 UNKNOWN，不从“查询不到”推导可以再运行。

当前 GitHub REST 文档的 `2026-03-10` 示例为 dispatch 返回 HTTP 200 及 run ID/URLs；不能沿用旧版本“固定 204、无 run ID”的假设。实现需固定所选 API/server 版本。取消接口的 HTTP 202 只代表请求接受，还须查询同一 run 的终态；日志/原件下载的重定向须单独按有界、无凭据跨源转发规则处理。[GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)、[workflow run 取消与日志](https://docs.github.com/en/rest/actions/workflow-runs#cancel-a-workflow-run)。GitLab 使用自己的 pipeline 创建/查询/取消接口，不能混用 GitHub 身份与回执。[GitLab Pipelines API](https://docs.gitlab.com/api/pipelines/)。

报告接受仍由当前 fenced Worker broker 完成。provider job 状态、固定执行源码与 runner 身份、完整原始报告和项目框架结果分别核验；仅调度成功或日志写 PASS 不能成为独立 VERIFIED Evidence。Cloud writer token、DB、Operator key 和 CI credential 不进入根/子 Agent。

可自主完成：provider-neutral 操作契约、纯授权/目标解析、inert HTTP adapter 的一次发送/失答/分页/取消 fixtures。实际 adapter 选择及联通需要用户指定 CI provider 与域名、仓库/项目、具体测试入口、允许的触发/读取/取消动作、runner/environment、凭据引用和执行预算；已有 Git 权限不自动授予这些动作。本文没有触发任何真实 CI。

## 一般 SSH

`SSH_FIXED_DIAGNOSTICS_V1` 仅允许冻结 literal IP/port/nonroot user/host key 与摘要固定、无参数的只读诊断脚本。`ssh_profile.py`、`ssh_broker.py` 与远端 helper 已有 durable SENT、原 operation UUID、短期签名票据、QUERY/STOP、有限资源与远端终态核验；它们应复用。当前没有通用远端 shell、argv 输入、scp/sftp、ProxyJump、PTY 或端口转发。

一般 SSH 应另立 profile，不扩宽旧固定诊断动作的含义。首片建议选择“受限命令/远端框架入口”，冻结命令 ID、可验证参数 schema、工作目录、允许文件范围、环境变量清单、只读/写入范围及输出/超时；目标和凭据由 host broker 解析。需要任意 shell、sudo、写配置或部署的任务必须另明确授权及远端受控进程范围，不能把 `side_effect_limits` 文本当执行约束。

保留严格 host key、固定 OpenSSH、BatchMode、无个人配置和无 agent forwarding；继续由远端持久 manager 跟踪原操作、树级停止与封存输出。SSH 连接退出、本地取消或 TTL 过期不替代远端实际 terminal/cgroup 观察；缺少可核验远端 manager 的目标无法承诺安全取消。OpenSSH 文档也指出，仅关闭 forwarding 并不能约束拥有一般 shell 权限的用户，因此不能以这几个 client 开关宣称任意命令已受控。[OpenSSH 客户端配置](https://man.openbsd.org/ssh_config)、[服务端 ForceCommand/forwarding 配置](https://man.openbsd.org/sshd_config)。

可自主完成：新 profile/schema 的设计、目标与动作解析、参数/路径/预算/UNKNOWN fixtures。实际接入仍需确切目标、网络路径、host key、非 root 账户、远端允许入口及是否可部署 helper/manager；XBlock 与 166dev 的 Local-only 约束继续成立。固定诊断旧 PASS 不升级为一般 SSH、CI 或真实 staging 已通过。

## Cloud Claude

本轮核对的交付 profile 只有 Codex：`delegation.py`、`native_subprocess.mjs`、`native_delegate.mjs`、`delegate_broker.py` 与 `ops/deepseek/delegates.package.json` 都固定 Codex 产品/payload/观察/请求计量。Claude capability 仍明确是 PLACEHOLDER。官方 Claude bundle 虽存在，但不能靠把 provider 字符串从 Codex 改为 Claude 就完成接入。

固定上游 Claude bundle 是父 workspace 内的一次性原生 Claude Code 子代理，不接受 follow-up/resume。其原生 settings/auth 生效，默认 `dontAsk` 拒绝未获准操作；省略 `settingSources` 意味着它会读取原生用户/项目/本地设置，平台必须审查实际隔离 home 与允许加载的项目配置，不能继承宿主个人 `.claude`、MCP 或 Hooks。[固定 Claude bundle 文档](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/subagent/subagent-claude-code/README.md)、[官方 bundle 运行源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/subagent/subagent-claude-code/src/run.ts)。

建议首次仍由 DeepSeek 指挥官调用官方 Claude 子代理，保持现有领域身份和报告归属；不同时替换 root harness。新增独立默认关闭开关、官方 bundle/Agent SDK/平台 payload 完整 lock 与可信摘要、模型/endpoint 显式选择、host inference broker、共享原预算中的 CLAUDE scope、隔离 home、完整 managed-range 终态及原件收集。observer 必须按实际 Claude 生命周期生成有界元数据，不能让 Agent 自报 COMPLETED、继承 Codex stop proof 或把 external activation UUID 当成产品可恢复 session ID。

Anthropic 官方提供 Agent SDK 的云端 API key/服务提供方认证路径；具体账户、endpoint、model 与额度须在云端预配。其原生会话能力也不能改变固定 DeepSeek 外部 bundle 的 one-shot 契约。[官方 Agent SDK 概览](https://code.claude.com/docs/en/agent-sdk/overview)、[认证与安装入口](https://code.claude.com/docs/en/agent-sdk/quickstart)。本轮不复制 Mac 登录、不读取个人认证目录、不把上游模型 key 交给 Agent。

可自主完成：官方包锁与完整 payload 清单校验、profile/observer/broker 的无模型合约 fixtures，以及取消/失租拒写与共享额度边界。启用及真实运行前需用户确定云端认证来源、模型/endpoint、调用额度，以及确切适用任务；未提供时持续关闭，不从 Codex 已启用推定 Claude 已配置或可执行。

## 继续执行所需的具体输入

这些是功能输入和目标授权，不额外要求测试服务器维护窗口或例行重启确认：

1. SDK：先支持哪类非终态的原会话，以及恢复后是否发送用户明确选择的新输入；提供一条可用于用户功能验收的原会话，未知旧 prompt/外部动作不得自动重放。
2. SUT CI：选 GitHub Actions、GitLab 或其他具体 provider，明确项目/入口/版本、runner、允许动作和独立凭据引用。
3. 一般 SSH：明确允许 Cloud 的目标/网络/host key/非 root 账户、受限框架入口与远端 manager 条件；Local-only 环境不作为候选。
4. Claude：明确在云端使用的服务身份来源、endpoint/model 和共享预算上限；不复用个人登录或其他服务凭据。

运行代码、真实模型/SUT 与功能验收仍需按各独立切片交付；本设计文档与 CI 配置静态检查没有替代这些结果。
