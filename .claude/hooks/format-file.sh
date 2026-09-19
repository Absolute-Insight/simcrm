#!/usr/bin/env bash
# PostToolUse formatter for Edit|Write.
#
# Mirrors .pre-commit-config.yaml so a commit is never bounced for formatting:
#   crm/**.py            -> ruff format + ruff check --fix
#   frontend/**.{js,ts,vue,css,scss,html,json} -> prettier --write, then eslint --fix
#
# The toolchain lives in the devcontainer, so each tool is used only where it
# is actually resolvable: repo-local node_modules/.bin first, then PATH. A
# missing tool is a skip, not an error -- but the skip is logged to
# .claude/hooks/format.log so "the hook did nothing" is diagnosable rather
# than invisible.
#
# ---------------------------------------------------------------------------
# Why prettier and ruff are pinned here and eslint is not
#
# Mirroring pre-commit means mirroring its *versions*, not just its tool names.
# Formatters are not version-stable: prettier changes its own output across
# minors, and `ruff format` tracks black's style as black itself moves. If this
# hook formats with a newer version than CI, it writes a file pre-commit then
# rewrites differently -- the exact "hooks modified a file, git add and
# re-commit" loop AGENTS.md describes, caused by the thing meant to prevent it.
#
# That was real, not hypothetical: the host resolved prettier 3.8.2 and ruff
# 0.16.5 from frontend/node_modules and PATH, against 3.2.5 and 0.8.1 in CI.
# Six prettier minors apart.
#
# So prettier and ruff run at the pinned version via a launcher that fetches it
# (npx / uv, both of which cache -- a warm run costs well under a second), and
# fall back to whatever is local only when the launcher is unavailable. A
# fallback is logged as `drift:` with both versions, because a silent fallback
# is the bug all over again.
#
# eslint is deliberately NOT pinned: pre-commit specifies `eslint@^10.0.2`, a
# caret range rather than an exact version, and a linter's --fix output does not
# drift across patch releases the way a formatter's does. Repo-local eslint that
# satisfies the range is the same check CI runs.
#
# SOURCE OF TRUTH for these two numbers is .pre-commit-config.yaml. When you
# bump a pin there, bump it here in the same commit -- and see
# `pre-commit-prettier-rev-is-not-a-prettier-version`: the mirror repo's `rev:`
# is not the prettier version, `additional_dependencies` is.
# ---------------------------------------------------------------------------
set -uo pipefail

PRETTIER_PIN=3.2.5   # .pre-commit-config.yaml -> mirrors-prettier additional_dependencies
RUFF_PIN=0.8.1       # .pre-commit-config.yaml -> ruff-pre-commit rev

payload=$(cat)

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
log="$root/.claude/hooks/format.log"
rel="?"

note() { printf '%s  %s  %s\n' "$(date -Is)" "$1" "$rel" >> "$log"; }

# jq parses the payload, so without it the hook cannot even learn which file it
# was called for. That is a total no-op and the most invisible failure this
# script has -- log it rather than exiting mute.
command -v jq >/dev/null 2>&1 || { note "skip:no-jq"; exit 0; }

file=$(printf '%s' "$payload" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')
[[ -z "$file" || ! -f "$file" ]] && exit 0
rel="${file#"$root"/}"

bin() {  # bin <name> -- repo-local first, then PATH
  local n=$1
  [[ -x "$root/frontend/node_modules/.bin/$n" ]] && { echo "$root/frontend/node_modules/.bin/$n"; return; }
  command -v "$n" 2>/dev/null
}

# Probe the pinned launcher once rather than inferring from a formatting run's
# exit code -- a file with a syntax error makes prettier exit non-zero too, and
# that must not be misread as "the pin is unavailable" and logged as drift.
have_pinned_prettier() {
  command -v npx >/dev/null 2>&1 || return 1
  [[ "$(npx --yes "prettier@$PRETTIER_PIN" --version 2>/dev/null)" == "$PRETTIER_PIN" ]]
}

have_pinned_ruff() {
  command -v uv >/dev/null 2>&1 || return 1
  [[ "$(uv tool run "ruff@$RUFF_PIN" --version 2>/dev/null)" == "ruff $RUFF_PIN" ]]
}

case "$rel" in
  crm/*.py|crm/**/*.py)
    if have_pinned_ruff; then
      uv tool run "ruff@$RUFF_PIN" format "$file" >/dev/null 2>&1
      uv tool run "ruff@$RUFF_PIN" check --fix "$file" >/dev/null 2>&1
    elif command -v ruff >/dev/null 2>&1; then
      note "drift:ruff:$(ruff --version 2>/dev/null | awk '{print $2}')!=$RUFF_PIN"
      ruff format "$file" >/dev/null 2>&1
      ruff check --fix "$file" >/dev/null 2>&1
    else
      note "skip:no-ruff"
    fi
    ;;
  frontend/*)
    case "$rel" in
      *.js|*.ts|*.vue|*.css|*.scss|*.html|*.json) ;;
      *) exit 0 ;;
    esac
    if have_pinned_prettier; then
      npx --yes "prettier@$PRETTIER_PIN" --write --ignore-unknown "$file" >/dev/null 2>&1
    else
      p=$(bin prettier)
      if [[ -n "$p" ]]; then
        note "drift:prettier:$("$p" --version 2>/dev/null)!=$PRETTIER_PIN"
        "$p" --write --ignore-unknown "$file" >/dev/null 2>&1
      else
        note "skip:no-prettier"
      fi
    fi
    case "$rel" in
      *.js|*.ts|*.vue)
        e=$(bin eslint)
        if [[ -n "$e" ]]; then (cd "$root/frontend" && "$e" --fix "$file" >/dev/null 2>&1); else note "skip:no-eslint"; fi
        ;;
    esac
    ;;
esac
exit 0
