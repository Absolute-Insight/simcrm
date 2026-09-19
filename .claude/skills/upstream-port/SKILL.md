---
name: upstream-port
description: Port fixes from upstream frappe/crm into this fork - establish the merge base, filter what we already carry, take net per-file diffs, and record what was left out. Use when pulling upstream work in, or when asked what upstream has that we do not.
disable-model-invocation: true
---

# Port from upstream frappe/crm

The reviewing counterpart is the `upstream-port-reviewer` agent — run it when
the branch is ready. The last port is written up in `.pi/ARCHIVE.md` under
**"Upstream port — frappe/crm v1.83.0"**; read it before starting, because it
records what was deliberately left behind and you should not re-litigate those
without a reason.

## Get the relationship right first, or everything after is wrong

**We descend from upstream `develop`, not from the line its releases are cut
on.** Upstream's `main` / `main-hotfix`, where every `v1.x` tag lives, split off
`develop` in March 2025 and has been maintained by backport since.

The consequence that costs the most time when rediscovered: **no `v1.x` release
tag is an ancestor of our history** — all 258 were checked. So "which upstream
release are we on" has no clean answer, and *"upstream released v1.N+1, let us
take that"* is wrong at the root. Reason in commits against the merge base, not
in version numbers.

Establish the base yourself rather than trusting a number in a doc:

```bash
git fetch upstream
git merge-base HEAD upstream/develop                       # expect 7dcd8430d, 2026-08-13
git rev-list --count $(git merge-base HEAD upstream/develop)..upstream/develop
```

That count is how far upstream has moved. It grows; re-measure every time.

## The unit is a net per-file diff, never a commit series

Do **not** cherry-pick a range. Upstream's `develop` contains commits that are
broken in isolation and fixed later — `2826f2d35` in the last reviewed range
ships literal `<<<<<<< HEAD` markers in `Field.vue`, cleaned up only by a
subsequent "resolve merge conflicts" commit. Replaying a series re-introduces
churn upstream itself reverted.

Take, per file, the **net difference between the merge base and the upstream
point you are porting to**, and apply it by hand onto our version of that file.

## Steps

**1. Work in an isolated worktree.** This checkout is shared with other
sessions, and a port touches many files.

```bash
git switch -c fix/upstream-<label> origin/develop   # in .worktrees/<name>
```

**2. Filter out what we already carry.**

```bash
git cherry -v develop upstream/develop $(git merge-base HEAD upstream/develop)
```

`git cherry` is the right first pass — last time it found 5 of 41 commits
already present verbatim. But it is **patch-id exact**: a fix we carry in
adapted form still reads as missing. Last port, three more of the "missing"
commits turned out to be already present, one with a fuller rationale than
upstream's. So treat its output as a shortlist to read, not a worklist to
apply.

**3. Read each candidate against our file.** For every commit that survives,
open our version of the file it touches. Decide explicitly: *take*, *adapt*, or
*leave*. The fork has diverged on permissions, theming and the agent layer;
upstream's version of a file is frequently not applicable.

**4. Apply as one commit per fix,** not one giant commit — `AGENTS.md` commit
style, and it is what makes the port reviewable at all. The last port was ten
commits, one per fix.

**5. Never copy generated or owned files.** `crm/www/crm.html`,
`crm/public/frontend/**` and `frontend/src/styles/vectora-theme.css` are build
or generator output — re-derive them by running the build or the generator.
`crm/__init__.py` is bumped by semantic-release; an upstream version line must
not come across. The `guard-paths.sh` hook refuses all of these, so a port that
fights the hook is a port doing the wrong thing.

**6. Read every ported test.** Upstream tests assume upstream's permission
model and schema. One that passes here may be passing for the wrong reason.

**7. Run the suites** — `/test`. Python needs the devcontainer bench, and if
you are working in a worktree it needs `PYTHONPATH` prepended or `bench` tests
the main checkout's code instead of yours; confirm a traceback names your
worktree path before believing a green run.

**8. Record the port in `.pi/ARCHIVE.md`** — the merge base, what was taken,
and **what was left out and why**. An omission is fine; an *undocumented*
omission is the finding, because the next port re-litigates it.

## The `.pi` staging trap — verified, and it will bite you at step 8

`.pi` is in `.gitignore` while its contents are tracked. So `git add` on any
`.pi` path prints "The following paths are ignored" and **exits 1 — while
still staging the file**.

That means this silently does nothing:

```bash
git add .pi/ARCHIVE.md && git commit -m "docs: record the port"   # WRONG
```

The `&&` never fires, the commit never happens, and the add *looked* like it
failed although it worked. Separate them:

```bash
git add .pi/ARCHIVE.md
git commit -m "docs: record the port and what was left out"
```

**9. Review.** Run the `upstream-port-reviewer` agent on the branch. Its first
job is finding local changes an upstream file silently overwrote — a lost local
fix looks exactly like a clean port, which is why a human diff read is not
enough.

## Scope

Port **fixes**. Upstream features arrive with upstream's assumptions about
permissions, layouts and the desk, and this fork has its own answers to all
three. A feature port is a product decision, not a maintenance task — raise it
rather than absorbing it.
