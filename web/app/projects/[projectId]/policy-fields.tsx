"use client";

import { Button, Form, Select, Space, Tag, Typography } from "antd";

import { useI18n } from "@/lib/i18n";
import type { TestType } from "@/lib/types";

export const testDimensions: TestType[] = ["FUNCTIONAL", "BOUNDARY", "NEGATIVE", "FAILURE", "CONCURRENCY", "CONSISTENCY", "COMPATIBILITY", "SECURITY", "PERFORMANCE", "RELIABILITY", "UPGRADE", "DATA", "RECOVERY"];
const categories = ["FUNCTIONAL", "BOUNDARY", "FAILURE", "CONCURRENCY", "CONSISTENCY", "COMPATIBILITY", "SECURITY", "PERFORMANCE", "RELIABILITY", "OBSERVABILITY", "UPGRADE", "DATA"];

export type PolicyFormValues = {
  coverage_default_dimensions: TestType[];
  coverage_by_category: Array<{ category: string; dimensions: TestType[] }>;
  blocking_severities: string[];
};

export function defaultPolicyValues(): PolicyFormValues {
  return { coverage_default_dimensions: ["FUNCTIONAL"], coverage_by_category: [], blocking_severities: ["BLOCKER", "CRITICAL"] };
}

export function compileFormPolicy(values: PolicyFormValues) {
  return {
    gate_version: "mvp/v1",
    gate: { blocking_finding_severities: values.blocking_severities },
    coverage: {
      version: "risk-design-policy/v1",
      default_dimensions: values.coverage_default_dimensions,
      by_category: Object.fromEntries(values.coverage_by_category.map((rule) => [rule.category, rule.dimensions])),
    },
  };
}

export function PolicyFields() {
  const { t, label } = useI18n();
  const form = Form.useFormInstance<PolicyFormValues>();
  const rules: PolicyFormValues["coverage_by_category"] = Form.useWatch("coverage_by_category", form) || [];
  const dimensionOptions = testDimensions.map((value) => ({ value, label: label(value) }));

  return <>
    <Typography.Paragraph className="muted">
      {t("Choose the test dimensions required by this run. HyperTest evaluates these rules and fixes them in the run's policy snapshot.", "选择本次测试运行要求的测试维度。HyperTest 按规则评估覆盖，并将策略固定在不可变快照中。")}
    </Typography.Paragraph>
    <Form.Item
      name="coverage_default_dimensions"
      label={t("Dimensions required for every risk", "所有风险都必须覆盖的维度")}
      rules={[{ required: true, type: "array", min: 1, message: t("Select at least the functional dimension.", "至少保留功能测试维度。") }]}
      extra={t("Functional coverage is always required. These shared dimensions apply to every risk category.", "功能测试始终必需；这里选择的共享维度适用于所有风险类别。")}
    >
      <Select mode="multiple" optionFilterProp="label" placeholder={t("Select shared test dimensions", "选择共享测试维度")} options={dimensionOptions.map((option) => ({ ...option, disabled: option.value === "FUNCTIONAL" }))} />
    </Form.Item>
    <Typography.Title level={5}>{t("Category rules", "按风险类别补充规则")}</Typography.Title>
    <Typography.Paragraph className="muted">
      {t("Without an override, concurrency risks also require concurrency tests and reliability risks require recovery tests. A category rule replaces that category's additional dimensions; shared dimensions still apply.", "未单独配置时，并发风险还需并发测试，可靠性风险还需恢复测试。类别规则会替换该类别的附加维度；共享维度始终保留。")}
    </Typography.Paragraph>
    <Form.List name="coverage_by_category" rules={[{
      validator: async (_, values: PolicyFormValues["coverage_by_category"] = []) => {
        const chosen = values.map((rule) => rule?.category).filter(Boolean);
        if (chosen.length !== new Set(chosen).size) throw new Error(t("Each risk category can have only one rule.", "每个风险类别只能配置一条规则。"));
      },
    }]}>
      {(fields, { add, remove }, { errors }) => <>
        {fields.map((field) => <div key={field.key} className="policy-rule">
          <Form.Item name={[field.name, "category"]} label={t(`Risk category ${field.name + 1}`, `风险类别 ${field.name + 1}`)} rules={[{ required: true, message: t("Choose a risk category.", "请选择风险类别。") }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t("Choose a risk category", "选择风险类别")}
              options={categories.map((value) => ({ value, label: label(value), disabled: rules.some((rule, index) => index !== field.name && rule?.category === value) }))}
            />
          </Form.Item>
          <Form.Item
            name={[field.name, "dimensions"]}
            label={t(`Additional dimensions ${field.name + 1}`, `附加维度 ${field.name + 1}`)}
            rules={[{ validator: async (_, value) => { if (!Array.isArray(value)) throw new Error(t("Choose the additional dimensions.", "请选择附加测试维度。")); } }]}
            extra={t("An empty list means shared dimensions only; it removes this category's baseline additions.", "留空表示只要求共享维度，并移除该类别默认的附加维度。")}
          >
            <Select mode="multiple" optionFilterProp="label" options={dimensionOptions} placeholder={t("Shared dimensions only, or select additions", "只使用共享维度，或选择附加维度")} />
          </Form.Item>
          <Button danger type="link" onClick={() => remove(field.name)} aria-label={t(`Remove category rule ${field.name + 1}`, `移除类别规则 ${field.name + 1}`)}>{t("Remove rule", "移除规则")}</Button>
        </div>)}
        <Form.ErrorList errors={errors} />
        <Button type="dashed" disabled={fields.length >= categories.length} onClick={() => add({ dimensions: [] })} style={{ marginBottom: 24 }}>{t("Add category rule", "添加类别规则")}</Button>
      </>}
    </Form.List>
    <Form.Item
      name="blocking_severities"
      label={t("Confirmed product defects that block release", "哪些已确认产品缺陷会阻止发布")}
      rules={[{ required: true, type: "array", min: 1, message: t("Select at least the blocker severity.", "至少保留阻断级缺陷。") }]}
      extra={t("Blocker defects always block release. Official execution and verified evidence are still required.", "阻断级缺陷始终阻止发布；正式执行和可信证据等其他门禁要求仍然有效。")}
    >
      <Select mode="multiple" optionFilterProp="label" placeholder={t("Select blocking severities", "选择阻断发布的严重程度")} options={["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"].map((value) => ({ value, label: label(value), disabled: value === "BLOCKER" }))} />
    </Form.Item>
  </>;
}

export function PolicyReview({ values }: { values: PolicyFormValues }) {
  const { t, label } = useI18n();
  return <Space direction="vertical" size={8}>
    <Typography.Text strong>{t("Pinned quality policy", "本次固定的质量策略")}</Typography.Text>
    <span>{t("Every risk: ", "所有风险：")}{values.coverage_default_dimensions.map((value) => <Tag key={value}>{label(value)}</Tag>)}</span>
    {values.coverage_by_category.length ? values.coverage_by_category.map((rule) => <span key={rule.category}>
      {label(rule.category)}：{rule.dimensions.length ? rule.dimensions.map((value) => <Tag key={value}>{label(value)}</Tag>) : <Typography.Text className="muted">{t("Shared dimensions only", "仅共享维度")}</Typography.Text>}
    </span>) : <Typography.Text className="muted">{t("Category-specific platform baseline.", "使用各风险类别的默认附加维度。")}</Typography.Text>}
    <span>{t("Release-blocking severities: ", "阻止发布的缺陷级别：")}{values.blocking_severities.map((value) => <Tag key={value}>{label(value)}</Tag>)}</span>
  </Space>;
}
