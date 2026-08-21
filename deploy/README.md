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

Every long-running service waits for `create-site` to finish, so `up -d` on a
fresh host serves nothing until the site exists — `docker compose ps` shows
`backend`, `frontend` and the workers as `Created` until then, which is
correct, not stuck. Then browse `http://<host>:8080` (or your
`HTTP_PUBLISH_PORT`; it is bound to loopback by default, see [TLS](#tls)) —
the CRM is at `/crm`. Log in as `Administrator` with the admin password from
`.env`.

`create-site` is idempotent: it skips the create when the site directory
already exists, so `docker compose up -d` is always safe to re-run. What it
does on *every* run is `bench enable-scheduler`: `bench new-site` writes
`enable_scheduler: 0` into the new site's config, and a site left that way has
every cron job in `crm/hooks.py` — the hourly signal run, deal-health scoring,
the daily digest — silently not running, with nothing in any log to say so.

**Verify the first boot** before handing anyone the URL:

```bash
docker compose ps                               # every service `running (healthy)`
docker compose exec backend bench --site <site> doctor
```

A healthy `doctor` looks like this — the scheduler line is the one that
matters:

```
-----Checking scheduler status-----
Scheduler disabled for <site>? False     # anything else: bench --site <site> enable-scheduler
Scheduler inactive for <site>? False
Workers online: 2                        # queue-short and queue-long
-----<site> Jobs-----
```

`Scheduler disabled ... True` means `create-site` did not get to its last
line; `Workers online: 0` means the queue containers are not up
(`docker compose ps`, then `docker compose logs queue-long`).

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

## Rehearsing on localhost

The restore drill in the checklist below ran `bench` directly, so **the compose
wrapper and the volume layout are the two things it did not cover**. A localhost
run exercises exactly those, against the real image, before a server is
involved. It is the cheapest way to turn "authored and reviewed" into "booted".

**Run it from the host, not from the dev container.** The dev container has no
Docker daemon and no `/var/run/docker.sock`, so `docker compose` is not merely
missing a binary there — there is nothing for it to talk to.

```bash
cd deploy
cp .env.example .env        # then apply the four localhost-specific values below
docker compose up -d
docker compose logs -f create-site     # one-shot; wait for it to finish
```

Four values differ from a server deployment, and three of them will bite:

| Value | Server | Localhost | Why |
|---|---|---|---|
| `SITE_NAME` | real domain | `vectora.localhost` | browsers resolve `*.localhost` to loopback (RFC 6761). The Host header you browse with does not have to match: `frontend` sets `FRAPPE_SITE_NAME_HEADER` to `SITE_NAME`, so nginx names the site to the backend explicitly |
| `HTTP_PUBLISH_PORT` | 8080 | **8090** | the dev container already serves vite on 8080 and bench on 8000. Publishing on 8080 collides with whichever claimed the host port first, and the symptom is a page from the wrong server rather than a bind error |
| `VECTORA_TAG` | a release | `develop` | see below — `:stable` is not what you want to rehearse |
| TLS | required | none | the site is loopback-only; the TLS section below does not apply |

Then browse `http://localhost:8090/crm` and log in as `Administrator` with
`ADMIN_PASSWORD`.

### The image is the part people get wrong

`:stable` is a moving pointer to the newest **main** or release-tag build, and main is the last
release. So a localhost rehearsal pinned to `:stable` rehearses the last
release, not the code you are about to ship — which is the opposite of the
point. Publish the current branch first:

```bash
gh workflow run builds.yml --ref develop
```

That produces two tags: `:develop` and `:sha-<short>`. `:stable` is only
written by a build of `main` or a `v*` tag, so a develop dispatch cannot move it — an earlier
version of the workflow tagged every build `:stable`, which meant a rehearsal
silently redirected whatever was pulling "newest main" at a develop commit.

The build guard requires this commit's **Playwright E2E Tests**, **Server
Tests** and **Unit Tests & Coverage** checks to be green. All three suites run
on pushes to `develop` as well as `main`, so a develop dispatch satisfies it
without a release. A dispatch of a commit whose checks are absent or red is
refused rather than published.

### What a localhost run does and does not prove

It proves the image boots, `create-site` completes, the volume layout is right,
nginx routes to the backend and the socket, the workers and scheduler come up,
and — with `--profile local-model` — that ollama pulls and answers. That is the
whole unrehearsed half of the deployment.

It does not prove anything about TLS, DNS, real mail delivery, or performance
under a real dataset, and a loopback site cannot receive an inbound webhook.
Those stay open until a real host runs it.

## TLS

This stack does not terminate TLS. Put your standard reverse proxy (Traefik,
Caddy, nginx with certbot) in front of the `frontend` service and forward to
`HTTP_PUBLISH_PORT`. If you already run frappe_docker's Traefik overlay,
`frontend` here is the same nginx it expects.

**The HTTP port is bound to loopback by default** —
`127.0.0.1:${HTTP_PUBLISH_PORT}` — so a proxy on the same host reaches it at
`http://127.0.0.1:8080` and nothing else can. That is the shape to keep: the
port speaks plain HTTP and carries session cookies, and Docker's published
ports bypass host firewall rules such as `ufw`, so a `0.0.0.0` bind is open to
the internet the moment it exists, whatever the firewall says.

If the proxy runs on another machine, expose the port deliberately in `.env`:

```bash
HTTP_BIND_ADDRESS=0.0.0.0      # or the host's private-network address
```

and restrict who can reach it at the network layer yourself, because once the
bind is not loopback, nothing in this stack does.

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
somebody reports a bug. (`VECTORA_TAG=stable`, set explicitly — the compose
file has no default — restores pull-and-go, at the cost of not being able to
say what a given host is running.)

**Step 2 is not ceremony.** `up -d` starts serving the new code immediately,
and `migrate` then takes as long as it takes — minutes on a real dataset. In
that window reps are on new code against an old schema, which is the one
combination nothing is tested against. Maintenance mode gives them an honest
"be right back" instead of errors that look like data loss.

*Rehearsed (2026-08-18), and worth being exact about what that did and did not
prove.* `migrate` was run against a scratch site restored from a real
1,716-deal backup. It completed without error, every record count survived
unchanged, and the site still logged in and served Vectora endpoints afterwards
— so schema sync, doctype and customization updates, and the orphan sweep are
all known to survive production-shaped data.

It did **not** exercise the patches. A restored database carries the origin's
`Patch Log`, so all 33 entries in `crm/patches.txt` were already recorded and
`migrate` skipped every one. Patches applying cleanly on a *fresh* site is still
only covered by CI. Nor did this go through `docker compose exec`, so the
container swap in steps 1–2 remains unrehearsed.

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
# stop here if the password is unset or empty -- see below for why
: "${DB_ROOT_PASSWORD:?set it in .env before restoring}"

docker compose exec -T backend bench --site <site> restore --force \
  --db-root-username root --db-root-password "$DB_ROOT_PASSWORD" \
  /home/frappe/frappe-bench/sites/<site>/private/backups/<file>.sql.gz \
  --with-public-files <files>.tar --with-private-files <private>.tar
```

**Both root flags are load-bearing, for different reasons.** `restore` drops and
recreates the database, which the site's own credentials may not be allowed to
do, so it opens a second connection as the MySQL superuser. Frappe resolves those
credentials in `get_root_connection` (`frappe/database/mariadb/setup_db.py`), and
neither flag carries a click default: an omitted flag arrives as `None`, not as
`"root"`.

`--db-root-password` has no terminal guard. Omit it — or let `DB_ROOT_PASSWORD`
expand empty, which looks identical from inside — and the lookup falls through to
`getpass()`, which with the `-T` above has no terminal to read and raises a bare
`EOFError`. Not "password missing"; a traceback, at the one moment you cannot
afford to decode one. Hence the guard line above, which catches unset and empty
alike and does not `exit` — so pasting it into a live shell cannot close it. The `backend` service does not
carry `DB_ROOT_PASSWORD` in its environment (only `db` gets it, from `.env`), so
nothing fills it in for you — take the value from `.env` on the host, where
compose already reads it.

`--db-root-username` is guarded by `sys.__stdin__.isatty()`, so it behaves in two
ways and only one of them is visible here. With `-T` there is no TTY, the guard
short-circuits, and it resolves to `root` silently. Run the same command *without*
`-T` — at a shell, which is where you will be during an incident — and it stops on
`Enter mysql super user [root]:`, a prompt nothing in this runbook predicted.
Passing it explicitly makes the command behave the same either way.

Verified by running the restore both ways against a real backup, and by
exercising both credential paths with stdin redirected.

Which means the restore drill in the pilot checklist below is not a nice-to-have:
it is the rehearsal for the only rollback you have. If step 0's backup has never
been restored, you do not have a rollback, you have a file.

**What a restore does and does not carry.** `restore` takes the SQL dump and,
optionally, the two file tars — nothing else. It never reads the
`site_config_backup.json` that `bench backup` writes beside the dump (see the
option list at `frappe/commands/site.py:164`), so a site's *configuration* does
not travel with its data. That is worth knowing in both directions:

- A dev site's unsafe flags — the bench in this repo's dev container carries
  `ignore_csrf: 1`, `developer_mode: 1`, `allow_tests: 1`, `mute_emails: 1` —
  **do not** follow a backup into this stack. `create-site` gives frappe's
  defaults, which are the safe ones, and a restore leaves them alone. Copying a
  site *directory* in by hand is a different matter, because that is the file
  itself.
- Neither does anything else you configured. A restore onto a fresh site does
  not reinstate the agent endpoint, mail settings, or anything else that lives
  in site config rather than in the database.

Either way, check it after any restore whose origin you are not certain of:

```bash
docker compose exec -T backend cat sites/${SITE_NAME}/site_config.json
```

**Treat the backup files themselves as secrets.** `copy_site_config` is a
verbatim copy of `site_config.json` (`frappe/utils/backups.py:382`), so the
`site_config_backup.json` sitting beside every dump carries that site's
`db_password` and `encryption_key` in plaintext. The encryption key is what
decrypts stored passwords, so a leaked backup directory is not only a data
disclosure.

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

## Telemetry

Off unless two things are both true: `pulse_api_key` is set in the site's
config **and** *Enable Telemetry* is on in System Settings (`developer_mode`
also switches it off). `create-site` sets neither key, so a stack built from
this directory sends nothing — the check is
`frappe.utils.telemetry.pulse.client.is_enabled`, and the first line of it
returns on the missing key.

When it is on, the CRM adds one daily event (`crm.telemetry.capture_feature_state`,
in `crm/hooks.py`'s `daily` list) on top of frappe's own: which integrations
are enabled and row counts — leads synced, products, hierarchy nodes. Feature
flags and counts; no record content, names, or values. The desk UI's usage
events come from frappe and follow the same switch.

To opt out on a site that has a key:

```bash
# the switch telemetry actually reads
docker compose exec backend bench --site <site> execute frappe.client.set_value \
  --kwargs '{"doctype": "System Settings", "name": "System Settings", "fieldname": "enable_telemetry", "value": 0}'
# or: desk UI → System Settings → untick Enable Telemetry
```

Removing `pulse_api_key` from `site_config.json` is the other off switch, and
the more durable one: a setup-wizard re-run can tick the checkbox back.

## site_config keys

Everything this stack reads from `sites/<site>/site_config.json`, set with
`docker compose exec backend bench --site <site> set-config <key> <value>`.
Unset means off for all of them.

| Key | What it does | Production? |
|---|---|---|
| `crm_seed_demo_data` | Lets the setup wizard seed fake leads, deals and users — see [First boot](#first-boot) for why that is opt-in and what clearing it later removes | No. Scratch and rehearsal sites only |
| `crm_enable_lead_syncing` | Turns the Facebook lead-ads connector back on, with the paging bug described [below](#lead-syncing-is-off) | Only if you accept that behaviour |
| `crm_proxy_read_timeout` | Tells the backend what `PROXY_READ_TIMEOUT` nginx was given, so **CRM Agent Settings** can allow a matching agent `timeout` — see [Operating the proactive tier](#operating-the-proactive-tier) | Yes, when you raise the proxy ceiling; keep the two equal |
| `is_demo_site` | Shows the "try it / sign up" banner in the sidebar (`window.is_demo_site`) | No |
| `developer_mode` | Frappe's developer mode: writes doctype JSON to disk on save, relaxes several checks, disables telemetry | **Never.** Changes made in the UI become file edits inside the container |
| `demo_username` / `demo_password` | Together they make `crm.api.live_demo.login` log any visitor in as that user **without a password** (the endpoint returns immediately unless both are set) | **Never set these on production.** They are a password-less login for that account, by design, for the public demo site only |
| `enable_scheduler` | Whether cron jobs run; `create-site` sets it to 1 every boot | Must be 1 — check with `bench doctor` |
| `pulse_api_key` | Telemetry destination; absent means off — see [Telemetry](#telemetry) | Your call |

`site_config.json` is a file in the `sites` volume, so it survives image
upgrades and does not travel with a backup — see the restore notes above. Read
it back with `docker compose exec -T backend cat sites/<site>/site_config.json`.

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
   again on the real stack before the pilot takes real data. Tearing the scratch
   site down afterwards is what surfaced the `--db-root-username` prompt above —
   the drill keeps paying out at every stage, including the cleanup.
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
