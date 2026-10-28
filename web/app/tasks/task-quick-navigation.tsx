"use client";

import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";

export type TaskNavigationItem = { id: string; label: string; count?: number; history?: boolean };

export function TaskQuickNavigation({ items }: { items: TaskNavigationItem[] }) {
  const { t } = useI18n();
  const navigation = useRef<HTMLElement>(null);
  const initialAnchor = useRef(true);
  const sectionIds = items.map((item) => item.id).join("|");
  const [activeId, setActiveId] = useState(items[0]?.id);

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
    <ul>{items.map((item) => <li key={item.id} className={item.history ? "task-quick-navigation-history" : undefined}>
      <a href={`#${item.id}`} aria-current={activeId === item.id ? "location" : undefined} onClick={() => setActiveId(item.id)}>
        <span>{item.label}</span>{item.count !== undefined ? <span className="task-quick-navigation-count">{item.count}</span> : null}
      </a>
    </li>)}</ul>
  </nav>;
}
