---
name: deploy
description: Bring up, upgrade, or verify the deploy/ compose stack (the published ghcr image). Use for first boot, a localhost rehearsal, or a version upgrade on a host.
disable-model-invocation: true
---

# Deploy / upgrade the compose stack

Authoritative detail is in `deploy/README.md`. This is the procedure and the
traps; read that file for TLS, backups, rollback, and the pilot checklist.

**Run compose from the host, never from the devcontainer** for a localhost
rehearsal — and remember containers started from inside the container are
siblings on the host anyway.

## Which am I doing?

| Situation | Section |
|---|---|
| Nothing running yet | First boot |
| Rehearsing on this machine | First boot, with the localhost overrides |
| A version is already running | Upgrade |

## First boot

```bash
cd deploy
cp .env.example .env      # fill SITE_NAME, DB_ROOT_PASSWORD, ADMIN_PASSWORD
docker compose up -d
docker compose logs -f create-site        # one-shot; wait for it to finish
```

Every long-running service waits on `create-site`, so `backend`, `frontend` and
the workers sit in `Created` until it completes. That is correct, not stuck.
`create-site` is idempotent and re-runs `bench enable-scheduler` every time —
which matters, because `bench new-site` writes `enable_scheduler: 0`.

**Localhost overrides** (four values differ; three of them bite):

| Value | Localhost |
|---|---|
| `SITE_NAME` | `vectora.localhost` (RFC 6761 → loopback) |
| `HTTP_PUBLISH_PORT` | **8090** — 8080 collides with vite, and the symptom is a page from the wrong server, not a bind error |
| `VECTORA_TAG` | `develop` (not `stable`) |
| TLS | none; loopback only |

## Upgrade

```bash
docker compose exec backend bench --site all backup --with-files   # first
# edit .env: VECTORA_TAG=vX.Y.Z          <-- skip this and NOTHING upgrades
docker compose exec backend bench --site <site> set-maintenance-mode on
docker compose pull
docker compose up -d
docker compose exec backend bench --site all migrate
docker compose exec backend bench --site <site> set-maintenance-mode off
```

Maintenance mode is not ceremony: `up -d` serves new code immediately and
`migrate` then takes minutes on a real dataset — new code against old schema is
the one combination nothing is tested against. Note `set-maintenance-mode` takes
one site at a time (unlike `migrate`/`backup`, which take `all`), and HTTP
workers take up to 60s to see the flag (`site_cache(ttl=60)`); background
workers see it immediately.

## Verify — always, before handing anyone the URL

```bash
docker compose ps                                   # all "running (healthy)"
docker compose exec backend bench --site <site> doctor
```

Read the doctor output rather than the exit code:

- `Scheduler disabled … True` → `create-site` did not reach its last line
- `Workers online: 0` → queue containers are down (`docker compose logs queue-long`)

Expect `Workers online: 2` (queue-short, queue-long).

## Demo data is opt-in — leave it that way on a real host

Finishing Frappe's setup wizard used to seed fake leads/deals/users, which the
proactive tier then scores and folds into the weekly forecast snapshot — a
snapshot records what was believed on a date and cannot be corrected afterwards.
Only set `crm_seed_demo_data 1` on a throwaway site.

## Before claiming a deploy worked

Say which tag is running, that `ps` was healthy, and what `doctor` printed. A
green `up -d` is not evidence the app is serving.
