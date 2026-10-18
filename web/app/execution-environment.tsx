"use client";

import { Alert, Button, Descriptions, Form, Input, InputNumber, Select, Space, Spin, Tag, Typography } from "antd";

import { useI18n } from "@/lib/i18n";
import { canUseEnvironment, environmentProfiles, safeHash, selectedEnvironmentProfile, validHealthPath, validServiceApp, validStartupTimeout, visibleDependencies, visibleEnvironmentDefinition, visibleExecutionIdentity } from "@/lib/execution-environment";
import type { EnvironmentFormValues } from "@/lib/execution-environment";
import type { EnvironmentCatalog, EnvironmentProfileId, EnvironmentRequest, ExecutionEnvironmentProfile, TestExecution } from "@/lib/types";

function ProfileName({ id }: { id: EnvironmentProfileId }) {
  const { t } = useI18n();
  if (id === "python-api-v2") return t("Python API · ASGI v2", "Python API · ASGI v2");
  if (id === "python-api-v1") return t("Python API · ASGI v1 (archived)", "Python API · ASGI v1（历史版本）");
  return t("Python · pytest", "Python · pytest");
}
function Dependencies({ values }: { values: unknown }) {
  const { t } = useI18n();
  const packages = visibleDependencies(values);
  return <details className="environment-details"><summary>{t("Preinstalled dependencies", "预装依赖")}</summary>{packages.length ? <ul className="environment-dependencies">{packages.map(([name, version]) => <li key={name}><code>{name} {version}</code></li>)}</ul> : <Typography.Paragraph className="muted">{t("No dependency inventory is available.", "未提供依赖清单。")}</Typography.Paragraph>}</details>;
}
export function EnvironmentRequestSummary({ request, profile }: { request: EnvironmentRequest; profile?: ExecutionEnvironmentProfile }) {
  const { t } = useI18n();
  return <div className="environment-request-summary">
    <Space wrap><Typography.Text strong><ProfileName id={request.profile_id} /></Typography.Text><Tag>{request.profile_id}</Tag></Space>
    <Typography.Paragraph className="muted">{t("Trusted prebuilt image; no external network or package installation during execution.", "使用可信预制镜像；执行时不访问外部网络，不安装依赖。")}</Typography.Paragraph>
    {request.profile_id === "python-api-v2" && <Typography.Paragraph className="muted">{t("API v2 isolates generated-test collection from repository pytest configuration and conftest files. Generated test modules must include their own fixtures.", "API v2 隔离仓库的 pytest 配置与 conftest，生成的测试模块必须自带所需 fixture。")}</Typography.Paragraph>}
    {request.profile_id === "python-api-v1" && <Typography.Paragraph className="muted">{t("This archived binding retains its original collection behavior and identity. New runs use API v2; this record has not been upgraded.", "此历史绑定保留原有测试收集行为与身份。新运行使用 API v2，此记录并未升级。")}</Typography.Paragraph>}
    {request.service && <Descriptions size="small" column={1} items={[
      { key: "app", label: t("ASGI application", "ASGI 应用"), children: <Typography.Text code>{request.service.app}</Typography.Text> },
      { key: "health", label: t("Health path", "就绪检查路径"), children: <Typography.Text code>{request.service.health_path}</Typography.Text> },
      { key: "timeout", label: t("Startup timeout", "启动超时"), children: t(`${request.service.startup_timeout_seconds} seconds`, `${request.service.startup_timeout_seconds} 秒`) },
    ]} />}
    {profile && <Dependencies values={profile.dependencies} />}
  </div>;
}

export function EnvironmentFields({ catalog, loading, failed, refreshing, refresh }: { catalog?: EnvironmentCatalog; loading: boolean; failed: boolean; refreshing: boolean; refresh: () => void }) {
  const { t, formatDate } = useI18n();
  const form = Form.useFormInstance<EnvironmentFormValues>();
  const selected = Form.useWatch("environment_profile_id", { form, preserve: true }) || "python-pytest-v1";
  const profile = selectedEnvironmentProfile(catalog, selected);
  return <>
    <Typography.Paragraph className="muted">{t("Choose a controlled Python environment. HyperTest fixes its image, dependencies and launcher with this run before Agent missions begin. The original testing-context text remains unchanged.", "选择受控 Python 环境。HyperTest 会在 Agent 任务开始前，将镜像、依赖和启动器固定在本次运行中。原测试上下文文字保持不变。")}</Typography.Paragraph>
    <div className="environment-catalog-status">
      <Button loading={refreshing} onClick={refresh}>{t("Refresh image availability", "刷新镜像可用性")}</Button>
      {loading && <Space><Spin size="small" /><span>{t("Reading controlled environments", "正在读取受控环境")}</span></Space>}
    </div>
    {failed && <Alert type="warning" showIcon message={t("Environment catalog is unavailable", "环境目录暂不可读取")} description={t("Your selection and service draft are preserved. Refresh availability before continuing; another environment will not be selected automatically.", "已保留环境选择和服务草稿。请刷新可用性后继续，系统不会自动替换环境。")} />}
    {!loading && !failed && !profile && <Alert type="warning" showIcon message={t("The selected environment is not listed", "目录中未提供所选环境")} description={t("Choose an available controlled profile below, or refresh the catalog. Your current draft remains available.", "请明确选择下方可用的受控环境，或刷新目录。当前草稿仍会保留。")}/>}
    <Form.Item required name="environment_profile_id" label={t("Execution environment", "执行环境")} rules={[{ validator: async (_, value) => { if (!canUseEnvironment(catalog, value, failed)) throw new Error(t("Choose an available controlled image, or refresh image availability.", "请选择镜像可用的受控环境，或先刷新镜像可用性。")); } }]}>
      <Select options={environmentProfiles.map((id) => ({ value: id, label: id === "python-api-v2" ? t("Python API · ASGI v2", "Python API · ASGI v2") : t("Python · pytest", "Python · pytest"), disabled: !canUseEnvironment(catalog, id, failed) }))} />
    </Form.Item>
    {profile && <div className="environment-profile-info">
      <Tag color={profile.available && !failed ? "blue" : "gold"}>{profile.available && !failed ? t("Image available on API host", "API 主机镜像可用") : t("Image unavailable", "镜像不可用")}</Tag>
      <Typography.Paragraph className="muted">{t("This check covers the API host image only. It does not guarantee Worker availability or that the application can start. Those checks occur during execution.", "此检查仅反映 API 主机上的预制镜像，不保证 Worker 可用或应用能成功启动。执行时仍会检查。")}{profile.checked_at && ` ${t("Checked", "检查时间")}: ${formatDate(profile.checked_at)}`}</Typography.Paragraph>
      {!profile.available && <Typography.Paragraph>{t("Prepare the trusted image on the execution host, then refresh. This form cannot build images or install packages.", "请在执行主机准备可信镜像，再刷新。本表单不会构建镜像或安装软件包。")}</Typography.Paragraph>}
      <Dependencies values={profile.dependencies} />
    </div>}
    {selected === "python-api-v2" && <>
      <Alert type="info" showIcon message={t("Run an ASGI application inside the isolated Runner", "在隔离 Runner 内运行 ASGI 应用")} description={<>{t("Use an application object from the pinned repository, not an application factory. The service listens only inside the Runner at ", "使用固定仓库中的应用对象，不支持应用工厂。服务仅在 Runner 内监听 ")}<Typography.Text code>127.0.0.1:8765</Typography.Text>{t(". Tests use HYPERTEST_BASE_URL; this address is not a browser link or a host port. Service readiness does not mean tests passed.", "。测试通过 HYPERTEST_BASE_URL 访问；此地址不是浏览器入口，也不映射宿主端口。服务就绪不代表测试通过。")}</>} />
      <Typography.Paragraph className="muted">{t("API v2 ignores repository pytest configuration and conftest during generated-test collection. Generated modules must provide self-contained fixtures.", "API v2 收集生成测试时不加载仓库 pytest 配置与 conftest，生成模块必须自带所需 fixture。")}</Typography.Paragraph>
      <Form.Item required name="service_app" label={t("ASGI application object", "ASGI 应用对象")} extra={t("Use package.module:attribute from the pinned repository. ASCII Python identifiers only; no (), arguments or shell commands.", "填写固定仓库中的 package.module:attribute，只允许 ASCII Python 标识符，不接受 ()、参数或 Shell 命令。")} rules={[{ validator: async (_, value) => { if (!validServiceApp(value)) throw new Error(t("Enter an ASGI application such as api.main:app, up to 256 ASCII characters.", "请输入 api.main:app 形式的 ASGI 应用对象，最多 256 个 ASCII 字符。")); } }]}><Input placeholder="api.main:app" autoComplete="off" /></Form.Item>
      <Form.Item required name="service_health_path" label={t("Health path", "就绪检查路径")} extra={t("Use an existing readiness endpoint such as /health. No URL, query, fragment, percent encoding or traversal.", "填写应用已有的就绪检查端点，如 /health；不接受 URL、查询、片段、百分号编码或路径穿越。")} rules={[{ validator: async (_, value) => { if (!validHealthPath(value)) throw new Error(t("Enter a local absolute path, such as /health, up to 256 characters.", "请输入 /health 形式的本地绝对路径，最多 256 个字符。")); } }]}><Input placeholder="/health" autoComplete="off" maxLength={256} /></Form.Item>
      <Form.Item required name="service_startup_timeout_seconds" label={t("Service startup timeout (seconds)", "服务启动超时（秒）")} rules={[{ validator: async (_, value) => { if (!validStartupTimeout(value)) throw new Error(t("Enter a whole number from 1 to 120.", "请输入 1 至 120 的整数。")); } }]}><InputNumber min={1} max={120} style={{ width: "100%" }} /></Form.Item>
    </>}
  </>;
}

export function PinnedEnvironment({ definition }: { definition: unknown }) {
  const { t } = useI18n();
  if (definition === null || definition === undefined) return <Typography.Paragraph className="muted">{t("Legacy run: no controlled environment was pinned at creation. The actual environment is recorded with each execution.", "历史运行：创建时未固定受控环境。实际环境会分别记录在每次执行中。")}</Typography.Paragraph>;
  const safe = visibleEnvironmentDefinition(definition);
  if (!safe) return <Alert type="error" showIcon message={t("Pinned environment identity is unavailable", "无法读取固定环境身份")} description={t("Refresh the source snapshot or ask the operator to inspect the saved binding. Do not substitute another environment.", "请刷新源码快照，或由运维检查已保存绑定。不能替换为其他环境。")}/>;
  return <section className="pinned-environment">
    <Typography.Title level={5}>{t("Pinned execution environment", "固定执行环境")}</Typography.Title>
    <EnvironmentRequestSummary request={safe.request} />
    <Dependencies values={safe.dependencies} />
    <details className="environment-details"><summary>{t("Image and integrity identity", "镜像与完整性身份")}</summary><Descriptions bordered size="small" column={1} items={[
      { key: "image", label: t("Image ID", "镜像 ID"), children: <Typography.Text code copyable>{safe.image_id}</Typography.Text> },
      { key: "platform", label: t("Image platform", "镜像平台"), children: `${safe.image_os} / ${safe.image_architecture}` },
      { key: "lock", label: t("Dependency lock SHA-256", "依赖锁 SHA-256"), children: <Typography.Text code copyable>{safe.dependency_lock_sha256}</Typography.Text> },
      { key: "launcher", label: t("Launcher SHA-256", "启动器 SHA-256"), children: <Typography.Text code copyable>{safe.launcher_sha256}</Typography.Text> },
    ]} /></details>
  </section>;
}

export function ExecutionEnvironmentIdentity({ execution }: { execution: TestExecution }) {
  const { t } = useI18n();
  const identity = visibleExecutionIdentity(execution.spec);
  const knownIds = ["python-pytest-v1", "python-api-v1", "python-api-v2", "docker:python-pytest-v1", "docker:python-api-v1", "docker:python-api-v2", "docker:pytest", "local:pytest"];
  return <section className="execution-environment-identity">
    <Typography.Title level={4}>{t("Execution environment identity", "执行环境身份")}</Typography.Title>
    <Descriptions bordered size="small" column={1} items={[
      { key: "id", label: t("Environment", "环境"), children: execution.environment_id && knownIds.includes(execution.environment_id) ? execution.environment_id : t("Not available in this record", "此记录未提供可识别身份") },
      { key: "hash", label: t("Environment SHA-256", "环境 SHA-256"), children: safeHash(execution.environment_fingerprint) ? <Typography.Text code copyable>{execution.environment_fingerprint}</Typography.Text> : "—" },
      { key: "image", label: t("Actual image ID", "实际镜像 ID"), children: identity.image_id ? <Typography.Text code copyable>{identity.image_id}</Typography.Text> : "—" },
      { key: "network", label: t("External network", "外部网络"), children: identity.network === "none" ? t("Disabled", "已禁用") : t("Not provided", "未提供") },
    ]} />
    {identity.definition && <PinnedEnvironment definition={identity.definition} />}
    <Typography.Paragraph className="muted">{t("Service startup facts and logs are in the collected Evidence below. Service readiness is separate from test results.", "服务启动事实和日志请查看下方收集的证据。服务就绪与测试结果分别记录。")}</Typography.Paragraph>
  </section>;
}
