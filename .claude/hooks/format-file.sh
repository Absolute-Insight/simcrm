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
set -uo pipefail

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')
[[ -z "$file" || ! -f "$file" ]] && exit 0

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
rel="${file#"$root"/}"
log="$root/.claude/hooks/format.log"

note() { printf '%s  %s  %s\n' "$(date -Is)" "$1" "$rel" >> "$log"; }

bin() {  # bin <name> -- repo-local first, then PATH
  local n=$1
  [[ -x "$root/frontend/node_modules/.bin/$n" ]] && { echo "$root/frontend/node_modules/.bin/$n"; return; }
  command -v "$n" 2>/dev/null
}

case "$rel" in
  crm/*.py|crm/**/*.py)
    if command -v ruff >/dev/null 2>&1; then
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
    p=$(bin prettier)
    if [[ -n "$p" ]]; then "$p" --write --ignore-unknown "$file" >/dev/null 2>&1; else note "skip:no-prettier"; fi
    case "$rel" in
      *.js|*.ts|*.vue)
        e=$(bin eslint)
        if [[ -n "$e" ]]; then (cd "$root/frontend" && "$e" --fix "$file" >/dev/null 2>&1); else note "skip:no-eslint"; fi
        ;;
    esac
    ;;
esac
exit 0
