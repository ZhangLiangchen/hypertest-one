# ADR-014：会话关闭后的 Finding 处置与独立 Gate 重评

**Status:** Accepted；实现与真实验收另行记录，不由本文推定通过。

**Date:** 2026-10-19

**Decision basis:** 项目负责人明确要求完成已关闭会话后的 Finding 处置和独立 Gate 重评 Web 闭环。

## Context

ADR-013 将一个完整测试周期绑定到一个持续主 Harness 会话。报告被接受后，Binding 和主 AgentSession 进入 CLOSED，不能重新打开。原准入同时拒绝了独立 EVALUATE_GATE，使操作者能够处置 Finding，却无法在原 Run 中形成基于新状态的正式质量结论。

Finding 是 Canonical State，Verdict 属于 HyperTest。重新计算固定 Policy 下的质量判断不需要 Agent Intelligence 或新的 Runner Facts，因此不能以重开会话、重新运行模型或清除原结果解决这一治理缺口。

## Decision

1. Finding 继续采用领域模型 §18 的状态机、必填处置理由和配对 Audit/Outbox。Web 人工处置必须提交预期 row_version；旧 API 的可选版本字段保持兼容。会话关闭不取消人工处置权限，处置成功不自动执行 Gate。
2. 在已有 RunExecutionBinding 的 Run 中，仅当 Binding 与其原主 AgentSession 都为 CLOSED、且同一 Run/Binding 已有被接受的 RunReport，才允许独立 `EVALUATE_GATE` DurableJob。该操作只允许 `finalize: true`，必须提供去除首尾空白后非空、不含 NUL、最长 2000 字符的 `reason`。理由属于 Operational 请求和审计，不进入 Gate 事实 hash，也不替代 Gate 根据事实计算的 reason。
3. RESERVED、ACTIVE、WAITING_INPUT、RECOVERY_REQUIRED、FAILED、CANCELLED 或无报告的 CLOSED 均不能借此取得新的执行权限。没有绑定的历史 Run 保留其原有 Gate 语义；新可选 reason 字段不原地重写旧 Job payload。
4. 提交、领取、执行和每次提交事务均检查 Run 排他、原 Binding ID/epoch、CLOSED 主 Session、Job 类型、当前 token 和数据库时钟内有效租约。锁顺序沿用 Run → Binding → Job → SourceSnapshot；活跃 Job/Mission/Execution 不允许并行治理提交。
5. 独立 Gate 不调用 Harness、Bridge、模型、Runner、Git 或环境能力预检，不新建 Session/Mission/Attempt/Execution/Evidence，不修改旧 Binding、checkpoint、预算、原生工作区或报告。取消、失败、租约回收也不得触发这些外部资源的清理。Job 的取消与显式关联重试仍有原租约和幂等保护。
6. Gate 的质量算法保持 `canonical-gate/v1`。关闭、解决或接受 Finding 风险不能豁免失败/缺失的正式执行和可信证据。修复需要新的固定 SHA/测试轮次，不能将新 Run 的通过写回旧 Run 的执行事实。
7. 仅可复用该 Run/Scope 最新的、Policy/State Hash/decision/Evidence manifest 均相同的相应状态 Verdict。状态改变则追加新 sequence；即使语义返回曾出现的旧状态，也不能倒指较早的 FINAL。连续相同状态的重评复用最新结论，但每个请求的理由、任务和结果仍可审计。
8. 原 FINAL、Verdict links、报告 envelope 与内容均保留。报告读接口可以从原 envelope 投影 nullable `verdict_key` / `verdict_decision`，不补写旧记录；无法验证的引用返回未知。Web 显示原报告所引用的结论，并在其与最新正式结论不同时说明历史差异。

## Options considered

| 方案 | 取舍 |
|---|---|
| CLOSED 后独立平台 Gate Job | 采用。复用确定性 Gate 与持久队列，不消耗模型或执行额度；需要单独 CLOSED-only fence。 |
| 重开原 Harness Session | 拒绝。违反 ADR-013 终态与身份规则，且治理计算不需要模型。 |
| 处置 Finding 时自动重评或隐式启动新 Run | 拒绝。混淆人工处置、执行事实与质量决定，隐藏任务成本和历史。 |
| 用同步 Gate 端点绕过 Binding | 拒绝。失去队列、租约和同 Run 排他治理。 |

## Consequences

完成报告后，操作者仍可在原 Run 内处置 Finding、提交明确理由、查看重评任务及最新结论。旧报告保持其生成时的含义；不会自动再调用模型生成新报告。

Web 的独立重评与原测试周期恢复必须明确区分。重评失败只重试该 Gate Job，不能用该入口恢复或替换终态 Harness。该变更不增加表、不改数据库 schema 或 TMP Agent wire/profile 版本。

## Specification ownership and acceptance

领域模型 §19/§23.8 拥有生命周期、历史、排他与持久化约束；TMP §38.1 区分平台操作者请求和 Agent 工具授权；技术架构拥有治理 Worker 与外部运行时边界。白皮书定义产品意图。

验收必须覆盖真实模型和 Docker 产生的完整周期，随后在 CLOSED 状态通过真实 Web 处置 Finding、重评、读取新旧结论与原报告；同时核对无新增模型/执行调用、旧事实未改、重复重评幂等以及拒绝矩阵。合成回归用于并发、租约和错误边界，不能代替真实周期。
