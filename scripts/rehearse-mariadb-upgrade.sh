#!/usr/bin/env bash
#
# Rehearse a MariaDB engine upgrade (10.6 -> 11.4 by default) on a RESTORE of a
# real backup, in a throwaway compose project, before doing it to the database
# that holds the data. See "Upgrading MariaDB to 11.4" in deploy/README.md.
#
#     scripts/rehearse-mariadb-upgrade.sh <backup-dir>
#     scripts/rehearse-mariadb-upgrade.sh <...-database.sql.gz> <...-site_config_backup.json>
#
# <backup-dir> is a directory holding one `bench backup` set: the newest
# *-database.sql.gz in it and the *-site_config_backup.json with the same
# timestamp prefix. Files (--with-files tarballs) are not needed and ignored.
#
# What it does, in order, each step timed:
#   1. starts db (FROM image) + two redis in a new project with an INTERNAL
#      network (no published ports, no route out -- a restored production site
#      cannot reach the ERP, the mail server or a model from here)
#   2. restores the dump, records exact row counts for every table and
#      CHECKSUM TABLE for a few key tables
#   3. slow-shuts the old server down (innodb_fast_shutdown=0, long timeout)
#   4. swaps the db image to TO on the SAME volume with MARIADB_AUTO_UPGRADE=1
#      -- the image's entrypoint backs up the system schema and runs
#      mariadb-upgrade -- and checks that it did
#   5. compares counts and checksums with step 2: must be identical
#   6. runs `bench migrate` with the APP image, compares again (key tables
#      must keep their row counts; other differences are reported)
#   7. starts gunicorn and hits /api/method/ping plus three authenticated
#      whitelisted reads, one of them a count checked against SQL
#   8. takes a `bench backup` against the new server, and checks the dump
#   9. restores that dump onto a fresh FROM engine -- the late rollback in the
#      runbook -- and compares the key tables' row counts
#  10. prints a pass/fail summary with timings, and tears everything down
#
# Options (all optional):
#   --from IMAGE   old engine.  Default: the DB_IMAGE default in deploy/docker-compose.yml
#   --to IMAGE     new engine.  Default: the commented DB_IMAGE target in deploy/.env.example
#   --app IMAGE    app image.   Default: ghcr.io/absolute-insight/simcrm:$VECTORA_TAG, where
#                  VECTORA_TAG comes from the environment, else from deploy/.env.example.
#                  Pass the tag production RUNS, so migrate is the no-op it should be.
#   --keep         leave the project up at the end (prints how to remove it)
#
# Exit status: 0 when every check passed, 1 when any failed, 2 on a usage or
# safety refusal. It never touches a project, container, volume or network
# whose name contains "vectora" -- it refuses to start if its own would.
#
# Needs: bash, docker with compose v2, gzip, and about 3x the uncompressed
# dump in free docker disk space.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

die() { echo "rehearse: $*" >&2; exit 2; }
usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 2; }

FROM_IMAGE="" TO_IMAGE="" APP_IMAGE="" KEEP=0
args=()
while (($#)); do
	case "$1" in
		--from) FROM_IMAGE="${2:?--from needs an image}"; shift 2 ;;
		--to) TO_IMAGE="${2:?--to needs an image}"; shift 2 ;;
		--app) APP_IMAGE="${2:?--app needs an image}"; shift 2 ;;
		--keep) KEEP=1; shift ;;
		-h | --help) usage ;;
		--) shift; args+=("$@"); break ;;
		-*) die "unknown option $1 (see --help)" ;;
		*) args+=("$1"); shift ;;
	esac
done
((${#args[@]} >= 1 && ${#args[@]} <= 2)) || usage

# --- inputs -----------------------------------------------------------------
if ((${#args[@]} == 1)) && [[ -d "${args[0]}" ]]; then
	dir="${args[0]}"
	DUMP="$(ls -1t "$dir"/*-database.sql.gz 2>/dev/null | head -n1 || true)"
	[[ -n "$DUMP" ]] || die "no *-database.sql.gz in $dir"
	prefix="$(basename "$DUMP")"
	prefix="${prefix%-database.sql.gz}"
	CONFIG="$dir/$prefix-site_config_backup.json"
else
	DUMP="${args[0]}"
	CONFIG="${args[1]:-}"
fi
[[ -f "$DUMP" ]] || die "no such dump: $DUMP"
[[ "$DUMP" == *.sql.gz ]] || die "expected a gzipped dump (*.sql.gz): $DUMP"
[[ -n "$CONFIG" && -f "$CONFIG" ]] || die "no site_config backup next to the dump (expected $CONFIG)"
gzip -t "$DUMP" || die "$DUMP is not a readable gzip file"

if [[ -z "$FROM_IMAGE" ]]; then
	FROM_IMAGE="$(grep -oE 'DB_IMAGE:-[^}]+' "$repo/deploy/docker-compose.yml" | head -n1 | cut -d- -f2- || true)"
	[[ -n "$FROM_IMAGE" ]] || die "cannot read the DB_IMAGE default from deploy/docker-compose.yml; pass --from"
fi
if [[ -z "$TO_IMAGE" ]]; then
	TO_IMAGE="$(sed -nE 's/^#[[:space:]]*DB_IMAGE=([^[:space:]]+).*/\1/p' "$repo/deploy/.env.example" | head -n1)"
	[[ -n "$TO_IMAGE" ]] || die "cannot read the target DB_IMAGE from deploy/.env.example; pass --to"
fi
if [[ -z "$APP_IMAGE" ]]; then
	tag="${VECTORA_TAG:-$(sed -nE 's/^VECTORA_TAG=([^[:space:]]+).*/\1/p' "$repo/deploy/.env.example" | head -n1)}"
	[[ -n "$tag" ]] || die "no VECTORA_TAG; pass --app"
	APP_IMAGE="ghcr.io/absolute-insight/simcrm:$tag"
fi
REDIS_IMAGE="$(grep -oE 'redis:6\.2-alpine@sha256:[0-9a-f]+' "$repo/deploy/docker-compose.yml" | head -n1 || true)"
REDIS_IMAGE="${REDIS_IMAGE:-redis:6.2-alpine}"
[[ "$FROM_IMAGE" != "$TO_IMAGE" ]] || die "--from and --to are the same image"

# --- safety: our names, never production's ------------------------------------
# compose would otherwise take a project name, a file or an env file from the
# caller's environment. On the production host that environment can point at
# the live stack.
unset COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_ENV_FILES COMPOSE_PROFILES COMPOSE_PATH_SEPARATOR DB_IMAGE
PROJECT="mdb-rehearse-$(date +%s)-$$"
[[ "$PROJECT" =~ ^mdb-rehearse-[0-9]+-[0-9]+$ ]] || die "unexpected project name $PROJECT"
case "${PROJECT,,}" in *vectora*) die "refusing: project name $PROJECT contains 'vectora'" ;; esac
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
	[[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]] ||
	[[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
	die "refusing: a project named $PROJECT already exists"
fi
SITE="mdb-rehearsal.localhost"
TAB=$'\t'

work="$(mktemp -d "${TMPDIR:-/tmp}/mdb-rehearse.XXXXXX")"
chmod 700 "$work"
root_pw="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
admin_pw="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"

cat >"$work/compose.yml" <<'YAML'
# Generated by scripts/rehearse-mariadb-upgrade.sh -- a throwaway project.
# The db flags mirror deploy/docker-compose.yml's `db` service; keep them so.
networks:
  default:
    internal: true
services:
  db:
    image: ${DB_IMAGE:?}
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
      - --innodb-buffer-pool-size=384M
    environment:
      MARIADB_ROOT_PASSWORD: ${ROOT_PW:?}
      MARIADB_AUTO_UPGRADE: ${AUTO_UPGRADE:-}
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      start_period: 60s
      interval: 2s
      timeout: 5s
      retries: 150
    stop_grace_period: 600s
    volumes:
      - db-data:/var/lib/mysql
  # Step 9 only: an empty FROM engine for the rollback restore.
  db-rollback:
    image: ${ROLLBACK_IMAGE:?}
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
    environment:
      MARIADB_ROOT_PASSWORD: ${ROOT_PW:?}
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      start_period: 60s
      interval: 2s
      timeout: 5s
      retries: 150
    volumes:
      - rollback-data:/var/lib/mysql
  redis-cache:
    image: ${REDIS_IMAGE:?}
  redis-queue:
    image: ${REDIS_IMAGE:?}
  backend:
    image: ${APP_IMAGE:?}
    volumes:
      - sites:/home/frappe/frappe-bench/sites
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS -H 'Host: mdb-rehearsal.localhost' http://localhost:8000/api/method/ping || exit 1"]
      start_period: 120s
      interval: 3s
      timeout: 5s
      retries: 40
volumes:
  db-data:
  rollback-data:
  sites:
YAML

envfile="$work/compose.env"
write_env() { # $1 = db image, $2 = auto-upgrade value
	umask 077
	printf 'DB_IMAGE=%s\nAUTO_UPGRADE=%s\nROOT_PW=%s\nREDIS_IMAGE=%s\nAPP_IMAGE=%s\nROLLBACK_IMAGE=%s\n' \
		"$1" "$2" "$root_pw" "$REDIS_IMAGE" "$APP_IMAGE" "$FROM_IMAGE" >"$envfile"
}
dc() { docker compose -p "$PROJECT" --project-directory "$work" -f "$work/compose.yml" --env-file "$envfile" "$@"; }
# SQL as root over the container's own socket; the password is read from the
# container's environment, never put on a command line.
sql() { dc exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -uroot -N -B "$@"' sh "$@"; }
sql_rb() { dc exec -T db-rollback sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -uroot -N -B "$@"' sh "$@"; }

cleanup() {
	local rc=$?
	if ((KEEP)); then
		echo
		echo "rehearse: --keep: project left up. Remove it with:"
		echo "  docker compose -p $PROJECT --project-directory $work -f $work/compose.yml --env-file $envfile down -v"
	else
		dc down -v --remove-orphans >/dev/null 2>&1 || true
		rm -rf "$work"
	fi
	exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

now() { date +%s; }
log() { printf '\n== %s\n' "$*"; }
declare -A T
results=()
failed=0
check() { # $1 = name, $2 = 0 for pass; $3.. detail
	local name="$1" ok="$2"
	shift 2
	if [[ "$ok" == 0 ]]; then results+=("PASS  $name${*:+ -- $*}"); else results+=("FAIL  $name${*:+ -- $*}"); failed=1; fi
}
human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }

echo "rehearse: project   $PROJECT (internal network, no published ports)"
echo "rehearse: dump      $DUMP"
echo "rehearse: from      $FROM_IMAGE"
echo "rehearse: to        $TO_IMAGE"
echo "rehearse: app       $APP_IMAGE"

# --- 1. the old engine --------------------------------------------------------
log "1/9 starting the old engine"
write_env "$FROM_IMAGE" ""
dc pull -q db redis-cache backend
t=$(now)
dc up -d --wait db redis-cache redis-queue
T[old_start]=$(($(now) - t))
old_version="$(sql -e 'SELECT VERSION()')"
echo "old server: $old_version"

# --- 2. restore -------------------------------------------------------------
log "2/9 restoring the backup"
# Site config: the backup's, plus switches that keep a restored production
# site quiet. db_host and redis come from common_site_config as on prod.
dc run --rm --no-deps -T backend python3 -c '
import json, os, sys
cfg = json.load(sys.stdin)
cfg.update({"mute_emails": 1, "pause_scheduler": 1, "maintenance_mode": 0})
cfg.pop("host_name", None)
for d in ("logs", "locks", "private/backups", "private/files", "public/files"):
    os.makedirs("sites/'"$SITE"'/" + d, exist_ok=True)
with open("sites/'"$SITE"'/site_config.json", "w") as f:
    json.dump(cfg, f, indent=1)
common = {}
if os.path.exists("sites/common_site_config.json"):
    common = json.load(open("sites/common_site_config.json"))
common.update({"db_host": "db", "db_port": 3306, "redis_cache": "redis://redis-cache:6379",
    "redis_queue": "redis://redis-queue:6379", "redis_socketio": "redis://redis-queue:6379"})
json.dump(common, open("sites/common_site_config.json", "w"), indent=1)
open("sites/apps.txt", "w").write("\n".join(sorted(os.listdir("apps"), key=lambda a: a != "frappe")) + "\n")
' <"$CONFIG" >/dev/null
# Read on the host: the image's entrypoint writes to stdout before the command.
db_name="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["db_name"])' "$CONFIG")"
db_user="$(python3 -I -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c.get("db_user") or c["db_name"])' "$CONFIG")"
[[ "$db_name" =~ ^[A-Za-z0-9_]+$ && "$db_user" =~ ^[A-Za-z0-9_]+$ ]] || die "unexpected db_name/db_user in $CONFIG"
db_pw="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["db_password"])' "$CONFIG")"
# Over stdin, so the site's database password never reaches a command line.
printf "CREATE DATABASE \`%s\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\nCREATE USER '%s'@'%%' IDENTIFIED BY '%s';\nGRANT ALL PRIVILEGES ON \`%s\`.* TO '%s'@'%%';\nFLUSH PRIVILEGES;\n" \
	"$db_name" "$db_user" "${db_pw//\'/\'\'}" "$db_name" "$db_user" | sql
unset db_pw

dump_bytes=$(stat -c %s "$DUMP")
t=$(now)
gzip -dc "$DUMP" | tee >(wc -c >"$work/raw_bytes") | sql "$db_name"
T[restore]=$(($(now) - t))
sleep 1
raw_bytes=$(cat "$work/raw_bytes")
echo "restored $(human "$dump_bytes") gzipped / $(human "$raw_bytes") SQL in ${T[restore]}s"

KEY_TABLES=("tabCRM Lead" "tabCRM Deal" "tabContact" "tabCRM Organization" "tabCommunication" "tabUser" "tabFile" "tabVersion")
snapshot() { # $1 = label; writes counts.$1 and sums.$1
	local label="$1" q
	q="$(sql -e "SET SESSION group_concat_max_len = 16777216;
		SELECT GROUP_CONCAT(CONCAT('SELECT ', QUOTE(table_name), ', COUNT(*) FROM \`', REPLACE(table_name, '\`', '\`\`'), '\`')
			ORDER BY table_name SEPARATOR ' UNION ALL ')
		FROM information_schema.tables WHERE table_schema = '$db_name' AND table_type = 'BASE TABLE'")"
	sql "$db_name" -e "$q" | sort >"$work/counts.$label"
	# Table and column collations: 11.4 maps a bare utf8mb4 to uca1400_ai_ci
	# (character_set_collations), so a definition that drifted would show here.
	sql -e "SELECT table_name, table_collation FROM information_schema.tables WHERE table_schema = '$db_name'
		UNION ALL SELECT CONCAT(table_name, '.', column_name), collation_name FROM information_schema.columns
		WHERE table_schema = '$db_name' AND collation_name IS NOT NULL" | sort >"$work/coll.$label"
	local present=() tbl
	for tbl in "${KEY_TABLES[@]}"; do grep -q "^$tbl$TAB" "$work/counts.$label" && present+=("\`$tbl\`"); done
	local IFS=,
	sql "$db_name" -e "CHECKSUM TABLE ${present[*]} EXTENDED" | sed "s/^$db_name\.//" | sort >"$work/sums.$label"
}
t=$(now)
snapshot before
T[snapshot]=$(($(now) - t))
tables=$(wc -l <"$work/counts.before")
rows=$(awk -F'\t' '{s += $2} END {print s + 0}' "$work/counts.before")
echo "$tables tables, $rows rows; key-table checksums:"
sed 's/^/  /' "$work/sums.before"
((tables > 0)) || die "the restore produced no tables"

# --- 3. clean shutdown -------------------------------------------------------
log "3/9 slow shutdown of the old engine"
# A slow shutdown leaves no undo or change-buffer work behind, and 11.x refuses
# to start on a 10.6 data directory that was not shut down cleanly -- crash
# recovery across the redo-log format change (10.8) is not supported.
sql -e "SET GLOBAL innodb_fast_shutdown = 0"
t=$(now)
dc stop -t 600 db
T[shutdown]=$(($(now) - t))
if dc logs db 2>&1 | tail -n 20 | grep -q "Shutdown complete"; then
	check "old engine shut down cleanly" 0 "${T[shutdown]}s"
else
	check "old engine shut down cleanly" 1 "no 'Shutdown complete' in the log -- do not start the new engine on this"
	exit 1
fi

# --- 4. the new engine on the same volume -------------------------------------
log "4/9 starting the new engine with MARIADB_AUTO_UPGRADE=1"
write_env "$TO_IMAGE" "1"
dc pull -q db
t=$(now)
dc up -d --wait db
T[upgrade]=$(($(now) - t))
new_version="$(sql -e 'SELECT VERSION()')"
echo "new server: $new_version"
dc logs db 2>&1 | grep -iE 'upgrade|backup' | sed 's/^/  /' || true
if dc logs db 2>&1 | grep -q "Finished mariadb-upgrade"; then
	check "mariadb-upgrade ran on first start" 0 "$old_version -> $new_version in ${T[upgrade]}s"
else
	check "mariadb-upgrade ran on first start" 1 "the entrypoint did not run it; see 'docker compose logs db'"
fi
info="$(dc exec -T db cat /var/lib/mysql/mariadb_upgrade_info 2>/dev/null | tr -d '\0' || true)"
[[ "$info" == "${new_version%%-*}"* ]] && check "mariadb_upgrade_info records the new version" 0 "$info" ||
	check "mariadb_upgrade_info records the new version" 1 "found '${info:-nothing}'"

# --- 5. same data? ------------------------------------------------------------
log "5/9 comparing data after the engine swap"
snapshot upgraded
if diff -u "$work/counts.before" "$work/counts.upgraded" >"$work/diff.counts"; then
	check "row counts identical after the engine swap" 0 "$tables tables, $rows rows"
else
	check "row counts identical after the engine swap" 1 "$(grep -c '^[-+][^-+]' "$work/diff.counts") differing lines"
	sed 's/^/  /' "$work/diff.counts" | head -n 40
fi
if diff -u "$work/sums.before" "$work/sums.upgraded" >"$work/diff.sums"; then
	check "key-table checksums identical after the engine swap" 0 "$(wc -l <"$work/sums.before") tables"
else
	check "key-table checksums identical after the engine swap" 1
	sed 's/^/  /' "$work/diff.sums"
fi
if diff -u "$work/coll.before" "$work/coll.upgraded" >"$work/diff.coll"; then
	check "table and column collations unchanged by the engine swap" 0 "$(wc -l <"$work/coll.before") definitions"
else
	check "table and column collations unchanged by the engine swap" 1
	head -n 20 "$work/diff.coll" | sed 's/^/  /'
fi

# --- 6. migrate ----------------------------------------------------------------
log "6/9 bench migrate with $APP_IMAGE"
t=$(now)
if dc run --rm --no-deps -T backend bench --site "$SITE" migrate >"$work/migrate.log" 2>&1; then
	T[migrate]=$(($(now) - t))
	check "bench migrate" 0 "${T[migrate]}s"
else
	T[migrate]=$(($(now) - t))
	check "bench migrate" 1 "exit non-zero after ${T[migrate]}s"
	tail -n 40 "$work/migrate.log" | sed 's/^/  /'
fi
snapshot migrated
bad=0
for tbl in "${KEY_TABLES[@]}"; do
	b="$(grep "^$tbl$TAB" "$work/counts.upgraded" || true)"
	a="$(grep "^$tbl$TAB" "$work/counts.migrated" || true)"
	[[ "$b" == "$a" ]] || { bad=1; echo "  $tbl: '${b#*$TAB}' -> '${a#*$TAB}'"; }
done
check "key tables keep their row counts through migrate" "$bad"
uca="$(grep -c 'uca1400' "$work/coll.migrated" || true)"
[[ "$uca" == 0 ]] && check "nothing migrate created took the 11.4 uca1400 default collation" 0 ||
	{ check "nothing migrate created took the 11.4 uca1400 default collation" 1 "$uca definitions"; grep uca1400 "$work/coll.migrated" | head -n 10 | sed 's/^/  /'; }
if ! diff -q "$work/counts.upgraded" "$work/counts.migrated" >/dev/null; then
	echo "  (info) migrate changed other tables -- expected when the app image is newer than the backup:"
	diff "$work/counts.upgraded" "$work/counts.migrated" | grep '^[<>]' | head -n 30 | sed 's/^/    /' || true
fi
if ! diff -q "$work/sums.upgraded" "$work/sums.migrated" >/dev/null; then
	echo "  (info) migrate rewrote rows in key tables:"
	diff "$work/sums.upgraded" "$work/sums.migrated" | grep '^[<>]' | sed 's/^/    /' || true
fi

# --- 7. the app answers ----------------------------------------------------------
log "7/9 serving requests"
# A throwaway Administrator password, set only in this restored copy.
dc run --rm --no-deps -T backend bench --site "$SITE" set-admin-password "$admin_pw" >"$work/admin.log" 2>&1 ||
	{ check "set a throwaway Administrator password" 1; tail -n 5 "$work/admin.log" | sed 's/^/  /'; }
if dc up -d --wait backend >/dev/null 2>&1; then
	check "gunicorn healthy on the new engine" 0
else
	check "gunicorn healthy on the new engine" 1 "see 'docker compose logs backend'"
fi
curl_in() { dc exec -T backend curl -sS -H "Host: $SITE" -b /tmp/mdb.cookies -c /tmp/mdb.cookies "$@"; }
ping="$(curl_in http://localhost:8000/api/method/ping 2>&1 || true)"
[[ "$ping" == *'"pong"'* ]] && check "GET /api/method/ping" 0 || check "GET /api/method/ping" 1 "${ping:0:200}"
printf 'usr=Administrator&pwd=%s' "$admin_pw" |
	curl_in -o /dev/null -w '%{http_code}' --data-binary @- http://localhost:8000/api/method/login >"$work/login" 2>&1 || true
[[ "$(cat "$work/login")" == 200 ]] && check "POST /api/method/login" 0 || check "POST /api/method/login" 1 "HTTP $(cat "$work/login")"
who="$(curl_in http://localhost:8000/api/method/frappe.auth.get_logged_user 2>&1 || true)"
[[ "$who" == *'"Administrator"'* ]] && check "GET frappe.auth.get_logged_user" 0 || check "GET frappe.auth.get_logged_user" 1 "${who:0:200}"
for dt in "CRM Lead" "CRM Deal"; do
	want="$(grep "^tab$dt$TAB" "$work/counts.migrated" | cut -f2)"
	got="$(curl_in -G --data-urlencode "doctype=$dt" http://localhost:8000/api/method/frappe.client.get_count 2>&1 || true)"
	[[ -n "$want" && "$got" == *"\"message\":$want}"* ]] && check "GET frappe.client.get_count $dt matches SQL" 0 "$want" ||
		check "GET frappe.client.get_count $dt matches SQL" 1 "SQL ${want:-?}, API ${got:0:200}"
done
leads="$(curl_in -G --data-urlencode 'fields=["name","modified"]' --data-urlencode 'limit_page_length=5' \
	--data-urlencode 'order_by=modified desc' "http://localhost:8000/api/resource/CRM%20Lead" 2>&1 || true)"
[[ "$leads" == '{"data":'* ]] && check "GET /api/resource/CRM Lead (ordered list)" 0 || check "GET /api/resource/CRM Lead (ordered list)" 1 "${leads:0:200}"

# --- 8. a backup from the new engine -----------------------------------------------
log "8/9 bench backup against the new engine"
t=$(now)
if dc exec -T backend bench --site "$SITE" backup >"$work/backup.log" 2>&1; then
	T[backup]=$(($(now) - t))
	# ...and the file it wrote is a whole dump: readable gzip, ends the way
	# mariadb-dump ends a complete run, and has the CRM's tables in it.
	if dc exec -T backend bash -c 'f=$(ls -1t sites/'"$SITE"'/private/backups/*-database.sql.gz | head -n1) &&
		gzip -t "$f" && gzip -dc "$f" | tail -n 1 | grep -q "Dump completed" &&
		gzip -dc "$f" | grep -q "CREATE TABLE \`tabCRM Lead\`"' >>"$work/backup.log" 2>&1; then
		check "bench backup against the new engine" 0 "${T[backup]}s, dump complete"
	else
		check "bench backup against the new engine" 1 "the dump it wrote is incomplete"
	fi
else
	T[backup]=$(($(now) - t))
	check "bench backup against the new engine" 1
	tail -n 20 "$work/backup.log" | sed 's/^/  /'
fi

# --- 9. the late rollback: that dump onto a fresh old engine -------------------------
log "9/9 restoring the new engine's dump onto a fresh $FROM_IMAGE"
dc up -d --wait db-rollback >/dev/null 2>&1
printf 'CREATE DATABASE `%s` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n' "$db_name" | sql_rb
t=$(now)
if dc exec -T backend bash -c 'cat "$(ls -1t sites/'"$SITE"'/private/backups/*-database.sql.gz | head -n1)"' |
	gzip -dc | sql_rb "$db_name" 2>"$work/rollback.log"; then
	T[rollback]=$(($(now) - t))
	bad=0
	for tbl in "${KEY_TABLES[@]}"; do
		grep -q "^$tbl$TAB" "$work/counts.migrated" || continue
		a="$(sql "$db_name" -e "SELECT COUNT(*) FROM \`$tbl\`")"
		b="$(sql_rb "$db_name" -e "SELECT COUNT(*) FROM \`$tbl\`")"
		[[ "$a" == "$b" ]] || { bad=1; echo "  $tbl: $a on the new engine, $b restored onto the old"; }
	done
	check "a dump from the new engine restores onto the old one" "$bad" "${T[rollback]}s, key-table counts equal"
else
	T[rollback]=$(($(now) - t))
	check "a dump from the new engine restores onto the old one" 1
	tail -n 10 "$work/rollback.log" | sed 's/^/  /'
fi

# --- summary --------------------------------------------------------------------
echo
echo "================ MariaDB upgrade rehearsal ================"
echo "from      $old_version   ($FROM_IMAGE)"
echo "to        $new_version   ($TO_IMAGE)"
echo "app       $APP_IMAGE"
echo "data      $tables tables, $rows rows; dump $(human "$dump_bytes") gzipped, $(human "$raw_bytes") SQL"
echo "timings   restore ${T[restore]}s | slow shutdown ${T[shutdown]}s | start+upgrade ${T[upgrade]}s | migrate ${T[migrate]}s | backup ${T[backup]:-?}s | rollback restore ${T[rollback]:-?}s"
echo "-----------------------------------------------------------"
printf '%s\n' "${results[@]}"
echo "-----------------------------------------------------------"
if ((failed)); then
	echo "RESULT: FAIL -- do not schedule the upgrade until every line above passes"
	exit 1
fi
echo "RESULT: PASS"
