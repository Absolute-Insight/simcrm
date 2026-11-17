#!/bin/bash
# Reload nginx when the backend or websocket container comes back on a new address.
#
# nginx resolves the names in frappe's `upstream` blocks (backend:8000,
# websocket:9000) once, when it loads its config, and nginx 1.22 has no way to
# look them up again. Docker gives a restarted container whatever address is free
# on the network at that moment, which is not always the one it had. 2026-11-17:
# an upgrade recreated redis-queue, websocket crash-looped on "EAI_AGAIN
# redis-queue" while it was gone, and came back on .9 while nginx still sent
# every socket.io request to .8 -- a 502 for every user, and realtime dead,
# until someone noticed and reloaded nginx by hand.
#
# So: look the names up every few seconds and reload nginx (graceful -- open
# connections finish on the old workers) when the addresses change.
#
# What it cannot do: nginx refuses a whole config in which any upstream name
# does not resolve, so while one container is down nothing can be reloaded --
# not even for the other one having moved. The reload happens as soon as both
# resolve again.
#
# Compose runs this as `bash upstream-watch.sh && exec nginx-entrypoint.sh`: it
# takes a baseline, puts the watch in the background and returns, so whatever
# nginx then resolves is at least as new as the baseline and any later move is
# seen. (Taken after nginx started, a move in between went unnoticed -- the
# rehearsal caught exactly that.)
set -u

interval=${WATCH_INTERVAL:-5}
pidfile=${NGINX_PID:-/run/nginx.pid}
# Touched every tick; frontend's healthcheck fails when it goes stale, so a dead
# watcher shows instead of quietly bringing the 502s back.
beat=${WATCH_BEAT:-/tmp/upstream-watch.beat}

hosts=()
for target in "${BACKEND:-}" "${SOCKETIO:-}"; do
	host=${target%%:*}
	# an IP needs no lookup
	if [[ -n $host && ! $host =~ ^[0-9.]+$ ]]; then hosts+=("$host"); fi
done
((${#hosts[@]})) || exit 0

log() { echo "[upstream-watch] $*"; }

# Every address of every host, sorted: Docker's DNS rotates the order when a
# service has more than one container, and only a changed set is a move.
addresses() {
	local host addrs out=""
	for host in "${hosts[@]}"; do
		addrs=$(getent ahostsv4 "$host" | awk '{ print $1 }' | sort -u | paste -sd, -)
		[[ -n $addrs ]] || return 1
		out+="$host=$addrs "
	done
	printf '%s' "${out% }"
}

# The pidfile alone is not proof: after a container restart it still names the
# old nginx, and that number may now belong to any process here.
nginx_up() {
	local pid
	pid=$(cat "$pidfile" 2>/dev/null) || return 1
	[[ $pid =~ ^[0-9]+$ ]] || return 1
	grep -q 'nginx: master' "/proc/$pid/cmdline" 2>/dev/null
}

until applied=$(addresses); do
	log "waiting for ${hosts[*]} to resolve before nginx starts"
	sleep "$interval"
done

watch() {
	local now
	while sleep "$interval"; do
		: >"$beat"
		if ! now=$(addresses); then
			# Something is down. Whatever it comes back on -- and whether a reload
			# sent just before it went managed to resolve it -- nginx gets a fresh
			# look once it is back. A spare graceful reload costs nothing.
			applied=""
			continue
		fi
		[[ $now != "$applied" ]] || continue
		nginx_up || continue
		# `nginx -s reload` exits 0 once the signal is sent, even when the master
		# then rejects the config; -t resolves the upstreams the same way first.
		if nginx -t -q 2>/dev/null && nginx -s reload; then
			log "${applied:-(after an outage)} -> $now: nginx reloaded"
			applied=$now
		fi
	done
}
watch &
