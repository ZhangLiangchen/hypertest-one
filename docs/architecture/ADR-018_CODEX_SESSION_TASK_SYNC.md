# ADR-018：Codex 会话测试任务与产物同步

**适用范围：旧 Local SessionTask 合同与历史。** 新 Local 接入已改为 [ADR-027](ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 的显式 Skill/CLI 归档；新归档不要求会话绑定或持续同步。本文及 ADR-024/026 继续解释旧身份、授权、回执与历史，不用于指导新归档接入。实现和部署见[归档交付](../LOCAL_ARCHIVE_DELIVERY_20261027.md)，用户功能验收另行记录。

**2026-10-26 增补：[ADR-026](ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)在显式启用的协作 profile 中允许一个 SessionTask 接纳多个获授权真实 root 的贡献，由当前 PRIMARY 汇总。下文一对一规则继续用于未启用任务与初始绑定；原 UUID/source/owner/历史不改写，旧 full sync 不变成多写者接口。字段及操作由领域 §50.6 / TMP §45.5 拥有。**

**状态：Accepted（2026-10-21，Asia/Singapore）；实现与验收单独记录。**

**2026-10-23增补：[ADR-024](ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md)接受Operator预创建UNBOUND SessionTask、同UUID显式绑定和新Local会话首次产物前TaskID门槛。绑定后仍是一真实父会话一任务；未绑定记录没有session/owner/Agent来源，旧自动任务的ID与历史保留。该增补按领域§50.5/TMP§45.4替代下面仅由首次sync创建的适用范围，不把绑定当同步或执行。**

## 决定

现阶段 HyperTest One 是 Codex 的测试任务、测试用例与测试报告管理平台。
**一个 Codex 会话对应一个测试任务；Codex 完成测试工作，将任务、计划、用例、报告等产物同步到平台。HyperTest 不承担测试执行。**

这一决定依据项目负责人的明确纠偏，优先于将新管理入口设计成执行材料准入、原生 Runner、可信 CI 核验或 UNKNOWN/BLOCKED Gate 的做法。ADR-017 的实现、原始材料与结论作为独立历史保留，不作为当前管理同步的前提。

## 职责与身份

- HyperTest 保存 Project、SessionTask、用例版本、报告版本、同步回执与审计，提供查询和关联。
- Codex 会话负责分析、设计、实现、调用 SUT 已有框架/CI、诊断和编写报告。平台的同步请求没有执行命令语义，不启动 Job、Harness、Runner、Gate 或 Provider。
- SessionTask 使用既有 Project；`(provider, session_id)` 唯一，首次归属的 Project 不随更新改变。会话引用用于来源与追溯，不是宿主执行身份或认证证明。
- 新会话建立自己的任务；当前使用新任务 `plan_markdown` 记录原Task URL/ID、原source session、原报告引用与剩余工作，Report的`source_ref`可指向旧任务原报告。没有结构化关联列，不宣称平台已执行关联校验。不把新会话改名成旧会话，也不把转引旧报告写成本次执行。当前不增加跨会话执行控制或并发写入协议。
- 旧 TestRun、Mission、Execution、Evidence、Verdict 与两种受管 Harness 保留其既有语义及历史；不回填、删除或重解释。

## 最小管理模型

1. **SessionTask**：Project、Provider、Session ID、标题、目标、任务状态、计划 Markdown、`reported_result`、版本号、来源与更新时间。任务状态表示工作进度，reported result 表示提交者报告的测试结果，两者分开。
2. **CaseRevision**：任务内稳定 case key、递增 revision、标题、步骤、预期结果、reported result 及其他提交内容。修改追加版本，省略某个用例不删除历史。
3. **ReportRevision**：任务内稳定 report key、递增 revision、原始 Markdown、报告来源、reported result 与关联引用。原始报告保留，摘要不能替代原件。
4. **SyncReceipt**：稳定幂等 key、原请求摘要、expected version、提交 actor、接受版本和结果引用。同 actor/Project/key 同请求返回原回执；同 key 不同内容冲突。client 在当前 grant 授权链核验，不是回执唯一身份。`expected_version` 防止旧客户端覆盖新状态，任务、用例、报告、回执和审计原子提交。原始 Markdown 直接保存在 PostgreSQL ReportRevision；附件引用只存来源元数据，不自动上传或抓取文件。

版本号、业务 key 与内容摘要用于去重、完整性和历史关联；不把 hash 或摘要解释为执行证明。

## 人工管理补充（2026-10-23）

Web / Operator 可编辑项目资料并设置 ACTIVE / ARCHIVED，也可编辑SessionTask的标题、目标、计划和五种进度状态，包含显式重开。项目key、任务Project/provider/session/owner保持固定。人工操作不能修改reported result、用例或报告，不启动、恢复、取消或重跑测试，不改变旧受管生命周期。

项目与任务删除采用可恢复的 `deleted_at` 标记，不 hard delete、不级联清理、不释放唯一键。存在未删除会话任务或任何legacy/native测试轮次时拒绝删除项目。所有人工写入受expected version保护；任务写入追加独立TaskManagementRevision冻结快照并与Audit/Outbox原子提交，既有SyncReceipt不变。固定版本读取覆盖两类快照，保留Agent与人工贡献的区别。

默认读取隐藏已删除对象，回收站显式列出并允许恢复。新同步拒绝已删除项目或任务；原同步key查询在当前有效授权下仍可对账，不因删除自动签发凭据或复活任务。字段和生命周期由领域§8.1/§50.4拥有，HTTP与权限契约由TMP§45.3拥有。此补充仍是管理功能，开发验收与部署分别记录。

## 结果与治理语义

管理平台接受并显示 Codex 提交的 PASS、FAIL、BLOCKED 等 reported result，并明确来源。
报告 FAIL 不因之后 PASS 而消失；缺少独立 CI 证明不把已提交 PASS 强制改写为 UNKNOWN。
这些记录不自动获得 legacy VERIFIED Evidence、FINAL Verdict 或 RELEASE_READY 语义。

Proposal/Verifier 的原则保留在管理接受边界：提交内容先校验权限、结构、版本、业务 key 与引用一致性，再由平台提交持久状态。Gate 仍解释原路径的质量判定，当前同步不调用 Gate，也不要求先有质量判定才能保存用例或报告。已观察事实、Agent 推断、待验证材料可在原报告与来源中分别记录。

**同步 UNKNOWN 与测试结果不同。** 写请求失答后保留原 journal/key，只 GET 查询原回执；NOT_FOUND 不证明旧 POST 未执行，不自动重发 POST、换 key 或新建替代任务。客户端 journal 只持久保存查询身份与完整请求 digest，不反复复制计划/报告原文。读取恢复成功后可再次显示原已报告结果，不重跑测试。

## 接入与权限

复用现有 MCP → 私有客户端 → typed HTTPS API 通道，增加 `hypertest_sync_task` 与 `hypertest_get_task`。同步和查询不需要 execution binding、host proof、设备执行授权、源码传输或受控工作区。

权限沿用 integration actor/client/project 授权，新增 `task:sync` scope；不向 Agent 提供 Operator key。token 只保存在客户端私有文件，工具参数只含任务数据。会话 ID 不替代 token 或项目授权。旧集成 scope、工具和 managed 语义不静默改变。

## 验收与边界

至少验证任务/用例/原始报告实际写入与读回、同会话唯一性、任务隔离、历史修订、幂等冲突、旧版本拒绝、失答只查询、撤权/项目越权拒绝，以及同步没有产生 Job/Binding/Execution/Gate。

开发、源码安装、本机验收与生产部署分别记录；本决定不授权生产部署、生产 schema 迁移、既有凭据复制、源码外发、VPN/白名单变更或 SUT 测试重跑。原生测试历史继续保留，但不是本轮同步功能验收的替代品。

接口字段、生命周期和约束由[领域规范](../domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)拥有，MCP/API 协作由[TMP](../protocol/TEST_MISSION_PROTOCOL.md)拥有，服务边界由[技术架构](HYPERTEST_TECHNICAL_ARCHITECTURE.md)拥有；使用说明见[会话任务同步](../CODEX_SESSION_TASK_SYNC.md)。
