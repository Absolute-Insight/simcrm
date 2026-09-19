#!/usr/bin/env bash
# PreToolUse guard for Bash `docker compose` pull/up/create calls.
#
# deploy/docker-compose.yml takes its tag from ${VECTORA_TAG} in deploy/.env,
# but deploy/docker-compose.override.yml is loaded automatically and pins every
# app service to a literal tag. When the two disagree, the override wins and
# .env is decoration: editing VECTORA_TAG and running `up -d` changes nothing,
# and `pull` fetches a version nobody asked for.
#
# That has bitten this stack repeatedly -- deploy/ currently holds eleven
# docker-compose.override.yml.bak-v3.14.* files, one per time the pin was
# hand-edited. The standing rule is "run `docker compose config --images`
# before every pull"; this makes the resolved answer appear at the moment of
# the decision instead of depending on remembering.
#
# Deliberately quiet when there is nothing new to say, in two stages.
#
# 1. If the resolved tag matches VECTORA_TAG there is no trap and nothing is
#    reported.
#
# 2. A *mismatch on its own is not an error here*, which is why this does not
#    simply warn whenever the two differ. The repo holds two contradictory
#    accounts of what .env means:
#
#      - deploy/README.md ("Upgrading"): .env pins the release and you bump it
#        to upgrade, "so the file records what is running".
#      - the override file's own header: .env is meant to stay one release
#        behind, naming the version you roll back to by deleting the override.
#
#    That header is stale -- it narrates v3.8.1 while the file it sits in pins
#    v3.15.0 -- and README's "Rolling back" section contradicts its premise
#    anyway (reverting the image is not a rollback once migrate has run). But
#    until somebody settles it, a standing difference between the two files is
#    the normal condition on this stack, and a guard that fires on the normal
#    condition is one you learn to click through. That is worse than no guard:
#    it spends the interruption budget on the case that is fine.
#
#    So the trigger is a *change*. The (resolved, declared) pair is recorded in
#    .claude/hooks/.compose-ack once reported; while it stays the same this is
#    silent, and it speaks again the moment either side moves -- which is
#    exactly when someone has edited .env expecting it to take effect, or a new
#    release has shifted the ground. Delete that file to hear the current state
#    again.
#
# `config --images` prints image references and nothing else, so this never
# renders the passwords that live beside VECTORA_TAG in deploy/.env. The one
# value read out of that file is VECTORA_TAG itself, and only to compare it.
#
# Degrades silently: no docker, no compose files, an unparseable command, or a
# stack with no simcrm image in it (the devcontainer stack, say) is exit 0.
# Skips are logged to .claude/hooks/compose.log so a mute guard stays
# diagnosable.
#
# Registered in settings.json WITHOUT an `if:` filter, unlike guard-commit.sh.
# A `Bash(docker compose:*)` prefix match would miss `cd deploy && docker
# compose pull`, which is the idiom deploy/README.md and the deploy skill both
# use -- i.e. it would skip exactly the calls worth checking. The command test
# below does the filtering instead, before anything expensive runs.
set -uo pipefail

input=$(cat)

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
log="$root/.claude/hooks/compose.log"
note() { printf '%s  %s\n' "$(date -Is)" "$1" >> "$log"; }

command -v jq >/dev/null 2>&1 || exit 0
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
[[ -z "$cmd" ]] && exit 0

# Only compose invocations, and only the three subcommands that resolve an
# image and act on it. `config`, `ps`, `logs`, `down` need no warning.
[[ "$cmd" == *"docker compose"* || "$cmd" == *"docker-compose"* ]] || exit 0
[[ "$cmd" =~ (^|[[:space:]])(pull|up|create)([[:space:]]|$) ]] || exit 0

cwd=$(jq -r '.cwd // empty' <<<"$input")
[[ -z "$cwd" || ! -d "$cwd" ]] && cwd="$root"

# `cd deploy && docker compose ...` is the usual shape, so honour a leading cd.
dir="$cwd"
if [[ "$cmd" =~ ^[[:space:]]*cd[[:space:]]+([^[:space:]\&\;]+) ]]; then
  cand="${BASH_REMATCH[1]//\"/}"; cand="${cand//\'/}"
  [[ "$cand" != /* ]] && cand="$cwd/$cand"
  [[ -d "$cand" ]] && dir="$cand"
fi

# Carry through only the flags that change which files/env get resolved. Any
# other token before the subcommand is ignored rather than guessed at.
globals=()
subcmd_re='^(pull|up|create)$'
read -ra toks <<<"$cmd"
i=0; seen_compose=0
while (( i < ${#toks[@]} )); do
  t="${toks[$i]}"
  if [[ $seen_compose -eq 0 ]]; then
    [[ "$t" == "compose" || "$t" == "docker-compose" ]] && seen_compose=1
    ((i++)); continue
  fi
  [[ "$t" =~ $subcmd_re ]] && break
  case "$t" in
    -f|--file|-p|--project-name|--env-file|--project-directory)
      globals+=("$t" "${toks[$((i+1))]:-}"); ((i+=2)); continue ;;
    -f=*|--file=*|--env-file=*|--project-directory=*|--project-name=*)
      globals+=("$t"); ((i++)); continue ;;
  esac
  ((i++))
done

command -v docker >/dev/null 2>&1 || { note "skip:no-docker"; exit 0; }

images=$(cd "$dir" 2>/dev/null && docker compose "${globals[@]}" config --images 2>/dev/null) || {
  note "skip:config-failed dir=$dir"; exit 0; }
[[ -z "$images" ]] && { note "skip:no-images dir=$dir"; exit 0; }

# Only this app's image is governed by VECTORA_TAG; mariadb/redis/ollama pins
# are irrelevant here.
app=$(grep -E 'simcrm' <<<"$images" | sort -u)
[[ -z "$app" ]] && exit 0
resolved=$(sed 's/.*://' <<<"$app" | sort -u)

# VECTORA_TAG as the env file declares it. --env-file wins if one was passed.
envfile="$dir/.env"
for ((j=0; j<${#globals[@]}; j++)); do
  [[ "${globals[$j]}" == "--env-file" ]] && envfile="${globals[$((j+1))]}"
  [[ "${globals[$j]}" == --env-file=* ]] && envfile="${globals[$j]#*=}"
done
[[ "$envfile" != /* ]] && envfile="$dir/$envfile"
declared=""
[[ -r "$envfile" ]] && declared=$(grep -m1 -E '^[[:space:]]*VECTORA_TAG=' "$envfile" 2>/dev/null |
  sed 's/^[^=]*=//; s/^["'\'']//; s/["'\'']$//; s/[[:space:]]*$//')

# One tag, and it is the declared one: nothing to warn about.
if [[ -n "$declared" && "$(wc -l <<<"$resolved")" -eq 1 && "$resolved" == "$declared" ]]; then
  exit 0
fi

# Mismatch. Report it only if it is not the one already reported -- see the
# header: a standing difference is the normal condition here, a change in it is
# the signal. Keyed on the env file too, so a localhost rehearsal and the real
# stack do not silence each other.
ack="$root/.claude/hooks/.compose-ack"
state="$envfile|$(paste -sd, <<<"$resolved")|$declared"
[[ -f "$ack" ]] && grep -qxF "$state" "$ack" && exit 0
printf '%s\n' "$state" >> "$ack"
# Keep it small; only the recent distinct states are worth remembering.
tail -n 20 "$ack" > "$ack.tmp" 2>/dev/null && mv "$ack.tmp" "$ack"

action=$(grep -oE '(^|[[:space:]])(pull|up|create)([[:space:]]|$)' <<<"$cmd" | head -1 | tr -d ' ')
reason="Resolved image tag(s) for this stack: $(paste -sd', ' <<<"$resolved")."
if [[ -n "$declared" ]]; then
  reason+=" VECTORA_TAG in ${envfile#"$root"/} says '$declared'."
  reason+=" The override file pins the tag and wins over .env, so this '$action' acts on $(paste -sd', ' <<<"$resolved"), NOT $declared."
  reason+=" If you are upgrading, edit deploy/docker-compose.override.yml -- editing .env alone will not do it."
  reason+=" (Reported once per distinct state; rm .claude/hooks/.compose-ack to see it again.)"
else
  reason+=" No VECTORA_TAG found in ${envfile#"$root"/} to compare against."
fi
reason+=" Full resolution: (cd ${dir#"$root"/} && docker compose config --images)"

jq -nc --arg r "$reason" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
exit 0
