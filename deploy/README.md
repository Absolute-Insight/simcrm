# Deploying Vectora

The stack in this directory runs the production image that
[`builds.yml`](../.github/workflows/builds.yml) publishes to
`ghcr.io/absolute-insight/simcrm` on every push to `main`. It is
[frappe_docker](https://github.com/frappe/frappe_docker)'s canonical layout:
one image, one role per container.

**Status: authored and reviewed, not yet exercised.** This configuration has
not been booted end-to-end — the environment it was written in has no Docker
daemon, and the image itself first exists after `main` receives a release and
`builds.yml` runs. Treat the first boot as part of the rollout, not as a
formality.

## Prerequisites

- A host with Docker Engine 24+ and the compose plugin
- DNS for your site name pointing at the host
- The image published (merge to `main`, wait for the **Build Container Image**
  workflow) — or build locally with frappe_docker and tag it to match
- Access to the image: ghcr packages are **private by default**. Either make
  the `simcrm` package public (github.com → your profile → Packages →
  simcrm → settings), or on the host:
  `docker login ghcr.io -u <github-user>` with a PAT that has `read:packages`

## First boot

```bash
cd deploy
cp .env.example .env        # fill in SITE_NAME, DB_ROOT_PASSWORD, ADMIN_PASSWORD
docker compose up -d
docker compose logs -f create-site   # one-shot; wait for it to finish
```

Then browse `http://<host>:8080` (or your `HTTP_PUBLISH_PORT`) — the CRM is at
`/crm`. Log in as `Administrator` with the admin password from `.env`.

`create-site` is idempotent: it skips itself when the site directory already
exists, so `docker compose up -d` is always safe to re-run.

**Demo data is not seeded.** A new site starts with `setup_complete = 0`, so
opening the desk UI — which the scheduler-watching step below sends you to —
prompts Frappe's setup wizard, and finishing it used to seed eleven fake leads,
seven fake deals and three fake users into your production CRM. The proactive
tier then treats them as real: signals score them and the weekly forecast
snapshot folds their value into the site total, which cannot be corrected
afterwards because a snapshot records what was believed on a date. Seeding is
now opt-in:

```bash
docker compose exec backend bench --site <site> set-config crm_seed_demo_data 1
```

Clearing it afterwards (**Clear Demo Data** in the sidebar) now also removes the
suggestions, rep plans and forecast rows derived from it, including the site
and team aggregates taken while it existed — those counted fiction and cannot
be recomputed. Per-rep history for real reps is untouched.

## TLS

This stack does not terminate TLS. Put your standard reverse proxy (Traefik,
Caddy, nginx with certbot) in front of the `frontend` service and forward to
`HTTP_PUBLISH_PORT`. If you already run frappe_docker's Traefik overlay,
`frontend` here is the same nginx it expects.

## Upgrading

`.env` pins `VECTORA_TAG` to a release, so upgrading is a deliberate edit
rather than whatever `pull` happens to fetch:

```bash
# 0. a backup you could actually restore from — see Rolling back
docker compose exec backend bench --site all backup --with-files

# 1. edit .env: VECTORA_TAG=v3.1.0

# 2. close the site while the schema and the code disagree
#    (one site at a time: unlike migrate/backup, this takes no "all")
docker compose exec backend bench --site <site> set-maintenance-mode on

docker compose pull
docker compose up -d                      # replaces containers on the new image
docker compose exec backend bench --site all migrate

docker compose exec backend bench --site <site> set-maintenance-mode off
```

**If you skip step 1, nothing upgrades** — `pull` re-fetches the same pinned
tag and `up -d` finds nothing to replace. That is the intended trade: an
upgrade you have to ask for, and a `.env` that records what is running when
somebody reports a bug. (`VECTORA_TAG=stable` restores pull-and-go, at the cost
of not being able to say what a given host is running.)

**Step 2 is not ceremony.** `up -d` starts serving the new code immediately,
and `migrate` then takes as long as it takes — minutes on a real dataset. In
that window reps are on new code against an old schema, which is the one
combination nothing is tested against. Maintenance mode gives them an honest
"be right back" instead of errors that look like data loss.

Order matters: migrate *after* the new image is up, so patches run on the code
that shipped them. `merge_duplicate_rep_plan_weeks` and friends are one-shot
frappe patches and track themselves — re-running migrate is safe.

### Rolling back

**Reverting the image is not a rollback once `migrate` has run.** Patches have
already changed the schema, and old code does not know about those changes;
some patches drop or rewrite columns and cannot be undone by running older code
over them. The only reliable path back is the backup from step 0:

```bash
# put the old tag back in .env first
docker compose up -d
docker compose exec -T backend bench --site <site> restore --force \
  --db-root-password "$DB_ROOT_PASSWORD" \
  /home/frappe/frappe-bench/sites/<site>/private/backups/<file>.sql.gz \
  --with-public-files <files>.tar --with-private-files <private>.tar
```

`--db-root-password` is not optional and this command used to omit it. `restore`
drops and recreates the database, which the site's own credentials may not do, so
without the flag `bench` **prompts** for the MySQL root password — and the
`backend` service does not carry `DB_ROOT_PASSWORD` in its environment (only `db`
gets it, from `.env`), so nothing fills the prompt in for you. Under a plain
`docker compose exec` there is no TTY either, so the rollback hangs at the one
moment you cannot afford it. Take the value from `.env` on the host, where compose
already reads it. Verified by running the restore both ways against a real
backup.

Which means the restore drill in the pilot checklist below is not a nice-to-have:
it is the rehearsal for the only rollback you have. If step 0's backup has never
been restored, you do not have a rollback, you have a file.

If `migrate` fails partway, do not roll the image back and carry on — the site
is between schemas. Read the error (`docker compose logs backend`, and frappe's
Error Log), fix forward if the cause is obvious, and restore if it is not.

## Backups

```bash
docker compose exec backend bench --site all backup --with-files
```

Backups land in the `sites` volume under `<site>/private/backups`. Copy them
off the host; a backup on the machine it protects is a copy, not a backup.

## Operating the proactive tier

- The **scheduler** container is what makes Vectora proactive: the hourly
  signal run, hourly deal-health scoring, and the daily digest all fire from
  it. If suggestions go quiet, check `docker compose logs scheduler` first.
- Deterministic automation (CRM Automation Rule) runs with the agent tier
  disabled — that is a design guarantee, not an accident. You can pilot with
  the agent off and lose only the model-drafted content.
- Report digests email deal values. Recipients are validated to be enabled
  users with a CRM role, but *which* users get digests is an ops decision —
  review `CRM Report Digest` records before enabling outbound email.
- Outbound email needs an Email Account configured in Frappe as usual;
  nothing in this compose file sends mail on its own.
- **If you enable the agent tier, its `timeout` must clear this stack's proxy.**
  `frontend` sets `PROXY_READ_TIMEOUT: 120`, and one agent call costs up to
  `timeout × 2` (it retries once) in a *web* worker — so a `timeout` of 120,
  which the agent runbook suggests for a reasoning model, lets the backend work
  for 240 s on a request nginx gave up on at 120. The rep sees a failure and a
  worker stays busy for two more minutes. Keep `timeout × 2 < PROXY_READ_TIMEOUT`
  (≈55 at the shipped setting), or raise `PROXY_READ_TIMEOUT` to match the model
  you actually run. Either way a slow model occupies a worker for its whole
  duration: size the pool before pointing this at something big.

  This is now enforced rather than merely advised: **CRM Agent Settings** refuses
  a `timeout` above 59. If you raise `PROXY_READ_TIMEOUT`, tell the backend so it
  can raise its own limit to match —
  `bench --site <site> set-config crm_proxy_read_timeout <seconds>`.
- **Check the endpoint before enabling the tier.** **Settings → Assistant → Test
  connection** sends one real request and checks the reply follows the schema.
  It works with the assistant switched off, and it is the fastest way to tell a
  wrong `base_url` from a model that cannot do structured output — those look
  identical to a rep, and have different fixes.

## Lead syncing is off

The Facebook lead-ads connector ships disabled and its settings tab is hidden.
It asks the Graph API for one enormous page and ignores the paging cursor, then
marks everything up to now as synced — so a form that produces more new leads
than fit in one page loses the remainder silently, with nothing in Failed Lead
Sync Log to show for it. The failure only appears when a campaign does well.

Nothing else depends on it; leads still arrive through the web form, the API
and manual entry. If you need it anyway and accept that behaviour, set
`crm_enable_lead_syncing` in site config:

```bash
docker compose exec backend bench --site <site> set-config crm_enable_lead_syncing 1
```

That restores the background jobs, the **Sync Now** button and the settings
tab together. Leave it unset until `fetch_leads()` follows `paging.next`.

## Running the agent on a local model

The agent tier is an HTTP client to any OpenAI-compatible endpoint — it does no
inference itself. Nothing about the CRM changes between a hosted API and a model
on your own hardware; only `base_url` in **CRM Agent Settings** does. Three
shapes are supported:

| | What it costs | When |
|---|---|---|
| **Off** | nothing | The default. Every deterministic feature — signals, deal health, planner, digests, automation — works with the agent disabled by design. You lose only model-drafted content. |
| **Hosted API** | per-token billing | Cheapest to run. Note that thread contents, including customer email, leave your infrastructure — a decision for whoever owns that data. |
| **Local model** | one host with a GPU | Nothing leaves your network. |

For the local shape this stack ships an opt-in profile:

```bash
docker compose --profile local-model up -d
docker compose logs -f ollama-pull    # first run downloads several GB
```

Then point the CRM at it — **CRM Agent Settings** → `base_url`
`http://ollama:11434/v1`, `model` the same value as `VECTORA_AGENT_MODEL`, and
`enabled` on. `127.0.0.1` will not work: from inside the backend container that
is the container itself, so the endpoint has to be the service name.

`ollama-pull` is a one-shot that fetches the weights and then makes one
throwaway call to warm them. It is idempotent, so `up -d` stays safe to re-run.

**Hardware.** A GPU with 8GB or more is the sensible floor for the default
model; add a device reservation to the `ollama` service (there is a commented
example in `docker-compose.yml`). CPU-only inference does work, but a summary
takes tens of seconds rather than about one, which pushes you into the timeout
interaction described above — raise the agent `timeout`, and
`PROXY_READ_TIMEOUT` with it, or every call will fail at the proxy. The 4GB VM
that comfortably runs the rest of this stack is **not** enough to also host a
model; put inference on its own machine.

**Model choice.** `granite-4.0-h-tiny` at Q4_K_M is what this stack is verified
against: guided decoding is clean and a warm summary returns in about a second
on a small GPU, against roughly nine and a half seconds cold — which is what
`OLLAMA_KEEP_ALIVE` exists to avoid. `LFM2.5-2.6B` also works, more slowly. Do
not ship `MiniCPM5-1B`: it intermittently returns empty content, which the agent
correctly reports as `unavailable` rather than inventing a summary.

**What a local model does not fix.** Prompt injection. Every model tested so far
follows instructions embedded in a customer's email — that is why this tier has
no write tools and why drafted replies are always shown to a human before
sending. Running the model yourself changes where the weights live, not whether
the output can be steered by someone who emails your reps.

## Pilot checklist

The defaults below are deliberately conservative; loosen them as the pilot
earns trust, not before.

1. **Restore drill first.** Take a backup, restore it to a scratch site, log
   in. A backup you have never restored is a hope, not a plan.
   *Rehearsed on a dev bench (2026-08-18), and it is what found the missing
   `--db-root-password` above.* Backup of a 1,716-deal site produced a 998 KiB
   dump in under a second; restoring it to a fresh scratch site brought back
   every count exactly — deals 1716, leads 1855, suggestions 378, contacts 183 —
   and Administrator could log in and read real records through the API,
   including a Vectora endpoint (`get_open_count` → 378). What that does **not**
   cover: it ran `bench` directly rather than through `docker compose exec`, so
   the compose wrapper and the volume layout are still unrehearsed. Do the drill
   again on the real stack before the pilot takes real data.
2. **Agent tier off, digests off.** Deterministic automation (assignment, SLA,
   automation rules) works with the agent disabled by design — you lose only
   the model-drafted content. Enable `CRM Report Digest` records only after
   deciding who may receive deal values by email.
3. **Two or three willing reps**, one manager, one week. Their real pipeline,
   not demo data.
4. **Watch the scheduler.** `docker compose logs -f scheduler` on day one: the
   hourly signal run and deal-health scoring have never run against real
   volume on real cron. Frappe's Error Log (bench --site <site> console, or
   the desk UI) catches anything a job swallows.
5. **Judge it on questions, not features:** did the suggestions point at deals
   the rep agreed were at risk? Did propose-my-week produce a plan worth
   keeping? Do the dashboard numbers match what the manager believes? Every
   "no" is a finding worth more than the pilot.

## What this is not

A high-availability setup. One database, no replicas, volumes on the host.
For a pilot with a handful of reps that is appropriate; for more, put the
database on managed infrastructure and keep the stateless services here.
