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
| Which file owns which job (nav index) | [KEY-FILES.md](./.pi/KEY-FILES.md) |
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

File→role tables for every subsystem — scripting engine, field rendering, form
dialogs, meta/stores, permissions, product surfaces, design system — live in
[.pi/KEY-FILES.md](./.pi/KEY-FILES.md). In an indexed checkout ask
`codegraph explore` instead: it answers the same question with the source and
the callers attached.

---

## Design system gotchas

These stay here rather than in the nav index, because they are not locations and
no index will tell you them.

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
KEY-FILES.md     — file→role nav index (moved out of AGENTS.md; keep current)
feats/           — user-facing feature docs
archives/        — old docs preserved verbatim
```

When a phase completes: move its spec from PLAN.md to ARCHIVE.md, update SPEC.md if
the API surface changed.
