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

## Where it stands (2026-08-18)

| | open | note |
|---|---|---|
| **P0** security / data integrity | 1 | remote email images — deferred by decision, nothing built |
| **P1** release / CI integrity | 0 | |
| **P2** completeness (the mandate) | 0 | |
| **P3** client-facing polish | 0 | |
| **P4** beyond the pilot | — | out of scope by definition |

**98 closed, 1 open.** Every planned feature is built, and the polish list is now empty.
The single open item is the P0 that was **deferred by an explicit decision** — remote
images in inbound email — so nothing is built against it by choice rather than by
omission.

That is the end of what can be closed from inside this container. Two things still need
someone other than me:

- the **pilot-only verifications** listed at the foot of this file — Twilio call
  recording, the Facebook connector and the injection/enrichment evals all need an
  account or a model endpoint this container does not have, so they are untested rather
  than working;
- the **read-only `onError` sweep**. The real figure is **126** resources without an
  `onError`, not ~92, and the reason given for deprioritising them — *"those degrade to an
  empty control rather than a false statement"* — **was wrong**. The entry below fixes the
  eight places where it was wrong.
  Being precise about what has and has not been checked, so this does not become the next
  unverified claim:
  **Swept exhaustively, two classes.** Every count-gated badge (2 — both lied, both fixed)
  and every component rendering `<EmptyState>` (25 scanned, 6 with no error branch — all
  fixed).
  **Checked and found to be a different failure, one class.** Settings panes bound to a
  `createDocumentResource` — `GeneralSettings`, `DashboardSettings` — fail by *crashing*,
  not by lying: frappe-ui's `documentResource.onError` sets `doc = null` and the templates
  dereference `settings.doc.x`. Loud rather than silent, and upstream code. Worth knowing;
  not the same danger.
  **Not exhaustively classified: the remaining ~118.** They are mostly option lists, link
  searches and submit-only resources, where an empty control really is the failure mode —
  but that is an expectation, not a finding, and it should be read as one.

---

## P0 — Security and data integrity

- [x] **Opening the Assistant settings page and pressing Save switched off every
      proactive suggestion.** The page read its fields with `frappe.client.get_value`,
      which returns `{}` for a Single nobody has saved — so on a fresh site every field
      arrived `undefined`, the page drew "Generate suggestions: off" with four blank
      thresholds *while the job was running happily on its defaults*, and saving wrote
      that fiction back: every Check and Int the admin had never been shown a value for
      landed as 0. `signals_enabled` → 0 turned the whole deterministic suggestion
      engine off, and all four thresholds collapsed to 1 day. An admin configuring a
      model endpoint had no way to know they had just killed the product's
      differentiating surface. **This had already happened to the dev site in this
      container**, which is how it surfaced: five `test_signals` tests were failing
      locally and passing in CI, because CI never saves those settings.
      `crm.agent.api.get_settings` now hands the page the *effective* configuration from
      the same dataclasses the job reads, and the save filters out anything undefined.
      A patch repairs sites already hit, keyed on the one fingerprint the broken write
      leaves — all four thresholds at 0, which no filled form produces and which carries
      no admin intent, since `SignalConfig` already clamps a 0 to one day. 8 tests.

      **Check on the pilot site:** the same save also zeroed `daily_call_budget`, and
      the code reads `<= 0` as *unlimited* — so the site-wide cap on model spend is off
      wherever this happened. Deliberately not repaired by the patch: unlike a zero
      threshold, a zero budget has a defined meaning, and guessing at intent there could
      re-impose a cap an admin removed on purpose. Worth an explicit look before the
      pilot points at a paid endpoint.
- [x] **The Twilio webhooks were authenticated by an identifier, not a secret.**
      `validate_twilio_request` compared the `AccountSid` in the request body against the
      configured one — but an Account SID is not a credential. It appears in the Twilio
      console, in dashboard URLs, and in the body of every webhook Twilio sends. Anyone
      holding one could POST to `update_recording_info` and rewrite a call log's
      `recording_url` to point a rep at audio of their choosing, or drive
      `update_call_status_info` to rewrite statuses. Twilio's real authentication is the
      `X-Twilio-Signature` HMAC, and nothing checked it. Now verified before the identifier
      comparisons, which are kept as defence in depth. The two in-tree comments claiming
      "webhook authenticity is enforced by validate_twilio_request()" were describing
      something the function did not do; corrected. **Not verified against live Twilio —
      confirm call recording and status updates still arrive during the pilot.** 7 tests
      sign requests for real (`RequestValidator` is deterministic), including the forged
      Account-SID case and the TLS-termination case that would otherwise reject genuine
      webhooks behind a proxy.
- [x] **Exotel's webhook token check was not constant-time**, on the one comparison
      standing in front of an unauthenticated endpoint. Now `hmac.compare_digest`, with
      both sides required non-empty so an unconfigured site cannot be talked into
      accepting a blank key. 4 tests.

- [x] **Three more unscoped realtime broadcasts, found by the same full scan.**
      `exotel/handler.py` published Exotel's raw passthru payload site-wide from an
      `allow_guest` webhook — `CallFrom`, the **customer's phone number**, delivered to
      every logged-in rep's browser for every call. `ExotelCallUI` filters on `AgentEmail`
      before showing the popup, but that decision happens after the data has crossed the
      wire. Now addressed to the agent, resolved from the call log, `AgentEmail`, or the
      `&agent=` the outgoing status-callback URL already carries; when none can be
      resolved it publishes nothing and logs, because silence beats broadcasting a
      customer's number. `whatsapp.py` now targets the record's room (the only component
      that listens, `Activities.vue`, is also the only one that `doc_subscribe`s), and
      `crm_customer_created` targets the acting user — Deal.vue listens for it but never
      subscribes to a doc room, so a doc-room publish would have reached nobody. 6 tests;
      no Exotel account here, so they exercise the addressing decision directly.
- [x] **Semgrep triage finished; the full scan is now a scheduled job.**
      CI's `semgrep ci` is a *diff* scan against the merge base, so nothing already in the
      tree can trip it — which is why several P0s sat there undetected. Every finding from
      a full local run now has a verdict, recorded inline next to the code rather than in
      a spreadsheet nobody opens.

      **Fixed rather than suppressed:** the hidden-column bug below; `override-doctype-class`
      (Contact and Email Template moved from `override_doctype_class` to
      `extend_doctype_class` — they only add the CRM list view's column set, and mixins
      stack where a controller override does not, so another app overriding Contact can no
      longer silently take the CRM's columns away; 3 tests);
      `frappe-enqueue-without-after-commit` on "Sync Now" (the worker re-reads the source
      from the database, so queueing before the request commits let it start against the
      old row, or none at all if the request rolled back).

      **Accepted with a reason on the line:** 7 `frappe-manual-commit` — install/migrate
      running outside a request, webhook audit trails that must survive the handler's own
      rollback, and call logs Twilio's follow-up webhooks look up by `CallSid` before this
      request has even responded. 2 `frappe-setuser` in `crm_form.py`, both halves of a
      snapshot/restore that only ever narrows privileges. 6
      `guest-whitelisted-method`: `get_translations`, `oauth_providers` and
      `accept_invitation` must be guest-reachable and expose nothing sensitive
      (`oauth_providers` decrypts a client secret only as an existence check and never
      returns it); `get_context_for_dev` is behind `developer_mode`; the two Twilio
      webhooks are authenticated by signature as of the item above. `live_demo.login`
      no-ops unless `demo_username`/`demo_password` are set in site config — **setting
      those on a production site is an authentication bypass by design**, now stated at
      the endpoint itself.

      `.github/workflows/semgrep-full-scan.yml` runs `semgrep scan` (not `ci`) over the
      whole tree weekly, on dispatch, and on every push to develop/main. **It is green at
      the commit that added it** — which was the precondition for adding it at all: born
      red against 25 untriaged findings it would have been ignored within a week.

- [x] **Event reminders were broadcast to every user on the site.**
      `event.py`'s `_send_system_notification` called `publish_realtime` with no `room`,
      `user` or `doctype`, which frappe resolves to `get_site_room()` — its own comment on
      that branch reads "This will be broadcasted to all Desk users". The payload carries
      the event's subject, description, owner and the participants' **email addresses**,
      so every logged-in rep got a popup for meetings they had nothing to do with, naming
      who was attending. Now one user room per recipient, sharing a single
      `_notification_audience` with the email path so the two channels cannot disagree
      about who an event concerns. **Found by running semgrep's full rule set locally —
      CI only diff-scans, so a pre-existing line like this can never trip it.** 4 tests.

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
- [x] **Forecast accuracy showed an in-tree manager the whole company's series.** The
      deferred half of the item above (decision, 2026-08-17). Snapshots were written per
      rep and site-wide only, and the reader picked a series by `user` alone — so a
      manager, who arrives with `user` unset, read the row with an empty user: the site
      aggregate. `CRM Forecast Snapshot` now carries a `scope` (`Rep`/`Team`/`Site`), the
      weekly job records a `Team` row for every hierarchy node with descendants, and the
      reader resolves scope from the caller. Team history cannot be backfilled — summing
      rep rows double-counts a deal owned by one member and assigned to another, and
      reflects today's ownership rather than the snapshot date's — so existing sites start
      accumulating from the next weekly run and the chart says so instead of looking
      broken. 8 tests in `test_metrics.py`.
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
      **Deferred by decision, not oversight** — raised with the maintainer and the call was
      to leave it as-is for the pilot. It stays open rather than closed because nothing has
      been built: the read receipt still fires. Worth revisiting before a client whose
      counterparties they would rather not tip off.
- [x] **Demo data contaminates forecast history irreversibly.** `hooks.py:97` seeded demo
      data on desk setup-wizard completion. A fresh site starts `setup_complete = 0`
      (verified against frappe's System Settings default), so any operator who opens desk
      on a production deployment is prompted for that wizard. `crm/demo/` never cleaned
      `CRM Suggestion`, `CRM Forecast Snapshot` or `CRM Rep Plan`, so hourly signals and
      weekly snapshots ran against fake deals and three fake users, and "Clear Demo Data"
      left immutable snapshots behind forever. One patch for contaminated snapshots had
      already shipped once. *Seeding is now opt-in via `crm_seed_demo_data`, gated at the
      hook so an explicit `bench execute` still works; the clear path removes derived
      suggestions, rep plans and forecast rows, and drops the Site/Team aggregates taken
      while demo data existed — those counted fiction and cannot be recomputed. Rows from
      before the seed, and real reps' Rep rows, survive. 12 tests; verified end-to-end by
      seeding, running the tier and clearing.*
- [x] **Two SSRF guards had diverged.** `integrations/api.py:183` (call-recording fetch)
      lacks the explicit multicast reject that `domain_enrichment/http.py:83` documents as
      necessary. The TODO at `integrations/api.py:213` says to share the helper "until
      enrichment ships" — it shipped. **1 h.**
- [x] **`get_assigned_users` was unscoped** (`doc.py:608`) — any user can enumerate who is
      assigned to any record. **15 min.**

## P1 — Release and CI integrity

- [x] **A hidden list column that followed another hidden one stayed visible.**
      `crm/api/doc.py` dropped hidden columns with `columns.remove(column)` from inside
      `for column in columns`. Removing from the list being iterated moves every later
      element down one, so the loop skipped the next: with two hidden columns adjacent in
      a saved view, the second was never examined. A field an admin had hidden kept its
      place in the list view and kept being fetched. Only triggers on a customised site —
      stock CRM Lead has exactly one hidden field — which is why it survived. Rebuilt as
      a new list; `rows` is unchanged, so what the query fetches is untouched. 4 tests,
      the regression one failing against the old code. Found by the full semgrep run
      below, not by CI.
- [x] **The plan-adherence scoping test failed every Monday.** `test_metrics.py:593`
      lacked the settled-day guard its sibling in `test_reports.py:83` has, so the one test
      protecting against cross-team leakage cried wolf weekly — and passed for the wrong
      reason on the other six days.
- [x] **Nothing gated merges.** `develop` is now protected and requires the three checks
      that run on *every* PR — Semantic Commits, Semgrep Rules, Pre-commit Checks. The
      others (`server-tests`, `frontend-tests`) carry `paths-ignore`, so requiring one
      would leave a docs-only PR waiting forever on a check that will never report.
      `main` is deliberately left unprotected: the release flow pushes a version-bump
      commit as `github-actions[bot]`, which is not an admin, so required checks there
      would break releases. Admins are exempt and no review is required, so the gate
      catches red merges without blocking a single maintainer.
      `.mergify.yml` is deleted — inherited from upstream, it auto-closed any PR to
      `main` whose author was not one of four *upstream* maintainers (so the owner's
      own), and backported to `main-hotfix`, which does not exist. Mergify is not
      installed; the config was inert cruft that would misfire the day someone added it.
      `codecov.yml`'s `if_ci_failed: ignore` reported coverage green exactly when CI had
      failed; it now errors.
- [x] **The e2e suite is green in CI and now blocks.** 18/18, and `continue-on-error`
      is gone. Three stacked faults, each hiding the next, none of them reproducible
      locally:
      **(1)** CI serves the site at `crm.test`, and the login spec waited on `/\/crm/`,
      which matches the `//crm` in that *host* — so the wait returned instantly on the
      login page. On `localhost` the same regex is accidentally correct.
      **(2)** The workflow's Email Account was never created: `bench console` is an
      interactive REPL, a piped multi-line block is echoed as continuation lines and
      never runs, and console exits 0 regardless — so the setup step went green with no
      account, and every send returned 501. (`smtp_server: localhost` would have been
      the next failure, since that value makes frappe open a live SMTP connection.)
      **(3)** CI built only the crm app's assets. The login page is served by *frappe*
      and its submit handler is in frappe's bundles, so clicking Sign In did nothing at
      all — no request, no error. A dev bench has those assets already, which is why no
      local run could ever reproduce it.
      Each was found only after making the layer *report* rather than guessing at a fix:
      an assertion on the setup, and response observers on login and send.
- [x] **The Playwright suite had never run in CI.** `ui-tests.yml:6` triggers only on
      branch `main-hotfix`, which does not exist. **5 min.**
- [x] **The frontend coverage gate could not fail.** `vitest.config.js` scoped coverage to
      10 hand-picked `src/utils` files, so a PR adding an untested util contributed zero
      lines and the 85% patch target passed trivially. Now the whole pure-logic layer
      (`src/utils`, `src/composables`). The same 527 lines are covered as before — the
      denominator went from 556 to 1495, so the honest figure is **35%, not 94%**.
      Components stay excluded because there are still **0 component tests across 358
      `.vue` files**; that is the next item, not something to hide by pretending the
      covered set is the whole app.
- [x] **The production image was published only to mutable tags.** Every build now also
      publishes `sha-<short>`, which is immutable and always means exactly one commit, and
      `.env.example` defaults to a release tag instead of `stable` — so a host can say what
      it is running when somebody reports a bug. The upgrade runbook is updated to match:
      with a pinned tag, `docker compose pull` alone no longer upgrades anything, and
      saying so is the point.
- [x] **The image built against Frappe `develop`**, so the framework moved under us even
      when our own tag did not. Rather than migrate to a released frappe — which the app
      cannot take today, since `pyproject.toml` requires `>=16.0.0-dev` — frappe is forked
      to `Absolute-Insight/frappe` and pinned on a **`vectora`** branch frozen at a
      known-good develop commit. Every lane now uses it: the image build, server tests,
      the migration test and the e2e suite. That freezes exactly the pairing the suite has
      been proving, with no behavioural change, and it advances only when someone decides
      to move it.
      Two details worth knowing. `FRAPPE_BRANCH` was also erpnext's branch, so pinning it
      would have broken that lane — erpnext now has its own variable. And frappe_docker's
      Containerfile spends `FRAPPE_BRANCH` twice, once as the *builder image tag*
      (`frappe/build:<branch>`), which upstream publishes only for its own branch names;
      the builder is a toolchain rather than frappe source, so it is pinned separately.
- [x] **The builder toolchain image still tracked `develop`** (`frappe/build:develop`).
      Now pinned by digest, along with `frappe/base` — and pinning that second image was
      not housekeeping: the Containerfile derives **both** of its bases from
      `FRAPPE_BRANCH`, the earlier fix rewrote only the `builder` line, and
      `frappe/base:vectora` does not exist, so the next release build would have died on
      a manifest-not-found error far from its cause. Caught by reading the upstream file
      rather than by CI, because `builds.yml` runs only on push to `main`. The step now
      **asserts** no `FROM` still resolves through `FRAPPE_BRANCH`, so a stage upstream
      adds tomorrow fails loudly here instead of silently. Both digests verified to be
      multi-arch indexes (amd64 + arm64) — pinning a per-architecture manifest would have
      broken the arm64 half. **How to advance frappe:** move
      `Absolute-Insight/frappe@vectora` to a newer upstream commit, let CI run, merge only
      if green. **How to advance the toolchain:**
      `docker buildx imagetools inspect frappe/build:develop --format '{{.Manifest.Digest}}'`.
- [x] **No test gate on the image build.** `builds.yml` runs on push to `main` and on any
      tag, neither of which runs the suite, so a `workflow_dispatch` of a red commit was
      publishable outright. A `guard` job now blocks the build until the commit's checks
      are green: it fails on any failed check and refuses a commit with no test run at
      all, waiting rather than reading once because a tag build can start before the
      main-push checks have finished. Decision logic unit-tested across seven states.
      *Partial by construction:* it can only require checks that actually run on `main`
      (today, the e2e suite) — the `pull_request`-only workflows are absent on that SHA.
      Making it total means running the full suite on `main` too. **2 h.**
- [x] **CI's only build gate compiled against the `@framework/ui` stub.** `yarn build`
      with no bench fell back to no-ops behind a `console.warn` and reported green — so
      a bundle where the Data Import page renders nothing and every product event is
      dropped would ship looking healthy. The resolver now refuses unless
      `FRAMEWORK_UI_STUB=1` says so deliberately, and CI's job sets it, which records the
      limitation in the workflow instead of hiding it in a resolver. All three paths
      verified: real package builds, explicit stub builds, absent bench refuses.
      *(The gate still does not compile the real integration — that needs a bench in CI,
      which is a separate item.)*
- [x] **The migration test upgraded from upstream `frappe/crm`, not from a previous
      Vectora release.** Upstream has no `CRM Rep Plan`, `CRM Quota`, `CRM Suggestion` or
      `CRM Forecast Snapshot`, so every patch this fork ships ran against zero rows —
      `merge_duplicate_rep_plan_weeks` "passed" by having nothing to merge. The base is now
      this fork's most recent release tag, which is the upgrade a customer actually
      performs. The checkout fetches tags (a shallow one has none), and the job **fails
      loudly** rather than falling back to the PR's own code as its own base, which would
      pass while testing nothing. Also drops the inherited `main → version-15` mapping:
      `pyproject.toml` requires frappe `>=16.0.0-dev`, so that lane could only ever have
      been green by never running.
- [x] **No rollback path was documented, and upgrades served new code on an old schema.**
      The runbook now takes a backup first, turns maintenance mode on before `up -d` and
      off after `migrate` — `up -d` starts serving immediately while `migrate` takes
      minutes on real data, and new-code-on-old-schema is the one combination nothing is
      tested against. It also says plainly that **reverting the image is not a rollback**
      once patches have run, so the restore drill in the pilot checklist is the rehearsal
      for the only rollback that exists. Commands verified against `bench` rather than
      written from memory: `set-maintenance-mode` takes a single site (no `all`, unlike
      `migrate`/`backup`), and `--force` belongs to `restore`, not to `bench`.

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
- [x] **`summarise_thread` had no UI.** Fully built, tested, rate-limited, budget-capped,
      documented as user-facing — and called by nothing. Now a "Summarise thread" action on
      the per-record panel, on demand rather than on load because each press costs a model
      call. Rendered strictly as text: the summary is written from a thread a counterparty
      contributed to, and every model tested follows instructions embedded in an email, so
      there is no `v-html` and must never be one. Degrades like the rest of the tier —
      `disabled` and `unavailable` each get a sentence saying what to do instead. Verified
      in a browser against a live local model, not just compiled.
- [x] **`get_dismissal_stats` had no UI.** Now a panel directly under the thresholds it
      is evidence for: dismissals by signal, most-rejected first, with the reasons reps
      typed (rendered as text). The endpoint exists so "a threshold reps keep rejecting is
      visible rather than guessed at", and putting it beside the knobs is what makes that
      true. Empty state says what fills it, because on day one of a pilot it *is* empty.

### Local model support (explicitly mandated)
- [x] **No local inference service in the deploy stack.** *Verified: the core code already
      works* — `crm.agent.client.complete()` against ollama returns a schema-valid summary in
      **1.03 s warm** (9.46 s cold), guided decoding clean. So this is deployment work, not a
      rewrite: an opt-in compose profile, a weights volume, `base_url` on a service name
      (127.0.0.1 does not resolve from inside the backend container), keep-alive plus a boot
      warmup for the 9× cold-start penalty, and honest hardware guidance. granite-4.0-h-tiny
      is the verified-good model; MiniCPM5-1B must not ship (returns empty content). **2 days.**
- [x] **No Agent settings UI.** Eleven configurable fields, including every signal
      threshold, with no pane in Vectora's own Settings — an admin had to drop to the raw
      Frappe desk to tune a pilot's thresholds. Now **Settings → Assistant**, gated on
      `isAdmin()` rather than `isManager()` because `CRM Agent Settings` grants read and
      write to System Manager only; showing it to a Sales Manager would be a pane that
      errors on load. Read and written in one call each — the settings are a Single, and
      field-by-field writes would leave the tier half-configured if the fourth failed.
      `api_key` is write-only: a Password field reads back masked, so round-tripping it
      would save the mask.
- [x] **No way to validate an endpoint.** The only way to learn `base_url` was wrong was a
      rep clicking a feature and getting a degraded dialog — the failure reached a user
      before the admin who caused it. **Settings → Assistant → Test connection** now runs
      the real `client.complete()` path with a schema rather than a bare HTTP ping,
      because reaching the host proves nothing about guided decoding and that is the
      interesting failure: `MiniCPM5-1B` connects fine and returns empty content. Three
      outcomes are distinguished — reachable/schema/unreachable — since the fixes differ
      (the URL vs the model). Works with the tier off, so an endpoint can be proved before
      reps see it. Reads the *saved* settings, never a caller-supplied URL: that would be
      an SSRF with credential replay. System Manager only, rate-limited to 6/min, and the
      API key cannot appear in the result (asserted). Verified against stub endpoints for
      all four outcomes plus in-browser for the pass and fail renders.
- [x] **Default `base_url` was `http://localhost:8000/v1` — Frappe's own port.** Enabling the
      tier without editing it makes the CRM POST to itself and fail opaquely. **15 min.**
- [x] **Nothing enforces `timeout × 2 < PROXY_READ_TIMEOUT`.** An admin could set 300 and
      discover it in production: nginx hangs up at 120 while the worker runs on for
      another 480 s, and nothing in the CRM explains the failed request. Now refused at
      save, against `crm_proxy_read_timeout` (default 120, matching the shipped stack) —
      *refused* rather than silently clamped, because a form showing a number the system
      is not using is the same dishonesty as the failure it prevents. The message names
      both the largest usable value and the config key that raises it. An
      uninterpretable site-config value falls back to the shipped default rather than
      unbounding the limit.

### Mobile parity
- [x] **A rep on a phone gets none of Vectora's three differentiating surfaces.**
      Suggestions, Planner and Reports were all gated `!mobile` in `AppSidebar.vue`.
      **The estimate was wrong, and checking beat guessing:** the pages were already
      responsive — verified at 390px, the dashboard stacks its tiles, the planner falls
      back from a week grid to a day list, the reports table scrolls in its own
      container. They were routed and rendering, just absent from the one menu a mobile
      rep has, so the fix was un-gating three links rather than the "expensive" grid
      rewrite this item predicted. Suggestions needed real work: the desktop slide-over
      is 400px hung off the sidebar, so the list was extracted to `SuggestionsList.vue`
      and mobile gets a route and a page, following the Notifications precedent. Dashboard
      *editing* stays desktop-only — it is a 20-column drag grid, undraggable by thumb.
      Calendar stays gated on evidence: seven day-columns and a clipped toolbar at 390px.
- [x] **Calendar is unusable at phone width.** Confirmed in the browser at 390px before
      touching it: seven day-columns with "Sat 22" running off the edge, Mon 17's date
      badge colliding with its own label, and the toolbar overflowing so the user picker
      was sliced in half — *including the view switcher*, so the one control that could
      have escaped the week grid was among the things cut off.
      Day is now the mobile default, but only in place of Week. Day and Month both survive
      the width, and substituting a preference that still works would be taking a decision
      that is not ours. The toolbar wraps instead of clipping.
      **The first attempt regressed the desktop**, which is why this was checked in a
      browser at both widths rather than reasoned about: `flex-wrap` stops flex items
      shrinking, so at 1440px the view select and user picker jumped onto their own rows
      where one row had been fine. Wrapping is now `sm:flex-nowrap` — phone-only.
      Also fixed in passing: the view select's placeholder read `Operator`, a copy-paste
      leftover from a filter control.
- [x] **`isMobileView` never re-evaluates.** *Fixed:* a `matchMedia` listener, guarded
      for its own absence and for Safari < 14's `addListener`-only form. 7 tests;
      mutation-checked (the old implementation fails 4 of them). Original entry: `computed(() => window.innerWidth < 768)`
      over a non-reactive source: it caches on first read and nothing invalidates it, so
      rotating a phone or resizing a window does not change it. Used in ~10 components
      (`ViewControls`, `CustomActions`, `DataFields`, `MobileLead`, and now the calendar's
      default view). Nobody has hit it because the value is read at mount and a phone
      rarely changes class mid-session, but every one of those `v-if`s is written as if it
      were live. The calendar's *layout* deliberately uses CSS breakpoints instead, which
      are correct by construction. Making it a real resize listener is a small change with
      a wide blast radius — every consumer would start reacting to resize, which is what
      they already appear to say. **P3, 2 h + a pass over the consumers.**

### Error handling on inherited surfaces
- [x] **19 `call().then()` sites with no rejection handler.** Every new Vectora surface
      uses the `ErrorState`/`describeError` primitives; no inherited surface did —
      assignment, quick entry, inline edit, saved views, bulk actions, and reps spend most
      of the day in those. Now 20 handlers via `actionErrorMessage`, the action-shaped
      counterpart to `ErrorState`: the server's own sentence wins, falling back to copy
      chosen by `kind`, and it never claims the change was not made — a dropped connection
      can still have reached the server, and that reassurance would send a rep to redo
      saved work. 10 unit tests.
      **The count was three too high and one category short.** `DeleteLinkedDocModal`,
      `CallLogDetailModal`, `Users` and `FilesUploader` already had handlers. But grepping
      for `.then(` missed resources submitted without an `onError` — found only by forcing
      a real 403 in a browser, where the record-page **assign** failed with nothing but a
      console line. That one was worse than silent: the assignee list is edited
      optimistically, so a rejected assign left the avatar on the record showing an
      assignment that never happened. It now rolls back and reports. `CalendarEventPanel`'s
      existing handler read `err.messages[0]` unguarded and threw a second error inside the
      catch on any rejection without that array.
- [x] **Resources submitted with no `onError` are a second, unenumerated category.**
      Swept: **157** `createResource`/`createListResource`/`createDocumentResource`
      declarations across 100 files.
      **The obvious metric was the wrong one.** Counting declarations without an `onError`
      key gives 130, and that number is close to meaningless — a resource also handles
      failure by exposing `.error` for the template to render (`StatTile`, `ErrorState`),
      by taking `onError` inline at the `submit()` call, or by being awaited inside a
      `try`. `AssignToBody`, `LeadModal` and every dashboard chart come back "unhandled"
      under that test and are all fine. The question worth asking is whether a rejection
      reaches the user, not whether one particular key is present.
      Re-triaged on that basis: **8 candidates that mutate or mislead**, of which 4 were
      real. Two were bugs rather than missing messages:
      - `SlaPolicyView` caught a failed rename and then *carried on*, refetching under the
        new name that does not exist, unawaited — then fired `toast.success('SLA policy
        updated')` unconditionally. A failed rename showed an error toast and a success
        toast, in that order.
      - `AssignmentRuleView` had the same shape, and there the unhandled rejection skipped
        the `isLoading = false` two lines below it: the spinner stayed up until reload.
      - `ERPNextSettings.productSyncStatus` falls back to `{}` on failure, so every tab
        rendered its empty copy — an admin checking whether the product sync had broken
        was told **"No failed syncs"** by a panel that had not managed to ask. Now an
        `ErrorState` ahead of the sections, with retry.
      - `demoData.clearDemoData` closed its confirm dialog and reported nothing on
        rejection, which looked identical to a slow success.
      **What remains, and why it is not a defect list.** ~92 read-only resources still have
      no explicit handler — mostly tab layouts, link-field option lookups and dropdown
      fetches, where failure degrades to an empty control rather than a false statement.
      The subset that *would* matter is the one where empty renders as a confident "none";
      those are the Vectora surfaces, and they already use `ErrorState`. Worth a pass, but
      it is polish, not a lie: **moved to P3.** The sweep script is heuristic (regex over
      brace-matched blocks) and is a candidate list, not an oracle — every fix above was
      confirmed by reading the call site.
- [x] **Two endpoints returned `"success"` when they did nothing.** `remove_linked_doc_
      reference` skips items the user cannot write and items that fail validation;
      `delete_bulk_docs` hands anything over ten records to a worker. Both answered
      `"success"` to every one of those, so the modal closed, the list reloaded, and the
      records were still there with no reason given. They now return what happened —
      `{unlinked, skipped}` and `{queued, count}` — and both modals report it, including
      the honest "deleting in the background" for the queued case. Tested: over ten says
      queued, under ten says done.
- [x] **Form Script `onValidate` failures abort the save with no feedback at all.**
      `document.js` caught and returned with only a `console.error`. The guide states the
      contract outright — "Throw a `new Error` (or call `throwError`) to block the save —
      the error message is shown as a toast automatically" — and only `throwError`
      delivered it, because it toasts on its way out. A plain `new Error`, *the idiom that
      sentence lists first*, left the rep pressing a save button that did nothing. The
      documentation described behaviour the code did not have. Now reported via
      `validationErrorMessage`; `throwError` marks its error so the message is not shown
      twice. Deliberately does **not** fire the script's `onError` hook: SPEC.md scopes
      that to "when a save fails", and a validation block means the save never started.
      Verified in a browser with a real Form Script: plain throw toasts, `throwError`
      toasts exactly once, and both still block the write.
- [x] **File-upload promise can hang forever.** `filesUploaderHandler.ts` parsed a 403 body
      as JSON unguarded, and Frappe answers 403 with an HTML sign-in page often enough that
      this was not an edge case. The throw escaped `onreadystatechange` without reaching
      `reject`, so the promise never settled — spinner forever, no error, for the life of
      the tab. A second unguarded parse of `error.exc` could do the same on any status.
      Both guarded, `reject` now unconditional, and the 413 branch keeps its own sentence
      rather than echoing nginx's HTML. 9 tests.

### Feature gaps
- [x] **Facebook lead sync drops paginated leads permanently.** `facebook.py:73`
      (`limit: 100000, # TODO: pagination`) never follows `paging.next`, and `:39` advances
      the watermark unconditionally — overflow leads are dropped *and* never re-fetched.
      **Disabled rather than fixed** (decision, 2026-08-17): the connector is now gated on
      `crm_enable_lead_syncing` in site config, default off, blocking the background jobs,
      the "Sync Now" button and the `enabled` checkbox, and hiding the settings tab.
      Six tests in `test_lead_sync_source.py` pin the switch. **The underlying pagination
      bug is untouched** — the work below still stands whenever Facebook lead ads matter.
- [x] **Facebook lead sync no longer drops leads.** Two bugs holding hands:
      `fetch_leads()` asked for a page of 100000, ignored the paging cursor Graph
      answered with, and `sync()` then moved the watermark to `now()` regardless. Either
      alone is survivable; together, a form with more new leads than fit one page handed
      back a partial batch and the rest were marked synced without ever being asked for
      — not queued, not retried, not logged, and the run reported success. Silent in
      exactly the case that matters: a campaign doing well enough to overflow a page.

      `fetch_leads()` is now a generator that follows `paging.next` to the end, and the
      watermark advances only as far as a lead the run actually handled — so a failure on
      page four leaves pages one to three imported and the mark sitting exactly there.
      Two details worth naming: the cursor is a URL out of a response body **carrying the
      page access token**, so its host is checked before every hop; and the mark is set
      one second *behind* the newest lead, because `time_created` is second-granular and
      the filter is strictly greater — a lead created in the same second as the last one
      seen would otherwise never be asked for. The deliberate one-second overlap is
      absorbed by an id-based `already_imported` check that skips silently, so it cannot
      bury the real duplicates in the failure log.

      Also found: creating a Lead Sync Source calls Facebook from `before_insert`, so the
      existing suite was making live outbound requests. Patched off in the tests.

      15 tests, Graph stubbed. Mutation-checked — restoring either original bug fails
      them (3 tests and 1 test respectively).

      **The connector stays switched off.** The reason it was disabled is fixed, but
      none of this has run against a live Facebook account, and the gate's message now
      says that rather than describing a bug that no longer exists. Flipping
      `crm_enable_lead_syncing` is a decision for whoever has an account to point at it.
- [x] **Scheduled re-enrichment.** Enrichment had two triggers — the button and
      record creation — so data captured once was never refreshed; a pilot running for
      months would be reading whatever a company's website said the day the record was
      made. `tasks.reenrich_stale_records` on `daily_long`, off unless
      `scheduled_reenrichment` is ticked, tuned by `reenrich_after_days` (90) and
      `reenrich_batch_size` (25).

      The selection rule is the part worth reading. Staleness comes from
      `CRM Enrichment Run` history, **not** from scanning the doctype: a record that
      has never been enriched is not stale, it is untouched, and sweeping those in
      would mean ticking one checkbox crawls every website in the CRM that night. The
      newest run counts whatever its status, so an uncrawlable site is retried on the
      sweep's cadence rather than nightly. Oldest first and capped, so a backlog is
      worked through over days. Independent of `auto_enrich`, so an admin can decline
      to crawl every new record and still keep the enriched ones fresh. Queued through
      the shared `enqueue_enrichment`, whose per-document `job_id` + `deduplicate` stop
      a sweep racing a rep who just pressed Enrich. Scheduled runs publish no realtime
      progress — nobody is waiting, and the alternative was a progress stream to a user
      who never asked (or, worse, a site-wide broadcast).

      16 tests. The negative cases each carry a control record that must still be
      swept, so "the sweep found nothing" cannot pass for "the sweep correctly declined
      this one". Two mutations checked: dropping the staleness cutoff fails 3 tests,
      reversing the ordering fails 1.

      **Note for the pilot:** enrichment settings remain desk-only — there is no
      Settings pane for them, unlike the assistant and digests.
- [x] **Segment analytics.** The dashboard could say *where* deals were (territory) and
      *who* owned them, but not **who we sell to**. Two charts —
      `deals_by_industry` and `deals_by_company_size` — plus a `pipeline_by_segment`
      report that reuses the charts' own aggregates, so the report and the dashboard
      cannot disagree about the same number. Both charts are in `CHARTS` and in the
      add-chart modal; the report is in `REPORTS` and therefore schedulable as a digest.

      Two things worth reading:

      **Company size is ordered by the field's declared option order, not by the label.**
      Sorted as strings those values run `1-10, 1000+, 11-50, 201-500, 51-200` — an axis
      that reads as a size ordering and is not one. Every individual number stays correct
      while the shape of the chart lies, which is the worst kind of wrong for a chart.
      The test fails against the alphabetical version.

      **An unanswered employee count was silently recorded as `1-10`.** Frappe
      pre-selects the first option of a Select that declares no default, so
      `no_of_employees` on Deal, Lead and Organization stored the smallest band for every
      record where nobody answered. On this container's data that is **1012 of 1044
      deals** — a company-size chart built on it would have reported almost the entire
      pipeline as micro-businesses and called it a finding. All three fields now lead
      with a blank option, so unset stays unset. 13 tests.

      **Note for the pilot:** rows written *before* this fix cannot be told apart — a
      stored `1-10` may be a real answer or an unanswered one. Read the earliest months
      of a company-size chart with that in mind on any site that predates the upgrade.

- [x] **Territory filter on dashboard and reports.** A manager could not scope either
      analytics surface to a region. Now they can, and — the part that took the design —
      the three charts and two reports that *cannot* say so on their face.

      The obvious seam was `scope_deals`/`scope_leads`, which every chart calls. Except
      five don't: `plan_adherence`, `quota_attainment`, `forecasted_revenue`,
      `forecast_accuracy` and `deals_by_stage_axis`. A filter hung there would have
      applied to 19 charts of 24 **silently**, putting one region's pipeline beside the
      whole company's quota attainment with both looking equally scoped.

      So `territory` is an explicit parameter on every chart, every report and the three
      shared helpers they delegate to. Three charts (`plan_adherence`,
      `quota_attainment`, `forecast_accuracy`) and two reports (`plan_adherence_by_rep`,
      `quota_attainment_by_rep`) genuinely cannot slice by it — rep plans have no
      territory, quota is per rep per month so filtering only the closed-won side would
      divide one region's revenue by the global target, and `CRM Forecast Snapshot` has
      no territory dimension without re-snapshotting history. They are named in
      `TERRITORY_BLIND`, return `territory_filtered: false`, and the UI prints
      **"Not filtered by <territory>"** on the tile, the chart and the report.

      **The test that makes the exception list worth anything:**
      `test_every_chart_that_claims_to_filter_actually_filters` runs every non-blind
      chart against two territories holding deliberately different data and fails if any
      returns the same answer for both. A chart can accept the parameter, advertise
      `territory_filtered: true` and drop it on the floor with nothing visible from
      outside — that is the only thing standing in front of it. Its twin does the same
      for reports. Building the fixture was most of the work: the first version compared
      only the `data` key and so passed every number tile silently, and equal-sized
      samples made several averages agree by coincidence.

      Verified in the browser: filtering to a territory took Open deals 675 → 21 and Won
      deals 256 → 13, while Plan adherence and Quota attainment kept their figures and
      said why. Mutation-checked by making one chart ignore the parameter — the test
      names it. 15 tests.
- [x] **`quota_attainment_by_rep` could not be scheduled.** The digest doctype's Select
      hardcoded four of the five registry reports, so the one report a sales manager most
      wants mailed to them was simply not on offer — and nothing failed to say so. Added,
      and the drift is now impossible to repeat: a test asserts the Select's options equal
      `REPORTS` exactly, another renders every option through the digest template, and
      `validate()` refuses a digest naming a report the site does not publish (the send
      loop skips an unknown key silently, which is right for a withdrawn report but would
      turn a typo into a digest that never arrives and never complains). The
      options-vs-registry test fails against the pre-fix tree, which is how it was
      checked. 12 tests.
- [x] **Report Digests now have an admin UI.** They were desk-only, so a pilot customer
      could not schedule one without a Frappe Desk login — a shipped feature that was, in
      practice, not reachable. `Settings → Automation & Rules → Report Digests`: list with
      an enable toggle, create/edit dialog, delete behind `ConfirmDialog`. The report
      dropdown is populated from `crm.api.reports.list_reports`, the same endpoint the
      Reports page uses, so a report added to the registry appears here without this
      component being touched. Uses `Skeleton`/`ErrorState` and `actionErrorMessage`
      rather than a bare spinner, and deliberately does *not* add a third
      `window.confirm`. The server's own validation message is what surfaces on a bad
      recipient — "stranger@example.com is not an enabled user of this site" names the
      address to fix, which a generic fallback would not. Verified end to end in the
      browser in both themes: create, reject, list, toggle, delete, empty state.
- [x] **Custom report builder.** Seven dimensions × five measures × four status scopes,
      as a rail entry on the Reports page rather than a page of its own — it returns the
      same payload shape as a built-in, so the table, CSV, print sheet, territory note and
      stale-payload guard are reused rather than rebuilt.
      **Scope read, stated because PLAN.md's entry is one line.** "Custom report builder
      UI", precondition "the five built-in reports have proven the metrics layer" — read
      as a dimension × measure builder over that layer rather than saved filter presets.
      The larger reading, which subsumes the smaller one if it was wrong.
      **How the one-source-of-numbers rule is actually kept.** `reports.py` forbids
      building a second aggregate, and a generic builder is one by construction — so the
      rule is held by measurement instead of by architecture: `ConformanceTest` asserts the
      builder produces identical numbers to `pipeline_by_stage`, `get_deals_by_source`,
      `get_deals_by_territory` and `get_deals_by_industry` for every pair they both
      compute. Mutation-checked. Each comparison matches its built-in's own semantics —
      the stage report is a periodless snapshot, the source and territory charts count
      deals *created* in a period across all statuses — because a suite comparing two
      different questions would pass while proving nothing.
      Confirmed in the browser as well as in tests: stage × deals returns 605/360, the same
      figures the built-in pipeline report shows on this site.
      **A test that passed for the wrong reason, again.** Deleting `scope_deals` — the
      permission guard, and the most security-sensitive line in the module — left all 29
      tests green, because a plain Sales User is pinned by `pin_user` and `belongs_to` does
      the filtering instead. The case that exercises it is an in-hierarchy Sales Manager,
      who is pinned to nobody. Found by mutation, not by reading.
      Dimension, measure, status scope **and the date column** are each validated against a
      closed registry before reaching a query, because all four become SQL. A realised
      measure refuses an open scope rather than switching it silently.
- [x] **The injection evals are codified.** The finding they record —
      **every model tried follows the injected instruction**, on the summariser and on
      the draft tier — existed only as a prose table produced by hand. A property nobody
      can re-measure quietly stops being true, and this one is load-bearing: it is the
      reason the agent tier has no write path and the reason a draft is something a
      human sends.

      `crm/agent/evals/cases.py` holds the corpus (a negotiation thread that is plainly
      going badly, three payloads, four tells); `runner.py` drives them against the
      site's configured endpoint and prints the same table. **Deliberately not a
      pass/fail gate** — a suite that is red on every model gets switched off within a
      week — so it emits a rate, and the number to watch is which model lands fewer.

      Two arms per case, always. A tell that fires on the *clean* thread is a broken
      tell, not a compromised model, and the report says `TELL BROKEN` rather than
      counting it; without that arm the whole suite could report total compromise
      against a detector that matched anything. A run against an unreachable endpoint
      reports `DID NOT RUN` and `Nothing was measured` — the first draft printed
      "0/4 cases landed", which reads as a clean bill of health for a model that was
      never asked anything.

      23 CI-safe tests drive every branch of the runner against a stubbed model, plus
      corpus checks (each payload really is added to its thread and really does attempt
      an override; a fence-free payload case still exists, since the claim that the
      fence is not what is being defeated rests on it).

      **No fresh measurement:** there is no model endpoint in this container. The
      existing hand-run numbers stand; re-run the suite on the pilot host once its
      endpoint is up.
- [x] **Enrichment fallback extractor** (+ golden-set evals). `model_fallback.py` asks the
      local model for the fields the rules could not read, off by default and behind its
      own switch — enabling the assistant tier is consent to send your own conversations
      to your endpoint, not consent to send it the contents of other people's websites.
      The three constraints are the feature; the extraction is the easy part:
      - **Fills blanks only.** A rule fired by admin config outranks an inference, so a
        field the rules answered is never sent and never overwritten.
      - **Industry is a choice, not an answer.** `mapper` auto-creates missing Link
        masters, so an invented industry does not fail loudly — it silently adds a row to
        the site's `CRM Industry` list. The model picks from the admin's own list and the
        answer is re-checked against it server-side. Guided decoding constrains shape,
        never truth.
      - **The page is hostile text** — HTML from a stranger's web server, chosen by
        whoever typed the website in. Fenced, markers neutralised, and the reply treated
        as data.
      Values arrive labelled `Method.MODEL` so a reviewer can tell inference from
      extraction. Both guards mutation-checked. Every degraded path lands on the blanks
      the rules produced.
      **The golden set is scored as a confusion matrix, not a hit rate.** "Fills more
      fields" is the wrong thing to optimise: a model that answers everything fills every
      field and fills some with fiction. Half the cases are *abstention* cases where the
      right answer is blank. `missed` is the failure this feature is allowed to have;
      `wrong` and `hallucinated` are the ones that write falsehoods onto a record.
      Two bugs found by reading the report rather than trusting green tests: the scorer
      counted every *correct* description as an invention (a case wanting a description
      carries `description_must_mention`, not a sentence, and the absent key read as
      "expect blank"), and the field-selection condition ignored `name`, so any case
      wanting a description was scored on all three fields. The unit test that should
      have caught the first passed `expected="x"` — a shape no real case has.
- [x] **Three dashboard tests assert absolute averages and fail on any site with data.**
      ~~`test_dashboard.py:158,224,588` hardcode `89285.71` and friends.~~ **Stale — the
      rewrite this entry describes went on to cover these three too, and the entry was
      never updated.** Verified rather than assumed: all 40 tests pass against this
      container's site, which holds 1140 deals and 1225 leads against a 35-lead fixture —
      the "long-lived site" condition the entry says turns them red. The two surviving
      literals (`89285.71`, `109482.76`) are asserted against
      `crm_deal/test_records.json` — the fixture *definition*, a file that cannot drift —
      which is exactly what the file header prescribes. Mutation-checked: adding 1 to one
      Won fixture value fails the guard, so it is a real assertion and not a vacuous one.
- [x] **Duplicated thresholds.** Five copies, not two. `signals.py` restated all four of
      `SIGNAL_DEFAULTS`' thresholds as module constants and `predict.py` kept a fifth copy
      of `CLOSE_HORIZON_DAYS`; the constants now derive from `SIGNAL_DEFAULTS`, and
      `predict` imports the one in `signals`.
      The `CLOSE_HORIZON_DAYS` split was the live bug: `find_close_date_at_risk` took the
      admin's `cfg.close_horizon_days` while the `slip_risk` health factor used the
      hardcoded 14, so widening the horizon in Settings moved the nudge and left the score
      alone. `score_deal` now takes `close_horizon_days` as a parameter — it stays pure, so
      its tests still need no site — and both callers pass the configured value. Verified
      against the running site: at 14 a deal due in 20 days does not fire `slip_risk`; at
      30 it does.
      New guards in `crm/agent/tests/test_thresholds.py`, both mutation-checked: the module
      constants must equal `SIGNAL_DEFAULTS`, and `HEALTH_AT_RISK` in `suggestions.js` is
      *parsed out of the file* and must equal `AT_RISK_BELOW` — a second copy of the number
      in the test would have been the very thing being guarded against.
- [x] **"At risk" names two different populations.** *Fixed:* the tile is now
      "Critical deals", matching the badge's word for the band it counts. Renamed rather
      than recounted -- changing it to count `< 70` would move a number managers may
      already be using, while the label moves nothing and makes it true. Guarded in both
      directions. Original entry: Found while unifying the constants
      above, and not fixed there because it is a product decision rather than a drift. The
      dashboard tile counts `health_score < 40` and calls it *Deals at risk*; the record
      badge calls 40–69 *At risk* and reserves *Critical* for `< 40`. So the tile's
      population is exactly the badge's **Critical** set, and a deal the record page badges
      "At risk" is not in the tile at all. A manager reading "8 deals at risk" beside a list
      of thirty "At risk" badges is being told two different things. Fixing it means either
      renaming the tile to *Critical deals* (a label change) or counting `< 70` (a number
      change, and a large jump) — **needs a call on which.** The boundary itself is now
      pinned across both languages, so whichever way it goes, the two sides move together.
- [x] **Six inline scoring literals order every rep's queue.** All six in `signals.py` are
      now named constants in one block at the top of the file, with the bands written down
      — flat scores are a judgement about the signal, graduated ones rise with the evidence,
      and every one is capped so no signal can monopolise the top of an inbox by growing
      without bound. This is what `predict.py:21` already required of itself.
      The second half was the real gap: `automation.py` wrote `60.0` for every rule, so an
      admin could not float a critical rule above a routine nudge. `CRM Automation Rule`
      gains a **Suggestion Urgency** field (0–100, shown only for `Create Suggestion`,
      exposed in the settings UI — the desk form is not reachable for these admins). The
      default stays 60, which sits deliberately between `NO_NEXT_STEP_SCORE` (40) and
      `SLA_BREACH_SCORE` (80), and a test pins that ordering rather than leaving it to a
      comment.
      Two failure modes closed on the way: an out-of-band value is clamped instead of
      obeyed, since the inbox sorts on it and a typo of 10000 would pin one rule to the top
      of every rep's list forever; and because adding an Int column backfills existing rows
      with **0 rather than the field default**, a patch fills in rules that predate the
      field. Without it every pre-existing rule would have kept firing while filing its
      suggestions below everything else — working, invisible, unexplained. The patch is
      idempotent, skips `Create Task` rules, and leaves a score somebody chose alone.

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
- [x] **Reports shows a shimmering skeleton forever when the report list fails or is
      empty.** `Reports.vue:337` only sets `active` inside `onSuccess`, and returns early on
      an empty list, so the fetch watcher never runs and the pane falls to a
      never-resolving `SkeletonTable`. Below 640px the rail carrying the `ErrorState` is
      hidden, so there is **no error message anywhere on screen**. *Fixed:* the list
      failing and the list being empty are now their own states in the main pane, which is
      always visible -- an `ErrorState` with retry and an `EmptyState`. Both are guarded on
      `isBuilder`, because a failed registry fetch is no reason to stop the report builder
      working.
- [x] **Native `window.confirm()` on one Vectora surface** — `Planner.vue:561`, which fires on
      every week arrow and rep switch while dirty. Chrome renders it as
      `localhost:8080 says…`, which reads as unfinished, and it blocks the tab while open.
      **AutomationRules is done** — it now uses `ui/ConfirmDialog` like the SLA views.
      Planner was the remaining one and the harder half: its route guard must return a
      promise, so the dialog could not simply replace the call.
      *Fixed:* `composables/confirmGate.js` — a confirmation the caller can `await`, which
      `onBeforeRouteLeave` returns directly. The trap it exists to close is a promise that
      never settles: a dialog closes by Escape and by backdrop click without any button
      handler running, and an unresolved guard promise does not look like a stuck dialog,
      it looks like a page you cannot navigate away from with nothing on screen to say
      why. So `open` is writable and any close that is not an explicit confirm answers no.
      8 unit tests, each mutation-checked.
      Verified in the browser on every path: week arrow, rep switch, conflict reload,
      route leave, and browser Back — confirm, cancel, and Escape on each, with the buffer
      checked afterwards.
      **Found while testing:** the leave guard runs *twice* per click on Leads/Deals/
      Contacts/Organizations/Notes/Tasks/Call Logs. `router.js:241` redirects those routes
      to their default view, and a redirect abandons the navigation and starts a new one,
      re-running the leave guards — so the user was asked twice. Pre-existing; the old
      `window.confirm` prompted twice too. The guard now drops the buffer once the user
      confirms, which is what "Discard changes" says it does and makes the second run a
      no-op.
      `ui/ConfirmDialog` gained optional `confirmLabel`/`cancelLabel` (defaults unchanged,
      other three call sites untouched): "Cancel" next to "discard your changes?" could
      cancel either the discard or the changes. Planner reads "Keep editing" /
      "Discard changes".
- [x] **Sales Targets and Automation Rules are the only Vectora surfaces with no
      loading/error primitives** — a bare spinner and frappe-ui's `ErrorMessage`, which on a
      transport failure renders the literal string "Failed to fetch" with no retry.
      `SkeletonTable`'s own docstring names the quota table as a call site it does not have.
      *Fixed:* both now use `SkeletonTable` (14 columns for the rep x month grid, 4 for the
      rule list) and `ErrorState` with retry. `ErrorMessage` survives only where the string
      is one we set ourselves -- the rule dialog's validation -- rather than whatever a
      fetch rejected with.
      Both verified in the browser on the success path; the transport-failure path was not
      forced, so it rests on `ErrorState` being proven on the other surfaces.
- [x] **The Sales Targets grid never shows an exact figure or a currency.** The wide
      sticky Year and Team-total columns now render the real figure with its currency via
      the same `formatCell` the CSV export uses, so the two surfaces agree. Month cells
      stay compact — twelve of them across a settings dialog leaves ~40px each and
      "250,000" clips to "250,0" there — but every compacted cell now carries the exact
      amount as a tooltip, so reading one back no longer means clicking into it. A target
      of zero reads as zero rather than `—`: `!value` could not tell a deliberate zero from
      an unset month. Verified with 249,900 and 250,400 side by side.
- [x] **Headline stat tiles print raw integers** (`1234`, not `1,234`). Now grouped in the
      reader's locale through the same `formatCell` the Reports page uses. Only actual
      numbers are touched — a tile whose value is already a string was formatted by its
      caller (percentages, "3 of 7"), and reformatting would undo that.
- [x] **Dates are hardcoded to `en-US`** in `utils/dashboard.ts`, and the range connector
      `" to "` is untranslated. Now the reader's locale (`undefined`, as `reportExport.js`
      already does for its `Intl` formatters) and `__('{0} to {1}', …)`.
- [x] **The dashboard range button stays English** — `__(preset)` on a runtime string the
      extractor never sees. Rebuilt from its parts as `Reports.vue` already does, so the
      button matches the dropdown beside it. A custom range falls through untouched: it is
      a formatted date, already localised, and not a phrase anyone translates.
- [x] **Automation Rules shows internal doctype names** — "CRM Deal" / "CRM Lead" in the
      dropdown and at the head of every rule summary. Labels are now separate from values,
      so the schema stops leaking at the user while the persisted value is untouched:
      verified by saving a rule and reading back `document_type: "CRM Deal"` under a
      summary that reads "Deal · …". Applies to, When, Then and Priority are all translated
      now; the status list is left alone because those are user-created records.
- [x] **The Dashboard chart grid is a fixed 20 columns**, so between roughly 640 and
      1000px — where the desktop layout is active and Dashboard *is* in the nav — a number
      card gets ~80px and truncates to nothing. *Fixed:* below 1000px the panels stack
      full-width in reading order (y then x, so two panels on one row keep their order)
      and each keeps its own height — flattening them would trade a width problem for a
      height one. Measured at 800px: panels went from ~140px slivers to 486px.
      The **Edit** button now gates on the same breakpoint rather than the phone one. It
      was still offered at 800px, where the grid it drags is not rendered, so it appeared
      to do nothing — the exact broken mode its own comment warned about, one breakpoint
      further out. Wide layout re-checked at 1440px and unchanged.
- [x] **The Reports rail claims to be a tablist but implements none of it** — no
      `aria-controls`, no `tabpanel`, no roving tabindex, no arrow keys. Either implement
      the pattern or drop the roles and let it be a nav of buttons. *Implemented* — it is a
      tab pattern in fact, so announcing one and then failing the keyboard was the wrong
      half to drop. Ids and `aria-controls` on every tab, `role="tabpanel"` +
      `aria-labelledby` on the pane (reusing the id the print stylesheet already selects),
      roving tabindex, and Up/Down/Home/End with automatic activation — arrowing down
      should *show* the next report, not merely outline it.
      Verified in the browser: exactly one tab stop, `aria-controls` resolves to the panel
      and the panel's label resolves back, and End jumps to the builder with selection and
      URL following.
- [x] **Panel reordering is built and unit-tested but has no UI** — `movePanel` in
      `dashboardHome.js:307` is imported by nothing, and `applyPanelPreference`'s `order`
      branch is unreachable because only `hidden` is ever written.
      *Wired, not deleted:* the mandate is that the pilot ships every planned feature, and
      this one was already built and tested — it just had no way in.
      Two chevrons per panel header, beside the existing Hide, disabled at the ends.
      Arrows rather than drag: the panel grid collapses to one column on a phone, so a drag
      target would move under the pointer between breakpoints, and arrows are keyboard-
      reachable without a drag-and-drop fallback. Each is labelled with its panel's name —
      "Move Quota attainment earlier" — since a screen reader listing six identical
      "Move up" buttons tells the user nothing.
      The join between the two existing functions turned out to be the part worth writing
      carefully, so it is a pure function of its own, `reorderVisiblePanel`, with 6 tests.
      It has to satisfy two requirements that pull against each other: the move must be
      between *visible* neighbours, because swapping with a hidden panel leaves the screen
      unchanged and the button looks broken; and the stored order must still cover the whole
      catalogue, because seeding it from the visible panels alone would drop every hidden
      panel to the unranked tail, so unhiding one later would not put it back.
      Verified in the browser: reorder, persistence across a reload, both ends disabled,
      and the awkward case — reorder while a panel is hidden, then unhide it and find it
      still in its stored position.
- [x] **~15 more `theme="orange"` Badges across the app** degrade to grey the same way,
      including the "Not Saved" badge in Settings. *Fixed:* 14 of them, to `amber`.
      Badge's valid set is `gray/blue/green/amber/red/violet` and it falls back to grey for
      anything else — right for a component, invisible as a bug. A vitest guard now reads
      the enum out of Badge's own `themeClasses` and asserts no `<Badge>` in the app names
      a theme outside it, so the next typo fails rather than rendering neutral.
- [x] **The root README is unmodified upstream Frappe CRM.** Rewritten for Vectora, with
      correct install instructions — the old ones told a reader to pull
      `ghcr.io/frappe/crm` and `bench get-app crm`, which installs upstream, not this
      fork. Upstream attribution is prominent rather than removed: this is an AGPL fork,
      most of the code is Frappe's, and the README says so, links there, and keeps the
      framework credits. Upstream screenshots dropped rather than relabelled — they show
      Frappe CRM's chrome and captioning them Vectora would be a lie.
- [x] **Vendor URL drift** — `AboutModal` showed the Vectora name and logo above five
      links that all led to Frappe. Repository and issue links now point at this fork: a
      Vectora planner bug filed on `frappe/crm` wastes the reporter's time and a
      maintainer's, and `support.frappe.io` promised help for a product Frappe does not
      support, so that link is gone rather than redirected. **The feature-documentation
      links stay pointed upstream on purpose** — I checked each one resolves and describes
      the inherited behaviour accurately (including Sales Hierarchy, which I had assumed
      was Vectora-only and is not). Swapping a working reference for a Vectora docs site
      that has not been written would be a downgrade; the link is relabelled for what it
      covers instead.
- [x] **Invitation email ignores the brand variable it is handed.** The template now uses
      `{{ title }}`, and the controller sources it from **FCRM Settings `brand_name`**
      rather than a literal — wiring the dead variable to a hardcoded string would have
      fixed nothing. A site branded "Northwind Sales" now invites people to Northwind
      Sales; unbranded sites still say Vectora. Subject line translated too. Verified by
      rendering the template both ways.
- [x] **Event reminder email is untranslated and interpolates user content into HTML
      unescaped** (`event.py:326`), in Bootstrap blue rather than the Vectora palette.
      **Moving it to a template would have looked like the fix and changed nothing:**
      frappe's Jinja environment runs with `autoescape = False` (verified against
      `frappe.get_jenv()`), so `{{ subject }}` in a file emits raw HTML exactly as the
      f-string did. The escaping is explicit in Python, the template says so, and 7 tests
      pin it — a comment cannot fail CI. The interesting attack is not a script tag, which
      mail clients drop, but closing our markup and appending a plausible reset-password
      link in a message sent to *external* participants. Strings translated, palette
      corrected, timestamp now through `format_datetime` rather than a hardcoded
      `strftime`, and the footer names the site's brand.
- [x] **Package metadata still names an upstream maintainer personally.** *Fixed:* set
      to the identity this repository already publishes under in its own commit history
      (`Absolute Insight` / `absolute.idev@gmail.com`) rather than anything invented. Not
      an attribution change -- per-file Frappe copyright headers stay, as the AGPL requires
      and as README's "Relationship to Frappe CRM" states. **Say so if either should
      differ; it is two lines.** Original entry: `pyproject.toml`
      `authors` and `hooks.py` `app_publisher` / `app_email` carry Frappe Technologies and
      `shariq@frappe.io`, so a Vectora bug report routed from app metadata reaches someone
      who does not maintain it. Left deliberately: changing `authors` would misattribute
      code Frappe wrote, and I have no address to substitute. **Needs a maintainer
      decision on the fork's contact identity**, then 15 min.
- [x] **~126 unwrapped English strings across 33 components**, worst on the Activities
      empty states (every Lead/Deal/Contact timeline) and ~45 filter operator labels.
      *Fixed:* 138 strings wrapped across 32 files — the 44 filter operator labels in
      `CFCondition.vue`, the 18 Activities empty-state titles and descriptions, weekday and
      priority option lists, and 16 template attributes that were unbound literals
      (`title="No SLA Policies Found"` → `:title="__('...')"`).
      The count was inflated: **AppSidebar's 11 nav labels, and the tab labels in
      SLASection, AssignmentSchedule, ERPNextSettings, Contact and Organization, were
      already translated at their render site** (`__(link.label)`), so wrapping them again
      would have double-translated. Deliberately left alone: brand names (Twilio, Exotel,
      Facebook, the four FX providers), the `ACXXXX…` format placeholders, a JSDoc example
      and commented-out code.
      **Two real bugs found doing it, neither of them a missing `__()`:**
      `SlaHolidays.vue:271` used `day.label` as the value it stored in `workday`, so once
      the labels became translatable a Spanish rep would have written "Lunes" into a Select
      the server has no such option for. Now `.value`, which is what it always meant.
      `DoctypeModal.vue:10` did `__('Edit ' + doctypeTitle)` — translate-a-string-built-at-
      runtime, so the keys were "Edit Note", "Edit Call Log" and so on, none of which appear
      in the source for an extractor to find. Now `__('Edit {0}', [__(name)])`.
      `GeolocationControl` had the same defect with a plural; both forms are spelled out.
      `getStandardFieldsMeta()` is a function now, not a const: `__` is installed on window
      during app creation, after every module in the import graph has been evaluated, so a
      module-scope `__()` would have run before the function existed.
      Verified in the browser — filter operators, Activities empty states, SLA work days
      (added a row, confirmed the stored value is still `Saturday`), assignment rule
      priorities and the Create Note modal. Zero console errors.
- [x] **Twilio callback URL built by substring-matching `":8"`** — copy-pasted in two files;
      a site on `:8443` silently loses its port. *Fixed:* parsed properly, and only a
      recognised bench port (8000/8080/9000) is dropped -- `get_url()` already honours
      `host_name`, and an admin who set that has told us their public address. The old code
      did not even strip 9000, since it only matched `:8`. It also did `str + None`, so
      calling it with no path -- as the signature invites -- raised. One definition now,
      re-exported where the copy was: the bug had to be found twice. 9 tests,
      mutation-checked.
- [x] **Eight surfaces told the user "there is nothing here" when the fetch had failed.**
      Found by testing the claim above rather than trusting it. Two shapes:
      **The two sidebar badges silently read as zero.** `openCount` and `notifications`
      carry `initialData` of `0` and `[]`, frappe-ui leaves that in place when the *first*
      fetch fails, the count computes to 0 and the badge hides itself. A rep opening
      Vectora while the endpoint is down sees a sidebar identical to a clean inbox — on a
      product whose whole proposition is proactive signals, that is the product telling
      them there is no work waiting when it never managed to ask. Measured: healthy sidebar
      reads `Suggestions 378`; with `get_open_count` returning 500 it reads `Suggestions`
      and nothing else, with no error anywhere on screen.
      **Six components answered a failed fetch with an empty state** — a bare `v-else`
      under `<EmptyState>`: the notifications panel ("You have no new notifications", which
      agreed with the hidden badge so both surfaces lied at once), both event panels,
      the email-account list ("no email accounts", which in Settings reads as *your mail is
      not configured*), the assignment-rule list, and a contact's Deals tab.
      *Fixed:* the badges show `–` with a tooltip instead of hiding, and the six get a real
      `ErrorState` with retry. The rule that decides it is a pure, tested function,
      `utils/resourceState.neverLoaded`, because the distinction is not obvious: frappe-ui
      restores `previousData` on a **failed reload**, so a count that has loaded once keeps
      its last good value — covering that with "unavailable" would be its own small lie.
      7 unit tests, mutation-checked.
      Verified headless against a live site by failing individual endpoints: cold-start
      failure shows `–`, a genuine zero still hides the badge, a failed reload keeps `378`,
      the two badges fail independently, and six healthy surfaces show no false alarm.

- [x] **Skeleton/error states cover only the new surfaces** — legacy list views still use
      frappe-ui defaults despite `EmptyState.vue` documenting the three-state contract.
      *Fixed:* all seven (Leads, Deals, Tasks, Contacts, Organizations, Call Logs, Notes).
      They were worse than "frappe-ui defaults": the branch chain went straight from *has
      data* to `EmptyState`, so **a list still fetching and a list whose fetch failed both
      rendered nothing at all** — a blank page under a working filter bar, which reads as
      an empty CRM rather than a slow or a broken one. Notes was worse again: its
      `EmptyState` was chained to the *footer's* `v-if`, so a failed fetch answered
      "No Notes yet" — telling the user their CRM is empty when it is actually broken,
      the exact thing `EmptyState`'s own docstring warns against.
      Error and loading are now their own branches and come first, so they cover the kanban
      view too. `SkeletonTable` for the six table lists; Notes gets card-shaped skeletons in
      its real grid, since a table skeleton over a card layout would shift on arrival.
      Verified per page in the browser by driving the live resource through all four states
      — loading, failed, empty, loaded — confirming they are mutually exclusive, that the
      failure state never claims the list is empty, that "Try again" recovers, and that the
      kanban view still renders after its `v-if` became a `v-else-if`.
- [x] **Dashboard rate limit is tuned as if it were one call per load** — the tile row fires
      5 concurrent `get_chart` calls, re-fired on every filter change, against a 60/min cap.
      429s on a manager's dashboard mid-demo. *Fixed:* both limits are now derived from
      "how many times may someone open or re-filter the dashboard in a minute" rather than
      being raw call counts, since the two endpoints cost a different number of calls per
      view — `get_dashboard` runs its panels server-side, the tile row does not.
      The failure was worse than an error: the 429 lands on the tiles only, so the panels
      below keep updating while the numbers above them freeze, and the page still looks
      like it is working. A guard reads `TILE_CATALOGUE` out of `Dashboard.vue`, so adding
      a sixth tile without raising the limit fails instead of quietly cutting the number of
      views a manager gets.
- [x] **~30 empty scaffold test classes**, including `crm_form_script`, `crm_fields_layout`
      and `crm_sales_hierarchy` — the doctypes behind the public API and the permission
      model. **Counted by discovery, contributing nothing.**
      *Resolved, and this entry was partly wrong.* The real count is 22, and
      `crm_sales_hierarchy` is **not** among them — it has 97 lines of its own tests plus a
      232-line permission suite in `test_org_hierarchy.py`. This item was stale.
      Of the remaining 22, the two named ones were the only scaffolds standing over
      untested behaviour that is ours rather than Frappe's, and both are the public
      scripting API that `CLAUDE.md` calls out. Both are now real suites:
      `test_crm_form_script.py` (11 tests) pins the contract that `get_form_script` **changes
      the shape of its return value with the row count** — a bare string for one, a list for
      several, `None` for none — and the standard-script guard.
      `test_crm_fields_layout.py` (10 tests) covers `handle_perm_level_restrictions`, which
      is what stops a permlevel'd field reaching the browser at all, and the permission gate
      on `save_fields_layout`.
      The other 20 are `bench new-doctype` boilerplate over master doctypes — `CRM Industry`,
      `CRM Lead Source`, `CRM Deal Status` and the like — where a test would exercise
      Frappe's framework rather than any code of ours. They are left as the upstream
      scaffolding they are; deleting them only invites `bench` to regenerate them.
      **Two traps caught by mutation testing, both of the "passes for the wrong reason"
      kind.** The form-script guard exempts `frappe.flags.in_test`, so a test that merely
      calls `save()` passes whether or not the guard exists — each test clears the flag
      first. And the first version of the `save_fields_layout` permission test passed with
      the gate deleted, because `doc.save()` refuses a Sales User too; it was asserting
      Frappe's behaviour, not ours. A second test now pins our own refusal by its message.

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
