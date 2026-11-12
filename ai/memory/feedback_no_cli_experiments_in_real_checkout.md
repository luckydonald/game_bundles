---
name: no-cli-experiments-in-real-checkout
description: "Never run the game-collections CLI (esp. `scrape`) for experiments in the real checkout; its git side effects can stash the user's uncommitted work. Use a temporary repo."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 378fc60e-208c-4055-9d9b-906fad36938a
  modified: 2026-11-12T00:31:58.198Z
---

Do not probe `game-collections scrape ...` (even with `--help` or deliberately wrong options) in the real repository, because the `--git` session can autostash or create worktrees in it.

**Why:** On 2026-11-12 `scrape --no-git-worktree humblebundle ... --git --help` autostashed all uncommitted work, including the user's unfinished Humble scrape output, and nothing restored it, because the group callback began the session before Click rejected the misplaced option. Recovered with `git stash pop`, nothing lost. Fixed by starting the session lazily in the subcommand body, see [[reuse-existing-prefixes]] for related design rules.

**How to apply:** Exercise git-touching CLI paths only through `CliRunner` tests on temporary repositories (see `tests/test_scrape_worktree.py` and `tests/test_scrape_git.py`) or in a throwaway clone. For read-only checks use `scrape --help` on the group, which is safe.
