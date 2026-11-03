/** User-editable testing instructions; this template does not submit or start work. */
export function cloudTestPrompt(mrUrl: string, locale: "en" | "zh"): string {
  const mr = mrUrl.trim() || (locale === "en" ? "${MR_URL}" : "${MR地址}");
  if (locale === "en") return `# New requirement: E2E testing

## 1. Context and test draft
- MR / PR: ${mr}
- Test environment: \${TEST_ENVIRONMENT}

Use glab to read the MR description, changes and relevant discussions. For a GitHub PR, use the available provider tools. Understand the intended behavior and testing direction.

Testing draft and basic flow:
\${TEST_DRAFT_AND_BASIC_FLOW}

Discover the environment entry points, execution method, test accounts and applicable operating limits from existing project documentation, the test framework and configuration. Ask only for missing information that cannot be confirmed and affects expected results, scope or safe execution. Do not invent requirements or copy credentials into the report.

## 2. Test analysis and completion criteria
Build a concise mapping from each relevant MR change to the minimum necessary E2E scenarios, assertions and evidence. Assign case IDs. Follow the entry point and scope in the draft; cover the changed behavior without adding unrelated business areas or defaulting to full or all-combination regression. Record out-of-scope risks as separate recommendations.

For each flow, define its key steps, observable business outcome, and how requests, business records and external results will be linked to the final assertions. Request acceptance or an intermediate success does not establish completion. If a scenario does not trigger the changed behavior, mark that verification point as uncovered even if the workflow succeeds. State how asynchronous completion will be checked and the project's applicable waiting limit.

## 3. Subagent review before execution
After analysis, ask an independent subagent to read the MR, test draft and case plan, and review:
- Whether cases follow the requirement's E2E flow and verify both the final outcome and the changed behavior.
- Whether key steps, assertions or evidence are missing, or unrelated scope has been added.

Link findings to case IDs or specific coverage gaps. Address each finding by recording the correction or the reason for not adopting it; carry unresolved gaps into the final report. Both subagent reviews are read-only: reviewers must not independently run state-changing tests.

## 4. Execution and subagent audit
Use the project's existing test framework and tools in the specified environment. Maintain a case ledger linking actual results to original execution records and evidence. Record reasons for case changes or removals; do not silently drop planned cases. Source analysis or simulated results alone do not demonstrate E2E execution.

If a state-changing request times out, loses its response or has an UNKNOWN outcome, query using the original request identifier, business record or external operation ID. Do not switch keys or repeat an equivalent request. If the outcome remains uncertain, retain its original identifiers and report the unresolved state.

After testing, ask an independent subagent to audit the full case ledger and original evidence, rather than relying only on the main Agent's summary. Verify the E2E outcomes, assertions and coverage; identify skipped, blocked, unexecuted or unverified cases. Link findings to cases and record a response to each. Report unavailable subagents or incomplete reviews explicitly.

Distinguish skipped, blocked and not-run cases, with the reason, impact on coverage and conditions needed to continue. Never count them as passed.

## 5. Complete test report
Include:
1. One-sentence summary: E2E coverage, overall result and key blockers.
2. Scope and environment: MR changes, environment used, observed SUT version and testing boundaries.
3. Case ledger: case ID, related change, scenario, steps, expected and actual results, status and evidence references.
4. Execution records: actual times, commands or framework runs, outputs and applicable reruns, linked to cases.
5. Evidence: relevant system logs and external system records; for on-chain flows, applicable transaction hashes, block or event data and observed state. Distinguish missing evidence.
6. Review findings and open issues: both subagent reviews and responses, defects, remaining coverage gaps, and reasons, impact and continuation conditions for unfinished cases.

Base the conclusion on actual execution and evidence. Keep task completion, test pass/fail and unverified scope distinct.`;
  return `# 新需求 E2E 测试

## 1. 测试背景与草稿
- MR / PR 地址：${mr}
- 测试环境：\${测试环境}

请通过 glab 读取 MR 描述、代码改动及相关讨论；GitHub PR 使用已有的对应工具。理解本次需求的预期行为、测试内容和方向。

以下是测试草稿和基本流程，供理解测试重点：
\${测试草稿与基本流程}

优先从项目现有文档、测试框架和配置中确认环境入口、执行方式、测试账户及适用的操作限制。仅对无法自行确认、且影响预期结果、测试范围或安全执行的关键信息提问；不补造需求，不将凭据写入报告。

## 2. 测试分析与完成判据
建立简明的“MR 变更点 → 最小必要 E2E 场景 → 明确断言 → 所需证据”对应关系，并为用例分配 ID。以草稿指定的入口和范围为准，覆盖改动涉及的行为，不扩展到无关业务，也不默认开展全量或全组合回归；范围外风险单独列为建议。

为每条链路明确关键步骤、可观察的业务终态，以及请求、业务记录、外部结果与最终断言的关联方式。请求已受理或中间步骤成功不能作为完成判据。场景未触发本次改动时，即使业务流程成功，也应标记对应验证点未覆盖。异步流程应说明完成状态的查询方式及项目适用的等待上限。

## 3. 执行前：subagent 测试重点审查
完成分析后，启用独立 subagent，只读 MR、测试草稿和用例计划，审查：
- 用例是否沿本次需求的 E2E 链路验证最终业务结果及改动行为？
- 是否遗漏关键步骤、断言或证据，或加入无关测试范围？

审查意见须关联用例 ID 或具体覆盖缺口。主 Agent 逐项回应，记录修正或不采纳理由；未解决缺口进入最终报告。两次 subagent 均只读审查材料，不独立执行会改变系统状态的测试。

## 4. 测试执行与完成后审计
在指定环境中使用项目已有的测试框架与工具执行测试。维护用例台账，将实际结果关联到原始执行记录和证据；调整或移除用例须保留原因，不静默遗漏原计划用例。源码分析或模拟结果不能代替 E2E 实际执行。

改变系统状态的请求出现超时、失答或 UNKNOWN 时，先使用原请求标识、业务记录或外部操作 ID 查询核对，不更换 key 或重复提交同义请求。结果仍无法确定时，保留原标识并报告未决状态。

测试完成后，启用独立 subagent，基于完整用例台账和原始证据审计，不能只依据主 Agent 的总结。核对 E2E 终态、断言和覆盖情况，找出跳过、阻塞、未执行或未验证的用例；发现须关联具体用例，由主 Agent 逐项回应。若 subagent 不可用或审查无法完成，须如实报告。

分别记录跳过、阻塞和未执行的用例，说明具体原因、覆盖影响及继续执行所需的条件，不得计为通过。

## 5. 完整测试报告
请输出包含以下内容的报告：
1. 一句话总结：E2E 覆盖情况、总体结果及关键阻塞。
2. 测试范围与环境：MR 改动、使用的环境、实际观察到的被测版本和本轮边界。
3. 用例台账：用例 ID、关联变更点、场景、步骤、预期结果、实际结果、状态及证据引用。
4. 执行记录：实际执行时间、命令或框架运行记录、输出及适用的复测结果，关联到具体用例。
5. 证据：相关系统日志、外部系统记录；涉及链上流程时，提供适用的交易哈希、区块或事件数据及实际状态，明确说明缺失证据。
6. 审查结论与遗留问题：两次 subagent 审查意见及回应、缺陷、剩余覆盖缺口，以及未完成用例的原因、影响和继续执行条件。

结论须基于实际执行与证据，明确区分任务完成、测试通过和未验证范围。`;
}
