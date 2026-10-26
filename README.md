# HyperTest One

## 2026-10-23 生产 Web 上线补记

PR #23 已合并，项目页 → 本地会话任务 → 接入本地模式已上线。实际 Web 源码为 `b27c8c14c80dce46bc21a02c83daba7070cf8292`；内部真实浏览器六条命令及已有用例 / 原始报告、外部严格 CA HTTPS 已验证。文中“待合并 / 待最终 gate”属于下方验收冻结时点；精确 image、保全、补证顺序和临时授权清理见[生产部署记录](docs/LOCAL_WEB_PRODUCTION_DEPLOYMENT_20261023.md)。原 `local-v0.1.0` 包 / tag / 三摘要与三宿主证明保持不变；本次后续纯文档提交不代表部署新 Web 源码。


Codex 会话中的测试任务、计划、用例和原始报告可通过 [Session Task MCP 同步](docs/CODEX_SESSION_TASK_SYNC.md)保存到 HyperTest One。一个实际会话对应一个任务；Agent 使用被测项目已有框架执行测试，平台负责管理、读取和版本历史。该入口使用独立 `task:sync` 授权，保留已有受管执行路径与历史。


## Cloud SDK + Codex 集成候选（默认关闭）

Cloud 当前仅实现官方 Python SDK + DeepSeek Harness + 显式 opt-in Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 Task 固定 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT strict PASS，独立只读重放 19 项通过。重评没有新的 current GET、模型 / SSH / SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，也不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 与失败原件保持。最终合并树、统一 Web 入口与测试服务器常驻 Cloud 服务尚未进行本轮验收或部署；默认关闭。 两种模式共享 Project，但保留各自任务、授权和历史；Local 发行与已上线入口不变。完整六步、环境路由、分阶段交付与原件限制见[Cloud 实现状态](docs/CLOUD_IMPLEMENTATION_STATUS.md)和[实施计划](docs/CLOUD_TEST_IMPLEMENTATION_PLAN.md)。

> **One Input. One Mission. One Complete Test Cycle.**

HyperTest One is an autonomous testing control plane with a state-centered Web workbench. It governs the complete supported testing cycle:

```text
Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding → Verdict
```

**Agent produces intelligence. Runner produces facts. HyperTest produces decisions.**

Agents submit proposals; HyperTest validates and commits canonical state. PostgreSQL owns traceability, snapshots, audit, and transactional outbox records. Legacy Runs use per-Mission sessions. ADR-013 introduces a persistent native session per Run; conversation remains separate from canonical testing state.

## Foundation and implementation status

Read these before changing the architecture or domain:

1. [Whitepaper](docs/foundation/HYPERTEST_WHITEPAPER.md)
2. [Technical architecture](docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)
3. [Test Mission Protocol](docs/protocol/TEST_MISSION_PROTOCOL.md)
4. [Canonical domain model and state machines](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)

[Current MVP status](docs/MVP_STATUS.md) records implemented capabilities, trust boundaries, verification, and the secondary roadmap.

[First-phase acceptance](docs/FIRST_PHASE_ACCEPTANCE.md) records actual checks and live
integration evidence. [Server operations](docs/SERVER_OPERATIONS.md) contains the
deployed release, SSH access, service management, and paired backup/recovery steps.

The current product targets **one trusted operator** in a controlled development/test environment. Application login, tenant isolation, RBAC, and hardened public deployment are future work.

The current production API/Worker core is **`c7cd43ad6346d8ce6c85564f7838afbb017f2da4`** (PR #17), with schema **`0020_interactive_tool_inbox`**. That release's PR and main CI passed with 967 tests passed and 21 skipped. The [ADR-016 production record](docs/ADR016_PRODUCTION_DEPLOYMENT.md) records the real current-Agent MCP cycle, explicit same-identity recovery and historical preservation. Web onboarding from **`980f27ab2341f1d62b2ee4896a321a240555548b`** was deployed on **2026-10-20 at 08:29:06 UTC**, with 35 preservation checks passed and platform health 10/10; the API/Worker core, schema, Bridge, operations package, existing data/authorization and access boundary remain. The [MCP installation delivery record](docs/MCP_INSTALLATION_DELIVERY_20261020.md) separates that Web rollout and distribution verification from the earlier testing cycle.

The historical production baseline was read-only verified on 2026-10-19 at merged main **`4d597d4`** (PR #12 Web, PR #11 API/Worker), with Host Harness Bridge build **`95e92c5`** and database **`0014_harness_operations`**. Its containers, restricted access and existing data/session/artifact hashes matched that delivery. The later ADR-015 release and schema `0018` are recorded in [ADR-015 production deployment](docs/ADR015_PRODUCTION_DEPLOYMENT.md); those records retain their own source identities and acceptance limits.

[ADR-014: post-session Gate reassessment](docs/architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md) is deployed through PR #11: after a reported session closes, record Finding dispositions and explicitly submit a reasoned independent Gate task using existing facts. Its original local positive/negative and governance results remain in [post-session Gate acceptance](docs/POST_SESSION_GATE_ACCEPTANCE.md).

The historical source-preparation diagnostics delivery added a bounded stage/category and bilingual recovery guidance; Git output, commands, URLs and credentials are excluded. An explicit retry links a new Job to the original failure with identical frozen input. Changing the repository or SHA requires a reviewed new round. That acceptance completed a real 390px Web failure/retry through Codex → trusted Docker → verified evidence → report with **37/37 tests passing and RELEASE_READY**. Its automated results and then-current schema `0014` belong to [the source-diagnostic acceptance record](docs/SOURCE_PREPARATION_DIAGNOSTICS_ACCEPTANCE.md).

ADR-016 adds a [current-Agent MCP plugin](docs/INTERACTIVE_MCP_CLIENT.md): submit a task, explicitly bind the actual local Agent, use the existing typed testing tools, and read progress, evidence and reports. The cloud Harness and Connector-managed local Harness remain available. Local execution describes where the Agent works; official test facts still come from the trusted platform Runner. The [production cycle](docs/ADR016_PRODUCTION_DEPLOYMENT.md) completed 33 real HTTP tests, five verified evidence reads, `RELEASE_READY` and a hash-verified two-page report through the actual current Agent and official MCP SDK console, with no second model. The earlier [isolated acceptance](docs/ADR016_ACCEPTANCE.md) retains its independent 27-test cycle. This does not claim native tool-catalog hot reload, new issue writes or private-SUT business acceptance.

The MCP distribution [**`mcp-v0.1.0`**](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/mcp-v0.1.0) is published from **`980f27ab2341f1d62b2ee4896a321a240555548b`** (PR #19). Its wheel, `release-manifest.json`, `SHA256SUMS` and `INSTALL.md` were downloaded anonymously over HTTPS and their checksums verified; the wheel also matches a local build from that exact commit. The wheel is **341,961 bytes**, SHA-256 **`a44b16c7394b41bdf104e9c5458b29567b9a9f1764044e62bc14f7b105eb796a`**. PR #19 and merged-main CI passed with **989 backend tests passed / 21 skipped** and **124 Web tests passed**.

The deployed Web provides a Project-specific installation prompt under **Create test run → My computer**. Its Chinese three-step guide, copy action and inline missing-key guidance were checked in production Chrome. The published wheel also listed all 18 MCP tools and completed a scoped read-only query over strict production HTTPS through the official SDK and private daemon; this verification created no Run, pairing, grant, source transfer or Issue. [The installation guide](docs/INTERACTIVE_MCP_CLIENT.md#install-and-pair-from-my-computer) explains verified wheel installation, local setup and device-management key access through the deployment administrator. Secrets stay in protected local files or hidden terminal input; the prompt contains no management key. Generic stdio hosts on macOS/Linux can submit/read or use CLOUD; current-Agent LOCAL execution requires the controlled Codex Desktop adapter and explicit binding.

The production Web entry accepts only the configured jump-host egress allowlist. Connection details live in protected operator configuration; this README does not publish the jump-host address. SSH is for administration and manual recovery, with forwarding disabled; there is no supported Web tunnel. Routine releases inspect the access rules and internal readiness without repeating connectivity probes from each external network. Initial activation or an access-boundary change requires separate access validation. See [the access guide](docs/WEB_PRODUCT_WORKFLOW.md#白名单-web-入口--allowlisted-web-access).

## Use the Web workbench

The workbench supports **中文 / English** switching in the top-right corner, with
the choice preserved across navigation and reloads. It includes guided project/run
creation, UTF-8 Markdown/text PRD import, durable task progress and direct links
from quality decisions to evidence and findings. See the bilingual
[Web workflow guide](docs/WEB_PRODUCT_WORKFLOW.md) for the complete operating flow,
input limits, server checkout paths, and the distinction between task completion
and a passing testing verdict. Use the configured allowlisted Web entry described in the access guide.

```text
/                         Create and browse projects
/projects/{project_id}    Create runs from pinned source inputs
/runs/{test_run_id}       Operate the testing cycle and inspect canonical state
```

1. Create a Project.
2. Create a Run with the repository's origin, PRD text, optional configuration, and policy. Resolve a GitHub branch/tag to a full pinned SHA, or enter the full SHA manually. HyperTest stores input artifacts and fixes immutable SourceSnapshot and PolicySnapshot identities. A checkout directory is not a replacement for its origin address.
3. Select **Run test cycle** and choose **Prepare pinned source and run automatically** for GitHub HTTPS origins, or provide an existing matching checkout on the Worker host. One durable request can prepare source and continue through verified requirement/risk/design/implementation Missions, trusted Docker execution, diagnosis when required, and the quality gate.
4. Watch canonical state, Mission attempts, proposals, executions, and Evidence populate. Work continues after refreshing or closing the page. The persistent profile retains one native session and frozen Run budgets across its typed stages; a new browser request must not reset that budget or create a replacement session.
5. Inspect queued/running work, errors, and stop reasons. Use the recorded task controls for cancellation and linked retry. A `RECOVERY_REQUIRED` binding first requires verification of its original session; an ended session requires a new testing round for further model/test work. Expand attempts to inspect their recorded summaries and rejected proposals separately from accepted facts.
6. Inspect the final quality verdict, rationale, canonical state hash, evidence manifest hash, and history. Findings support controlled triage, confirmation, resolution, closure, and reopening with a recorded reason. On this branch, follow [post-session disposition and reassessment](#post-session-finding-disposition-and-gate-reassessment) after a reported session closes.

If a Mission pauses for input, use **Answer question** in the Run overview, Mission/task details, or **Questions & answers**. Read the original question, choose an optional suggestion or write a free-text answer, then select **Submit answer & continue**. Closing the answer drawer or switching language preserves its draft in the current page; refreshing or leaving the page does not promise unsent-draft recovery. A successful answer queues the **same** Job and retains its Mission, Attempt and AgentSession identities. Do not start another cycle or use ordinary task retry to bypass a pending question. To stop waiting, cancel that Job through its task controls; its question and any recorded answer remain in history. Answers supplement context without changing the frozen PRD, source, Mission contract or testing scope, and cannot substitute for accepted Proposals, trusted execution evidence or a Verdict.

PRD import must decode UTF-8 once with fatal error handling, reject empty/whitespace-only/BOM-only input, and preserve the existing PRD on any invalid import. It must not trim valid content or normalize its line endings. Native Chrome reproduced an empty-file defect in d20: it replaced an existing draft, then Next failed the required-field validation. The repaired local [browser matrix](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-browser-matrix-2026-10-17.json) passed all 9 fixtures/15 checks, including rejection without losing the draft or filename, successful import/review, editing, cancellation/reselection and language switching. This local validation created no Run and called no model. Production acceptance uses one independent Project/Run on the VPN HTTP origin to check file → edit → persisted hash → real Codex/Docker/Evidence/Verdict; its actual outcome is separately recorded in the [latest delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md). Previous clipboard-based model runs do not prove that production import path.

Request identities use `crypto.randomUUID()` when available and otherwise a UUID v4 generated with `crypto.getRandomValues()`, allowing ordinary public-IP HTTP without a weak-random fallback. The three HTTP entry points (Project, Run and Job creation) were exercised in the Stage 1 production record; the later scope-fix model acceptance is separate. The helper does not change immutable-input or idempotency rules.

Individual **Plan next mission**, Mission execution and **Execute tests** controls belong to unbound legacy Runs. Bound Runs use their recorded persistent-session task controls; they cannot bypass ownership through manual stage actions. ADR-014 adds a separate CLOSED-only **Reevaluate quality gate** action after an accepted report. Generated Python tests remain checksum-addressed artifacts linked to canonical TestCases; the application commit stays fixed.

The Run workbench includes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, Verdicts, Tasks, and Questions & answers. The background task monitor and task details show queue state, timestamps, errors, cancellation, and retry history. Tasks refresh every 1.5 seconds, questions every 2 seconds and canonical state every 5 seconds. Refreshing the page observes saved work without submitting another request. Attempts, rejected proposals, execution errors, artifact content, and finding transitions remain inspectable.

The Planner is deterministic-first:

```text
No active Requirement                 → ANALYZE_REQUIREMENTS
Requirement without identified Risk   → ANALYZE_RISKS
Risk with missing design dimensions   → DESIGN_TESTS
TestCase without a usable implementation → IMPLEMENT_TESTS
Missing official execution            → EXECUTION_REQUIRED
Observed failure with trusted evidence → DIAGNOSE_FAILURE
Facts ready for a quality decision     → VERDICT_REQUIRED
```

The **Run test cycle** action queues durable work. In the persistent profile, one native session proceeds serially through typed domain tools; HyperTest checks deterministic admission, accepts proposals, controls official execution and computes Gate decisions. The bounded step-by-step controller remains a legacy compatibility path. PostgreSQL stores immutable Job inputs and history, and permits at most one active request per Run. Worker leases fence canonical commits. API restarts and page refreshes preserve submitted work; a Worker crash becomes an explicit interruption after its lease expires. Recovery does not automatically replay external operations. A Job's `SUCCEEDED` status means the request finished; its result and formal Verdict describe testing outcomes.

## Post-session Finding disposition and Gate reassessment

**Branch implementation; production deployment and real acceptance are tracked separately.**

1. Open a Finding, inspect its supporting evidence, then select the next allowed status and record the reason. Resolution requires a resolution type. A stale `row_version` is rejected; refresh the current Finding before deciding again. **Disposition history** shows the recorded transitions and reasons; a failed history read preserves the current form.
2. After both the binding and its original primary session are `CLOSED` and an accepted report exists, select **Reevaluate quality gate** from Overview, Findings or Verdicts. Enter a nonblank reason of at most 2,000 characters; NUL is rejected. Closing the dialog or switching language preserves its same-page draft.
3. Select **Save reevaluation task**. Inspect the durable task's reason, state and recorded Verdict. A failed task uses **Review & retry gate task** to create a linked retry with the original payload. An uncertain submission retains its original request identity.
4. The latest `FINAL` / `TEST_RUN` Verdict leads the overview. Changed state appends a new sequence; an unchanged evaluation reuses the latest matching Verdict while retaining each task's reason and audit records. The report keeps its original Verdict reference and shows when a newer formal decision exists.

Resolving or closing a Finding does not change official test results. A recorded failing execution still blocks release. Gate-only work does not call a model, Bridge, Runner or Git and does not reopen the session. Verify an actual code fix in **New round from this run** with reviewed inputs and the repaired SHA. FAILED, CANCELLED, active, waiting, recovery-required and unreported CLOSED bindings cannot use this exception.

中文操作：打开“发现”核对证据 → 选择合法下一状态并填写处置原因 → 查看“处置历史” → 在已关闭且有报告的运行选择“重新评估质量门禁” → 填写最多 2,000 字符的非空重评原因 → “提交重评任务” → 从任务打开已记录判定，对照最新 FINAL 与原报告引用的历史判定。失败后检查并关联重试，不重新启动会话。处置记录不能证明修复，验证代码修复需创建新轮次。

## Coverage and decisions

`RiskCoverageEvaluator` requires FUNCTIONAL for every non-obsolete Risk, plus BOUNDARY, FAILURE, CONCURRENCY, SECURITY, or PERFORMANCE for the corresponding category; RELIABILITY additionally requires RECOVERY. Only relationally linked ACTIVE TestCases contribute. Each Run's immutable PolicySnapshot can declare additional global or category-specific dimensions. Planner, Verifier, Gate, and Web use the same resolved rules and policy hash.

The workbench displays eligible Requirement/Risk/TestCase counts, Risk identification coverage, Risk test coverage, and each Risk's required/covered/missing dimensions. Empty denominators return `null` and display as unknown.

The gate requires full identification/design coverage and every active Case's latest OFFICIAL execution to match the source commit, complete successfully, and provide verified trusted metadata and JUnit artifacts. Confirmed policy-blocking product defects prevent release. Missing facts produce `BLOCKED`, observed failures produce `RELEASE_BLOCKED`, and complete passing facts produce `RELEASE_READY`. Design coverage alone never produces a release decision.

Runs sharing a SourceSnapshot serialize Gate reads with canonical proposal commits and implementation-status updates, so a decision and its state hash describe the same snapshot state. These locks are released for actual Agent/test execution. Verdict hashes bind canonical inputs, artifact integrity, the Gate rule version, and the computed decision; reuse requires the latest matching Verdict in that Run/scope/status, with the same policy, decision and evidence manifest. Returning to a previously seen state still appends a new sequence rather than rewinding the current decision.

## Run the complete development workflow

The commands below describe the host-based legacy development profile. For the current containerized platform and persistent Host Harness Bridge profile, use the [containerized deployment guide](docs/CONTAINERIZED_DEPLOYMENT.md). Do not infer persistent-session support from starting only the legacy host services.

Use Python 3.12, PostgreSQL 17, Node.js 22, Git, a Docker CLI/daemon, and a Codex CLI available and authenticated on the Worker host. Host-based Worker execution preserves the operator's existing Agent authentication and repository access.

Start PostgreSQL and install backend dependencies:

```bash
docker compose up -d postgres
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,interactive]'
cp .env.example .env
alembic upgrade head
```

Build the trusted Runner image before running tests:

```bash
bash scripts/build-runner-image.sh python-pytest-v1
bash scripts/build-runner-image.sh python-api-v2
```

The operator script downloads the full pinned/hash-verified binary wheel closure, resolves the base image digest and builds offline (`--network none`). The two defaults are `hypertest-runner:py312-controlled` and `hypertest-runner:py312-api-v2`; configure `HYPERTEST_RUNNER_CONTROLLED_IMAGE` / `HYPERTEST_RUNNER_API_V2_IMAGE` consistently on API and Worker. Existing legacy unbound Runs continue to use their configured `HYPERTEST_RUNNER_IMAGE` and are never silently migrated or rebound. Profile v1 lock/launcher contents are versioned contracts: future changes need a new profile version. Runner execution never builds, pulls or installs dependencies.

Choose the approved profile in the Web's **Execution environment** step. For the API profile enter, for example, `examples.api_sut.app:app`, health path `/health` and a 30-second startup limit. The request shape is:

```json
{"environment":{"profile_id":"python-api-v2","service":{"app":"examples.api_sut.app:app","health_path":"/health","startup_timeout_seconds":30}}}
```

`GET /execution-environments` reports API-host image inspection, not a guarantee that a Worker or SUT is ready. Bootstrap freezes the actual image ID; executions revalidate that ID rather than the current tag. Missing/altered images fail closed. `HYPERTEST_BASE_URL=http://127.0.0.1:8765` exists only inside the isolated Runner. Generated tests send real HTTP to that variable; they do not launch the service. API-v2 fixes `-c /dev/null --noconftest --rootdir=/repo`, so HTTP tests and fixtures must be self-contained in their submitted module. Repository pytest configuration and conftest files are not loaded. Archived API-v1 and pytest-v1 keep the original launcher and lock bytes; existing API-v1 image configuration remains available for history and replay. Service logs and lifecycle/readiness facts are verified Runner evidence. Readiness does not imply passing tests. Environment-bound Runs require Docker. Arbitrary dependencies, external services/databases, credentials and remote SIT are separate contracts.

Install Web dependencies, configure the host, and start API, Worker, and Web:

```bash
npm --prefix web ci
export HYPERTEST_ARTIFACT_ROOT="$PWD/.hypertest-artifacts"
export HYPERTEST_WORKSPACE_ROOT="$PWD/.hypertest-workspaces"
mkdir -p "$HYPERTEST_WORKSPACE_ROOT"
bash scripts/dev.sh
```

The helper requires the installed `.venv` and `web/node_modules`, verifies Node.js 22, applies migrations, and starts API, Worker, and Web. API/Web listen on loopback. Exiting the helper cleans up its own service processes. Set `HYPERTEST_DEV_API_PORT` / `HYPERTEST_DEV_WEB_PORT` to override defaults 8000 / 3000. `bash scripts/dev.sh --check` applies migrations and verifies API/Worker imports without starting services.

The supervisor supports macOS's system Bash and Linux without GNU `setsid` or
`wait -n`. Configure paths for the actual host; `/workspace` is not a required path.
`HYPERTEST_CODEX_BINARY` selects an installed official CLI (default `codex`).
`HYPERTEST_CODEX_MODEL` optionally selects a model supported by that Worker's account.
If desktop/user CLI settings select an incompatible model, explicitly set
`HYPERTEST_CODEX_IGNORE_USER_CONFIG=true` to use the standalone CLI defaults while
retaining its existing authentication. This does not change the user's global
configuration or copy credentials. HyperTest supplies a typed output schema and
collects the CLI's saved final response; model tools remain in the read-only sandbox.

`HYPERTEST_WORKSPACE_ROOT` must contain the repository checkout paths supplied through Web. **Prepare pinned checkout** creates or reuses a clean pinned checkout under `.hypertest-checkouts/{source_snapshot_id}/repo` inside that root. Automatic preparation supports credential-free `https://github.com/owner/repository` URLs, uses the existing Git proxy/authentication, and does not reset operator checkouts. Other hosts retain the existing-workspace path. Each checkout must have the matching origin, full pinned commit at HEAD, and clean tracked content. Agent work and generated-test execution use temporary copies; keep the source checkout at its pinned commit.

To start each service manually instead, run `uvicorn hypertest.main:app --host 127.0.0.1 --port 8000` in the activated Python environment, start the Worker in a second terminal with the same configuration, then start Web in a third terminal:

```bash
source .venv/bin/activate
python -m hypertest.worker
```

```bash
cd web
HYPERTEST_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1
```

```text
Web:      http://localhost:3000
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
```

The capabilities panel reports installed Agent and Runner choices and recent Worker liveness. API and Worker must share the PostgreSQL database, artifact store, workspace root, and host integration configuration. Codex authentication, checkout access, a usable Docker daemon, and the trusted image must exist on the Worker host before their respective actions can succeed.

Worker settings default to `HYPERTEST_WORKER_LEASE_SECONDS=30`, `HYPERTEST_WORKER_HEARTBEAT_SECONDS=5`, and `HYPERTEST_WORKER_POLL_SECONDS=1`. Heartbeats must be positive and shorter than the lease. Each Worker executes one request at a time; multiple Workers can process different Runs. `python -m hypertest.worker --once` recovers expired leases and processes at most one queued request. Mission Attempts and Executions record their owning Job through immutable relational links, so recovery does not infer ownership from machine timestamps.

Worker shutdown interrupts active work. Docker staging/execution containers and their volumes carry the owning Job UUID; recovery first commits interrupted domain history, then attempts cleanup of only those labelled resources outside database locks. Cleanup availability and removal counts are audited. If Docker is unreachable, or a provider process survived a hard host/process kill, inspect external resources before retrying. The system preserves canonical history without claiming exactly-once external execution.

Local and Debian 13 server acceptance cover both supported stdlib/pytest backend paths using real Codex proposals and trusted Docker execution: passing applications produced FINAL `RELEASE_READY`; defective applications produced actual failures, evidence-backed Findings, and FINAL `RELEASE_BLOCKED`. Their original execution identity is `89d15ae` (212 tests); that history remains preserved. The later `79d3292` baseline passed 223 tests, followed by the deployed main `d20a2bc` release with 302 backend checks and a separate passing clipboard-PRD Web cycle. Source resolution, automatic checkout, large-input transport and failure details belong to that prior release; their checks and real Web cycle are recorded separately in [first-phase acceptance](docs/FIRST_PHASE_ACCEPTANCE.md), alongside exact Run/Execution/Evidence/Verdict identities and supported scope.

The [old cloud runtime diagnosis](docs/CODEX_RUNTIME_TROUBLESHOOTING.md) retains the historical EROFS and CONNECT 403 findings; it does not describe current local or server authentication. Provider-neutral tests remain distinct from live acceptance, and supported-path results do not establish semantic completeness or another host's integration readiness.

For a controlled local-development fallback, explicitly set `HYPERTEST_RUNNER_ALLOW_LOCAL=true` for API and Worker and select the local Runner. It runs trusted repository code as a host process; it is not a container sandbox. Docker remains the default Runner.

`docker compose up --build` can host the database/API/Web browsing stack. Its default services do not start the independent Worker or inherit the host's Agent login, tools, checkouts, or artifact configuration. Use the host workflow above for working Missions and official Runner execution unless the Worker and those integrations are explicitly provisioned for the containers.

## API

All routes use `/api/v1` by default. OpenAPI documents request and response schemas.

```text
GET  /health
GET  /capabilities
GET  /execution-environments

POST /projects
GET  /projects
GET  /projects/{project_id}
GET  /projects/{project_id}/test-runs
POST /projects/{project_id}/source-snapshots
POST /projects/{project_id}/runs/bootstrap
POST /policy-snapshots
GET  /source-snapshots/{source_snapshot_id}
GET  /source-snapshots/{source_snapshot_id}/prd
GET  /source-snapshots/{source_snapshot_id}/configuration
GET  /policy-snapshots/{policy_snapshot_id}

POST /test-runs
GET  /test-runs/{test_run_id}
GET  /test-runs/{test_run_id}/requirements
GET  /test-runs/{test_run_id}/risks
GET  /test-runs/{test_run_id}/test-cases
GET  /test-runs/{test_run_id}/coverage
GET  /test-runs/{test_run_id}/missions
POST /test-runs/{test_run_id}/missions
POST /test-runs/{test_run_id}/plan-next
POST /test-runs/{test_run_id}/advance
POST /test-runs/{test_run_id}/prepare-workspace
POST /test-runs/{test_run_id}/jobs
GET  /test-runs/{test_run_id}/jobs
GET  /test-runs/{test_run_id}/input-requests
GET  /test-runs/{test_run_id}/implementations
GET  /test-runs/{test_run_id}/implementations/{implementation_id}/content
GET  /test-runs/{test_run_id}/harness
GET  /test-runs/{test_run_id}/reports
GET  /reports/{report_id}/content
GET  /test-runs/{test_run_id}/executions
POST /test-runs/{test_run_id}/executions
GET  /test-runs/{test_run_id}/evidence
GET  /test-runs/{test_run_id}/findings
GET  /test-runs/{test_run_id}/verdicts
POST /test-runs/{test_run_id}/evaluate

GET  /missions/{mission_id}
POST /missions/{mission_id}/execute
GET  /missions/{mission_id}/attempts
GET  /missions/{mission_id}/proposals
POST /missions/{mission_id}/retry
POST /missions/{mission_id}/cancel
GET  /executions/{execution_id}
GET  /evidence/{evidence_id}/content
POST /findings/{finding_id}/transition
GET  /findings/{finding_id}/history?limit=50
GET  /jobs/{job_id}
GET  /jobs/{job_id}/activity
POST /jobs/{job_id}/cancel
POST /jobs/{job_id}/retry
GET  /input-requests/{input_request_id}
POST /input-requests/{input_request_id}/answer
```

The prepare-workspace endpoint needs no request body and returns `workspace`, `repository_url`, and the pinned `commit_sha`. PRD and configuration text reads verify their saved snapshot checksums.

Web uses the Job API for long operations. `POST /test-runs/{id}/jobs` accepts `operation`, `idempotency_key`, optional `mission_id` (required only for EXECUTE_MISSION), and operation-specific `payload`, then returns HTTP 202. Supported operations are ADVANCE_RUN, EXECUTE_MISSION, EXECUTE_TESTS, EVALUATE_GATE, and PREPARE_WORKSPACE. A request to advance the Run is:

```json
{
  "operation": "ADVANCE_RUN",
  "idempotency_key": "run-cycle:request-1",
  "payload": {
    "workspace": "/workspace/my-project",
    "backend": "docker",
    "timeout_seconds": 300,
    "max_steps": 12
  }
}
```

For automatic GitHub checkout, replace `workspace` with `"prepare_workspace": true`; provide exactly one source mode. The same Worker request prepares the pinned source before starting missions. `POST /sources/resolve` accepts `repository_url` and a branch/tag `revision` before bootstrap, returning the full SHA without changing canonical state or a checkout. Other origins continue to use an existing workspace.

Poll the Run's Job list or `GET /jobs/{id}` for state and result. The same key and input return the original request; conflicting input or another active request returns 409. Cancellation returns 202. Retry accepts a new `idempotency_key` and returns 202 with a new linked Job. A cancelled Mission remains cancelled; explicitly plan a new Mission generation when its work is still needed. A FAILED Mission must first use the controlled Mission retry action before execution can be submitted again. `RETRYING` is displayed as **Awaiting retry**: it is a stopped Mission waiting for an explicit action, not evidence that a Worker is actively executing it. `GET /capabilities` includes `worker.available`, `worker.last_seen_at`, and `worker.active_workers`.

### Independent post-session Gate API

Submit `POST /test-runs/{id}/jobs` with a new request identity:

```json
{
  "operation": "EVALUATE_GATE",
  "idempotency_key": "gate-review:request-1",
  "payload": {"finalize": true, "reason": "Review the recorded Finding dispositions."}
}
```

For bound Runs this requires a CLOSED binding, its original CLOSED primary session, an accepted same-Run/binding report and no conflicting active work. The reason is trimmed, nonblank, at most 2,000 characters and cannot contain NUL. It remains task/audit metadata and does not override Gate policy or enter the state hash. Legacy unbound Gate payloads retain their optional-reason compatibility. `GET /findings/{id}/history?limit=50` returns bounded, typed disposition events and an explicit truncation flag, without raw audit metadata. See [the operator guide](docs/WEB_PRODUCT_WORKFLOW.md#会话关闭后的发现处置与门禁重评--post-session-disposition-and-gate-reassessment).

### Safe task activity API

`GET /jobs/{job_id}/activity?limit=30&before=<event UUID>` reads recent operational activity without starting work. The response separates the server observation time, current Mission/Attempt, current claim's most recent Provider signal and that Job's Worker heartbeat. Items contain fixed activity types, source, platform timestamps, count and HyperTest-owned relational IDs; they do not expose Provider events, reasoning, messages, commands, paths or stderr. Earlier records can be read using the returned cursor. Each Attempt retains at most 200 recent records; this is a bounded activity view, not a complete transcript.

A Worker heartbeat proves Worker liveness, not model progress. A quiet model may still be working. No progress percentage, automatic cancellation or replay follows from silence; waiting for a human answer, official Runner work and terminal Jobs are shown according to their actual states. Read-only activity polling has no effect on Canonical State, Evidence or Verdict. See [the operator flow](docs/WEB_PRODUCT_WORKFLOW.md#任务活动与等待诊断--task-activity-and-waiting) and [activity acceptance](docs/MISSION_ACTIVITY_ACCEPTANCE.md) for current verification and limits.

### Human input API

Question reads return the recorded question/options, status, original answer/timestamps, `row_version`, and the owning Run/Mission/Attempt/AgentSession/Job identities. Options are suggestions; free-text answers remain allowed. A question can be `PENDING`, `ANSWERED`, `CONSUMED`, or `CANCELLED`. It belongs to operational Mission context and does not itself create a Canonical Requirement or Evidence.

Submit an answer to `POST /input-requests/{id}/answer`:

```json
{
  "answer": "Use the isolated test tenant described in the PRD.",
  "expected_row_version": 1,
  "idempotency_key": "answer:question-1:request-1"
}
```

The answer must contain 1–12,000 characters, cannot be blank or contain NUL, and is stored without trimming or line-ending normalization. HTTP 202 returns `{ "input_request": { ... }, "job": { ... } }`: saving the answer and changing its original Job from `WAITING_INPUT` to `QUEUED` are atomic. Waiting retains the Run's active-work reservation but releases its Worker lease; a Worker claims the queued continuation with a **new lease** and resumes the same Mission/Attempt/AgentSession. It does not create a replacement Job or rewrite the frozen Job payload/specification.

If submission is uncertain, retain the exact answer, original `expected_row_version` and idempotency key, refresh the recorded state, then explicitly retry the same request if needed. The same key/body returns the original question/Job even after consumption or completion. A different saved answer, changed request identity, stale question, or incompatible task state returns 409. Web keeps the draft and explains the refresh/retry action. A `WAITING_INPUT` Job can be cancelled through `POST /jobs/{id}/cancel`; direct Mission cancellation is not the waiting-task control path. The supported human-input path uses durable `ADVANCE_RUN` or `EXECUTE_MISSION` work, rather than keeping a synchronous HTTP request open.

The older direct `/advance`, Mission execute, Runner execute, Gate, and prepare-workspace endpoints remain available for compatibility. They run synchronously only in the unbound direct compatibility mode and reject queued/bound control bypasses as well as conflicting work. The direct advance loop rechecks operation ownership before and after each Planner step and stops if a durable request was admitted between service commits; it does not hold exclusive ownership for its entire loop. The advance payload accepts `workspace`, `backend` (`docker` by default), `timeout_seconds`, and `max_steps` (default 12, range 1–32). Its controller uses real Mission/Runner/Gate services until a final Verdict, interruption, rejection, or work limit; the HTTP API does not accept synthetic Agent results. Job results retain completed steps and a stop reason.

The bootstrap request accepts `repository_url`, a full 40- or 64-character `commit_sha`, `prd_text`, optional `branch`, `configuration_text`, `environment`, `policy`, and `idempotency_key`. Retrying the same project/key returns its original Run. A supported policy example is:

```json
{
  "gate": {
    "blocking_finding_severities": ["BLOCKER", "CRITICAL"]
  },
  "coverage": {
    "version": "risk-design-policy/v1",
    "default_dimensions": ["FUNCTIONAL", "FAILURE"],
    "by_category": {
      "CONCURRENCY": ["CONCURRENCY", "BOUNDARY"]
    }
  }
}
```

Global `default_dimensions` apply to every Risk. `by_category` replaces a category's specialized dimensions; unspecified categories retain the baseline specialization. FUNCTIONAL is always required, including when a configured list is empty. Unknown rules, categories, test dimensions, versions, and duplicate dimensions are rejected before creating immutable Policy state. The Coverage API exposes `rule_version` and `effective_policy_hash`; equal effective rules have the same hash regardless of dimension order. Omitting coverage preserves the original baseline.

The Web creation flow guides Source → Requirements → Policy → Review. Its Policy controls configure shared dimensions, per-category dimensions, and blocking Finding severities; FUNCTIONAL and BLOCKER remain mandatory.

Direct `POST /policy-snapshots` callers must provide `content_sha256` matching the canonical JSON of `compiled_policy` (sorted keys, compact separators, UTF-8). Bootstrap computes this digest for Web users. Creating a new PolicySnapshot does not alter existing Runs.

## Migrations and validation

`0004_test_design` creates TestCase and RiskTestCase. `0005_delivery` adds canonical implementations, executions, evidence, findings, verdicts, relational links, proposal types, and delivery history guards. `0006_immutable_contracts` adds immutable SourceSnapshot/PolicySnapshot and frozen Mission contract guards without rewriting historical rows. `0007_durable_jobs` adds operational jobs, Worker liveness, request idempotency, one-active-request-per-Run enforcement, and immutable Job history. `0008_job_ownership` adds immutable nullable Job FKs to Mission Attempts and Executions, with same-Run and supported-operation guards. Existing direct-operation history keeps null ownership. `0009_mission_inputs` adds durable question/answer history and waiting/resume governance. `0010_mission_activity` adds a separate bounded operational activity table without backfilling or rewriting history. `0011_execution_environments` adds a nullable immutable Source environment binding; old SQL NULL inputs retain their original source/Gate hash semantics. `0012_api_environment_v2` widens only the allowed profile CHECK; API-v1 rows remain unchanged. `0013_run_bindings` adds persistent Run ownership and Run-scoped questions without merging historical sessions. `0014_harness_operations` adds operational checkpoints, tool/budget ledgers, reports, runtime control and controlled GitLab operation history. Upgrade from a clean database applies `0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010 → 0011 → 0012 → 0013 → 0014`.

Backend validation requires a real PostgreSQL database:

```bash
ruff check src tests alembic
alembic upgrade head
pytest -q
```

Tests isolate their workspace and artifact paths from the operator's `.env` settings.
For a separate local test database, create and migrate it once, then set
`HYPERTEST_TEST_DATABASE_URL` in the environment or ignored `.env` file:

```bash
docker compose exec postgres createdb -U hypertest hypertest_test
export HYPERTEST_TEST_DATABASE_URL=postgresql+asyncpg://hypertest:hypertest@127.0.0.1:5432/hypertest_test
HYPERTEST_DATABASE_URL="$HYPERTEST_TEST_DATABASE_URL" alembic upgrade head
pytest -q
```

The test database must already exist; pytest never drops, recreates, or clears a
database. Without this optional setting, tests use the configured development/CI
database, which must be disposable.

Frontend work follows [PRODUCT.md](PRODUCT.md) for users and workflow and [DESIGN.md](DESIGN.md) for visual tokens, navigation, responsive behavior and interaction states. The default is code-led implementation with bilingual support: prioritize progress, failure reasons, formal verdicts and trusted evidence. See [frontend design acceptance](docs/FRONTEND_DESIGN_REVIEW.md) for browser checks and their scope. The four foundational specifications retain authority over domain and protocol semantics.

Web validation:

```bash
cd web
npm ci
npm test
npm run typecheck
npm run build
```

GitHub Actions runs backend checks against PostgreSQL 17 and the mandatory Web job on Node.js 22, installing each job's dependencies once. Tests cover the canonical Planner cycle, proposal boundaries, trusted Runner facts, evidence integrity, finding lifecycle, deterministic Gate decisions, Web APIs, and PostgreSQL history constraints.

## Historical delivery records

The following notes preserve earlier release identities and acceptance results. Their then-current access and controller descriptions are historical; use the deployed baseline, current access guide and profile rules above for operation.

The **ADR-013 containerized platform and persistent Harness profile are implemented and deployed**. Each new Run retains one native Codex session across typed missions, trusted execution, questions, diagnosis and reports. The bilingual Web exposes session recovery and integrity-checked reports. Local implementation evidence is recorded in [ADR-013 acceptance](docs/ADR013_ACCEPTANCE.md). The [production cutover and real acceptance record](docs/ADR013_PRODUCTION_DEPLOYMENT.md) documents the 2026-10-19 migration: production source is `f415fd0`, API/Worker/Bridge runtime builds use `95e92c5`, and the database is at `0014_harness_operations`. The formal positive chain completed 49 passing Docker tests under the initial release, then explicit same-session recovery, its second question, Gate and a `RELEASE_READY` report under the runtime fix; the negative chain completed fully under the fix with 14 passing / 8 failing assertions, diagnosis and a `RELEASE_BLOCKED` report. Existing data, Codex OAuth, the then-configured VPN egress allowlist and SSH tunnel were preserved. The [containerized deployment runbook](docs/CONTAINERIZED_DEPLOYMENT.md) covers fixed images, the host Bridge, guarded startup and paired recovery. Real GitLab creation, other Providers and subsequent Web changes require separate acceptance.

The preceding increment added **controlled Python / ASGI API environments** under migrations `0011_execution_environments` / `0012_api_environment_v2`. The five-step Web flow freezes an approved prebuilt image, locked dependencies and a typed service entry point at Run creation. The trusted Runner starts the service inside its isolated container, probes HTTP readiness and executes real HTTP pytest tests; no host port or runtime package installation is introduced. Automated checks and real Web/Codex/Docker success (91 PASS / RELEASE_READY) and business failure diagnosis (30 PASS,22 FAIL / RELEASE_BLOCKED) have passed; exact acceptance identities are recorded separately in [controlled-environment acceptance](docs/CONTROLLED_ENVIRONMENT_ACCEPTANCE.md). At that initial acceptance, production was `a48bc96` / schema0009; PR #7 and PR #8 were subsequently merged and deployed as the historical `0a2af9c` / schema0012 baseline, before the ADR-013 cutover above.

The preceding increment adds a persistent, bilingual **Agent activity** panel and waiting diagnostics under migration `0010_mission_activity`. Fixed safe event types and platform timestamps distinguish current-turn Provider signals from Worker heartbeat without recording transcript content or changing Evidence/Verdict. Local checks passed **384 backend / 41 Web tests**, Ruff, migrations, typecheck, production build and audit 0. A fresh real Web/Codex/Docker cycle, including waiting, API/Worker restart and same-thread answer/resume, reached **FINAL RELEASE_READY / JUnit 8 PASS**. See [activity acceptance](docs/MISSION_ACTIVITY_ACCEPTANCE.md) for source identity, preservation and limits. Its initial pre-deployment record refers to `a48bc96` / schema0009; that historical state is superseded by the later PR #7 / #8 deployment above, preserving the recorded VPN/SSH access policy.

The delivered `WAITING_INPUT` workflow persists Mission questions, Web answers and continuation of the same durable Job under migration `0009_mission_inputs`. Local and server real Web/Codex/Docker acceptance passed before PR #6 was merged and deployed as `a48bc96`. See [human input operation](docs/WEB_PRODUCT_WORKFLOW.md#等待输入回答并继续--waiting-for-input-answer-and-continue) and [continuation acceptance](docs/WAITING_INPUT_ACCEPTANCE.md); earlier records retain their own execution identities.

Delivery has two stages. **Stage 1**, deployed as `73dff989b87fa7349d9b36bd8416ece948a82212`, passed 9 real PRD-file fixtures/15 native-browser checks, 20 frontend regressions and fresh Web checks. Its backend inputs were unchanged from d20/the 302-test source; that historical 114-input manifest is `0d58f4c0990f87d50b49c15b9148c72bdbe3957e5093d5f91a8626e6476d2c07` and does not identify the subsequent backend scope fix.

The historical VPN entry **http://155.138.206.106:8080** was active in the Stage 1 record, restricted at both UFW and nginx to the then-configured VPN peer. SSH22 and `127.0.0.1:8080` were retained as a fallback then; API, Web backend and PostgreSQL remained loopback-bound. This shared-egress network permission is not individual login/RBAC. Actual release/network results are maintained in the [latest delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md) and [server operations](docs/SERVER_OPERATIONS.md).

The first production file-import Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5` correctly stopped **BLOCKED**: 10 Requirements, 6 Risks and 8 Cases included two erroneous Runner-infrastructure cases. The real implementation Agent returned PARTIAL with 6 proposals; verification rejected them (`RESULT_NOT_COMPLETED`), leaving **0 Canonical Implementations / Executions / Evidence / Verdicts**. [preserved failed-run record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-first-attempt-2026-10-17.json). HTTP Project/Run/Job creation and the exact edited 605-byte PRD/hash were verified; this is not a complete passing cycle.

**Stage 2** changes backend runtime context and Codex guidance to distinguish the application's requirements from instructions about testing it. Authoritative scope is clarified in [domain §12](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement) and [TMP §9](docs/protocol/TEST_MISSION_PROTOCOL.md#9-mission-context). This stage is no longer backend-identical to d20/302. Its new freeze passed **303 backend tests / 3 warnings (48.70s)**, Ruff, test-DB Alembic head 0008 and a fresh independent **20-test Web/typecheck/build/audit-0** verification. Source-input manifest is `4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90`; it includes uncommitted changes above 73d and is not that commit SHA. The final release SHA/deployment and a fresh-Project real-model cycle using the same PRD/source/configuration/Policy content belong to the [latest delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md). No prior accepted state is rewritten, PARTIAL is not accepted, and Gate rules are not relaxed.

## HyperTest Local

本地模式首次接入、已有任务绑定及恢复可使用独立的 [hypertest-local-task-onboarding Skill](skills/hypertest-local-task-onboarding/SKILL.md)：将完整 `skills/hypertest-local-task-onboarding/` 目录复制到所用 Agent 的技能目录（Codex 可用 `~/.codex/skills/`），或通过支持 GitHub 路径的 Skill 安装器选择本仓库该路径；随后用 `$hypertest-local-task-onboarding` 调用。此操作只安装指南，不安装 Local runtime、不新增授权，也不将该 Skill 补入旧发行包。

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](docs/LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](docs/local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。


本源码分支仅交付 Local（ADR-020）与 TaskSyncCore（ADR-021）的 Local 消费方。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

原 ADR-018 全文、TMP §45 与领域 §50 保持本分支基线原文。原 API/profile、task:sync、
Project/actor owner、完整请求、expected_version 与历史语义不变；hypertest_sync_task 不是 PATCH。
同一真实父会话由一个有效 LocalSyncCoordinator 接受 Hook 触发与显式 MCP；子代理只回交父任务。
只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录。
冻结后保留完整请求/key/version；SENT/UNKNOWN/失答及 NOT_FOUND 只 GET 原 key，不自动再次 POST。
有效 ACK 后完整读回固定接受版本才确认本次同步；传输状态不重写 reported_result，Stop 不代表 PASS/COMPLETED。

Local 发行独立使用 local-vSEMVER，旧 mcp-v0.1.0/mcp-v0.2.0 历史不重标。
安装只复用既有私有 Project 授权，不申请 Operator key、签发 grant 或复制模型登录；
Hooks 需显式选择 workspace 或私有 approved artifact policy，版本匹配后启用。
升级/回退/卸载保留私有身份、账本、未决 key、源产物、用户项目与其他宿主配置。
Cloud/Local 共享 Project 的设计与任何外部 Cloud 实施进度不由本 Local 源码分支声称已交付。
