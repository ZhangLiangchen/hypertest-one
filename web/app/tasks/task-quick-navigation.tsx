"use client";

import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";
import type { SessionTaskDetail } from "@/lib/types";

export function TaskQuickNavigation({ detail }: { detail: SessionTaskDetail }) {
  const { t } = useI18n();
  const navigation = useRef<HTMLElement>(null);
  const initialAnchor = useRef(true);
  const items = [
    { id: "task-collaboration", label: t("Session collaboration", "会话协作") },
    { id: "task-overview", label: t("Task overview", "任务概览") },
    { id: "task-plan", label: t("Test plan", "测试计划") },
    { id: "task-cases", label: t("Test cases", "测试用例"), count: detail.cases.length },
    { id: "task-reports", label: t("Original test reports", "原始测试报告"), count: detail.reports.length },
    ...((detail.binding_history?.length || 0) > 0
      ? [{ id: "task-binding-history", label: t("Binding history", "会话绑定历史") }] : []),
    { id: "task-management", label: t("Management history", "管理历史") },
    { id: "task-sync", label: t("Sync history", "同步历史") },
  ];
  const sectionIds = items.map((item) => item.id).join("|");
  const [activeId, setActiveId] = useState(items[0].id);

  useEffect(() => {
    const sections = sectionIds.split("|").map((id) => document.getElementById(id)).filter((section): section is HTMLElement => Boolean(section));
    const offset = Number.parseFloat(getComputedStyle(navigation.current!).top);
    // Task content arrives after the route shell, including on a direct hash URL.
    if (initialAnchor.current) {
      sections.find((section) => `#${section.id}` === window.location.hash)?.scrollIntoView({ block: "start" });
      initialAnchor.current = false;
    }
    const update = () => {
      const last = sections.at(-1);
      const current = last && last.getBoundingClientRect().bottom <= window.innerHeight
        ? last : sections.find((section) => section.getBoundingClientRect().bottom > offset + 1);
      if (current) setActiveId(current.id);
    };
    const observer = new IntersectionObserver(update, { rootMargin: `-${offset}px 0px 0px 0px`, threshold: [0, 1] });
    sections.forEach((section) => observer.observe(section));
    update();
    return () => observer.disconnect();
  }, [sectionIds]);

  return <nav ref={navigation} className="task-quick-navigation" aria-labelledby="task-quick-navigation-heading">
    <h2 id="task-quick-navigation-heading">{t("Quick navigation", "快速导航")}</h2>
    <ul>{items.map((item) => <li key={item.id} className={item.id === "task-binding-history" || item.id === "task-management" && !detail.binding_history?.length ? "task-quick-navigation-history" : undefined}>
      <a href={`#${item.id}`} aria-current={activeId === item.id ? "location" : undefined} onClick={() => setActiveId(item.id)}>
        <span>{item.label}</span>{"count" in item ? <span className="task-quick-navigation-count">{item.count}</span> : null}
      </a>
    </li>)}</ul>
  </nav>;
}
