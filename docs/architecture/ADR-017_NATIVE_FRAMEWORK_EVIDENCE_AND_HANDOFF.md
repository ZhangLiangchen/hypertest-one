# ADR-017：原生测试框架材料接入与顺序贡献者交接

**Status:** Accepted — historical native intake profile. Current Codex task/case/report management follows [ADR-018](ADR-018_CODEX_SESSION_TASK_SYNC.md). Controlled acceptance records are retained separately and are not distributed with product source.

**Date:** 2026-10-21（Asia/Singapore）

**Deciders / Decision basis:** 项目负责人要求按白皮书的职责分层复用项目既有测试框架，并保留已形成的原生材料治理协议及历史。

**Scope:** 独立 `native-framework-intake/v1alpha1` 接入 profile 的项目、计划、用例、执行材料、验证、结论与贡献者接续；不新建测试执行器，不修改已有受管 Harness、Runner、Gate 或历史身份。

## Context

HyperTest 管理长期测试资产与质量治理；Agent 完成分析、设计、实现并调用项目已有框架 / CI。旧实现的 Python/pytest 目标、平台 DockerRunner、源码上传与单原生主会话是 ADR-010 / 012 / 013 / 015 / 016 的既定 profile，并非所有后续任务必须遵守的产品边界。

项目既有框架可能使用不同语言、进程入口和原生报告格式；SUT 与测试框架的版本身份须分别记录。为兼容已有材料治理，本 ADR 保留独立 intake profile。具体私有项目、源码与二进制身份、执行命令、时间和原始验收材料留在授权存储，不随产品源码公开。

## Decision

### 1. 平台治理，Agent 调用，项目执行

HyperTest 管理 Project、测试轮次、固定计划、用例、任务责任、执行记录、原始材料及结论；不发现 / 执行测试、不安装项目依赖、不启动 SUT、不维护语言镜像或 backend 矩阵。Agent 在实际获授权的工程环境调用已有脚本或 CI，遵守项目 fixtures / 配置 / 原生测试语义。

历史执行材料可 retrospective intake。执行前计划保留原始身份；平台 accepted_at / submitted_at 使用实际入账时间，observed start/end 分开记录，不能声称平台预先下发或重新执行了已发生的测试。

首个切片提供既有 FastAPI 中的窄类型 API 与本机客户端，持久数据仍写 PostgreSQL + Audit + transactional outbox，文件写既有 Artifact Store。SQLite / JSON / 客户端 journal 只能保存私有意图和对账索引，不能成为第二个 Canonical Store。Web 和现有 MCP 工具本轮不承载新 profile；CLI 不是新的执行引擎。

### 2. 独立原生测试轮次与计划 / 用例准入

`NativeTestRun` 是本 profile 的测试轮次表示，与旧 `TestRun` 使用不同的 API / 表 / ID 类型，均属于同一长期 `Project`。它不以给旧 Run 换 ID 的方式迁移历史，也不把一项活动同时写成两个可互换的轮次。旧 TMP 工具、Job、Binding 和 Gate 不消费 native 表；原生接口不修改旧行。未来统一查询 / 迁移需显式身份映射及兼容设计。

计划与原始 Plan/Case Proposal 一次冻结在 `native_test_runs` 根记录，计划与轮次当前为 1:1，不为相同概念增设另一套 Task 或计划引擎。`native_cases` 保存接受的测试意图、预期、Requirement / Risk 来源引用和原生实现引用。平台 Verifier 校验 schema、项目归属、必需输入、用例 key、来源 / 实现引用及去重；整批接受、关系、原始 Proposal、Audit / Outbox 与操作回执同事务提交。结构 / 引用接受不宣称语义覆盖或测试通过。

本 profile 的来源引用可指向原始需求文档 / 风险材料及其固定身份；它们不是伪造的旧 Canonical Requirement / Risk ID。未形成正式需求 / 风险分析、语义覆盖和独立来源验证时明确记录缺口，不能据“有 case”宣称旧 Canonical Chain 或 Release Gate 全部完成。

### 3. 不可变输入与实际测试资产

计划固定目标、范围、验收要求、生效策略、SUT 身份、测试资产、环境 / 工具和传输声明：

- SUT repository 的 credential-free origin、完整源码 SHA（确知时）、tracked / dirty / untracked 观察；二进制被测物独立记录大小和摘要、来源引用及源码关联的 `UNVERIFIED` / unknown，缺少 SHA 时不得编造。
- 测试框架仓库的独立完整 SHA、实际使用文件的版本 / 摘要、已有修改及必要 patch / untracked 资产的受控引用。`HEAD + dirty=true` 不足以固定实际执行树，缺内容或范围就保留可复现性缺口。
- 入口 argv、相对工作目录、框架和工具版本、环境变量名称、服务 / 外部依赖身份、网络和副作用边界。秘密值不进入 argv、计划、日志或报告。
- 原生实现可以是既有脚本、Java 测试、项目配置与参数化场景，不强制 Python、pytest symbol 或 `tests/*.py`。文件摘要用于资产完整性，不证明内容在所声称的执行中被使用。

改变固定目标、源码 / 测试资产、环境或策略时新建轮次并关联原历史；每次执行仍保存实际观察的上下文与计划差异，不冒充原输入未变。重跑追加执行，保留首次失败和 setup 错误。

本机调用不要求上传源码，也不授予源码外发权限。本轮只接收经检查的 manifest、选定报告 / 日志和进程材料；不上传 JAR、源码树、认证目录或完整 `.git`。存储位置是本轮明确配置的本机 PostgreSQL / Artifact Store。将来上传到远端须另核对材料范围、目标和授权；不能沿用 ADR-015 的旧上传流程推定授权。

### 4. 执行记录、材料、验证分别建模

`NativeExecutionRecord` 是 Agent 提交的执行观察，关联用例、固定入口与输入、start/end、exit code、原生 report 引用和 observed outcome；它不等于旧 `TestExecution(OFFICIAL)`。平台只接收已执行材料，不通过此 API 运行命令。

原始 `NativeMaterial` 保存在受控 Artifact Store，记录执行 FK、kind、media type、长度、SHA-256 与内容地址。接口接收有界字节，不读取模型给定的本机路径 / URL，不任意下载外部报告。原始 stdout / stderr / JSONL / Surefire XML / process metadata 分开保留；摘要和聚合统计只是派生索引。存在未脱敏秘密时停止该材料传输，不能悄悄删改后声称仍是原始完整报告。

平台追加 `NativeVerification`，分别记录内容完整性、报告一致性与来源核验。重算 hash / size、核对报告结构、计数、退出码和 case 归属能发现矛盾，不能证明真实执行、源码关联、环境正确或产品行为正确。Agent 身份、Operator 身份、会话登记、签名或材料 hash 均不能单独提升来源。

**本轮没有独立可信原生来源 verifier。所有本机材料的 provenance 保持 `UNVERIFIED`，不会产生旧 `Evidence(VERIFIED)` 或可信 OFFICIAL Execution。** 计划 / 用例接受表示管理资产已被接受；材料接收、报告解析、来源验证和质量通过是四个不同结果。

### 5. 原生结论是受控决策，当前不允许 PASS

`NativeConclusion` 是平台确定性治理决定，并引用参与的执行 / 验证、策略及固定状态；Agent 只能请求评估，不能提交 decision。首版只允许 `UNKNOWN` / `BLOCKED`：

- 已观察通过但缺少可信执行出处 / 版本 / 环境证明，结论 `UNKNOWN`，质量尚不能确定。
- 存在材料完整性 / 报告矛盾、观察到断言失败或明确未完成条件，结论 `BLOCKED` 并保留 observed FAIL / setup ERROR 和原因；这不把未验证本地失败直接确认为产品缺陷。
- 不存在本轮 native `PASS`、`RELEASE_READY`、Evidence waiver 或人工点击升可信。旧 `canonical-gate/v1` 与 FINAL / 报告内容保持不变。

`NativeConclusion.UNKNOWN` 是这个质量 profile 的“不足以判定”；`NativeOperation.UNKNOWN` / 客户端 journal UNKNOWN 是某次副作用是否完成尚未查明。两者不是同一状态机，也不增加旧 TMP TestRun 状态。后续成功观察不删除早先失败，Gate 不通过挑选成功记录掩盖未处置历史；重测和失败处置必须可追溯。

### 6. 领取与跨会话顺序交接

首版由受保护的单 Operator API 显式登记 `NativeContributor` 并下发计划 / 用例；Operator 身份、当前 contributor / generation 与不可猜的 run/generation-scoped writer capability 共同校验写入责任。contributor 的 actor / session label 是经操作者登记的贡献归属，不是可信宿主证明的 Provider native session，也不创建旧 AgentSession / RunExecutionBinding。知道可 GET 的 contributor / generation 不授予写权。

所有执行提交和评估在既有 Operator 认证之外另以 `X-Hypertest-Native-Writer-Key` 验证当前私有 capability，平台只存 hash，不向 Agent 分发全局 Operator key。操作者通过独立管理 handoff 指定原 / 新 contributor、expected generation、已接受状态引用、原始材料位置、剩余工作与原因，无需失效旧 key。先检查原操作均已对账，再原子保存 append-only `NativeHandoff`、递增 generation、切换 contributor / 新 capability 与 Audit / Outbox，随后继任者读取原状态再写。旧 key 即使知道新 generation 仍被拒；不得覆盖旧贡献者、原会话身份或历史材料。

create / handoff 的新 writer key 仅首次成功响应一次提供，客户端在 owned `0600` 文件保管；GET、普通幂等回执、日志不返回原文或 hash。响应遗失先查询原 key / 已提交 generation，不能自动重发或恢复秘密。确需恢复写入时由 Operator 在完成原操作对账后发起新的显式 handoff / rotation 意图，追加历史而非自动重签。

这是任务资产的顺序接续，不是重新连接原生聊天、不伪造旧 session ID、不搬运对话 / 思维链 / 认证，不推导并发 writer 或平台可 kill 任意聊天。因授权、源码或环境变化需要新轮次时不能借 handoff 改原计划。未决副作用禁止通过换贡献者绕过。

### 7. 幂等、未知操作与失败恢复

所有写前客户端先在私有 journal 固定 request key / versioned digest / intent；服务端 `NativeOperation` 与领域提交、Audit / Outbox 同事务保存回执。同 key 同输入返回原结果，异输入冲突。发送后失答只 GET 原 key；NOT_FOUND 不证明未执行，不自动 POST、换 key 或新轮次。

外部测试 / CI / 问题单等副作用发生 UNKNOWN 时登记原 operation 和关联材料，阻止新的执行与 handoff；受控 reconcile 是独立 Operator 窄管理例外，可在 writer key 遗失时调用；必须匹配原 operation key 与 UNKNOWN 状态、具体查证结果、受控原始材料引用和 reason，run 行锁中提交 Audit / Outbox。它不再次运行命令或发外部 POST；无材料、仅摘要或 NOT_FOUND 不足以解除 UNKNOWN，本地材料来源仍不升可信。先完成原操作对账，随后才可由 Operator 发起新的显式 handoff / key rotation，不能自动重签。不能证明结果时继续 UNKNOWN。客户端 journal 丢失不得成为重做依据。手工重跑必须有明确新执行意图，保留原记录与 lineage；不承诺 exactly-once。

### 8. 后续可信 CI 接入的明确验收要求

当前始终 UNKNOWN 不是完整迁移的终点。真实项目后续需要正式原生 PASS 时，须实现独立来源核验契约和对应 profile 版本，至少：

1. 用与提交 Agent 隔离的已授权 SCM / CI 身份，独立从批准 Project 读取真实 pipeline / job / attempt；固定 project、job ID、源码 commit/tree、测试资产与 dirty/patch 处理、实际环境 / runner 标识、开始结束、exit 与原始报告 / trace。
2. 独立读回原始产物并校验身份、权限、摘要、版本与 run / case / invocation 对应；核对测试发现 / skipped / failures / expected coverage 和退出语义。Agent 提供 URL、签名、token 或同一 shell 自述不能成为独立证明。
3. 保留来源 verifier 身份、版本、信任策略与查证时间，拒绝 fork / 错项目 / 错 SHA / 过期 / 已撤权 / 不完整报告与迟到旧 owner；I/O 外释放聚合锁，提交前重验权限及原输入。
4. 追加验证和正式证据关联，保留原始未验证材料与失败；可信 PASS 的 Policy / Gate 单独版本化，验证正向、真实失败、伪造报告、错源码、权限撤销、响应丢失、重复提交和交接后迟到写。签名或校验通过不能替代业务断言的充分性。

此契约本轮仅形成设计和验收门槛，未实现 CI connector、可信来源提升或 native PASS；不据此增加 runner backend、CI 调度器、通用 Shell、镜像构建服务或外发源码权限。

## Supersession and specification ownership

| 旧规则 | 原拥有文档 / 决策 | 本次明确适用范围 |
| --- | --- | --- |
| 正式执行事实只来自 HyperTest Runner | AGENTS、架构 §2/24–28、TMP §26–27/41、领域 §16–17/33；ADR-005/010 | 继续约束旧 OFFICIAL / Evidence。新 profile 允许原生材料接入，来源不足不升级；未来外部可信事实须满足 §8 |
| Python/pytest、安全 tests 路径、禁项目配置、统一平台环境 | 架构 §25–26、TMP §18/9.1、领域 §9/15；ADR-012 | 仅旧 Runner profile；新 native 实现引用按真实项目入口与资产，不运行平台 launcher |
| 同 Run 唯一持续 native Session、丢失即新 Run | 架构 §11/18/39、TMP §6.1/23.6、领域 §23.4/23.10；ADR-013/015/016 | 原受管 / interactive Run 保持。新 native profile 使用 contributor generation 与显式顺序交接，不重写旧 Binding 或伪造原生身份 |
| 本地须先受控源码上传 / pinned workspace | 架构 §10.1/20、TMP §22.3/23.3、领域 §9.1/23.9 | 只约束旧远端执行 / 来源传输。新本机材料接入不默认源码传输，输入不足明确未知 |
| 测试任务只用旧 TestRun 表 | 领域 §11、ADR-013 | 新 profile 使用独立版本化 NativeTestRun；旧 Run 不迁入、不双写、不混用 ID，未来统一需显式迁移 |

领域规范拥有新字段 / FK / lifecycle / 事务约束，TMP 拥有请求、版本和幂等，架构拥有组件边界，白皮书拥有产品意图。新条款不授权绕过旧 profile 的 Verifier、Gate、授权、恢复或历史保护。

## Options considered

| 选项 | 复杂度 / 成本 | 可扩展性 / 维护 | 现有体系适配 | 决定 |
| --- | --- | --- | --- | --- |
| 把 Java / Maven / Node 加入平台 Runner backend 矩阵 | 高；需依赖 / 环境 / 启动器治理 | 随项目继续膨胀 | 破坏白皮书职责 | 不采用 |
| Agent shell + hash 直接作为 VERIFIED Evidence | 表面低、误判成本高 | 无法证明来源 | 绕过事实治理 | 不采用 |
| 独立原生材料 profile，PostgreSQL 治理与显式交接 | 首个真实入口所需最小增量 | 后续按真实 CI 需求增加来源验证 | 保留旧链与历史 | 采用 |
| 只保存本地 JSON / Markdown 报告 | 低 | 无受控写权、对账、关系与历史约束 | 不能满足管理闭环 | 仅作为原始材料 / 私有 journal |

## Consequences

项目原生框架可以直接被 Agent 使用，平台首先得到可追溯的计划 / 用例 / 材料 / 保守结论，后续贡献者可受控接续。代价是首版没有正式 native PASS，也尚未完成语义覆盖、原生 CI 可信来源、Web/MCP 和真实跨 Provider 会话证明；必须清楚展示这些边界，不能把实现 API 等同完整产品迁移。

旧 PostgreSQL 数据、原始失败、FINAL Verdict、授权、两种受管 Harness、SSH / TLS / VPN 白名单、Artifact 与 source identities 均保留。开发和本机隔离迁移 / 验收不包含生产发布、生产数据库迁移、提单或共享链写入。

## Implementation and acceptance boundaries

独立 typed API、PostgreSQL additive schema、受控 Artifact、有界读取、Proposal / Verifier / Gate、原 key 对账与私有 journal 客户端作为历史兼容路径保留。可信原生来源核验和正式 native PASS 不由这些机制自动取得。

私有 SUT 的执行与验收原件由操作者在授权位置保存；本公开 ADR 不携带原始报告、执行摘要或私有来源身份。当前 Codex 管理同步及其 Web/MCP 采用 ADR-018；管理结果保存不以本 ADR 的来源提升或 Gate 为前提。
