# Key files

A navigation index: which file owns which job. Moved out of `AGENTS.md`
because that file is loaded into context on every single session, and a
file→role table is the one kind of content an indexed repo can answer on
demand — `codegraph explore "<symbol or question>"` returns the verbatim
source plus its callers, which is strictly more than a row here can say.

Kept anyway, and kept current, because it is the map you want when the
question is "what is the shape of this app" rather than "where is X".
The one thing that did *not* move is the `--ink-*` contrast rule: that is a
gotcha, not a location, and it stays in `AGENTS.md`.

---

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
| `frontend/src/utils/surfaces.js` | Nav/settings surface registry (`SURFACES`, `canSee`, `editableBy`, `isAtFloor`) — the source of truth `Settings → Access Control` renders |
| `frontend/src/stores/access.js` | `canSee(key)` over the session's hidden set, loaded once in the router guard |

### Permissions
| File | Role |
|---|---|
| `crm/permissions/org_hierarchy.py` | Sales-hierarchy row scoping for `CRM Lead` / `CRM Deal` (`permission_query_conditions`, `has_permission`); reads `manager_outside_hierarchy` for the out-of-tree case |
| `crm/api/access.py` | `get_visibility` / `set_visibility` — the nav/settings visibility matrix; `get_data_access` / `set_data_access` — the two server-enforced switches |

### Product surfaces (Vectora)
| File | Role |
|---|---|
| `frontend/src/components/Suggestions.vue` | Shell inbox panel — the proactive surface |
| `frontend/src/components/RecordSuggestions.vue` | Per-record "Needs attention" + deal health |
| `frontend/src/pages/Planner.vue` | Weekly planner grid, propose-my-week, plan vs actual |
| `frontend/src/pages/Reports.vue` | Report viewer, CSV export, print view |
| `frontend/src/pages/Dashboard.vue` | Role-aware dashboard (rep home / manager view) |
| `frontend/src/components/CommandPalette/` | Ctrl/Cmd+K: `useCRMCommands.js` builds the rows, `crm/api/command_palette.py` searches; `utils/commandPalette.js` ranks |
| `frontend/src/composables/useNavLinks.js` | The app's places and their conditions, read by the sidebar and the palette |
| `frontend/src/composables/useCRMOnboarding.js` | The checklist for every caller but the sidebar and its panel; reporting a step is a no-op where no steps are registered |
| `frontend/src/components/Settings/Quotas.vue` | Sales targets: rep × month grid |
| `frontend/src/components/Settings/VisitTargets.vue` | Visit targets: visits per working week per rep |
| `frontend/src/components/Settings/AutomationRules.vue` | Automation rule admin |
| `frontend/src/components/Modals/HelpCenterModal.vue` | In-app help center (articles from `crm/help/`) with the Mentor box (`crm.agent.api.ask_mentor`) |
| `frontend/src/components/Assistant.vue` | Sidebar assistant panel over the admin-curated knowledge base (`crm.agent.api.ask_assistant`) |
| `frontend/src/pages/Analyst.vue` | Admin-only analyst page: model narrative beside computed tables (`crm.agent.api.ask_analyst`) |
| `frontend/src/components/AgentChat.vue` | The transcript/input shared by the three chat surfaces; stores come from `stores/agentChat.js` |
| `frontend/src/components/Settings/KnowledgeSettings.vue` | Settings → Knowledge: what the Assistant may quote (`crm/api/knowledge.py`, `crm/knowledge/samples/`) |
| `frontend/src/components/Settings/AccessControl.vue` | Settings → Access Control: admin-only data-access switches plus the role × surface visibility matrix (`crm/api/access.py`) |

### Field mode (offline)
| File | Role |
|---|---|
| `crm/api/offline.py` | `get_pack` — the permission-scoped snapshot a phone carries; `handshake` — CSRF token + server clock for a cached shell; `replay` — applies one outbox entry exactly once |
| `frontend/offlineShell.js` | Vite plugin: writes `shell.html`, the built page with the Jinja boot block replaced by a loader |
| `frontend/public/field-sw.js` | Service-worker fragment: network-first navigations under `/crm`, falling back to the precached shell |
| `frontend/src/offline/bootSnapshot.js` | The boot a shell starts from (no CSRF token), and the inline loader that restores it |
| `frontend/src/offline/connectivity.js` | `connectivity.online`, `probe()`, `throughGate()` — wraps the resource fetcher and `call()` |
| `frontend/src/offline/pack.js` | The pack on the device: load, sync, expiry, background refresh |
| `frontend/src/offline/outbox.js` | The outbox: `enqueue`, `flushOutbox`, retry/discard; every Field write goes through it |
| `frontend/src/utils/fieldOutbox.js` | Pure outbox rules: validation, `applyOutbox` overlay, `failureKind` |
| `frontend/src/components/Field/FieldEntryDialog.vue` | The one capture dialog (log, outcome, cancel, note, task) |
| `crm/fcrm/doctype/crm_offline_receipt/` | One row per replayed entry: what makes a retry a no-op |
| `frontend/src/offline/sheets.js` | Reference sheets kept on the device: download, index, remove |
| `frontend/src/offline/db.js` | The two IndexedDB stores (pack, outbox) and when each is cleared |
| `frontend/src/utils/fieldPack.js` | Pure helpers: index by customer, search, expiry, display |
| `frontend/src/pages/Field.vue` + `components/Field/` | The standalone Field surface: week, customers, customer, tasks |

### Design system
| File | Role |
|---|---|
| `frontend/src/styles/vectora-theme.css` | **Generated** token overrides — never hand-edit |
| `frontend/scripts/generate_vectora_theme.py` | The generator; asserts every contrast floor before it writes |
| `frontend/src/index.css` | Position rail, motion/elevation language, display type scale |
| `frontend/src/components/ui/` | `Skeleton`, `SkeletonTable`, `ErrorState` — loading and failure primitives |
| `frontend/src/utils/chartTheme.js` | Brand chart palette, light and dark |
