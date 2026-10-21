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

- All must pass before committing.
- Add tests in `tests/unit/` when adding pure logic to `src/utils/`

### Python

Runs in the devcontainer bench against **`test_site` — never the site you browse**
(demo rows skew any test that reads site-wide state). Commands, the reinstall recipe
and the site config it needs: [.claude/skills/test/SKILL.md](./.claude/skills/test/SKILL.md) (`/test`).
`bench --site … reinstall` is in the `settings.json` deny list — ask the user to run it.

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
Never commit on `develop` — pre-commit's `no-commit-to-branch` rejects it; branch first.
Pre-commit hooks run prettier + eslint + oxlint automatically. If they modify a file,
`git add` the file again and re-commit.

---

## Agent tooling (`.claude/`, `.mcp.json`)

`.claude/` is tracked on purpose: these encode the repo's rules, so they belong
to the repo rather than to one machine. (A personal, gitignored `CLAUDE.md`
sits alongside and covers *this host* — where the toolchain actually lives,
which ports are which. Machine facts go there; repo rules go here.)

### Slash commands

| Command | Does |
|---|---|
| `/dev-up` | Bring up / verify the devcontainer stack, deps, dev site |
| `/test` | Run the suites the way CI runs them (frontend unit, python, e2e) |
| `/deploy` | Bring up or upgrade the `deploy/` compose stack, then verify |
| `/release` | Cut a release per [docs/RELEASING.md](./docs/RELEASING.md) |
| `/backmerge` | Release steps 6+7 — the ones that get missed |
| `/upstream-port` | Port fixes from upstream `frappe/crm` |

`/deploy`, `/release`, `/backmerge` and `/upstream-port` are
`disable-model-invocation`: they have side effects and are started deliberately.

### Review agents

`permissions-reviewer` (row scoping and the access boundary),
`theme-contrast-reviewer` (the `--ink-*` ladder — see **Design system
gotchas**), `upstream-port-reviewer`, `clock-and-timezone-reviewer` and
`doctype-migration-reviewer`.

### Hooks — enforced, not advisory

- **`guard-paths.sh`** (PreToolUse) refuses writes to generated files, build
  output, `.env`, lockfiles and `crm/__init__.py`.
- **`guard-compose.sh`** resolves what `docker compose pull/up/create` will
  *actually* run. It reports a **change**, not a difference — a guard that
  fires on the normal condition is one you learn to click through.
- **`format-file.sh`** (PostToolUse) formats edited files so pre-commit does
  not bounce the commit. It **pins prettier and ruff to the versions CI uses**
  (currently 3.2.5 and 0.8.1); formatting with a newer version writes a file
  pre-commit then rewrites differently, which is the bounce it exists to
  prevent. Bump those constants in the same commit as
  `.pre-commit-config.yaml`. eslint is unpinned on purpose — pre-commit gives
  it a caret range, and a linter's `--fix` does not drift like a formatter's.
- **`verify-tests.sh`** (Stop) runs vitest before a turn ends, but only when
  the turn touched `frontend/src` or `frontend/tests`, and stands down after
  three consecutive red runs so a pre-existing failure cannot wedge a session.

All degrade rather than fail when a tool is missing, and each logs its skips
(`format.log`, `compose.log`, `verify.log`, all gitignored). Check the log
before concluding a hook did nothing.

### MCP

`.mcp.json` declares **codegraph** at project scope so the "ask
`codegraph explore` instead" advice above holds in a fresh worktree and for
anyone else who opens the repo. The binary is a host tool, so inside the
devcontainer the server does not connect — use the shell form there. Playwright
is deliberately absent: it arrives via a plugin under another server name, and
the e2e suite drives it through `npx playwright test` anyway.

---

## Docs structure

When a phase completes: move its spec from PLAN.md to ARCHIVE.md, update SPEC.md if
the API surface changed.
