# Vectora — Pilot Readiness Checklist

**Mandate (2026-08-16):** the production pilot ships the *complete* product — every
planned feature, enterprise-grade — because its purpose is to validate Vectora in a real
production environment before it is presented to clients. Deferring a feature is a gap to
close, not a scope decision.

Ordered by what would hurt most in that setting. Every item was verified against the code;
each names the file, the concrete failure, and the effort. Check items off as they land.

**Legend:** `[x]` done · `[ ]` open · **P0** blocks a pilot with real customer data ·
**P1** blocks a *trustworthy* pilot · **P2** completeness mandate · **P3** client-facing
polish · **P4** platform work beyond the pilot.

---

## P0 — Security and data integrity

- [x] **Auth bypass: `remove_assignments` took `ignore_permissions` from the client.**
      `crm/api/doc.py:591`. Whitelisted arguments arrive from the request, and `set_status`
      skips its permission check entirely when set — so any authenticated user could
      unassign anyone from any record, including records they cannot read. A ToDo
      assignment is one of the clauses granting a rep visibility, so this was also a way to
      take a deal away from its owner. Neither caller ever passed it. *Parameter deleted.*
- [x] **Latent bypass shipped from the browser.** `ListBulkActions.vue:147` sent
      `ignore_permissions: true` to `remove_multiple`. Harmless today only because that
      signature drops unknown kwargs — a live bypass the day upstream adds the parameter.
- [x] **`deploy/.env` was not gitignored, and this repository is public.** The runbook's
      first boot step is `cp .env.example .env` *inside the working tree*, and that file
      holds `DB_ROOT_PASSWORD` and `ADMIN_PASSWORD`. One `git add -A` on a deploy host
      publishes a production database password.
- [x] **Quota attainment divided a scoped numerator by an unscoped denominator.**
      `crm/api/dashboard.py:1770` vs `:1799`. `quota_in_period` uses `frappe.get_all`, which
      does not check permissions; `won_value_in_period` is subtree-scoped. An in-tree
      manager at 90% attainment sees ~30% — and `quota_attainment` is a curated tile, the
      first number on the manager dashboard. `forecast_accuracy_rows` (`:1850`) has the same
      shape. **1–2 h.**
- [x] **The `user=` parameter was trusted for anyone holding Sales Manager.**
      `dashboard.py:112,149`; `reports.py:104,227`. Only a *plain* Sales User is pinned to
      themselves. Combined with the item above, an in-tree manager can read another team's
      quota targets — compensation data. `rep_plan.py:63` already has the right pattern
      (`_can_view`); the metrics layer doesn't use it. **2–3 h.**
- [x] **Quota and Suggestion permission queries were role-based, not hierarchy-scoped —
      contradicting SECURITY.md.** `crm_quota.py:60`, `crm_suggestion.py:8` return
      unrestricted for any Sales Manager. `SECURITY.md:26` states rep isolation as an
      invariant, and CRM Rep Plan honours it; these two don't. An in-tree manager sees every
      rep's targets company-wide. **2 h.**
- [x] **Bulk "Convert to Deal" silently lost conversions.** `ListBulkActions.vue:88`
      fires one un-awaited POST per lead with no `.catch`; the first response closes the
      dialog while the rest are in flight. A rep converts 30 leads, sees success toasts, and
      some silently did not convert. Real pipeline lost. **2 h** (`Promise.allSettled` + one
      summary toast). **Highest-value single fix in this list.**
- [x] **Deal saves in a foreign currency blocked on a third-party API and threw when it was
      down.** `crm_deal.py:102` → `exchange_rate.py:8`. Synchronous `requests.get` to
      frankfurter/exchangerate.host inside `validate`, up to 10 s in a web worker, and
      `_raise_exchange_rate_error` throws if both providers fail. On a host with no outbound
      internet — a normal corporate deployment — *every* non-base-currency deal save fails.
      Also the only outbound endpoint in the app with no `@rate_limit`. **3–4 h.**
- [x] **Customer PII was logged to the browser console in production.** `TwilioCallUI.vue:475`
      logs every inbound caller's phone number; `:329`, `ExotelCallUI.vue:397,420` log full
      call payloads; `UserMultiSelect.vue:79` is a bare debug leftover. `vite.config.js` has
      no `build:` block, so no `drop_console` — these ship verbatim. **1 h.**
- [x] **Sales Manager could author server-rendered Jinja with database-read globals.**
      `automation.py:110`. `frappe.render_template` with default globals still exposes
      `frappe.db.sql` and a `get_all` forced to `ignore_permissions=True`. A customer's line
      manager can read arbitrary tables via an automation rule's title template. **2–4 h.**
- [x] **Digest recipients were validated only at save time.** `crm_report_digest.py:30` vs
      `:47`. An offboarded rep keeps receiving daily pipeline values at a personal address
      indefinitely. The deploy runbook currently claims otherwise. **30 min.**
- [x] **`crm/api/rep_plan.py` had no role gate** on any of its 7 endpoints and writes with
      `ignore_permissions` (`:204`). Any authenticated account — including a portal user
      with no CRM role — can create plan records that feed the adherence metric. **15 min.**
- [x] **`CRMSalesHierarchy.on_trash` overrode `NestedSet.on_trash` without calling
      super.** `crm_sales_hierarchy.py:50`. Skips both the "manager still has reports" guard
      and the lft/rgt repair, on the doctype that *defines* rep isolation — whose test file
      is a 9-line empty stub. Offboarding a manager orphans their reports or 500s after the
      role removal already committed. **2 h + tests.**
- [x] **Inbound email rendered in an unsandboxed same-origin iframe.**
      `EmailContent.vue:103`, `srcdoc` with no `sandbox`. Not a confirmed XSS — Frappe
      sanitises Text Editor fields with nh3 — but there is no defence in depth and no CSP
      anywhere in the app, and remote content loads automatically, giving external senders
      read receipts on every rep who opens their mail. **2 h.**
- [ ] **Remote images in inbound email still load automatically**, so an external
      sender gets a read receipt on every rep who opens their mail. Blocking them is
      normal mail-client behaviour but needs a "load images" affordance to not look
      broken, so it was left out of the sandbox fix rather than smuggled in. **1 day.**
- [ ] **Demo data contaminates forecast history irreversibly.** `hooks.py:97` seeds demo
      data on desk setup-wizard completion — which `deploy/README.md:107` sends operators
      to. `crm/demo/` never cleans `CRM Suggestion`, `CRM Forecast Snapshot` or
      `CRM Rep Plan`, so hourly signals and weekly snapshots run against fake deals and
      three fake users, and "Clear Demo Data" leaves immutable snapshots behind forever.
      One patch for contaminated snapshots has already shipped once. **3 h.**
- [x] **Two SSRF guards had diverged.** `integrations/api.py:183` (call-recording fetch)
      lacks the explicit multicast reject that `domain_enrichment/http.py:83` documents as
      necessary. The TODO at `integrations/api.py:213` says to share the helper "until
      enrichment ships" — it shipped. **1 h.**
- [x] **`get_assigned_users` was unscoped** (`doc.py:608`) — any user can enumerate who is
      assigned to any record. **15 min.**

## P1 — Release and CI integrity

- [x] **The plan-adherence scoping test failed every Monday.** `test_metrics.py:593`
      lacked the settled-day guard its sibling in `test_reports.py:83` has, so the one test
      protecting against cross-team leakage cried wolf weekly — and passed for the wrong
      reason on the other six days.
- [ ] **Nothing gates merges.** `develop` and `main` are both unprotected, `.mergify.yml`
      has no `check-success` condition, and `codecov.yml:19` sets `if_ci_failed: ignore`.
      **30 min.**
- [ ] **Three e2e specs fail; the suite runs but is advisory until they are triaged.**
      First real run: **15/18**. `planner.spec.ts:104` fails on a clean `develop`
      locally too, so it predates all of this — an item created for the current week
      does not appear on the planner, and the deriving-the-week-from-the-runner's-clock
      theory did **not** hold up when tested, so it needs a real diagnosis rather than a
      guess. `login.spec.ts:12` (the sidebar's Leads link never appears) and
      `email.spec.ts:10` both **pass locally but fail against a freshly created site** —
      which is worth understanding on its own terms, because a fresh site is exactly what
      the pilot will be. Remove `continue-on-error` from `ui-tests.yml` once these are
      closed. **1–2 days.**
- [x] **The Playwright suite had never run in CI.** `ui-tests.yml:6` triggers only on
      branch `main-hotfix`, which does not exist. **5 min.**
- [ ] **The frontend coverage gate cannot fail.** `vitest.config.js:12` scopes coverage to
      10 hand-picked `src/utils` files, so the 85% patch target in `codecov.yml` passes
      trivially for any new component. 0 component tests across 358 `.vue` files. **2 h** to
      widen; component tests are a larger programme.
- [ ] **The production image is built against Frappe `develop` and published to a mutable
      tag.** `builds.yml:51,56`. Two `docker compose pull`s a week apart produce materially
      different systems, framework included, with no way to reproduce what a customer is
      running. No test gate on the build. **1 day** + pinning work.
- [ ] **CI's only build gate compiles against the `@framework/ui` stub.**
      `frontend-tests.yml:47` runs `yarn build` with no bench present, so
      `resolveFrameworkUi()` silently falls back to no-ops and reports green. A removed
      upstream export is invisible until a browser hits it. Make the build *fail* unless
      `FRAMEWORK_UI_STUB=1` is explicit, and set it in that job. **1 h.**
- [ ] **The migration test upgrades from upstream `frappe/crm`, not from a previous
      Vectora release.** `migration-test.yml:94`. The fork's own patches never run against
      data a previous fork version produced. **3 h.**
- [ ] **No rollback path is documented, and upgrades serve new code on an old schema.**
      `deploy/README.md:48` starts containers before `bench migrate`. **3 h.**

## P2 — Completeness (the mandate)

### Built but unreachable — highest value per hour in the whole list
- [x] **Forecast-accuracy chart could not be added to a dashboard.** Backend complete
      since Phase 10 and registered in `CHARTS`, but absent from `AddChartModal`. It ships
      an `emptyState`, so the "wait for snapshots" concern is already handled. *Registered.*
- [x] **"Deals at Risk" could not be re-added once deleted.** In the default layout but
      not the picker. *Registered.*
- [x] **Upgraded sites showed duplicate plan-adherence and quota tiles.**
      `add_vectora_dashboard_widgets` merged two metrics that a later commit made curated
      tiles. *Patch corrected, `remove_duplicated_grid_tiles` added for sites that already
      ran it, and a test now guards the intersection.*
- [ ] **`summarise_thread` has no UI.** Fully built, tested, rate-limited, budget-capped,
      documented as user-facing — and called by nothing. Half the model tier is unreachable.
      Render as plain text, never HTML. **0.5–1 day.**
- [ ] **`get_dismissal_stats` has no UI.** Same story. It exists so "a threshold reps keep
      rejecting is visible rather than guessed at" — exactly the pilot's feedback loop.
      **0.5 day.**

### Local model support (explicitly mandated)
- [x] **No local inference service in the deploy stack.** *Verified: the core code already
      works* — `crm.agent.client.complete()` against ollama returns a schema-valid summary in
      **1.03 s warm** (9.46 s cold), guided decoding clean. So this is deployment work, not a
      rewrite: an opt-in compose profile, a weights volume, `base_url` on a service name
      (127.0.0.1 does not resolve from inside the backend container), keep-alive plus a boot
      warmup for the 9× cold-start penalty, and honest hardware guidance. granite-4.0-h-tiny
      is the verified-good model; MiniCPM5-1B must not ship (returns empty content). **2 days.**
- [ ] **No Agent settings UI.** 11 configurable fields including every signal threshold,
      and no pane in Vectora's own Settings — an admin must drop to the raw Frappe desk.
      For a pilot whose thresholds *will* need tuning, that is real friction. **1 day.**
- [ ] **No way to validate an endpoint.** The only way to learn `base_url` is wrong is a rep
      clicking a feature and getting a degraded dialog. Add a test-connection action. **3 h.**
- [x] **Default `base_url` was `http://localhost:8000/v1` — Frappe's own port.** Enabling the
      tier without editing it makes the CRM POST to itself and fail opaquely. **15 min.**
- [ ] **Nothing enforces `timeout × 2 < PROXY_READ_TIMEOUT`.** Documented in both runbooks
      now, but an admin can still set 300 and discover it in production. Clamp it. **1 h.**

### Mobile parity
- [ ] **A rep on a phone gets none of Vectora's three differentiating surfaces.**
      Suggestions, Planner and Reports are all gated `!mobile` (`AppSidebar.vue:180,300-313`).
      Per-record suggestions do work on mobile. The Planner week grid is the expensive part.
      **3–5 days.**

### Error handling on inherited surfaces
- [ ] **19 `call().then()` sites with no rejection handler.** The split is precise: every
      new Vectora surface uses the `ErrorState`/`describeError` primitives; *no* inherited
      surface does — assignment, quick entry, inline edit, saved views, bulk actions. Reps
      spend most of the day in the inherited ones. **1 day.**
- [ ] **Two endpoints return `"success"` when they did nothing.**
      `doc.py:771,798` skip items the user cannot write, skip validation failures, and
      enqueue when >10 — then return success unconditionally. The modal closes, the list
      reloads, the records are still there. **3 h.**
- [ ] **Form Script `onValidate` failures abort the save with no feedback at all.**
      `document.js:95` catches and returns; the thorough `onError` handler 30 lines above is
      bypassed. This is the failure mode Form Script authors will hit most. **2 h.**
- [ ] **File-upload promise can hang forever.** `filesUploaderHandler.ts:75` parses a 403
      body as JSON unguarded; an HTML error page throws inside the handler and the promise
      never settles. **1 h.**

### Feature gaps
- [ ] **Facebook lead sync drops paginated leads permanently.** `facebook.py:73`
      (`limit: 100000, # TODO: pagination`) never follows `paging.next`, and `:39` advances
      the watermark unconditionally — overflow leads are dropped *and* never re-fetched.
      **Blocker if the pilot uses Facebook lead ads; otherwise P2.** **1 day.**
- [ ] **Scheduled re-enrichment** — documented as "future feature, not implemented". **2 d.**
- [ ] **Territory/segment analytics** — one territory chart exists; no segment dimension
      anywhere, no territory filter on dashboard or reports. **3–5 days.**
- [ ] **`quota_attainment_by_rep` cannot be scheduled** — the digest doctype hardcodes four
      of the five registry reports. **1 h.**
- [ ] **Report Digest has no admin UI** — desk-only. **1–2 days.**
- [ ] **Custom report builder** — its stated precondition (five reports shipped) is met.
      **1–2 weeks.**
- [ ] **Codified injection eval suite.** Its gating condition — "when a second write
      capability lands" — is already met by `draft_reply`. The hostile thread exists only as
      a prose table. Note the honest finding it records: **every model tried follows the
      injected instruction**, which is why the tier has no write path. **2–3 days.**
- [ ] **Enrichment fallback extractor** (+ golden-set evals) — enrichment currently leaves
      JS-rendered sites blank; the model seam was planned and never built. **3–5 days.**
- [ ] **Duplicated thresholds.** `AT_RISK_BELOW = 40` (`predict.py:44`) and
      `HEALTH_AT_RISK = 40` (`suggestions.js:36`) are independent; the tile count and the
      record badges drift apart if either moves. `CLOSE_HORIZON_DAYS` has the same split —
      widening the horizon in Settings moves the suggestion but not the health factor. **3 h.**
- [ ] **Six inline scoring literals order every rep's queue** (`signals.py:140,167,200,265,
      327,375`, `automation.py:182`) — against the convention `predict.py:21` states
      explicitly. An admin cannot make a critical automation rule outrank a routine nudge. **3 h.**

## P3 — Client-facing polish

- [x] **Every dashboard panel carried an invisible but clickable "Hide" button.**
      `PanelCard.vue` never had the `group/panel` class its header's
      `group-hover/panel:opacity-100` depends on, so the button sat at `opacity: 0`
      permanently — and opacity does not disable pointer events. A stray click made a panel
      vanish mid-demo with no visible control to blame. *One class.*
- [x] **The medium-urgency badge on "Needs your attention" rendered grey.**
      `Dashboard.vue:188` used `theme="orange"`, which is not in Badge's enum, so it
      degraded to neutral beside the red ones — the warning tier was invisible. *(~15 more
      `theme="orange"` Badges elsewhere are a frappe-ui-v1 migration miss; see below.)*
- [x] **The "Assign to the record owner" switch lied and ate the first click.**
      Stored `0`/`1`, bound raw into a control that compares strictly against `true`: it
      looked on, announced `aria-checked="false"`, and the first click meant to turn it off
      did nothing visible. It also had no accessible name.
- [x] **Dashboard Save and Reset failed silently.** Neither declared `onError`, so a
      permission or validation failure stopped the spinner and said nothing — the manager's
      arrangement is gone on the next reload with no clue why.
- [x] **The dashboard filter bar could not wrap**, so on a narrow viewport the user filter
      was pushed past the edge and clipped by `overflow-hidden` — unreachable, not
      scrollable. Every other filter bar in the app already wrapped.
- [x] **SECURITY.md declared the shipping version unsupported** — the table said 2.x while
      `__version__` is 3.0.0, so a researcher would read 3.x as out of scope.
- [ ] **Reports shows a shimmering skeleton forever when the report list fails or is
      empty.** `Reports.vue:337` only sets `active` inside `onSuccess`, and returns early on
      an empty list, so the fetch watcher never runs and the pane falls to a
      never-resolving `SkeletonTable`. Below 640px the rail carrying the `ErrorState` is
      hidden, so there is **no error message anywhere on screen**. **1 h.**
- [ ] **Native `window.confirm()` on two Vectora surfaces** — `Planner.vue:561` (fires on
      every week arrow and rep switch while dirty) and `AutomationRules.vue:346`. Chrome
      renders these as `localhost:8080 says…`, which reads as unfinished. `ui/ConfirmDialog`
      already exists and is used elsewhere. **AutomationRules trivial; Planner ~0.5 day**
      (the route guard must return a promise).
- [ ] **Sales Targets and Automation Rules are the only Vectora surfaces with no
      loading/error primitives** — a bare spinner and frappe-ui's `ErrorMessage`, which on a
      transport failure renders the literal string "Failed to fetch" with no retry.
      `SkeletonTable`'s own docstring names the quota table as a call site it does not have.
      **30 min each.**
- [ ] **The Sales Targets grid never shows an exact figure or a currency.** Every cell,
      including the wide sticky Year and Team totals, goes through compact notation —
      249,900 and 250,400 both read `250K`, and a target of zero reads `—`. The only exact
      digits appear inside a focused input. CSV export formats the same money properly, so
      the two surfaces disagree. **1 h.**
- [ ] **Headline stat tiles print raw integers** (`1234`, not `1,234`) directly above a
      chart grid that compacts the same magnitudes to `1.2K`. The delta beside them *is*
      carefully formatted. No wrong numbers today — every value is pre-rounded server-side —
      but the panels bypass the `formatCell` the Reports page uses for identical columns, so
      they will drift the moment the backend stops rounding. **1 h.**
- [ ] **Dates are hardcoded to `en-US`** in `utils/dashboard.ts:24`, and the range
      connector `" to "` is untranslated. **30 min.**
- [ ] **The dashboard range button stays English** — `__(preset)` on a runtime string the
      extractor never sees, while the dropdown items beside it translate correctly.
      `Reports.vue:293` already has the fix; back-port it. **20 min.**
- [ ] **Automation Rules shows internal doctype names** — "CRM Deal" / "CRM Lead" in the
      dropdown and at the head of every rule summary, where the rest of the product says
      "Deal" / "Lead". Five option sets are untranslated. **30 min.**
- [ ] **The Dashboard chart grid is a fixed 20 columns**, so between roughly 640 and
      1000px — where the desktop layout is active and Dashboard *is* in the nav — a number
      card gets ~80px and truncates to nothing. **0.5 day.**
- [ ] **The Reports rail claims to be a tablist but implements none of it** — no
      `aria-controls`, no `tabpanel`, no roving tabindex, no arrow keys. Either implement
      the pattern or drop the roles and let it be a nav of buttons. **1–3 h.**
- [ ] **Panel reordering is built and unit-tested but has no UI** — `movePanel` in
      `dashboardHome.js:307` is imported by nothing, and `applyPanelPreference`'s `order`
      branch is unreachable because only `hidden` is ever written. **Decide: wire or delete.**
- [ ] **~15 more `theme="orange"` Badges across the app** degrade to grey the same way,
      including the "Not Saved" badge in Settings. **1 h.**
- [ ] **The root README is unmodified upstream Frappe CRM** — Frappe logo, `<h1>Frappe
      CRM</h1>`, a badge pointing at `frappe/crm`, and a live-demo link to
      frappecrm-demo.frappe.cloud. The repo is public and will be shown to clients as
      Vectora. `pyproject.toml` and `hooks.py` carry upstream metadata too. **2 h.**
- [ ] **Vendor URL drift** — `AboutModal.vue:51` and five other places link to frappe.io,
      github.com/frappe/crm and support.frappe.io. The most visible rebrand leak. **1 h.**
- [ ] **Invitation email ignores the brand variable it is handed** — the controller passes
      `title="Vectora"`, the template hardcodes it and never uses `{{ title }}`. First email
      every new user receives. **30 min.**
- [ ] **Event reminder email is untranslated and interpolates user content into HTML
      unescaped** (`event.py:326`), in Bootstrap blue rather than the Vectora palette. **2 h.**
- [ ] **~126 unwrapped English strings across 33 components**, worst on the Activities
      empty states (every Lead/Deal/Contact timeline) and ~45 filter operator labels. **1 day.**
- [ ] **Twilio callback URL built by substring-matching `":8"`** — copy-pasted in two files;
      a site on `:8443` silently loses its port. **30 min.**
- [ ] **Skeleton/error states cover only the new surfaces** — legacy list views still use
      frappe-ui defaults despite `EmptyState.vue` documenting the three-state contract. **2–3 d.**
- [ ] **Dashboard rate limit is tuned as if it were one call per load** — the tile row fires
      5 concurrent `get_chart` calls, re-fired on every filter change, against a 60/min cap.
      429s on a manager's dashboard mid-demo. **1 h.**
- [ ] **~30 empty scaffold test classes**, including `crm_form_script`, `crm_fields_layout`
      and `crm_sales_hierarchy` — the doctypes behind the public API and the permission
      model. **Counted by discovery, contributing nothing.**

## P4 — Platform work beyond the pilot

The longest dependency chain in the codebase, roughly 3–5 weeks sequential, none of it
user-visible except the last:

`Phase 3B full decouple` → `Phase 4 getMeta single source of truth` → `Phase 6A
programmatic layout` + `6B usePermLevel` → `Phase 5 scripting DX rethink`

Phase 3B and Phase 5 both have open design questions that need a maintainer decision before
work starts. Also here: MCP transport (needs an auth story mapping an MCP client to a Frappe
user — the hard part, not the adapter), the assistant tier (one sentence of spec; hard-gated
by the injection findings since it is by definition write-capable), inter-script
communication, conditional field injection, list-view scripting, and a discoverable
keyboard-shortcut sheet.

---

## Documentation drift found along the way

Fix these when touching the surrounding docs, not as a work item of their own: `SPEC.md`
and `AGENTS.md` claim 118 tests (actual 359) and CLAUDE.md says coverage spans four utils
files (actual ten); `feats/agent/README.md` says plans for MCP/enrichment-fallback/assistant
"live in docs/superpowers/plans/" — they were never written; the same file cites "PLAN.md
Phase 8, constraint 4", which was deleted; `feats/suggestions/README.md` presents
`summarise_thread` and `get_dismissal_stats` as user-facing when neither is reachable;
ARCHIVE's two deferred Phase 7 items never made it into PLAN.md's backlog;
`SkeletonTable.vue` names quota and planner tables as callers that don't import it.
