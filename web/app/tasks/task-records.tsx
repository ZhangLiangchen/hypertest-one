"use client";

import { Tag } from "antd";
import { useI18n } from "@/lib/i18n";
import type { ReportedResult } from "@/lib/types";

export function ReportedResultTag({ result }: { result: ReportedResult }) {
  const { label } = useI18n();
  return <Tag color={result === "PASS" ? "green" : ["FAIL", "ERROR"].includes(result) ? "red" : ["BLOCKED", "UNKNOWN"].includes(result) ? "gold" : undefined}>{label(result)}</Tag>;
}
