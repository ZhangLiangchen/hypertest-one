"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Empty, Skeleton, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { errorText, getRunHarness, getRunReportContent, recoverRunBinding } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { RunBinding } from "@/lib/types";

export function RunHarness({ runId, refreshRun, selectTab }: { runId: string; refreshRun: () => Promise<unknown>; selectTab: (key: string) => void }) {
  const { t, label, locale, formatDate } = useI18n();
  const client = useQueryClient();
  const harness = useQuery({ queryKey: ["harness", runId], queryFn: () => getRunHarness(runId), refetchInterval: 5_000 });
  const [reportId, setReportId] = useState<string | null>(null);
  const report = harness.data?.reports.find((item) => item.id === reportId);
  const content = useQuery({ queryKey: ["run-report", reportId], queryFn: () => getRunReportContent(reportId!), enabled: !!reportId, retry: false });
  const binding = harness.data?.binding;
  const recovery = useMutation({
    mutationFn: (current: RunBinding) => recoverRunBinding(current),
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: ["harness", runId] });
      await refreshRun();
    },
  });
  const color = binding?.status === "RECOVERY_REQUIRED" || binding?.status === "WAITING_INPUT" ? "gold"
    : binding?.status === "FAILED" ? "red" : binding?.status === "ACTIVE" ? "blue" : undefined;

  return <section className="harness-records" aria-label={t("Session & reports", "持续会话与报告")}>
    <div className="section-heading"><h2>{t("Persistent testing session", "持续测试会话")}</h2><Button onClick={() => void harness.refetch()} loading={harness.isFetching}>{t("Refresh", "刷新")}</Button></div>
    <Typography.Paragraph className="muted">{t("A bound session retains the same testing context across stages and questions. Formal execution evidence and the quality verdict remain in their own records.", "已绑定会话会在阶段切换和人工问答之间保留同一测试上下文。正式执行证据与质量判定仍以各自记录为准。")}</Typography.Paragraph>
    {harness.error && <Alert type="warning" showIcon message={t("Session details could not be refreshed", "会话详情暂时无法刷新")} description={errorText(harness.error, locale)} />}
    {harness.isLoading ? <Skeleton active paragraph={{ rows: 3 }} /> : !binding ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("This run has no persistent session binding. Any existing stage history and testing results remain available in their sections.", "此运行尚无持续会话绑定。已有阶段历史与测试结果仍可在相应栏目中查看。")} /> : <>
      <Space wrap><Tag color={color}>{binding.status === "ACTIVE" ? t("Session available", "会话可继续") : label(binding.status)}</Tag><Typography.Text type="secondary">{t("Updated", "更新于")} {formatDate(binding.updated_at)}</Typography.Text></Space>
      {binding.status === "WAITING_INPUT" && <Alert type="info" showIcon style={{ marginTop: 16 }} message={t("The session is waiting for your answer", "会话正在等待你的回答")} description={t("Answer the recorded question to continue the same task and session.", "回答已记录的问题，即可继续同一任务与会话。") } action={<Button onClick={() => selectTab("input-requests")}>{t("Questions & answers", "问题与回答")}</Button>} />}
      {binding.status === "RECOVERY_REQUIRED" && <Alert type="warning" showIcon style={{ marginTop: 16 }} message={t("Verify the original session before continuing", "继续前需核验原会话")} description={<><p>{t("Recovery checks that the old call has stopped and the original session and workspace are intact. It does not replay an interrupted test. After successful recovery, retry the recorded task explicitly.", "恢复会核验旧调用已停止、原会话与工作区仍完整，不会重放中断的测试。恢复成功后，请在后台任务中显式重试原任务。")}</p><Button loading={recovery.isPending} disabled={!!harness.error} onClick={() => recovery.mutate(binding)}>{t("Verify & recover session", "核验并恢复会话")}</Button></>} />}
      {recovery.error && <Alert type="error" showIcon style={{ marginTop: 16 }} message={t("Session recovery was not confirmed", "尚未确认会话恢复成功")} description={errorText(recovery.error, locale)} />}
      {recovery.isSuccess && binding.status !== "RECOVERY_REQUIRED" && <Alert type="info" showIcon style={{ marginTop: 16 }} message={t("Session verified; inspect the task before retrying", "原会话已核验，请检查任务后重试")} action={<Button onClick={() => selectTab("tasks")}>{t("Background tasks", "后台任务")}</Button>} />}
      <details style={{ marginTop: 16 }}><summary>{t("Session identity & limits", "会话身份与限制")}</summary><Descriptions size="small" column={1} style={{ marginTop: 12 }} items={[
        { key: "binding", label: t("Binding", "绑定标识"), children: <Typography.Text code copyable>{binding.id}</Typography.Text> },
        { key: "session", label: t("Primary session", "主会话标识"), children: <Typography.Text code copyable>{binding.primary_agent_session_id}</Typography.Text> },
        { key: "epoch", label: t("Recovery generation", "恢复代际"), children: binding.binding_epoch },
        ...(harness.data?.state ? [{ key: "budget", label: t("Cycle limits", "周期上限"), children: t(`Up to ${harness.data.state.max_steps} steps; ${harness.data.state.timeout_seconds}s per test execution; ${harness.data.state.harness_budget_seconds}s of active agent time across the run. Waiting for your answer does not use this time.`, `最多 ${harness.data.state.max_steps} 个步骤；每次测试执行限时 ${harness.data.state.timeout_seconds} 秒；整个运行累计 Agent 活跃时间上限 ${harness.data.state.harness_budget_seconds} 秒。等待回答不计入活跃时间。`) }] : []),
      ]} /></details>
    </>}
    <section style={{ marginTop: 28 }} aria-label={t("Testing reports", "测试报告")}>
      <div className="section-heading"><h2>{t("Testing reports", "测试报告")}</h2></div>
      <Typography.Paragraph className="muted">{t("Reports summarize accepted records. Use the quality verdict and linked evidence to assess release readiness.", "报告汇总已接受的记录。请结合质量判定与关联证据判断是否可发布。")}</Typography.Paragraph>
      {!!harness.data?.reports.length ? <ul className="input-request-list">{harness.data.reports.map((item) => <li key={item.id}><div><Typography.Text strong>{t("Testing report", "测试报告")}</Typography.Text><p className="muted">{formatDate(item.created_at)}</p></div><Button onClick={() => setReportId(item.id)}>{t("Read report", "阅读报告")}</Button></li>)}</ul> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={harness.error ? t("Reports could not be loaded. Refresh to try again.", "暂无法读取报告，请刷新重试。") : t("No report has been submitted yet.", "尚未提交测试报告。")} />}
    </section>
    <section style={{ marginTop: 28 }} aria-label={t("GitLab issues", "GitLab 问题单")}>
      <div className="section-heading"><h2>{t("GitLab issues", "GitLab 问题单")}</h2></div>
      {!!harness.data?.issues.length ? <ul className="input-request-list">{harness.data.issues.map((item) => <li key={item.id}><div><Space wrap><Tag color={item.status === "UNKNOWN" ? "gold" : undefined}>{item.status === "SUCCEEDED" ? t("Issue created", "已创建问题单") : label(item.status)}</Tag><Typography.Text className="muted">{formatDate(item.updated_at)}</Typography.Text></Space><p className="entity-key">{t("Finding", "问题发现")} {item.finding_id}</p>{item.status === "UNKNOWN" && <p>{t("The external result is unknown. Reconcile the existing request before creating another issue.", "外部结果尚不确定。请先核对已有请求，避免重复创建问题单。")}</p>}</div>{item.status === "SUCCEEDED" && item.issue_url ? <a href={item.issue_url} target="_blank" rel="noopener noreferrer">{t("Open issue", "打开问题单")} {item.issue_iid ? `#${item.issue_iid}` : ""}</a> : null}</li>)}</ul> : <Typography.Paragraph className="muted">{harness.error ? t("Issue records could not be loaded.", "暂无法读取提单记录。") : t("No issue request has been recorded for this run.", "本次运行尚无提单请求记录。")}</Typography.Paragraph>}
    </section>
    <Drawer title={t("Testing report", "测试报告")} open={!!reportId} width={840} onClose={() => setReportId(null)}>
      {report && <Typography.Paragraph style={{ overflowWrap: "anywhere" }}><Typography.Text className="muted">SHA-256 </Typography.Text><Typography.Text code copyable>{report.content_sha256}</Typography.Text></Typography.Paragraph>}
      {content.error && <Alert type="error" showIcon message={t("Report could not be verified", "报告未能通过读取校验")} description={errorText(content.error, locale)} action={<Button onClick={() => void content.refetch()}>{t("Retry", "重试")}</Button>} />}
      {content.isLoading ? <Skeleton active paragraph={{ rows: 8 }} /> : !content.error && content.data !== undefined ? <pre className="artifact-content">{content.data}</pre> : null}
    </Drawer>
  </section>;
}
