#!/usr/bin/env bash
# Stop hook: refuse to end a turn on a red frontend suite.
#
# AGENTS.md says "all must pass before committing", but that is advisory text
# -- it is obeyed when it happens to be in context and skipped when it is not.
# This makes the frontend half of it deterministic: if the turn touched
# frontend source or tests, vitest runs before the turn is allowed to end.
#
# Scope is deliberately the frontend only. The python and e2e suites need the
# devcontainer bench and a browser respectively; gating on suites that cannot
# run from wherever the session happens to be would mean skipping constantly,
# and a gate that usually skips teaches you to ignore it. vitest is ~480 tests
# in well under a second with no services behind it, so it is the one suite
# cheap enough to run on every turn that earns it.
#
# Like format-file.sh, a missing toolchain is a skip, not an error -- on the
# host frontend/node_modules does not exist -- but the skip is logged to
# .claude/hooks/verify.log so "the gate did nothing" stays diagnosable.
#
# The block is bounded. Three consecutive blocks in one session and it stands
# down: a suite that is red for a reason unrelated to the turn (a half-finished
# refactor, a bad merge) must not be able to wedge the session.
set -uo pipefail

MAX_BLOCKS=3

payload=$(cat)

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
log="$root/.claude/hooks/verify.log"

# Feature work happens in .worktrees/<branch> while the main checkout sits on
# develop, so test the tree the session is actually in -- same reasoning as
# guard-commit.sh reading cwd rather than the project root.
cwd=$(jq -r '.cwd // empty' <<<"$payload")
[[ -z "$cwd" || ! -d "$cwd" ]] && cwd="$root"
repo=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || exit 0

session=$(jq -r '.session_id // "unknown"' <<<"$payload")
state="${TMPDIR:-/tmp}/.crm-verify-$(id -u)-${session}"

note() { printf '%s  %s\n' "$(date -Is)" "$1" >> "$log"; }

pass() { rm -f "$state"; exit 0; }

# Nothing in the frontend changed -> nothing for this gate to say. Covers
# staged and unstaged against HEAD, plus files that are new and untracked.
changed=$(git -C "$repo" diff --name-only HEAD -- frontend/src frontend/tests 2>/dev/null)
untracked=$(git -C "$repo" ls-files --others --exclude-standard -- frontend/src frontend/tests 2>/dev/null)
[[ -z "$changed$untracked" ]] && pass

[[ -d "$repo/frontend/node_modules" ]] || { note "skip:no-node_modules (host?)"; pass; }

if command -v yarn >/dev/null 2>&1; then
  runner=(yarn test:run)
elif [[ -x "$repo/frontend/node_modules/.bin/vitest" ]]; then
  runner=("$repo/frontend/node_modules/.bin/vitest" run)
else
  note "skip:no-yarn-or-vitest"; pass
fi

out=$(cd "$repo/frontend" && "${runner[@]}" 2>&1)
if [[ $? -eq 0 ]]; then
  note "pass:vitest"
  pass
fi

blocks=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 ))
printf '%s' "$blocks" > "$state"

if (( blocks > MAX_BLOCKS )); then
  note "stand-down:vitest still red after $MAX_BLOCKS blocks"
  pass
fi

note "block:vitest red ($blocks/$MAX_BLOCKS)"

# Hand back the failing tail, not the whole run: the summary and the first
# failures are what says which test broke, and the rest is per-file noise.
tail=$(printf '%s' "$out" | grep -E '(FAIL|✕|×|AssertionError|Tests +[0-9]|Test Files +[0-9])' | head -40)
[[ -z "$tail" ]] && tail=$(printf '%s' "$out" | tail -40)

jq -nc --arg t "$tail" --arg n "$blocks" --arg m "$MAX_BLOCKS" \
  '{decision:"block",
    reason:("The frontend suite is red and this turn changed frontend/src or frontend/tests. AGENTS.md: all tests must pass before committing. Fix the failures below (or say so explicitly if they are pre-existing and unrelated -- this gate stands down after \($m) blocks).\n\n" + $t)}'
exit 0
