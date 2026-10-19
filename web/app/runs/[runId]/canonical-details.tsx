"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Empty, Skeleton, Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { errorText, getImplementationContent } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Requirement, Risk, TestCase, TestImplementation } from "@/lib/types";

export type CanonicalSelection = { kind: "requirement" | "risk" | "testCase" | "implementation"; id: string };

type Props = {
  runId: string;
  selection: CanonicalSelection | null;
  requirements: Requirement[];
  risks: Risk[];
  testCases: TestCase[];
  implementations: TestImplementation[];
  onSelect: (selection: CanonicalSelection) => void;
  onClose: () => void;
};

/** Accepted testing assets share the run's pinned source; Provider drafts do not appear here. */
export function CanonicalDetailsDrawer({ runId, selection, requirements, risks, testCases, implementations, onSelect, onClose }: Props) {
  const { t, label, locale } = useI18n();
  const requirement = selection?.kind === "requirement" ? requirements.find((item) => item.id === selection.id) : undefined;
  const risk = selection?.kind === "risk" ? risks.find((item) => item.id === selection.id) : undefined;
  const testCase = selection?.kind === "testCase" ? testCases.find((item) => item.id === selection.id) : undefined;
  const implementation = selection?.kind === "implementation" ? implementations.find((item) => item.id === selection.id) : undefined;
  const record = requirement || risk || testCase || implementation;
  const source = useQuery({
    queryKey: ["implementation-content", runId, implementation?.id],
    queryFn: () => getImplementationContent(runId, implementation!.id),
    enabled: !!implementation?.artifact_uri,
    retry: false,
  });
  const title = selection?.kind === "requirement" ? t("Requirement details", "需求详情")
    : selection?.kind === "risk" ? t("Risk details", "风险详情")
    : selection?.kind === "testCase" ? t("Test case details", "测试用例详情")
    : t("Implementation details", "自动化实现详情");

  function text(value: string | null | undefined): ReactNode {
    return <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxWidth: "75ch" }}>{value || t("Not recorded.", "未记录。")}</Typography.Paragraph>;
  }

  function references(heading: string, kind: CanonicalSelection["kind"], keys: string[], available: Array<{ id: string; key: string; title?: string; file_path?: string }>) {
    return <section style={{ marginTop: 24 }} aria-label={heading}>
      <Typography.Title level={4}>{heading}</Typography.Title>
      {keys.length ? <Space direction="vertical" style={{ width: "100%" }}>{keys.map((key) => {
        const item = available.find((entry) => entry.key === key);
        return item ? <Button key={key} type="link" className="text-link" onClick={() => onSelect({ kind, id: item.id })}>{item.title || item.file_path || item.key} <span className="entity-key">{item.key}</span></Button>
          : <Typography.Text key={key} type="secondary">{key} · {t("Not in the loaded records", "尚未加载此关联记录")}</Typography.Text>;
      })}</Space> : <Typography.Paragraph type="secondary">{t("No linked records.", "暂无关联记录。")}</Typography.Paragraph>}
    </section>;
  }

  const requirementRisks = requirement ? risks.filter((item) => item.requirement_keys.includes(requirement.key)) : [];
  const riskCases = risk ? testCases.filter((item) => item.risk_keys.includes(risk.key)) : [];
  const caseImplementations = testCase ? implementations.filter((item) => (item.test_case_keys || item.testcase_keys || []).includes(testCase.key)) : [];

  return <Drawer title={title} open={!!selection} width={840} onClose={onClose}>
    {!record ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("This record is not in the loaded testing assets. Refresh the run before trying again.", "当前已加载的测试产物中没有此记录，请刷新运行后重试。")} /> : <>
      <Typography.Text className="entity-key" copyable>{record.key}</Typography.Text>
      <Typography.Title level={3} style={{ overflowWrap: "anywhere" }}>{implementation ? implementation.file_path : (requirement || risk || testCase)!.title}</Typography.Title>
      <Space wrap style={{ marginBottom: 16 }}>
        <Tag>{label(implementation ? implementation.validation_status : (requirement || risk || testCase)!.lifecycle_status)}</Tag>
        {(requirement || testCase) && <Tag>{label((requirement || testCase)!.priority)}</Tag>}
        {risk && <Tag>{label(risk.severity)}</Tag>}
      </Space>
      {requirement && <>
        <Typography.Title level={4}>{t("Requirement", "需求说明")}</Typography.Title>{text(requirement.description)}
        <Descriptions column={1} size="small" items={[
          { key: "type", label: t("Type", "类型"), children: label(requirement.requirement_type) },
          { key: "source", label: t("Source", "来源"), children: label(requirement.source_type) },
          { key: "reference", label: t("Source reference", "来源引用"), children: text(requirement.source_ref) },
          { key: "logical", label: t("Logical key", "逻辑标识"), children: text(requirement.logical_key) },
        ]} />
        {references(t("Linked risks", "关联风险"), "risk", requirementRisks.map((item) => item.key), risks)}
      </>}
      {risk && <>
        <Typography.Title level={4}>{t("Risk", "风险说明")}</Typography.Title>{text(risk.description)}
        <Descriptions column={1} size="small" items={[
          { key: "category", label: t("Category", "类别"), children: label(risk.category) },
          { key: "probability", label: t("Probability", "发生概率"), children: label(risk.probability) },
        ]} />
        <Typography.Title level={4}>{t("Rationale", "风险依据")}</Typography.Title>{text(risk.rationale)}
        {references(t("Linked requirements", "关联需求"), "requirement", risk.requirement_keys, requirements)}
        {references(t("Linked test cases", "关联测试用例"), "testCase", riskCases.map((item) => item.key), testCases)}
      </>}
      {testCase && <>
        <Typography.Title level={4}>{t("Test intent", "测试意图")}</Typography.Title>{text(testCase.description)}
        <Typography.Paragraph><Typography.Text type="secondary">{t("Test type", "测试类型")} </Typography.Text>{label(testCase.test_type)}</Typography.Paragraph>
        <Typography.Title level={4}>{t("Preconditions", "前置条件")}</Typography.Title>
        {testCase.preconditions.length ? <ol>{testCase.preconditions.map((item, index) => <li key={index}>{text(item)}</li>)}</ol> : <Typography.Paragraph type="secondary">{t("No preconditions recorded.", "未记录前置条件。")}</Typography.Paragraph>}
        <Typography.Title level={4}>{t("Expected result", "预期结果")}</Typography.Title>{text(testCase.expected_result)}
        {references(t("Linked risks", "关联风险"), "risk", testCase.risk_keys, risks)}
        {references(t("Accepted implementations", "已接受的自动化实现"), "implementation", caseImplementations.map((item) => item.key), implementations)}
      </>}
      {implementation && <>
        <Descriptions column={1} size="small" items={[
          { key: "symbol", label: t("Test function", "测试函数"), children: <Typography.Text code copyable>{implementation.symbol}</Typography.Text> },
          { key: "framework", label: t("Framework", "框架"), children: `${implementation.framework} / ${implementation.language}` },
          { key: "commit", label: t("Source commit", "源码提交"), children: <Typography.Text code copyable>{implementation.commit_sha}</Typography.Text> },
          ...(implementation.repository_url ? [{ key: "repository", label: t("Repository", "仓库"), children: text(implementation.repository_url) }] : []),
          ...(implementation.source_sha256 ? [{ key: "sha", label: "SHA-256", children: <Typography.Text code copyable>{implementation.source_sha256}</Typography.Text> }] : []),
        ]} />
        <section style={{ marginTop: 24 }} aria-label={t("Accepted test source", "已接受的测试源码")}>
          <Typography.Title level={4}>{t("Accepted test source", "已接受的测试源码")}</Typography.Title>
          <Typography.Paragraph type="secondary">{t("This code was accepted as a testing asset. Its validation status and official Runner results are separate records.", "此代码是已接受的测试产物。源码验证状态和正式 Runner 执行结果分别记录。")}</Typography.Paragraph>
          {!implementation.artifact_uri ? <Alert type="info" showIcon message={t("Existing repository test", "仓库中已有的测试")} description={t("This implementation references a test in the pinned commit. Review the recorded file and function in that repository; no generated source artifact was saved.", "此实现引用固定提交中的已有测试。请在该仓库的对应提交中查看上述文件和函数；平台没有保存独立的生成源码文件。")} />
            : source.isLoading ? <Skeleton active paragraph={{ rows: 6 }} />
              : source.error ? <Alert type="error" showIcon message={t("Test source could not be verified", "测试源码未能通过读取校验")} description={errorText(source.error, locale)} action={<Button onClick={() => void source.refetch()}>{t("Retry", "重试")}</Button>} />
                : source.data !== undefined ? <pre className="artifact-content">{source.data}</pre> : null}
        </section>
        {references(t("Linked test cases", "关联测试用例"), "testCase", implementation.test_case_keys || implementation.testcase_keys || [], testCases)}
      </>}
    </>}
  </Drawer>;
}
