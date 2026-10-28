# HyperTest One MVP status

> **历史记录，不是当前状态入口。** 本文汇集 2026-10-19 至 2026-10-23 各轮冻结时的实现、部署与验收；下文“current”“生产”“待部署”等均指各自记录时点，不代表当前运行环境。当前待办和交付请查 [TODO](TODO.md)、[跟进交付](FOLLOWUP_DELIVERY_20261023.md) 与 [服务器操作](SERVER_OPERATIONS.md)，实际部署须现场核对。新 Local 接入按 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 使用显式 CLI/Skill 归档，旧 MCP/Hooks 仅保留兼容历史与恢复。

## Cloud SDK + Codex 集成状态（2026-10-23）

Cloud 当前仅实现官方 Python SDK + DeepSeek Harness + 显式 opt-in Codex；Claude Code 保持占位。source30 Worker / source29 helper 的 r8 Task 固定 v19 COMPLETED / reported PASS，canonical 固定 SSH 专项通过；source31 对同一 v19 固定快照的 SNAPSHOT_REASSESSMENT strict PASS，独立只读重放 19 项通过。重评没有新的 current GET、模型 / SSH / SUT 执行；来源仍是 runtime-reported，不是独立 writer 证明，也不升级 legacy VERIFIED / Gate。旧 source30 NON_PASS、r7 UNKNOWN / HELD 与失败原件保持。最终合并树、统一 Web 入口与测试服务器常驻 Cloud 服务尚未进行本轮验收或部署；默认关闭。

正式候选迁移为管理 `0024_local_task_binding` 后的 `0025_cloud_tasks` → `0026_cloud_ssh_operations`；旧隔离 fixture 编号与历史通过记录不改。capabilities 的 supported 仅表示实现支持，当前配置与每 Attempt Worker 准入另列。Local 包、既有会话同步、FAIL / UNKNOWN / 幂等读回契约与项目管理历史保持；当前未把新树或 Web 声称为已部署。详见[Cloud 状态](CLOUD_IMPLEMENTATION_STATUS.md)。以下旧发布记录各保留原时点身份。

This document separates the usable single-operator testing workflow from the longer-term product roadmap. The foundation documents remain authoritative for domain ownership, protocol, and evidence trust.

## Historical increment: current-Agent MCP execution (2026-10-20)

ADR-016 is deployed from PR #17 at **`c7cd43ad6346d8ce6c85564f7838afbb017f2da4`** / schema **`0020_interactive_tool_inbox`**. PR and main CI passed with 967 tests passed and 21 skipped. The actual current Codex Desktop Agent used the official MCP SDK console to reason and submit proposals, without another model; the platform's trusted Docker Runner completed 33 real HTTP tests, followed by five hash-verified Evidence reads, FINAL `RELEASE_READY` and a hash-verified two-page report. Two explicit Worker recoveries retained the original Run/native/workspace and advanced epochs 1 → 2 → 3. Final independent historical preservation passed 39 checks. The original server and Connector-managed local Harness paths remain, with no new full-cycle claim for those modes, issue writes or private-SUT business acceptance. See [ADR-016 production deployment](ADR016_PRODUCTION_DEPLOYMENT.md); the earlier [27-test isolated cycle](ADR016_ACCEPTANCE.md) retains its own identities and limits.

## Historical ADR-015 increment: dual-mode Harness (2026-10-19)

ADR-015 is deployed at application **`63bd6cc`** / schema **`0018_harness_selection`**, retaining the existing server Host Bridge and adding the local Connector mode. Local Provider, Git and controlled Issue credentials stay on the selected node; accepted source and typed proposals cross bounded authenticated channels, while trusted Runners still produce formal facts. Production cutover and historical data / authentication / access preservation passed. **Strict external TLS verification passed; the online local-Connector core E2E passed.** Existing isolated positive, negative, recovery and authorized Issue evidence remain separate; extended device-failure cases are not all accepted. See [production deployment](ADR015_PRODUCTION_DEPLOYMENT.md) and [isolated acceptance](ADR015_ACCEPTANCE.md).

## Historical PR #13 increment: actionable source-preparation diagnostics

Source preparation records bounded platform-owned stages, categories and next-step suggestions in the failed Job. The bilingual Web shows them beside the original task's existing retry controls; legacy failures without saved diagnostics remain explicitly unknown. Git output, commands, URLs, paths and credentials are excluded. Fixing external Git/network/storage conditions permits an explicit linked retry with the same frozen input; changing source input requires a reviewed new round. Existing session recovery and terminal-binding rules remain intact.

Local real 390px Web creation/import/start/failure/retry completed one Codex session and an OFFICIAL Docker execution: **37/37 PASS**, verified Evidence, FINAL RELEASE_READY and an accepted report. The original FAILED Job and fixed inputs remained unchanged. **808 backend checks including 18 real Docker checks**, **104 Web tests**, Ruff, Alembic head0014, typecheck and production build passed. No migration, merge or production deployment is included. Exact runtime/frontend identities and limitations are in [source-preparation acceptance](SOURCE_PREPARATION_DIAGNOSTICS_ACCEPTANCE.md).

## Historical PR #11 implementation freeze: post-session Finding governance and Gate reassessment

The deployment-pending wording and test counts below describe the PR #11 development freeze. PR #11 was subsequently merged/deployed; its subsequent production verification is recorded below and in its acceptance record.

[ADR-014](architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md) is implemented on this branch. After a binding and its original primary session both close with an accepted same-Run/binding report, an operator can record Finding dispositions and explicitly queue an independent `EVALUATE_GATE` task. The task requires `finalize: true` and a trimmed, nonblank reason of at most 2,000 characters without NUL. The reason is retained in the Job and paired Audit/Outbox, without entering the Gate fact hash or overriding policy. Active, waiting, recovery-required, failed, cancelled and unreported closed sessions cannot use this exception; unbound legacy Runs keep their existing Gate contract.

The bilingual Web connects disposition history → explicit reason → durable task → recorded Verdict. History reads are bounded and project only typed status/resolution/version/reason fields. Read failures retain loaded records and the current draft. A failed Gate task uses a linked retry preserving its original payload; uncertain submission retains its request identity. The latest FINAL / TEST_RUN Verdict leads the overview; the original report retains its original Verdict and marks later decisions separately. Reassessment creates no model/Bridge/Runner/Git work, does not reopen the session and does not modify old execution facts, reports or FINAL records. Disposing a Finding does not waive an official test failure; verifying a code fix requires a new reviewed testing round.

**Application deployment is pending; local real Web/Codex/Docker acceptance passed.** The fresh positive run passed 15/15 tests and its CLOSED Gate reused FINAL #1 RELEASE_READY. The negative run produced 18 PASS / 9 assertion FAIL and an accepted diagnosis/report; four human Finding transitions and three independent Gate tasks appended FINAL #2/#3, then reused #3 while preserving all original facts and report bytes. Closing the Finding did not waive failures. Frozen automated checks passed **686 backend tests / 18 opt-in Docker skips / 3 existing warnings**, Ruff, **96 Web tests**, typecheck and production build. There is no new migration; head remains `0014_harness_operations`. Two late operations-renderer inputs subsequently passed 48 targeted checks; their identity is recorded separately from the 686-test freeze. Exact source/check identities, real-run outcomes and preservation checks are recorded in [post-session Gate acceptance](POST_SESSION_GATE_ACCEPTANCE.md).

中文操作：打开发现并核对证据 → 填写处置原因、保存合法状态迁移 → 查看处置历史 → 在有已接受报告的 CLOSED 运行选择“重新评估质量门禁” → 填写最多 2,000 字符的非空重评原因 → “提交重评任务” → 从后台任务查看结果判定，区分最新 FINAL 与原报告的历史判定。失败使用“检查并重试门禁任务”；验证代码修复仍需创建新轮次。详见[双语操作指南](WEB_PRODUCT_WORKFLOW.md#会话关闭后的发现处置与门禁重评--post-session-disposition-and-gate-reassessment)。

## Historical deployed baseline and access (2026-10-20)

Production cutover completed on 2026-10-20 at 06:34:11.197055 UTC: application **`c7cd43ad6346d8ce6c85564f7838afbb017f2da4`**, Host Harness Bridge **`95e92c5`**, schema **`0020_interactive_tool_inbox`**, and fixed operations manifest **`61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d`**. The original database container/image/volume/start identity, authentication, sessions, files and access configuration remain. Independent final preservation retained 3,698 full historical rows across 49 tables plus the original node's stable configuration, and all 7,429 old files. The production current-Agent cycle used certificate-verified HTTPS; detailed cutover, recovery, content-verification and preservation boundaries are in [the ADR-016 production record](ADR016_PRODUCTION_DEPLOYMENT.md). The earlier ADR-015 `63bd6cc` / schema0018 deployment remains [historical evidence](ADR015_PRODUCTION_DEPLOYMENT.md).

The only supported Web access path is the configured allowlisted jump-host egress. Addresses and CIDRs stay in protected operator configuration. SSH remains for administration and manual recovery with forwarding disabled; no Web tunnel is retained. Routine deployments verify access-rule preservation and internal readiness; first activation or a changed access boundary requires additional connectivity checks. Earlier delivery sections below retain their then-current access facts and do not define the current policy.

## Deployed PR #10 capability: result review and a new testing round

The Web opens complete accepted requirement/risk/case details and linked assets, reads generated test source through a Run-scoped integrity-checked API, and exposes saved reports beside the quality verdict. Ended sessions lead to a reviewed new round; recovery and pre-binding source-preparation failures lead to the recorded task retry. A new round can reuse exact PRD/context text, every original policy field and environment requests, while selecting a repaired SHA and resolving current image identity again. Existing drafts and all old runs/results remain intact. That increment added no migration or quality-rule change; its local real acceptance remains recorded in [result-review acceptance](WEB_RESULT_REVIEW_RETEST_ACCEPTANCE.md).

## Historical cutover: ADR-013 containerization and persistent Harness

Implemented migrations `0013_run_bindings` / `0014_harness_operations`, a native Codex session per Run, fenced host Bridge calls, deterministic domain-tool admission, trusted Docker execution, both question scopes, explicit same-session recovery, reports and controlled GitLab operations. API, Worker, Web, nginx and PostgreSQL have a production Compose; Provider authentication and native sessions remain on the host. The cutover Web included session/report/recovery views and prevented execution retries against a closed binding. ADR-014 now adds only the independent Gate exception described above.

Local real Codex/Docker acceptance reached RELEASE_READY for the success and question/resume runs, and RELEASE_BLOCKED with an accepted diagnosis/report for the broken service. Worker and Bridge restarts during waiting preserved the original Job/session; explicit recovery preserved failed history and increased the binding epoch. Automated checks passed 629 backend tests with real controlled Docker enabled, 61 Web tests, Ruff/typecheck/build and npm audit 0. Exact checks, Linux staging results and limits are maintained in [ADR-013 acceptance](ADR013_ACCEPTANCE.md) and [containerized deployment](CONTAINERIZED_DEPLOYMENT.md).

PR #9 merged as `740a74d`; production cutover is complete at schema `0014_harness_operations`, with runtime build `95e92c5` including backup/health-check adaptations and the rejected-read session fix. Original data, Codex OAuth, the then-configured VPN allowlist and SSH tunnel were preserved at that cutover. Actual production Web/Codex/Docker acceptance reached 49 PASS and RELEASE_READY after two questions and explicit same-session recovery; a fresh broken-service run produced 14 PASS / 8 assertion failures, a diagnosis Finding and RELEASE_BLOCKED. Reports and evidence hashes were independently verified (41 positive and 43 negative checks). Final runtime CI passed 645 backend tests (18 opt-in Docker skips, 3 existing warnings), 61 Web tests, Ruff, Alembic, typecheck and build. See [formal production deployment](ADR013_PRODUCTION_DEPLOYMENT.md) for source/image identities, backups, observation and access evidence. Real external GitLab issue creation, other Provider adapters, multiple hosts and actual host reboot remain outside this acceptance.

## Historical increment: controlled dependencies and service API environments

The five-step bilingual Web selects approved Python/pytest or isolated ASGI API-v2 profiles. Bootstrap freezes actual image/dependency/service identity under migrations0011/0012; the Docker Runner owns start/readiness, real HTTP execution, bounded logs and cleanup. API-v2 isolates repository pytest configuration/conftest; archived API-v1 retains its original launcher, locks, image and history. Legacy NULL inputs retain original source/Gate hashes. **474 backend tests /18 opt-in skipped /3 existing warnings**, **18 independently executed real Docker checks**, **55 Web tests**, Ruff/typecheck/build and 19/19 isolated restore checks have passed. The v1 real attempts correctly ended with environment-error BLOCKED verdicts; fresh v2 Web/Codex/Docker acceptance passed both the 91-PASS RELEASE_READY path and the 30-PASS/22-FAIL product-diagnosis RELEASE_BLOCKED path, each with 28/28 independent checks in [the acceptance record](CONTROLLED_ENVIRONMENT_ACCEPTANCE.md). At this increment’s initial acceptance production was a48bc96/schema0009; PR #7 / #8 were later merged and deployed as the historical 0a2af9c/schema0012 baseline, before the ADR-013 cutover above.

## Historical increment: safe task activity and waiting diagnostics

This branch adds a bounded operational activity view under migration `0010_mission_activity`: fixed Provider/control-plane activity types, platform timestamps and counts, current Mission/Attempt, current-claim Provider signals and per-Job Worker heartbeat. It does not persist transcript content or change Canonical State, official Evidence, Coverage or Verdict. The Web keeps this information in a bilingual auxiliary task-detail panel, distinguishes waiting for human input from quiet Agent work, and preserves loaded records on refresh failure. Silence does not trigger automatic cancellation, retry or a percentage estimate.

Local acceptance passed **384 backend tests / 3 existing warnings**, Ruff, test/app Alembic head0010, independent **41 Web tests / typecheck / production build / audit 0**, and isolated paired-backup restore. A fresh real Web/Codex/Docker cycle passed after waiting, API/Worker restart and an answer resuming the original thread: **2 Requirements / 5 Risks / 8 Cases / 1 Implementation / 1 Execution / 4 Evidence / FINAL RELEASE_READY, JUnit 8 PASS**. The 42 safe activity rows, current-claim isolation and preserved old rows/artifact bytes were independently checked. [The activity acceptance record](MISSION_ACTIVITY_ACCEPTANCE.md) separates automated checks, actual execution and release identity. The initial pre-deployment baseline was merged main `a48bc96` / schema0009, as verified in [the historical PR #6 deployment record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr6-deployment-2026-10-18.md); PR #7 / #8 were subsequently deployed as recorded above.

## Historical WAITING_INPUT implementation and acceptance

This change adds durable human-input requests, Web answers and provider continuation under migration `0009_mission_inputs`. A paused Job is `WAITING_INPUT`: it keeps the Run's active-work reservation while releasing the Worker lease. Saving a nonblank answer and requeueing that **same Job** are atomic; the next claim obtains a new lease and resumes the same Mission, Attempt and AgentSession. Frozen inputs/specification/payload, accepted Canonical state and prior history are retained. Cancelling the waiting Job closes its open questions through the Job controls; direct Mission cancellation must not bypass that ownership.

The Web overview, mission/task details and Questions & answers section expose original questions, suggested options, editable free-text drafts and recorded answers. Same-page drafts survive dismissal and language switching, and read/submission failures retain loaded content. Uncertain same-body retries keep the original idempotency key and concurrency version; saved answers are immutable, and conflicting submissions return 409. Answers are context, cannot change the frozen PRD/source/testing scope, and are not accepted Proposals, trusted Runner evidence or quality decisions. The highest-sequence `FINAL` / `TEST_RUN` selector remains the source of the lead quality verdict.

The frontend passed a fresh independent installation, **31 regression tests**, typecheck, production build and npm audit **0 vulnerabilities**; its one mechanical design scan found no issues. [Check record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/waiting-input-web-checks-2026-10-18.md). **Local and Debian server actual Web answer → same Codex thread resume → official Docker/Evidence/FINAL RELEASE_READY acceptance have passed**, including API/Worker restart while waiting. The frozen backend passed **345 tests / 3 existing warnings**, Ruff and migration checks locally and on the server. [Evidence and limits](WAITING_INPUT_ACCEPTANCE.md) records the same Job/Attempt/session identities, actual `8e01ac5` model execution, verified build reuse, preserved historical rows/artifacts and isolated backup restore. PR #6 was subsequently merged and deployed as `a48bc96`; it did not rerun or rewrite that historical execution. Existing live acceptance below is historical evidence for its own paths. At that historical delivery, the VPN allowlist, SSH fallback, operator credentials and existing data boundaries were unchanged. See [operator flow](WEB_PRODUCT_WORKFLOW.md#等待输入回答并继续--waiting-for-input-answer-and-continue) and [API contract](../README.md#human-input-api).

## Historical PRD import and scope-fix delivery stages

**Stage 1 — import/HTTP/access:** deployed `73dff989b87fa7349d9b36bd8416ece948a82212`, after d20. Native Chrome/macOS acceptance passed **9 real fixtures / 15 UI checks**, with invalid imports preserving draft and filename, valid UTF-8/BOM/CRLF, editing, cancellation/reselection, language switching and Review/back checks. Persistent frontend regressions passed **20/20 (14 decode + 6 UUID)** with fresh install/typecheck/build/audit 0. The 114-input manifest `0d58f4c0990f87d50b49c15b9148c72bdbe3957e5093d5f91a8626e6476d2c07` belongs to this stage, when 86 backend inputs still equaled the prior 302-test source. [Browser matrix](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-browser-matrix-2026-10-17.json).

Its historical VPN HTTP endpoint `155.138.206.106:8080` was active under the recorded deployment, restricted by UFW and nginx to the configured VPN peer; SSH/tunnel remained available then, with API/Web backend/PG loopback-bound. HTTP Project/Run/Job creation and the edited 605-byte PRD hash were verified. This egress-IP boundary is not individual authentication or RBAC; exact protocol/network and subsequent deployment results are maintained in the [latest delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md).

The first real file-based Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5` stopped BLOCKED after **10 Requirements / 6 Risks / 8 Cases**. Testing-method and source-protection instructions had been modeled as application requirements, producing two cases for HyperTest Runner internals absent from the application. The implementation Agent honestly returned PARTIAL with six proposals; `RESULT_NOT_COMPLETED` rejection correctly left **0 Canonical Implementations / Executions / Evidence / Verdicts**. The six rejected Proposal rows and all accepted/failed history remain intact; this was not a passing cycle. [preserved failed-run record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-first-attempt-2026-10-17.json).

**Stage 2 — scope correction:** backend runtime now projects authoritative Snapshot repository/commit into provider-independent `context.testing_scope`, with Requirements/Risks/Design/Implementation guidance distinguishing application behavior and intrinsic product constraints from directions for generating/running tests. Codex follows that context. [Domain §12](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement) and [TMP §9](protocol/TEST_MISSION_PROTOCOL.md#9-mission-context) own this clarification. Genuine product CONSTRAINT requirements and explicitly requested Runner features in the actual SUT remain valid. Raw inputs, frozen Mission specs, accepted Canonical history and Verifier/Gate rules are not rewritten or weakened.

This stage changes backend source and tests, so it must not reuse the Stage 1 “backend unchanged” claim. The new frozen working tree passed **303 backend tests / 3 warnings (48.70s)**, Ruff, test-DB Alembic 0008 and a fresh independent **20-Web-test/typecheck/build/audit-0** verification. Manifest `4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90` identifies the changed source above 73d; it is not the previous 114-input manifest or a Git SHA. Final release SHA/deployment and the same-605-byte fresh-Project real-model/Docker cycle are independently registered in the [latest delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md). A new Run within the old Project would reuse its SourceSnapshot-scoped bad Cases; the fresh Project intentionally isolates new analysis without retiring/deleting history. `RETRYING` means **Awaiting retry**, not an active Worker execution.

## Historical release and acceptance baseline


The development and pre-upgrade deployment baseline is main `79d329299d038ff9e6a3fe1659fb27bf589062c1`: its required backend checks passed with **223 tests / 3 warnings**, and both [CI jobs](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39033073576) succeeded. The four historical real Codex/model/Docker chains ran on `89d15ae` (the local analysis portion began on `5b1b7ce`); those execution identities and results remain unchanged. The 79d server synchronization independently preserved 64 API resource paths and all 12 Evidence/input artifacts.

The final frozen working tree above 79d passed **302 backend tests / 3 warnings (32.87s)**, Ruff and dedicated-test-DB Alembic head `0008_job_ownership`. All 23 Web inputs remain hash-identical to the independent installation that passed typecheck, production build and npm audit 0; the backend-only final URL rejection patch did not rerun Web checks. The [check report](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-checks-2026-10-17.md) records the exact 86 backend and 23 Web inputs, commands and manifest `6ea1934a8a4a577d6990e38eda11a49c1727b9505b333d416d961b207f68e85f`.

The prior live Web Run `01a149ff-2749-7ecc-b5f4-5a02307cb7b0` completed automatic GitHub source preparation, real Codex/model proposals, trusted Docker execution, evidence and FINAL **RELEASE_READY**: 7 Requirements, 6 Risks, 9 Cases, 9 Implementations, 1 Execution, 4 verified Evidence; JUnit **34 tests / 0 failures / 0 errors / 0 skipped**. The first Risk call was cancelled through Web after a long interval without new events; a linked explicit retry preserved all history and reused the accepted Requirements. Task → Verdict → JUnit navigation and original Attempt summaries were verified in the actual bilingual Web.

That live cycle used the 298-test frozen source manifest `0a34e3356d1b2f37b2731b160730747b5dcfa49e9e549c59ad94c8c7e29f1273`. A subsequent rejection-path-only URL parser hardening and four API regressions passed the final 302-test suite; valid GitHub behavior was unchanged. The running model process identity is not rewritten as a later commit. That release did not rerun the already accepted failure-diagnosis chains. See [first-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) for the itemized current-versus-historical matrix and [delivery record](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/phase-one-web-delivery-2026-10-17.md) for the final commit and actual deployment/readiness identity.

## Implemented workflow

The canonical stages below remain valid. Descriptions of the step-by-step controller (per-Job planning-step limits, stopping on a rejected Proposal, and manual stage actions) describe the legacy compatibility profile. The current ADR-013 persistent profile uses a frozen cumulative Run budget, typed domain-tool admission and binding ownership; the same native session can correct rejected proposals, and bound Runs reject conflicting manual stage mutations. See the current increment above and ADR-013 for that active Web flow.

The primary **Run test cycle** action submits durable work to PostgreSQL. The persistent profile retains one native session across typed stages under frozen Run budgets. The bounded controller description below is the historical unbound compatibility path, not the current persistent-session dispatch model. A cycle request selects exactly one source mode: automatic pinned GitHub HTTPS checkout (`prepare_workspace: true`), or an existing matching workspace path. Automatic preparation runs inside that same `ADVANCE_RUN` Job before any Mission; the standalone `PREPARE_WORKSPACE` action remains available. Operators choose a Runner once; HyperTest follows deterministic Planner decisions, verifies Agent proposals, executes official tests, and evaluates the Gate. Individual stage actions remain available only for the unbound legacy path; bound Runs use their persistent task controls.

| Stage | Operator action in Web | Canonical result |
|---|---|---|
| Project | Create a project | Project |
| Inputs | Create a run with repository URL, full commit SHA, PRD text, configuration text, and policy | Immutable SourceSnapshot and PolicySnapshot; TestRun |
| Requirements | Submit the complete cycle, then inspect accepted ANALYZE_REQUIREMENTS output | Canonical Requirement and accepted proposal provenance |
| Risk identification | Inspect ANALYZE_RISKS output from the same bound session | Risk and relational RequirementRisk links |
| Test design | Inspect DESIGN_TESTS proposals as typed admission closes dimensional gaps | TestCase and relational RiskTestCase links |
| Automation | Review accepted IMPLEMENT_TESTS output and generated source | TestImplementation, immutable generated test artifacts, ImplementationTestCase links |
| Official execution | The bound session requests official execution; inspect trusted Runner results | TestExecution, per-case results, checksum-verified Evidence and ExecutionEvidence links |
| Diagnosis | Inspect DIAGNOSE_FAILURE after official facts show failures | Evidence-backed Finding proposals |
| Finding management | Inspect evidence, record a permitted disposition and reason, review history | Controlled lifecycle transition, reason, version, AuditEvent and OutboxEvent |
| Quality decision | Harness requests Gate during the cycle; this branch adds reasoned independent Gate Jobs after reported CLOSED completion | Latest matching Verdict reuse or append-only new sequence, state hash, evidence manifest hash, evidence/finding links |

The Web workbench exposes Requirements, Risks, Test Cases, Missions, Automation, Executions, Evidence, Findings, Verdicts, Tasks, and Questions & answers. Its background task monitor polls durable work every 1.5 seconds, questions every 2 seconds; canonical state refreshes every 5 seconds. Operators can inspect task timelines, errors, cancellations and linked retries alongside Mission attempts, proposals, validation failures, runner results, artifact contents, saved PRD/configuration inputs with checksum verification, finding evidence, and decision rationale. Refreshing the page does not submit duplicate work. Active cancellation interrupts controlled external work; explicit replanning creates a new Mission generation while retaining cancelled history. The product does not require a chat conversation.

The legacy controller is user-triggered and bounded: Web used 12 planning steps per Job, with a supported limit of 1–32. Job submission returns 202; refreshing or closing the browser does not end the work. Completed steps are persisted by their owning services. A rejected Proposal, active external work, runtime error, or step limit stops the work visibly; another request resumes from canonical state. A recorded `WAITING_INPUT` pause instead requires its answer and continues the same Job, as described above. The controller follows Planner reasons such as `EXECUTION_REQUIRED`, `EXECUTION_IN_PROGRESS`, and `VERDICT_REQUIRED`; it does not become an LLM reasoning loop.

Before Git or Agent work, the cycle performs a read-only Runner fingerprint check against the actual Docker daemon/trusted image or the explicit local-development opt-in. It releases Run/Job locks before this I/O and revalidates its lease/admission afterward. Failure starts no Git/Agent/Mission, creates no Execution/Evidence and performs no image pull or install. Readiness is operational and may change before official execution; a separate Gate-only action does not depend on it.

Automatic preparation releases database Run/Job row locks before Git I/O, then rechecks ownership and the live lease before further dispatch. Preparation failure starts no Agent; preparation is a prelude rather than a planning step. The cycle result includes the resolved workspace for subsequent operator actions. A controlled `MISSION_REJECTED` or `MISSION_FAILED` stop leaves its Job `FAILED` while preserving the stop reason, already-persisted steps and available related identities in `result`. A failed Mission is not reported as merely in progress and is not silently replayed. Generic runtime failures need not have a partial result. Historical Job payloads missing the additive `prepare_workspace: false` default compare equivalently in memory; their stored immutable payloads are never rewritten.

PostgreSQL `durable_jobs` stores request identity, inputs, state/result, cancellation, and retry lineage. Only one active request is allowed per Run. Independent Workers claim jobs using SKIP LOCKED, renew leases, and fence canonical commits with their live token. Worker shutdown or expired leases produce explicit interruptions; unfinished Mission Attempts and Executions retain failure history. No automatic replay occurs after a lease expires because external work may already have run. Explicit retry creates a new Job. Job success is distinct from a passing quality Verdict. Worker liveness is exposed through capabilities; queued work with no available Worker is visible. Time-based project scanning and unattended release automation remain outside this iteration.

Mission Attempts and Executions carry immutable nullable `durable_job_id` relationships, guarded for matching Run and allowed operation; existing synchronous history remains unowned. Recovery uses those links rather than timestamp inference across machine clocks. The compatibility direct controller checks ownership before and after each Planner step, so a queued request admitted between commits stops further direct work; the entire legacy loop is not exclusively reserved.

Run creation uses Source → Requirements → Policy → Review. Operators select shared and category-specific design dimensions and gate-blocking Finding severities; the immutable resulting Policy is visible in the Run inputs and coverage rule/hash.

The interface supports Chinese and English with a persisted browser preference,
localized component controls, dates, state labels and validation messages. Project
and run drafts survive closing/reopening the dialog and switching language within
the page. UTF-8 Markdown/text PRDs can be imported into the editable requirements
field. Task completion is explicitly separated from quality decisions; task steps
and Verdict relations link directly to recorded execution, evidence and findings.
Temporary polling errors preserve loaded data and the selected result tab.
Uncertain task submissions recover the saved Job by request identity before any
explicit retry. Bootstrap rejects reuse of a request key for different substantive
inputs before writing artifacts; branch reference labels follow the existing
SourceSnapshot identity rules. See the [Web workflow guide](WEB_PRODUCT_WORKFLOW.md).

The prior successful cycle used pasted Chinese PRD text; its extension permission limitation is historical. The repaired local native-Chrome import matrix now passes 9 fixtures/15 checks. Production file/hash/HTTP identity and live-model outcomes are separately maintained in the latest delivery record, rather than inferred from the local matrix.

## Current trust and coverage boundaries

- Agent output is a Proposal. HyperTest alone validates and commits Canonical State.
- Repository origins cannot embed passwords, or HTTP(S) usernames/tokens. Authentication belongs to host Git configuration; SSH usernames and existing credential-free local/scp-style origins retain their identity. Creation rejects unsafe inputs before snapshot/Run/artifact writes. Runtime also rejects historical credential-bearing snapshots before creating an Agent Session or Attempt, without rewriting them. HTTP 422 details expose only `type`, `loc` and `msg`, omitting submitted `input`, validator `ctx` and raw request values. This guard does not scan paths/query strings for arbitrary secrets or establish comprehensive log redaction.
- Materialized Web input sets require readable, hash-matching PRD and configuration artifacts before an Agent Session starts. A missing configuration artifact is an error even when its intended content is empty. Legacy direct hash-only snapshots with no PRD artifact URI retain their optional configuration context; any materialized configuration is still checked. Compatibility does not alter immutable hashes or reconstruct missing truth.
- Runner-generated metadata, stdout, stderr, and JUnit are collected independently of Agent assertions. Artifact contents are addressed by SHA-256 and verified when read and when the gate consumes them.
- PostgreSQL stores canonical entities, relational traceability, audit events, and transactional outbox rows. Outbox publishing infrastructure is a later operational extension.
- SourceSnapshot and PolicySnapshot UPDATE/DELETE guards preserve immutable inputs. Once a Mission leaves CREATED, its identity, spec, objective, protocol, priority, and request identity remain frozen; retry cannot return it to draft or erase history. Mission creation, acceptance, interruption, rejection, timeout, and cancellation use transactional lifecycle Audit/Outbox records.
- Test design coverage defaults to `FUNCTIONAL` plus the applicable risk-specific dimension. Immutable PolicySnapshot rules can configure global and category-specific dimensions through `coverage.default_dimensions` and `coverage.by_category`; FUNCTIONAL remains mandatory. The compiler rejects unsupported rules before storing Policy state. Planner, Verifier, Gate, and Web share the resolved rule version and hash. Dimensional coverage remains deterministic, not a claim of semantic completeness.
- The gate requires complete identification/design coverage and successful latest OFFICIAL results for every active TestCase, matching source commit, verified trusted execution metadata and JUnit, and no policy-blocking confirmed product defect. Missing or inconclusive facts produce `BLOCKED`; observed failures or blocking defects produce `RELEASE_BLOCKED`; complete passing facts produce `RELEASE_READY`.
- Gate reads, canonical proposal commits, and Runner updates to shared implementations use a SourceSnapshot lock after the Run lock, preserving consistent decisions across Runs sharing the same source. The lock does not span actual test/provider execution. Verdict hashing binds the rule version and computed decision alongside canonical inputs and artifact integrity. Reuse requires the latest matching Verdict for the Run/scope/status, with the same policy, decision and evidence manifest; returning to an older semantic state appends a new sequence rather than rewinding history.
- The gate's baseline does not waive official execution or trusted evidence. The currently configurable gate policy is `gate.blocking_finding_severities`; `BLOCKER` always blocks.
- Finding deduplication currently scopes the affected component to the TestRun and referenced cases. Historical cross-run recurrence analysis remains a separate extension.
- Generated tests are separate assets from the immutable application commit. Runner overlays are limited to safe Python paths under `tests/`; they cannot replace tracked application files.

## Operating mode

This MVP is for one trusted operator in a controlled development or test environment. It does not include application login, tenant isolation, project RBAC, or hardened public deployment. Keep its API and Web access within that operating boundary. A Docker daemon and authenticated Agent CLI are privileged host integrations managed by the operator.

The trusted Docker Runner uses a prebuilt Python/pytest image, records its resolved image identity, and executes with networking disabled, a read-only root filesystem, dropped capabilities, a non-root user, and resource limits. Build the image before execution. Project-specific dependencies must be preinstalled in an appropriate trusted image; execution does not install them.

The local Runner is an explicit development fallback enabled with `HYPERTEST_RUNNER_ALLOW_LOCAL=true`. It executes trusted code as a host process and provides no container isolation. Its provenance still comes from the Runner collector; enabling it is not a claim that host processes are sandboxed.

In the legacy host profile, Agent execution requires a Codex CLI available and authenticated on the Worker host, plus a checkout accessible under `HYPERTEST_WORKSPACE_ROOT` matching the pinned repository and commit. API and Worker share the same database, Artifact Store, Workspace Root, and integration configuration. Web can prepare/reuse managed checkouts for credential-free GitHub HTTPS URLs through the existing Git proxy/authentication; other hosts use a supplied checkout path. It does not reset operator checkouts. Source preparation and official execution reject mismatched or modified tracked files. Legacy agents work in temporary per-Mission copies; the persistent profile instead retains the Run-bound host session/workspace until controlled termination. Agent Sessions and provider telemetry are operational data, never canonical domain state. Lease fencing prevents stale canonical commits; external execution is not exactly-once.

The legacy Codex adapter passes its UTF-8 Mission prompt through the official CLI stdin interface (`codex exec -`), while keeping the strict output schema, CLI-written final-result file, read-only sandbox and noninteractive approval policy. Concurrent pipe draining avoids blocking telemetry behind prompt transport. The multi-megabyte subprocess regression establishes transport without argv size failure; it does not establish provider context-window capacity. The current supported harness is Codex. Its `WAITING_INPUT` question/answer/resume path passed independent local and server real-model acceptance as recorded above; the current persistent profile separately implements nine controlled domain tools. Additional Harness adapters and cross-Provider acceptance remain separate work.

Docker staging/execution containers and precreated source/result volumes carry the owning Job UUID. Expired-job recovery commits interrupted state first, then performs best-effort cleanup outside database locks, removing only matching managed resources and recording paired `job.resources_cleanup` Audit/Outbox events with availability and removal counts. An unreachable Docker daemon or orphan provider process still requires operator inspection before retry.

See [README](../README.md) for setup commands and [the domain specification](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md) for canonical constraints.

## Verification

Required repository checks are:

```bash
ruff check src tests alembic
alembic upgrade head
pytest -q
cd web
npm ci
npm test
npm run typecheck
npm run build
```

PostgreSQL integration tests exercise the canonical Planner chain, configurable dimensional coverage, Mission lifecycle events, durable queue behavior, and the delivery layers. Dedicated regressions verify immutable input snapshots and Mission contracts alongside immutable execution input, immutable Evidence content, append-only FINAL Verdicts with controlled revocation, and active Finding fingerprint uniqueness while preserving resolved history. The current migration head is `0020_interactive_tool_inbox`; ADR-016 adds0019–0020, ADR-015 adds0015–0018, and ADR-014 adds no migration. The earlier `0010_mission_activity` and `0009_mission_inputs` check counts retain their original migration identity.

The bounded controller is tested against real PostgreSQL and real pytest execution, including continuation after a step limit. Queue checks cover idempotency, concurrent claims, durable cancellation, interruption/retry, and rejection of stale lease commits. `scripts/dev.sh --check` verifies migrations and API/Worker imports; normal invocation starts the installed host API, independent Worker, and Node.js 22 Web, with configurable development ports and cleanup of its own processes.

Historical local live acceptance is complete for the supported stdlib/pytest backend workflow. Real Codex proposals produced the canonical analysis/design/implementation chain, and the trusted Docker Runner produced official evidence. The passing source yielded FINAL `RELEASE_READY`; the defective source yielded actual failures, a real diagnosis Finding, and FINAL `RELEASE_BLOCKED`. The operator then used Web to triage/confirm the Finding and reevaluate the Gate, appending a second blocked Verdict while retaining the first. Initial PARTIAL/REJECTED implementation attempts and FAILED Jobs remain visible; explicit retries created new linked work and accepted real model output.

The Debian 13 server independently passed both historical live-model/Docker acceptance paths after the operator completed OAuth under the service account. All nine server Missions completed on their first Attempt. Its successful source produced 14 passing pytest instances across 11 canonical Cases and FINAL `RELEASE_READY`; its defective source produced actual failures, a new evidence-backed product Finding, and FINAL `RELEASE_BLOCKED`. The single Worker consumed the two Runs serially, and the production Web was operated through the loopback SSH tunnel. Server versions, SQL provenance, paired backup/recovery, and exact identities are recorded in [first-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) and [server operations](SERVER_OPERATIONS.md).

The historical live-integration implementation `89d15ae` passed **212 backend tests** with three warnings, Web install/typecheck/build, npm audit with zero reported vulnerabilities, and both backend/Web CI jobs. [First-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) records exact identities, hashes, SQL traceability, Web evidence, supported scope, and separately maintained server results. The [old cloud diagnosis](CODEX_RUNTIME_TROUBLESHOOTING.md) remains historical EROFS/CONNECT 403 evidence; it did not establish invalid credentials. Canonical controller fixture tests and local live acceptance remain different evidence, and neither substitutes for another host's actual integration checks.

Real provider credentials, a running Docker daemon, and repository-specific application dependencies are external operating prerequisites. Passing local tests alone does not establish that those integrations are available on another deployment; the Web capabilities panel reports installed Agent and Runner choices.

## Secondary roadmap

These are extensions to the current operable workflow, not hidden prerequisites for completing a supported run:

- Additional Agent harnesses and capability negotiation.
- More test languages, frameworks, Runner backends, and trusted environment images.
- Semantic coverage evaluation beyond the configurable deterministic test dimensions.
- Automated repair/retest selection, change impact, and cross-run knowledge reuse.
- Time-based project scheduling and automatic outbox delivery beyond the user-triggered durable queue.
- Object storage and signed evidence manifests beyond the local content-addressed store.
- Authentication, authorization, multi-user/tenant isolation, and hardened production deployment.
- Direct Requirement-to-TestCase links when needed beyond the existing relational Risk path.
- Cleanup of legacy Alembic/ORM enum-length and index metadata differences unrelated to delivery; new delivery table definitions match their ORM metadata.

## Local 交付状态

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。


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
