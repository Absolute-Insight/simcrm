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
| Acumatica ERP sync | [feats/acumatica/README.md](./.pi/feats/acumatica/README.md) |
| In-app help center & assistant chat | [feats/help/README.md](./.pi/feats/help/README.md) |
| Deploying to a server (compose stack, upgrades, backups) | [deploy/README.md](./deploy/README.md) |
| Cutting a release (versioning, the image build, what is not automatic) | [docs/RELEASING.md](./docs/RELEASING.md) |

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
| `frontend/src/components/Modals/HelpCenterModal.vue` | In-app help center (articles from `crm/help/`) |
| `frontend/src/components/Assistant.vue` | Global assistant chat panel (`crm.agent.api.ask_assistant`) |

### Design system
| File | Role |
|---|---|
| `frontend/src/styles/vectora-theme.css` | **Generated** token overrides — never hand-edit |
| `frontend/scripts/generate_vectora_theme.py` | The generator; asserts every contrast floor before it writes |
| `frontend/src/index.css` | Position rail, motion/elevation language, display type scale |
| `frontend/src/components/ui/` | `Skeleton`, `SkeletonTable`, `ErrorState` — loading and failure primitives |
| `frontend/src/utils/chartTheme.js` | Brand chart palette, light and dark |

**Coloured text uses the `-9` step.** `--ink-{green,red,orange}-*` is a
readability ladder, not a lightness one: it runs light-to-dark in light mode and
dark-to-light in dark mode, so a low step is a background tint in *both*.
`text-ink-red-3` looks like a red on the dark theme and measures 1.24:1 on the
light one. `-9` stays above 6.3:1 on every surface in both modes; `-8` grazes
the AA floor on a tinted stat tile. Use orange, not amber, for warnings — no
amber step clears 4.5 against a light surface.

Check with a browser, in **both** themes — the generator's floors cover the
tokens it writes, and these are not among them.

---

## Tests

```bash
cd frontend
yarn test:run      # single run
yarn test          # watch mode
```

- **29 files · 480 tests · well under a second** — all must pass before committing.
  Counts drift; re-read them from `yarn test:run` rather than trusting this line.
- Location: `frontend/tests/unit/`
- Only pure utility functions are unit-tested (no Vue component tests yet)
- Add tests in `tests/unit/` when adding pure logic to `src/utils/`

### Python

```bash
cd /home/frappe/frappe-bench    # the bench is a docker volume, not a repo directory
bench --site test_site run-tests --app crm                          # all of it
bench --site test_site run-tests --module crm.agent.tests.test_signals
bench --site test_site reinstall --yes                              # reset, as CI does per run
```

**Use a dedicated `test_site`, never the site you browse.** `bench run-tests` runs
against whatever site you name, so a development site full of demo records puts that
data in with the suite's own fixtures — and any test whose subject reads site-wide state
then measures the demo instead of the code. The per-rep suggestion ceiling counts every
open row on the site, which is exactly this shape.

The site needs `allow_tests` on, and mail keys (`auto_email_id`, `mail_server`,
`mail_login`, `mail_password` — see `.github/helper/site_config.json`); without a default
outgoing account the report-digest tests find no queued email and fail on the site rather
than on the code. A full run leaves ~70 records behind from fixtures created outside a
rolled-back transaction, so reinstall periodically.

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
