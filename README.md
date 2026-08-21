<div align="center" markdown="1">

<img src="crm/public/images/logo.svg" height="80" alt="Vectora">

<h1>Vectora</h1>

**A CRM that tells you what needs doing**

[Report an issue](https://github.com/Absolute-Insight/simcrm/issues) · [Deployment guide](deploy/README.md) · [Project context](AGENTS.md)

</div>

## What this is

Vectora is a sales CRM built on [Frappe CRM](https://github.com/frappe/crm). It keeps
everything that makes Frappe CRM good — the lead and deal pages, Kanban, custom views,
telephony, email — and adds a layer on top that does the noticing for you:

- **Suggestion inbox.** Deals going quiet, closing dates slipping, follow-ups nobody
  picked up. Ranked by urgency, each with the reason it was raised. Runs on
  deterministic signals, no model required.
- **Deal health.** A per-record score and the factors behind it, on the record itself.
- **Weekly planner.** Plan a rep's week, then measure what actually happened against it.
- **Reports and forecasting.** Pipeline, conversion, quota attainment and forecast
  accuracy, with CSV export and a print view.
- **Sales hierarchy.** Managers see their own subtree and nobody else's — enforced in
  the permission layer, not just the UI.
- **Automation rules.** When a deal reaches a stage, raise a task or a suggestion.
  Deterministic, and they run with the assistant switched off.
- **An optional assistant.** Thread summaries and drafted replies against any
  OpenAI-compatible endpoint, including a model on your own hardware. Off by default;
  every feature above works without it.

## Relationship to Frappe CRM

This is a fork, not a plugin, and most of the code here is Frappe's. Vectora is
distributed under the **AGPL v3**, the same licence as upstream, and the copyright
notices on inherited files are Frappe Technologies'.

Upstream's documentation at [docs.frappe.io/crm](https://docs.frappe.io/crm) describes
the inherited CRM accurately and is worth reading. It does not cover anything in the
list above — those are Vectora's, and their documentation lives in this repository.

Bugs in Vectora belong on [this repository's tracker](https://github.com/Absolute-Insight/simcrm/issues),
not upstream's.

## Deploying

The production stack lives in [`deploy/`](deploy/) — one compose file, the image
published to `ghcr.io/absolute-insight/simcrm`, and a runbook covering first boot,
upgrades, backups, and the restore drill you should rehearse before trusting either.

```bash
cd deploy
cp .env.example .env        # VECTORA_TAG, SITE_NAME, DB_ROOT_PASSWORD, ADMIN_PASSWORD
docker compose up -d
docker compose logs -f create-site
docker compose exec backend bench --site <site> doctor   # scheduler enabled, workers online
```

The stack publishes its HTTP port on loopback only; the runbook's TLS section
covers putting a reverse proxy in front of it.

Read [deploy/README.md](deploy/README.md) before the first upgrade: reverting the image
is **not** a rollback once `migrate` has run, and the runbook explains what is.

For the optional local-model profile, hardware guidance, and why the assistant's
timeout has to clear your proxy's, see the same file.

## Development

Requires a [Frappe bench](https://docs.frappe.io/framework/user/en/installation).

```bash
bench get-app crm https://github.com/Absolute-Insight/simcrm
bench new-site sitename.localhost --install-app crm
bench browse sitename.localhost --user Administrator
```

The CRM is served at `sitename.localhost:8000/crm`.

For frontend work, run the Vite dev server against that site — the prebuilt bundle
under `crm/public/frontend/` is a build artefact and will be stale:

```bash
cd apps/crm/frontend
yarn install
yarn dev            # then browse http://sitename.localhost:8080
```

### Before you commit

```bash
cd frontend && yarn test:run          # unit tests
bench --site <site> run-tests --app crm
pre-commit run --files <changed files>
```

[AGENTS.md](AGENTS.md) is the map of the codebase; [CLAUDE.md](CLAUDE.md) covers how to
work in it. [docs/PILOT-READINESS.md](docs/PILOT-READINESS.md) tracks what is done and
what is not, honestly.

## Built on

- [Frappe CRM](https://github.com/frappe/crm) — the CRM this forks
- [Frappe Framework](https://github.com/frappe/frappe) — the full-stack framework underneath
- [Frappe UI](https://github.com/frappe/frappe-ui) — the Vue component library

## Licence

[GNU AGPL v3](LICENSE). © Frappe Technologies Pvt. Ltd. and contributors.
