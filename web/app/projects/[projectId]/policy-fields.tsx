"use client";

import { Button, Form, Select, Space, Tag, Typography } from "antd";

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
  return <>
    <Typography.Paragraph className="muted">Choose the test dimensions required by this run. HyperTest evaluates these rules deterministically and fixes them in the run's policy snapshot.</Typography.Paragraph>
    <Form.Item name="coverage_default_dimensions" label="Dimensions required for every risk" rules={[{ required: true, type: "array", min: 1 }]} extra="FUNCTIONAL is always required. The selected dimensions apply to every risk category.">
      <Select mode="multiple" options={testDimensions.map((value) => ({ value, label: value, disabled: value === "FUNCTIONAL" }))} />
    </Form.Item>
    <Typography.Title level={5}>Category rules</Typography.Title>
    <Typography.Paragraph className="muted">An unconfigured category keeps the platform baseline, such as CONCURRENCY for concurrency risks and RECOVERY for reliability risks. A category rule replaces that category's additional dimensions; the dimensions required for every risk still apply.</Typography.Paragraph>
    <Form.List name="coverage_by_category" rules={[{
      validator: async (_, values: PolicyFormValues["coverage_by_category"] = []) => {
        const chosen = values.map((rule) => rule?.category).filter(Boolean);
        if (chosen.length !== new Set(chosen).size) throw new Error("Each risk category can have only one rule.");
      },
    }]}>
      {(fields, { add, remove }, { errors }) => <>
        {fields.map((field) => <div key={field.key} className="policy-rule">
          <Form.Item name={[field.name, "category"]} label={`Risk category ${field.name + 1}`} rules={[{ required: true, message: "Choose a risk category." }]}>
            <Select options={categories.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name={[field.name, "dimensions"]} label={`Additional dimensions ${field.name + 1}`} rules={[{ validator: async (_, value) => { if (!Array.isArray(value)) throw new Error("Choose the additional dimensions."); } }]} extra="Multiple dimensions are supported. Select an empty list only when the shared dimensions are sufficient.">
            <Select mode="multiple" options={testDimensions.map((value) => ({ value, label: value }))} placeholder="Choose required test dimensions" />
          </Form.Item>
          <Button danger type="link" onClick={() => remove(field.name)} aria-label={`Remove category rule ${field.name + 1}`}>Remove rule</Button>
        </div>)}
        <Form.ErrorList errors={errors} />
        <Button type="dashed" disabled={fields.length >= categories.length} onClick={() => add({ dimensions: [] })} style={{ marginBottom: 24 }}>Add category rule</Button>
      </>}
    </Form.List>
    <Form.Item name="blocking_severities" label="Confirmed product defects that block release" rules={[{ required: true, type: "array", min: 1 }]} extra="BLOCKER always blocks release. All other execution and verified-evidence requirements remain in force.">
      <Select mode="multiple" options={["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"].map((value) => ({ value, label: value, disabled: value === "BLOCKER" }))} />
    </Form.Item>
  </>;
}

export function PolicyReview({ values }: { values: PolicyFormValues }) {
  return <Space direction="vertical" size={8}>
    <Typography.Text strong>Pinned quality policy</Typography.Text>
    <span>Every risk: {values.coverage_default_dimensions.map((value) => <Tag key={value}>{value}</Tag>)}</span>
    {values.coverage_by_category.length ? values.coverage_by_category.map((rule) => <span key={rule.category}>{rule.category}: {rule.dimensions.map((value) => <Tag key={value}>{value}</Tag>)}</span>) : <Typography.Text className="muted">Category-specific platform baseline.</Typography.Text>}
    <span>Release-blocking severities: {values.blocking_severities.map((value) => <Tag key={value}>{value}</Tag>)}</span>
  </Space>;
}
