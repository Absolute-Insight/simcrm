#!/usr/bin/env bash
# PreToolUse guard for Edit|Write|NotebookEdit.
#
# Denies writes to files that something else owns: build output, the generated
# theme, secrets, lockfiles, and the version line semantic-release bumps.
# Editing any of these is silently undone by the next build/release, or -- for
# deploy/.env -- publishes a production password, so it is worth a hard stop
# rather than a review comment.
#
# Emits a PreToolUse permissionDecision. "deny" is not absolute: the user can
# still make the edit themselves, and can lift a rule by editing this file.
set -uo pipefail

payload=$(cat)
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[[ -z "$file" ]] && exit 0

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
rel="${file#"$root"/}"

deny() {
  jq -nc --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

case "$rel" in
  frontend/src/styles/vectora-theme.css)
    deny "vectora-theme.css is GENERATED. Edit frontend/scripts/generate_vectora_theme.py and re-run it -- it asserts every contrast floor before writing. A hand-edit here is overwritten by the next generator run and skips those assertions." ;;
  crm/www/crm.html|crm/public/frontend/*|crm/public/dist/*)
    deny "$rel is build output from 'yarn build' (vite -> copy-html-entry). Change the frontend source instead; this file is gitignored and regenerated." ;;
  .env|deploy/.env|deploy/.env.bak-*)
    deny "$rel holds DB_ROOT_PASSWORD / ADMIN_PASSWORD and is gitignored for that reason. Edit deploy/.env.example, or have the user edit the real .env by hand." ;;
  yarn.lock|frontend/yarn.lock|package-lock.json)
    deny "$rel is a lockfile -- let the package manager write it (yarn add / yarn install)." ;;
  crm/__init__.py)
    deny "crm/__init__.py holds __version__, which semantic-release bumps on a push to main (docs/RELEASING.md). Hand-bumping fights the automation." ;;
esac
exit 0
