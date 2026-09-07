#!/usr/bin/env bash
# PreToolUse guard for Bash git-commit calls.
#
# .pre-commit-config.yaml runs no-commit-to-branch --branch develop, and
# docs/RELEASING.md makes main the release branch (a push to it cuts a
# release). Committing directly to either is rejected by pre-commit anyway --
# catching it here saves the round trip and says what to do instead.
#
# The branch is read from the directory the command runs in (the hook input's
# cwd), not from the project root: feature work happens in .worktrees/<branch>
# while the main checkout sits on develop, and reading the root refused every
# commit made from a worktree.
set -uo pipefail

input=$(cat)
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
[[ "$cmd" != *"git commit"* ]] && exit 0

repo=$(jq -r '.cwd // empty' <<<"$input")
[[ -z "$repo" || ! -d "$repo" ]] && repo="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

branch=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
case "$branch" in
  develop|main)
    jq -nc --arg b "$branch" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",
        permissionDecisionReason:("On branch \($b). pre-commit'"'"'s no-commit-to-branch rejects commits to develop, and main is the release branch -- a push there cuts a release (docs/RELEASING.md). Branch first: git switch -c feat/<name>")}}'
    ;;
esac
exit 0
