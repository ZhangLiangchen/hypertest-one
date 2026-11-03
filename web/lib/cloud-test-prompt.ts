/** User-editable testing instructions; this template does not submit or start work. */
export function cloudTestPrompt(mrUrl: string, locale: "en" | "zh"): string {
  const mr = mrUrl.trim() || (locale === "en" ? "${MR_URL}" : "${MR地址}");
  if (locale === "en") return `# New requirement: E2E testing

## 1. Context and test draft
- MR / PR: ${mr}
- Test environment: \${TEST_ENVIRONMENT}

Use glab to read the MR description, changes and relevant discussions, and understand the intended behavior and testing direction. For a GitHub PR, use the available provider tools. Test in the environment specified above.

Testing draft and basic flow:
\${TEST_DRAFT_AND_BASIC_FLOW}

## 2. Test analysis
Identify the E2E flow from the business entry point through key state transitions to the final observable result. Use the MR and draft to define the test focus, cases, expected results and scope boundaries. List missing information explicitly; do not invent requirements or expand the scope on your own. Record out-of-scope risks as separate recommendations.

## 3. Subagent review before execution
After analysis, ask an independent subagent to review the test focus and cases:
- Do they follow the requirement's E2E flow and verify its final outcome?
- Have any key steps been missed or unrelated tests added?
Record the review findings and necessary corrections before execution.

## 4. Execution and subagent audit
Use the project's existing test framework and tools in the specified environment. Preserve actual execution records and evidence; source analysis or simulated results alone do not demonstrate E2E execution.

After testing, ask an independent subagent to audit the cases against execution records and evidence. Check whether the E2E flow was completed and identify every skipped, blocked or unexecuted case. Report each case's reason and its impact on the conclusion; never count it as passed. If subagents are unavailable or a review cannot finish, report that limitation explicitly.

## 5. Complete test report
Include:
1. One-sentence summary: the E2E flow tested, overall result and key blockers.
2. Scope and environment: MR changes, environment used, observed SUT version and testing boundaries.
3. Test cases: ID, scenario, steps, expected and actual results, status and evidence references.
4. Execution records: actual times, commands or framework runs, outputs and rerun results where applicable.
5. Evidence: relevant system logs; for on-chain flows, transaction hashes, block or event data and observed state. Link evidence to its cases and distinguish unavailable evidence.
6. Review findings and open issues: both subagent reviews, defects, and all skipped, blocked or unexecuted cases with reasons and impact.

Base the conclusion on actual execution and evidence. Keep test completion, test pass/fail and unverified scope distinct.`;
  return `# 新需求 E2E 测试

## 1. 测试背景与草稿
- MR / PR 地址：${mr}
- 测试环境：\${测试环境}

请通过 glab 读取 MR 描述、代码改动及相关讨论，理解本次需求的预期行为、测试内容和方向；GitHub PR 使用已有的对应工具。请在上述测试环境中进行测试。

以下是测试草稿和基本流程，供理解测试重点：
\${测试草稿与基本流程}

## 2. 测试分析
梳理从业务入口、关键状态流转到最终可观察结果的 E2E 测试链路。结合 MR 与草稿明确测试重点、用例、预期结果及范围边界。缺失信息应明确列出，不补造需求，不擅自扩大测试范围；范围外风险单独列为建议。

## 3. 执行前：subagent 测试重点审查
完成测试分析后，启用独立 subagent 审查测试重点与用例：
- 是否偏离本次需求的 E2E 测试链路，是否验证最终业务结果？
- 是否遗漏关键步骤，或擅自加入与本次需求无关的测试？
记录审查结论，完成必要修正后再执行测试。

## 4. 测试执行与完成后审计
在指定环境中使用项目已有的测试框架与工具执行测试，保留真实执行记录和证据；不能仅以源码分析或模拟结果代替 E2E 实际执行。

测试完成后，启用独立 subagent，逐项对照用例、执行记录和证据，审计是否完成 E2E 测试闭环，以及是否存在跳过、阻塞或未执行的用例。对每项未完成测试上报具体原因及其对结论的影响，不得计为通过。若 subagent 不可用或审查无法完成，也须如实报告。

## 5. 完整测试报告
请输出包含以下内容的报告：
1. 一句话总结：实际验证的 E2E 链路、总体结果及关键阻塞。
2. 测试范围与环境：MR 改动、使用的测试环境、实际观察到的被测版本和本轮边界。
3. 测试用例：用例 ID、场景、步骤、预期结果、实际结果、状态及证据引用。
4. 测试执行记录：实际执行时间、命令或框架运行记录、输出，以及适用的复测结果。
5. 证据：相关系统日志；涉及链上流程时，提供交易哈希、区块或事件数据及实际状态。证据须对应到具体用例，缺失证据应明确说明。
6. 审查结论与遗留问题：两次 subagent 审查结论、缺陷，以及所有跳过、阻塞、未执行用例的原因和影响。

结论须基于实际执行与证据，明确区分测试完成、测试通过和未验证范围。`;
}
