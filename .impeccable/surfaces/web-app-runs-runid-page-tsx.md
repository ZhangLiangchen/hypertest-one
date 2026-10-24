---
version: 1
slug: "web-app-runs-runid-page-tsx"
primary_target: "web/app/runs/[runId]/page.tsx"
related_targets: ["web/app/page.tsx","web/app/projects/[projectId]/page.tsx","web/app/projects/[projectId]/tasks/new/page.tsx","web/app/projects/[projectId]/cloud/page.tsx","web/app/projects/[projectId]/memory/page.tsx","web/app/tasks/[taskId]/page.tsx","web/app/cloud-tasks/[taskId]/page.tsx","web/app/workspace-ui.tsx","web/app/globals.css","web/app/providers.tsx"]
---

# Testing workbench

Mode: Operate. Scope: all eight workspace routes: project index, project workspace, task creation, Cloud directory/resources/creation, project experience, Local task, Cloud task and legacy run; shared shell and detail overlays follow the same system.
The user delegates navigation, visual direction and ordinary interactions, explicitly requests code-led implementation, and confirms PRODUCT.md's users and workflow. No further aesthetic selection round is required.
HyperTest One implements and supports PC wide-screen interfaces only. This permanent product constraint applies to every page, component, interaction, layout and regression check; mobile and portrait compatibility are not required. Existing narrow-screen CSS is retained implementation history and does not create a compatibility commitment or maintenance requirement.

## Direction contract

User-pinned direction: Apple Liquid Glass. Code-led Operate UI; no concept selection needed. This is an extension of the existing world across the workspace routes. Follow Apple's [Liquid Glass overview](https://developer.apple.com/documentation/TechnologyOverviews/liquid-glass) and WWDC25 Meet Liquid Glass / Get to know the new design system. [ReportPortal Test executions](https://reportportal.io/docs/test-executions/) informs table-oriented inspection, visible filters and adjacent record actions; it does not define HyperTest's domain semantics.

THESIS: A quiet testing workspace with a floating glass control plane above stable, legible testing records. Navigation gains depth; formal evidence remains clear.
OWN-WORLD: Daytime QA work calls for pale cool canvas, white content, deep graphite text and one blue action accent. A single frosted navigation plane has a fine inner highlight, soft downward shadow and concentric corners. Content uses restrained 16px rounding and no live blur.
STORY: Find a project, move between Local tasks, Cloud testing and Project experience, inspect the task's fixed records and next action, then follow its reports or the legacy run's execution, evidence and formal verdict. Existing identities, trust semantics and bilingual workflows remain authoritative.
FIRST VIEWPORT: Inset 68px glass header with brand, context, guide and language controls. Shared heading puts the title and description beside its action group, with record metadata beneath. Project workspaces add one three-destination glass navigation strip above opaque panels and tables. The legacy run retains its left section index beside solid decision/task panels. Compose for PC wide screens.
FORM: The user pinned Liquid Glass; existing navigation and data model retained. Signature interaction is a small light/elevation response on navigation/control hover and press, and a softly changing selected tab. No animation of blur or decorative entrance sequences. Reduce motion removes authored transitions; reduced transparency, higher contrast, forced colors and unsupported filters use solid materials.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance


## Constraints and open decisions

Keep existing APIs, mutation safety, input limits, bilingual switching, canonical trust boundaries and histories. No synthetic data ships in product routes. Review uses isolated, explicitly labeled synthetic API fixtures to exercise empty, loading, error, long-text, blocked and passing states; this does not certify a real testing cycle. No new business features or release claims are inferred.

## Implemented extension

- Shared `WorkspaceHeading`, `ProjectNavigation` and `WorkspaceLoading` components unify route titles, project wayfinding and pending reads. Local and Cloud task identities and separate Memory authorization remain visible.
- Shared panels retain white fill, 16px corners and 24px padding. Stacks and adjacent experience panels keep 24px separation. Shared section headings use 20px; nested sections use 17px.
- Task creation uses a centered 1040px form; paired repository fields use two columns and a 24px gap. Forms use 24px item spacing and quiet section dividers.
- Standard table cells use 16px vertical and 20px horizontal padding; explicit small tables keep the component library's compact density. Warning notices use the shared opaque surface, border and ink roles recorded in DESIGN.md.
- Header, project navigation and legacy run index share static CSS glass, preference fallbacks and short control feedback. Native optical refraction is not implemented.

## Visual review evidence

Desktop captures in `output/playwright/desktop-{projects,project,create-task,cloud-tasks,cloud-resources,cloud-create,memory,local-task,cloud-task,legacy-run,project-modal,guide-drawer}.png` record the route and overlay review at 1440px width. These are synthetic frontend visual-regression fixtures, not business acceptance or model/SUT execution evidence. Tokens and spacing in DESIGN.md are grounded in the final stylesheet and provider; a capture taken before the last visual fix is not proof of the final spacing.
