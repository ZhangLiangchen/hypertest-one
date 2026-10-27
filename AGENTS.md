# HyperTest One — Agent Guidance

> **One Input. One Mission. One Complete Test Cycle.**

剩余工作统一看[当前TODO](docs/TODO.md)与[本轮跟进](docs/FOLLOWUP_DELIVERY_20261023.md)；实现、部署和USER_OWNED验收分别记录，不从历史候选状态重复安排已完成工作。

## Local 显式归档重构（2026-10-27）

用户已确定按[ADR-027](docs/architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)将 Local Agent 接入改为测试结束后显式调用 `hypertest-archive` Skill 与 `hypertest` CLI 归档。新流程移除 HyperTest 自有 MCP、全部 Hooks、native bridge 与常驻同步依赖，不再以 SessionStart/BIND/JOIN 为归档前提；上传者由独立归档授权确定，原会话仅为来源声明。新增全局 CLI 授权页、操作指导和一键绑定，用户级 profile 可跨目录/会话复用明确获准项目；每次上传必填 Project ID、Task ID，Subtask ID 可选，省略时直接归档到 Task 根空间，不补造默认子任务。具体任务见[开发计划](docs/LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)与[CLI 授权指南](docs/CLI_AUTHORIZATION_GUIDE.md)。

**新归档已实现并部署 API/Web（Git `1512d11f99c5e500e4fc56c685410ffa9e533530`、schema0031），cli-v0.1.0 已公开；定向自测、镜像与部署健康见[本轮交付](docs/LOCAL_ARCHIVE_DELIVERY_20261027.md)，USER_OWNED 验收未执行。** 下文 ADR-018/020/024/026 继续约束旧 profile 与历史；新归档按领域§56、TMP§51、技术架构§50实施。代码默认关闭旧 Local 新写，部署切换与本地安装迁移分别记录；本地按受管收据精确移除自有配置，保留其他插件配置、凭据、全部旧任务/报告/回执、源文件和未决 key，只读恢复不再依赖 MCP/Hooks。不得以“移除接入”删除历史、伪造 native 来源、自动重发未知请求或连带停用 Cloud/Memory。

CLI 推荐安装方式已改为复制 Prompt 给本机 Agent，平台授权/项目指引与 GitHub Release 提供中英文内容；Web 已按 Git `8b90efb878c51568c9e35901ad31116b742a5f7f` 部署，cli-v0.1.0 包与原摘要保持。安装、Skill 配置和配对由 Agent 完成，网页批准由用户完成；真实本机验收尚未执行，详见[Prompt 安装交付](docs/CLI_PROMPT_INSTALL_DELIVERY_20261027.md)。

CLI 授权已移除手选历史 ACTIVE 上传身份，用户只核短码/客户端并批准项目、权限和期限。API 在首次合法批准时按稳定 Operator 建立不可变专用上传身份映射，跨设备复用；历史actor/grant/Task owner/回执保留。API/Web已按Git `006100788751a416b0d6f1dbe8d78c96d3155a5f`部署、schema0032，见[项目授权交付](docs/CLI_PROJECT_AUTHORIZATION_DELIVERY_20261027.md)。cli-v0.1.0继续可用，旧请求按原key恢复，不自动改绑或延长过期配对。

CLI 授权页已补客户端「添加项目」入口、同profile增量授权Prompt及客户端→项目折叠树；绑定后展示名称和绿色状态。Web已按Git `fc9de8665fac15d8b63e92de6b1198ccfd3d1fd9`部署，API保持0061007、schema0032、cli-v0.1.0不变。定向回归、PC合成浏览器和健康检查见[授权页交付](docs/CLI_AUTHORIZATION_UI_DELIVERY_20261027.md)，真实追加授权仍USER_OWNED。

## 快速原型阶段：自测与验证约束

- **当前项目处于快速原型阶段：保留关键自测，降低日常检查强度，避免过度自测拖慢开发效率。** 日常验证以本次改动的实际风险和最小足够范围为准，不以测试数量、覆盖率或完整验证矩阵作为普通交付目标。
- 文档修改只检查文档差异；局部代码修改只运行直接受影响模块及关联契约的必要检查，Lint、类型检查和构建按改动需要选择。可复用仍适用的已有结果，不默认在本地、服务器与CI重复运行同一套检查。相关检查通过且无具体未解决问题后立即结束。
- 本次改动涉及授权隔离、凭据边界、幂等与原key/UNKNOWN恢复、版本冲突、迁移、数据和历史保全时，必须保留相应关键行为及拒绝路径的自测；这些领域不构成每轮固定必跑清单。提速不改变产品领域、证据真实性或历史语义不变量。
- 低影响、可逆或机械性修改不默认新增专用测试。功能契约变化时同步更新受影响的旧fixture、测试加载器和断言；优先验证可观察行为及安全语义，避免无契约依据地锁死工具总数、内部结构或异步调度次数。不得仅为通过CI而削弱关键断言或掩盖真实失败。
- 全量后端/Web回归按需用于集中回归、候选发行或跨模块高风险改动，不作为每次普通迭代的默认前置条件。只有明确的用户要求、现有强制检查或具体故障才扩大范围；不自行追加多宿主矩阵、重复采样、额外审查或新的测试环境，继续遵守下文环境复用和test DB边界。
- **本阶段关闭日常push和PR自动CI。** `.github/workflows/ci.yml`仅保留`workflow_dispatch`手动入口，按需执行完整平台回归，不作为日常提交、合并或测试服务器部署的前置条件。Codex仍按本次改动范围完成必要的本地或服务器关键自测；本地检查不能保证发现所有BUG。`local-v*`、`mcp-v*`标签触发的发行构建继续保留，明确的发行要求仍适用。关闭自动CI不代表测试通过，不把未运行、跳过或失败改标为通过；自测、手动CI与部署健康检查仍与USER_OWNED功能验收分别记录。

## Web 产品实现范围（长期约束）

- **HyperTest One 仅实现并支持 PC 宽屏界面，无需兼容竖屏或移动端。** 此约束适用于后续全部 Web 页面、组件、交互、布局和回归验证，不限于某次美化工作。
- 不为移动端、竖屏或窄屏额外建设适配布局、兼容逻辑、截图或测试矩阵，也不将这些检查作为交付前置条件。
- 既有窄屏 CSS 可作为历史实现保留，不构成产品兼容承诺或后续维护要求。PC 宽屏下的中英文、键盘操作、焦点及可读性要求继续适用。

## 当前测试服务器：开发与部署规则（2026-10-24 增补）

最新API/Web已于2026-10-27按Git `006100788751a416b0d6f1dbe8d78c96d3155a5f`部署CLI项目授权简化，schema0032，固定ops保持1512d11，见[授权交付](docs/CLI_PROJECT_AUTHORIZATION_DELIVERY_20261027.md)。此前Web按Git `8b90efb878c51568c9e35901ad31116b742a5f7f`部署CLI Prompt安装入口，见[Prompt交付](docs/CLI_PROMPT_INSTALL_DELIVERY_20261027.md)；当时API/固定ops为下述1512d11、schema0031。此前API/Web已于2026-10-27按Git `1512d11f99c5e500e4fc56c685410ffa9e533530`部署显式CLI归档与授权页面，schema0031，旧Local新写关闭，见[归档交付](docs/LOCAL_ARCHIVE_DELIVERY_20261027.md)。独立Cloud Worker与legacy Worker镜像保持。此前Web于2026-10-26按Git `57cb59543a0e1b2102eccb06d917ba4e88bed071`部署本地任务详情左侧悬浮快速导航，见[导航交付](docs/TASK_QUICK_NAVIGATION_DELIVERY_20261026.md)；此前按`72322d66417f17b6cecad2f194a6866cec18f3d3`部署工作台多Agent中英文文案，见[文案更新](docs/WEB_COPY_DELIVERY_20261026.md)；此前df5155b已部署Local单Prompt安装/升级入口，并公开local-v0.1.1-rc.2候选，见[Local更新](docs/LOCAL_ONE_COMMAND_DELIVERY_20261026.md)；API保持Git `66f69f17a249ee382d60096ef9871695be457ee5`多会话协作，schema0029，见[协作交付](docs/MULTI_SESSION_LOCAL_DELIVERY_20261026.md)；独立Cloud Worker保持Git `76edb01a985b484bb1d1e1a88fcadd44b7a3532b`身份。此前API/独立Cloud Worker按该76edb01部署，新增默认关闭的受控公开HTTPS首片与框架冻结；Web已于2026-10-26按`d2d329ef575978e978f7b322a4a4123122688760`修复创建任务页的面板留白及云端读取状态并部署，见[本轮Web修复](docs/TASK_CREATE_WEB_FIX_20261026.md)；此前首屏、滚动及拆包改进见[Web性能交付](docs/WEB_PERFORMANCE_DELIVERY_20261025.md)；此前PC宽屏全页面统一见[原Web记录](docs/LIQUID_GLASS_WEB_DELIVERY_20261025.md)；当时schema0028，legacy Worker保留55de50e。P0/Memory能力与独立权限保持，见[最新跟进交付](docs/FOLLOWUP_DELIVERY_20261023.md)、[Memory原交付](docs/POWERCONTEXT_INTEGRATION_DELIVERY_20261023.md)及[P0原记录](docs/P0_RECOVERY_DELIVERY_20261023.md)。下文C4/6d49等保留历史，不替代最新部署身份或用户验收。容量处置与清理结果由[本轮磁盘清理记录](docs/DISK_CLEANUP_20261024.md)拥有；后续构建检查实际余量，不沿用旧观察或自行删除历史。

本服务器是内部测试环境，允许服务中断，没有零停机要求。Compose、容器、目录和历史文档中的 `production` / “生产”命名不代表当前环境的可用性要求。

后续应用服务部署统一采用 Docker。宿主 nginx 已按用户指令停用、屏蔽并卸载；容器 nginx 保持提供入口，见[宿主 nginx 移除记录](docs/HOST_NGINX_REMOVAL_20261025.md)。本次未迁移既有独立 Cloud Worker / Bridge，不据此改写它们的当前运行身份。

- 用户要求部署时，已授权停止旧服务、原地构建、执行必要的非破坏性迁移并重启，无需为服务中断再次确认。默认流程为：本地修改 → commit/push → 服务器 fetch 并固定完整 Git SHA → 停止受影响服务 → 在服务器构建新版本 → 迁移（需要时）→ 启动 → 最小冒烟检查；不要求先建隔离环境。
- 常规开发、构建和相关自动回归默认复用已有干净 checkout、兼容的依赖环境、构建缓存与测试基础设施；不把临时工作目录、隔离/影子环境、额外源码或构建副本、重复 virtualenv / node_modules 作为每轮默认步骤。复用环境不减少必要回归或强制检查。
- 只有具体依赖冲突、破坏性测试或安全边界确有需要时，才采用最小范围隔离。创建前说明原因、资源和生命周期，优先复用已有测试环境，不为局部问题复制多套全栈；完成后清理本轮新增、确认可再生且不再使用的临时目录、容器、依赖环境和副本，保留必须的源产物、历史与未决记录。
- 复用环境不等于将测试 fixtures 写入业务数据库。可复用明确用于自动回归的已有 test DB，reset 仅限其中的合成测试数据；不得初始化、清空或覆盖业务库及其历史。需要数据库安全边界时，隔离最小必要的测试库即可，不默认另建整套平台。
- 日常部署不默认要求蓝绿切换、影子环境、冷备、隔离恢复演练、逐表逐文件 hash 保全、独立复核或历史生产 Gate。PR 合并、正式发行资格也不是测试服务器部署的默认前置条件；用户明确要求的发行流程及强制 CI 检查仍适用。
- 验证与改动范围相称：文档修改只检查文档差异；局部代码修改只做相关检查；部署后检查服务启动、健康接口及本次变更的一条关键路径。相关检查通过且无具体未解决问题后立即结束，不自行扩大到全量回归、多宿主矩阵、反复健康采样或额外审查。
- 只有用户明确要求、强制检查要求或具体故障需要时，才扩大验证。不得为普通开发任务额外建设验收、证明或保全体系。
- 允许中断不等于允许丢失数据。保留数据库与数据卷、源产物、历史记录、未决同步 key / journal、凭据及宿主配置；清库、删卷、破坏性迁移或不可逆覆盖须有明确授权。迁移确有数据风险时，只做与该风险相称的数据保护，不自动升级为整套生产发布流程。
- 保留现有 SSH 访问、主机密钥校验、密码人工恢复、TLS、VPN 白名单及其他访问限制；不泄露或复制凭据到仓库、日志或交付物，不改动无关服务。
- 本节取代旧运维文档及历史发布记录对本测试服务器的可用性与发布流程约束。历史验收记录仅供追溯，不作为每次开发的执行清单；产品领域、授权、幂等、证据真实性和历史语义不变量继续适用，不把产品证据规则扩展为开发部署 Gate。

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

- **Local management path: HyperTest One manages testing tasks, cases and reports; local Agents perform testing and synchronize their outputs. This management API does not execute tests.** [ADR-018](docs/architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) and [ADR-024](docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md) retain the default single-session contract. [ADR-026](docs/architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md) adds explicitly enabled one-task/many-root participation: same owner actor, exact source authorization/JOIN, isolated append-only contributions and one current primary publisher. Initial binding identity/history stay immutable; child delegates do not acquire parent writer rights. Legacy full sync cannot write collaborative tasks; original-key reconciliation and old single-session tasks remain compatible. Implementation/deployment/client release/user acceptance are recorded separately.
- **Cloud and Local share one Project:** Cloud uses independent CloudTask / CloudAttempt identities and the official DeepSeek Harness Python SDK under [ADR-019](docs/architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md). The six steps are Project resources → frozen task inputs → dispatch → DeepSeek/Codex work → accepted artifacts → project-framework execution/reporting. Claude remains a placeholder. Cloud 当前仅实现官方 Python SDK + DeepSeek Harness + 显式 opt-in Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 Task 固定 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT strict PASS，独立只读重放 19 项通过。重评没有新的 current GET、模型 / SSH / SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，也不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 与失败原件保持。测试服务器 API/Worker 仍为 C4 `d065ae2e27b6ff37c87a8ebe0c549a96dda45a73` 来源，当前 Cloud/Codex 已启用、SSH 未启用，Worker 空闲；代码默认关闭与测试服务器的实际启用配置分别记录。Web 已按物理 Git 源码 `6d496890013614de5f216a9e672b4e915fd66550`（tree `874d110b`）部署，cloud-client 定向组件回归 17 通过 / 0 失败 / 0 跳过，正式构建成功，Web healthy、根页与 Cloud setup 均 HTTP 200。用户功能验收尚未执行，上述回归与健康检查不作为本轮模型 / SUT 执行证明。实际部署见 [Cloud Git 交付记录](docs/CLOUD_GIT_DELIVERY_20261023.md)；实现与历史边界见 [Cloud status](docs/CLOUD_IMPLEMENTATION_STATUS.md).
- Cloud API processes do not run Agents or tests. Only the current fenced Worker broker writes Cloud reports; root / child Agents receive no platform token, DB access or Operator key. Cloud `cloud:work` and Local `task:sync`, identities, ledgers and UNKNOWN reconciliation remain separate. Model identities must be provisioned in the cloud; do not copy local logins. Cloud disablement or failure must not block Local synchronization or history.
- [ADR-021](docs/architecture/ADR-021_SHARED_TASK_SYNC_CORE.md) shares TaskSyncCore semantics / library through separate LocalSyncAdapter and CloudSyncAdapter, not a generic Task table, API, token or global journal. Activity, uploads and SDK idle are not completion or PASS. ADR-022 的 Memory Gateway 已在2026-10-23独立集成切片中实现，范围与历史Cloud交付分开记录；其独立权限、Project映射与人工发布不改变已有任务身份或测试结果。经验服务与 Canonical 测试状态、TaskSyncCore 分离；`task:sync` / `cloud:work` 不授权经验访问，服务管理 key 不进入 Agent，外部 Generation / Embedding 默认关闭。
- Session sync shares Project, stores versioned plans/cases/raw reports and reported results with source metadata, and uses scoped authorization, idempotency receipts and expected-version checks. It does not require Job, Harness, Runner, execution binding, source transfer, independent CI proof or Gate. Reported PASS/FAIL is preserved and does not become legacy VERIFIED Evidence or RELEASE_READY automatically. Sync UNKNOWN is reconciled by original key and never rewrites a test result.
- [ADR-024](docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md) adds Operator-created UNBOUND Local tasks and one-time binding of the same UUID to a real native parent session. Do not invent provider/session/owner/source metadata for an unbound task. New Local clients must bind an explicit Task ID before their first asset sync; return TASK_BINDING_REQUIRED without POST when missing. Preserve confirmed legacy auto-task resume, shared Hook/MCP coordination, exact intended-actor authorization, and original-key-only CREATE/BIND reconciliation. Cloud and Local share Project, not task identity or execution rights.
- ADR-024的新BIND及手动已绑定Task的显式MCP新sync，目前仅实现已核对上游源码的Codex CLI `0.144.6`逐调用caller路径：宿主注入的`_meta.threadId`经独立私有IPC与SessionStart root核对，child不能只填已知父ID写父Task。缺context、错配或未支持的宿主明确拒绝，零新POST；Claude/DeepSeek对应适配未实现，CLI自报session不能替代。保留已确认legacy auto任务resume、授权GET及原key只读恢复。此context是本地宿主归因，不是服务端独立身份证明；远端组件验证及真实宿主E2E未观察的边界见[绑定验收记录](docs/LOCAL_TASK_BINDING_ACCEPTANCE_20261023.md)。
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
2. Preserve existing invariants and history semantics.
3. If the rule must change, update the corresponding specification in the same change.
4. Do not silently encode architecture decisions only in implementation code.

The goal is for HyperTest One to remain agent-independent, model-independent, evidence-driven, auditable, reproducible, and replaceable at the harness layer.

## HyperTest One development and test-server delivery

The `hypertest-one` server is the user's **single-user dedicated test environment**,
used to validate HyperTest One and cloud task execution. It is not a production or
shared multi-user service. Service interruption and restart are allowed during
development; a running test does not by itself impose a maintenance-window gate.
This describes the deployment environment, not a change to the ADR-018 management
boundary or authorization to run an unrelated SUT.

- Default flow for HyperTest One code changes: edit locally → commit and push to
  Git → fetch the specified branch/commit on the server and record its resolved
  full SHA → stop affected services, build there, apply needed migrations and
  start the updated services → run the relevant remote checks once. Stop after
  those checks pass with no concrete unresolved issue; expand validation only for
  an explicit user request, mandatory checks or a specific failure. Run a needed
  full suite remotely. Do not default to a full local test suite or local production build;
  quick local checks are optional debugging aids, not a mandatory preflight matrix.
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
  uncommitted work; fetch into a clean, separate server release when needed.
- Routine authorized development does not require an extra deployment approval,
  a formal maintenance window, a paired cold-backup/restore rehearsal or a fixed
  15-minute observation. Choose additional checks for the actual change or an
  explicitly requested validation goal, rather than treating old release records
  as permanent gates.
- Preserve projects, tasks, cases, reports, revisions, receipts, audit history,
  credentials and persistent files. Permission to interrupt services is not
  permission to reset the database, delete volumes, overwrite history or replay
  an uncertain external operation. Back up according to migration/data risk;
  restoration exercises are separate validation work, not an every-deploy default.
- Record the deployed Git SHA and resulting image identities. For this server,
  these current rules and the [default operations flow](docs/SERVER_OPERATIONS.md#当前环境与默认交付流程)
  supersede older descriptions of a production environment and routine heavy
  deployment gates. Historical commands, paths and evidence remain historical facts.

## Remote operations

- Read [server operations](docs/SERVER_OPERATIONS.md#ssh-access) before connecting to the deployed server.
- When already running on the test server, operate locally; do not require the Mac-only SSH alias or provision its private key. Follow the test-server deployment and minimal-verification rules above.
- On the configured local Mac, use `ssh hypertest-one` for interactive access. Automated checks must use the same alias with `BatchMode=yes` and `PreferredAuthentications=publickey`; use `bash ops/check-remote.sh` for platform health checks.
- Keep the existing password login available for manual recovery. Automated checks must fail on key authentication errors rather than depend on a temporary `SSH_ASKPASS` helper or prompt for a password.
- The alias and private key are local to this Mac, not provisioned in CI or cloud executors. Preserve host-key verification, existing server access, and the VPN allowlist.

## Local 实现与独立发行增补

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](docs/LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](docs/local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR #23 已合并，项目页 → 本地会话任务 → 接入本地模式已按 `b27c8c14c80dce46bc21a02c83daba7070cf8292` 上线，精确证据见[Local Web 历史部署记录](docs/LOCAL_WEB_PRODUCTION_DEPLOYMENT_20261023.md)。本次 Cloud 集成未重验或升级该 Local 包。


本节记录 Local（ADR-020）与 TaskSyncCore（ADR-021）Local 消费方的独立交付边界。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

Local独立发行当时以原ADR-018全文、TMP §45与领域 §50为历史基线；现行预创建、绑定及caller增补按ADR-024、TMP §45.4与领域 §50.5执行。原API/profile、task:sync、
Project/actor owner、完整请求、expected_version与既存历史语义继续保留；hypertest_sync_task不是PATCH。
同一真实父会话由一个有效 LocalSyncCoordinator 接受 Hook 触发与显式 MCP；子代理只回交父任务。
只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录。
冻结后保留完整请求/key/version；SENT/UNKNOWN/失答及 NOT_FOUND 只 GET 原 key，不自动再次 POST。
有效 ACK 后完整读回固定接受版本才确认本次同步；传输状态不重写 reported_result，Stop 不代表 PASS/COMPLETED。

Local 发行独立使用 local-vSEMVER，旧 mcp-v0.1.0/mcp-v0.2.0 历史不重标。
安装只复用既有私有 Project 授权，不申请 Operator key、签发 grant 或复制模型登录；
Hooks 需显式选择 workspace 或私有 approved artifact policy，版本匹配后启用。
升级/回退/卸载保留私有身份、账本、未决 key、源产物、用户项目与其他宿主配置。
Local 发行不包含 Cloud runtime；Cloud 实施进度与最终树验收按独立 Cloud 状态记录，不由 Local 发行成绩推定。
