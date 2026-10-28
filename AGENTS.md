# HyperTest One — Agent Guidance

> **One Input. One Mission. One Complete Test Cycle.**

剩余工作看[当前 TODO](docs/TODO.md)；实现、部署和 USER_OWNED 验收分别记录，历史交付见[文档索引](docs/README.md)，不从历史候选状态重复安排已完成工作。

## 快速原型阶段：新旧实现不兼容的决策

按 [ADR-028](docs/architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md)，当前快速原型阶段，新旧实现不一致时以新实现为准；不要求保留旧实现、兼容入口、旧任务或其他属于被替代实现的数据。可在对应改造及部署中直接删除这些旧代码和旧数据，无需为此再询问许可或建设兼容迁移、备份恢复演练。明确本次替代范围及关联对象，执行定向清理并如实记录；不以此清空整库、删除无关项目、现行数据、用户源文件、凭据、访问配置或其他服务。测试 fixture 仍只能写入专用测试库。删除旧记录不代表未知外部操作未执行，不得自动重发或伪造迁移及历史结果。本决定取代旧规范中与该范围冲突的无条件保留、兼容及另行批准要求，其他现行安全和数据合同继续有效。

## Local 显式归档

新 Local 测试结束后显式调用 `hypertest-archive` Skill 与 `hypertest` CLI，遵循 [ADR-027](docs/architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)、领域 §56、TMP §51、技术架构 §50 和 [CLI 授权指南](docs/CLI_AUTHORIZATION_GUIDE.md)。每次上传必填 Project ID、Task ID，Subtask ID 可选；省略时写 Task 根空间，不补造默认子任务。上传者由独立归档授权确定，原会话仅为来源声明。用户级 profile 只复用明确获准项目，网页批准由用户完成。

新流程不依赖 HyperTest 自有 MCP、Hooks、native bridge 或常驻同步；旧 Local 新写默认关闭。旧 profile 尚未清理的行为按 ADR-018/020/024/026 解释，其不兼容的旧入口及数据可依 ADR-028 移除。按受管收据精确处理旧自有配置，保留其他插件配置、凭据与用户源文件；不自动重发未知请求、不伪造来源、不连带停用 Cloud/Memory。未完成事项见 [TODO](docs/TODO.md)，各轮实现、部署、发行与用户验收见[文档索引](docs/README.md)。

## 快速原型阶段：自测与验证约束

- **当前项目处于快速原型阶段：保留关键自测，降低日常检查强度，避免过度自测拖慢开发效率。** 日常验证以本次改动的实际风险和最小足够范围为准，不以测试数量、覆盖率或完整验证矩阵作为普通交付目标。
- 文档修改只检查文档差异；局部代码修改只运行直接受影响模块及关联契约的必要检查，Lint、类型检查和构建按改动需要选择。可复用仍适用的已有结果，不默认在本地、服务器与CI重复运行同一套检查。相关检查通过且无具体未解决问题后立即结束。
- 本次改动涉及授权隔离、凭据边界、幂等与原key/UNKNOWN恢复、版本冲突、迁移、数据和历史保全时，必须保留相应关键行为及拒绝路径的自测；这些领域不构成每轮固定必跑清单。提速不改变现行产品领域或证据真实性；被替代的旧数据按 ADR-028 处理。
- 低影响、可逆或机械性修改不默认新增专用测试。功能契约变化时同步更新受影响的旧fixture、测试加载器和断言；优先验证可观察行为及安全语义，避免无契约依据地锁死工具总数、内部结构或异步调度次数。不得仅为通过CI而削弱关键断言或掩盖真实失败。
- 全量后端/Web回归按需用于集中回归、候选发行或跨模块高风险改动，不作为每次普通迭代的默认前置条件。只有明确的用户要求、现有强制检查或具体故障才扩大范围；不自行追加多宿主矩阵、重复采样、额外审查或新的测试环境，继续遵守下文环境复用和test DB边界。
- **本阶段关闭日常push和PR自动CI。** `.github/workflows/ci.yml`仅保留`workflow_dispatch`手动入口，按需执行完整平台回归，不作为日常提交、合并或测试服务器部署的前置条件。Codex仍按本次改动范围完成必要的本地或服务器关键自测；本地检查不能保证发现所有BUG。`local-v*`、`mcp-v*`标签触发的发行构建继续保留，明确的发行要求仍适用。关闭自动CI不代表测试通过，不把未运行、跳过或失败改标为通过；自测、手动CI与部署健康检查仍与USER_OWNED功能验收分别记录。

## Web 产品实现范围（长期约束）

- **HyperTest One 仅实现并支持 PC 宽屏界面，无需兼容竖屏或移动端。** 此约束适用于后续全部 Web 页面、组件、交互、布局和回归验证，不限于某次美化工作。
- 不为移动端、竖屏或窄屏额外建设适配布局、兼容逻辑、截图或测试矩阵，也不将这些检查作为交付前置条件。
- 既有窄屏 CSS 可作为历史实现保留，不构成产品兼容承诺或后续维护要求。PC 宽屏下的中英文、键盘操作、焦点及可读性要求继续适用。

## 当前测试环境：本 Mac 容器（2026-10-28）

各轮部署记录为历史事实，实际服务、镜像、schema、配置和磁盘余量在操作前核实，不从旧记录推断当前状态。操作规则见[服务器操作](docs/SERVER_OPERATIONS.md)，历史记录见[文档索引](docs/README.md)。

用户确认本 Mac 即当前测试服务器，使用本机 Docker Compose，不存在需通过 SSH 连接的测试服务器。该单用户内部环境允许服务中断，没有零停机要求。历史远端地址、SSH 别名和旧服务器命令仅供追溯。

应用服务通过本机 Docker 部署；当前 `hypertest-mac` Compose 配置和独立 PowerContext 目录位于 `~/.local/share/`，具体状态和入口操作前以实际配置和容器为准。保留现有 WireGuard Web、私有 BFF、TLS 和访问边界。旧远端 nginx 记录是历史，不代表当前 Mac 状态。

- 用户要求部署时，已授权停止旧服务、原地构建、执行必要迁移并重启；符合 ADR-028 的定向旧数据清理已获授权，无需为服务中断再次确认。默认流程为：本地修改 → commit/push 并固定完整 Git SHA → 停止受影响容器 → 用该提交在本机 Docker 构建新版本 → 迁移（需要时）→ 启动 → 最小冒烟检查；不要求先建隔离环境。
- 常规开发、构建和相关自动回归默认复用已有干净 checkout、兼容的依赖环境、构建缓存与测试基础设施；不把临时工作目录、隔离/影子环境、额外源码或构建副本、重复 virtualenv / node_modules 作为每轮默认步骤。复用环境不减少必要回归或强制检查。
- 只有具体依赖冲突、破坏性测试或安全边界确有需要时，才采用最小范围隔离。创建前说明原因、资源和生命周期，优先复用已有测试环境，不为局部问题复制多套全栈；完成后清理本轮新增、确认可再生且不再使用的临时目录、容器、依赖环境和副本，保留不属于本次替代范围的源产物、历史与未决记录。
- 复用环境不等于将测试 fixtures 写入业务数据库。可复用明确用于自动回归的已有 test DB，reset 仅限其中的合成测试数据；不得初始化、清空或覆盖业务库及其历史。需要数据库安全边界时，隔离最小必要的测试库即可，不默认另建整套平台。
- 日常部署不默认要求蓝绿切换、影子环境、冷备、隔离恢复演练、逐表逐文件 hash 保全、独立复核或历史生产 Gate。PR 合并、正式发行资格也不是测试服务器部署的默认前置条件；用户明确要求的发行流程及强制 CI 检查仍适用。
- 验证与改动范围相称：文档修改只检查文档差异；局部代码修改只做相关检查；部署后检查服务启动、健康接口及本次变更的一条关键路径。相关检查通过且无具体未解决问题后立即结束，不自行扩大到全量回归、多宿主矩阵、反复健康采样或额外审查。
- 只有用户明确要求、强制检查要求或具体故障需要时，才扩大验证。不得为普通开发任务额外建设验收、证明或保全体系。
- 按 ADR-028 可以定向删除被替代且不兼容的旧实现及对应旧数据，无需额外审批；不因此授权清空整库、删除数据卷或删除无关现行数据、凭据及宿主配置。未知外部操作不得自动重发；其他范围的破坏性操作须有明确授权。
- 保留现有 WireGuard、BFF、TLS 及其他访问限制；不泄露或复制凭据到仓库、日志或交付物，不改动无关服务。
- 本节取代旧运维文档及历史发布记录对本测试服务器的可用性与发布流程约束。历史验收记录仅供追溯，不作为每次开发的执行清单；现行产品领域、授权、幂等与证据真实性继续适用；被替代的旧历史按 ADR-028 处理，不把产品证据规则扩展为开发部署 Gate。

This repository is governed by four foundational documents. Any implementation, refactor, protocol change, schema change, or architecture decision MUST remain consistent with them unless an explicit Architecture Decision supersedes the relevant rule.

## Required reading

1. `docs/foundation/HYPERTEST_WHITEPAPER.md` — product identity, scope, principles, and long-term direction.
2. `docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md` — system boundaries, runtime components, control-plane architecture, runner and agent integration.
3. `docs/protocol/TEST_MISSION_PROTOCOL.md` — provider-independent contract between HyperTest and Codex / Claude Code / other agent harnesses.
4. `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` — normative canonical data model, lifecycle, database constraints, ownership and invariants.

## Precedence

When details conflict:

1. `HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md` is normative for fields, relationships, lifecycle, uniqueness, persistence, database constraints and state transitions.
2. `TEST_MISSION_PROTOCOL.md` is normative for HyperTest ↔ Agent mission, proposal, event, result and tool interaction contracts.
3. `HYPERTEST_TECHNICAL_ARCHITECTURE.md` is normative for service boundaries and runtime architecture.
4. `HYPERTEST_WHITEPAPER.md` defines product intent, principles and long-term positioning.

## Non-negotiable architecture principles

Legacy compatibility and retention statements below describe historical profiles only. The user has decided to retire SessionTask and the legacy managed TestRun, including their creation, execution, reports and associated data; no compatibility endpoint is required. Deployment and migration status must be verified separately. ADR-028 governs their removal. Independent Native, LocalArchive, Cloud and Memory remain separate.

- **Local management path: HyperTest One manages testing tasks, cases and reports; local Agents perform testing and explicitly archive their outputs under ADR-027. This management API does not execute tests.** The following session-sync rules apply to the legacy profile: [ADR-018](docs/architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) and [ADR-024](docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md) retain the default single-session contract. [ADR-026](docs/architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md) adds explicitly enabled one-task/many-root participation: same owner actor, exact source authorization/JOIN, isolated append-only contributions and one current primary publisher. Initial binding identity/history stay immutable; child delegates do not acquire parent writer rights. Legacy full sync cannot write collaborative tasks; original-key reconciliation and old single-session tasks remain compatible. Implementation/deployment/client release/user acceptance are recorded separately.
- **Cloud and Local share one Project:** Cloud uses independent CloudTask / CloudAttempt identities and the official DeepSeek Harness Python SDK under [ADR-019](docs/architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md). The six steps are Project resources → frozen task inputs → dispatch → DeepSeek/Codex work → accepted artifacts → project-framework execution/reporting. Codex is explicitly opt-in; Claude remains a placeholder. Source snapshots, reported results, deployment and user acceptance have separate identities and must not be upgraded or inferred from one another. Historical results and limitations are recorded in [Cloud status](docs/CLOUD_IMPLEMENTATION_STATUS.md) and [Cloud delivery](docs/CLOUD_GIT_DELIVERY_20261023.md).
- Cloud API processes do not run Agents or tests. Only the current fenced Worker broker writes Cloud reports; root / child Agents receive no platform token, DB access or Operator key. Cloud `cloud:work` and Local `task:sync`, identities, ledgers and UNKNOWN reconciliation remain separate. Model identities must be provisioned in the cloud; do not copy local logins. Cloud disablement or failure must not block Local synchronization or history.
- [ADR-021](docs/architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) shares TaskSyncCore semantics / library through separate LocalSyncAdapter and CloudSyncAdapter, not a generic Task table, API, token or global journal. Activity, uploads and SDK idle are not completion or PASS. ADR-022 的 Memory Gateway 已在2026-10-23独立集成切片中实现，范围与历史Cloud交付分开记录；其独立权限、Project映射与人工发布不改变已有任务身份或测试结果。经验服务与 Canonical 测试状态、TaskSyncCore 分离；`task:sync` / `cloud:work` 不授权经验访问，服务管理 key 不进入 Agent，外部 Generation / Embedding 默认关闭。
- Session sync shares Project, stores versioned plans/cases/raw reports and reported results with source metadata, and uses scoped authorization, idempotency receipts and expected-version checks. It does not require Job, Harness, Runner, execution binding, source transfer, independent CI proof or Gate. Reported PASS/FAIL is preserved and does not become legacy VERIFIED Evidence or RELEASE_READY automatically. Sync UNKNOWN is reconciled by original key and never rewrites a test result.
- [ADR-024](docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md) adds Operator-created UNBOUND Local tasks and one-time binding of the same UUID to a real native parent session. Do not invent provider/session/owner/source metadata for an unbound task. Legacy SessionTask clients must bind an explicit Task ID before their first asset sync; return TASK_BINDING_REQUIRED without POST when missing. Preserve confirmed legacy auto-task resume, shared Hook/MCP coordination, exact intended-actor authorization, and original-key-only CREATE/BIND reconciliation. Cloud and Local share Project, not task identity or execution rights.
- ADR-024的新BIND及手动已绑定Task的显式MCP新sync，目前仅实现已核对上游源码的Codex CLI `0.144.6`逐调用caller路径：宿主注入的`_meta.threadId`经独立私有IPC与SessionStart root核对，child不能只填已知父ID写父Task。缺context、错配或未支持的宿主明确拒绝，零新POST；Claude/DeepSeek对应适配未实现，CLI自报session不能替代。尚存的legacy auto任务resume、授权GET及原key只读恢复按旧合同运行，可依 ADR-028 退休。此context是本地宿主归因，不是服务端独立身份证明；远端组件验证及真实宿主E2E未观察的边界见[绑定验收记录](docs/LOCAL_TASK_BINDING_ACCEPTANCE_20261023.md)。
- ADR-017 native intake and ADR-010/012/013/015/016 execution paths remain separate compatibility/history; do not apply their execution admission rules to current management sync or alter historical results.

- HyperTest is an **Autonomous Testing Control Plane**, not another generic coding agent.
- HyperTest orchestrates **testing missions**, not model reasoning.
- General-purpose agent harnesses such as Codex and Claude Code are replaceable Testing Workers.
- **Agent performs testing work. Project test tools produce execution results. HyperTest governs evidence and conclusions.**
- Agent output is a Proposal by default; agents do not directly own Canonical Testing State.
- Agent calls each SUT's existing framework / CI; HyperTest does not build another test engine or Runner backend matrix. Formal facts require independently verified execution provenance; Agent summaries, hashes and shell self-reports are insufficient.
- [ADR-017](docs/architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md) defines the additive `native-framework-intake/v1alpha1` profile. Native plans / cases pass Proposal / Verifier acceptance; local execution materials remain UNVERIFIED and the first native Gate only emits UNKNOWN / BLOCKED. Native Contributor handoff is explicit, sequential and fenced by a private generation-scoped capability; session labels are metadata, not native-chat identity proof.
- ADR-010 / 012 / 013 / 015 / 016 Runner-only facts, Python/pytest targets, source transfer and persistent primary-session rules continue to govern their legacy profiles and history. They do not restrict the new native profile to platform execution; native records cannot be relabeled as legacy VERIFIED Evidence or RELEASE_READY.
- Canonical chain: `Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding → Verdict`.
- Agent conversation, chain-of-thought, provider-specific event formats and temporary workspace data are not Canonical Testing State.
- BUGate remains a stateless Testing Protocol / Policy layer; HyperTest is the stateful runtime.
- Prefer PostgreSQL canonical relational state + audit log + transactional outbox for v1. Do not introduce Graph DB, Kafka, full event sourcing or a custom generic Agent Loop without a demonstrated requirement.

## Change discipline

Before changing a core domain entity, mission lifecycle, runner/evidence trust model, or agent contract:

1. Identify which foundational document owns the rule.
2. Preserve current invariants and truthfulness; apply ADR-028 when a replaced, incompatible implementation and its old data are removed.
3. If the rule must change, update the corresponding specification in the same change.
4. Do not silently encode architecture decisions only in implementation code.

The goal is for HyperTest One to remain agent-independent, model-independent, evidence-driven, auditable, reproducible, and replaceable at the harness layer.

## HyperTest One development and test-server delivery

This Mac and its `hypertest-mac` containers are the user's **single-user dedicated test environment**,
used to validate HyperTest One and cloud task execution. It is not a production or
shared multi-user service. Service interruption and restart are allowed during
development; a running test does not by itself impose a maintenance-window gate.
This describes the deployment environment, not authorization to run an unrelated SUT.

- Default flow for HyperTest One code changes: edit locally → commit and push to
  Git → record the pushed full SHA → stop affected local containers, build from that SHA, apply needed migrations and
  start the updated services → run the relevant checks once. Stop after
  those checks pass with no concrete unresolved issue; expand validation only for
  an explicit user request, mandatory checks or a specific failure. Run a needed
  full suite in the test environment. Do not default to a full local test suite or local production build;
  quick checks are optional debugging aids, not a mandatory preflight matrix.
- Environment reuse, minimal isolation and cleanup follow the current test-server
  rules above and [server operations](docs/SERVER_OPERATIONS.md#复用现有环境与最小隔离2026-10-24-增补).
  Reuse does not reduce mandatory tests or authorize fixtures in the business DB;
  only synthetic data in an explicitly dedicated test DB may be reset.
- Default scope is implementation and deployment, including necessary builds,
  migrations, restarts and basic service health checks. Functional acceptance is
  performed by the user unless the user explicitly requests the agent to conduct
  it. Do not independently create acceptance projects, tasks or credentials, or
  trigger models, SUT tests or business acceptance flows. Normal change-scoped
  automated regression tests during implementation and deployment health checks
  remain allowed; report them as regression or health checks, not user acceptance.
- Pure documentation changes only need static checks and commit/push. They do not
  trigger a server build, migration, restart or functional regression run.
- Deploy from pushed Git history. Do not package and upload an uncommitted local
  worktree as the normal source-delivery path. Do not reset another checkout's
  uncommitted work; reuse the clean local checkout or use a separate release only when necessary.
- Routine authorized development does not require an extra deployment approval,
  a formal maintenance window, a paired cold-backup/restore rehearsal or a fixed
  15-minute observation. Choose additional checks for the actual change or an
  explicitly requested validation goal, rather than treating old release records
  as permanent gates.
- Under ADR-028, remove the replaced incompatible implementation and its associated old data when needed without additional approval; identify the affected scope. Preserve unrelated current data, projects, credentials and user files. This does not authorize resetting the entire database, deleting volumes or replaying uncertain external operations. Backup and restoration exercises are not a routine prerequisite.
- Record the deployed Git SHA and resulting image identities. For this server,
  these current rules and the [default operations flow](docs/SERVER_OPERATIONS.md#当前环境与默认交付流程)
  supersede older descriptions of a production environment and routine heavy
  deployment gates. Historical commands, paths and evidence remain historical facts.

## 本机容器操作

- 当前测试环境就是本 Mac，直接使用本机 Docker Compose；不尝试旧 `hypertest-one` SSH 别名。
- 读取[服务器操作](docs/SERVER_OPERATIONS.md)及本机 `~/.local/share/hypertest-mac/README.md`，先核对 Compose、容器、镜像、schema 和可用磁盘。现有配置与历史身份均需现场核实。
- 保持实际 WireGuard、TLS、BFF、数据库卷、独立 PowerContext 和其他未涉及的服务；针对被替代数据按 ADR-028 定向迁移。

## 旧 Local 发行与兼容

旧 `local-v*` 发行、三宿主 Hook/MCP 资格和历史矩阵仅适用于各自的固定版本和 profile，不构成新 CLI 的宿主验收。尚存的旧任务、会话、修订、回执与 journal 可按 ADR-028 随被替代实现定向删除；无关授权及用户源文件保留。不把 reported result 升级为正式 Evidence 或 Gate。若旧恢复路径仍存在，失答或 UNKNOWN 只按原 key 查询和恢复；移除后不能推定未执行，也不自动重发。旧 profile 只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录；冻结后保留完整请求、key 和 version，SENT/UNKNOWN/失答及 NOT_FOUND 只查询原 key，有效 ACK 后须完整读回固定接受版本。Stop 不代表 PASS/COMPLETED。旧宿主事实及精确限制见[历史验收](docs/LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)和[文档索引](docs/README.md)。
