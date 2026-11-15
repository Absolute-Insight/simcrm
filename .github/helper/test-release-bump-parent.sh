#!/usr/bin/env bash
# Checks for release-bump-parent.py, the content test behind the build guard's
# one exemption.
#
# The guard in builds.yml lets a release bump inherit its parent's checks. That
# is only safe if "is a bump" means "changes the version string and nothing
# else", and builds.yml runs only on a push to main or a tag -- so without this
# the rule would first be exercised by a release.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/release-bump-parent.py"
parent="05874ded5bbd19033c77fee0a39e8912d5b78b83"
failures=0

# commit <subject> <parents-json> <files-json>  ->  GitHub "get a commit" JSON
commit() {
	python3 -c '
import json, sys
print(json.dumps({
    "sha": "8fa1410b53731faecf1a1aeb7a592c305e360257",
    "commit": {"message": sys.argv[1]},
    "parents": [{"sha": s} for s in json.loads(sys.argv[2])],
    "files": json.loads(sys.argv[3]),
}))' "$@"
}

# file <patch> [additions] [deletions] [status] [filename]
file() {
	python3 -c '
import json, sys
a = sys.argv[1:] + [None] * 5
f = {"filename": a[4] or "crm/__init__.py", "status": a[3] or "modified",
     "additions": int(a[1] or 1), "deletions": int(a[2] or 1)}
if a[0] != "<none>":
    f["patch"] = a[0]
print(json.dumps([f]))' "$@"
}

check() {
	local name="$1" want_rc="$2" want_out="$3" json="$4"
	local out rc
	out=$(printf '%s' "$json" | python3 "$script" 2>/dev/null)
	rc=$?
	if [ "$rc" != "$want_rc" ] || [ "$out" != "$want_out" ]; then
		echo "FAIL  $name: want exit $want_rc and '$want_out', got exit $rc and '$out'"
		printf '%s' "$json" | python3 "$script" 2>&1 | sed 's/^/        /'
		failures=$((failures + 1))
		return
	fi
	echo "ok    $name"
}

subject="chore(release): Bumped to Version 3.28.0"
one_parent="[\"$parent\"]"
# Exactly what GitHub returns for v3.28.0's bump commit.
good_patch=$'@@ -1,2 +1,2 @@\n-__version__ = "3.27.0"\n+__version__ = "3.28.0"\n __title__ = "Vectora"'

check "a real bump inherits from its parent" 0 "$parent" \
	"$(commit "$subject" "$one_parent" "$(file "$good_patch")")"

# The finding: right subject, right file, and code riding along.
check "code added beside the version is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1,2 +1,3 @@\n-__version__ = "3.27.0"\n+__version__ = "3.28.0"\n+import os; os.system("id")\n __title__ = "Vectora"' 2 1)")"
check "code on the version line itself is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1,2 +1,2 @@\n-__version__ = "3.27.0"\n+__version__ = "3.28.0"; import os\n __title__ = "Vectora"')")"
check "a changed line that is not the version is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1,2 +1,2 @@\n __version__ = "3.27.0"\n-__title__ = "Vectora"\n+__title__ = __import__("os").getcwd()')")"
# additions/deletions say +1 -1 but the patch disagrees: believe neither.
check "a patch that contradicts its own line counts is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1,2 +1,3 @@\n-__version__ = "3.27.0"\n+__version__ = "3.28.0"\n+evil()')")"
check "no patch from GitHub is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file "<none>")")"
check "a missing trailing newline is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1 +1 @@\n-__version__ = "3.27.0"\n+__version__ = "3.28.0"\n\\ No newline at end of file')")"
check "an unchanged version is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file \
		$'@@ -1 +1 @@\n-__version__ = "3.27.0"\n+__version__ = "3.27.0"')")"

# What the guard already refused, kept refused.
check "another subject is not a bump" 1 "" \
	"$(commit "fix: something" "$one_parent" "$(file "$good_patch")")"
check "a second file is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" \
		"$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]) + [{"filename": "crm/hooks.py", "status": "modified", "additions": 1, "deletions": 0}]))' "$(file "$good_patch")")")"
check "another file alone is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file "$good_patch" 1 1 modified crm/hooks.py)")"
check "a merge commit is not a bump" 1 "" \
	"$(commit "$subject" "[\"$parent\", \"$parent\"]" "$(file "$good_patch")")"
check "a root commit is not a bump" 1 "" \
	"$(commit "$subject" "[]" "$(file "$good_patch")")"
check "a renamed-in file is not a bump" 1 "" \
	"$(commit "$subject" "$one_parent" "$(file "$good_patch" 1 1 renamed)")"

# Unreadable input stops the guard rather than reading as "ordinary commit".
check "garbage input is an error, not a verdict" 2 "" "not json"
check "an API error body is an error, not a verdict" 2 "" '{"message": "Not Found"}'

echo
if [ "$failures" -ne 0 ]; then
	echo "$failures release-bump-parent.py check(s) failed"
	exit 1
fi
echo "all release-bump-parent.py checks passed"
