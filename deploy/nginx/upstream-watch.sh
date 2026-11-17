#!/bin/bash
# Reload nginx when the backend or websocket container comes back on a new address.
#
# nginx resolves the names in frappe's `upstream` blocks (backend:8000,
# websocket:9000) once, when it starts, and nginx 1.22 has no way to look them up
# again. Docker gives a restarted container whatever address is free on the
# network at that moment, which is not always the one it had. 2026-11-17: an
# upgrade recreated redis-queue, websocket crash-looped on "EAI_AGAIN
# redis-queue" while it was gone, and came back on .9 while nginx still sent
# every socket.io request to .8 -- a 502 for every user, and realtime dead,
# until someone noticed and reloaded nginx by hand.
#
# So: look the names up every few seconds, and reload nginx (graceful -- open
# connections finish on the old workers) when an address changes. A name that
# does not resolve is a container that is down, not a change: nothing is
# reloaded until it is back, since a reload that cannot resolve an upstream
# fails anyway.
set -u

interval=${WATCH_INTERVAL:-5}
pidfile=${NGINX_PID:-/run/nginx.pid}

hosts=()
for target in "${BACKEND:-}" "${SOCKETIO:-}"; do
	host=${target%%:*}
	# an IP needs no lookup
	if [[ -n $host && ! $host =~ ^[0-9.]+$ ]]; then hosts+=("$host"); fi
done
((${#hosts[@]})) || exit 0

addresses() {
	local host addr out=""
	for host in "${hosts[@]}"; do
		addr=$(getent ahostsv4 "$host" | awk 'NR == 1 { print $1 }')
		[[ -n $addr ]] || return 1
		out+="$host=$addr "
	done
	printf '%s' "${out% }"
}

# Run before nginx starts (compose: `bash upstream-watch.sh && exec
# nginx-entrypoint.sh`): the baseline is taken first, so whatever nginx then
# resolves is at least as new, and any later change is seen. Taken after nginx
# started, a move in between went unnoticed -- the rehearsal caught exactly that.
# nginx cannot start until both names resolve either, so waiting here costs
# nothing.
until last=$(addresses); do sleep "$interval"; done

watch() {
	local now
	while sleep "$interval"; do
		now=$(addresses) || continue
		[[ $now != "$last" ]] || continue
		echo "[upstream-watch] $last -> $now: reloading nginx"
		# Fails until nginx is up (no pid yet): tried again on the next tick.
		if [[ -s $pidfile ]] && nginx -s reload; then last=$now; fi
	done
}
watch &
