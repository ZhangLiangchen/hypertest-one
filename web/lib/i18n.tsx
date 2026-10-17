"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

export type Locale = "zh" | "en";
export const LOCALE_COOKIE = "hypertest_locale";

const labels: Record<string, [string, string]> = {
  ACTIVE: ["Active", "启用"], ARCHIVED: ["Archived", "已归档"],
  CREATED: ["Created", "已创建"], READY: ["Ready", "就绪"],
  ANALYZING: ["Analyzing", "分析中"], DESIGNING: ["Designing", "设计中"],
  IMPLEMENTING: ["Implementing", "实现中"], EXECUTING: ["Executing", "执行中"],
  DIAGNOSING: ["Diagnosing", "诊断中"], VERIFYING: ["Verifying", "校验中"],
  COMPLETED: ["Completed", "已完成"], CANCELLED: ["Cancelled", "已取消"],
  FAILED: ["Failed", "失败"], ERROR: ["Error", "错误"], TIMED_OUT: ["Timed out", "已超时"],
  QUEUED: ["Queued", "排队中"], RUNNING: ["Running", "运行中"],
  PROVISIONING: ["Provisioning", "准备环境中"], COLLECTING: ["Collecting evidence", "采集证据中"],
  DISPATCHED: ["Dispatched", "已派发"], WAITING_INPUT: ["Waiting for input", "等待输入"],
  WAITING_EXECUTION: ["Waiting for execution", "等待执行"], SUBMITTED: ["Submitted", "已提交"],
  RETRYING: ["Retrying", "重试中"], EXPIRED: ["Expired", "已过期"],
  CANCEL_REQUESTED: ["Cancellation requested", "已请求取消"], INTERRUPTED: ["Interrupted", "已中断"],
  SUCCEEDED: ["Task completed", "任务已完成"], PARTIAL: ["Partial", "部分完成"],
  PENDING: ["Pending", "待处理"], VALIDATING: ["Validating", "校验中"],
  ACCEPTED: ["Accepted", "已接受"], REJECTED: ["Rejected", "已拒绝"],
  VALIDATED: ["Validated", "校验通过"], STALE: ["Stale", "已失效"],
  SUPERSEDED: ["Superseded", "已被替代"], DEPRECATED: ["Deprecated", "已弃用"],
  OPEN: ["Open", "待处理"], MITIGATED: ["Mitigated", "已缓解"], OBSOLETE: ["Obsolete", "已过时"],
  PASS: ["Pass", "通过"], FAIL: ["Fail", "未通过"], BLOCKED: ["Blocked", "受阻"],
  INCONCLUSIVE: ["Inconclusive", "结论不确定"], UNKNOWN: ["Unknown", "未知"],
  SKIPPED: ["Skipped", "已跳过"], NOT_RUN: ["Not run", "尚未运行"],
  RELEASE_READY: ["Ready for release", "可发布"], RELEASE_BLOCKED: ["Release blocked", "阻止发布"],
  RETEST_REQUIRED: ["Retest required", "需要复测"], RISK_ACCEPTED: ["Risk accepted", "已接受风险"],
  DRAFT: ["Draft", "草稿"], FINAL: ["Final", "正式结论"], REVOKED: ["Revoked", "已撤销"],
  NEW: ["New", "待分诊"], TRIAGED: ["Triaged", "已分诊"], INVALID: ["Invalid", "无效"],
  CONFIRMED: ["Confirmed", "已确认"], RESOLVED: ["Resolved", "已解决"],
  CLOSED: ["Closed", "已关闭"], REOPENED: ["Reopened", "已重开"],
  BLOCKER: ["Blocker", "阻断"], CRITICAL: ["Critical", "严重"], MAJOR: ["Major", "重大"],
  MINOR: ["Minor", "轻微"], INFO: ["Informational", "提示"],
  HIGH: ["High", "高"], MEDIUM: ["Medium", "中"], LOW: ["Low", "低"],
  FUNCTIONAL: ["Functional", "功能"], NON_FUNCTIONAL: ["Non-functional", "非功能"],
  CONSTRAINT: ["Constraint", "约束"], BOUNDARY: ["Boundary", "边界"],
  NEGATIVE: ["Negative", "异常输入"], FAILURE: ["Failure handling", "故障处理"],
  CONCURRENCY: ["Concurrency", "并发"], CONSISTENCY: ["Consistency", "一致性"],
  COMPATIBILITY: ["Compatibility", "兼容性"], SECURITY: ["Security", "安全"],
  PERFORMANCE: ["Performance", "性能"], RELIABILITY: ["Reliability", "可靠性"],
  OPERABILITY: ["Operability", "可运维性"], OBSERVABILITY: ["Observability", "可观测性"],
  UPGRADE: ["Upgrade", "升级"], DATA: ["Data", "数据"], RECOVERY: ["Recovery", "恢复"],
  ANALYZE_REQUIREMENTS: ["Analyze requirements", "分析需求"], ANALYZE_IMPACT: ["Analyze impact", "分析影响"],
  ANALYZE_RISKS: ["Analyze risks", "分析风险"], DESIGN_TESTS: ["Design tests", "设计用例"],
  REVIEW_TESTS: ["Review tests", "评审用例"], IMPLEMENT_TESTS: ["Implement tests", "生成测试实现"],
  REVIEW_IMPLEMENTATION: ["Review implementation", "评审测试实现"],
  DIAGNOSE_FAILURE: ["Diagnose failures", "诊断失败"], INVESTIGATE_FINDING: ["Investigate finding", "调查发现"],
  REPAIR_TEST: ["Repair tests", "修复测试"], RETEST_ANALYSIS: ["Analyze retest", "分析复测"],
  VERIFY_COVERAGE: ["Verify coverage", "校验覆盖"],
  REQUIREMENT: ["Requirement", "需求"], RISK: ["Risk", "风险"], TEST_CASE: ["Test case", "测试用例"],
  TEST_IMPLEMENTATION: ["Test implementation", "测试实现"], FINDING: ["Finding", "问题发现"],
  TEST_RUN: ["Test run", "测试运行"], RELEASE: ["Release", "发布"],
  PREPARE_WORKSPACE: ["Prepare source checkout", "准备源码检出"], EXECUTE_MISSION: ["Execute mission", "执行任务阶段"],
  EXECUTE_TESTS: ["Run official tests", "运行正式测试"], ADVANCE_RUN: ["Run test cycle", "运行测试周期"],
  EVALUATE_GATE: ["Evaluate quality gate", "评估质量门禁"],
  OFFICIAL: ["Official", "正式执行"], EXPLORATORY: ["Exploratory", "探索执行"],
  VALIDATION: ["Validation", "验证执行"], REPRODUCTION: ["Reproduction", "复现执行"],
  COLLECTED: ["Collected", "已采集"], VERIFIED: ["Verified", "已验证"],
  RUNNER: ["Trusted Runner", "可信 Runner"], SYSTEM: ["System", "系统"],
  EXTERNAL_VERIFIED: ["Externally verified", "外部已验证"], AGENT_REPORTED: ["Agent reported", "Agent 自述"],
  USER_PROVIDED: ["User provided", "用户提供"],
  EXECUTION_METADATA: ["Execution metadata", "执行元数据"], STDOUT: ["Standard output", "标准输出"],
  STDERR: ["Standard error", "标准错误"], JUNIT: ["JUnit report", "JUnit 测试报告"],
  HTTP_REQUEST: ["HTTP request", "HTTP 请求"], HTTP_RESPONSE: ["HTTP response", "HTTP 响应"],
  LOG: ["Log", "日志"], METRIC: ["Metric", "指标"], TRACE: ["Trace", "链路追踪"],
  SCREENSHOT: ["Screenshot", "截图"], DATABASE_STATE: ["Database state", "数据库状态"],
  FILE_ARTIFACT: ["File artifact", "文件产物"], GIT_DIFF: ["Git diff", "Git 变更"],
  ENVIRONMENT_FINGERPRINT: ["Environment fingerprint", "环境指纹"], CUSTOM: ["Custom", "自定义"],
  PRODUCT_DEFECT: ["Product defect", "产品缺陷"], TEST_DEFECT: ["Test defect", "测试缺陷"],
  ENVIRONMENT_FAILURE: ["Environment failure", "环境故障"], INFRA_FAILURE: ["Infrastructure failure", "基础设施故障"],
  FLAKY: ["Flaky", "不稳定"], DATA_ISSUE: ["Data issue", "数据问题"],
  EXPECTED_BEHAVIOR: ["Expected behavior", "符合预期"], REQUIREMENT_ISSUE: ["Requirement issue", "需求问题"],
  FIXED: ["Fixed", "已修复"], DUPLICATE: ["Duplicate", "重复问题"], WONT_FIX: ["Won't fix", "不予修复"],
  NOT_REPRODUCIBLE: ["Not reproducible", "无法复现"], ENVIRONMENT_FIXED: ["Environment fixed", "环境已修复"],
  TEST_FIXED: ["Test fixed", "测试已修复"], SUPPORTS: ["Supports", "支持"],
  CONTRADICTS: ["Contradicts", "相矛盾"], CONTEXT: ["Context", "上下文"],
  CREATE: ["Create", "创建"], UPDATE: ["Update", "更新"], DEPRECATE: ["Deprecate", "弃用"],
  LINK: ["Link", "关联"], UNLINK: ["Unlink", "取消关联"],
  PRD: ["PRD", "PRD 需求文档"], ISSUE: ["Issue", "议题"], API_SPEC: ["API specification", "API 规范"],
  DESIGN_DOC: ["Design document", "设计文档"], CODE: ["Code", "代码"], MANUAL: ["Manual", "手动"],
  WEB: ["Web", "网页提交"], COVERED: ["Covered", "已覆盖"], GAP: ["Gap", "存在缺口"],
  EXECUTION_REQUIRED: ["Official execution required", "需要正式执行"],
  EXECUTION_IN_PROGRESS: ["Execution in progress", "正式执行进行中"],
  VERDICT_REQUIRED: ["Quality decision required", "需要质量判定"],
  VERDICT_FINALIZED: ["Quality decision finalized", "质量判定已完成"],
  STEP_LIMIT_REACHED: ["Step limit reached", "已达到本次步骤上限"],
  MISSION_REJECTED: ["Mission result was not accepted", "测试任务产出未被接受"],
  MISSION_FAILED: ["Mission needs explicit recovery", "测试任务需要显式恢复"],
  MISSION_IN_PROGRESS: ["Mission in progress", "测试任务仍在进行"],
  TEST_DESIGN_COVERAGE_COMPLETE: ["Test design coverage complete", "测试设计覆盖已完成"],
};

function localizeVerdictReason(reason: string, locale: Locale): string {
  if (locale === "en") return reason;
  const messages: Record<string, string> = {
    "TestRun is cancelled.": "本次测试运行已取消。",
    "Requirements, risks, and active test cases must all be present.": "需要先具备需求、风险和有效测试用例。",
    "Risk identification and required test design dimensions are incomplete.": "风险识别或要求的测试设计维度尚未覆盖完整。",
    "Complete risk design coverage; every active test case passed its latest official execution with verified trusted evidence; no policy-blocking confirmed product defect.": "风险设计覆盖完整；所有有效测试用例的最新正式执行均通过，并具有已验证的可信证据；不存在按策略阻止发布的已确认产品缺陷。",
  };
  return reason.split("\n").map((line) => {
    if (messages[line]) return messages[line];
    const defect = line.match(/^Confirmed product defects block release: (.+)\.$/);
    if (defect) return `已确认的产品缺陷阻止发布：${defect[1]}。`;
    const caseReason = line.match(/^([^:]+): (.+)$/);
    if (!caseReason) return line;
    const [, key, detail] = caseReason;
    const caseMessages: Record<string, string> = {
      "no official execution result.": "尚无正式执行结果。",
      "latest official execution has a different source commit.": "最新正式执行的源码提交与本次运行不一致。",
      "latest official execution failed.": "最新正式执行未通过。",
      "verified trusted execution metadata and JUnit evidence are required.": "需要已验证的可信执行元数据和 JUnit 测试证据。",
    };
    if (caseMessages[detail]) return `${key}：${caseMessages[detail]}`;
    const pending = detail.match(/^latest official execution is ([A-Z_]+)\.$/);
    if (pending) return `${key}：最新正式执行的状态为${labels[pending[1]]?.[1] || pending[1]}。`;
    const result = detail.match(/^no successful official case result \(([A-Z_]+)\)\.$/);
    if (result) return `${key}：尚无通过的正式用例结果（${labels[result[1]]?.[1] || result[1]}）。`;
    return line;
  }).join("\n");
}

type I18n = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (english: string, chinese: string) => string;
  label: (value: string | null | undefined) => string;
  formatDate: (value: string | null | undefined) => string;
  verdictReason: (reason: string) => string;
};

const Context = createContext<I18n | null>(null);

export function I18nProvider({ initialLocale, children }: { initialLocale: Locale; children: React.ReactNode }) {
  const [locale, updateLocale] = useState<Locale>(initialLocale);
  const setLocale = useCallback((next: Locale) => {
    updateLocale(next);
    document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
    document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }, []);
  const value = useMemo<I18n>(() => ({
    locale,
    setLocale,
    t: (english, chinese) => locale === "zh" ? chinese : english,
    label: (code) => code ? labels[code]?.[locale === "zh" ? 1 : 0] || code : "—",
    verdictReason: (reason) => localizeVerdictReason(reason, locale),
    formatDate: (timestamp) => {
      if (!timestamp) return "—";
      const date = new Date(timestamp);
      return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US");
    },
  }), [locale, setLocale]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n requires I18nProvider");
  return value;
}
