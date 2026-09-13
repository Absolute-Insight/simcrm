---
name: release
description: Cut a release - promote develop to main, let semantic-release tag it and start the image build, then verify the image reached ghcr. Use when the user wants to ship a version.
---

# Cut a release

Full detail and the war stories are in `docs/RELEASING.md`. Read it before a
first release. The one thing to internalise:

> **A release is not finished when the GitHub release appears. It is finished
> when the image is in ghcr.**

The build does start itself: `successCmd` in `.releaserc` has semantic-release
dispatch `builds.yml` on the tag it just created. That dispatch is one `gh`
call and can fail, which is why step 4 is _check, then dispatch only if it did
not fire_ — and why v3.1.4, v3.1.5 and v3.2.1 each carry a manual
`workflow_dispatch` from before `successCmd` existed.

**Do not dispatch it reflexively.** Two builds of one commit produce two
different digests, and the later push silently rewrites the version tag and
`stable`. On 2026-09-13 a manual dispatch 30s behind the automatic one did
exactly that to v3.14.0 and v3.14.1, leaving production running an image its
own release tag no longer named. `builds.yml` now carries a concurrency guard,
so a duplicate cancels the first rather than racing it — but the guard is a
net, not a reason to throw.

## Steps

**1. Check the parent's checks are green _now_.** `builds.yml` refuses to build
a commit whose checks are absent or failing, and a release bump commit inherits
its parent's checks. If the parent is red, that release cannot be published and
cannot be repaired afterwards — re-running checks on a commit uses the workflow
files _from that commit_. This is exactly how v3.2.0 shipped with no image.

```bash
gh run list --branch develop --limit 10
```

Required by name: `Playwright E2E Tests`, `Server Tests`, `Unit Tests & Coverage`.

**2. Preview what you are about to cut.**

```bash
git fetch origin
git log --format=%s origin/main..origin/develop | grep -oE '^[a-z]+(\([a-z-]+\))?!?:' | sort | uniq -c
```

any `feat:` → minor; else any `fix:`/`perf:` → patch; only `docs:`/`chore:`/
`ci:`/`test:` → **no release at all**.

**3. Promote.** Merge PRs into `develop` with a _merge_ commit, never a squash —
semantic-release reads individual commit messages, and a squashed `fix:` subject
turns a feature release into a patch with a one-line changelog.

```bash
git merge-base --is-ancestor origin/main origin/develop   # expect success
git push origin origin/develop:refs/heads/main
```

**4. Watch the build semantic-release started; dispatch only if it did not.**

```bash
gh run list --workflow builds.yml --limit 3        # expect a run on vX.Y.Z
gh workflow run builds.yml --ref vX.Y.Z           # ONLY if none fired
```

Give the automatic dispatch a moment before concluding it failed — it runs
after the tag is pushed, so it can trail the tag by seconds.

**5. Verify the image is really in the registry** — a green build is not proof:

```bash
REPO=absolute-insight/simcrm
TOKEN=$(curl -sf "https://ghcr.io/token?scope=repository:$REPO:pull&service=ghcr.io" \
        | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
     -H 'Accept: application/vnd.oci.image.index.v1+json' \
     "https://ghcr.io/v2/$REPO/manifests/vX.Y.Z"      # expect 200
```

**6. Back-merge the bump into `develop`**, then **bump `VECTORA_TAG` in
`deploy/.env.example`** so the documented pin names a release that exists.

## Ask before pushing to main

Step 3 _is_ the release. Confirm with the user before running it, every time.

## There is no hotfix lane

`main-hotfix` appears in workflow conditions but has never existed. A hotfix
takes the same path: branch → PR into `develop` → promote.
