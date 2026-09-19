---
name: backmerge
description: Merge the release bump commit from main back into develop, so the next promotion stays a fast-forward. Use after cutting a release, or when a push to main is rejected as non-fast-forward.
disable-model-invocation: true
---

# Back-merge main into develop

Step 6 of `docs/RELEASING.md`, split out because it is the step that gets
missed. Everything before it is visible — a tag, a release page, an image in
ghcr. This one produces nothing you would notice the absence of **until the
next release, which it then blocks.**

## What actually goes wrong

semantic-release creates the version bump commit (`chore(release): Bumped to
Version X.Y.Z`, touching `crm/__init__.py`) **on `main`**. Nothing brings it
back. `develop` then lacks a commit `main` has, so:

```bash
git push origin origin/develop:refs/heads/main     # rejected: non-fast-forward
```

and the next release cannot be promoted until this is fixed. The fix is always
available, but it is discovered at the worst moment — mid-release, when you
believed you were shipping.

## Do it as a branch and a PR

`.pre-commit-config.yaml` runs `no-commit-to-branch --branch develop`, and this
repo's `guard-commit.sh` hook refuses commits on `develop` and `main` too. Both
are right. Do **not** reach for `--no-verify`.

> **`docs/RELEASING.md` step 6 tells you to call the merges API directly:**
>
> ```bash
> gh api repos/Absolute-Insight/simcrm/merges -f base=develop -f head=main ...
> ```
>
> **That does not work.** It returns `403 Must have admin rights to
> Repository` — `develop` is protected, and neither the `aisight-dev` nor the
> `Absolute-Insight` token carries admin. Verified 2026-09-19. Do not burn time
> re-trying it or hunting for a token; the RELEASING.md snippet is wrong.

The route that works, and the one every past back-merge actually took (#233 for
v3.14.5, #252 for v3.16.0), is an ordinary branch and PR:

```bash
git worktree add .worktrees/backmerge-vXYZ -b chore/backmerge-vX.Y.Z origin/main
```

Branch from **`origin/main`**, so the branch already carries the bump commit and
the PR diff against `develop` is exactly what is missing. Use a worktree — this
checkout is shared with other sessions.

## Bundle release step 7 into the same PR

Past back-merges carry **both** outstanding release steps, and it is worth
keeping that habit: the `.env.example` pin gets missed for the same reason the
back-merge does.

So on the branch, also bump `VECTORA_TAG` in `deploy/.env.example` to the
release just cut — but **verify the image exists first**, because a GitHub
release and a published image are two separate steps and v3.2.0 shipped the
first without the second:

```bash
REPO=absolute-insight/simcrm
TOKEN=$(curl -sf "https://ghcr.io/token?scope=repository:$REPO:pull&service=ghcr.io" \
        | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
     -H 'Accept: application/vnd.oci.image.index.v1+json' \
     "https://ghcr.io/v2/$REPO/manifests/vX.Y.Z"      # expect 200
```

## Steps

**1. See whether a back-merge is actually owed.**

```bash
git fetch origin
git merge-base --is-ancestor origin/main origin/develop && echo "in sync" || echo "BACK-MERGE OWED"
git log --oneline origin/develop..origin/main
```

The second command lists precisely what `main` has and `develop` does not. In
the healthy case it is empty and the ancestor check passes. In the normal
post-release case it is exactly one `chore(release):` commit.

If it lists **anything other than release bumps**, stop and look properly —
a hotfix committed straight to `main` is not supposed to exist (there is no
hotfix lane; see `docs/RELEASING.md`), and back-merging it silently is not the
right response to finding one.

**2. Branch, bump, push, PR.** Push with the **`Absolute-Insight`** account
(`gh auth switch --user Absolute-Insight`) — `aisight-dev` is usually the active
one and is not what this repo's pushes go out as.

```bash
gh pr create --base develop --head chore/backmerge-vX.Y.Z \
  --title "chore: merge the vX.Y.Z release bump back into develop"
```

**3. Merge it with a MERGE COMMIT, never a squash.** semantic-release reads
individual commit messages, and squashing a back-merge flattens the bump commit
in a way that confuses the next release's version calculation.

```bash
gh pr merge <n> --merge
```

Repo-wide auto-merge is **disabled** (`enablePullRequestAutoMerge` is refused),
so `--auto` does not work — wait for the checks and merge by hand. Full CI runs
on this PR even though it is two one-line changes; Playwright and the server
tests are the long poles.

**4. Confirm the branches are reconciled.**

```bash
git fetch origin
git merge-base --is-ancestor origin/main origin/develop && echo "fast-forward restored"
```

This must pass before you consider the release finished. If it does not, the
merge did not land — look at the PR rather than re-running the check.

**5. Delete the branch.** `git push origin --delete chore/backmerge-vX.Y.Z`,
and `git worktree remove` the worktree. Skipping this is how the remote
accumulated five abandoned `chore/backmerge-*` branches (v3.14.7, v3.14.8,
v3.14.10, v3.14.11, v3.15.0) whose work had in fact already landed — they look
like outstanding back-merges and cost a few minutes each time someone checks.
The authoritative answer is always the ancestor check in step 1, never the
presence of a branch.

## If a promotion has already been rejected

Nothing is broken and nothing is lost — you found the problem at step 3 of a
release rather than at step 6 of the last one. Run this skill, then resume
`/release` from the promote step. Do not force-push `main` to make the
rejection go away: that rewrites published release history, and the tags and
the ghcr images still point at the old commits.

## Why this is not automated

It could be, and `successCmd` in `.releaserc` is where it would go. It is not,
because a merge into `develop` that fires from CI on every release would also
fire on a release cut from a `main` that someone had hand-touched, and would
merge that too. The check in step 1 — *is the only thing coming back a version
bump?* — is the part worth a human, and it is cheap.
