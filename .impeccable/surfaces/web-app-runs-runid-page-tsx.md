---
version: 1
slug: "web-app-runs-runid-page-tsx"
primary_target: "web/app/runs/[runId]/page.tsx"
related_targets: ["web/app/page.tsx","web/app/projects/[projectId]/page.tsx"]
---

# Testing workbench

Mode: Operate. Scope: project index, project runs, run workbench, shared shell and detail overlays.
The user delegates navigation, visual direction and ordinary interactions, explicitly requests code-led implementation, and confirms PRODUCT.md's users and workflow. No further aesthetic selection round is required.

## Direction contract

User-pinned direction: Apple Liquid Glass. Code-led Operate UI; no concept selection needed. Scope includes shared shell, projects, project runs, run tabs, forms and detail overlays. Follow Apple WWDC25 Meet Liquid Glass and Get to know the new design system.

THESIS: A quiet testing workspace with a floating glass control plane above stable, legible testing records. Navigation gains depth; formal evidence remains clear.
OWN-WORLD: Daytime QA work calls for pale cool canvas, white content, deep graphite text and one blue action accent. A single frosted navigation plane has a fine inner highlight, soft downward shadow and concentric corners. Content uses restrained 16px rounding and no live blur.
STORY: Find a project, inspect its fixed run and next action, then follow execution, evidence and the formal verdict. Existing semantics and bilingual workflows remain authoritative.
FIRST VIEWPORT: Inset 68px glass header with brand, project navigation, guide and language controls. Clear title and primary action above a compact workflow introduction and a white project table. On runs, a glass section index sits beside solid decision/task panels; mobile turns it into a horizontal strip.
FORM: The user pinned Liquid Glass; existing navigation and data model retained. Signature interaction is a small light/elevation response on navigation/control hover and press, and a softly changing selected tab. No animation of blur or decorative entrance sequences. Reduce motion removes authored transitions; reduced transparency, higher contrast, forced colors and unsupported filters use solid materials.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance


## Constraints and open decisions

Keep existing APIs, mutation safety, input limits, bilingual switching, canonical trust boundaries and histories. No synthetic data ships in product routes. Review uses isolated, explicitly labeled synthetic API fixtures to exercise empty, loading, error, long-text, blocked and passing states; this does not certify a real testing cycle. No new business features or release claims are inferred.
