# Deploying Vectora

The stack in this directory runs the production image that
[`builds.yml`](../.github/workflows/builds.yml) publishes to
`ghcr.io/absolute-insight/simcrm` on every push to `main`. It is
[frappe_docker](https://github.com/frappe/frappe_docker)'s canonical layout:
one image, one role per container.

**Status: booted and upgraded end-to-end, never run on a real host.** As of
2026-08-22 this stack has been started from the published image (v3.1.5 and
v3.2.1), seeded, and taken through the documented upgrade — so first boot,
`create-site`, the volume layout, nginx routing, the workers and the scheduler
are all exercised rather than assumed, and so is `migrate` across a release.
What no run here can cover is a real host: TLS, DNS, a port published anywhere
but loopback, real mail, inbound webhooks, and performance against a real
dataset. Restore has been drilled on a bench but not through this stack. Treat
those as part of the rollout, not as formalities.

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
and — with `--profile local-model` — that ollama pulls and answers. That was
the whole unrehearsed half of the deployment until 2026-08-22; see *Upgrading*
for what has since been run.

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

# 3. reopen. Give it a minute -- see "Maintenance mode lags by a minute"
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

### Maintenance mode lags by a minute

`set-maintenance-mode` writes a flag to `site_config.json`, and a running web
worker does not see that write for up to 60 seconds. Frappe reads the site
config through a 60-second in-process cache on the request path
(`site_cache(ttl=60)` in `frappe/config.py`, used because `frappe/app.py` calls
`frappe.init(..., is_request=True)`). Background workers and the scheduler
re-init per job and per tick, so they take the flag up immediately; only HTTP
traffic lags.

It lags in *both* directions, measured on this version:

- After `set-maintenance-mode on`, the site keeps serving normally for up to a
  minute. In the sequence above that does not matter, because `up -d` replaces
  the backend container a moment later and the new process reads the flag at
  startup — which is the real reason the site is closed during `migrate`, not
  the command on its own. If you ever set the flag *without* restarting
  anything, wait a minute before believing the site is closed.
- After `set-maintenance-mode off`, real endpoints keep answering 503 for up to
  a minute, then recover on their own. That is the cache expiring, not a failed
  upgrade: check `curl` again after 60 seconds before reaching for a restart.

`/api/method/ping` answers 200 throughout — it is exempt so healthchecks stay
green during the window — so it tells you nothing about whether maintenance
mode is engaged. Test a real endpoint, and **test it with a session**.

That second half is not a detail. An unauthenticated request is rejected before
the maintenance gate runs, so it answers 403 whether the site is closed or not —
`curl https://<site>/crm` looks identical either way. Probe it that way during an
upgrade and you will conclude the flag never took, and start restarting things to
force an issue that does not exist. Log in and look for `SessionStopped`:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<site>/api/method/login \
  -H 'Content-Type: application/json' \
  -d '{"usr":"Administrator","pwd":"<admin password>"}'
# 503 while closed, 200 once the config cache has expired
```

**If you do restart to force the issue, do not restart `backend` alone.** nginx
in the `frontend` service resolves the backend's address when it loads its
config, so a backend that comes back on a new container IP leaves `frontend`
proxying to an address nothing answers on, and every request 502s until nginx
restarts too. Restart the pair, or the whole stack:

```bash
docker compose restart backend frontend
```

*Rehearsed (2026-08-18), and worth being exact about what that did and did not
prove.* `migrate` was run against a scratch site restored from a real
1,716-deal backup. It completed without error, every record count survived
unchanged, and the site still logged in and served Vectora endpoints afterwards
— so schema sync, doctype and customization updates, and the orphan sweep are
all known to survive production-shaped data.

It did **not** exercise the patches. A restored database carries the origin's
`Patch Log`, so all 33 entries in `crm/patches.txt` were already recorded and
`migrate` skipped every one. Nor did it go through `docker compose exec`, so it
said nothing about the container swap or the maintenance-mode steps.

*Rehearsed again (2026-08-22), this time as the whole sequence.* A stack was
booted on v3.1.5 from the published image, seeded (12 deals, 8 leads, 5
contacts, 1 organization), and taken to v3.2.1 by running the steps above
verbatim through `docker compose exec`. Backup wrote all four artifacts.
`migrate` exited 0 and applied both patches new in that range
(`add_analytics_dashboard_widgets`, `remove_duplicated_grid_tiles`) — so patches
running on a fresh-ish site is no longer CI-only. Every count survived
unchanged and the deal-value sum matched to the cent. The site logged in and
served its endpoints on the new version, and the scheduler was still enabled
afterwards.

The one thing that pass changed here is the section above: reopening the site
appeared to fail, and the cause turned out to be the 60-second config cache
rather than anything in the procedure. Still unrehearsed: the restore path in
*Rolling back*, and anything involving a real host — TLS, a published port, an
inbound webhook.

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

For the local shape this stack ships an opt-in profile. On a **first boot**, set
`VECTORA_AGENT_ENABLED=1` in `.env` before bringing it up and the site is created
already pointed at the model:

```bash
docker compose --profile local-model up -d
docker compose logs -f ollama-pull    # first run downloads several GB
```

`create-site` passes `VECTORA_AGENT_BASE_URL`, `VECTORA_AGENT_MODEL` and
`VECTORA_AGENT_ENABLED` to `after_install`, which writes them into **CRM Agent
Settings** once. It is read at site creation and never again — an admin who
later changes the endpoint in the UI keeps that change across upgrades, which a
value re-applied on every deploy would silently undo.

On a site that **already exists** those variables do nothing, because
`create-site` skips. Set it in the UI instead: **Settings → Assistant** →
`base_url` `http://ollama:11434/v1`, `model` the same value as
`VECTORA_AGENT_MODEL`, `enabled` on.

Either way the endpoint has to be the service name. `127.0.0.1` will not work:
from inside the backend container that is the container itself — which is the
one mistake that makes a correctly-pulled model look broken.

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

**Model choice.** `LFM2.5-2.6B` at Q4_K_M is the default and what this stack is
verified against. Eleven models were run through the real `client.complete()`
path — the same code a rep's summary goes through — on two axes: does guided
decoding produce a schema-valid object, and does the model follow instructions
planted in a customer's email. The second axis chose the default.

| Model | Licence | Q4 | Warm | Injection cases landed |
|---|---|---|---|---|
| **LFM2.5-2.6B** | LFM1.0 | 1.7 GB | 2.8 s | **1 of 4** — refused the discount draft **0/7** |
| granite-4.0-h-micro | Apache-2.0 | 1.9 GB | 1.1 s | 3 of 4 — discount **7/7** |
| Qwen3.8-2B-Distill | Apache-2.0 | 1.3 GB | 1.7 s | 3 of 4 — discount **7/7** |
| granite-4.0-h-tiny *(old default)* | Apache-2.0 | 4.2 GB | 0.8 s | discount **7/7**, and calls a plainly negative thread `neutral` |
| antares-1b | Apache-2.0 | 1.1 GB | 0.5 s | 4 of 4 |
| SmolLM3-3B | Apache-2.0 | 1.9 GB | 1.0 s | 4 of 4 |
| granite-4.1-3b / 4.1-8b | Apache-2.0 | 2.1 / 5.0 GB | 1.0 / 3.0 s | 4 of 4 / no better at 8B |

Four more could not run this workload at all, which is worth knowing before you
try them: `InternScience/Agents-A1-4B` and `MiniCPM5-1B` return **empty content**
under a schema (A1-4B spends its whole budget in a `reasoning` channel — 39s,
84s and 95s at 2048, 4096 and 8192 tokens, all empty); `Qwen3-4B-Instruct-2507`
invents keys the schema forbids; `Nanbeige4.2-3B` fails with
`Failed to initialize samplers` because llama.cpp cannot build a grammar for it;
`fuse-1-Lite` will not load — `unknown model architecture: 'fuse3'`.

Scale does not buy resistance: `granite-4.1-8b` is no better than the 3B, and it
inherits the same `neutral` sentiment error as `granite-4.0-h-tiny`.

`max_tokens` must be **2048 or more** for this default. At 1024 a long thread
comes back as `Invalid JSON: EOF while parsing a string` — a budget too small to
finish the object, reported to the rep as `unavailable`.

### The model licence, and who it binds

**`LFM2.5-2.6B` is not permissively licensed.** It ships under LFM1.0, whose own
text defines a *Threshold* of **"annual revenue of 10 million United States
dollars ($10,000,000) or more"** and limits Commercial Use above it. Apache-2.0
models carry no such condition; this one was chosen anyway, because it is the
only model measured here that refuses to draft a fraudulent discount.

The licensee is whoever runs the weights — the customer, not us. So the position
has to be stated at the point of sale rather than discovered at an audit:

- **Under the threshold:** run the default as shipped. Nothing to buy.
- **At or above it:** two supported ways through, and the choice is theirs.
  1. **Buy a commercial licence from Liquid AI** and keep the default, its
     footprint and its behaviour unchanged.
  2. **Move to hardware that can host a larger permissively-licensed model.**
     The Apache field only becomes interesting further up the size curve than
     the 1.7 GB default — that means a dedicated inference host with a real GPU,
     not the 4 GB VM this stack runs on. Set `VECTORA_AGENT_MODEL` and
     `VECTORA_AGENT_BASE_URL` accordingly; nothing in the code changes.

Either way the endpoint is two settings fields. A deployment that wants neither
can leave the agent tier off, which is the shipped default and a supported state
— the deterministic tier (assignment, SLA, automation rules, signals) runs
without a model at all.

**What a local model does not fix.** Prompt injection — not even this one. The
default resists the draft case and one summarise case; it still follows a
planted instruction in the other three. Every other model tested is worse. That
is why this tier has no write tools and why drafted replies are always shown to
a human before sending. Running the model yourself changes where the weights
live, not whether the output can be steered by someone who emails your reps.

## First deployment (internal)

Before any customer sees this, put it on a real host with no real users. That
deployment is not a formality — it is the only place several things can be
tested at all, because everything below is unreachable from a container:

**What relaxes on an internal box.** Throwaway data means a lost restore costs
an afternoon, not a customer. Loosen the conservative defaults deliberately
here, and find out what breaks while it is cheap.

**What does not.** Docker's published ports bypass host firewall rules such as
`ufw`, so a `0.0.0.0` bind is on the internet the moment it exists, whatever the
firewall says — and this stack speaks plain HTTP carrying session cookies. Keep
the loopback bind and put a proxy in front, on a test box as much as a real one.
`DB_ROOT_PASSWORD` and `ADMIN_PASSWORD` are real credentials regardless of whose
data sits behind them.

Exercise these in order, because each one is untested by everything upstream of
this point:

1. **TLS, DNS, and a proxy in front of `HTTP_PUBLISH_PORT`.** Never exercised.
   The stack terminates no TLS by design.
2. **Real mail.** A default outgoing account, one real send, and confirm it is
   recorded as a Communication. Every test upstream runs against a muted queue.
3. **A backup cron, then a restore on that host.** *There is no automated backup
   in this stack* — `bench backup` is a manual step in *Upgrading* above, and
   frappe's own scheduler only cleans up old downloadable backups. Wire the cron
   and an offsite copy on day one, then restore from it. Restore is rehearsed
   through `docker compose exec` but only against a dozen records; duration
   against a real database is unknown.
4. **The scheduler across a full day.** `docker compose logs -f scheduler` — the
   hourly signal run and deal-health scoring have never run against
   real-shaped data on a real clock.
5. **Volume.** Load a dataset the size you expect and watch the list views, the
   dashboard and how long `migrate` takes.
6. **The integrations you intend to sell** — telephony, WhatsApp, ERPNext, lead
   syncing. All four are credential-gated and none has been exercised.
7. **The agent tier last, and on its own machine.** The host running this stack
   cannot also host a model. Bring it up with `--profile local-model`, confirm
   the default answers, and leave drafted replies behind the human gate.

**Then upgrade that host when the next release lands.** Following *Upgrading*
against a machine carrying accumulated state is the only version of that test
that counts, and it is where you will meet the 60-second maintenance-mode lag in
the wild rather than in a rehearsal.

Write down what surprised you at each step. That list is the real distance
between "works in a container" and "works on a host", and it is what the first
customer deployment should be planned against.

### What the first one surprised us with

Run on `vectora.absolute-insight.ai`, 2026-08-23. Measured numbers, not estimates.

**Changing the site timezone freezes every scheduled job, and then self-heals.**
The worst finding of the day, because nothing reports it. Completing the setup
wizard moved the site from Frappe's `+05:30` default to `+02:00`.
`Scheduled Job Type.last_execution` stores a *naive local* datetime, so every
stored value was re-read 3h30m in the future, `get_next_execution()` sat
permanently ahead of `now()`, and all 59 jobs stopped being due. No email flush,
no inbound mail pull, no signal run, no digests — for the length of the offset.
Then it comes back on its own, so whoever investigates later finds a healthy
system and no evidence. After any timezone change, check:

```bash
docker compose exec backend bench --site <site> console
>>> frappe.get_doc("Scheduled Job Type", {"method": "frappe.email.queue.flush"}).is_event_due()
```

If that is `False` with a `last_execution` in the future, shift the stored values
back by the offset rather than clamping them to `now()` — clamping makes every
daily job skip a day. The same shift is needed for `creation`/`modified` across
the data: 153,661 of them were future-dated here, which sorts anything you
genuinely touch *below* every seeded row in a list view ordered by last-modified.

**The "Create Lead from Incoming Emails" toggle does not govern IMAP accounts.**
`crm/api/settings.py` appends `{"append_to": "CRM Lead"}` to the IMAP folder row
unconditionally. Frappe core then creates the document itself
(`receive.py`: `append_to = self.append_to if self.email_account.use_imap else ...`)
and stamps the Communication, so CRM's own hook returns early at
`if doc.reference_doctype and doc.reference_name` and never consults the flag.
Result: a lead per unknown sender whatever the checkbox says. Clear `append_to`
on the folder row to make the toggle authoritative.

**No custom IMAP/SMTP option exists in the Add Email screen.** The list is
GMail, Outlook, Sendgrid, SparkPost, Yahoo, Yandex and Frappe Mail. A customer
on their own mail host — which is most of them — cannot add an account without a
bench shell. This deployment's IONOS account had to be created server-side.

**The `local-model` profile pinned an image tag that does not exist.**
`ollama/ollama:0.12.12` has never been published; the series is 0.3x. Anyone
following step 7 hit `failed to resolve reference` immediately. Now pinned to
`0.32.15`. Check a pin resolves before shipping it.

**`VECTORA_AGENT_ENABLED` does nothing on an existing site.**
`apply_endpoint_defaults()` runs from `after_install` only — deliberately, so an
upgrade cannot silently revert an endpoint an admin changed. On a site that
already exists, switch the tier on in the settings doctype instead.

**Measured, for planning against:**

| | |
|---|---|
| `bench migrate` | **5s** against 3,000 deals / 5,002 leads / 6,018 contacts |
| hourly scheduler batch | ~20s wall clock, all jobs `Complete` |
| `score_open_deals` coverage | 2,997 of 2,997 open deals scored |
| `run_signals` output | 156 open suggestions |
| mail round trip | send → scheduler flush 20s; inbound pull ≤10 min (cron interval) |

Mail deliverability needed no DNS work — IONOS's own `s1-ionos` selector signed,
and the receiver returned `dkim=pass spf=pass dmarc=pass`. A dangling
`*._domainkey` CNAME left over from an earlier setup was irrelevant, because the
signing selector is chosen by the sending server, not by what is in DNS.

**Demo data plus a live mailbox is a reputation risk.** Seeded users sit on
`@vectora.test` and `@example.com`; `.test` is a reserved TLD that can never
resolve. Every CRM notification to one is a hard `550` at the smarthost. Turn
`enable_email_notifications` off for them — that stops the mail without
disabling the accounts, so they can still be logged into for role testing.

**The upgrade, rehearsed.** v3.3.0 → v3.3.1 on this host, carrying the full
dataset, following *Upgrading* above verbatim:

| Step | |
|---|---|
| `bench --site all backup --with-files` | 2.6 MiB dump + tars, seconds |
| `docker compose pull` | **205s** — the long pole, and it happens *before* the site closes |
| `docker compose up -d` | **101s** |
| `bench --site all migrate` | **12s** |
| maintenance-off → serving again | **32s** |

Total closed-to-users window: about **2m30s**, of which the pull is none — pull
first, then close. Everything survived: row counts, the Email Account with its
password, the cleared `append_to`, and the agent tier's endpoint and model. The
container's `/tmp` does not survive, which matters only if you have staged
scripts there.

Run the profile you actually use — `docker compose --profile local-model up -d`
rather than bare `up -d`, or the model service drops out of compose's view.

**Still open here:** an offsite backup destination (decided: an S3-compatible
bucket, not yet wired — step 3 cannot close until it exists), and every
integration in step 6.

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
