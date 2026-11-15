#!/usr/bin/env bash
# Install semgrep and fetch frappe's rules, both at a pin.
#
#   bash .github/helper/install-semgrep.sh [<rules-dest>]     (default: frappe-semgrep-rules)
#
# Shared by linters.yml (the PR diff scan) and semgrep-full-scan.yml (the whole
# tree, on every push to develop and main), so the two cannot run different
# rules against the same code.
#
# Both used to float: `pip install --upgrade semgrep` and a `git clone` of the
# rules' default branch. That is a release hazard here, not a style point. The
# build guard in builds.yml refuses a commit with ANY failed check on it, and
# the full scan runs on the very commit a release is cut from -- so a rule
# added upstream turned that commit red and the release shipped without an
# image (v3.17.1, 2026-10-13; docs/RELEASING.md). Nothing in this repository
# had changed.
#
# So they move when somebody moves them:
#
#   1. set the two values below
#        gh api repos/frappe/semgrep-rules/commits/HEAD --jq .sha
#        https://pypi.org/project/semgrep/#history
#   2. open the PR -- linters.yml runs the diff scan with the new pin
#   3. before merging, run the full scan on the branch and fix or justify
#      what it finds:  gh workflow run semgrep-full-scan.yml --ref <branch>
#
# Not pinned, because the registry does not version it: the
# `r/python.lang.correctness` pack both workflows also pass to semgrep. It can
# still change under a release. If it does, the remedy is the one RELEASING.md
# gives for any red check on develop's HEAD.
set -euo pipefail

SEMGREP_VERSION="1.185.0" # what CI resolved on 2026-11-13, on python 3.14
SEMGREP_RULES_REPO="https://github.com/frappe/semgrep-rules.git"
SEMGREP_RULES_REF="81a6e3d47a328249e8ddf04c586e493dd5553002" # main, 2026-09-30

dest="${1:-frappe-semgrep-rules}"

pip install "semgrep==${SEMGREP_VERSION}"

rm -rf "$dest"
git init --quiet "$dest"
git -C "$dest" remote add origin "$SEMGREP_RULES_REPO"
# github.com serves an arbitrary commit to `fetch --depth 1`; the fallback
# covers a mirror that does not.
git -C "$dest" fetch --quiet --depth 1 origin "$SEMGREP_RULES_REF" ||
	git -C "$dest" fetch --quiet origin
git -C "$dest" checkout --quiet --detach "$SEMGREP_RULES_REF"

got="$(git -C "$dest" rev-parse HEAD)"
if [ "$got" != "$SEMGREP_RULES_REF" ]; then
	echo "::error::semgrep rules are at $got, expected $SEMGREP_RULES_REF" >&2
	exit 1
fi
echo "semgrep ${SEMGREP_VERSION}; frappe/semgrep-rules at ${SEMGREP_RULES_REF} in ${dest}"
