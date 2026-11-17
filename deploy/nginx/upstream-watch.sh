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
# How long a reload has to show new workers before it counts as not taken.
reload_wait=${WATCH_RELOAD_WAIT:-10}

log() { echo "[upstream-watch] $*"; }

hosts=()
for target in "${BACKEND:-}" "${SOCKETIO:-}"; do
	host=${target%:*}
	# an address needs no lookup: IPv4, or IPv6 in brackets
	if [[ -n $host && ! $host =~ ^[0-9.]+$ && $host != \[* ]]; then hosts+=("$host"); fi
done

# Every address of every host, sorted: Docker's DNS rotates the order when a
# service has more than one container, and only a changed set is a move. Both
# families, as nginx resolves both.
addresses() {
	local host addrs out=""
	for host in "${hosts[@]}"; do
		addrs=$(getent ahosts "$host" | awk '{ print $1 }' | sort -u | paste -sd, -)
		[[ -n $addrs ]] || return 1
		out+="$host=$addrs "
	done
	printf '%s' "${out% }"
}

# The pidfile alone is not proof: after a container restart it still names the
# old nginx, and that number may now belong to any process here.
master_pid() {
	local pid
	pid=$(cat "$pidfile" 2>/dev/null) || return 1
	[[ $pid =~ ^[0-9]+$ ]] || return 1
	grep -q 'nginx: master' "/proc/$pid/cmdline" 2>/dev/null || return 1
	echo "$pid"
}

# The master's children that are workers. Builtins only: this runs every 0.1s
# while a reload is judged, and a fork per process adds up.
workers() {
	local dir pid ppid cmdline
	for dir in /proc/[0-9]*; do
		# field 4 is the parent; the comm of nginx (and of anything it forks) has
		# no spaces to shift it
		read -r pid _ _ ppid _ <"$dir/stat" 2>/dev/null || continue
		[[ $ppid == "$1" ]] || continue
		read -r -d '' cmdline <"$dir/cmdline" 2>/dev/null
		[[ $cmdline == *"worker process"* ]] && echo "$pid"
	done
}

last_refusal=""
reload_nginx() {
	local master before checked worker i
	master=$(master_pid) || return 1
	if ! checked=$(nginx -t -q 2>&1); then
		# once per distinct reason, not every tick
		[[ $checked == "$last_refusal" ]] || log "nginx -t refuses the config, not reloading: $checked"
		last_refusal=$checked
		return 1
	fi
	last_refusal=""
	before=" $(workers "$master" | tr '\n' ' ') "
	nginx -s reload || return 1
	# `nginx -s reload` exits 0 once the signal is sent, whether or not the master
	# then accepts the config -- a name that stopped resolving since -t is enough
	# to make it keep the old one. Only an accepted config starts new workers.
	for ((i = 0; i < reload_wait * 10; i++)); do
		sleep 0.1
		for worker in $(workers "$master"); do
			[[ $before == *" $worker "* ]] || return 0
		done
	done
	log "nginx did not take the reload (no new workers); trying again"
	return 1
}

watch_upstreams() {
	local now
	while sleep "$interval"; do
		: >"$beat"
		((${#hosts[@]})) || continue
		if ! now=$(addresses); then
			# Something is down. Whatever it comes back on, nginx gets a fresh look
			# once it is back: a spare graceful reload costs nothing.
			applied=""
			continue
		fi
		[[ $now != "$applied" ]] || continue
		if reload_nginx; then
			log "${applied:-(after an outage)} -> $now: nginx reloaded"
			applied=$now
		fi
	done
}

applied=""
if ((${#hosts[@]})); then
	until applied=$(addresses); do
		log "waiting for ${hosts[*]} to resolve before nginx starts"
		sleep "$interval"
	done
fi
watch_upstreams &
