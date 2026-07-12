Here is the complete investigation report.

## 1. Existing CI config

**No `.gitlab-ci.yml` exists anywhere in the repo.** The only automation configs found are GitHub Actions workflows under `/home/user/git/luckydonald/game_collections/.github/workflows/`:

- `claude.yml` — generic `@claude` mention responder (issue/PR comments) using `anthropics/claude-code-action@v1`.
- `claude-issue-agent.yml` — `@claude` issue handler, same action, gated on `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` secrets.
- `codex-issue-agent.yml` — `@codex` issue handler using `openai/codex-action@v1`; this one is the closest existing template for a "run agent → commit → open PR" flow: it creates a branch (`codex/issue-<n>-<run_id>`), runs the agent, commits with `git add -A && git commit -m "..."`, pushes, and opens a PR via `gh pr create`.

Full contents of all three were captured above during the investigation (see the workflow YAML dumped earlier in this session).

Also worth noting: `git remote -v` shows only `base` (github.com/luckydonald/base) and `empty` (github.com/EmptyAAS/empty) remotes — no `origin` is configured, and the current branch is `mane` (not `main`). There is no GitLab remote at all, and no Dockerfile anywhere in the repo (`find -iname "Dockerfile*"` returned nothing) — a note to flag back, since the user's own request in `ai/query.md` asks for a "gitlab workflow," but this repo's actual CI/hosting is GitHub-only right now.

## 2. `game-collections scrape humblebundle` CLI command

Entry point: `/home/user/git/luckydonald/game_collections/src/game_collections/cli.py`, lines 241–305, `scrape_humblebundle_command`, registered under a `scrape` Typer sub-app (`scrape_app = typer.Typer(...)`, `app.add_typer(scrape_app, name="scrape")`, line 36-37).

Signature/options:
```
game-collections scrape humblebundle
  [--url URL ...]                 # repeatable; crawl only these Choice/Games URLs
  [--lists-root PATH]             # default: lists
  [--archive-root PATH]           # default: archives
  [--resolution-map PATH]         # default: config/humblebundle-store-ids.yml
  [--non-interactive]             # record unresolved IDs instead of prompting
```

What it does: creates a `HumbleHttpClient`, loads the resolution map, builds a `StorefrontResolver`, calls `crawl_humble_offers(...)` (in `sources/humblebundle/crawler.py`) to fetch current Humble Choice + active Games bundle offers, resolves Steam store IDs, writes back the resolution map, then calls `write_humble_offer(...)` for each offer.

Output — yes, it writes into `lists/`: `write_humble_offer` (in `/home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/crawler.py:234`) writes:
- `archives/humblebundle/choice/<month-key>/metadata.json` + `source.json` (or `archives/humblebundle/bundle/<key>/...`)
- `lists/humblebundle/choice/<month-key>.yml` for Choice, or `lists/humblebundle/bundle/<key>/<n>-item-bundle.yml` (and `entire-<n>-item-bundle.yml` for tier 0) for Games bundles.

Exit behavior: prints per-offer archive counts, lists unresolved games, exits 1 if there were crawl errors or unresolved (non-interactive mode leaves unresolved marked `unresolved:store:steam:<slug>` rather than prompting).

Invocation: it's registered via `pyproject.toml`'s `[project.scripts]`:
```toml
[project.scripts]
game-collections = "game_collections.cli:app"
```
So it's run as `uv run game-collections scrape humblebundle [options]` (consistent with `CLAUDE.md`'s documented pattern of `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections ...`).

## 3. `commit-with-lplp-style` skill

Definition: `/home/user/git/luckydonald/game_collections/ai/skills/commit-with-lplp-style/SKILL.md` (there's also a thin pointer command at `.claude/commands/commit-with-lplp-style.md`). Full content captured above; key points:

- Commit after every completed task; never leave work uncommitted.
- Check last commits: fold/amend known `ai:` auto-commit patterns (`ai: updated prompt`, `ai: save decision <slug>`, `ai: agent <id> results`, `ai: record memory <slug>`, plan-save commits) into the preceding real work commit — unless a plan genuinely has multiple revisions (then keep `ai: Plan:` / `ai: Plan update:` separate).
- **Always write the message to `ai/git/pending-commit.md` first**, then commit with `-F ai/git/pending-commit.md` (never inline `-m` message text). Procedure: `rm ai/git/pending-commit.md || echo 'was gone'` → write file → `git commit -F ai/git/pending-commit.md`.
- **Message format:**
  ```
  [where] component-or-topic: ai: Run: <short one-line summary><sentence-separator>

  <multiline body: what changed, why, key decisions>
  ```
  `[where]` is a component/subsystem/topic (e.g. `[frontend]`, `[github]`, `[docker]`, `[infra]`), never a Conventional Commits type like `feat`/`fix`. Summary ends in `.`, `:`, `,`, `!`, or `?`. Multiple scopes: `[backend|frontend]`.
- Stage only files touched for the current task, by explicit path — never `git add .`/`git add -A`. Never stage `ai/git/pending-commit.md` itself (it's gitignored).
- Once activated, keep committing automatically without re-asking.
- Never rewrite already-committed history proactively — ask first.

Current `ai/git/pending-commit.md` content (the last-used message, showing the real style in practice):
```
[humblebundle] choice backfill: ai: Run: Backfilled 27 more historical Humble Choice months from dangarbri.tech.

`scripts/backfill_humble_choice.py --all` picked up every remaining month the mirror covers (December 2019 through April 2026, gaps where the mirror has no page), resolving Steam IDs the same way as the 2026-05/2026-06 smoke test. Several older or obscure titles couldn't be matched uniquely and are left as `unresolved:store:steam:<slug>` for manual `game-collections complete` follow-up.

`lists/humblebundle/choice/` now has 30 months (45 lists total); bumped the hard-coded count in `tests/test_lists.py` to match. `game-collections validate` and the full test suite pass.
```

Recent `git log --oneline` (confirms the format, `ai:` suffix convention, and `[where] topic:` prefixes):
```
2b3ba16 ai: updated prompt
9b578c6 ai: updated prompt
265b3f1 [humblebundle] choice backfill: ai: Run: Backfilled 27 more historical Humble Choice months from dangarbri.tech.
c5e4b44 [humblebundle] choice backfill: ai: Run: Added `scripts/backfill_humble_choice.py` to backfill historical Humble Choice lists from dangarbri.tech.
a71887c [humblebundle] choice backfill: ai: Plan update: Add month-selection flags (`--all`/`--month`/`--from`/`--to`) to the backfill script plan.
7b277ab [humblebundle] choice backfill: ai: Plan: Add `scripts/backfill_humble_choice.py` to backfill historical Humble Choice lists from dangarbri.tech.
0f34f4b [cli] list completion: ai: Run: Split draft completion into a mode-aware command.
...
022d2b6 [humblebundle] current offers: ai: Run: Archived July Choice and seven active Games bundles.
```

## 4. `pyproject.toml`

```toml
[project]
name = "game-collections"
requires-python = ">=3.14"
dependencies = ["httpx>=0.28,<1", "markdownify>=1.2,<2", "pydantic>=2.12,<3", "PyYAML>=6.0.2,<7", "typer>=0.16,<1", "vdf>=3.4,<4"]

[project.optional-dependencies]
test = ["pytest>=8.4,<10"]

[project.scripts]
game-collections = "game_collections.cli:app"
```
Python **3.14+** required. Dependency manager is **uv** (confirmed by `uv.lock` present at repo root, and `CLAUDE.md`'s documented commands):
```
env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema
```
No separate lint command is documented in CLAUDE.md (pre-commit config exists at `.pre-commit-config.yaml`/`.pre-commit-hooks.yaml` for that purpose, not covered in depth here since not requested beyond noting it's present).

## 5. `scripts/backfill_humble_choice.py`

Path: `/home/user/git/luckydonald/game_collections/scripts/backfill_humble_choice.py`. It's a standalone one-off script (not part of the `game_collections` package, run via `uv run python scripts/backfill_humble_choice.py`), that mirrors historical Humble Choice months from `https://dangarbri.tech/humblechoice` and writes the **same list/archive shape** as `game-collections scrape humblebundle`: `lists/humblebundle/choice/<YYYY-MM>.yml` plus `archives/humblebundle/choice/<YYYY-MM>/{metadata,source}.json`. It reuses `crawler.py` internals (`_atomic_write`, `_game_list_yaml`, `_json`, `MONTHS`, `HumbleCrawlError`, `HumbleHttpClient`) and `resolver.StorefrontResolver` plus `search.complete_game_list` for Steam ID resolution. This confirms the scraper output pattern the new CI job's crawl step should produce/commit: files under `lists/humblebundle/...` and `archives/humblebundle/...`.

No script in the repo currently commits/pushes/opens PRs for scrape output — that automation doesn't exist yet apart from the `codex-issue-agent.yml` pattern (branch-create → commit → `gh pr create`) described above, and the user's own captured request in `ai/query.md` (line 339) explicitly asks for exactly this: *"write a gitlab workflow which runs the normal crawler (`game-collections scrape humblebundle`) every week, and creates a PR with the results. If the branch still exists from last week, work on that instead of master, and add another commit. The commit shall follow the LPLP commit style..."*

## 6. Dockerfile / container references

**No Dockerfile exists anywhere in the repo** (`find -iname "Dockerfile*"` returned nothing). No container/base-image references were found for Python/uv setup. For a GitHub Actions or GitLab CI job, the closest existing precedent is the `codex-issue-agent.yml` workflow which runs directly on `ubuntu-latest` (no container), and CLAUDE.md's documented setup uses `uv sync --extra test` directly rather than any Docker-based build — so a new CI job should likely follow the same "install uv, `uv sync`, `uv run ...`" runner-native pattern rather than a container image, unless the user wants to introduce one.

## Additional finding: GitLab/MR references repo-wide

`grep -rniE "gitlab|merge request|\bglab\b"` across `.py/.md/.yml/.yaml/.toml` only matched `ai/query.md`, `ai/°base/query.md` (both just recording the user's own prompt text quoted above), and one unrelated mention in `ai/°base/plans/020_download-references-script-and-uv-hook-fix.md`. There is no existing `glab` usage, no GitLab remote, and no other GitLab-specific tooling anywhere in the repo — a GitLab CI pipeline for this would be built from scratch, and note again that the actual git host in use appears to be GitHub (remotes are all `github.com`), which the parent agent may want to clarify with the user before proceeding with a `.gitlab-ci.yml`.