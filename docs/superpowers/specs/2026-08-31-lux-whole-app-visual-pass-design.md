# Vectora Lux — whole-app visual pass (design)

**Date:** 2026-08-31
**Status:** Approved (user sign-off in session)
**Scope:** Every user-facing surface of the CRM frontend. Extends the language
established in `2026-08-25-vectora-lux-dashboard-design.md` — which explicitly
deferred "Reports → Planner → app shell" to later phases — to the whole app,
and replaces the body typeface and the icon set.

## What we are building

The Lux language currently reaches four surfaces (Dashboard, Planner, Reports,
Kanban). Everywhere else — every list view, every detail page, Settings, all
modals, the mobile pages — still renders in stock frappe-ui. This pass closes
that gap, and goes one step further than a re-skin: it normalizes the spacing,
radius and type rhythm that make an app read as considered rather than
assembled. It also replaces the two things that most visibly date the UI: the
body typeface and the 119 hand-drawn icons.

## Decisions (settled with the user)

| Question | Decision |
|---|---|
| Depth of change | **Skin + density.** Token language, font and icons applied to existing layouts, *plus* a normalized spacing scale, radius scale, list-row density, toolbar heights, and empty/loading states. Layout structure and information architecture stay as they are. |
| Icon set | **Phosphor** (`@phosphor-icons/vue` 2.2.1, MIT), applied through an adapter layer rather than a rewrite. |
| Typeface | **Plus Jakarta Sans throughout** (`@fontsource-variable/plus-jakarta-sans`, wght 200–800). One family for body and display. |
| Space Grotesk | **Dropped entirely.** The wordmark moves to PJS 800 at tight tracking. |
| Light theme | **Lifted, not left behind.** Still no blur and no glow — but it gets layered elevation, tinted (not flat-white) surfaces, refined hairlines, and the same density and type system. Light stops reading as the fallback theme. |
| Review cadence | **Run the whole pass, review at the end.** No intermediate approval gates. |

## Measured inputs

Font metrics were measured from the actual `woff2` files with `fontTools`,
not assumed:

| Metric | Inter (today) | Plus Jakarta Sans | Δ |
|---|---|---|---|
| x-height / em | 0.546 | 0.536 | −1.8% |
| cap-height / em | 0.728 | 0.745 | +2.4% |
| default line box / em | 1.21 | 1.26 | **+4.1%** |
| lowercase `n` advance | 0.591 | 0.573 | −3.0% |
| **tabular digit advance** | 0.648 | 0.600 | **−7.5%** |

Three consequences drive the design:

1. **`tnum` is present in PJS**, so `body { font-variant-numeric: tabular-nums }`
   keeps working. This mattered enough to block on: the repo relies on it for
   currency and timestamps.
2. **Tabular digits are 7.5% narrower**, not wider. (The proportional `0` glyph
   *is* 16% wider than Inter's, but this app never renders it.) Numeric columns
   gain headroom; there is no truncation risk from the swap.
3. **The default line box is 4.1% taller.** Anything sized by its content —
   buttons, list rows, badges — grows ~4% unless line-heights are set
   explicitly. The density system below sets them explicitly for this reason.

## Design

### 1. Type system

Add `@fontsource-variable/plus-jakarta-sans`; remove
`@fontsource-variable/space-grotesk` and its `@import`.

Body inherits PJS by overriding `fontFamily.sans` in the Tailwind preset, so
frappe-ui's own components pick it up without per-component edits.

**Display differentiation moves from family to weight and tracking.** There is
no second family any more: `fontFamily.display` resolves to PJS, and the
display voice comes from weight 700/800 plus negative tracking that tightens as
size grows. PJS's cap-height (0.745, above Inter's 0.728) carries display sizes
on its own. The existing hooks — `.v-title`, `.v-title-sm`, `.font-display`,
and the `text-2xl-*` / `text-3xl-*` size selectors — keep their current
contract; only what they resolve to changes.

Explicit line-heights are set per type step to absorb the +4.1% line box.

### 2. Icon system — adapter, not rewrite

`@phosphor-icons/vue` merges `$attrs` onto its `<svg>` root and defaults
`fill="currentColor"` (verified in the compiled package source). That means
every existing call site — `<DealsIcon class="h-4" />`, `text-ink-gray-5`, and
the 40 `h-4` / 27 `size-4` / 24 `w-4` usages — keeps working unchanged.

So each of the 119 files in `frontend/src/components/Icons/` **keeps its
filename** and becomes a thin wrapper around a Phosphor icon:

- The wrapper **preserves that icon's current default `width`/`height`**, so no
  call site shifts. This matters because the existing set is not uniform: 79
  icons are 16×16, 24 are 24×24, and the rest are 18/12/20/32/40/64/300/666.
  Call sites that pass only `h-4` rely on the intrinsic width.
- **All 90 consuming files change by zero lines.**

Weight defaults to `regular` app-wide via Phosphor's `provide()` injection.
`fill` is reserved for active nav items and status dots; `duotone` for empty
states. These are the only two exceptions — a set that uses every weight looks
like a set with no rules.

**Not converted:** brand and product marks — `CRMLogo`, `ERPNextIcon`,
`GoogleIcon` — stay hand-drawn, because Phosphor has no brand glyphs. Status
glyphs (`TaskStatusIcon`, `TaskPriorityIcon`, `DotIcon`) are evaluated
individually; where Phosphor has no honest equivalent they stay as they are
rather than being forced onto an approximate icon.

Imports are named and tree-shaken, so only the icons actually used ship.

### 3. Scale normalization

**Radius.** Today: 133×`rounded-4`, 46×`rounded-6`, 46×`rounded-5`, plus
strays (`rounded`, `rounded-lg`, `rounded-1`, `rounded-8`, `rounded-b`,
`rounded-tl`, …). Collapse to three semantic steps — **control** (inputs,
buttons, badges), **card**, **overlay** (modals, popovers) — and map every
stray onto one of them. Directional radii (`rounded-b`, `rounded-tl`) are kept
where they serve a real join.

**Density.** Row height, cell padding, section gap, page gutter and toolbar
height become CSS custom properties, so surfaces retune together instead of
being adjusted one file at a time. Current values are inconsistent by surface —
Modals use `p-2`/`p-3`/`p-4`/`px-4`/`px-6` interchangeably; Settings mixes
`gap-1`/`gap-2`/`gap-3`/`gap-4` and `py-2`/`py-3`; the page gutter is
`mx-3 sm:mx-5` in lists but `px-5` elsewhere. The tokens give these one source
of truth.

**Elevation.** Add `.v-glass-sm` for row- and inline-level elevation, so
surfaces that need lift without becoming a full card have something to use.
Light theme gains its own layered elevation and tinted surface tokens under the
same class names — no blur, no glow, per the constraint below.

**On concrete values.** This spec fixes the *structure* of the radius and
density scales — how many steps there are, what each one means, and that they
are driven from one place. It deliberately does not fix the numbers. Those are
set in the implementation plan and tuned against screenshots in both themes,
because the +4.1% line box means the correct row height is something to measure
on screen, not to derive on paper. The rule that survives tuning: three radius
steps and one density source, no fourth step added to solve a local problem.

### 4. Surface rollout

Tiers are **work organization, not approval gates** — the user chose to review
the finished pass rather than each stage. They order the work so that the shell
settles before the surfaces inside it, and they give the implementation plan its
commit boundaries.

| Tier | Surfaces |
|---|---|
| 1 · Shell | `AppSidebar`, `AppHeader`, `SidebarBrand`, `SidebarUser`, `DesktopLayout`, `MobileLayout`, `SettingsLayoutBase`, `ViewBreadcrumbs` |
| 2 · Lists | `ListRows`, `ListHeader`, the 8 `*ListView.vue`, `EmptyState`, Kanban, filter/sort/toolbar controls |
| 3 · Detail | `Lead`, `Deal`, `Contact`, `Organization`, `Tasks`, `Notes`, `CallLogs`, `Calendar`, Activities panels, FieldLayout sections |
| 4 · Modals & Settings | all of `components/Modals/`, all of `components/Settings/` |
| 5 · Mobile & misc | mobile pages, `Welcome`, `DataImport`, `PersonaForm`, `InvalidPage`, `NotPermitted` |

### 5. Known fragility

`frappe-ui/experimental/ListView` exposes **no `data-slot` hooks** — verified by
grep across the package. Its row markup is
`<div class="grid items-center gap-4 px-2">`, and row density can only be
reached by targeting those utility classes.

Mitigation: scope every such override under a wrapper class this repo owns
(applied in `components/ListViews/ListRows.vue`) and keep the selectors at zero
specificity with `:where()`, so any component that needs to opt out still wins.
This is the one part of the pass that can break on a frappe-ui upgrade, and it
is commented as such at the site.

### 6. Non-goals

- No layout or information-architecture changes. Nothing moves; things are
  re-proportioned in place.
- No new widget or component types.
- No hand edits to the generated `frontend/src/styles/vectora-theme.css` — it
  is regenerated by `frontend/scripts/generate_vectora_theme.py`, which asserts
  contrast floors before it writes.
- No change to which theme users get by default.
- No changes to Python, to the agent layer, or to any API contract.

## Hard constraints

From `AGENTS.md`, non-negotiable:

- **Coloured text uses the `-9` ink step.** The `--ink-{green,red,orange}-*`
  ramps are readability ladders, not lightness ladders — a low step is a
  background tint in *both* themes. `-8` grazes the AA floor on a tinted tile.
- **Orange, not amber, for warnings.** No amber step clears 4.5:1 against a
  light surface.
- **Both themes are verified in a browser.** The generator's floors cover only
  the tokens it writes; every effect authored by hand in this pass is outside
  that coverage.
- Light theme takes **no blur and no glow** — its premium reading comes from
  elevation, surface tint, hairlines and type.
- `prefers-reduced-motion: reduce` continues to disable every animation
  globally.
- The `guard-paths.sh` PreToolUse hook refuses writes to `vectora-theme.css`,
  `crm/www/crm.html`, `crm/public/frontend/**`, `.env`, lockfiles and
  `crm/__init__.py`. Work with it, not around it.

## Verification

1. `cd frontend && yarn test:run` — the full unit suite green. (Read the count
   from the run; the number in `AGENTS.md` drifts.)
2. Playwright against the live instance on `localhost:8000/crm`: every tier,
   in **both** themes, screenshotted.
3. In-browser contrast measurement on the new surfaces — computed values, not
   estimates — for body text, muted labels and coloured deltas on each new
   surface treatment.
4. Icon audit: confirm no call site changed size or alignment, since the
   adapter's whole promise is that none does.
5. `pre-commit run --files <changed files>`.

## Risks

| Risk | Handling |
|---|---|
| PJS's +4.1% line box silently grows content-sized controls | Explicit line-heights per type step; screenshot diff of shell and list rows |
| Phosphor's 256-unit grid reads optically lighter than the current mixed-weight set at 16px | Visual check at real size before rolling past tier 1; `weight` is a one-line global change if it reads too light |
| Some of the 119 icons have no honest Phosphor equivalent | Those stay hand-drawn rather than being mapped to an approximation |
| frappe-ui upgrade breaks the ListView density overrides | Zero-specificity `:where()` under an owned wrapper class, commented at the site |
| Light-theme lift drifts toward the dark treatment | Constraint is explicit: no blur, no glow; verified per tier in both themes |
