# Versioning & Revert Cheat-Sheet

How we manage versions of the Picasso portal so a new change can **never** permanently
break a working version. Every committed state is a restore point. Nothing is ever truly lost.

This file is the working agreement for the project. When in doubt, follow it.

---

## The one rule that prevents disaster

**Commit the working state before starting the next thing.**

Before any new tool or change is started, the repo should be at a known-good state that is
committed *and* deployed *and* verified in the browser. That guarantees a clean point to
fall back to. We never build on top of unverified work.

---

## Two independent safety nets

You can always get back to a working version using either of these — they're independent:

1. **Git history (the source code)** — every commit is a full, timestamped snapshot in
   GitHub Desktop's **History** tab. Revert restores any past state.
2. **Dokploy deployments (the running app)** — Dokploy keeps previous deployments and can
   roll back the live app to an earlier one from its dashboard, without touching the source.

If a bad push breaks the live site: roll back the **deployment** in Dokploy for an instant
fix, then sort out the **source** in Git at your own pace.

---

## How to revert in GitHub Desktop (easiest first)

1. **Undo the last change**
   History tab → right-click the bad commit → **Revert changes in commit**.
   This makes a *new* commit that undoes it. Non-destructive, and itself reversible.

2. **Look at an old version before deciding**
   History tab → click any commit to see exactly what changed, file by file.

3. **Go fully back to a known-good point** (the "put it back to Tuesday" option)
   This is a hard reset — slightly more advanced. Ask for the exact steps the one time you
   need it; don't run it from memory, since it discards uncommitted work.

> Reverting is itself a commit, so even a revert loses nothing. You can revert the revert.

---

## Commit habits that make reverts surgical

- **One tool / one logical change per commit.** Don't batch five tools into one commit —
  if tool 3 broke something, you want to revert *just* tool 3, not lose the other four.

- **Clear commit messages.** `Crane curves tool working`, not `update`. Future-you scanning
  History needs to find the good state fast.

- **Verify before committing as "working".** Deploy, open it in the browser, click it.
  Only then is it a trustworthy fallback point.

---

## Branches — for anything risky (optional but powerful)

For a big or uncertain change (new engine, adding Postgres, anything that could cascade):

1. GitHub Desktop → **Current Branch → New Branch** (e.g. `try-rao-engine`).
2. Build and commit there. `main` stays pristine and keeps deploying as-is.
3. If it works → merge into `main`. If it doesn't → just delete the branch; `main` never
   knew it existed.

Rule of thumb: **branch for the scary stuff** (engines, infrastructure), **commit straight
to `main`** for small, isolated page work.

---

## Why the architecture protects you too

Tools live in separate files (`engines/<tool>.py`, `pages/<tool>.py`). A change to the
crane-curves tool touches only crane-curves files — it physically cannot break seafastening,
the GA page, or the nav, because the change never goes near them. Small, isolated files +
Git history = a bad change is small, contained, *and* snapshotted.

---

## Milestone tags (optional)

When a meaningful chunk is solid (e.g. first three tools all working), tag it: `v0.1`.
A named bookmark you can always return to. "Get me back to v0.1" is unambiguous.

---

## Quick reference

| I want to…                                  | Do this |
|---------------------------------------------|---------|
| Save a working state                        | Commit (+ push) in GitHub Desktop |
| Undo the last change                        | History → right-click → Revert changes in commit |
| See what an old version contained           | History → click the commit |
| Instantly fix a broken live site            | Dokploy → roll back to previous deployment |
| Try something risky safely                  | New Branch → build there → merge or delete |
| Mark a major known-good point               | Tag it (e.g. `v0.1`) |
