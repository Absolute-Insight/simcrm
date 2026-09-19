# Releasing Vectora

Cutting a release is automatic, including the image build. That last part was
manual until 2026-09-10 and is the reason v3.2.0 shipped as a GitHub release
with no container image behind it. Read
[The tag does not build itself](#the-tag-does-not-build-itself) anyway: the
gap it describes is real, the automation just steps over it now, and you still
have to check the image arrived.

## The path

```
feature branch ──PR──▶ develop ──push──▶ main ──▶ semantic-release ──▶ tag + GitHub release
                                                                            │
                                          semantic-release dispatches builds.yml
                                                                            │
                                                                    image in ghcr
                                                                            │
                                        bump commit ──back-merge──▶ develop
```

`develop` is the default branch and every PR targets it. `main` is the release branch:
pushing to it _is_ cutting a release. Nothing else triggers one.

## Steps

1. **Merge the PR into `develop`** with a merge commit, not a squash. semantic-release
   reads the individual commit messages to compute the version and write the release
   notes; squashing 30 commits into one gives you a one-line changelog and, if the squash
   subject is a `fix:`, a patch bump for a release full of features.

2. **Promote `develop` to `main`.** `main` is normally an ancestor of `develop`, so this
   is a fast-forward:

   ```bash
   git fetch origin
   git merge-base --is-ancestor origin/main origin/develop   # expect success
   git push origin origin/develop:refs/heads/main
   ```

3. **semantic-release runs on the push** (`on_release.yml`). It computes the next version
   from the conventional-commit types in `main..develop`, `sed`s it into
   `crm/__init__.py`, commits `chore(release): Bumped to Version X.Y.Z`, tags that commit,
   and publishes the GitHub release. You do not tag or bump by hand — doing so fights the
   automation.

   Version comes from the commit types in the range: any `feat:` → minor, otherwise any
   `fix:`/`perf:` → patch, `docs:`/`chore:`/`ci:`/`test:` alone → **no release at all**.
   Check what you are about to cut before you push:

   ```bash
   git log --format=%s origin/main..origin/develop | grep -oE '^[a-z]+(\([a-z-]+\))?!?:' | sort | uniq -c
   ```

4. **The image build starts itself.** semantic-release dispatches `builds.yml` on
   the tag it has just created (`successCmd` in `.releaserc`). Watch it, and if it
   did not start — the dispatch is one `gh` call and can fail — run it by hand:

   ```bash
   gh run list --workflow builds.yml --limit 3
   gh workflow run builds.yml --ref vX.Y.Z   # only if the automatic one did not fire
   ```

   **Check before you dispatch.** Two builds of one commit are not the same
   image: transitive dependencies resolve at build time, so the second push
   rewrites the version tag and `stable` to a different digest. On 2026-09-13 a
   manual dispatch 30 seconds behind the automatic one did this to v3.14.0 and
   v3.14.1, and production was left running an image its own release tag no
   longer named — both builds were green and smoke-tested, so nothing looked
   wrong anywhere. The `build` job's `concurrency` queues same-ref runs rather
   than cancelling them -- on purpose, so a release build is never killed by a
   main push behind it -- which means a duplicate waits its turn and then
   overwrites the tag regardless. Not dispatching twice is the only defence.

   To ask what a host is _actually_ running, and to pin it:

   ```bash
   docker inspect vectora-backend-1 --format '{{.Image}}'
   docker image inspect <that id> --format '{{index .RepoDigests 0}}'
   ```

5. **Verify the image is actually in the registry.** A green build is not proof; ask the
   registry:

   ```bash
   REPO=absolute-insight/simcrm
   TOKEN=$(curl -sf "https://ghcr.io/token?scope=repository:$REPO:pull&service=ghcr.io" \
           | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
        -H 'Accept: application/vnd.oci.image.index.v1+json' \
        "https://ghcr.io/v2/$REPO/manifests/vX.Y.Z"     # expect 200
   ```

6. **Back-merge the bump commit into `develop`**, or the branches diverge and the next
   promotion is no longer a fast-forward. Run `/backmerge`, which does steps 6 and 7
   together.

   This step produces nothing visible — no tag, no release page, no image — which is why
   it is the one that gets missed. The bill then arrives at the *start of the next
   release*, when step 2 is rejected as a non-fast-forward. Missed after v3.13.1, v3.14.0
   and v3.16.0.

   > **This used to document a `gh api .../merges` call. That call does not work:** it
   > returns `403 Must have admin rights to Repository`, because `develop` is protected
   > and neither the `aisight-dev` nor the `Absolute-Insight` token carries admin.
   > Verified 2026-09-19. Don't retry it or go hunting for a token.

   The `no-commit-to-branch` pre-commit hook blocks committing to `develop` locally, and
   so does `.claude/hooks/guard-commit.sh`. Both are right — don't reach for
   `--no-verify`. Use an ordinary branch and PR, which is what every back-merge has
   actually been (#233, #252, #253). Branch from **`origin/main`** so it already carries
   the bump commit and the PR diff against `develop` is exactly what is missing:

   ```bash
   git worktree add .worktrees/backmerge-vXYZ -b chore/backmerge-vX.Y.Z origin/main
   # make step 7's edit on this branch too — same PR, as #233 and #252 did
   gh auth switch --user Absolute-Insight        # aisight-dev is usually the active one
   gh pr create --base develop --head chore/backmerge-vX.Y.Z \
     --title "chore: merge the vX.Y.Z release bump back into develop"
   gh pr merge <n> --merge                       # a MERGE commit, never a squash
   ```

   Repo-wide auto-merge is **disabled** (`enablePullRequestAutoMerge` is refused), so
   `--auto` fails — wait for the checks and merge by hand. Full CI runs even on a
   two-line PR; Playwright and the server tests are the long poles, ~10 minutes.

   Confirm it landed, then delete the branch:

   ```bash
   git fetch origin
   git merge-base --is-ancestor origin/main origin/develop && echo "fast-forward restored"
   git push origin --delete chore/backmerge-vX.Y.Z
   ```

   Deleting matters: five `chore/backmerge-*` branches (v3.14.7, v3.14.8, v3.14.10,
   v3.14.11, v3.15.0) sat on the remote for weeks, all long since merged, and each one
   costs someone a few minutes to re-check. The ancestor check above is the only
   authority on whether a back-merge is owed; a branch's existence means nothing.

7. **Bump `VECTORA_TAG` in `deploy/.env.example`** so the documented pin is a release that
   exists — and one whose **image** exists, which is a separate question (see
   [The tag does not build itself](#the-tag-does-not-build-itself)). Verify with the
   `curl` in step 5 before pinning. Carry this on the step 6 branch so it lands in the
   same PR.

## The tag does not build itself

`builds.yml` triggers on `push` to `main` **and on any tag**, which reads as though
tagging publishes the image. It does not.

semantic-release creates the bump commit and the tag, and pushes them with the workflow's
`GITHUB_TOKEN`. GitHub deliberately does not trigger workflows from pushes made with that
token — otherwise a workflow could trigger itself forever. So the tag lands and nothing
happens.

This is why v3.1.4, v3.1.5 and v3.2.1 each have a `workflow_dispatch` run of `builds.yml`
in their history. Those are not retries of a failure; they are the release.

**What closes it.** GitHub suppresses `push` and `create` events from
`GITHUB_TOKEN`, but not `workflow_dispatch`. So semantic-release now asks for
the build itself, from `successCmd` in `.releaserc`, with `actions: write` on
the release job. The step above is the same command; it is just no longer
yours to remember. Verifying the image arrived still is.

**A release is not finished when the GitHub release appears. It is finished when the image
is in ghcr.**

## The guard, and what it needs

`builds.yml` refuses to build a commit whose checks are absent or failing — it publishes
the image customers run, and neither a push to `main` nor a tag runs the test suites by
itself. It waits for these, by name, on the commit being built:

- `Playwright E2E Tests`
- `Server Tests`
- `Unit Tests & Coverage`

A release bump commit is the deliberate exception. It contains one `sed` of the version
string, and the token that pushed it suppressed the workflows that would have tested it —
so the guard verifies the commit really is a bump (subject starts `chore(release):`, and
`crm/__init__.py` is the only file touched) and inherits its parent's checks. It refuses
to walk the parent of anything else.

The practical consequence: **the parent's checks must be green at the moment you promote.**
If they are red, that release cannot be published, and it cannot be repaired after the
fact — re-running the checks on that commit uses the workflow files _from that commit_, so
a CI bug fixed later on `main` does not retroactively fix them. That is exactly how v3.2.0
ended up as a release with no image, and why the fix had to ship as v3.2.1.

## Things that make a check look green when it never ran

Three asymmetries have each hidden a failure here. All three are worth knowing before you
trust a green PR.

**`main` and a PR do not run the same suite.** `server-tests.yml` resolves a frappe branch
from the target branch. Every lane now resolves to `vectora` — the branch the image is
built from — but the inherited mapping sent anything that was not `develop` to frappe
`version-15`/`version-16`. This fork carries neither (`Absolute-Insight/frappe` has only
`develop` and `vectora`) and could not run on version-15 in any case, since `pyproject.toml`
requires `frappe >=16.0.0-dev`. The clone failed before a single test ran. It stayed hidden
because the suite ran only on `pull_request`, and pull requests target `develop`.
`migration-test.yml` had already hit the same mapping and called it _"green only by never
running."_

**`paths-ignore` applies to PRs but not to pushes.** `frontend-tests.yml` and
`server-tests.yml` skip paths on `pull_request` and deliberately do not on `push`, because
the guard needs the check present on every commit it might publish. So
`Unit Tests & Coverage` can be legitimately absent from a PR that touched only a `.yml`
file, and still be required on `main`.

**A local suite run is not CI's.** `bench run-tests` runs against whatever site you name,
and a full run leaves roughly 70 records behind. CI reinstalls per run. A test that reads
site-wide state can pass locally on the residue of earlier runs and fail on CI's clean
site — which is how `test_a_failing_scope_costs_only_its_own_rows` shipped: it asserted a
forecast snapshot wrote rows, and its own deal had no close date, so it was really
measuring whether the site happened to hold some other forecastable deal. Reinstall before
believing a green suite:

```bash
cd frappe-bench
bench set-config -g mariadb_root_password <root-pw>       # remove this again afterwards
bench --site test_site reinstall --yes --admin-password admin
bench --site test_site install-app crm                    # reinstall drops it
bench --site test_site run-tests --app crm
```

## There is no hotfix lane

`main-hotfix` appears in a couple of workflow conditions and it is worth knowing that
**the branch has never existed**. It was a staging lane someone planned and never created;
`ui-tests.yml` records that the E2E suite consequently "had never run in CI once", because
it was gated on a branch nothing ever pushed to.

So a hotfix takes the same path as anything else: branch, PR into `develop`, promote. If
you ever do create `main-hotfix`, note that the conditions referencing it only control
whether ERPNext is installed for the server suite — nothing else keys off it, and it is
not wired to publish.
