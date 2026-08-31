---
name: test
description: Run this repo's test suites the way CI runs them - frontend vitest, python bench run-tests, Playwright e2e - and interpret the results honestly. Use before committing, before opening a PR, or when asked whether the tests pass.
---

# Run the tests

Three suites, three environments. Run the ones your change touches; run all
three before promoting to `main`.

## Frontend unit (vitest) — fast, always run these

```bash
cd frontend
yarn test:run          # single run
yarn test              # watch
yarn test:coverage
```

Sub-second. Only pure utilities in `frontend/src/utils/` are covered — there
are no component tests. **Re-read the file/test counts from the run output**;
any number written in a doc is stale by definition.

Lint the way CI does (`frontend-tests.yml`):

```bash
cd frontend && npx eslint src --ext .js,.ts,.vue && npx oxlint src
```

## Python (bench) — use `test_site`, never your dev site

```bash
cd /home/frappe/frappe-bench    # the bench is a docker volume, not a repo directory
bench --site test_site run-tests --app crm
bench --site test_site run-tests --module crm.agent.tests.test_signals
```

Two traps, both of which have shipped bugs here:

1. **Never point this at `dev.localhost`.** `run-tests` runs against whatever
   site you name. A dev site full of demo records means any test that reads
   site-wide state measures the demo, not the code — the per-rep suggestion
   ceiling counts every open row on the site and is exactly this shape.
2. **A green local run is not CI's.** A full run leaves ~70 records behind from
   fixtures created outside a rolled-back transaction; CI reinstalls per run.
   Before believing a green suite:

   ```bash
   bench set-config -g mariadb_root_password <root-pw>   # remove again afterwards
   bench --site test_site reinstall --yes --admin-password admin
   bench --site test_site install-app crm                # reinstall drops it
   bench --site test_site run-tests --app crm
   ```

The site needs `allow_tests` on and mail keys (`auto_email_id`, `mail_server`,
`mail_login`, `mail_password` — see `.github/helper/site_config.json`); without
a default outgoing account the report-digest tests find no queued email and fail
on the *site*, not on the code.

## Playwright e2e

```bash
yarn test:e2e          # or :ui / :headed / :debug
```

CI adds `127.0.0.1 crm.test` to `/etc/hosts` and runs against a bench it builds
from scratch (`ui-tests.yml`).

## Reporting the result

State what you ran, on which site, and paste the failure output when something
fails. "Tests pass" without naming the suite and site is the claim that hides
every problem above.
