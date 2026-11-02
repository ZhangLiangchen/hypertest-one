"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { credentialFreeUrl } from "@/lib/cloud";
import type { CloudConfiguration, CloudConfigRevision } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import type { Project } from "@/lib/types";
import "./resources-layout.css";

type ResourceValues = { sut_url: string; framework_url: string; environment_name: string; expected_deployment?: string };

export function CloudResources({ latest, project, operation, enabled, onSaved }: {
  latest?: CloudConfigRevision; project?: Project;
  operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onSaved: () => void;
}) {
  const { t } = useI18n();
  const [form] = Form.useForm<ResourceValues>();
  const [resourceIssue, setResourceIssue] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [baseVersion, setBaseVersion] = useState(0);
  const [draftTouched, setDraftTouched] = useState(false);
  const [baseConfiguration, setBaseConfiguration] = useState<CloudConfiguration | null>(null);

  useEffect(() => {
    if (latest || loaded !== null || draftTouched || !project) return;
    form.setFieldsValue({ sut_url: project.repository_url || "", framework_url: project.test_framework_repository_url || "" });
  }, [project, latest, loaded, draftTouched, form]);

  useEffect(() => {
    if (!latest || loaded !== null || draftTouched) return;
    const config = latest.configuration;
    form.setFieldsValue({ sut_url: config.sut.url, framework_url: config.framework.url,
      environment_name: config.environment.name, expected_deployment: config.environment.expected_deployment });
    setLoaded(latest.id); setBaseVersion(latest.revision); setBaseConfiguration(config);
  }, [latest, loaded, form, draftTouched]);

  const blocked = !enabled || operation.blocked;
  async function configure(values: ResourceValues) {
    if (blocked) return;
    setResourceIssue(null);
    try {
      const sutUrl = values.sut_url.trim(), frameworkUrl = values.framework_url.trim();
      // WEB_ONLY currently requires its legacy HTTPS connection. Keep the
      // original environment intact until that restriction has a native route.
      const legacyWebOnly = baseConfiguration?.environment.cloud_access_policy === "WEB_ONLY";
      const configuration: CloudConfiguration = {
        sut: { url: sutUrl, ...(baseConfiguration?.sut.url === sutUrl && baseConfiguration.sut.default_selector ? { default_selector: baseConfiguration.sut.default_selector } : {}) },
        framework: { url: frameworkUrl, ...(baseConfiguration?.framework.url === frameworkUrl && baseConfiguration.framework.default_selector ? { default_selector: baseConfiguration.framework.default_selector } : {}) },
        environment: { ...(legacyWebOnly ? baseConfiguration.environment : { connection: "NONE" as const, require_matching_deployment: false,
          ...(baseConfiguration?.environment.cloud_access_policy ? { cloud_access_policy: baseConfiguration.environment.cloud_access_policy } : {}) }), name: values.environment_name.trim(),
          expected_deployment: values.expected_deployment?.trim() || "UNKNOWN" },
      };
      const result = await operation.submit({ operation: "CONFIGURE", expected_version: baseVersion, configuration });
      if (result) { setLoaded(result.config_id || null); setBaseVersion(result.version); setBaseConfiguration(configuration); onSaved(); }
    } catch { setResourceIssue(t("Review both repository addresses before saving.", "请先核对两个仓库的地址。")); }
  }

  return <div className="workspace-section-stack cloud-resources">
    <section className="overview-section workspace-panel cloud-resources-config" aria-labelledby="cloud-resources-title">
      <div className="cloud-resources-heading"><div><Typography.Title id="cloud-resources-title" level={2}>{t("Project repositories and environment", "项目仓库与测试环境")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Choose repository versions for each task; saved resource revisions remain unchanged.", "为每个任务选择仓库版本；已保存的资源修订保持不变。")}</Typography.Paragraph></div><span className="cloud-resources-baseline">{t("Draft baseline revision", "草稿基线修订")} <strong>{baseVersion}</strong></span></div>
      {resourceIssue ? <Alert showIcon type="error" message={resourceIssue} style={{ marginBottom: 20 }} /> : null}
      {latest && latest.revision !== baseVersion ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("A newer resource revision is available", "存在更新的资源修订")}
        description={t("Your draft still uses its original version. Read the saved revision before replacing your draft; it will not be rebased automatically.", "草稿仍使用原版本。替换草稿前请核对已保存修订，系统不会自动改变提交基线。 ")}
        action={<Button disabled={operation.blocked} onClick={() => { setDraftTouched(false); setLoaded(null); }}>{t("Load latest saved resources", "载入最新已保存资源")}</Button>} /> : null}
      {baseConfiguration?.environment.cloud_access_policy === "WEB_ONLY" ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Existing environment restriction retained", "保留现有环境访问限制")}
        description={t("This resource revision retains its existing HTTPS-only environment configuration. An unavailable credential or unsupported runtime may prevent its use.", "此资源修订保留现有仅 HTTPS 环境配置；凭据不可用或运行环境不支持时可能无法使用。 ")} /> : null}
      {baseConfiguration?.environment.cloud_access_policy === "LOCAL_ONLY" ? <Alert showIcon type="info" style={{ marginBottom: 20 }} message={t("Existing environment restriction retained", "保留现有环境访问限制")}
        description={t("This environment is restricted to Local tasks.", "此环境仅允许 Local 任务。 ")} /> : null}
      <Form form={form} className="workspace-form cloud-task-fields" layout="vertical" onValuesChange={() => setDraftTouched(true)} initialValues={{ environment_name: "Test environment", expected_deployment: "UNKNOWN" }} onFinish={(values) => void configure(values)} scrollToFirstError>
        <div className="form-grid cloud-resources-repositories">{(["sut", "framework"] as const).map((role) => <section className="form-section" key={role}>
          <Typography.Title level={3}>{role === "sut" ? t("System under test", "被测对象") : t("Test framework", "测试框架")}</Typography.Title>
          <Form.Item name={`${role}_url`} label={t("Git repository URL", "Git 仓库地址")} rules={[{ required: true }, { validator: (_, value) => !value || credentialFreeUrl(value) ? Promise.resolve() : Promise.reject(new Error(t("Use an HTTPS or SSH Git address without embedded credentials.", "请使用不含凭据的 HTTPS 或 SSH Git 地址。"))) }]}><Input autoComplete="off" placeholder="https://git.example.com/team/repository.git" /></Form.Item>
        </section>)}</div>
        <section className="form-section cloud-resources-environment" aria-labelledby="cloud-environment-title">
          <Typography.Title id="cloud-environment-title" level={3}>{t("Test environment", "测试环境")}</Typography.Title>
          <div className="form-grid cloud-resource-environment-fields">
          <Form.Item name="environment_name" label={t("Environment name", "环境名称")} rules={[{ required: true }]}><Input maxLength={128} /></Form.Item>
          <Form.Item name="expected_deployment" label={t("Expected deployment identity", "预期部署版本")} extra={t("A source SHA does not prove the environment runs that version.", "源码 SHA 不证明环境已部署对应版本。 ")}><Input maxLength={512} /></Form.Item>
          </div>
        </section>
        <div className="form-actions"><Button type="primary" htmlType="submit" disabled={blocked} loading={operation.busy}>{t("Save resource revision", "保存资源修订")}</Button>
          <Typography.Text className="cloud-resource-action-baseline" type="secondary">{t("Draft baseline revision", "草稿基线修订")}: {baseVersion}</Typography.Text></div>
      </Form>
    </section>
  </div>;
}
