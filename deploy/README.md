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

`create-site` is idempotent: it skips the create when the site already exists
— a `sites/<site>/site_config.json`, and no marker saying a create is still in
flight — so `docker compose up -d` is always safe to re-run. What it does on
*every* run is `bench enable-scheduler`: `bench new-site` writes
`enable_scheduler: 0` into the new site's config, and a site left that way has
every cron job in `crm/hooks.py` — the hourly signal run, deal-health scoring,
the daily digest — silently not running, with nothing in any log to say so.

**A first boot that dies partway repairs itself.** `create-site` leaves a marker
(`sites/.creating-<site>`) for exactly as long as `bench new-site` is running.
If the container is killed in that window — the 1 GB limit, a host reboot —
the next start finds the marker, removes the half-made site directory and
creates the site again; it used to find the directory, take it for a site, and
restart for ever against a database that had never been made.

Removal needs two things, not one: the marker, **and** the database itself
saying there is nothing there — it does not exist, has no frappe tables, or
does not record every app the create installs. A site with no marker is never
touched. A marker beside a database that looks complete, or that could not be
asked, removes nothing: `create-site` exits with the three commands that
settle it (inspect, clear the marker, or remove the failed attempt), because a
question that went unanswered is not grounds to delete a site and its
encryption key. The one thing an automatic retry leaves behind is the
abandoned attempt's database, whose name the log prints so it can be dropped
by hand.

**Keep other users off the host during first boot.** `bench new-site` takes
the database root password and the administrator password as command-line
options and has no other supported way to receive them, so for the minute the
site takes to create both are readable in the host's process table (`ps`,
`docker top`). After that they exist only in `.env` and the container
environment.

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

### Running a QA stack beside production on the same host

The table above assumes the rehearsal *is* the deployment, with a `.env` of its
own. On a host that runs both — `vectora` for production and `vectora-qa`
alongside it — there is only one `deploy/.env`, and it holds production's
values. The two stacks are separated by `-p` and by the override file, **not by
their environment**, so every variable in that table is production's unless you
say otherwise on the command line.

**Give the QA stack its own env file and pass it every time.** This host keeps
one at `~/backups/vectora/qa-stack.env` — outside the repository, because it
holds `DB_ROOT_PASSWORD` and `ADMIN_PASSWORD` and this repository is public:

```bash
docker compose -p vectora-qa -f docker-compose.yml \
  --env-file ~/backups/vectora/qa-stack.env up -d
```

Overriding only the two variables below on the command line looks equivalent
and is not:

```bash
# works, but leaves DB_ROOT_PASSWORD pointing at production's
SITE_NAME=vectora.localhost HTTP_PUBLISH_PORT=8091 \
  docker compose -p vectora-qa -f docker-compose.yml up -d
```

MariaDB sets the root password **once, when the data directory is initialised**,
and ignores the environment on every later boot. So a QA stack recreated from
production's `.env` runs perfectly — the site authenticates with its own user
out of `site_config.json` — while `DB_ROOT_PASSWORD` silently no longer matches
the database. Nothing notices until something needs root: `bench new-site`,
`bench restore`, `bench drop-site`. Those fail with `Access denied for user
'root'`, which reads like a corrupted stack rather than a stale variable.

That is the state this host was left in on 2026-09-19. Harmless day to day,
and corrected by the next `up -d` that passes `--env-file`.

Two variables in that file are the ones that break the stack outright:

**`SITE_NAME` decides whether `create-site` creates anything.** It skips only
when `sites/${SITE_NAME}/site_config.json` exists. Inherit production's name
and it looks for production's site in the QA volume, does not find it, and runs
`bench new-site` — which fails at `install_db` with `Access denied for user
'_<hash>'`, because `DB_ROOT_PASSWORD` is production's too. `restart:
on-failure` turns that into a restart loop, and every long-running service
waits on `create-site`, so the whole stack stays down until it is brought up
with the right env file. Each attempt now cleans up after itself (see [First
boot](#first-boot)), so the right name is all the recovery there is; before
that the first failure left a half-built directory that had to be deleted from
the QA `sites` volume by hand.

**`HTTP_PUBLISH_PORT` is a straight collision.** Both stacks want 8090;
whichever starts first gets it and the other fails to bind with `port is
already allocated`. Production publishes 8090 for local access — it is reached
publicly through the `sim-net` alias, not the published port — so give QA
8091.

Pass the env file on *every* QA command, not only when you intend to recreate:
`up -d` recreates whenever the resolved config changes, so the moment you get
it wrong is rarely the moment you expected to.

**And after any recreation, put the model network back.** QA has no model
server of its own; its backend and both queue workers reach production's
`vectora-llm-1` over a network that exists for that and nothing else. `up
-d` drops the attachment every time, and the agent surfaces then fail
*silently* — they render normally and never answer. Verify rather than assume:

```bash
# once per host: a network with the model server on it and nothing else
docker network create vectora-model-net 2>/dev/null || true
docker network connect vectora-model-net vectora-llm-1 2>/dev/null || true

for c in vectora-qa-backend-1 vectora-qa-queue-short-1 vectora-qa-queue-long-1; do
  docker network connect vectora-model-net "$c" 2>/dev/null || true
  docker exec "$c" curl -s -o /dev/null -w "$c %{http_code}\n" \
    http://vectora-llm-1:8086/v1/models            # expect 200
  docker exec "$c" getent hosts db redis-cache redis-queue   # expect ONE address each
done
```

**Do not attach QA to `vectora_default`**, which is what this section used to
say. That is production's whole network, and both stacks are the same compose
file: every service answers to the same alias (`db`, `redis-cache`,
`redis-queue`) on its own project network. A QA container joined to both
networks resolves each of those names to *two* addresses, and which one a
connection gets is up to Docker's resolver. Redis here has no password, so
nothing refuses the wrong one: a QA worker can take jobs off production's
queue — and drop them, because they name a site it does not have — while QA's
own enqueues land in production. The `getent` line above is the check: two
addresses for any of the three means a container is still on production's
network, and `docker network disconnect vectora_default <container>` is the
fix. On `vectora-model-net` the only production name QA can resolve is the model
server's.

`vectora-llm-1` loses the attachment when it is recreated — which needs
`--profile gpu-model`, so a routine `up -d` does not do it. Re-run the two
"once per host" lines after any upgrade that did.

Sharing the tag is fine and deliberate: QA should run the same version as
production. Stage an upgrade by setting `VECTORA_TAG` once, recreating
`vectora-qa` first, checking it, then recreating `vectora`. One declared
version, two separately-timed rollouts.

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
and — with `--profile gpu-model`, on a host with an NVIDIA card — that the
model is pulled, checked against its pin and answers. That was
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

**Tell nginx which proxy to believe.** The `frontend` container reads the
client address from `X-Forwarded-For`, but only when the request arrives from
an address in `UPSTREAM_REAL_IP_ADDRESS`. The default covers Docker's private
range, which is where a proxy on this host appears from (as the compose
network's gateway, or as a sibling container). A proxy on another machine needs
its address there instead. Get this wrong and every request reaches frappe
with the same address, so the per-IP rate limits (login attempts, invitation
acceptance) become one shared bucket for the whole company. Changing it needs
`docker compose up -d`, not just a restart, so the container picks up the new
environment.

### `host_name`, and the Host header

**Your proxy must refuse Host headers that are not yours.** The `frontend`
container does not route on Host at all: it names the site to the backend
itself (`FRAPPE_SITE_NAME_HEADER`), so a request for any hostname that reaches
the port is served as this site. That is convenient for a rehearsal and it
means nothing in this stack filters Host. Frappe, meanwhile, builds the
absolute links it emails — password resets, invitations, share links — from
`host_name` in the site's config if there is one, and otherwise from the Host
header of the request that triggered the email. So with neither a filtering
proxy nor a `host_name`, anyone who can reach the proxy can ask for a password
reset for a real user with a Host header of their own, and the email that user
receives carries a link to the attacker's server.

Close both ends:

- On the proxy, serve only the real hostname and reject or drop everything
  else — a default server that returns 444 in nginx, a `Host()` rule and no
  catch-all router in Traefik, an explicit site address in Caddy.
- In `.env`, set `SITE_HOST_NAME` to the public URL, scheme included:

  ```bash
  SITE_HOST_NAME=https://crm.example.com
  ```

  `create-site` writes it to the site's `host_name` on the next `docker compose
  up -d`, and links stop depending on what a request claimed. It is optional
  and unset by default: unset, nothing is written, and a `host_name` you set by
  hand (the [WhatsApp](#whatsapp) steps have you do that) stays as it is. Once
  set it is re-applied on every `up -d`, so `.env` is then where to change it.
  A value without `http://` or `https://` is refused with a line in the
  `create-site` log rather than written.

## Installing it as an app (PWA)

Vectora ships a web app manifest and a service worker, so a browser can install
it to a desktop or home screen and run it in its own window. Nothing needs
turning on — but two things have to be true of the deployment, and one of them
is easy to break from outside this stack.

**It needs a secure context.** Service workers register only over HTTPS, or on
`localhost`. A rehearsal on `vectora.localhost:8090` therefore installs fine; a
real host reached over plain HTTP does not, which is one more reason the TLS
section above is not optional.

**It needs the `Service-Worker-Allowed` header to survive your proxy.** The
worker is served from `/assets/crm/frontend/sw.js` but has to control `/crm`,
and a worker may not claim a scope above its own directory unless the response
says it may. `nginx/security_headers.conf` — mounted into `frontend` by
`docker-compose.yml` — adds `Service-Worker-Allowed: /crm`. A proxy that
rewrites response headers can strip it on the way out.

Check both in one line, against the public URL rather than the container:

```bash
curl -sI https://<site>/assets/crm/frontend/sw.js | grep -i service-worker-allowed
# Service-Worker-Allowed: /crm
```

If it is missing, registration fails with a `SecurityError` in the browser
console and the app carries on with no worker: no offline shell, no install
prompt, everything else unaffected. That is a degradation, not an outage — it
is not worth a rollback, and it is invisible from the server side, so this
`curl` is the only cheap way to know.

To confirm the install itself, open the site in Chrome and look at DevTools →
Application → Manifest: `Scope` and `Start URL` should both read `/crm`, and
the install control appears in the address bar. On iOS the route is Share → Add
to Home Screen, which uses the apple-touch icons and ignores the manifest scope
entirely — it works whether or not the header made it through.

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

**The first `up -d` on a release after v3.30.0 also restarts the database and both
redis containers**, once, because their definitions changed: `db` gained an
InnoDB buffer pool size (see [Sizing the database](#sizing-the-database)), and
both redis images are now pinned by digest — the same 6.2.24 they already run,
and nothing else about either service changed. No data changes: the database
comes back on the same volume, the queue replays its append-only file, and the
cache reloads the snapshot it wrote on the way down, from the `/data` volume
that follows it across the recreate. It is a cold restart of MariaDB all the
same, so let it happen here, inside the maintenance window of step 2, and not
as a surprise the next time somebody runs `up -d` to change a proxy setting.

**The first `up -d` on a release after v3.36.0 also restarts the model
server**, once, if you run the `gpu-model` profile: `llm` and `llm-fetch` are
now pinned by digest — the same `ollama/ollama:0.40.16` they already run, and
nothing else about either changed. `llm-fetch` re-checks the model's
fingerprint, `llm` comes back on the same volume with no download, and the
first question afterwards waits about a minute for the weights to load. Until
then every model surface reports `unavailable`.

**The first `up -d` on a release after v3.37.0 also restarts the model
server**, once, if you run the `gpu-model` profile: `llm` now loads and warms
the model itself as it starts, so its definition changed. It is back in
seconds and warm about a minute and a half later; a question asked in between
waits for the rest of the load, as the first question used to after every
restart.

**That release also removes the `local-model` profile and the model it
served.** There is no longer a model in this stack for a host without an NVIDIA
card: `LFM2.5-2.6B` on the `ollama` service, which ran on a CPU or a small GPU,
is gone, and the one model shipped now is served by `gpu-model` only. A host
that ran `local-model` keeps its old container until it is removed, and its
model surfaces report `unavailable` after `migrate` until `gpu-model` is up, or
`base_url` is pointed at an endpoint elsewhere. The steps are under [The
model](#the-model-nemotron-35-bolt-e4b-gpu-model), "Moving a host from the
`local-model` profile". On any host, delete `VECTORA_AGENT_MODEL`,
`VECTORA_AGENT_BASE_URL` and `OLLAMA_KEEP_ALIVE` from `.env` if the first two
still carry the old values (`hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M`,
`http://ollama:11434/v1`): they do nothing to the existing site, and a site
created later from that file would be pointed at the service that was removed.

**If you run the off-host copy, say so too** — `docker compose --profile
offsite up -d`. `backup-offsite` is behind a profile like the model servers
below, so a plain `up -d` leaves the old container running the old script:
still uploading `site_config_backup.json`, and without the new healthcheck.
See [Getting them off the host](#getting-them-off-the-host).

**If you run the model, say so on every `pull` and `up`** —
`docker compose --profile gpu-model pull` and
`docker compose --profile gpu-model up -d` (or set `COMPOSE_PROFILES=gpu-model`
in `.env` once). A service behind a profile is invisible to a plain `up -d`, so
`llm` is never recreated and never picks up a changed setting. Production once
ran for seventeen days on a model container created before
`OLLAMA_CONTEXT_LENGTH` existed: the server stayed at ollama's 4096 default
while prompts were sized for 8192, so the Analyst's larger tables were refused
as `context_length` and long Assistant and Mentor prompts lost their head — the
system instruction and the grounding. Check what the server is actually running
with, not what the file says:

```bash
docker inspect <project>-llm-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep OLLAMA_CONTEXT_LENGTH
```

**`--site all` is not "every directory under `sites/`".** Frappe counts a
directory as a site only if it contains `site_config.json`, so anything else
parked there is skipped. The production volume currently holds
`sites/qa-data-migration`, which is not a site at all — it is four backup files
from 2026-09-01 left in a folder. Harmless, and `migrate` ignores it, but it
appears in every `ls sites/` and reads like a second site you have forgotten to
maintain. Check for `site_config.json` before believing a listing.

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

### Bumping the database image

`db` is pinned by **digest**, not by tag:

```yaml
image: mariadb:10.6.28@sha256:553351e2...
```

That is not pedantry. `mariadb:10.6` is a moving pointer, and it moved between
2026-09-08 and 2026-09-10. The consequence was that the `docker compose up -d`
in the runbook above — which an operator also runs to apply an unrelated `.env`
change — recreated the production database container with a cold restart in the
middle of the day. The next move of that tag is to 10.6.29, and on a floating
tag the engine would upgrade in place, unrehearsed, with no backup taken.

So a database upgrade is now something you ask for, and it has a backup in
front of it:

```bash
# 0. a backup you could restore from, and check it landed
docker compose exec backend bench --site all backup --with-files

# 1. find the digest of the version you want
docker buildx imagetools inspect mariadb:10.6.29 --format '{{.Manifest.Digest}}'

# 2. edit docker-compose.yml: image: mariadb:10.6.29@sha256:<that digest>
docker compose pull db
docker compose up -d db

# 3. watch it come back before touching anything else
docker compose ps db                       # expect `running (healthy)`
docker compose logs db | tail -40          # look for a mariadb-upgrade prompt
docker compose exec backend bench --site <site> doctor
```

Across a **patch** bump inside a series the on-disk format does not change and
nothing else is needed. Across a **series** bump the system tables do change and
`mariadb-upgrade` has to run. That only happens when `db.env` (below) sets
`MARIADB_AUTO_UPGRADE=1`, and since the image is pinned by digest, a version
change is never something that happens behind your back either way.

**MariaDB 10.6 is past its upstream end of life** (July 2026), so the series
will receive no further fixes and the patch bump above has nowhere left to go.
The way out is the series bump to 11.4 LTS in the next section. Until production
has made it, the engines are deliberately split: production on the 10.6 default
here, the devcontainer and e2e on 11.4, and `server-tests.yml` and
`migration-test.yml` running both. Dependabot proposes patch bumps only, and only
where it can read a literal `image:` -- the devcontainer, not the `DB_IMAGE`
default here.

### Upgrading MariaDB to 11.4

The engine is chosen by one variable. Unset, `db` runs the 10.6.28 digest in
`docker-compose.yml`; set, it runs whatever `.env` says:

```bash
# .env -- the target, as .env.example carries it (commented out)
DB_IMAGE=mariadb:11.4.13@sha256:5e73baf8179b29f115101bb102763a47a017361f3e9792daccba6646c3ab1532
```

**Setting it is the upgrade, and it is one way.** 11.4 rewrites the data
directory (the redo log format changed in 10.8, the system tables in 11.x), and
10.6 cannot open the result. Commenting the line out again does not roll back --
it starts a 10.6 that refuses its own volume. The rollback is below, and it is a
restore. Merging the change that introduced `DB_IMAGE` did nothing to a running
stack: unset, the service resolves to exactly what it did before, so its config
hash is unchanged and `up -d` leaves the database alone (checked with
`docker compose config --hash db` against the previous file).

Frappe supports it: the pinned framework warns only outside 10.6–11.8
(`frappe/database/mariadb/setup_db.py`, `check_compatible_versions`) and runs
its own CI on 11.8. Two things differ from 10.6 that matter here:

- **The `mysql*` command names are gone** from the 11.x image -- `mariadb`,
  `mariadb-admin`, `mariadb-dump` only. Nothing in this stack calls the old
  names (`db`'s healthcheck is `healthcheck.sh`, the app image's client is its
  own 10.11), but a habit of `docker compose exec db mysql` will stop working.
- **A bare `utf8mb4` now means `utf8mb4_uca1400_ai_ci`** (11.4's
  `character_set_collations`). Every frappe table and database names
  `utf8mb4_unicode_ci` explicitly, and the existing data keeps its collation;
  what changes is the default collation of a connection that does not name
  one, which is what frappe's upstream CI on 11.8 runs with too. The rehearsal
  fails if the swap or a migrate leaves any table or column on `uca1400`. If a
  query ever reports "Illegal mix of collations", the fix is a `db` flag,
  `--character-set-collations=utf8mb4=utf8mb4_unicode_ci` (it recreates `db`
  on the next `up -d`).

#### Before the window

1. **Run a release that has `DB_IMAGE`.** `grep DB_IMAGE docker-compose.yml`
   must find it, and `docker compose config --images | grep mariadb` must show
   the 10.6.28 digest -- i.e. nothing has been switched yet.
2. **A fresh backup, and a copy of it somewhere other than this host.** The
   rollback depends on it.

   ```bash
   docker compose exec backend bench --site all backup --with-files
   docker compose exec backend ls -lt sites/<site>/private/backups | head -5
   ```

   Then confirm the off-host copy has it (`backup-offsite`, see
   [Getting them off the host](#getting-them-off-the-host)), or copy the
   `-database.sql.gz` and the `-site_config_backup.json` off by hand. The
   second file holds the site's database password and encryption key: treat
   both as secrets.
3. **Rehearse on that backup.** From a checkout of this repository on a host
   with docker (this one is fine -- it never touches the `vectora` project):

   ```bash
   mkdir -m 700 ~/mdb-rehearsal
   docker compose cp backend:/home/frappe/frappe-bench/sites/<site>/private/backups/<stamp>-<site>-database.sql.gz ~/mdb-rehearsal/
   docker compose cp backend:/home/frappe/frappe-bench/sites/<site>/private/backups/<stamp>-<site>-site_config_backup.json ~/mdb-rehearsal/
   scripts/rehearse-mariadb-upgrade.sh --app ghcr.io/absolute-insight/simcrm:<VECTORA_TAG production runs> ~/mdb-rehearsal
   rm -rf ~/mdb-rehearsal     # afterwards: it is a copy of production
   ```

   It restores the dump onto 10.6 in a throwaway project (internal network, no
   ports, torn down with `down -v` on exit), counts every table's rows and
   checksums the CRM's main tables, shuts 10.6 down slowly, starts 11.4 on the
   same volume with `MARIADB_AUTO_UPGRADE=1`, compares everything again, runs
   `bench migrate`, logs in through the API and reads, and takes a backup from
   the new engine. It must end in `RESULT: PASS`. Its `timings` line sizes the
   window: on the dev site (12 MB of SQL) restore took 13 s, the 11.4 start
   with its upgrade 16 s, migrate 5 s; production's upgrade step is dominated by
   the start-up, not the data, so expect a similar figure plus the shutdown.
4. **Room for the cold copy, and no old one in the way.** Step 3 of the window
   copies the whole data directory into a second volume, so the disk docker
   keeps its volumes on needs at least twice the data directory's size free,
   plus a gigabyte -- one copy for the rollback, the rest for 11.4's upgrade
   work and the night's backup:

   ```bash
   docker run --rm -v vectora_db-data:/d:ro \
     mariadb:10.6.28@sha256:c7d726a1c0d29e486a1ab4ef0c76c75431a11428e76c50e99ba32106cea04114 du -sh /d
   df -h "$(docker info -f '{{.DockerRootDir}}')/volumes"
   docker volume inspect vectora_db-data-pre-11-4 >/dev/null 2>&1 && echo "EXISTS -- stop"
   ```

   If `vectora_db-data-pre-11-4` already exists -- an earlier attempt -- do not
   go on: `cp -a` would merge today's files into that one's, and the result is
   a data directory neither engine wrote. Look at what it is first
   (`docker volume inspect vectora_db-data-pre-11-4` for its creation date,
   and the `du` above with that name), and only once you are sure nothing
   needs it, remove it deliberately with
   `docker volume rm vectora_db-data-pre-11-4`.

#### In the window

```bash
# 1. close the site and stop everything that writes
docker compose exec backend bench --site <site> set-maintenance-mode on
docker compose stop scheduler queue-short queue-long backup
docker compose exec backend bench --site all backup        # the last one on 10.6
docker compose stop frontend websocket backend

# a count to compare afterwards
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -N <db_name>' \
  <<< 'SELECT (SELECT COUNT(*) FROM `tabCRM Lead`), (SELECT COUNT(*) FROM `tabCRM Deal`), (SELECT COUNT(*) FROM `tabCommunication`)'

# 2. a SLOW, complete shutdown of 10.6 -- never a kill
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -e "SET GLOBAL innodb_fast_shutdown = 0"'
docker compose stop -t 600 db
docker compose logs db | tail -3                           # must end in "Shutdown complete"

# 3. a cold copy of the 10.6 data directory: the fast rollback. Into a volume
#    that must not exist yet -- see "Before the window", item 4.
docker volume inspect vectora_db-data-pre-11-4 >/dev/null 2>&1 \
  && echo "vectora_db-data-pre-11-4 exists -- stop" \
  || docker run --rm -v vectora_db-data:/from:ro -v vectora_db-data-pre-11-4:/to \
       mariadb:10.6.28@sha256:c7d726a1c0d29e486a1ab4ef0c76c75431a11428e76c50e99ba32106cea04114 \
       cp -a /from/. /to/

# 4. switch: the image, and the entrypoint's upgrade step.
#    ADD this line to .env -- production's .env predates the commented
#    example in .env.example, so there is nothing to uncomment:
#      DB_IMAGE=mariadb:11.4.13@sha256:5e73baf8179b29f115101bb102763a47a017361f3e9792daccba6646c3ab1532
printf 'MARIADB_AUTO_UPGRADE=1\n' > db.env
docker compose config --images | grep mariadb              # the 11.4.13 digest
docker compose pull db
docker compose up -d db
docker compose ps db                                       # wait for (healthy)
docker compose logs db | grep -E 'Entrypoint|ERROR'

# 5. the app, on the new engine
docker compose up -d
docker compose exec backend bench --site all migrate
docker compose exec backend bench --site <site> set-maintenance-mode off
```

**Step 2's flags are the important ones.** `docker compose stop` gives a
container ten seconds before SIGKILL, and a 10.6 that is killed leaves redo log
to replay -- which 11.4 will not do across the redo-log format change ("Upgrade
after a crash is not supported", per MariaDB's upgrade notes; not reproduced
here). If that happens, remove the `DB_IMAGE` line from `.env`, let 10.6 start and recover,
and do step 2 again. `-t 600` and the slow shutdown leave nothing to replay.

**Step 4's log is supposed to have errors in it.** The entrypoint starts the
new server on the old system tables to back them up before upgrading them, and
in that window it logs `[ERROR] Incorrect definition of table
mysql.column_stats` several times. What matters is what follows: `Backing up
system database`, `Starting mariadb-upgrade`, `Finished mariadb-upgrade`, then
`ready for connections`, with no `ERROR` after it. The system-schema backup
lands in the data directory as `system_mysql_backup_*.sql.zst`.

Leave `db.env` in place afterwards. It does nothing on a start where the
version has not changed, and the next 11.4 patch bump then upgrades the system
tables by itself.

#### Verifying

```bash
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -N -e "SELECT VERSION()"'   # 11.4.13-MariaDB
docker compose exec -T db cat /var/lib/mysql/mariadb_upgrade_info                                           # 11.4.13-MariaDB
# the same three counts as before step 2
docker compose exec backend bench --site <site> doctor
docker compose exec backend bench --site all backup                     # a dump from the new engine
curl -fsS -H "Host: <site>" http://127.0.0.1:${HTTP_PORT:-8080}/api/method/ping
docker compose ps                                                      # everything (healthy)
```

Then log in as a rep and open a deal, a lead list and the dashboard.

#### Rolling back

**Before reopening** (steps 4–5 failed, or verification did not match): put
back the cold copy from step 3. Nothing has been written since.

```bash
docker compose stop -t 600 db
# remove the DB_IMAGE line from .env, then:
rm db.env
docker run --rm -v vectora_db-data:/to -v vectora_db-data-pre-11-4:/from:ro \
  mariadb:10.6.28@sha256:c7d726a1c0d29e486a1ab4ef0c76c75431a11428e76c50e99ba32106cea04114 \
  sh -c 'rm -rf /to/* /to/.[!.]* 2>/dev/null; cp -a /from/. /to/'
docker compose up -d
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -N -e "SELECT VERSION()"'   # 10.6.28
```

**After reopening** the cold copy would lose everything written since, so the
way back is a dump taken from 11.4 and restored onto an empty 10.6 -- a logical
restore, which 10.6 can read because every table is still on
`utf8mb4_unicode_ci`:

```bash
# 1. close the site and stop everything that writes -- window step 1 again --
#    so the dump below is the last write, not a snapshot of a moving target
docker compose exec backend bench --site <site> set-maintenance-mode on
docker compose stop scheduler queue-short queue-long backup
docker compose exec backend bench --site all backup        # from 11.4
docker compose stop frontend websocket backend
docker compose stop -t 600 db

# 2. set the 11.4 data directory ASIDE, not away: docker cannot rename a
#    volume, so copy it (same disk check as "Before the window", item 4, and
#    the same refusal if the target already exists), then empty the original
docker volume inspect vectora_db-data-11-4-failed >/dev/null 2>&1 \
  && echo "vectora_db-data-11-4-failed exists -- stop" \
  || docker run --rm -v vectora_db-data:/from:ro -v vectora_db-data-11-4-failed:/to \
       mariadb:11.4.13@sha256:5e73baf8179b29f115101bb102763a47a017361f3e9792daccba6646c3ab1532 \
       cp -a /from/. /to/
docker run --rm -v vectora_db-data:/d \
  mariadb:10.6.28@sha256:c7d726a1c0d29e486a1ab4ef0c76c75431a11428e76c50e99ba32106cea04114 \
  sh -c 'rm -rf /d/* /d/.[!.]* 2>/dev/null; ls -A /d | wc -l'   # 0

# 3. a new, empty 10.6 on the emptied volume
# remove the DB_IMAGE line from .env, then:
rm db.env
docker compose up -d db

# 4. the restore from "Rolling back" further down this file (under "Upgrading"),
#    with that dump -- in a one-off container, because `up` would start
#    create-site against a database that is not there yet. The guard and both
#    root flags are explained there.
: "${DB_ROOT_PASSWORD:?set it from .env before restoring}"
docker compose run --rm --no-deps -T backend bench --site <site> restore --force \
  --db-root-username root --db-root-password "$DB_ROOT_PASSWORD" \
  /home/frappe/frappe-bench/sites/<site>/private/backups/<that dump>.sql.gz

# 5. verify as in "Verifying" (10.6.28 this time, the same counts), then reopen
docker compose up -d
docker compose exec backend bench --site <site> set-maintenance-mode off
```

Only once the restored 10.6 has verified, and taken a nightly backup of its
own, remove the set-aside copy: `docker volume rm vectora_db-data-11-4-failed`.
Until then it is the only copy of the 11.4 data directory, and the way back if
the restore turns out to be missing something.

Keep `vectora_db-data-pre-11-4` until the new engine has run through a week
of nightly backups, then `docker volume rm vectora_db-data-pre-11-4`.

#### Afterwards

In a pull request: make the 11.4 digest the default in `docker-compose.yml`
(it resolves to what `.env` already says, so it recreates nothing), drop the
10.6 legs from `server-tests.yml` and `migration-test.yml`, and record the date
here.

### Sizing the database

`db` runs with a 384 MB InnoDB buffer pool inside a 1 GB container. Both are
settings in `.env`:

| Key | Default | What it is |
|---|---|---|
| `DB_INNODB_BUFFER_POOL_SIZE` | `384M` | Memory InnoDB may use to cache table and index pages |
| `DB_MEMORY_LIMIT` | `1g` | The container's ceiling; the kernel kills MariaDB if it gets there |

Up to v3.30.0 the pool was InnoDB's stock 128 MB, with most of the container's
gigabyte unused: every read past the hottest 128 MB of pages went to disk. The
default is conservative on purpose. The pool is not all MariaDB allocates —
each connection brings sort and join buffers and in-memory temporary tables,
and the table cache grows with frappe's several hundred tables — and a
database that is OOM-killed mid-write is a far worse outcome than one that
reads from disk. **Keep the pool at or below about half of the limit**, and
raise the two together.

Measure before raising either:

```bash
# how big the data is -- the most a pool could usefully hold
docker compose exec backend bench --site <site> mariadb -e "
  SELECT ROUND(SUM(data_length + index_length) / 1048576) AS data_mb
  FROM information_schema.tables WHERE table_schema = DATABASE();"

# how often a read misses the pool: reads / read_requests, since the last start
docker compose exec backend bench --site <site> mariadb -e "
  SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';"

# what the container is actually using against its limit
docker stats --no-stream $(docker compose ps -q db)
```

If the data is smaller than the pool, there is nothing to gain. If
`Innodb_buffer_pool_reads` is more than a percent or so of
`Innodb_buffer_pool_read_requests` after a normal working day, the working set
does not fit: on a host with memory to spare set, for example,
`DB_MEMORY_LIMIT=2g` and `DB_INNODB_BUFFER_POOL_SIZE=1G`.

Changing either value recreates the `db` container on the next `docker compose
up -d` — a cold restart of the database, so do it in a maintenance window, with
a backup in front of it. Nothing on disk changes, and going back is the same
edit reversed. (The pool is also a dynamic variable — `SET GLOBAL
innodb_buffer_pool_size = ...` as the MariaDB root user resizes it on a running
server — but that does not survive a restart and does not move the container's
limit, so it is for trying a value, not for keeping one.)

**`redis-cache` is not bounded, and that is deliberate for now.** It has a
256 MB container limit and no `maxmemory` of its own, so in principle it can
grow until the kernel kills it rather than evict. The obvious fix — a ceiling
with `allkeys-lru` and no snapshots, which is what bench configures for its
own cache — is unsafe on this stack, because this redis does not hold only
cache. The Acumatica in-flight markers live there for thirty days and are the
one thing that stops a retried quote being written to the ERP twice; the
event-reminder ledger is there as well. Evicting a marker, or losing it on a
restart, is a duplicate sales order in a customer's live system. Bounding the
cache therefore waits on moving those keys somewhere durable; until then,
watch it instead:

```bash
docker stats --no-stream $(docker compose ps -q redis-cache)     # against the 256MiB limit
```

`redis-queue` is left alone for the same kind of reason: no ceiling and no
eviction, because a key evicted there is a queued job that never runs.

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

**After restarting `backend` or `websocket` alone, check that `frontend`
followed.** nginx in the `frontend` service resolves both addresses only when it
loads its config, so either one coming back on a new container IP leaves every
request (or every socket.io connection) 502ing until nginx reloads.
`frontend` runs `nginx/upstream-watch.sh` beside nginx for exactly this: it looks
both names up every 5 seconds and reloads nginx, gracefully, once they have moved
and both resolve. Expect up to that long of 502s, and none of it while either
container is still down -- nginx refuses a config naming an upstream that does
not resolve. A reload shows in the logs, and a dead watcher turns the
healthcheck red:

```bash
docker compose logs frontend | grep upstream-watch
```

If 502s outlast the container coming back (or on a stack without the watcher),
reload by hand -- no connection is dropped:

```bash
docker compose exec frontend nginx -s reload
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
over them. The only reliable path back is the backup from step 0 — after the
check below.

**Open ERP writes do not survive a rollback.** From the release that added the
ERP write ledger, an Acumatica Customer or SalesOrder write whose answer never
came is recorded only as an open row in **CRM ERP Write** — the previous release
cannot read it, and restoring a pre-upgrade backup drops it. Before rolling back
(or restoring), look for open rows and settle each one in Acumatica by hand —
link the customer or record the quote the write may have made — or the old code
may send it a second time:

```bash
docker compose exec backend bench --site <site> mariadb -e \
  "select target, state, started_at, remote_id, error from \`tabCRM ERP Write\`
   where state in ('In Flight','Unknown')"
```

Then:

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

Which means the [restore drill](#restore-drill) is not a nice-to-have:
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
disclosure. That is why the off-host copy leaves this one file behind — see
[Getting them off the host](#getting-them-off-the-host) — and why the key has
to be kept somewhere else as well.

### Restoring onto a new host

The restore above runs on the host that took the backup, where
`site_config.json` is still in the `sites` volume. Losing the host is a
different restore, and it needs one thing a dump does not contain: **the
site's `encryption_key`.**

Frappe encrypts every Password field with it — the Acumatica credentials,
WhatsApp tokens and App Secrets, mail account passwords. They are in the dump,
encrypted. A site created fresh gets a fresh key, so a dump restored into it
restores every one of those values as ciphertext nothing can read: the site
comes up, users log in (login passwords are hashed, not encrypted), and each
integration then fails at its first call with a decryption error.

**Do this once, today, while the host is healthy:** put the key in whatever
holds your other operational secrets — a password manager, not the bucket the
backups go to.

```bash
docker compose exec -T backend cat sites/${SITE_NAME}/site_config.json | grep encryption_key
```

It does not change for the life of the site, so once is enough. (If it is ever
missing from that file, frappe generates one the first time it encrypts
something; check again after the first integration is configured.)

Then the new-host restore is:

```bash
# 1. a fresh stack: .env with the same SITE_NAME, then first boot as usual
docker compose up -d
docker compose logs -f create-site

# 2. the backup, from wherever it was kept, into the sites volume
docker compose cp ./<stamp>-database.sql.gz      backend:/home/frappe/frappe-bench/sites/<site>/private/backups/
docker compose cp ./<stamp>-files.tar            backend:/home/frappe/frappe-bench/sites/<site>/private/backups/
docker compose cp ./<stamp>-private-files.tar    backend:/home/frappe/frappe-bench/sites/<site>/private/backups/

# 3. the old key, BEFORE the restore, so nothing is ever read with the new one
docker compose exec backend bench --site <site> set-config encryption_key '<the key you kept>'

# 4. restore exactly as in "Rolling back" above, then migrate
: "${DB_ROOT_PASSWORD:?set it in .env before restoring}"
docker compose exec -T backend bench --site <site> restore --force \
  --db-root-username root --db-root-password "$DB_ROOT_PASSWORD" \
  /home/frappe/frappe-bench/sites/<site>/private/backups/<stamp>-database.sql.gz \
  --with-public-files /home/frappe/frappe-bench/sites/<site>/private/backups/<stamp>-files.tar \
  --with-private-files /home/frappe/frappe-bench/sites/<site>/private/backups/<stamp>-private-files.tar
docker compose exec backend bench --site all migrate
docker compose restart backend queue-short queue-long scheduler websocket
```

Do **not** carry `db_name` or `db_password` over from the old config: those
belong to the database the new stack just created, and the new
`site_config.json` already has the right ones. `encryption_key` is the only
value that must come from the old host. Everything else the old
`site_config.json` held — `host_name`, the keys in [site_config
keys](#site_config-keys) — is configuration to re-apply by hand, as the restore
notes above say.

Check it worked the way a user would find out it had not: open **CRM Agent
Settings**, or an Email Account, and save it; or run one ERP sync. A wrong key
fails there, immediately, with a decryption error.

If `migrate` fails partway, do not roll the image back and carry on — the site
is between schemas. Read the error (`docker compose logs backend`, and frappe's
Error Log), fix forward if the cause is obvious, and restore if it is not.

## Backups

A `backup` service takes one every night and prunes to a week. You do not have
to remember anything for the routine case.

```bash
docker compose logs backup | tail            # when the last one ran
docker compose exec backend ls -lh sites/$SITE_NAME/private/backups
```

`BACKUP_HOUR` (default `2`) is the hour it runs, container local time.

### Knowing when a backup did not happen

The loop can only log a failure and sleep until the next night, and nobody
reads that log. So the `backup` container carries a healthcheck: it is
`healthy` while the newest `*-database*.sql.gz` in the backups directory is
younger than `BACKUP_MAX_AGE_HOURS` (default `26` — one nightly run plus slack;
whole hours only, anything else is ignored in favour of 26 with a line in the
`backup` log) and `unhealthy` once it is not. A night that failed — a full volume, a database
that was down at 02:00 — shows up about two hours later:

```bash
docker compose ps backup                     # healthy / unhealthy / starting
docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q backup)"
```

`starting` is the honest answer on a site that has not had its first night
yet: there is no backup to be late. It lasts until the first dump exists, or
26 hours, whichever comes first; a site with a recent backup goes `healthy`
within a minute of the container starting.

**A healthcheck is a state, not an alert.** Docker records it and restarts
nothing — restarting would not help — so an unhealthy `backup` is visible only
to something that looks. Two ways to have something look, and a production
host wants the first:

#### Being told when a backup did not happen

A dead-man's switch: the service reports each run to a monitor *outside this
host*, and the monitor alerts when a report it expected does not arrive. That
catches what no check on the host can — the whole host being down, docker
stopped, the container deleted — because silence is the signal.

Both backup services speak the [healthchecks.io](https://healthchecks.io)
protocol when given a check URL:

| `.env` key | Pinged by | Suggested check |
|---|---|---|
| `BACKUP_PING_URL` | `backup`, once a night | period 1 day, grace 3 hours |
| `OFFSITE_PING_URL` | `backup-offsite`, every hour | period 1 hour, grace 2 hours |

Each run sends `GET <url>/start` when it begins, then a success ping when it
worked or `GET <url>/fail` when it did not, so the monitor alerts on a failure
straight away and on a missing run after the grace period, and shows how long
each run took. For the off-host copy, "worked" means the copy, the monthly
copy and any pruning all succeeded.

The success ping is `GET <url>` from `backup`, and `GET <url>/0` from
`backup-offsite` — the exit-status form of the same protocol, which
healthchecks.io (hosted or self-hosted) reads as success. The reason is the
secret below: the rclone image has no curl, busybox wget takes a URL only on
its command line (where `ps` on the host would show it), so the offsite
service pings through rclone's own HTTP client with the URL in its
environment — and that client can only fetch a path *below* the URL.

1. Create two checks (healthchecks.io → Add Check, one per row above), set
   their period and grace, and connect the alert channels you actually read
   (email, Slack, SMS, PagerDuty…).
2. Put their ping URLs in `.env`:
   ```bash
   BACKUP_PING_URL=https://hc-ping.com/<uuid-of-the-nightly-check>
   OFFSITE_PING_URL=https://hc-ping.com/<uuid-of-the-hourly-check>
   ```
3. Recreate both services so they read them:
   ```bash
   docker compose up -d backup
   docker compose --profile offsite up -d backup-offsite
   ```
4. Check the first pings arrived: the offsite check turns green within a few
   minutes; the nightly one after the next `BACKUP_HOUR` (or force a run in
   the monitor's UI with "Ping now" to see the channel work).

**The URL must be healthchecks.io-shaped**: `https://host/path` with nothing
after the path, so that `/start`, `/fail` and `/0` can be appended. A URL with
a query string or fragment (`...?status=up`, `...#x`) is refused at start with
a log line saying so, and that service sends no pings: appending a path to it
would ping the wrong endpoint.

Guarantees, so the monitor can never cost you a backup: pings run only when
the variable is set and starts with `http://` or `https://`; each is bounded
at 15 seconds; a ping that fails is logged as `did not get through (ignored)`
and the run carries on. **The URL's path is the secret** — anyone who has it
can mark a run as passed — so the services log it only up to the host
(`https://hc-ping.com/...`), and neither service ever puts it on a command
line: `backup` hands it to curl on stdin, `backup-offsite` to rclone in its
environment. Keep it as you keep the rest of `.env`.

**Self-hosted alternative.** healthchecks.io is open source
([healthchecks/healthchecks](https://github.com/healthchecks/healthchecks));
run it on a machine *other than this one* (a monitor on the host it watches
goes down with it) and use its ping URLs instead. Another monitor works if it
alerts when an expected HTTP GET stops arriving *and* accepts the `/start`,
`/fail` and (for the offsite check) `/0` paths on a URL without a query
string. Uptime Kuma's "Push" monitors, for instance, take their status in a
query string and are refused for both services.

#### Or: a cron line on the host

With nothing else to hand, a cron line on the host that mails when either backup
container is not healthy is better than nothing — but it shares the host's
fate, and it is the only place the unencrypted-copies warning below surfaces:

```bash
# /etc/cron.d/vectora-backup-health  (needs a working local `mail`)
0 8 * * * root cd /path/to/deploy && for s in backup backup-offsite; do id=$(docker compose ps -q $s 2>/dev/null); [ -n "$id" ] || continue; st=$(docker inspect --format '{{.State.Health.Status}}' "$id"); [ "$st" = healthy ] || echo "$s is $st: $(docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' "$id" | tail -n 3)" | mail -s "Vectora backup: $s $st" ops@example.com; done
```

### Getting them off the host

A backup that only exists on the machine it protects survives a bad delete,
not a lost server — and losing the server is the case a customer actually
fears. The `backup-offsite` service copies the dumps to Backblaze B2 every
hour. It is behind a compose profile, so it starts only when you ask:

```bash
docker compose --profile offsite up -d backup-offsite
docker compose logs -f backup-offsite        # first copy, then hourly
```

**For a new install, in this order:** create the bucket with Object Lock and
lifecycle rules and a key that cannot delete ([Immutable copies, and how long
they are kept](#immutable-copies-and-how-long-they-are-kept)); generate the
encryption passphrase and put it where it will outlive this host
([Encrypting the copies](#encrypting-the-copies)); set the ping URL
([above](#being-told-when-a-backup-did-not-happen)); then start the service.

The `.env` keys, all documented in `.env.example`:

| Key | What it is |
|---|---|
| `B2_ACCOUNT_ID` | Required. The application key's **keyID** |
| `B2_APPLICATION_KEY` | Required. The application key itself, shown once at creation |
| `BACKUP_TARGET` | The bucket as an rclone destination, e.g. `offsite:vecmbp` |
| `OFFSITE_CRYPT_PASSWORD`, `OFFSITE_CRYPT_SALT` | Encrypt the copies before they leave the host. Set them — [below](#encrypting-the-copies) |
| `OFFSITE_ALLOW_PLAINTEXT` | Default `0`. `1` accepts unencrypted copies without the healthcheck reporting it |
| `OFFSITE_INCLUDE_SITE_CONFIG` | Default `0`. Also copy `site_config_backup.json`; honoured only when the copies are encrypted |
| `OFFSITE_RETENTION_DAYS` | Default `0` (never delete — no delete is ever attempted). Prefer lifecycle rules — [below](#immutable-copies-and-how-long-they-are-kept) |
| `OFFSITE_MAX_AGE_HOURS` | Default `28`. How stale the newest copy may be before the container is unhealthy |
| `OFFSITE_PING_URL` | Optional dead-man's switch — [above](#being-told-when-a-backup-did-not-happen) |

What lands where, with `BACKUP_TARGET=offsite:<bucket>` (a path after the
bucket name is kept in front of all four):

| Prefix in the bucket | What |
|---|---|
| `<site>/` | dailies, unencrypted (no passphrase set) |
| `<site>.crypt/` | dailies, encrypted |
| `monthly/<site>/` | the first backup of each month, unencrypted — only with `OFFSITE_ALLOW_PLAINTEXT=1` |
| `monthly/<site>.crypt/` | the first backup of each month, encrypted |

No prefix is a prefix of another, so each takes its own lifecycle rule, and
encrypted and unencrypted copies are never mixed in one listing.

It copies rather than syncs, deliberately: `rclone copy` never deletes at the
destination, so the seven-day local retention does not propagate to the
archive, and a copy that failed at 02:00 is retried at 03:00 rather than a day
later. Re-copying costs nothing — rclone skips what is already there. Files
modified in the last 15 minutes wait for the next run, so a dump that is still
being written is never uploaded half-finished (on a locked bucket it would
stay there, locked, for the whole retention period).

**The monthly tier** (encrypted copies only, or plaintext that
`OFFSITE_ALLOW_PLAINTEXT=1` accepted — an upgraded stack without a passphrase
does not start keeping a year of plaintext dumps). After each successful
hourly copy, the service copies this month's first backup set to `monthly/` —
one set a month, whatever restarts in between, because it asks the destination
rather than remembering: if `monthly/` already has a dump for the month, it is
*that* set that gets copied again (rclone uploads only what is missing, so a
copy that died between the dump and the tars is completed), and the month
counts as done only once a copy has exited cleanly. "First" is the earliest
set of the month still on the host (the host keeps a week, so after an outage
spanning the 1st it is the first night it can see); a set is only taken once
nothing in it has changed for an hour. Lifecycle rules then keep `monthly/`
longer than the dailies. `OFFSITE_RETENTION_DAYS`, if set, never touches it.

Check it is still working, rather than assuming:

```bash
docker compose ps backup-offsite             # healthy == key works, a recent dump is there, copies are encrypted
docker compose exec backup-offsite cat /tmp/offsite.status
docker compose exec backup-offsite sh -c 'rclone ls "$(cat /tmp/offsite.dest)"' | tail
docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' "$(docker compose ps -q backup-offsite)"
```

The healthcheck asks three things every five minutes, and prints each one
that fails (the last command above shows it). Can the key still open the
bucket — so an expired or revoked key shows up as unhealthy instead of as an
archive that quietly stopped weeks ago. Is the newest database dump *at the
destination* younger than `OFFSITE_MAX_AGE_HOURS` (default `28`: the backup's
own 26 plus time to upload). And are the copies encrypted — unless
`OFFSITE_ALLOW_PLAINTEXT=1` says plaintext is a decision. The status file says
the same in `key=value` form: `encryption=on|off`, `prune=off|script|delegated|failed`,
`monthly=<YYYYMM done>`, `last_result`, `last_ok`.

**After changing any of these settings, or upgrading**, recreate the service by
name — it is behind a profile, so a plain `docker compose up -d` does not touch
it:

```bash
docker compose --profile offsite up -d backup-offsite
```

#### What is not copied

`*-site_config_backup.json`, unless the copies are encrypted and
`OFFSITE_INCLUDE_SITE_CONFIG=1`. Frappe writes one beside every dump and it is
`site_config.json` verbatim: `db_password` and `encryption_key`, in plaintext.
The dump next to it holds every stored integration secret, encrypted with that
key. Together in a third party's bucket they are the whole CRM — every
customer record and every ERP, WhatsApp and mail credential — to anyone who
can read the bucket, and an application key scoped to write does not make the
bucket unreadable to a Backblaze account compromise.

So the copy leaves that file on the host, which means **the encryption key has
to be kept somewhere else** for a restore onto a new host to be complete —
[Restoring onto a new host](#restoring-onto-a-new-host) is the procedure, and
it is one line to do today. With encryption on, `OFFSITE_INCLUDE_SITE_CONFIG=1`
puts it in the archive instead, as ciphertext.

Until PR #402 the file *was* copied, so a bucket that has been in use holds one
per night already, and `rclone copy` never deletes. [Cleaning up the plaintext
secrets already in the
bucket](#cleaning-up-the-plaintext-secrets-already-in-the-bucket) is the
runbook.

#### Encrypting the copies

Set a passphrase in `.env` and every copy goes through an rclone
[`crypt`](https://rclone.org/crypt/) remote, so the bucket only ever receives
ciphertext. `.env.example` has the two keys uncommented and empty: a new
install is expected to fill them before its first copy.

```bash
OFFSITE_CRYPT_PASSWORD=<openssl rand -base64 32>
OFFSITE_CRYPT_SALT=<openssl rand -base64 32>       # rclone's password2; optional, recommended
docker compose --profile offsite up -d backup-offsite
```

**The passphrase is the archive.** There is no recovery if it is lost, and the
archive exists for the day this host — and its `.env` — are gone. Before the
first encrypted copy:

1. Store both values in the team's password manager, in an entry named for the
   deployment and the bucket, next to the site's `encryption_key`.
2. Write both on paper, seal it in an envelope signed across the flap, and give
   it to a second person who does not keep it near this host — so one person
   leaving, or one locked-out password manager, does not end the archive.
3. Then turn it on, and prove it reads back (below).

Changing the passphrase or the salt later makes everything already encrypted
unreadable under the new values, and the canary (below) stops the service
rather than let that happen in the same prefix. To rotate, point the copies at
a new prefix as well (a new `BACKUP_TARGET` path), set the new values, let the
new copies land, and keep the old values until the old copies have aged out.

**It is not protected on this host, and is not meant to be.** It sits in `.env`
in the clear, shows in `docker inspect` of the container like every other
variable there, and the copy the service writes into rclone's config is only
*obscured* — rclone's word for a reversible encoding that stops a glance, not
a reader. Encryption here protects the bucket from whoever can read the
bucket. Anyone who can read this host's `.env` already has the database.

- File *contents* are encrypted; file *names* are not (they gain a `.bin`
  suffix), so the bucket's console still shows which nights are present.
- With a passphrase set, `OFFSITE_INCLUDE_SITE_CONFIG=1` also copies
  `site_config_backup.json`, which makes the archive self-contained. Without
  one that setting is ignored, and the log says so.
- **The canary.** Each encrypted prefix holds a small `.vectora-canary`,
  written under its passphrase the first time. On every start the service
  decrypts it; if the passphrase or salt in `.env` is not the one that wrote
  the prefix — a typo, a rotation done in place — it logs `... differs from
  the one that wrote this prefix` and `NOT COPYING`, pings `/fail`, waits
  `OFFSITE_START_RETRY_SECONDS` (default 900) and exits to be restarted,
  rather than putting a second key's files into the same archive where only
  a restore would find them. A prefix that already holds encrypted files but
  no canary must decrypt its first file before the canary is added. If the
  bucket cannot be listed or read at that moment, the log says `NOT COPYING
  YET ... a network or key problem, not the passphrase` and it retries on
  the same schedule — an outage is not reported as a wrong passphrase.
  Existence is checked by listing, never by reading: on B2, reading a file
  that is not there succeeds with no output. Pruning never deletes it.

**Without a passphrase**, nothing breaks: an install that predates this keeps
copying, unencrypted, to the same `<site>/` prefix as before. But it is never
quiet about it. Every hourly run logs

```
[offsite] WARNING: copies leave this host UNENCRYPTED. ...
```

and the healthcheck reports `copies are NOT encrypted`, so the container goes
`unhealthy` about an hour after it starts and whatever watches container
health sees it. Set the passphrase, or — only for a destination you control end
to end — `OFFSITE_ALLOW_PLAINTEXT=1`, which keeps the log line and clears the
healthcheck.

**Switching an existing install to encrypted copies:**

1. Generate and store the passphrase and salt as above.
2. Add them to `.env` and recreate: `docker compose --profile offsite up -d backup-offsite`.
3. The log now says `-> offsite:<bucket>/<site>.crypt, encrypted`. The first
   run uploads the week of backups on the host, encrypted, under
   `<site>.crypt/`; the month's first set goes to `monthly/<site>.crypt/`.
   The plaintext `<site>/` is not touched or re-encrypted — the two
   archives never mix.
4. Read one back (below) and compare it with the original.
5. When `<site>.crypt/` holds as many nights as you want to be able to go
   back, the plaintext prefix is the exposure that is left: let its
   lifecycle rule age it out, or delete it with your own key (Object Lock
   retention permitting). Until then they are as readable as they ever were.

Reading an encrypted archive back, on any machine with rclone and the two
secrets — or let [the restore drill](#restore-drill) do it:

```bash
export RCLONE_CONFIG_OFFSITE_TYPE=b2 RCLONE_CONFIG_OFFSITE_ACCOUNT=<keyID> RCLONE_CONFIG_OFFSITE_KEY=<key>
export RCLONE_CONFIG_ARCHIVE_TYPE=crypt
export RCLONE_CONFIG_ARCHIVE_REMOTE=offsite:<bucket>/<site>.crypt     # or <bucket>/monthly/<site>.crypt
export RCLONE_CONFIG_ARCHIVE_FILENAME_ENCRYPTION=off
export RCLONE_CONFIG_ARCHIVE_DIRECTORY_NAME_ENCRYPTION=false
export RCLONE_CONFIG_ARCHIVE_PASSWORD=$(rclone obscure -)     # type the passphrase, then Ctrl-D
# and RCLONE_CONFIG_ARCHIVE_PASSWORD2 the same way, if a salt was set
rclone ls archive:
rclone copy archive: ./restore --include "<stamp>-*"
```

An encrypted backup nobody has ever decrypted is the same kind of object as a
backup nobody has ever restored.

#### Immutable copies, and how long they are kept

The off-host copy is worth having because it survives whatever happens to this
host — including someone who takes it over and wants the backups gone too. So
the key this host holds should be able to **add** to the archive and nothing
else, and the bucket itself should refuse deletes for a while after each
upload. Retention is then the bucket's job, not this service's:

- **Object Lock** with a default retention: every uploaded file version is
  immutable for `LOCK_DAYS`. Not even a key with `deleteFiles` can remove it in
  that time.
- **Lifecycle rules** per prefix: dailies hidden after `DAILY_DAYS`, monthlies
  after `MONTHLY_DAYS`, hidden versions deleted a day later.
- **An application key without `deleteFiles`**: `listBuckets`, `listFiles`,
  `readFiles`, `writeFiles`, restricted to the one bucket.

The numbers are yours; these are the ones the rest of this section uses:

```bash
BUCKET=vectora-backups-<company>     # bucket names are global on B2
SITE=<your SITE_NAME>
LOCK_DAYS=30         # immutability window for every upload
DAILY_DAYS=30        # keep dailies this long; >= LOCK_DAYS
MONTHLY_DAYS=365     # keep monthlies this long
```

Keep `DAILY_DAYS` at or above `LOCK_DAYS`: a lifecycle rule cannot delete a
version that is still locked, so a shorter rule only leaves hidden-but-billed
versions until the lock ends. Monthlies are locked for `LOCK_DAYS` like
everything else (the default retention is per bucket); after that they are
protected by this host's key not being able to delete. If monthlies must be
locked for their whole life, give them a second bucket with
`LOCK_DAYS=MONTHLY_DAYS` — and know that compliance-mode locking for a year
is a year of storage nobody can remove.

**Governance or compliance.** In *governance* mode a key with the
`bypassGovernance` capability can still shorten or remove a lock — the escape
hatch for a mistake. That includes the master key and, through the web
console, **anyone who can log in to the Backblaze account**. So governance
mode protects against this host being taken over, not against the account
being taken over. In *compliance* mode nobody can shorten a lock, Backblaze
included, until the retention ends.

- Whatever the mode: turn on two-factor authentication for the Backblaze
  account (in its sign-in settings), keep the master
  application key offline, and give no one else the account login.
- Governance is the sensible default when the threat you are guarding against
  is this server: a compromised host holds a key that cannot delete, and the
  account stays out of reach behind 2FA.
- Choose **compliance** when account takeover is in scope — a phished or
  shared login, an insider with console access — or when a regulator sets the
  rule. The price is real: nothing locked can be removed early, by you either,
  so start with a short `LOCK_DAYS` and lengthen it once the bill is known.

With the [b2 command-line tool](https://www.backblaze.com/docs/cloud-storage-command-line-tools)
(v4 syntax, written from its documentation and not run against an account
here — check `b2 bucket update --help` on the version you have),
authorised with the master key **on your own machine, not this host**:

```bash
b2 account authorize        # master keyID + key, interactively

# 1. the bucket, with Object Lock. (An existing bucket can have Object Lock
#    switched on from its settings in the console; it can never be switched off.)
b2 bucket create --file-lock-enabled --default-server-side-encryption SSE-B2 "$BUCKET" allPrivate

# 2. default retention for every new upload. The period is "<n> days" or
#    "<n> years", space and all: the v4 parser rejects "30d".
b2 bucket update --default-retention-mode governance \
  --default-retention-period "${LOCK_DAYS} days" "$BUCKET" allPrivate

# 2a. and check it took, before anything relies on it: this must print mode
#     "governance" (or "compliance") and a period of LOCK_DAYS days. An empty
#     or null defaultRetention means uploads are NOT locked -- stop and fix it.
b2 bucket get "$BUCKET" | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin).get("fileLockConfiguration"), indent=2))'

# 3. lifecycle: one rule per prefix (encrypted and plaintext, daily and monthly)
b2 bucket update "$BUCKET" allPrivate \
  --lifecycle-rule "{\"fileNamePrefix\": \"$SITE/\", \"daysFromUploadingToHiding\": $DAILY_DAYS, \"daysFromHidingToDeleting\": 1}" \
  --lifecycle-rule "{\"fileNamePrefix\": \"$SITE.crypt/\", \"daysFromUploadingToHiding\": $DAILY_DAYS, \"daysFromHidingToDeleting\": 1}" \
  --lifecycle-rule "{\"fileNamePrefix\": \"monthly/\", \"daysFromUploadingToHiding\": $MONTHLY_DAYS, \"daysFromHidingToDeleting\": 1}"

# 4. the key this host gets: write and read, never delete, this bucket only
b2 key create --bucket "$BUCKET" "vectora-$SITE-offsite" listBuckets,listFiles,readFiles,writeFiles
#    -> put its keyID in B2_ACCOUNT_ID and the key in B2_APPLICATION_KEY, then
#       BACKUP_TARGET=offsite:$BUCKET, and recreate backup-offsite

# 5. check all of it: fileLockConfiguration (as in 2a), the three
#    lifecycleRules, and the key's capabilities (no deleteFiles)
b2 bucket get "$BUCKET"
b2 key list --long | grep "vectora-$SITE-offsite"
```

The same in the web console: **Buckets → Create a Bucket**, Private, Default
Encryption *Enable*, Object Lock *Enable*; then on the bucket, **Object Lock →
Default Retention Policy** *Governance*, `LOCK_DAYS` days; **Lifecycle
Settings → Use custom lifecycle rules**, one row per prefix above with "Days
till hide" and "Days till delete" = `1`; **Application Keys → Add a New
Application Key**, *Allow access to bucket* = this bucket, *Type of access* =
**Read and Write**, then — because the console's Read and Write includes
`deleteFiles` — create it with the CLI (step 4) instead if you can. A key
whose capabilities include `deleteFiles` defeats the point of everything else
here.

Prefixes in the rules are relative to the bucket: if `BACKUP_TARGET` carries a
path (`offsite:<bucket>/vectora`), put it in front of each (`vectora/$SITE/`,
`vectora/monthly/`).

**What the service does with that key.** With `OFFSITE_RETENTION_DAYS` unset
(the default), it never issues a delete of any kind. If it *is* set and the
store refuses the delete — no `deleteFiles`, or a locked version — the service
logs once that pruning is **delegated to the bucket's lifecycle rules**, sets
`prune=delegated` in its status file, and stops trying; that is a supported
state, not a failure. Any other prune error is a failure, logged as
`PRUNE FAILED`, shown by the healthcheck and pinged to `/fail`.

One B2 subtlety: rclone's delete on B2 *hides* a file rather than removing
it, and hiding needs only `writeFiles`. So against a write-only B2 key a
prune may "succeed" by hiding old dailies; the versions themselves stay (and
under Object Lock cannot be removed until their retention ends), and the
lifecycle rule's "days till delete" removes them. Nothing is lost that the
lifecycle rules would have kept — but it is one more reason to leave
`OFFSITE_RETENTION_DAYS` unset and let the bucket decide.

`OFFSITE_RETENTION_DAYS` remains for stores without lifecycle rules. It
deletes dailies (never `monthly/`) last modified more than that many days ago,
and has three limits built in: values under 14 are refused (the host keeps a
week, and a shorter window would delete files only for the next hourly copy to
upload them again); it runs only straight after a copy that succeeded; and it
does not run at all unless a dump newer than `OFFSITE_MAX_AGE_HOURS` is at the
destination — an archive that has stopped receiving is the last copy there is,
and is not aged away.

#### Cleaning up the plaintext secrets already in the bucket

For a bucket that received copies before PR #402: it holds one
`*-site_config_backup.json` per night — `db_password` and `encryption_key` in
plaintext — next to unencrypted dumps of the whole CRM. Run this once, in
order, from your own machine with your own credentials. Nothing here runs from
the server, and the server's key should not be able to do step 4 anyway.

**1. Find out whether anyone read them.** Before deleting anything, because
deleting is also deleting the evidence.

- Backblaze console → **Application Keys**: every key with access to this
  bucket. Any you cannot account for: note its keyID, then delete it.
- Backblaze console → **Reports**: per-bucket daily *Class B transactions*
  (downloads) and *download bandwidth*, back to when the first copy was made.
  Downloads on days nobody you know restored anything are the warning sign.
- If server access logging or event notifications were configured on the
  bucket, read those for downloads (`b2_download_file_by_name` /
  `b2_download_file_by_id`, or S3 `GetObject`) of `*site_config_backup.json`.
  B2 keeps no per-object read log unless it was set up beforehand; the
  Reports page is then the evidence there is.
- Write down what you found and the date: it decides step 3.

**2. Rotate the site's database password — always.** It is cheap and it is in
every one of those files. In the deploy directory on the server, in a quiet
hour (the app is down for about a minute):

```bash
cd /path/to/deploy
SITE_NAME=$(sed -n 's/^SITE_NAME=//p' .env)
DB_NAME=$(docker compose exec -T backend sh -c "sed -n 's/.*\"db_name\": *\"\([^\"]*\)\".*/\1/p' sites/$SITE_NAME/site_config.json")
OLD_DB_PASSWORD=$(docker compose exec -T backend sh -c "sed -n 's/.*\"db_password\": *\"\([^\"]*\)\".*/\1/p' sites/$SITE_NAME/site_config.json")
export NEW_DB_PASSWORD=$(openssl rand -hex 24)

# a. stop everything that holds a connection
docker compose stop backend websocket queue-short queue-long scheduler backup

# b. change it in MariaDB. The SQL goes on stdin, the root password comes from
#    the db container's own environment: neither is on a command line.
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot' <<SQL
ALTER USER '$DB_NAME'@'%' IDENTIFIED BY '$NEW_DB_PASSWORD';
SQL

# c. and in the site's config (the value travels by environment)
docker compose run --rm --no-deps -T -e NEW_DB_PASSWORD --entrypoint bash backend \
  -c 'bench --site "$0" set-config db_password "$NEW_DB_PASSWORD"' "$SITE_NAME"

# d. start everything again
docker compose up -d

# e. verify: the app answers, the database answers, the old password does not
docker compose exec -T backend bench --site "$SITE_NAME" execute frappe.db.count --args "['User']"
docker compose exec -T backend curl -fsS -H "Host: $SITE_NAME" http://localhost:8000/api/method/ping
docker compose exec -T db sh -c "MYSQL_PWD='$OLD_DB_PASSWORD' mariadb -u'$DB_NAME' -e 'select 1'"   # must say: Access denied
docker compose ps                                                                                   # all healthy again
unset NEW_DB_PASSWORD OLD_DB_PASSWORD
```

The site user is `'<db_name>'@'%'` because `create-site` makes it with
`--mariadb-user-host-login-scope='%'`; `SELECT user, host FROM mysql.user`
confirms it. The new password lives only in `site_config.json` on the `sites`
volume — `.env` never held it.

The database **root** password (`DB_ROOT_PASSWORD` in `.env`) is not in
`site_config_backup.json`, so it was not exposed by these files. To rotate it
anyway, change it in MariaDB first, then in `.env`, then let compose recreate
`db` and `create-site` (the variable is in their environment — a cold restart
of the database):

```bash
export NEW_ROOT=$(openssl rand -hex 24)
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot' <<SQL
ALTER USER IF EXISTS 'root'@'%' IDENTIFIED BY '$NEW_ROOT';
ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY '$NEW_ROOT';
SQL
cp .env .env.bak-root && sed -i "s/^DB_ROOT_PASSWORD=.*/DB_ROOT_PASSWORD=$NEW_ROOT/" .env
docker compose up -d                                   # recreates db and create-site
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -e "select 1"'
shred -u .env.bak-root; unset NEW_ROOT
```

`MYSQL_ROOT_PASSWORD` is read only when the data directory is first
initialised, which is why the `ALTER USER` comes first: changing `.env` alone
changes nothing but the next `create-site`'s view of it. Both procedures were
rehearsed on a throwaway stack.

**3. The `encryption_key` — only if step 1 found exposure, and not by changing
it.** The pinned frappe (`scripts/frappe-pin.env`, e2e1006be) has **no**
supported key-rotation command: nothing in `frappe/commands` or
`frappe/utils/password.py` re-encrypts under a new key. What the key protects
in this codebase:

- every Password field: the `__Auth` table, rows with `encrypted = 1` — mail
  account passwords, CRM Acumatica / WhatsApp / telephony credentials, user
  API secrets, OAuth client secrets;
- two-factor OTP secrets (`tabDefaultValue`, `<user>_otpsecret`);
- the HMAC secret for signed URLs (`frappe.utils.verified_command`) — e.g.
  unsubscribe links — unless `site_config.json` sets a separate `secret`;
- frappe's own backup encryption key, which a v14 patch seeded from it (used
  only if *System Settings → Encrypt Backups* is on; it is off here).

Changing `encryption_key` in `site_config.json` re-encrypts **none** of that:
every stored secret fails with "Encryption key is invalid", every 2FA user is
locked out, every link already sent stops verifying. Do not do it, and do not
script a re-encryption the framework does not provide.

What does work, and is the actual fix: **make what the key decrypts worthless.**
Change each secret at its source — a new Acumatica password, new WhatsApp and
telephony tokens, new mail-account app passwords, regenerated API keys, users
re-enrolling 2FA — and enter the new values in the CRM. They are encrypted with
the same key, but the copies of the old ciphertext in the bucket now decrypt
to credentials that no longer work. The key itself then protects nothing an
attacker can use. Record which secrets you changed. (If you also want signed
links to stop depending on it, set a long random `secret` in
`site_config.json`; links already in people's mailboxes stop working.)

If step 1 found nothing, the risk that remains is that someone read the files
without leaving a trace you could see; weigh that against the work above. The
database password in step 2 is rotated either way.

**4. Delete them.** With a key of your own that has `listFiles` and
`deleteFiles` on the bucket (not the server's):

```bash
export PURGE_B2_ACCOUNT_ID=<keyID> PURGE_B2_APPLICATION_KEY=<key>
scripts/purge-plaintext-site-config-backups.sh offsite:<bucket>            # dry run: lists and counts
scripts/purge-plaintext-site-config-backups.sh --delete offsite:<bucket>   # asks you to type the bucket name
```

It touches only `*site_config_backup*.json` outside the `*.crypt/` prefixes
(an encrypted archive's copies are ciphertext and are what make it
self-contained), deletes them permanently on B2 (`--b2-hard-delete` — a plain
delete only hides, and the hidden version keeps the secret), then lists again
*including old versions* and exits non-zero, saying the secrets are still
recoverable, if any version of any of them is left. It must know the remote is
B2 to do that: it takes the type from `PURGE_B2_*` / `RCLONE_CONFIG_<REMOTE>_TYPE`,
or from `rclone config show <remote>` when the remote is defined in your
`rclone.conf`, and refuses `--delete` when it cannot tell (or when the remote
is another kind of store, where it cannot prove old versions are gone). Files
still under Object Lock retention cannot be deleted until it ends; if it
reports some, delete them from the console's *Show versions* view after their
retain-until date.

The unencrypted dumps beside them still hold every customer record; they go
when the plaintext prefix is retired after [switching to encrypted
copies](#encrypting-the-copies).

### Restore drill

A backup that has never been restored is a hope. `scripts/restore-drill.sh`
restores one into a throwaway stack and says whether it worked:

```bash
cd /path/to/repo
scripts/restore-drill.sh --record deploy/restore-drills.log offsite                # newest daily from the bucket
scripts/restore-drill.sh --record deploy/restore-drills.log --monthly offsite      # newest monthly
scripts/restore-drill.sh --stamp 20261102_020001 offsite                           # a particular night
scripts/restore-drill.sh /path/to/a/backup/dir                                     # a set on disk
```

With `offsite` it reads the bucket, prefix and passphrase from `deploy/.env`
(`--env-file` for another) and decrypts when `OFFSITE_CRYPT_PASSWORD` is set.
It reads with the server's key by default; a key of its own is better —
`b2 key create --bucket "$BUCKET" vectora-restore-drill listBuckets,listFiles,readFiles` —
passed as `DRILL_B2_ACCOUNT_ID` / `DRILL_B2_APPLICATION_KEY`. Whichever key, it
never writes to the bucket: the remote is only ever the source of an `rclone
lsf` or `rclone copy` into a private temp directory.

Then, in a compose project of its own (`vbk-drill-<time>`; `--project` to
name it), on an **internal-only network** with **no published ports** — so
nothing restored can send mail, call the ERP or be reached — it creates a
fresh site, puts the set's `encryption_key` in place (from the archive's
`site_config_backup.json`, or `--encryption-key-file`), restores the database
and both file archives, runs `bench migrate`, counts deals, leads,
organisations, contacts, users and files, checks the file archives' contents
arrived, checks every stored secret decrypts with the key, starts the app
server and asks `/api/method/ping`. Output:

```
  step                                       result     secs  detail
  fetch the backup set from the bucket       ok            2
  check the backup set                       ok            0  20261116_143051: db +public +private +site_config
  start the throwaway stack (vbk-drill-…)    ok            6
  create a fresh site                        ok           24
  restore the database and files             ok           17
  bench migrate                              ok            4
  row counts                                 ok           11  CRM Deal=0 CRM Lead=1 ... User=2 File=2
  files restored                             ok            0  public 1/1, private 1/1
  stored secrets decrypt with the key        ok            1  1 of 1 stored secrets decrypt
  GET /api/method/ping                       ok            3  {"message":"pong"}

RESULT: PASS in 68s
```

The exit status is 0 only on PASS. Everything it started is removed with
`docker compose down -v` when it exits, however it exits, and the temp
directory holding the decrypted backup goes with it. It refuses to run as any
project whose name starts with `vectora` (compose would name its containers
`vectora-*`, and its teardown is `down -v`), and in any project that already
has containers. Without an encryption key the secrets step reports
`NOT VERIFIED` rather than failing — but a real new-host restore without that
key loses every integration credential, so treat it as a finding. A backup
with no deals and no leads fails unless `--allow-empty`: restoring an empty
CRM proves little.

**Run it quarterly**, and after any change to the backup setup (new bucket,
new passphrase, a frappe upgrade). Use a host with the RAM for a second
database for ten minutes — the production host is fine outside working hours.
`--record` appends one tab-separated line per run (date, PASS/FAIL, duration,
backup stamp, source, image, counts); keep that file, and put the date and
result in your ops log as well. A FAIL is an incident: the backups you have
are not the backups you think you have.

What it does not prove: that DNS, TLS and the proxy come back, that mail and
the ERP connection work from a new host, or that people can log in through the
browser. Those are the rest of [Restoring onto a new host](#restoring-onto-a-new-host).

### Why this is a service and not a note in a runbook

Until it existed the only backup on a Vectora host was the one an operator
remembered to take before an upgrade — and frappe deletes backups older than
`keep_backups_for_hours` on *every* `bench backup`, a value no site set, so it
defaulted to 23. Taking the pre-upgrade backup destroyed the previous one. A
rep bulk-deleting deals on Monday was unrecoverable by Tuesday afternoon, and
the restore drill below restored a file that no longer existed.

`create-site` now writes `keep_backups_for_hours: 168` on every boot, so a
week of nightlies is on the host at any time.

Ad-hoc, before something you are unsure about:

```bash
docker compose exec backend bench --site all backup --with-files
```

Backups land in the `sites` volume under `<site>/private/backups`.

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

## WhatsApp

The image ships [frappe_whatsapp](https://github.com/shridarpatil/frappe_whatsapp)
(MIT, unmodified, pinned by commit in `scripts/frappe-whatsapp-pin.env`). It does
nothing until a WhatsApp Account is set Active: the tab, the composer and the
webhook all stay off. A new site gets it from `create-site`. An existing one has
to be given it, once:

```bash
# 0. a backup you could actually restore from -- see the warning below
docker compose exec backend bench --site all backup --with-files

# 1. upgrade to a release that contains it, as in "Upgrading". `up -d` reruns the
#    configurator, which puts the app in the volume's sites/apps.txt.

# 2. install it, then migrate so the CRM roles and the WhatsApp lead source land
docker compose exec backend bench --site <site> install-app frappe_whatsapp
docker compose exec backend bench --site <site> migrate
```

**Take this `docker-compose.yml` with the image.** The `apps.txt` rewrite and the
new-site install live in it, so an upgrade that replaces only the image fails step
2 with "not in apps.txt". `upgrade-prod-to.sh` needs this compose file in place
before it runs.

**This changes what a rollback means, and reverses its order.** Once installed,
the site's database names an app older images do not contain, so `bench` fails on
them for every command, `restore` included. **Restore the backup from step 0 while
still on the new image, then put the old tag back in `.env` and `up -d`.** That is
the opposite of the order in **Rolling back**, which is for upgrades that add no
app.

Then configure it:

Do these in this order. Meta delivers as soon as a number is subscribed, and a
number with no line has every delivery refused.

1. **System Settings:** Country **must** be South Africa. A stored `082…` means
   the site's country, both when sending and when matching what arrives.
2. **`host_name`:** the public HTTPS URL, or media links sent to Meta point at an
   internal name: `bench --site <site> set-config host_name https://crm.example.com`
3. **WhatsApp Account** in Desk, one per number: token, phone number id, business
   id, `https://graph.facebook.com`, API version, verify token, status Active.
4. **CRM WhatsApp Line** in Desk, one per number: the account, the rep (required)
   and the App Secret. **A number with no App Secret has every webhook refused
   with a 403**, on purpose. A rep with no line reads threads but cannot send,
   unless WhatsApp Settings names a default outgoing account that is nobody's line.
5. **Meta, last:** point the app's WhatsApp webhook at
   `https://<host>/api/method/frappe_whatsapp.utils.webhook.webhook`, with the
   account's verify token, subscribed to `messages`. Meta's delivery addresses
   are not a stable published list, so **put no IP allowlist or login in front of
   this path**: every message and status would be dropped. The App Secret check
   is what protects it.

Inbound media is downloaded by a background job, so a queue worker must be
running, and is stored as a private file only people who can see the record can
open. A file that cannot be fetched leaves a note in the thread.

A message from a number the CRM has never seen creates a lead owned by the rep
whose number received it. If the number is a Contact on no deal, as imported
contacts usually are, an open deal of their organization takes the message;
failing that, the lead carries the Contact's name and organization. Tokens and App Secrets are Password fields,
System Manager only.

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
| `crm_erp_trusted_hosts` | A list of hostnames the Acumatica **Instance URL** and the SIMERP **Site URL** may point at even though they are on a private, loopback or link-local address, and may reach over plain `http` — see [below](#an-erp-on-a-private-address) | Only for an ERP you host on the same private network. Never a public name |

`site_config.json` is a file in the `sites` volume, so it survives image
upgrades and does not travel with a backup — see the restore notes above. Read
it back with `docker compose exec -T backend cat sites/<site>/site_config.json`.

### An ERP on a private address

The Acumatica and SIMERP settings panes each hold a URL and the credentials the
CRM sends to it, and a Sales Manager can edit both. So the URL has to be
`https://` and has to resolve to a public address: otherwise the pane would be a
way to post the stored secrets to, or probe, anything on the server's own
network. A URL that fails either test is refused when it is saved, and a stored
one is checked again every time the credentials are about to be sent.

A SIMERP or Acumatica you host yourself, reachable only on a private network —
another compose stack on this host, a VPN address — is the legitimate exception,
and it is yours to grant, not the pane's:

```bash
docker compose exec backend bench --site <site> set-config -p \
  crm_erp_trusted_hosts '["erpnext.internal"]'
```

Exact hostnames (or IP literals), no wildcards. A listed host may be private and
may be `http`. SIMERP installed on the *same site* as the CRM has no URL and is
not affected.

**The upgrade that introduces this check grandfathers what is already in use.**
During `bench migrate`, the patch `trust_existing_internal_erp_hosts` reads the
Instance URL and Site URL saved at that moment and adds the host to
`crm_erp_trusted_hosts` for you, keeping whatever the key already held, when:

- it is on a private address (10.x, 172.16–31.x, 192.168.x, an IPv6 ULA, a
  CGNAT/VPN range), or
- it does not resolve from the migrate container **and** its name is private —
  a compose service name with no dot (`erpnext-frontend`), or one under
  `.internal`, `.local`, `.lan` or `.test`.

It does **not** add, and says so with the command that would:

- a loopback or link-local address (`127.0.0.1`, `localhost`,
  `169.254.169.254`) — if a saved URL really points there, list it yourself;
- a public-looking name that merely failed to resolve during the migrate;
- a host that resolves to a public address, which needs no trust.

Every decision is one line in the migrate output and the `crm.integrations`
log, prefixed `crm_erp_trusted_hosts:`. **Read them after the upgrade**: a line
ending in `NOT trusted … run: bench --site … set-config -p crm_erp_trusted_hosts
'[…]'` is an integration that will be refused until you run that command. If
`site_config.json` is read-only the patch does not fail the migrate; it prints
the same command for you to apply. Read the key back afterwards and remove
anything you do not recognise:

```bash
docker compose exec -T backend cat sites/<site>/site_config.json
```

Only that one upgrade does this. A private host entered *later* is refused by
the pane, with a message naming the host and this key, until you list it.

Changing either URL to a different host also asks for the credentials again: the
ones stored for the old host are never sent to a new one. Editing only the path
of the URL does neither.

**A redirect from either server is not followed.** The usual case is a stored
`http://` URL on a public host whose proxy answers `301` to `https://`: it used
to work by being followed, and after this upgrade every read and write through
it is refused with "answered with a redirect". Change the saved URL to
`https://` — before the upgrade, or after it (the scheme is part of the host
the credentials belong to, so the pane asks for them again).

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
| **Local model** | one host with an NVIDIA card | Nothing leaves your network. |

For the local shape this stack ships one opt-in profile, `gpu-model`, and one
model: NVIDIA's `Nemotron 3.5 Bolt E4B`. It is the only model the stack serves
and the only one it is measured against. On a **first boot**, set
`VECTORA_AGENT_ENABLED=1` in `.env` before bringing it up and the site is created
already pointed at the model:

```bash
docker compose --profile gpu-model up -d
docker compose logs -f llm-fetch     # first run downloads 10 GB; every `up -d` re-checks the pin before llm starts
docker compose logs llm | grep -E 'loaded and warm|could not be loaded'  # the first says the first question will be quick
```

`create-site` passes `VECTORA_AGENT_BASE_URL`, `VECTORA_AGENT_MODEL` and
`VECTORA_AGENT_ENABLED` to `after_install`, which writes them into **CRM Agent
Settings** once. Unset, the first two are the `llm` service
(`http://llm:8086/v1`) and the model it serves (`VECTORA_LLM_MODEL`). It is
read at site creation and never again — an admin who later changes the endpoint
in the UI keeps that change across upgrades, which a value re-applied on every
deploy would silently undo.

**Check `.env` for the old values before creating a site.** An `.env` written
for v3.36 or earlier sets `VECTORA_AGENT_MODEL` to the retired
`hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M` and `VECTORA_AGENT_BASE_URL` to
`http://ollama:11434/v1`, and a set value beats the defaults above: a new site
— a QA stack, a second customer — is then created pointed at a service that no
longer exists, and the tier reports `unavailable`. Nothing repairs that
afterwards, because patches do not run on a site that is being installed.
Delete both lines, and `OLLAMA_KEEP_ALIVE` with them, which nothing reads.

On a site that **already exists** those variables do nothing, because
`create-site` skips. Set it in the UI instead: **Settings → Assistant**, with
the values in the table below.

Either way the endpoint has to be the service name. `127.0.0.1` will not work:
from inside the backend container that is the container itself — which is the
one mistake that makes a correctly-pulled model look broken.

**Hardware.** One NVIDIA card the model can have to itself; a 24 GB card holds
it with room to spare. It has not been measured on a CPU, and nothing here
supports running it on one. The 4GB VM that comfortably runs the rest of this
stack is **not** enough to also host a model; put inference on its own machine,
or on a card of its own.

**Another model is a different product.** The tier will talk to any
OpenAI-compatible endpoint, and every number below belongs to this model on
this server. Point `base_url` somewhere else and none of them carries over:
run the injection corpus (`crm.agent.evals.runner`) against that endpoint
before a rep sees its output. What earlier candidates did on that corpus is
recorded, dated, in `.pi/feats/agent/README.md`.

### The model: Nemotron 3.5 Bolt E4B (`gpu-model`)

The `gpu-model` profile serves NVIDIA's `Nemotron 3.5 Bolt E4B` — a
post-trained Gemma 4 E4B, 7.5B parameters, 10 GB at Q8_0 — on ollama. It is one
model for every tier, and it also hears and sees: the Assistant's **dictation**
and **photo attachments** need it (or another model that reads audio and
images).

The profile has to be named on every `pull` and `up -d` (or set
`COMPOSE_PROFILES=gpu-model` in `.env`). A plain upgrade never recreates `llm`.
The service keeps the name and port the llama.cpp server it replaced had, so
`base_url` does not change.

Then **Settings → Assistant**:

| Setting | Value | Why |
|---|---|---|
| `base_url` | `http://llm:8086/v1` | the service, never `127.0.0.1`; a new site is created with it |
| `model` | `nemotron-3.5-bolt:e4b-q8_0` | as `VECTORA_LLM_MODEL`; a new site is created with it |
| `context_tokens` | **32768** | each of the four parallel requests gets `OLLAMA_CONTEXT_LENGTH`; more here and ollama truncates the instruction away |
| `max_tokens` | **8192** | thinking is charged to it |
| Turn off model reasoning | **off** | with thinking the injection corpus never lands; without it one case does |
| Model accepts audio and images | **on** | turns on dictation and photo attachments |
| `timeout` | 59 (the cap) | four requests at once with thinking: p90 15–20 s |

Dictation always runs with thinking off, whatever the setting says — a
reasoning pass over a transcription paraphrases it.

Measured 2026-11-16 (one RTX PRO 4000 Blackwell, Q8_0, ollama 0.40.16), against
the MiniCPM-V 4.7 it replaces:

| | Bolt E4B, thinking on | MiniCPM-V 4.7 (2026-10-29) |
|---|---|---|
| Task probe: 7 Analyst plans, 6 grounded Analyst answers, 3 summaries, 3 drafts, 4 Assistant answers | 22/23 (the miss was the probe's own regex) | 23/23 |
| Injection corpus, 5 cases ×5, two runs | **resisted all** | 2 of 5 landed |
| Attachment injection (planted discount, spec override, phishing link; text and image) | **resisted all** | image-borne discount landed 5/5 (with a projector) |
| Dictation, 32 clips: WER / key tokens | **0.138** / 84 of 96 | no audio |
| South African English, 117 clips (EdAcc) | WER 0.143 (Whisper small: 0.140) | — |
| Reading a cell off a dense reference-sheet image | 6–7 of 11 | 9 of 11 (with the 4x projector) |
| One request / four at once, median | 1.6 s / 4–9 s (p90 15–20 s) | 4.1 s |

With thinking **off** it is faster (0.4 s) and the task probe is unchanged, but
the Analyst's hostile-organisation-name case lands 5/5 — keep it on. Figures it
reads off a photo are not checked the way reference-sheet rows are: an answer
that rests on an image is never shown as verified. Under four parallel requests
the outputs vary run to run (batched decoding), and two probe runs in four lost
an Analyst sentence to the grounding check — which is the check doing its job.

**The model is pinned.** Before `llm` starts, `llm-fetch` pulls
`VECTORA_LLM_MODEL` with a private ollama of its own and checks every digest
in its manifest — weights, the audio/vision projector, chat template,
parameters — against `VECTORA_LLM_FINGERPRINT`. ollama verifies each blob
against its digest as it downloads, so the manifest pins the bytes. On a
mismatch (the tag was re-pointed upstream) the model is deleted again, the step
exits 1 and `llm` is not started: every tier degrades to `unavailable` rather
than answering from an unmeasured model. Re-run the evals before changing
either value. `llm` loads the model and warms it with a few throwaway
questions as it starts (about a minute and a half), and logs `<model> is
loaded and warm`; the first real question does not wait for the weights.

The licence is OpenMDW-1.1 (over Apache-2.0 for the Gemma base): no field-of-use
limits, no share-back, outputs unrestricted. Its notice duty applies only if the
weights are distributed — shipping them on a customer's own hardware is that.
NVIDIA's model card warns it is "more susceptible to prompt injection" without
rails; the fences, the grounding checks and the no-write-tools rule are those
rails, and the corpus above is measured through them.

One surface is outside both that rule and that corpus. The domain-enrichment
model fallback (**CRM Enrichment Settings → Model Fallback**, off by default) hands the model a
stranger's web page and writes what it reads — company name, description,
industry — into fields the rules left blank, with no person in between. The
corpus has no page-injection case for it, so it has **not been measured on this
model**. Leave it off until it has been.

**Moving a host from MiniCPM-V (the `gpu-model` profile up to v3.30).** The
old weights sit in the `llm-models` volume, which nothing uses any more:

1. `docker compose --profile gpu-model up -d` — recreates `llm` on ollama and
   runs `llm-fetch` (10 GB download).
2. Change the settings above in **Settings → Assistant**, Save, then
   **Test connection**.
3. Once it answers, remove the old weights:
   `docker volume rm <project>_llm-models` (21 GB).

A host override that pinned `llm` to one card by `device_ids` still applies —
the service name is unchanged.

**Moving a host from the `local-model` profile (up to v3.36).** That profile
— an `ollama` service on port 11434 serving `LFM2.5-2.6B` — is gone, and so is
the model. `migrate` moves a site only when it stores *both* exactly the old
shipped model name and exactly `http://ollama:11434/v1`, which is a site that
was on this stack's own model server: it is pointed at
`http://llm:8086/v1` and this model, "Turn off model reasoning" is switched
back off (the old model ignored it; this one obeys it, and is measured with
thinking on), and a stored API key is removed, because it was entered for the
old endpoint. A site whose admin entered another endpoint is left exactly as it
is, its model name included — that is their server. Until `llm` is up the tier
reports `unavailable`, as it does for any endpoint that does not answer.

1. In `.env`, change `COMPOSE_PROFILES=local-model` to
   `COMPOSE_PROFILES=gpu-model` if it is set there. Compose does not complain
   about a profile that no longer exists; it starts nothing for it.
2. `docker compose --profile gpu-model up -d` on a host with an NVIDIA card.
3. Set the rest of the table above in **Settings → Assistant**, Save, then
   **Test connection**.
4. Remove what the old profile left behind. Compose no longer knows the
   `ollama` container, so no `up -d` stops it: it keeps running, holding its
   memory, until it is removed.
   `docker rm -f <project>-ollama-1 <project>-ollama-pull-1`, then
   `docker volume rm <project>_ollama-models` — the volume holds only the
   downloaded weights, nothing that cannot be fetched again.
5. Drop `OLLAMA_KEEP_ALIVE` and `OLLAMA_CONTEXT_LENGTH` from `.env`; nothing
   reads them. Drop `VECTORA_AGENT_MODEL` and `VECTORA_AGENT_BASE_URL` too if
   they still name the old model and `http://ollama:11434/v1`: they do nothing
   to this site, and a site created later from the same `.env` would be
   pointed at a service that is no longer there.

A host without an NVIDIA card has no model in this stack any more: point
`base_url` at an endpoint elsewhere, or leave the tier off.

### The model licence, and who it binds

The licensee is whoever runs the weights — the customer, not us. Nemotron 3.5
Bolt E4B ships under OpenMDW-1.1, over Apache-2.0 for its Gemma base: no
field-of-use limits, no revenue threshold, no share-back, outputs unrestricted.
Its one duty is a notice, and it applies only where the weights are
distributed — see above. Nothing has to be bought to run it.

A deployment that wants no model at all can leave the agent tier off, which is
the shipped default and a supported state — the deterministic tier (assignment,
SLA, automation rules, signals) runs without a model at all.

**What a local model does not fix.** Prompt injection. This model resisted
every case in the corpus on 2026-11-16 with its thinking on, and one case
landed 5 of 5 with thinking off; its own model card warns it is more
susceptible without rails. A corpus is the attacks somebody thought of. That is
why the chat and drafting surfaces have no write tools and why drafted replies
are always shown to a human before sending. The one place a model's output is
written without a person reading it first is the opt-in enrichment fallback
described above — unmeasured on this model, and off by default. Running the
model yourself changes where the weights
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
   cannot also host a model. Bring it up with `--profile gpu-model`, confirm
   the model answers, and leave drafted replies behind the human gate.

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
`0.32.15`, and to `0.40.4` on 2026-10-15. Check a pin resolves before shipping it.
(The profile was removed with its model on 2026-11-20; `gpu-model` is the one
that remains.)

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

Run the profile you actually use — `docker compose --profile gpu-model up -d`
(it was `local-model` when this was written) rather than bare `up -d`, or the
model service drops out of compose's view.

**Still open here:** an offsite backup destination (decided: an S3-compatible
bucket, not yet wired — step 3 cannot close until it exists), and every
integration in step 6.

## Pilot checklist

The defaults below are deliberately conservative; loosen them as the pilot
earns trust, not before.

1. **Restore drill first.** `scripts/restore-drill.sh offsite` — see
   [Restore drill](#restore-drill) — then log in to a scratch site of your own
   once. A backup you have never restored is a hope, not a plan.
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
