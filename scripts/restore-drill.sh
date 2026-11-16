#!/usr/bin/env bash
# Restore drill: prove that a Vectora backup restores, without going near the
# stack it came from.
#
#   scripts/restore-drill.sh [options] <source>
#
# <source> is one of
#   a directory        holding a backup set (<stamp>-*-database.sql.gz and the
#                      files tars beside it); the newest set is used
#   a *-database.sql.gz the set with that file's stamp, from its directory
#   offsite            the bucket the `backup-offsite` service writes to, read
#                      with the settings in --env-file, and decrypted when
#                      OFFSITE_CRYPT_PASSWORD is set there
#
# Options
#   --env-file FILE           deploy/.env to read the image, the bucket and the
#                             passphrase from (default: deploy/.env beside
#                             this script). Read with sed, never sourced.
#   --image IMAGE:TAG         app image (default: VECTORA_IMAGE:VECTORA_TAG
#                             from the env file)
#   --stamp YYYYMMDD_HHMMSS   which backup set (default: the newest)
#   --monthly                 with `offsite`: read the monthly/ tier
#   --encryption-key-file F   a file holding the site's encryption_key, to
#                             prove the stored secrets decrypt (taken from
#                             the set's site_config_backup.json when present)
#   --project NAME            compose project name (default: vbk-drill-<time>)
#   --record FILE             append a one-line result to FILE
#   --allow-empty             pass even if the backup holds no deals or leads
#
# What it does: copies the set into a private temp directory, starts a
# throwaway compose project (db, redis x2, one app container) on an
# internal-only network with no published ports, creates a fresh site,
# restores the database and both file archives into it, runs migrate,
# counts rows in a few doctypes, checks the files arrived, checks the stored
# secrets decrypt, starts the app server and asks /api/method/ping. Then a
# pass/fail table with timings, and the exit status says which.
#
# What it never does: touch a compose project called vectora (or any project
# whose containers would be named vectora-*), reuse a project that already
# has containers, or write to the bucket -- the remote is only ever the
# SOURCE of an rclone lsf/copy, and a read-only key is enough (README.md,
# "Restore drill"). Everything it starts is removed with `down -v` on exit,
# and the temp directory with the decrypted backup goes with it.
set -euo pipefail

die() {
	echo "restore-drill: $*" >&2
	exit 2
}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deploy_dir="$here/../deploy"
env_file="$deploy_dir/.env"
image=""
stamp=""
tier=daily
key_file=""
project="vbk-drill-$(date +%Y%m%d%H%M%S)"
record=""
allow_empty=0
source_arg=""

while [ $# -gt 0 ]; do
	case "$1" in
	--env-file) env_file="${2:?--env-file needs a path}"; shift 2 ;;
	--image) image="${2:?--image needs IMAGE:TAG}"; shift 2 ;;
	--stamp) stamp="${2:?--stamp needs YYYYMMDD_HHMMSS}"; shift 2 ;;
	--monthly) tier=monthly; shift ;;
	--encryption-key-file) key_file="${2:?--encryption-key-file needs a path}"; shift 2 ;;
	--project) project="${2:?--project needs a name}"; shift 2 ;;
	--record) record="${2:?--record needs a path}"; shift 2 ;;
	--allow-empty) allow_empty=1; shift ;;
	-h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
	-*) die "unknown option $1 (see --help)" ;;
	*) [ -z "$source_arg" ] || die "one source only"; source_arg="$1"; shift ;;
	esac
done
[ -n "$source_arg" ] || die "no source given (see --help)"

# --- The guard: never the production project --------------------------------
# Compose names containers <project>-<service>-<n>, so refusing every project
# that starts with "vectora" is what keeps a vectora-* container out of reach,
# including `down -v`, which would take production's database volume with it.
lower="$(printf '%s' "$project" | tr '[:upper:]' '[:lower:]')"
case "$lower" in
vectora*)
	die "refusing: '$project' is, or could be, the production compose project. Use a throwaway name." ;;
esac
case "$project" in
*[!a-z0-9_-]* | [!a-z0-9]*) die "refusing: '$project' is not a valid compose project name (lowercase letters, digits, - and _)" ;;
esac
case "$stamp" in
"" | [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
*) die "--stamp must look like 20261116_020001" ;;
esac
# Whatever the caller's shell says, this script names its own project and file.
unset COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES

command -v docker >/dev/null || die "docker is not on PATH"
docker compose version >/dev/null 2>&1 || die "docker compose (v2) is not available"
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]; then
	die "refusing: compose project '$project' already has containers; a drill only runs in a project it creates"
fi

# --- Settings, read from the env file without executing it -----------------
env_get() {
	local v="${!1:-}"
	if [ -z "$v" ] && [ -f "$env_file" ]; then
		v="$(sed -n "s/^$1=//p" "$env_file" | tail -n 1)"
		v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
	fi
	printf '%s' "$v"
}
if [ -z "$image" ]; then
	img="$(env_get VECTORA_IMAGE)"
	tag="$(env_get VECTORA_TAG)"
	[ -n "$tag" ] || die "no --image given and no VECTORA_TAG in $env_file"
	image="${img:-ghcr.io/absolute-insight/simcrm}:$tag"
fi
# The database and redis the drill runs on are the ones production pins.
pin() { sed -n "s|^ *image: \($1[^ ]*\) *$|\1|p" "$deploy_dir/docker-compose.yml" | head -n 1; }
# The database is whatever production runs: DB_IMAGE from the env file (the
# MariaDB upgrade switch), else the default the compose file pins. A drill on a
# different engine than production's would prove the wrong restore.
db_image="$(env_get DB_IMAGE)"
if [ -z "$db_image" ]; then
	db_image="$(sed -n 's|^ *image: \${DB_IMAGE:-\(mariadb:[^}]*\)} *$|\1|p' "$deploy_dir/docker-compose.yml" | head -n 1)"
fi
[ -n "$db_image" ] || db_image="$(pin mariadb:)"
redis_image="$(pin redis:)"
rclone_image="$(pin rclone/rclone:)"
[ -n "$db_image" ] && [ -n "$redis_image" ] || die "cannot read the mariadb/redis pins from $deploy_dir/docker-compose.yml"

# --- Workspace ----------------------------------------------------------------
umask 077
work="$(mktemp -d "${TMPDIR:-/tmp}/vbk-drill.XXXXXX")"
in="$work/in"
mkdir -p "$in" "$work/logs"
compose=(docker compose -p "$project" -f "$work/compose.yml")
started=0

cleanup() {
	local rc=$?
	if [ "$started" = 1 ]; then
		# Belt and braces: never `down -v` anything that is named like production.
		if "${compose[@]}" ps -a --format '{{.Name}}' 2>/dev/null | grep -q '^vectora-'; then
			echo "restore-drill: a container in '$project' is named vectora-*; NOT tearing down -- remove it by hand" >&2
		else
			"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 \
				|| echo "restore-drill: teardown of '$project' failed; remove it with: docker compose -p $project down -v" >&2
		fi
	fi
	rm -rf "$work" 2>/dev/null || true
	exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# --- The step table -------------------------------------------------------------
names=()
results=()
secs=()
notes=()
failed=0
step() {
	# step <label> <command...>: runs it unless something already failed.
	local label="$1"; shift
	local n=${#names[@]}
	names+=("$label")
	if [ "$failed" = 1 ]; then
		results+=("skipped"); secs+=("-"); notes+=("")
		return 0
	fi
	echo "== $label" >&2
	local t0=$SECONDS
	if "$@" >"$work/logs/$n.log" 2>&1; then
		results+=("ok")
	else
		results+=("FAIL")
		failed=1
		echo "-- $label failed; last lines of its output:" >&2
		tail -n 25 "$work/logs/$n.log" >&2 || true
	fi
	secs+=("$((SECONDS - t0))")
	notes+=("${note:-}")
	note=""
}
note=""

# --- 1. Fetch -------------------------------------------------------------------
fetched_from=""
pick_stamp() {
	# newest (or the requested) stamp among the database dumps listed on stdin
	sed -n 's/^\([0-9]\{8\}_[0-9]\{6\}\)-.*-database\.sql\.gz$/\1/p' \
		| { if [ -n "$stamp" ]; then grep -x -- "$stamp"; else sort | tail -n 1; fi; }
}

fetch_local() {
	local dir="$source_arg"
	if [ -f "$source_arg" ]; then
		dir="$(dirname "$source_arg")"
		stamp="$(basename "$source_arg" | cut -c1-15)"
	fi
	[ -d "$dir" ] || { echo "no such file or directory: $source_arg"; return 1; }
	stamp="$(ls "$dir" | pick_stamp)" || true
	[ -n "$stamp" ] || { echo "no complete *-database.sql.gz backup set in $dir"; return 1; }
	cp -- "$dir/$stamp"-* "$in/" || return 1
	fetched_from="$dir"
}

fetch_offsite() {
	[ -n "$rclone_image" ] || { echo "cannot read the rclone pin from docker-compose.yml"; return 1; }
	local target site pass salt src
	target="$(env_get BACKUP_TARGET)"
	target="${target:-offsite:vecmbp}"
	target="${target%/}"
	site="$(env_get SITE_NAME)"
	[ -n "$site" ] || { echo "no SITE_NAME in $env_file"; return 1; }
	# A read-only key for the drill is better than the server's; either works.
	export RCLONE_CONFIG_OFFSITE_TYPE RCLONE_CONFIG_OFFSITE_ACCOUNT RCLONE_CONFIG_OFFSITE_KEY
	RCLONE_CONFIG_OFFSITE_TYPE="$(env_get OFFSITE_TYPE)"
	RCLONE_CONFIG_OFFSITE_TYPE="${RCLONE_CONFIG_OFFSITE_TYPE:-b2}"
	RCLONE_CONFIG_OFFSITE_ACCOUNT="${DRILL_B2_ACCOUNT_ID:-$(env_get B2_ACCOUNT_ID)}"
	RCLONE_CONFIG_OFFSITE_KEY="${DRILL_B2_APPLICATION_KEY:-$(env_get B2_APPLICATION_KEY)}"
	local prefix="$target"
	[ "$tier" = monthly ] && prefix="$target/monthly"
	pass="$(env_get OFFSITE_CRYPT_PASSWORD)"
	local envs=(-e RCLONE_CONFIG_OFFSITE_TYPE -e RCLONE_CONFIG_OFFSITE_ACCOUNT -e RCLONE_CONFIG_OFFSITE_KEY)
	if [ -n "$pass" ]; then
		export RCLONE_CONFIG_DRILLCRYPT_TYPE=crypt
		export RCLONE_CONFIG_DRILLCRYPT_REMOTE="$prefix/$site.crypt"
		export RCLONE_CONFIG_DRILLCRYPT_FILENAME_ENCRYPTION=off
		export RCLONE_CONFIG_DRILLCRYPT_DIRECTORY_NAME_ENCRYPTION=false
		RCLONE_CONFIG_DRILLCRYPT_PASSWORD="$(printf '%s' "$pass" | docker run --rm -i --network none "$rclone_image" obscure -)" || return 1
		export RCLONE_CONFIG_DRILLCRYPT_PASSWORD
		envs+=(-e RCLONE_CONFIG_DRILLCRYPT_TYPE -e RCLONE_CONFIG_DRILLCRYPT_REMOTE -e RCLONE_CONFIG_DRILLCRYPT_PASSWORD
			-e RCLONE_CONFIG_DRILLCRYPT_FILENAME_ENCRYPTION -e RCLONE_CONFIG_DRILLCRYPT_DIRECTORY_NAME_ENCRYPTION)
		salt="$(env_get OFFSITE_CRYPT_SALT)"
		if [ -n "$salt" ]; then
			RCLONE_CONFIG_DRILLCRYPT_PASSWORD2="$(printf '%s' "$salt" | docker run --rm -i --network none "$rclone_image" obscure -)" || return 1
			export RCLONE_CONFIG_DRILLCRYPT_PASSWORD2
			envs+=(-e RCLONE_CONFIG_DRILLCRYPT_PASSWORD2)
		fi
		src="drillcrypt:"
	else
		src="$prefix/$site"
	fi
	# The only two rclone commands this script runs. The remote is the source
	# of both; the destination is the private temp directory.
	local listing
	listing="$(docker run --rm "${envs[@]}" "$rclone_image" lsf "$src" --files-only --include "*-database*.sql.gz")" || return 1
	stamp="$(printf '%s\n' "$listing" | pick_stamp)" || true
	[ -n "$stamp" ] || { echo "no backup set${stamp:+ $stamp} at $src"; return 1; }
	docker run --rm "${envs[@]}" -v "$in:/out" --user "$(id -u):$(id -g)" "$rclone_image" \
		copy "$src" /out --filter "+ ${stamp}-*" --filter "- *" --stats 0 || return 1
	fetched_from="$src"
	[ -z "$pass" ] || fetched_from="$prefix/$site.crypt (decrypted)"
}

if [ "$source_arg" = offsite ]; then
	step "fetch the backup set from the bucket" fetch_offsite
else
	step "copy the backup set" fetch_local
fi

db_file="" public_tar="" private_tar="" conf_file=""
classify() {
	local f
	for f in "$in"/*; do
		case "$(basename "$f")" in
		*-database-enc.sql.gz | *-enc.*) echo "frappe-encrypted backups (encrypt_backup) are not supported by this drill: $f"; return 1 ;;
		*-partial-database.sql.gz) ;;
		*-database.sql.gz) db_file="$f" ;;
		*-private-files.tar | *-private-files.tgz) private_tar="$f" ;;
		*-files.tar | *-files.tgz) public_tar="$f" ;;
		*-site_config_backup.json) conf_file="$f" ;;
		esac
	done
	[ -n "$db_file" ] || { echo "the set has no database dump"; return 1; }
	# Readable by the container's user through the bind mount. The directory
	# above stays 0700, so nobody else on the host can reach them.
	chmod 0755 "$in" && chmod 0644 "$in"/* || return 1
	note="$stamp: db"
	[ -z "$public_tar" ] || note="$note +public"
	[ -z "$private_tar" ] || note="$note +private"
	[ -z "$conf_file" ] || note="$note +site_config"
	return 0
}
step "check the backup set" classify

key=""
if [ -n "$key_file" ]; then
	key="$(tr -d ' \n\r' <"$key_file")"
elif [ -n "$conf_file" ]; then
	key="$(sed -n 's/.*"encryption_key": *"\([^"]*\)".*/\1/p' "$conf_file" | head -n 1)"
fi

# --- 2. The throwaway stack ---------------------------------------------------------
site=drill.localhost
DRILL_DB_ROOT_PASSWORD="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
DRILL_ADMIN_PASSWORD="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
DRILL_ENCRYPTION_KEY="$key"
DRILL_IMAGE="$image"
export DRILL_DB_ROOT_PASSWORD DRILL_ADMIN_PASSWORD DRILL_ENCRYPTION_KEY DRILL_IMAGE

cat >"$work/compose.yml" <<EOF
# Generated by scripts/restore-drill.sh; deleted when it exits.
name: $project
x-app: &app
  image: \${DRILL_IMAGE}
  volumes:
    - sites:/home/frappe/frappe-bench/sites
    - ./in:/drill-in:ro
  networks: [drill]
services:
  db:
    image: $db_image
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
    environment:
      MYSQL_ROOT_PASSWORD: \${DRILL_DB_ROOT_PASSWORD}
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      start_period: 60s
      interval: 5s
      timeout: 5s
      retries: 60
    volumes:
      - db-data:/var/lib/mysql
    networks: [drill]
  redis-cache:
    image: $redis_image
    networks: [drill]
  redis-queue:
    image: $redis_image
    networks: [drill]
  backend:
    <<: *app
    depends_on:
      db:
        condition: service_healthy
      redis-cache:
        condition: service_started
      redis-queue:
        condition: service_started
# internal: the restored data never gets a route out -- no mail, no ERP call,
# no webhook can leave this network, whatever a migrate hook tries.
networks:
  drill:
    internal: true
volumes:
  sites:
  db-data:
EOF

app() { "${compose[@]}" run --rm -T --no-deps -e DRILL_DB_ROOT_PASSWORD -e DRILL_ADMIN_PASSWORD -e DRILL_ENCRYPTION_KEY backend bash -c "$1"; }

start_stack() {
	started=1
	"${compose[@]}" up -d --wait db redis-cache redis-queue
}
step "start the throwaway stack" start_stack

new_site() {
	app "set -e
		bench set-config -g db_host db
		bench set-config -gp db_port 3306
		bench set-config -g redis_cache redis://redis-cache:6379
		bench set-config -g redis_queue redis://redis-queue:6379
		bench set-config -g redis_socketio redis://redis-queue:6379
		ls -1 apps > sites/apps.txt
		bench new-site $site --mariadb-user-host-login-scope='%' \
			--db-root-password \"\$DRILL_DB_ROOT_PASSWORD\" --admin-password \"\$DRILL_ADMIN_PASSWORD\"
		bench --site $site set-config -p mute_emails 1
		bench --site $site set-config -p pause_scheduler 1"
}
step "create a fresh site" new_site

restore() {
	local files=""
	[ -n "$public_tar" ] && files="$files --with-public-files /drill-in/$(basename "$public_tar")"
	[ -n "$private_tar" ] && files="$files --with-private-files /drill-in/$(basename "$private_tar")"
	# The key goes in BEFORE the restore, as in README.md's new-host restore:
	# nothing is ever read with the wrong one. Written to the JSON directly so
	# it is never in a process's argv.
	app "set -e
		if [ -n \"\$DRILL_ENCRYPTION_KEY\" ]; then
			env/bin/python -c 'import json, os
p = \"sites/$site/site_config.json\"
c = json.load(open(p))
c[\"encryption_key\"] = os.environ[\"DRILL_ENCRYPTION_KEY\"]
json.dump(c, open(p, \"w\"), indent=1)'
		fi
		bench --site $site restore --force --db-root-username root \
			--db-root-password \"\$DRILL_DB_ROOT_PASSWORD\" /drill-in/$(basename "$db_file")$files"
}
step "restore the database and files" restore

step "bench migrate" app "bench --site $site migrate"

count_rows() {
	local dt out summary="" total=0
	for dt in "CRM Deal" "CRM Lead" "CRM Organization" "Contact" "User" "File"; do
		# `bench execute` prints a return value only when it is truthy, so a
		# count of 0 is an empty line -- with exit status 0, which is what
		# tells it from a failure.
		# The image's entrypoint talks on stdout too, hence the marker.
		out="$(app "out=\$(bench --site $site execute frappe.db.count --args \"['$dt']\") || exit 1; echo \"DRILLCOUNT=\$out\"" | tr -d '\r')" || {
			echo "counting $dt failed: $out"
			return 1
		}
		out="$(printf '%s\n' "$out" | sed -n 's/^DRILLCOUNT=//p' | tail -n 1)"
		out="${out:-0}"
		case "$out" in *[!0-9]*) echo "count of $dt did not come back as a number: $out"; return 1 ;; esac
		summary="$summary $dt=$out"
		case "$dt" in "CRM Deal" | "CRM Lead") total=$((total + out)) ;; esac
	done
	note="${summary# }"
	echo "$note"
	if [ "$total" = 0 ] && [ "$allow_empty" != 1 ]; then
		echo "the restored site holds no deals and no leads; a backup of an empty CRM proves little (--allow-empty to accept)"
		return 1
	fi
}
step "row counts" count_rows

files_arrived() {
	local want_pub=0 want_priv=0 got
	tarcount() { case "$1" in *.tgz) tar -tzf "$1" ;; *) tar -tf "$1" ;; esac | grep -vc '/$' || true; }
	[ -n "$public_tar" ] && want_pub="$(tarcount "$public_tar")"
	[ -n "$private_tar" ] && want_priv="$(tarcount "$private_tar")"
	got="$(app "echo DRILLPUB=\$(find sites/$site/public/files -type f | wc -l); echo DRILLPRIV=\$(find sites/$site/private/files -type f | wc -l)" | tr -d '\r ')"
	local got_pub got_priv
	got_pub="$(printf '%s\n' "$got" | sed -n 's/^DRILLPUB=//p')"
	got_priv="$(printf '%s\n' "$got" | sed -n 's/^DRILLPRIV=//p')"
	note="public $got_pub/$want_pub, private $got_priv/$want_priv"
	echo "$note"
	[ "${got_pub:-0}" -ge "$want_pub" ] && [ "${got_priv:-0}" -ge "$want_priv" ]
}
step "files restored" files_arrived

secrets_decrypt() {
	local out total bad
	out="$(app "cd sites && ../env/bin/python -c '
import frappe
frappe.init(site=\"$site\", sites_path=\".\")
frappe.connect()
from frappe.utils.password import decrypt
rows = frappe.db.sql(\"select password from \`__Auth\` where encrypted = 1\")
bad = 0
for (p,) in rows:
    try:
        decrypt(p)
    except Exception:
        bad += 1
print(\"DRILL\", len(rows), bad)
'" | tr -d '\r' | sed -n 's/^DRILL //p' | tail -n 1)"
	total="${out% *}"
	bad="${out#* }"
	case "$total$bad" in "" | *[!0-9]*) echo "the decryption check did not run: $out"; return 1 ;; esac
	if [ -z "$key" ]; then
		note="NOT VERIFIED: no encryption_key supplied ($total stored secrets)"
		echo "$note"
		return 0
	fi
	note="$((total - bad)) of $total stored secrets decrypt"
	echo "$note"
	[ "$bad" = 0 ]
}
step "stored secrets decrypt with the key" secrets_decrypt

ping_site() {
	"${compose[@]}" up -d --no-deps backend || return 1
	local i out
	for i in $(seq 1 60); do
		out="$("${compose[@]}" exec -T backend curl -fsS -H "Host: $site" http://localhost:8000/api/method/ping 2>/dev/null)" || true
		case "$out" in *pong*) note="$out"; echo "$out"; return 0 ;; esac
		sleep 3
	done
	echo "no pong after 180s; last answer: $out"
	"${compose[@]}" logs --tail 40 backend
	return 1
}
step "GET /api/method/ping" ping_site

# --- 3. Report -----------------------------------------------------------------------
total=0
for s in "${secs[@]}"; do [ "$s" = "-" ] || total=$((total + s)); done
echo
echo "Restore drill  $(date -Is)"
echo "  project  $project (removed on exit)"
echo "  image    $image"
echo "  backup   ${stamp:-?} from ${fetched_from:-$source_arg}${key:+ (with encryption_key)}"
echo
printf '  %-42s %-8s %6s  %s\n' "step" "result" "secs" "detail"
for i in "${!names[@]}"; do
	printf '  %-42s %-8s %6s  %s\n' "${names[$i]}" "${results[$i]}" "${secs[$i]}" "${notes[$i]}"
done
echo
if [ "$failed" = 0 ]; then verdict=PASS; else verdict=FAIL; fi
echo "RESULT: $verdict in ${total}s"
if [ -n "$record" ]; then
	detail=""
	for i in "${!names[@]}"; do [ -z "${notes[$i]}" ] || detail="$detail; ${notes[$i]}"; done
	printf '%s\t%s\t%ss\t%s\t%s\t%s\t%s\n' "$(date -Is)" "$verdict" "$total" "${stamp:-?}" "${fetched_from:-$source_arg}" "$image" "${detail#; }" >>"$record"
	echo "recorded in $record"
fi
[ "$failed" = 0 ]
