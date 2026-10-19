# Web 工作台操作指南 / Web workbench guide

当前生产应用为 `63bd6cc`，原 Host Bridge 为 `95e92c5`，数据库为
`0018_harness_selection`。ADR-014 的 CLOSED 后治理与 ADR-015 双模式均已包含在发布中；
各自隔离验收仍独立保留。严格外部 TLS 已核验，线上本地 Connector 核心周期已通过。
当前发布和限制见[生产部署记录](ADR015_PRODUCTION_DEPLOYMENT.md)，历史治理结果见
[会话关闭后 Gate 验收](POST_SESSION_GATE_ACCEPTANCE.md)。

Production uses application `63bd6cc`, the retained Host Bridge `95e92c5` and schema0018.
ADR-014 and ADR-015 are included in the deployed application. Strict external TLS is verified;
the online local-Connector core E2E is verified. Separate historical acceptance remains linked
from [the current production record](ADR015_PRODUCTION_DEPLOYMENT.md).

## 结果复核与修复后复测 / Result review and retest

PR #10 的实现与隔离真实验收见[结果复核与新轮次验收](WEB_RESULT_REVIEW_RETEST_ACCEPTANCE.md)。
生产基线及是否已部署以[服务器操作交付](SERVER_OPERATIONS.md)为准。

- 点击需求、风险或测试用例标题，查看完整说明、前置条件和预期结果，并沿关联按钮追溯。
  在自动化实现中点击文件名，读取平台已接受的测试源码；服务端会核验 Run 的项目与快照
  归属、Artifact 路径和 SHA。已有仓库测试只显示其固定提交及文件信息。
- 概览的“阅读已保存报告”及完成任务的报告入口可直达报告。报告汇总已接受记录；
  正式质量结论仍以 FINAL Verdict 及可信 Evidence 为准。
- CLOSED / FAILED / CANCELLED 会话不能重开。使用“基于本次运行创建新轮次”，进入
  同一 Project 的草稿，选择“核对沿用的输入”；原 SHA、PRD、上下文、环境请求及完整
  Policy 被预填。检查原 SHA，选择需要验证的修复提交和服务入口，再按五步流程确认。
  保留原 SHA 也可以显式创建独立复测轮次。新轮次使用新请求身份、Binding 与原生会话；
  原运行、失败、报告和 Verdict 保留。
- 策略默认“沿用完整原策略”，包括表单未提供的字段；选择“重新配置并替换策略”才
  改用 Web 表单规则。环境只沿用请求，创建时重新核验实际镜像；归档或未绑定环境需
  显式新建并选择当前受控环境，不会静默升级。
- 读取旧输入失败时不替换草稿；已有草稿需要明确选择替换。关闭和语言切换保留同页
  草稿，刷新页面不承诺恢复未提交内容。保存输入的前导U+FEFF、换行和空配置保留。
- RECOVERY_REQUIRED 先核验原会话；恢复后通过原失败任务显式重试。源码准备阶段尚无
  Binding 的失败同样从原任务创建关联重试，不另建周期绕过历史。未知提交结果仍按原
  请求标识核对。已关闭会话中的原执行任务不能恢复；独立 Gate 任务采用下节的治理与关联重试入口。
- Finding 后续处置不会改写旧 FINAL 或报告。本分支按 ADR-014 提供 CLOSED 后独立 Gate 重评，
  仅使用已有正式事实，不恢复模型会话；验证代码修复仍需创建新轮次。

Open a requirement, risk, case or implementation to review the accepted testing asset and its links.
Use **Read saved report** from Overview or a completed task. After a session ends, choose
**New round from this run**, review the saved inputs, select the repaired SHA and service, then
confirm a new round. The full original policy is retained unless you explicitly replace it;
current trusted images are resolved again. Old runs and decisions remain in history. Input-load
failure preserves the current draft, and retrying failed work keeps its original task lineage.

## 会话关闭后的发现处置与门禁重评 / Post-session disposition and Gate reassessment

此入口已包含在当前生产应用中；[ADR-014](architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)
和领域模型 §23.8 定义规则，真实验收进度以[专门记录](POST_SESSION_GATE_ACCEPTANCE.md)为准。

1. 在“发现”中打开条目，先查看诊断、关联测试用例与可信 Evidence。选择合法下一状态，
   填写必需的处置原因；进入 RESOLVED 还需选择解决方式。平台检查原 `row_version`，
   并发冲突时刷新发现、核对状态后再决定，不会覆盖另一操作者的更新。
2. 在同一抽屉查看“处置历史”：状态、解决方式、版本、时间和原因分别保留。
   当前显示最近 50 条事件；更早记录或过长原因会明确提示截断。历史刷新失败会保留
   已加载内容与当前处置草稿，不阻止继续核对发现。
3. 仅当 Binding 与原主 AgentSession 均为 CLOSED、同 Run/Binding 已接受报告且没有
   冲突中的活动工作时，使用概览、“发现”或“质量判定”中的“重新评估质量门禁”。
   对话框说明此操作不会启动或恢复智能体、Bridge、Runner、Git 或新的正式执行。
4. 填写非空“重评原因”，最长 2,000 字符，不能含 NUL；首尾空白去除后保存。
   原因进入后台任务与 Audit/Outbox，不参与质量事实 hash，也不能覆盖策略。
   关闭对话框或切换中英文保留同页草稿，刷新或离开页面不承诺保存未提交内容。
5. 选择“提交重评任务”，查看已持久化 Job 的原因、状态及结果，用“打开已记录判定”
   进入对应 Verdict。刷新或关闭页面不取消任务。提交结果不确定时按原幂等请求身份核对；
   任务失败后使用“检查并重试门禁任务”，追加保留原 payload/reason 的关联重试。
6. 概览显示最高序号的 FINAL / TEST_RUN 判定。正式状态变化会追加新 sequence；连续
   相同状态复用最新匹配判定，每次请求仍保留独立原因、任务和结果审计。即使决策文字
   仍为 RELEASE_BLOCKED，也可能因处置状态变化产生新判定。
7. “持续会话与报告”展示原报告引用的 Verdict；其与最新正式结论不同时显示历史差异。
   原报告内容、SHA、旧 FINAL 和关联证据保持完整，不会为重评重新调用模型生成报告。

**关闭发现不代表代码已经修复。** 解决方式仅记录处理决定；已有正式 FAIL 不因 CLOSED、
FIXED 或 RISK_ACCEPTED 而变为 PASS，重评仍会阻止发布。验证修复需选择“基于本次运行创建
新轮次”，核对原输入、明确修复 SHA 后执行新的完整周期。ACTIVE、WAITING_INPUT、
RECOVERY_REQUIRED、FAILED、CANCELLED，以及没有报告的 CLOSED 不适用此独立 Gate 例外。

Open **Findings**, inspect the evidence, record a permitted disposition and its reason, then review
**Disposition history**. For a reported CLOSED binding and its original CLOSED session, select
**Reevaluate quality gate**, enter a nonblank reason of up to 2,000 characters, and choose
**Save reevaluation task**. Inspect the durable task and open its recorded Verdict. Failed work uses
**Review & retry gate task** with linked history; uncertain submissions retain their request identity.
The same-page draft survives dismissal and language switching. History refresh errors retain loaded
records and the form. Reassessment uses fixed policy and verified existing facts, calls no Agent or
Runner, and keeps the session closed. The latest FINAL is the current formal decision; the original
report retains its own Verdict and marks later decisions separately. Closing a Finding does not
waive an official failure or prove a fix. Verify repaired code in a new reviewed testing round.

API: `POST /api/v1/test-runs/{id}/jobs`，
`{operation:"EVALUATE_GATE", idempotency_key, payload:{finalize:true, reason}}`；
`GET /api/v1/findings/{id}/history?limit=50`（上限 100，返回 `events` 与 `truncated`）。
没有 Binding 的旧运行继续使用其原有 Gate 兼容契约；已绑定运行不能用同步端点绕过准入。

## 历史等待输入功能的交付记录

WAITING_INPUT 问题持久化、Web 回答及同一后台任务恢复已在本地和服务器通过真实模型 / Docker 验收，数据库迁移为 `0009_mission_inputs`。其 345 后端 / 31 Web 回归及检查、同 Job / Attempt / 原生 thread 恢复身份见[问答验收](WAITING_INPUT_ACCEPTANCE.md)。PR #6 已合并，服务器同步为 `a48bc96`；原真实执行身份仍为 `8e01ac5`，不改写成合并版本重新运行。见[合并部署记录](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr6-deployment-2026-10-18.md)。以下既有文件导入、测试链及 VPN/SSH 记录保留各自身份。

## 历史文件导入两阶段版本与验收状态

历史阶段1 `73dff989b87fa7349d9b36bd8416ece948a82212` 当时已部署，VPN 公网 `http://155.138.206.106:8080` 当时已激活精确来源的双层白名单，并保留 SSH 隧道。本地9实际PRD文件/15UI检查、20前端回归及生产HTTP Project/Run/Job创建、导入编辑稿原文/hash均有实际证据。

生产首轮Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5` 为BLOCKED：10Req/6Risk/8Case中2Case错误要求测试Runner内部功能，实际模型如实返回PARTIAL/6实现提案；平台拒绝并保留6条未接受Proposal，Canonical Implementation/Execution/Evidence/Verdict均0，不能称完整通过。

阶段2新增provider-independent `testing_scope`，区分被测应用行为/产品自身约束与如何测试的操作指令；[领域§12](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement)/[TMP§9](protocol/TEST_MISSION_PROTOCOL.md#9-mission-context)明确其规则。后端runtime/codex及回归已变化；新冻结工作树的303后端检查（3 warnings/48.70s）及fresh Web20/typecheck/build/audit0、Ruff/0008已通过，manifest `4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90`；最终提交/部署SHA与相同605字节PRD的新Project真实链统一见[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)。不得沿用阶段1“后端等d20/302”作为当前补丁已验证的证据，也不预写新链成功。

## 界面语言

在右上角选择 **中文** 或 **English**。默认中文，语言选择保存在当前浏览器的 Cookie 中，刷新与页面跳转后继续生效。切换不会清空当前表单或正在查看的页签，Ant Design 的表单、分页、确认框和日期显示也随语言更新。

界面语言不改写 PRD、项目名称、Agent 生成的需求/用例/诊断、测试源码或证据原文。质量门禁的固定系统理由提供中文展示，并保留可展开查看的判定记录原文；原始记录、ID 和 Hash 不变。

Choose **中文** or **English** in the upper-right corner. The browser remembers the language across navigation and reloads. Switching preserves the open form and selected result tab. Requirements, Agent output, generated code and evidence retain their original content.

## 从项目到结果

1. **创建项目**：填写项目名称、唯一标识及默认分支。仓库地址可预填后续运行。项目名会建议一个可编辑的标识；标识已存在时可以直接打开原项目。
2. **创建测试运行 → 源码**：填写仓库的 origin 源地址。GitHub HTTPS 来源可输入分支/标签并选择“解析并固定提交”，也可手工填写完整 40/64 位提交 SHA。解析不创建 Run，也不修改仓库；同名分支/标签需明确 `refs/heads/...` 或 `refs/tags/...`。修改源地址或参考版本后必须重新解析。正式测试始终使用固定 SHA，分支后续移动不会改变已有输入。
3. **需求**：粘贴 PRD，或导入 UTF-8 `.md` / `.txt` 文件并编辑正文。导入限 8 MiB，需求限 2,000,000 字符，配置限 100,000 字符；最终序列化请求须不超过 10 MiB。配置可使用纯文本或 JSON，留空按空文本原样保存。 本轮修复要求：只做一次 fatal UTF-8 解码，空文件、纯空白、仅 BOM、非法 UTF-8、NUL 或超限内容拒绝导入并保留原 PRD；有效内容保留原有空白和换行。带 BOM 且有正文的有效 UTF-8 可导入，BOM 按 UTF-8 解码处理，不把仅 BOM 当作需求。本地9文件/15项实际浏览器检查已通过，详见下方证据；生产链独立登记。
4. **执行环境**：选择预置 Python/pytest 或隔离 ASGI API 环境。API模式填写应用入口（如 `examples.api_sut.app:app`）、health path和启动时限。目录检查仅表示API主机镜像可用，服务会在Runner执行时实际启动和探测。不可用时保留草稿并重试目录，不自动换环境。
5. **策略**：选择全局和按风险类别的设计维度，以及阻止发布的缺陷级别。功能维度与阻断级缺陷的底线规则由平台保留。
6. **确认**：检查源码 SHA、PRD 原文和策略。创建后形成不可变输入；新的需求或代码版本应创建新 Run。关闭向导会在当前页面保留草稿和步骤；离开页面或刷新不提供草稿恢复。
7. **运行测试周期**：GitHub HTTPS 来源可选择“自动准备固定源码并运行”，一次持久任务完成检出、Agent Mission、Docker 执行及 Gate。其他来源选择 Worker 主机上的匹配 Git 检出；其 HEAD 和 `git remote get-url origin` 必须与本次输入一致。Worker 独立处理任务，关闭浏览器不会取消工作。环境绑定由创建时固定；受控profile仅Docker执行，正式执行不联网安装依赖。
8. **查看结果**：后台任务显示状态、错误、周期步骤和重试历史。被拒绝的 Mission 也保留已完成步骤与关联身份；展开尝试记录可查看 Agent 摘要、未决事项和完整原始结果，不能将其当作正式事实。检出失败会在操作窗口显示错误与任务入口。通过任务详情可直达阶段、执行、证据、发现或质量判定。页面自动刷新数据，暂时读取失败会保留已加载内容和页签。
9. **查看判定依据**：在“最新质量判定”中打开详情，再沿关联查看证据和问题发现。证据详情展示实际内容、采集来源与 SHA-256；失败运行可查看诊断结果。确认或解决 Finding 属于受控操作，需要填写原因，不能用“任务完成”代替质量结论。
10. **报告后处置与重评（本分支）**：按上节记录 Finding 处置，再显式提交带原因的独立 Gate Job；查看新旧判定与原报告差异。该入口不重新执行测试。

**仓库源地址与检出目录不同。** 创建 Run 时的 repository 应等于已有检出的 `git remote get-url origin`；不能将任意 checkout 目录冒充 origin。本地 Git 路径只有本身就是 origin 值时才适用。运行时填写的 workspace 则是 Worker 主机上干净且匹配固定提交的检出目录。浏览器本机路径不会上传源码。自动检出仅支持 URL 中不包含凭据的 GitHub HTTPS 仓库；私有仓库授权需预先配置在 Worker 主机。

仓库地址不能嵌入密码或 HTTPS 用户信息；使用主机上预先配置的 Git 认证。平台会在创建输入和启动 Agent 前检查，校验错误不返回提交的原始字段值。完整周期还会先检查实际 Runner 和可信镜像是否可用；这一步失败时不会调用模型或检出仓库。运行前检查不代表已经产生测试执行事实，最终以 Execution、Evidence 和 Verdict 为准。

Create a project, pin repository/commit inputs, provide the PRD, choose the execution environment and policy, then review the immutable snapshot. Then submit a **Run test cycle** task using a matching checkout on the Worker host. Follow Tasks → Executions → Evidence → Findings → Verdicts. Local paths refer to the Worker host; entering a laptop path does not upload a repository.

GitHub HTTPS origins can resolve a branch/tag to an immutable SHA and prepare that source within the same durable test-cycle task. Other origins use a manual full SHA and an existing matching checkout. Attempt details show the original Agent summary and unresolved items separately from accepted proposals and trusted execution evidence. The controlled catalog provides Python/pytest and a prebuilt FastAPI/uvicorn/httpx ASGI profile; workloads install nothing at execution time. Legacy unbound Runs retain their configured original Runner.

Repository addresses must not embed credentials. Configure Git authentication on the host. The complete cycle checks the actual Runner before model calls or source preparation; a successful preflight is readiness information, while formal execution facts still come from the Runner.

## 受控依赖与 API 环境 / Controlled dependencies and API environments

环境选择与 PRD/configuration 原文分开。`python-pytest-v1` 提供标准pytest；`python-api-v2` 预装完整锁定的FastAPI、uvicorn、httpx等依赖。运维先构建可信镜像，Web不接受任意requirements/pip、Shell、Dockerfile、镜像名、外部URL或凭据。详情可核对依赖版本、锁和launcher摘要。切回基础profile不会发送隐藏的服务参数。API-v2 明确隔离仓库 pytest 配置/conftest，生成模块内的 fixtures 必须自包含；历史 API-v1 按原身份只读展示，不能静默升级。

创建Run时固定实际imageID、依赖与服务定义。修改目录或镜像tag不会改变已有Run，缺少固定镜像时明确失败；新环境或依赖需要新Run，不能在执行表单临时覆盖。旧环境NULL显示旧运行语义，未知/损坏绑定不可降级绕过。周期和独立执行窗口只读显示绑定，受控环境强制Docker。

ASGI服务只在Runner隔离容器内启动，固定 `127.0.0.1:8765`。Runner执行HTTP200就绪探测，再向pytest注入 `HYPERTEST_BASE_URL`；该地址不是浏览器访问入口，不暴露宿主端口。生成测试使用真实HTTP请求，无TestClient/mock替代。执行详情展示实际镜像/平台和环境指纹，Evidence可查看有界服务日志、启动/健康/退出/清理和JUnit；服务“已就绪”不表示测试通过，质量以正式Verdict为准。

The environment step selects an approved profile and freezes its actual image/dependency/launcher identity with the SourceSnapshot. For ASGI, enter only a Python module/attribute, local readiness path and bounded startup time. The platform starts the service; tests use the injected `HYPERTEST_BASE_URL` for real HTTP. That URL is container-local. Inspect execution identity, service evidence and the final Verdict. An unavailable image preserves the form draft and fails closed; neither the Web nor an Agent installs packages or silently replaces a bound environment.

[规范与验收](CONTROLLED_ENVIRONMENT_ACCEPTANCE.md)区分自动化、真实模型和部署身份；该历史环境增量未改变当时的服务器访问边界。

## 历史文件导入与 HTTP 创建验收

原生 Chrome 已真实复现：已有需求草稿导入 `empty.txt` 后被空内容覆盖，进入下一步才出现 required 错误。[缺陷截图](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-empty-bug-2026-10-17.png)。这更新了此前“扩展禁止本地文件访问，只检查 chooser”的历史限制。修复后用真实系统选择器完成9文件/15检查全部通过，没有注入File/Input或修改Chrome文件访问权限。

本轮输入修复以“先校验、后替换草稿”为准：无效文件显示导入错误，旧正文不变；有效文件清除先前字段错误，用户可检查内容后继续。[九文件浏览器矩阵](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-browser-matrix-2026-10-17.json)已通过合法中文/英文/emoji、BOM+CRLF、无效文件保留正文/文件名、取消/重选、编辑后重开、中英切换及Review/回退。该本地验收没有新建Run或调用模型。生产上另建一个独立Project/Run，核对导入后编辑正文/hash并执行真实Agent/Docker/Evidence/Verdict；实际结果以[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)为准，不从本地picker通过推断整链成功。

普通 HTTP 页面可能没有 `crypto.randomUUID()`。本轮请求身份改用可用的原生 randomUUID，或 `crypto.getRandomValues()` 生成的 UUID v4；不使用 `Math.random()`，没有密码学随机源则不生成身份。这只是浏览器兼容修复，不改变 Job / Run 幂等契约。三入口均有UUID回归，阶段1已实际通过公网HTTP创建Project / Run / Job；后续scope修复的完整模型链另由最新交付登记记录。

Invalid PRD imports preserve the current draft and filename. Native Chrome/macOS acceptance passed 9 real fixtures and 15 UI checks, without creating a local Run or calling a model. The production HTTP Project/Run/Job entries passed in Stage 1. Its first model cycle correctly rejected PARTIAL output; a fresh-Project scope-fix cycle and exact runtime identities are maintained separately in the latest delivery record. HTTP request UUIDs use a cryptographic fallback.

## 任务状态与质量结论

| 展示 | 含义 |
|---|---|
| 任务已完成 / Task completed | Worker 完成了该次操作；测试是否通过以正式执行和质量判定为准 |
| 通过 / Pass | 对应正式执行或用例通过 |
| 可发布 / Ready for release | 当前规则所需设计覆盖、正式执行和可信证据齐全，且没有策略阻断的已确认缺陷 |
| 阻止发布 / Release blocked | 已观察到失败或存在策略阻断的已确认缺陷 |
| 受阻 / Blocked | 当前流程或判定受阻；展开原因检查缺失事实、覆盖或运行状态 |
| 等待重试 / Awaiting retry（RETRYING） | Mission已停止并等待显式重试，不表示Worker当前正在执行；查看原Attempt/拒绝原因 |
| 已中断 / Interrupted | 先查看已保存的状态和外部资源，再显式重试；旧历史保留 |

后台任务提交具有幂等身份。响应丢失时，Web 先查询相同请求是否已保存；无法确认时保留同一请求标识供重试。创建 Run 的同一标识不能绑定不同的实质输入，平台返回 409 并保留原记录；分支参考标签不改变 SourceSnapshot 的身份。

**Task completion is not a passing quality verdict.** Inspect official execution facts and the final verdict. Requests preserve identity across uncertain submissions; retries retain prior history.

## 任务活动与等待诊断 / Task activity and waiting

### 源码准备失败 / Source preparation failure

自动准备固定源码失败时，打开原后台任务详情查看“源码准备诊断”：失败阶段、错误分类、平台说明和下一步建议。分类区分 Git 认证、仓库不可用或无权限、网络/代理、证书、固定提交不可用、存储、超时、Git 缺失、输入不支持、检出校验及未知错误。它是受控运行诊断，不是缺陷、测试结果或最终根因证明；Web 不展示原始 Git stderr、命令、认证 URL 或 Provider 内容。旧任务没有记录时会说明无法确定原因。

修复 Worker 的现有 Git 凭据/代理、网络、证书信任或存储条件后，从该失败任务的“检查并重试”显式创建关联新 Job；原输入和失败记录保留。不要关闭证书校验或把凭据填进仓库 URL。若需要换仓库/SHA，使用“从本次新建一轮”审阅输入并创建新轮次；原快照不可修改。已有会话要求恢复或已终结时，遵循原恢复/新轮次入口，不能用源码重试绕过绑定。

Open the failed task to inspect its source preparation stage, category, explanation and suggested next step. These are bounded platform observations; raw Git output, commands, credentials and Provider text are excluded. Repair the configured Worker environment, then explicitly retry the original task to create a linked Job with the same frozen input. Use **New round from this run** to review a different repository or SHA. Existing session recovery rules still apply. Historical failures without a recorded diagnostic remain unknown.

在后台任务详情中查看辅助活动区。它展示已知的当前阶段 / Mission / Attempt、最近 Provider 信号、本 Job 的 Worker 心跳和最近成功刷新；活动类型提供中文和英文，不展示模型原文、命令或推理。

- **Worker 心跳**说明负责本任务的 Worker 仍在续租，不等于模型有新进展。其他 Worker 的在线状态不能替代本 Job 的心跳。
- **Provider 信号**说明平台最近接收了外部事件，不证明测试已完成。长时间未收到信号时模型仍可能正常工作；可检查任务期限与已有状态，按需要使用现有取消操作，不应仅因沉默盲目重试。
- **等待你的回答**按 WAITING_INPUT 显示，不当作模型卡死。回答恢复后仍为同一 Attempt，但本轮信号与等待前的一轮分开计算。Runner 执行和任务终态也不显示模型静默警报。
- **近期活动**每 Attempt 最多保留 200 条，约 2 秒内同类信号可合并计数，可按需查看更早记录；不承诺完整会话日志。刷新失败时保留已加载内容并提示尚未更新，不能把旧活动时间当成实时状态。

活动记录是运行观察信息，不能替代已接受的 Proposal、可信 Evidence 或 FINAL Verdict，不显示百分比或预计完成时间，也不触发自动取消、重试、重新规划或质量判定。[本轮活动验收](MISSION_ACTIVITY_ACCEPTANCE.md)区分自动化、真实模型检查和部署状态。

## 等待输入、回答并继续 / Waiting for input, answer and continue

当智能体需要澄清时，运行概览会显示“需要你的回答”，主操作变为“回答问题”。也可从测试任务详情、后台任务详情或“问题与回答”页签进入。此时后台任务为 `WAITING_INPUT`，表示流程暂停，既不代表失败，也不代表操作或测试通过；等待期间保留此 Run 的任务位置，但不占用 Worker。

1. 打开问题，阅读智能体问题原文。建议回答只是填入草稿的快捷入口，不会自动提交，也不限制自由文本。
2. 填写 1–12,000 个字符的非空白回答，不能含 NUL 空字符。正文保留原空白与换行。关闭面板、重开或切换中英文时，当前页面内的草稿会保留；离开或刷新页面不保证未提交草稿恢复。
3. 选择“提交回答并继续”。保存回答与原 Job 的 `WAITING_INPUT → QUEUED` 在同一事务完成。Worker 用新 lease 领取该任务，继续原 Mission、Attempt 和 AgentSession；不新建 Job，不改写原 Job payload 或 Mission spec。
4. 查看原后台任务的后续状态和正式产物。`ANSWERED` 表示回答已保存；`CONSUMED` 表示已供恢复任务使用，均不表示提议被接受、执行通过或可发布。正式结论仍以最高序号、`FINAL` 且 scope 为 `TEST_RUN` 的判定及其证据为准。

网络或状态刷新失败时，已加载问题和草稿会保留。请先刷新；提交结果不确定时，再次提交相同回答会复用原幂等标识和原 `row_version`，避免重复恢复。另一页面已回答或任务状态改变时，服务返回 409；查看保存的答案和任务记录，未提交的不同草稿仍可在面板中查看，不能覆盖原答案。

需要停止等待时，进入原后台任务详情并“取消任务”；Mission 的“管理暂停任务”会引导到该 Job。取消会保留问题及已记录回答，不能回答已取消的问题来重开任务。不要发起新周期或普通重试来绕过待答问题。

回答只补充任务上下文，不改变冻结 PRD、仓库提交、Mission 契约或被测范围。若澄清实际需要变更需求或源码，请另建输入正确的 Run；回答本身不是 Canonical Requirement、Runner Evidence 或质量决策。

The overview and **Questions & answers** section expose each recorded question. Suggestions fill an editable draft; free text is always allowed. **Submit answer & continue** atomically saves the answer and queues the same paused Job. A new Worker lease resumes the same Mission, Attempt and AgentSession. A failed read keeps loaded content; an uncertain same-body retry retains its original request key/version. Cancel the original Job to stop waiting. Answers remain context and do not modify frozen inputs, authorize a different testing scope, or establish test facts. The local real Web/Codex same-thread/Docker continuation path has passed; exact identities and separate server verification are tracked in [current acceptance](WAITING_INPUT_ACCEPTANCE.md).

API reference: `GET /api/v1/test-runs/{run_id}/input-requests`, `GET /api/v1/input-requests/{id}`, and `POST /api/v1/input-requests/{id}/answer` with `{answer, expected_row_version, idempotency_key}`. Successful answer submission returns HTTP 202 `{input_request, job}`; conflicting state or a different immutable answer returns 409. See [README API details](../README.md#human-input-api).

| 展示 | 含义 |
|---|---|
| 等待输入 / WAITING_INPUT | 同一后台任务暂停，等待回答；保留 Run reservation，不占用 Worker |
| PENDING | 问题待回答；Worker 安全暂停后才可提交 |
| 回答已保存 / ANSWERED | 原问题已记录答案，原 Job 已重新入队 |
| 智能体已接收 / CONSUMED | 回答已用于恢复过程，不代表已产生正式测试事实 |
| 已取消 / CANCELLED | 问题历史保留，不能再提交回答或据此重开任务 |

## 白名单 Web 入口 / Allowlisted Web access

Web 唯一路径是经已配置跳板出口访问受限入口。先连接获准网络，再打开运维交付中的
Web 地址；出口地址、CIDR 和连接资料只放在受保护配置中，不写入产品指南。
实际服务监听、nginx 来源限制及宿主 / Docker 入口规则见[服务器运维](SERVER_OPERATIONS.md)。
API、Web 后端和 PostgreSQL 不提供绕过入口的公网访问。

SSH 仅用于管理与人工恢复，已禁用转发；不再提供 Web SSH 隧道或本机回环备用入口。
管理别名、密钥认证、主机校验及密码恢复访问按运维文档保留。共享获准出口仍属于网络许可，
不等同于应用登录、个人身份或 RBAC。

常规发布检查现有白名单规则仍生效，并执行服务内部就绪检查；无需每轮重新请求用户连接
VPN、使用手机或逐条探测外部网络。首次开放、监听或访问边界变更时，再专项验证允许与
拒绝来源、Host/Origin 和转发头约束。前述及其他历史验收记录中的 SSH 隧道描述仅代表历史策略，
不是当前访问操作。

The only Web path uses the configured allowlisted jump-host egress. Connect to the approved network
and use the Web address from the protected operator handoff. SSH remains for administration and
manual recovery, with forwarding disabled; no Web tunnel or loopback fallback is supported.
Routine deployments verify the access rules and internal readiness. Separate allowed/denied-source
connectivity checks are required for initial activation or changes to the access boundary, rather
than every ordinary release. Shared-egress permission does not provide individual login or RBAC.
