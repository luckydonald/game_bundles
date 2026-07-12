# Weekly Humble Bundle scrape workflow (GitHub Actions)

## Context

Repo lives on GitHub (remotes are `github.com/luckydonald/base`, `github.com/EmptyAAS/empty`; no GitLab remote, no `.gitlab-ci.yml`, no prior GitLab tooling anywhere in the repo). User confirmed GitHub Actions is the right target instead of GitLab CI. Goal: run `game-collections scrape humblebundle` weekly, commit new/changed `lists/humblebundle/...` + `archives/humblebundle/...` + resolution-map output, and open (or update) a PR — reusing a single rolling branch across weeks instead of creating a new one every run, and writing the commit in this repo's LPLP style (`ai/skills/commit-with-lplp-style/SKILL.md`).

Closest existing precedent: `.github/workflows/codex-issue-agent.yml` already does branch-create → commit → push → `gh pr create` with the built-in `GITHUB_TOKEN`, confirming `gh` CLI is available on `ubuntu-latest` runners without extra setup.

## New file

`.github/workflows/weekly-humblebundle-scrape.yml`

### Triggers
```yaml
on:
  schedule:
    - cron: '0 6 * * 1'   # Monday 06:00 UTC
  workflow_dispatch: {}
```

### Permissions
```yaml
permissions:
  contents: write
  pull-requests: write
```

### Job outline (single job, `ubuntu-latest`)

1. **Checkout** with `fetch-depth: 0` (need full history to check remote branch and diff cleanly).
2. **Set up Python 3.14 + uv** via `astral-sh/setup-uv@v...` action (sets up uv, caches deps) then `env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test`.
3. **Resolve rolling branch** — fixed name `automation/humblebundle-weekly-scrape`:
   - `git fetch origin`
   - If `origin/automation/humblebundle-weekly-scrape` exists: `git checkout -B automation/humblebundle-weekly-scrape origin/automation/humblebundle-weekly-scrape` (branch survived from last week, still has an open PR) then `git rebase origin/main` to pick up any unrelated main changes before adding this week's commit. If the rebase fails (conflict), run `git rebase --abort` and continue on the branch as-is — do not block the scrape/commit on this; a human resolves the conflict later via the open PR.
   - Else: `git checkout -B automation/humblebundle-weekly-scrape origin/main` (fresh — last week's PR was merged/closed and branch deleted).
4. **Run the crawler**: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --non-interactive`, capturing stdout to a file and the exit code. Do **not** hard-fail the job on nonzero exit — CLAUDE.md's own backfill workflow treats unresolved games as an expected, committable state (`unresolved:store:steam:<slug>` markers for later manual `game-collections complete`). Record the exit code and an unresolved-count (grep captured stdout) for use in the commit/PR body; only surface it as an informational warning in logs.
5. **Check for changes**: `git status --porcelain -- lists/ archives/ config/humblebundle-store-ids.yml`. If empty, log "no new offers this week" and end the job successfully (no commit, no push, no PR touch).
6. **Write commit message** to `ai/git/pending-commit.md` following the LPLP format exactly (`[where] topic: ai: Run: <summary>.` + body), e.g.:
   ```
   [humblebundle] weekly scrape: ai: Run: Archived this week's Humble Bundle offers via scheduled CI.

   Automated `game-collections scrape humblebundle --non-interactive` run from the weekly GitHub Actions workflow.
   <N> unresolved store IDs left as `unresolved:store:steam:<slug>` for manual `game-collections complete` follow-up (or "None." if zero).
   ```
   Generate this with a small shell/python snippet inline in the step (no LLM call — deterministic template + counts parsed from step 4's captured stdout).
7. **Commit**: stage explicit paths only — `git add lists/ archives/ config/humblebundle-store-ids.yml` (whichever actually changed per `git status`), then `git commit -F ai/git/pending-commit.md`. Leftover `ai/git/pending-commit.md` on disk doesn't matter — no cleanup needed.
8. **Configure git identity** for the commit before step 7: `user.name = "Lucky Lucy (automation)"`, `user.email = "3._.code@luckydonald.de"`.
9. **Push**: `git push origin automation/humblebundle-weekly-scrape` (plain push works whether the branch is new or continuing, since we always rebuild it from `origin/main` + merge when reused, never force-push).
10. **Push and PR happen regardless of rebase/scrape exit-code outcome** — the job keeps scraping and committing every week even if a prior rebase conflict was ignored; a human resolves it on the open PR whenever they get to it.
11. **Open or update PR** via `gh` CLI:
    - `gh pr list --head automation/humblebundle-weekly-scrape --state open --json number -q '.[0].number'`
    - If empty: `gh pr create --base main --head automation/humblebundle-weekly-scrape --title "[humblebundle] weekly scrape" --body-file <generated body>`
    - If present: nothing further needed — the new commit already shows up on the existing open PR automatically; optionally `gh pr comment <number> --body "New offers added: <summary>."` for visibility.

## Verification

- No live CI to trigger from here; validate by reading the finished YAML for correctness (actionlint-style read-through: valid cron syntax, correct permissions block, correct step ordering, `${{ secrets.GITHUB_TOKEN }}` wired to `gh`/`git push` auth).
- Optionally dry-run the branch/commit logic locally: `git fetch`, manually exercise the checkout-or-create branch logic and the `git status --porcelain` change-detection line to confirm the commands are correct against the actual repo layout (`lists/humblebundle/`, `archives/humblebundle/`, `config/humblebundle-store-ids.yml`).
- Confirm `game-collections scrape humblebundle --non-interactive` still matches the CLI signature in `src/game_collections/cli.py` (flag exists, no interactive prompts block CI).
