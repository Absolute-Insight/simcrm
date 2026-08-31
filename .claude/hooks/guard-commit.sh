#!/usr/bin/env bash
# PreToolUse guard for Bash git-commit calls.
#
# .pre-commit-config.yaml runs no-commit-to-branch --branch develop, and
# docs/RELEASING.md makes main the release branch (a push to it cuts a
# release). Committing directly to either is rejected by pre-commit anyway --
# catching it here saves the round trip and says what to do instead.
set -uo pipefail

cmd=$(cat | jq -r '.tool_input.command // empty')
[[ "$cmd" != *"git commit"* ]] && exit 0

branch=$(git -C "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
case "$branch" in
  develop|main)
    jq -nc --arg b "$branch" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",
        permissionDecisionReason:("On branch \($b). pre-commit'"'"'s no-commit-to-branch rejects commits to develop, and main is the release branch -- a push there cuts a release (docs/RELEASING.md). Branch first: git switch -c feat/<name>")}}'
    ;;
esac
exit 0
