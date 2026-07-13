---
name: ""
metadata: 
  node_type: memory
  originSessionId: a808247f-045f-4315-84b5-49fb38c66f8e
---

When the user says "make sure everything since `origin/mane` is cleaned up" during a `commit-with-lplp-style` rebase, that is explicit authorization for the full stray-`ai:`-commit cleanup procedure across the **entire** `origin/mane..HEAD` range — not just the commits the current turn's task added. Audit every commit back to the merge-base with `origin/mane`, including older already-completed tasks sitting further back in the branch.

**Why:** on 2026-07-13, after cleaning up only the new `--collection` task's commits, the user asked for the whole range; the branch also had an older `isthereanydeal` task's history with a chain of un-renamed raw `ai: save plan 012_...` commits (drafting bursts, seconds apart) sitting underneath an already-properly-renamed `ai: Plan:` commit — evidence that a prior session renamed the final plan commit but never folded the earlier raw drafts into it.

**How to apply:** on an explicit full-range cleanup request, run `git log --oneline origin/mane..HEAD`, diff every adjacent raw `ai: save plan <N>_*`/`ai: save decision`/`ai: agent ... results`/`ai: updated prompt` commit pair to tell genuine revisions (keep as `ai: Plan update:`) from same-burst drafting noise (squash into whichever commit in that burst already carries a proper renamed message, or into the last one if none is renamed yet). Don't stop at the current task's own commits just because that's what triggered the session.
