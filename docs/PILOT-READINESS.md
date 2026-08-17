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
- [ ] **Finish triaging the semgrep findings, then make the full scan a scheduled job.**
      The 7 `guest-whitelisted-method` findings are now reviewed: `get_translations`,
      `oauth_providers` and `accept_invitation` must be guest-reachable and expose nothing
      sensitive (`oauth_providers` decrypts a client secret only as an existence check and
      never returns it); `get_context_for_dev` is behind `developer_mode`;
      `live_demo.login` no-ops unless `demo_username`/`demo_password` are set in site
      config — **worth knowing that setting those on a production site is an auth bypass
      by design**; the two Twilio and one Exotel webhooks are fixed above. Remaining: 12
      `frappe-manual-commit`, 3 `frappe-setuser`, 1 `override-doctype-class`, 1
      `frappe-enqueue-without-after-commit`. CI diff-scans, so nothing already in the tree can trip it — which is why two
      P0 leaks sat there. A full run reports 12 `frappe-manual-commit`, 8
      `guest-whitelisted-method`, 3 `frappe-setuser`, 1 `override-doctype-class`, 1
      `frappe-enqueue-without-after-commit`. These are "audit this" advisories rather than
      confirmed bugs, and each needs a verdict recorded. **Deliberately not adding the
      scheduled job first:** born red against 25 untriaged findings it would be ignored
      within a week, which is worse than not having it. **1 day.**

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
- [ ] **Calendar is unusable at phone width** — the week view puts seven day-columns in
      390px and clips its own toolbar. Needs a day view as the mobile default. **1 day.**

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
- [ ] **Resources submitted with no `onError` are a second, unenumerated category.**
      `AssignToBody` was found by accident; nothing has swept `createResource` call sites
      the way this pass swept `.then(`. **4 h** to enumerate and triage.
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
- [ ] **Facebook lead sync pagination** — follow `paging.next` in `fetch_leads()` and
      advance `last_synced_at` only to the newest lead actually imported, then flip the
      default in `crm/lead_syncing/__init__.py`. **1 day.**
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
- [ ] **Three dashboard tests assert absolute averages and fail on any site with data.**
      `test_dashboard.py:158,224,588` hardcode `89285.71` and friends. The file's own header
      explains why that cannot hold — `make_test_records` commits its fixtures instead of
      rolling them back — and most of the file was rewritten to compute expectations
      independently; these three were missed. Green in CI on a fresh site, red on any
      long-lived one, which is the wrong way round for a regression test. Found while
      verifying the forecast work; confirmed pre-existing against a clean tree. **1 h.**
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
- [ ] **Package metadata still names an upstream maintainer personally.** `pyproject.toml`
      `authors` and `hooks.py` `app_publisher` / `app_email` carry Frappe Technologies and
      `shariq@frappe.io`, so a Vectora bug report routed from app metadata reaches someone
      who does not maintain it. Left deliberately: changing `authors` would misattribute
      code Frappe wrote, and I have no address to substitute. **Needs a maintainer
      decision on the fork's contact identity**, then 15 min.
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
