---
name: HyperTest One
description: A quiet testing workspace with floating navigation and stable, traceable records.
colors:
  primary: "#2563eb"
  primary-hover: "#1d4ed8"
  primary-active: "#1e40af"
  canvas: "#f2f5fa"
  surface: "#ffffff"
  shell: "#f6f9ff"
  glass-top: "#fcfdff"
  glass-bottom: "#f4f7fc"
  ink: "#172338"
  muted: "#526177"
  line: "#dce3ed"
  control-border: "#8190a5"
  placeholder: "#5f6f85"
  navigation-selected: "#e4ecfb"
  tab-selected: "#e0eafb"
  workspace-selected: "#e9f0ff"
  segmented-track: "#edf1f7"
  trail: "#edf2fa"
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
  warning-border: "#e7ddc2"
  table-header: "#f7f9fc"
  table-hover: "#f3f7ff"
  contrast-muted: "#34445c"
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
  overlay-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "18px"
    letterSpacing: "-0.02em"
  section:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.45
    letterSpacing: "-0.02em"
  subsection:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "17px"
    lineHeight: 1.5
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
  control: "10px"
  compact-surface: "8px"
  surface: "16px"
  modal: "20px"
  drawer: "20px"
  navigation: "22px"
  navigation-compact: "18px"
  section: "12px"
  tag: "6px"
  artifact: "6px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  compact: "12px"
  md: "16px"
  panel-compact: "20px"
  panel: "24px"
  section: "28px"
  lg: "32px"
  wide: "40px"
  page-bottom: "64px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-active:
    backgroundColor: "{colors.primary-active}"
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "38px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "38px"
  navigation:
    textColor: "{colors.ink}"
    rounded: "{rounded.navigation}"
    height: "68px"
  navigation-solid:
    backgroundColor: "{colors.shell}"
  tag-success:
    backgroundColor: "{colors.success-tag-bg}"
    textColor: "{colors.success-tag-ink}"
    rounded: "{rounded.tag}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "24px"
  modal:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.modal}"
    padding: "28px"
  run-section-selected:
    backgroundColor: "{colors.tab-selected}"
    textColor: "{colors.primary-active}"
    rounded: "{rounded.section}"
    padding: "11px 14px"
  evidence-trail:
    backgroundColor: "{colors.trail}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "4px"
  project-navigation:
    textColor: "{colors.muted}"
    rounded: "{rounded.navigation-compact}"
    padding: "6px"
  project-navigation-selected:
    backgroundColor: "{colors.navigation-selected}"
    textColor: "{colors.primary-active}"
    rounded: "{rounded.section}"
    padding: "11px 18px"
  workspace-tab-selected:
    backgroundColor: "{colors.workspace-selected}"
    textColor: "{colors.primary-active}"
    padding: "10px 16px"
  table-cell:
    padding: "16px 20px"
  warning-notice:
    backgroundColor: "{colors.warning-surface}"
    textColor: "{colors.warning-ink}"
    rounded: "{rounded.compact-surface}"
---

# Design System: HyperTest One

## Overview

**Creative North Star: "The Floating Testing Reference Index"**

HyperTest One places a quiet, floating control plane above stable testing records. Pale cool canvas, white reading surfaces, graphite text and one blue action accent keep daily QA work clear. Static glass navigation gains definition from an opaque light gradient, an inner highlight and a soft downward shadow; aligned records, immutable identifiers and adjacent evidence retain the reference-index structure.

The material direction adapts Apple's [Liquid Glass overview](https://developer.apple.com/documentation/TechnologyOverviews/liquid-glass), [Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/) and [Get to know the new design system](https://developer.apple.com/videos/play/wwdc2025/356/) to the existing web workspace. The reusable principles are separation between navigation and content, related corner geometry, restrained interaction feedback and legibility across user preferences. The implementation preserves the Liquid Glass hierarchy with an opaque static CSS gradient and two shadow layers. Navigation does not sample or blur scrolling content; native optical refraction is not implemented. [ReportPortal's test-execution workspace](https://reportportal.io/docs/test-executions/) is the reference for table-oriented inspection, visible filters and adjacent record actions; HyperTest retains its own task and result semantics.

Daily operation on PC wide screens determines density and typography. A decision stays close to its reason and evidence, supporting metadata stays readable, and Chinese and English receive the same hierarchy. These rules describe the current checkout's shared stylesheet, Ant Design provider and application components across the eight workspace routes. HyperTest One implements and supports PC wide-screen interfaces only; mobile and portrait compatibility are outside the product scope. Product and canonical-state semantics remain governed by PRODUCT.md and the four foundational specifications.

**Key Characteristics:**
- Floating light navigation with an opaque static gradient and two shadow layers.
- Opaque records, forms, decisions and evidence on a pale cool canvas.
- Related rounded geometry, capsule primary actions and quiet control feedback.
- Readable Chinese and English, stable drafts and explicit unknown or recorded-result states.

## Colors

Electric blue supplies action emphasis; pale cool neutrals separate navigation from records. Frontmatter values are normative. Implementation sources are `web/app/globals.css` and `web/app/providers.tsx`.

### Primary
- **Electric Blue** (`primary`, `primary-hover`, `primary-active`): primary actions, links, caret and keyboard focus. Selected navigation uses the darker active ink on a pale blue fill.
- **Cool Navigation Fields** (`navigation-selected`, `tab-selected`, `workspace-selected`, `trail`): current global/project navigation, selected run section, workspace tabs and the connected evidence strip. Preserve their individual roles. Segmented controls use their own neutral track.

### Secondary
- **Information Teal** (`info`, `info-bg`, `info-border`): informational messages and test-design progress.
- **Recorded State Colors** (`success`, `warning`, `error`): established semantic feedback, reinforced by written labels. Danger and warning decisions use their dedicated ink and opaque surface tokens. Shared warning notices also use the warning surface, border and ink roles, keeping extended explanations readable.
- **Semantic Tag Colors** (`success-tag-*`, `danger-tag-bg`, `warning-tag-bg`, `info-tag-*`): readable foregrounds on restrained state fills. Red and gold tags use the corresponding danger and warning ink tokens; volcano also retains its explicit authored override.

### Neutral
- **Cool Canvas** (`canvas`), **White Surface** (`surface`) and **Table Fields** (`table-header`, `table-hover`): page ground, records and table states. Two shallow cool radial gradients add ambient light near the page top.
- **Static Glass Light** (`glass-top`, `glass-bottom`) and **Solid Light** (`shell`): opaque gradient endpoints for navigation and the plain fill used for stronger contrast. The gradient itself lives in the sidecar material extension, outside the color-token schema.
- **Slate Ink** (`ink`), **Quiet Ink** (`muted`) and **Placeholder Ink** (`placeholder`): primary content, readable explanations and input hints. Ant Design receives Quiet Ink through both `colorTextSecondary` and `colorTextDescription`, covering form help, counters, optional marks and guide-step descriptions.
- **Surface Line** (`line`) and **Control Line** (`control-border`): thin structure and visible form boundaries. Higher-contrast preferences strengthen lines with Control Line and change the CSS muted token to `contrast-muted`.

### Named Rules
**The State Has Words Rule.** Color reinforces a written status and, where present, an icon. An accent color or completed workflow never supplies a quality verdict.

Keep the `html .ant-tag.ant-tag-*` selector specificity so Ant preset rules do not silently restore lighter text. Readable descriptions belong to the muted ink role; disabled controls retain their separate component-library state.

## Typography

**Headline and Body Font:** platform system sans with explicit Chinese fallbacks, as recorded in frontmatter.
**Label/Mono Font:** SFMono-Regular, Consolas, Liberation Mono, monospace for keys and artifact content.

**Character:** compact hierarchy for repeated scanning and extended reading. Identifiers distinguish immutable records without competing with human-readable names; numerical counts and table values use tabular figures.

### Hierarchy
- **Headline:** the single page title in the shared workspace heading.
- **Title:** quality decision. Existing compact overview labels retain their local hierarchy.
- **Overlay Title:** modal and drawer title, with modest negative tracking.
- **Section / Subsection:** shared panel headings and nested form sections. Ant Card headings use the subsection size; shared section headings are the stronger panel level.
- **Body:** Ant Design's base reading and control size. Longer decision and task text uses the reading role; decision reasons are capped at a readable measure (72ch).
- **Label:** table headers, filters, metadata and evidence navigation. Compact supporting record labels sometimes use smaller type (11px).
- **Identifier / Artifact:** keys and logs; preserve original text, line breaks and wrapping. Artifact content scrolls within a bounded viewport (65vh).

## Layout

The sticky header floats above the page with a separate inset: desktop height (68px), top offset and margin (16px), side gutters (24px), maximum width (1460px) and horizontal padding (22px). Its desktop corner is larger than the contained controls. The centered content container has its own maximum width (1400px), side gutters (48px), top padding (40px) and bottom padding (64px).

Navigation progresses from Projects to a project workspace to a Local task, Cloud task or legacy run. Project navigation keeps Local tasks, Cloud testing and Project experience adjacent while preserving their separate identities. On the desktop run workbench, sections use a left index (180px wide, 8px inner padding) separated from pane content by a gap (24px). Overview groups use a proportional split (1.25:1), with normal gaps (20px or 24px). Dense tables own horizontal scrolling; long identifiers wrap inside their content region.

Shared workspace headings align a title and description with a trailing action group, separated by a gap (24px). Description text has a readable measure (75ch); metadata sits below the title row with its own spacing (18px top margin, 8px by 16px gaps). The project navigation is a content-width floating strip with an inner inset (6px) and section separation (28px below). Shared panel stacks and adjacent workspace panels keep a clear gap (24px), including the project-experience search and records panels.

Task creation uses a centered form width (1040px). Repository pairs use equal columns and a gap (24px); form sections use vertical separation (24px) with fine dividers, and actions have their own top rule. Form items keep the same vertical rhythm (24px). Description blocks use readable label fields, a title separation (20px) and item spacing (16px).

The supported operating context is PC wide screens only. This is a permanent product constraint for all pages, components, interactions, layouts and regression checks. Mobile and portrait layouts, compatibility logic, screenshots and test matrices are not required. Existing narrow-screen media queries are retained legacy CSS, not a declaration of supported operating contexts or a compatibility maintenance requirement.

The spacing vocabulary combines small control gaps with comfortable panel and section separation; it is not a mandatory single-step grid. Typical workspace panel padding is the panel step, shared through the stylesheet's panel spacing token. Textarea counters reserve a separate bottom line (24px margin) before explanatory Form.Item text. Preserve that reservation when adding counted fields.

**The Action Hierarchy Rule.** Keep the complete testing cycle as the principal run action; group secondary planning, execution, gate and input actions in the existing More actions disclosure.

## Elevation & Depth

Depth belongs to navigation and immediate control feedback. Header, project navigation and run-section navigation share an opaque static light gradient, a fine inner highlight and a diffuse downward shadow. White content surfaces use fill and a thin border without an added ambient shadow. Primary buttons have a small colored shadow at rest and a slightly larger hover shadow; default buttons retain no resting shadow. Modals, drawers and menus use their library overlay behavior.

### Shadow Vocabulary
- **Navigation glass:** `var(--ht-glass-shadow)` — `0 6px 22px rgb(34 58 98 / 8%), inset 0 1px 0 rgb(255 255 255 / 96%)`.
- **Primary action, rest:** `0 3px 8px rgb(37 99 235 / 16%)`.
- **Primary action, hover:** `0 5px 14px rgb(37 99 235 / 22%)`.
- **Navigation hover:** `0 2px 7px rgb(34 58 98 / 7%)`.
- **Selected run section:** `inset 0 1px 0 rgb(255 255 255 / 90%), 0 2px 5px rgb(34 58 98 / 5%)`.

**The Navigation Material Rule.** Use the same opaque static gradient and two shadow layers on the shared header, project navigation and run-section navigation. Do not apply live backdrop filtering. Keep decisions, evidence, tables, forms and reading surfaces opaque; controls within navigation use simple fills.

Navigation surfaces use the shared static gradient material (`--ht-glass`) without a backdrop-filter support branch. Reduced transparency and increased contrast use the plain solid shell and a stronger inset edge. Forced colors use system Canvas, CanvasText and Highlight, with shadows removed. The opaque material preserves separation during rapid scrolling without resampling the content beneath it.

## Shapes

Related corners create the shared form language: major content surfaces use the surface radius; standard controls use the control radius; modal and drawer bodies use their overlay radii. The desktop header uses the navigation radius. Project and run navigation use the compact navigation radius, with section controls using the section radius. Primary actions, current header links, counts and header utility controls are capsules. Workspace tabs have rounded upper corners (10px) over a fine baseline; segmented controls use a track radius (12px) with smaller selected-item corners (8px).

Compact table wrappers, alerts and policy blocks retain their compact-surface radius. Semantic tags and artifact blocks retain smaller corners; these are local content treatments, not defaults for new controls. Borders are normally one pixel. The evidence strip has the surface radius and a small inner inset; its internal buttons have related corners (11px), while dividers keep the group connected. Project avatars use the section radius.

## Components

### Buttons
Primary actions use electric blue, white text, capsule corners, the shared control height and stronger text (weight 600, 18px inline padding). Default actions are white with a control border and standard control corners; link and text variants keep their Ant Design behavior. Loading and disabled states guard repeated work while keeping context. Hover and active treatments use the configured blue tokens; enabled primary press scales slightly (0.98). All authored state transitions are short (180ms) with the shared ease.

### Inputs / Fields
Use labeled opaque inputs and selects, vertical form layout, readable placeholder ink and visible validation messages. The shared theme sets the standard control height and radius. Readable help, optional labels, counters and guide descriptions receive the muted description token. Counted textareas reserve their own bottom line before help text.

Keep drafts on the current page when dialogs close. Creation runs through source, requirements, environment, policy and review steps; language changes retain the draft, original PRD and current step. Invalid submission focuses the first failing field. Pending mutations guard dismissal and repeated submission as the existing forms do.

### Chips
Tags show a written status. Green, red, gold, blue/geekblue and volcano retain explicit semantic overrides; neutral tags serve metadata and states that do not imply success. General tags can wrap long content. Project status labels remain on one line so English Archived stays intact in its status cell. A verified evidence tag does not imply a passing run.

### Cards / Containers
White bordered containers use the surface radius and normal panel spacing. Danger and warning decisions add opaque semantic fill and border. Table headings are lightly tinted, rows have a cool hover field and cell padding (16px vertically, 20px horizontally); explicitly small tables retain the library's compact size. Ant Cards use a restrained header (56px high) and normal panel padding. Empty, loading and failed reads occupy the same region as their eventual content and offer a relevant next action or retry.

### Workspace heading and loading
The shared workspace heading provides a single page-title level, optional back link, description, action group and metadata row. Keep project and task names at that level rather than inventing route-specific heading systems. The shared loading surface pairs a written status with a skeleton title and four text rows in an opaque bordered panel (28px padding); when placed inside a table surface it reuses that surface's outer border.

### Navigation
The brand returns home; the header identifies project/run context and exposes guide and language controls. Current global navigation combines `aria-current`, darker blue ink and a pale capsule fill. Hover adds a light fill and a small shadow. The locale control uses a thin translucent fill within the header, with no second backdrop filter.

Project navigation uses three icon-and-label links for Local tasks, Cloud testing and Project experience, with `aria-current="page"` on the active destination. Links have generous inline padding (18px), a minimum height (42px), the section radius and a pale selected fill. This navigation shares the header's opaque static glass material and solid preference alternatives. Workspace content tabs remain opaque and use the workspace-selected field; they do not add another glass layer. Segmented switches keep a neutral track, white selected item and darker blue selected text.

Run tabs sit on one opaque static glass navigation surface. Selected and active text use the darker blue token, paired with the selected section fill; hover uses the configured hover ink. Tabs retain selection per run in session storage and through language changes. Evidence shortcuts select the relevant section and focus its selected tab. Keep the library's keyboard behavior, including Home/End and Enter activation. Details open in solid drawers so users retain run context.

### Decision and evidence trail
The lead decision is the highest-sequence verdict whose status is `FINAL` and scope is `TEST_RUN`. Draft, revoked and narrower verdicts remain in history. With no eligible verdict, show waiting or unavailable text; task completion never substitutes for a decision. Historical execution failures may precede the current verdict and must retain that distinction.

The opaque evidence trail links to executions, findings, evidence and verdicts, carrying counts or a dash when data has not loaded. Unknown coverage is labeled Unknown rather than displayed as zero. Failed refreshes retain loaded records with a retry warning. Agent activity remains supporting information; trusted Runner execution and evidence provide formal facts.

### Progressive content
Local record originals, revision histories and task snapshots mount when their disclosure opens. Cases, reports and history lists use pages of 20 records, preserving every record and its original text. Deferred presentation does not truncate or rewrite accepted artifacts.

The workflow guide, project/run creation dialogs and Cloud resource/task forms load when first opened. After that first opening, keep the component instance and its draft when it closes or its tab changes; later visits reuse the same form state. A deferred panel uses the existing written loading surface.

### Overlays
Modal and drawer bodies remain opaque with related overlay corners. Modals use generous internal padding (28px). The right drawer floats inside a viewport inset (12px), with a lightly tinted header and an opaque reading area. Close controls are capsules; long URLs, hashes and descriptions wrap within the available width.

### Accessibility and motion
Maintain a skip link, visible keyboard focus, accessible control names, semantic headings and written statuses in both languages. The authored focus outline uses the primary accent (3px with a 3px offset). Ant Design also receives the primary accent through `colorPrimaryBorder` so its controls retain strong library focus treatment. Clamped overview descriptions retain links to the full content. No accessibility conformance level is inferred from these implementation rules.

Control and navigation feedback transitions color, fill, border, shadow or a small press transform; the static navigation gradient remains unchanged. The shared easing is `cubic-bezier(.16, 1, .3, 1)`. Reduced motion removes authored transitions and the primary press transform. Run tab-pane animation is explicitly disabled.

The root layout uses the official Ant Design Next.js registry to insert component styles during server rendering. Ant Design's shared theme keeps `motion: false` for both server and browser, preserving identical tokens through hydration without inserting preference-dependent wrappers or discarding drafts. Short authored CSS feedback remains available and follows `prefers-reduced-motion`. Solid-material preferences remain part of the same navigation contract.

## Do's and Don'ts

### Do:
- **Do** use the pale cool canvas, floating light navigation, blue actions and opaque reading surfaces for new operating pages.
- **Do** use the shared workspace heading, project navigation and panel spacing across PC wide-screen pages.
- **Do** keep decisions, reasons, record identity and evidence reachable in one reading path.
- **Do** preserve bilingual drafts, selected run sections, loaded results and immutable history during updates.
- **Do** give readable help the muted description token and reserve a separate line for textarea counters.
- **Do** pair state color with readable labels, preserve visible keyboard focus and keep short project status labels intact.
- **Do** retain static navigation materials, preference alternatives and identical server/browser Ant Design tokens.
- **Do** distinguish unknown, unavailable, zero, task completion and formal quality decisions.

### Don't:
- **Don't** apply live backdrop filtering to navigation or content surfaces.
- **Don't** add decorative entrance sequences to routine testing work.
- **Don't** infer release readiness from task success, coverage counts or an Agent report.
- **Don't** let dense tables or long identifiers create whole-page horizontal overflow.
- **Don't** replace explicit semantic tag overrides with lower-specificity preset styling.
- **Don't** add noisy imagery, neon body text or promotional display typography to this operating workspace.
- **Don't** ship synthetic acceptance records in product routes or present frontend fixture checks as a real testing cycle.
