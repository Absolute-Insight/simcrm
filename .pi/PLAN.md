# Vectora Development Plan

> **This file**: Current and upcoming work only. No completed phases.
> **Completed phases**: [ARCHIVE.md](./ARCHIVE.md)
> **Stable API contracts**: [SPEC.md](./SPEC.md)
> **Per-phase task plans** (TDD, bite-sized): `docs/superpowers/plans/` — written when a phase starts.

---

## Product Direction (updated 2026-08-15)

The product rebrands to **Vectora**. Direction, in priority order:

1. **Agentic workflow & automation as the spine.** The system watches, predicts, and
   proposes — *proactive with a predictive approach, not reactive*. The rep's day starts
   with "here is what needs attention and why", not with an empty list view.
2. **Global feature coherence.** Every module (Leads, Deals, Contacts, Organizations,
   Tasks, Calls, Notes) uses the same patterns: filters, quick actions, empty/loading
   states, keyboard behaviour. New features must reuse these patterns, never invent
   parallel ones.
3. **Original, intuitive, professional, modern, premium UI.** A deliberate design
   language, not restyled defaults.
4. **Rep planning linked to actual activity.** Plans (auto-proposed by the agent and
   manually authored by reps) resolve against real logged activity — plan vs. actual is
   a first-class measure.
5. **Accurate analytics and forecasts; clean, informative reporting.** One tested
   metrics layer is the single source of numbers for dashboards, forecasts, and reports.

**Scope guard for the rebrand**: Vectora is a *display-layer* brand. `app_name = "crm"`,
Python module paths, and `CRM *` doctype names stay — renaming them is a breaking data
migration and breaks every existing Form Script, for zero user-visible gain.

---

## Implementation Order

Two tracks. The **product track** delivers the new direction; the **platform track**
(pre-existing refactors) continues and stays valuable, but no longer blocks product work.

| Order | Phase | Track | Scope | Status |
|---|---|---|---|---|
| ~~1~~ | ~~Phase 7 — Vectora rebrand & design language~~ | Product | Brand + UI + coherence | ✅ Done — [ARCHIVE](./ARCHIVE.md#phase-7--vectora-rebrand--design-language) |
| ~~2~~ | ~~Phase 8 — Proactive agent workflows~~ | Product | Signals, predictions, suggestions, automation | ✅ Done — [ARCHIVE](./ARCHIVE.md#phase-8--proactive-agent-workflows) |
| ~~3~~ | ~~Phase 9 — Rep planning~~ | Product | Auto + manual plans linked to actuals | ✅ Done — [ARCHIVE](./ARCHIVE.md#phase-9--rep-planning) |
| **4** | [Phase 10 — Dashboards, analytics & forecasts](#phase-10--dashboards-analytics--forecasts) | Product | Metrics layer, role-aware dashboards, forecasting | 🔵 In progress — remaining items below |
| ~~5~~ | ~~Phase 11 — Reporting~~ | Product | Built-in reports, exports, scheduled digests | ✅ Done — [ARCHIVE](./ARCHIVE.md#phase-11--reporting) |
| 6 | [Phase 3B — Full decouple (Grid independent)](#phase-3b--full-decouple-grid-independent) | Platform | Structural refactor | 🔜 Next |
| 7 | [Phase 4 — getMeta single source of truth](#phase-4--getmeta-single-source-of-truth) | Platform | Architectural cleanup | After 3B |
| 8 | [Phase 6 — More Capabilities (selected)](#phase-6--more-capabilities-selected) | Platform | Feature expansion | After 4 |
| 9 | [Phase 5 — Scripting DX Rethink](#phase-5--scripting-dx-rethink) | Platform | Syntax/API redesign | Last |

**Note (3B)**: Phase 7B shipped as a token/CSS layer and did not restructure
`FieldLayout`/`Field`/`Grid`, so Phase 3B proceeds without conflict.

---
## Phase 10 — Dashboards, Analytics & Forecasts

> The metrics layer, the forecast and the role-aware dashboard all shipped
> (2026-08-14/15). What is left is listed here; everything else moved to
> [ARCHIVE](./ARCHIVE.md). Feature doc:
> [feats/reporting/README.md](./feats/reporting/README.md).

### Shipped

- [x] One tested metrics layer. `crm/api/dashboard.py` is the only place an aggregate is
      computed; `reports.py` consumes it and tests assert a tile and its report row are
      equal for the same period.
- [x] Forecast correctness: Lost deals excluded, actual bucketed by `closed_date`, the
      selected range honoured, a patch clearing the snapshot history the old behaviour
      contaminated.
- [x] Hierarchy scoping on every aggregate (`scope_deals` / `scope_leads` /
      `visible_reps`), and `belongs_to` so a rep's tile counts the deals assigned to them
      as well as the ones they own — the definition their deal list has always used.
- [x] `CRM Quota` — monthly per rep in the base currency, pro-rated by covered days for
      an arbitrary range, with a Settings → Sales Targets grid. Quarter/year/team numbers
      are sums, never stored.
- [x] Weekly forecast snapshots per rep and site-wide; `get_forecast_accuracy` compares
      the last pre-month snapshot against live actuals.
- [x] Role-aware dashboard: rep home (attention, today's plan, own tiles) and manager
      view (team adherence, quota attainment) with the customisable chart grid kept
      underneath. Every tile drills through by writing the same standard view the list
      reads.
- [x] A migration patch adds the new widgets to layouts on existing sites, idempotently,
      without clobbering a customised layout.

### Remaining

- [x] Forecast-accuracy widget on the dashboard — registered in `AddChartModal`, so a
      manager can add it. The "wait for snapshots" caution here was answered by giving the
      chart an `emptyState` instead: it says it is waiting rather than drawing one point.
      Verified: `get_chart?name=forecast_accuracy` returns its axis config with `data: []`
      on a site with no snapshots yet.
- [ ] Territory/segment analytics (backlog) — the metrics layer can carry it now that
      quota shape is settled.

---

## Phase 3B — Full Decouple (Grid Independent)

> **Platform track. Structural refactor. See conflict note in Implementation Order.**

### Goal

Make `Grid` work as a standalone component that does not depend on inject/provide chains
from `FieldLayout → Field.vue`. Make `FieldLayout` and `Field` use a single unified
context instead of 6+ separate inject keys.

### Current inject/provide chain (to eliminate)

```
FieldLayout provides:     data, hasTabs, doctype, preview, isGridRow
Field.vue provides:       triggerOnChange, triggerButton, triggerOnRowAdd,
                          triggerOnRowRemove, fieldPropertyOverrides
Field.vue provides:       (also) parentFieldname — for Grid
Grid.vue provides:        parentDoc, fieldPropertyOverrides, parentFieldname
GridRowModal provides:    parentFieldname
```

If Grid is used outside this chain, all injects fall back to defaults (empty
functions/objects) and scripting silently doesn't work.

### Proposed approach

**`useFieldLayout(doctype, options)` composable** — encapsulates all wiring. One
provide/inject key replaces all 6+.

```js
// src/composables/useFieldLayout.js
export function useFieldLayout(doctype, options = {}) {
  // options.docname         — for existing doc (triggers script loading via useDocument)
  // options.doc             — for standalone mode (local reactive data, no useDocument)
  // options.readonly        — all fields read-only
  // options.onFieldChange   — callback instead of script hooks

  const fieldPropertyOverrides = reactive({})

  return {
    context: {
      doc,
      doctype,
      fieldPropertyOverrides,
      triggerOnChange,
      triggerButton,
      triggerOnRowAdd,
      triggerOnRowRemove,
      setFieldProperty: (target, property, value, rowName) => { ... },
      removeFieldProperty: (target, property, rowName) => { ... },
    }
  }
}
```

`FieldLayout`, `Field.vue`, `Grid.vue` all inject `'fieldLayoutContext'` instead of 6
separate keys. External consumers that don't use `useFieldLayout` get safe no-op
defaults automatically.

### Decisions needed before starting

1. **Should Grid work completely without any FieldLayout context?**
   - If yes: Grid needs its own script-loading path for child doctype scripts.
   - If no: Grid without FieldLayout context = display only, no scripting.
   - Recommendation: "no" for now.

2. **Should FieldLayout continue to accept `tabs` as a prop, or should it fetch its own layout?**
   - Currently all callers fetch tabs via `createResource` and pass them in.
   - Moving fetch inside FieldLayout would make it self-contained but less flexible.
   - Ask before deciding.

### Files

| File | Change |
|---|---|
| `frontend/src/composables/useFieldLayout.js` | **New** — unified composable |
| `frontend/src/components/FieldLayout/FieldLayout.vue` | Use `useFieldLayout`; provide single context key |
| `frontend/src/components/FieldLayout/Field.vue` | Inject `'fieldLayoutContext'`; remove 6 separate injects |
| `frontend/src/components/Controls/Grid.vue` | Inject `'fieldLayoutContext'` with safe fallback |
| `frontend/src/components/Controls/GridRowModal.vue` | Simplify — propagate context, remove `parentFieldname` prop |

### Checklist

- [ ] Decide Grid standalone behaviour (display only vs full scripting)
- [ ] Decide whether FieldLayout fetches its own layout
- [ ] `useFieldLayout.js` composable
- [ ] `FieldLayout.vue` — provide `fieldLayoutContext`; keep Phase 3A `context` prop working
- [ ] `Field.vue` — inject `fieldLayoutContext`; remove `isGridRow` branch
- [ ] `Grid.vue` — inject `fieldLayoutContext`; fallback to props-only mode
- [ ] `GridRowModal.vue` — simplify
- [ ] Regression test: all existing forms (Lead, Deal, Contact, Organization pages, all modals)

---

## Phase 4 — getMeta Single Source of Truth

> **After Phase 3B. Completes the architectural cleanup.**

### Goal

1. `getMeta.getField(fieldname)` is the single place that clones, applies overrides, and transforms (Select→array, Link→User).
2. Layout APIs (`get_fields_layout`, `get_sidepanel_sections`) return fieldname strings only + a perm overrides map — no embedded `field.as_dict()`.
3. Rendering components call `getMeta.getField()` instead of doing their own transforms.
4. `getFields()` no longer filters `hidden` fields — callers decide.

### Why after Phase 3B

Phase 3B gives a single context object (`useFieldLayout`) as the wiring point. Routing
all field resolution through `getMeta.getField()` can happen there in one place.

### What remains (not done in Phase 1)

- `getFields()` in `meta.js` still mutates `doctypesMeta` field objects
- Layout APIs still return full `field.as_dict()` per field (redundant)
- `getFields()` still has `!f.hidden` filter
- `processField()` is tested but not wired into rendering

### Checklist

- [ ] Phase 3B must be merged first
- [ ] `meta.js` — `getField(fieldname, options)` method: clones + applies perm overrides + script overrides + transforms
- [ ] `meta.js` — `getFields()` uses `getField()` internally; removes `!f.hidden` filter
- [ ] `useFieldLayout.js` — routes field resolution through `getMeta.getField()`
- [ ] `crm_fields_layout.py` — `get_fields_layout` returns `{ tabs: [...fieldname strings...], perm_overrides: {...} }`
- [ ] Update all callers of layout APIs to handle new format
- [ ] `ColumnSettings`, `ViewControls`, `KanbanSettings` — add explicit `hidden` filter
- [ ] Remove redundant Select/Link transforms from `SidePanelLayout.vue`

---

## Phase 6 — More Capabilities (selected)

> **After Phase 4. Feature expansion on clean foundation.**

### 6A — Programmatic layout manipulation

Inject virtual fields and sections that exist only at runtime — not in the DocType:

```js
class CRMLead {
  onLoad() {
    this.addField('basic_section', {
      fieldname: '_score_display',
      fieldtype: 'HTML',
      label: 'Lead Score',
      after: 'status',
    })

    this.addSection({
      name: '_ext_section',
      label: 'Extension Data',
      after: 'contact_section',
      fields: [
        { fieldname: '_ext_field1', fieldtype: 'Data', label: 'Custom Field' },
      ],
    })
  }
}
```

Virtual fields are managed in a separate `virtualFields` map on the document context.

### 6B — `usePermLevel` composable

Move perm level restriction logic client-side. Currently `handle_perm_level_restrictions`
in `crm_fields_layout.py` modifies `read_only`/`hidden` on the server. This means the
client must re-fetch the layout to reflect permission changes.

A `usePermLevel(doctype)` composable would:
- Fetch the user's permitted perm levels per doctype (once, cached)
- Expose `getPermOverrides(fields)` computing restrictions client-side
- Pass result as `permOverrides` into `getMeta.getField()`

**Depends on Phase 4.**

### Checklist

- [ ] Phase 4 must be merged first
- [ ] 6A: `addField(sectionName, fieldDef)` prototype method in `script.js`
- [ ] 6A: `addSection(sectionDef)` prototype method
- [ ] 6A: `virtualFields` map on document context
- [ ] 6A: Layout resolution merges virtual fields
- [ ] 6B: `usePermLevel(doctype)` composable
- [ ] 6B: `crm_fields_layout.py` — return raw perm data instead of modifying fields
- [ ] 6B: Wire into `getMeta.getField()` via Phase 4

---

## Phase 5 — Scripting DX Rethink

> **Last. Do once the full capability set (Phases 3B–6) is known and stable.**

### Why last

- The syntax should reflect all capabilities — not a subset.
- A syntax change is a breaking change for script authors — do it once.
- `setFieldProperty` works well enough in the meantime.

### Ideas (not decided — decide with maintainer)

#### Builder / chainable API

```js
this.field('annual_revenue').hide()
this.field('status').setOptions('New\nOpen\nClosed')
this.field('email').makeRequired().setLabel('Work Email')
this.section('financial_section').collapse()
this.fields(['email', 'phone']).makeRequired()
```

#### Declarative rules

```js
class CRMLead {
  rules = {
    lost_reason: {
      hidden: (doc) => doc.status !== 'Lost',
      reqd:   (doc) => doc.status === 'Lost',
    },
  }
}
```

#### Reactive shortcuts

```js
this.field('lost_reason')
  .showWhen(() => this.doc.status === 'Lost')
  .requireWhen(() => this.doc.status === 'Lost')
```

### Backwards compatibility

`setFieldProperty`, `setFieldProperties`, `removeFieldProperty`, `getField`, `formDialog`
continue to work. New syntax is additive.

---

## Deferred / Backlog

| Feature | Notes |
|---|---|
| List view scripting | Column visibility, custom cell renderers, bulk action hooks |
| Inter-script communication | `this.emit('event', data)` / `this.on('event', handler)` across scripts |
| Conditional field injection | Variant of 6A — scripts inject fields only when a condition is true |
| Custom report builder UI | The five built-in reports have proven the metrics layer; this is now unblocked |
| Codified injection eval suite | Assert-on-refusal-rate across models. The hostile thread is a documented standing eval; codify it when a second write capability lands |
| Territory/segment analytics | Metrics layer extension; unblocked now that quota shape is settled |
| Forecast-accuracy widget | Endpoint and chart shape exist; register once snapshots have accumulated |
| Block remote images in inbound email | Post-v1 by decision. Scoped and de-risked already — see below, the mechanism is one CSP token |


### Block remote images in inbound email (post-v1)

Deferred out of the pilot by decision, twice. Logged here with the scoping already
done so nobody re-derives it: **the blocking mechanism is one token**, and the
obvious version of that token is wrong.

`EmailContent.vue` already renders inbound mail in a sandboxed `srcdoc` iframe
carrying its own `<meta>` CSP. Today it says `img-src http: https: data: cid:`.
The fix is:

```
img-src 'self' data:
```

Four things were verified in a browser against that exact config, each with a
same-origin control to prove the probe was live:

- **A `<meta>` CSP *is* enforced inside `srcdoc`.** Permissive control loaded;
  restricted sibling reported `FAILED: csp` with no request leaving the browser.
- **`'self'` resolves to the parent origin** in a `srcdoc` document with
  `sandbox="allow-same-origin"`. This is the part that matters: frappe rewrites
  `cid:` to a same-origin `/files/…` URL at receive time
  (`frappe/email/receive.py:751`), so inline logos and signatures arrive as
  same-origin paths. `img-src data: cid:` — the obvious directive — would have
  blocked every one of them, and `cid:` in the current CSP is dead weight that
  never reaches the browser.
- **One directive covers every evasion route.** `<img src>`, CSS
  `background-image`, `srcset`, and `<picture><source>` were each blocked by
  `img-src` alone. No DOM rewriting or per-element scrubbing is needed.

So the work is not the block, it is the affordance — mail that is one large
remote image renders as a blank box, which reads as a bug rather than a policy:

| task | note | est. |
|---|---|---|
| CSP token, drop the dead `cid:` | the actual block | 15 min |
| `hasRemoteImages()` in `src/utils/` + unit tests | so the banner does not cry wolf; must catch `srcset`, `<picture>`, `background-image`, protocol-relative `//host` | 1–1.5 h |
| `htmlContent` → `computed` | it is a plain `const` evaluated once at setup, so the toggle cannot re-render. Fixes a latent bug for free: `props.content` changes never re-render today | 30 min |
| banner + "Load images" | `__()`; orange not amber, `-9` ink step; both themes | 1.5–2 h |
| browser verification | real remote-image email, both themes | 1 h |

**≈ half a day.** Blast radius is one component with one caller
(`EmailArea.vue:64`), tightening one token in a control that already shipped.

Deliberately **out** of that estimate: "always load images from this sender"
needs a persistence store, an endpoint, settings UI and a trust model (2–3 days);
a server-side image proxy hides the rep's IP but still confirms the open, so it
buys less than it costs. Ship the session-only toggle.


---

## Design Principles

1. **Generic-first** — No CRM-specific assumptions in FieldLayout, Grid, Field, or the
   scripting engine. CRM-specific behaviour lives in Form Script records.

2. **Ask before deciding** — Document the options, pick the right one with the
   maintainer. Especially for: prop names, composable APIs, breaking changes.

3. **Props > inject for public API** — Components accept props for their core inputs.
   inject/provide is for internal wiring only.

4. **Test pure logic first** — Extract functions to utility files, write unit tests,
   then wire into components. Vitest is already set up (118 tests, ~250ms).

5. **Incremental, independently shippable** — Each phase merges and is usable on its own.

6. **Extensibility via records** — Third-party apps extend via `CRM Form Script`
   records. No source code modification. Multiple scripts per doctype run sequentially;
   last-write-wins for overrides.

7. **Proactive, not reactive** — Features surface the next action before the user asks.
   Every prediction shows its contributing factors; nothing is an unexplained score.

8. **Coherent by default** — A new surface reuses the global patterns (filters, quick
   actions, states, shortcuts). Divergence is a bug, not a style choice.

9. **Agent output is untrusted input** — Proven by the live-model injection gate
   (`feats/agent/README.md`): no model-proposed write lands without a `formDialog()`
   confirmation showing the exact payload as plain text; deterministic automation never
   depends on a model being enabled.

10. **One source of numbers** — Dashboards, forecasts, and reports consume only the
    tested metrics layer. Two surfaces showing different values for the same metric is
    a release blocker.
