---
name: HyperTest One
description: A traceable testing workspace for daily quality decisions.
colors:
  primary: "#2563eb"
  primary-hover: "#1d4ed8"
  primary-active: "#1e40af"
  nav-indicator: "#22d3ee"
  shell: "#0f172a"
  canvas: "#f3f6fb"
  surface: "#ffffff"
  ink: "#172338"
  muted: "#526177"
  line: "#d8e1ee"
  control-border: "#8190a5"
  placeholder: "#5f6f85"
  selected: "#e9f0ff"
  tab-selected: "#dfe9ff"
  trail: "#edf2fa"
  focus: "#2563eb"
  info: "#0e7490"
  info-bg: "#e7f6fb"
  info-border: "#8cc6d8"
  success: "#22734c"
  warning: "#94620b"
  error: "#b53f40"
  danger-ink: "#a53338"
  warning-ink: "#805507"
  success-tag-ink: "#20613d"
  success-tag-bg: "#edf7ef"
  danger-tag-bg: "#fff1ef"
  warning-tag-bg: "#fff8df"
  info-tag-ink: "#225d83"
  info-tag-bg: "#edf5fb"
  danger-surface: "#fff8f7"
  warning-surface: "#fffcf3"
  table-header: "#f1f5fb"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-0.03em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "25px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
  reading:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "13px"
    lineHeight: 1.8
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
  identifier:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "11px"
    lineHeight: 1.7
  artifact:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "12px"
    lineHeight: 1.8
rounded:
  control: "6px"
  compact-surface: "8px"
  surface: "10px"
  modal: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  compact: "12px"
  md: "16px"
  panel-compact: "20px"
  panel: "24px"
  section: "28px"
  lg: "32px"
  page: "36px"
  wide: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-active:
    backgroundColor: "{colors.primary-active}"
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
  navigation:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.surface}"
    height: "64px"
  tag-success:
    backgroundColor: "{colors.success-tag-bg}"
    textColor: "{colors.success-tag-ink}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "22px 24px"
  run-section-selected:
    backgroundColor: "{colors.tab-selected}"
    textColor: "{colors.primary-active}"
    rounded: "{rounded.control}"
    padding: "11px 14px"
  evidence-trail:
    backgroundColor: "{colors.trail}"
    textColor: "{colors.ink}"
    rounded: "{rounded.compact-surface}"
---

# Design System: HyperTest One

## Overview

**Creative North Star: "The Testing Reference Index"**

HyperTest One uses a deep navy navigation shell, electric blue actions, cool neutral fields and white work surfaces to make testing records easy to locate and read. The modern technical character comes from precise contrast and a restrained cyan navigation indicator. The reference-index structure remains grounded in consistent identifiers, aligned lists and selected sections. Selected run sections pair darker blue text with pale blue surfaces, and keyboard focus retains a strong accent outline through both authored CSS and the component-library theme.

Daily operation determines the density. Actions have clear hierarchy, supporting metadata stays quiet, and a decision remains close to its reason and evidence. System fonts are a deliberate reading choice for this operating workspace; there is no separate display face or promotional type treatment.

**Key Characteristics:**
- Navy shell, electric blue actions and flat white work surfaces.
- Compact, readable Chinese and English typography.
- Traceable identifiers and adjacent evidence links.
- Explicit unknown, pending, error and recorded-result states.

## Colors

The palette combines electric blue actions, a deep navy shell and cool neutral surfaces with conventional semantic state colors. Frontmatter values are normative; Ant Design's theme and `web/app/globals.css` are the implementation sources.

### Primary
- **Electric Blue** (`primary`, `primary-hover`, `primary-active`): primary actions, links, caret, visible focus and the risk-identification progress line; hover and active colors are explicitly configured in the Ant theme.
- **Midnight Navy** (`shell`): persistent application header, keeping navigation distinct from work content; the authored SVG favicon uses the same shell color.
- **Cool Blue Fields** (`selected`, `tab-selected`, `trail`): selected and connected working areas; preserve the observed distinction between selection and evidence-navigation surfaces.

### Secondary
- **Information Teal** (`info`, `info-bg`, `info-border`): informational messages and test-design progress; keep it distinct from primary action blue.
- **Signal Cyan** (`nav-indicator`): the current global navigation underline only; it is not a body-text, button or success color.

### Neutral
- **Cool Canvas** (`canvas`) and **White Surface** (`surface`): page field and work containers.
- **Slate Ink** (`ink`), **Quiet Ink** (`muted`) and **Placeholder Ink** (`placeholder`): content, supporting text and input hints.
- **Surface Line** (`line`) and **Control Line** (`control-border`): structural separation and form boundaries.

### Named Rules
**The Signal Cyan Rule.** Reserve bright cyan for the current global navigation indicator; retain green, red and amber for their established semantic states.

**The State Has Words Rule.** Color reinforces a written status and, where present, an icon. An accent color or completed workflow never supplies a quality verdict.

Semantic tags use darker foregrounds than the default Ant presets. Green, red and blue tags were measured at 6.75:1, 6.10:1 and 6.43:1 against their rendered backgrounds in the acceptance capture. Gold and volcano are also explicitly overridden. Keep the `html .ant-tag.ant-tag-*` selector specificity so Ant's preset rules do not silently restore lighter text. These measurements do not certify every component or state.

## Typography

**Headline and Body Font:** platform system sans with explicit Chinese fallbacks, as recorded above.
**Label/Mono Font:** SFMono-Regular, Consolas, Liberation Mono, monospace for keys and artifact content.

**Character:** restrained hierarchy for repeated scanning and extended reading. Identifiers distinguish immutable records without competing with human-readable names; numerical counts use tabular figures.

### Hierarchy
- **Headline:** page title; reduces to 25px at the mobile breakpoint.
- **Title:** quality decision; reduces to 23px on mobile. Section headings use 14–17px at weight 600, according to their position.
- **Body:** Ant Design's base reading and control size. Longer decision and task text uses the `reading` role, with reasons capped at 72ch.
- **Label:** table headers, filters, metadata and evidence navigation. Compact supporting record labels sometimes use 11px.
- **Identifier / Artifact:** keys and logs; preserve original text, line breaks and wrapping. Artifact content scrolls within a bounded viewport rather than expanding the entire page.

## Layout

The shared shell has a sticky header and a centered content container capped at 1460px, with 40px side gutters on large screens. Desktop content padding is 36px above and 56px below; above 1600px, top padding becomes 40px. The spacing vocabulary combines small 4–16px control gaps with 20–28px panel and section separation; it is not an enforced single-step grid.

Navigation progresses from Projects to a project's runs to one run. Context links preserve that hierarchy. Run sections use a 160px left index at Ant's `lg` breakpoint (992px upward); below it, tabs move above content and use the component library's horizontal overflow controls. Overview groups use a 1.25:1 split with 20px or 24px gaps, tightening to 16px below 1200px. Dense tables own horizontal scrolling rather than forcing the page wider.

At 991px and below, gutters become 20px and top padding 28px. At 640px and below, gutters become 16px, top padding 24px and the header 60px; heading actions stack, overview panels become a single column and the four evidence links become a two-by-two grid. Coverage counts compact into a full-width row above the measures. Supporting workflow labels disappear below 1200px; the main header navigation hides on mobile while the brand home link and page context links remain accessible. Detail content wraps long keys, URLs and hashes.

**The Action Hierarchy Rule.** Keep the complete testing cycle as the principal run action; group secondary planning, execution, gate and input actions in the existing More actions disclosure.

## Elevation & Depth

Work surfaces are flat, separated by a pale canvas, white fill and thin borders. Primary and default buttons explicitly remove their library shadows. The header uses position and color for hierarchy; its selected link uses a two-pixel inset underline. Modals, drawers and menus retain the component library's overlay behavior; no independent custom shadow scale is defined for them.

## Shapes

Controls and selected tabs use the control radius. Compact strips, table wrappers, alerts and avatars use the compact-surface radius; major work panels use the surface radius and modals use the modal radius. Borders are normally one pixel. The evidence trail clips to its outer radius while its internal buttons remain square, creating one connected strip.

## Components

### Buttons
Primary actions use electric blue with white text, medium weight (500) and the shared control height. Default actions stay white with a control border; link and text variants retain Ant Design behavior. Loading and disabled states block duplicate work while preserving context. Hover and active treatments use the explicitly configured `primary-hover` and `primary-active` tokens; link variants share those configured colors.

### Inputs / Fields
Use labeled Ant inputs and selects, vertical form layout, readable placeholder ink and visible validation messages. Keep drafts on the current page when dialogs close. Creation runs through source, requirements, policy and review steps; switch languages without clearing the draft, original PRD or step. Invalid submission focuses the first failing field. Pending mutations guard dismissal and repeated submission as the existing forms do.

### Chips
Tags wrap rather than truncate, and always show a status label. Green, red, gold, blue/geekblue and volcano use the explicit semantic overrides; neutral tags serve metadata and states that do not imply success. Do not equate a verified evidence tag with a passing run.

### Cards / Containers
White, bordered work containers use the shared surface radius, usually 20–24px internal spacing. Danger and warning decision panels add a subtle semantic fill and border. Table headings are lightly tinted; records use modest dividers and tabular counts. Empty, loading and failed reads occupy the same region as their eventual content and offer a relevant next action or retry.

### Navigation
The brand returns home; the header identifies project/run context and exposes guide and language controls. Current global navigation uses `aria-current`. Run tabs use the darker `primary-active` token for selected and active text, and `primary-hover` for hover text. The selected text sits on the `tab-selected` surface; preserve this pairing rather than using the brighter action blue on the tinted background. Run tabs retain selection per run in session storage and through language changes; evidence shortcuts select the relevant section and focus its selected tab. Keep native/library tab keyboard behavior, including Home/End and Enter activation. Section details open in drawers so users retain run context.

### Decision and evidence trail
The lead decision is the highest-sequence verdict whose status is `FINAL` and scope is `TEST_RUN`. Draft, revoked and narrower verdicts remain in history. With no eligible verdict, show waiting or unavailable text; task completion never substitutes for a decision. Historical execution failures may precede the current verdict and must retain that distinction.

The evidence trail links to executions, findings, evidence and verdicts, carrying counts or a dash when no data has loaded. Unknown coverage is labeled Unknown rather than displayed as zero. Failed refreshes retain loaded records with a retry warning. Agent activity remains supporting information; trusted execution and evidence provide formal facts.

### Accessibility and motion
Maintain a skip link, visible keyboard focus, accessible control names, semantic headings and written statuses in both languages. The shared focus outline uses the primary accent at three pixels with a three-pixel offset. The authored `:focus-visible` rule uses `var(--ht-accent)`. Ant Design receives the same primary accent through `colorPrimaryBorder`, which its focus-outline generator uses for component controls; preserve this theme token so library buttons and tabs retain the strong outline. Long overview descriptions may be clamped, but their detail links must retain the full content path. Do not claim an unverified accessibility conformance level.

The authored selected-tab background transition is 160ms ease-out and is disabled by the reduced-motion media query. Run tab pane animation is explicitly disabled. `providers.tsx` listens to `matchMedia('(prefers-reduced-motion: reduce)')` and switches Ant Design's motion token, including when the preference changes. Global CSS does not blanket-disable third-party animations; retain the provider-level handling so overlay lifecycle behavior stays intact.

## Do's and Don'ts

### Do:
- **Do** use the navy shell, electric blue actions, white surfaces and existing spacing roles for new operating pages.
- **Do** keep decisions, reasons, record identity and evidence reachable in one reading path.
- **Do** preserve bilingual drafts, selected run sections, loaded results and immutable history during updates.
- **Do** pair state color with readable labels and preserve visible keyboard focus.
- **Do** distinguish unknown, unavailable, zero, task completion and formal quality decisions.

### Don't:
- **Don't** infer release readiness from task success, coverage counts or an Agent report.
- **Don't** let dense tables or long identifiers create whole-page horizontal overflow.
- **Don't** replace explicit semantic tag overrides with lower-specificity preset styling.
- **Don't** add decorative textures, neon body text or promotional display typography to this operating workspace.
- **Don't** ship synthetic acceptance records in product routes or present frontend fixture checks as a real testing cycle.
