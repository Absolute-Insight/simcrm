# CRM — Project Context

## What this project is

Frappe CRM frontend. Vue 3 + frappe-ui. The backend is Frappe Python. Scripts in
`frontend/` only; Python in `crm/` (Frappe app). No build step for Form Scripts —
they run as evaluated strings in the browser.

---

## Where to read before working

| Task | Read first |
|---|---|
| What are we building next | [PLAN.md](./.pi/PLAN.md) |
| Stable API contracts (setFieldProperty, formDialog, helpers) | [SPEC.md](./.pi/SPEC.md) |
| Why code is the way it is (decisions, bugs fixed, history) | [ARCHIVE.md](./.pi/ARCHIVE.md) |
| Form scripting user guide | [feats/form-scripting/guide.md](./.pi/feats/form-scripting/guide.md) |
| formDialog() API reference | [feats/form-scripting/form-dialog.md](./.pi/feats/form-scripting/form-dialog.md) |
| Local agent layer (`crm/agent/`) | [feats/agent/README.md](./.pi/feats/agent/README.md) |
| Proactive signals, scoring, suggestion inbox | [feats/suggestions/README.md](./.pi/feats/suggestions/README.md) |
| Rep planning and plan-vs-actual matching | [feats/planning/README.md](./.pi/feats/planning/README.md) |
| Analytics, forecasting, quota, reports, digests | [feats/reporting/README.md](./.pi/feats/reporting/README.md) |

---

## Key files

### Scripting engine
| File | Role |
|---|---|
| `frontend/src/data/document.js` | `useDocument` — loads doc, wires script, patches `save.submit`, exposes triggers |
| `frontend/src/data/script.js` | `getScript` — fetches Form Script records, evaluates class via `new Function`, injects helpers, `setupHelperMethods` |
| `frontend/src/utils/scriptHelpers.js` | `createDocProxy`, `getClassNames` — extracted pure helpers |

### Field rendering
| File | Role |
|---|---|
| `frontend/src/components/FieldLayout/FieldLayout.vue` | Tab/section/column layout. Accepts `context` prop for standalone mode (no useDocument) |
| `frontend/src/components/FieldLayout/Field.vue` | Renders a single field. Calls `useDocument` unless `fieldLayoutContext` is injected |
| `frontend/src/components/FieldLayout/Section.vue` | Section with CollapsibleSection |
| `frontend/src/components/FieldLayout/Column.vue` | Column wrapper |

### Form dialog system
| File | Role |
|---|---|
| `frontend/src/components/Modals/FieldLayoutDialog.vue` | Dialog shell + standalone FieldLayout + local reactive doc |
| `frontend/src/components/Modals/FieldLayoutDialogContainer.vue` | Renders dialog entries from reactive array |
| `frontend/src/utils/renderFieldLayoutDialog.js` | `formDialog()` — pushes to array, returns Promise |
| `frontend/src/components/Modals/GlobalModals.vue` | Mounts FieldLayoutDialogContainer + other app-wide modals |

### Field transforms & validation
| File | Role |
|---|---|
| `frontend/src/utils/fieldTransforms.js` | `processField()`, `findMissingMandatory()`, `parseLinkFilters()` — pure, tested |
| `frontend/src/utils/expressions.js` | `evaluateDependsOnValue()`, `evaluateExpression()` |

### Meta & stores
| File | Role |
|---|---|
| `frontend/src/stores/meta.js` | `getMeta(doctype)` — fetches DocType meta, exposes `getFields()`, formatters |
| `frontend/src/stores/global.js` | `$dialog`, `$socket`, `makeCall` |
| `frontend/src/stores/suggestions.js` | Suggestion inbox store, badge count, accept/dismiss flows |

### Product surfaces (Vectora)
| File | Role |
|---|---|
| `frontend/src/components/Suggestions.vue` | Shell inbox panel — the proactive surface |
| `frontend/src/components/RecordSuggestions.vue` | Per-record "Needs attention" + deal health |
| `frontend/src/pages/Planner.vue` | Weekly planner grid, propose-my-week, plan vs actual |
| `frontend/src/pages/Reports.vue` | Report viewer, CSV export, print view |
| `frontend/src/pages/Dashboard.vue` | Role-aware dashboard (rep home / manager view) |
| `frontend/src/components/Settings/Quotas.vue` | Sales targets: rep × month grid |
| `frontend/src/components/Settings/AutomationRules.vue` | Automation rule admin |

### Design system
| File | Role |
|---|---|
| `frontend/src/styles/vectora-theme.css` | **Generated** token overrides — never hand-edit |
| `frontend/scripts/generate_vectora_theme.py` | The generator; asserts every contrast floor before it writes |
| `frontend/src/index.css` | Position rail, motion/elevation language, display type scale |
| `frontend/src/components/ui/` | `Skeleton`, `SkeletonTable`, `ErrorState` — loading and failure primitives |
| `frontend/src/utils/chartTheme.js` | Brand chart palette, light and dark |

---

## Tests

```bash
cd frontend
yarn test:run      # single run
yarn test          # watch mode
```

- **118 tests · ~250ms** — all must pass before committing
- Location: `frontend/tests/unit/`
- Only pure utility functions are unit-tested (no Vue component tests yet)
- Add tests in `tests/unit/` when adding pure logic to `src/utils/`

---

## Commit style

```
feat: short description
fix: short description
refactor: short description
test: short description
docs: short description
```

Multiple logical commits per PR — one commit per coherent change, not one giant commit.
Pre-commit hooks run prettier + eslint + oxlint automatically. If they modify a file,
`git add` the file again and re-commit.

---

## Docs structure

```
PLAN.md          — future only (phases 3B, 4, 5, 6)
SPEC.md          — stable contracts
ARCHIVE.md       — completed phases + decision rationale
feats/           — user-facing feature docs
archives/        — old docs preserved verbatim
```

When a phase completes: move its spec from PLAN.md to ARCHIVE.md, update SPEC.md if
the API surface changed.
