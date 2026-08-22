# Releasing Vectora

Cutting a release is mostly automatic and has exactly one manual step that looks
automatic. That step is why v3.2.0 shipped as a GitHub release with no container image
behind it. Read [The tag does not build itself](#the-tag-does-not-build-itself) before
your first release.

## The path

```
feature branch ──PR──▶ develop ──push──▶ main ──▶ semantic-release ──▶ tag + GitHub release
                                                                            │
                                                        you dispatch builds.yml on the tag
                                                                            │
                                                                    image in ghcr
                                                                            │
                                        bump commit ──back-merge──▶ develop
```

`develop` is the default branch and every PR targets it. `main` is the release branch:
pushing to it *is* cutting a release. Nothing else triggers one.

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

4. **Dispatch the image build on the new tag.** See below — this is the step that is not
   automatic.

   ```bash
   gh workflow run builds.yml --ref vX.Y.Z
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
   promotion is no longer a fast-forward. The `no-commit-to-branch` pre-commit hook blocks
   committing to `develop` locally, so do it server-side rather than reaching for
   `--no-verify`:

   ```bash
   gh api repos/Absolute-Insight/simcrm/merges \
     -f base=develop -f head=main \
     -f commit_message="chore: merge the vX.Y.Z release bump back into develop"
   ```

7. **Bump `VECTORA_TAG` in `deploy/.env.example`** so the documented pin is a release that
   exists.

## The tag does not build itself

`builds.yml` triggers on `push` to `main` **and on any tag**, which reads as though
tagging publishes the image. It does not.

semantic-release creates the bump commit and the tag, and pushes them with the workflow's
`GITHUB_TOKEN`. GitHub deliberately does not trigger workflows from pushes made with that
token — otherwise a workflow could trigger itself forever. So the tag lands and nothing
happens.

This is why v3.1.4, v3.1.5 and v3.2.1 each have a `workflow_dispatch` run of `builds.yml`
in their history. Those are not retries of a failure; they are the release.

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
fact — re-running the checks on that commit uses the workflow files *from that commit*, so
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
`migration-test.yml` had already hit the same mapping and called it *"green only by never
running."*

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
