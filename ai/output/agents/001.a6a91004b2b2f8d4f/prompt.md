In repo /home/user/git/luckydonald/game_collections, investigate:

1. Any existing CI config: check for .gitlab-ci.yml, .github/workflows/*, or similar files. Report full contents if found.
2. The `game-collections scrape humblebundle` CLI command: find its entry point (likely in src/game_collections/ or scripts/), what it does, what output it produces (does it write to lists/ directory?), and how it's invoked (pyproject.toml [project.scripts] entry, uv run, etc).
3. The "commit-with-lplp-style" skill: find its definition (likely under .claude/skills/ or .agents/ or similar), and read ai/git/pending-commit.md if it exists, and any recent git log commits with "ai:" prefix to understand the commit message format/style used in this repo (already visible in git log: "ai: updated prompt", "[humblebundle] choice backfill: ai: ...").
4. Check pyproject.toml for python version requirement, dependency manager (uv), and how tests/lint are run (mentioned in CLAUDE.md: uv sync --extra test, uv run pytest, uv run game-collections validate/schema).
5. Look for any existing scripts/backfill_humble_choice.py (mentioned in recent commit) to understand scraper patterns and how new list files get added/committed.
6. Check if there's a Dockerfile or existing container/base image reference anywhere in the repo useful for a GitLab CI job (python version, uv install method).

Report back: full CI file contents if any exist, the exact CLI invocation for scraping, the commit message conventions/format (give examples), and any existing automation scripts for creating PRs/branches (grep for "merge request", "MR", "gitlab", "GITLAB", "glab" across the repo).