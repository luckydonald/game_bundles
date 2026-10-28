# Todos

## For Agents
If you are an agent tasked to process/fix this file:

- Fix the outstanding issues (unchecked items) below.
- At least 1 commit (/commit-with-lplp-style) per task, possibly more where it makes sense.
- You are allowed to plan for one or more items as it makes sense.


## How to sync from CalDAV

Source: `sync_todo` MCP, calendar `TODO: Today` (`calendar_id` 7). Each item ends with its todo `uid`, and may optionally include a body as blockquote the next lines.

To complete one:
1. tick the box - good to squash into the code commit
2. call `mcp__sync_todo__complete_todo(calendar_id=7, uid=<uid>)`.
3. Finally call `../DockerTgBot/scripts/sync_todos.py --project base` to update this file, which may add new tasks.
   - Generally, leaving out the project parameter is fine, too, as this syncs all projects, which is what you want to do eventually anyway.
   - If you specify the project you may also occasionally add flags to reduce the length, which may be good if you got more than 20 todos completed.
     - Add `--purge-missing` if you want to remove items not tracked in the todo list. Still incompleted ones should be duplicated to the `sync_todo` MCP first.
     - Add `--purge-complete` to clean up completed tasks.

## Todos added manually
Each of those tasks shall be a commit of its own, following the LPLP commit style.

- [x] The current humble monthly contains _Game 2/8: Dead Cells + The Bad Seed DLC_, which are actually two games.
- [x] The TUI apply picker should show a "diff" (steam collections to remove, steam collections to add, steam collections kept)
- [x] Standardize `Entire 14 Item Bundle` between `humblebundle` crawler and `isthereanydeal` (which does `entire-14-item-bundle`). Probably just dash-snake-case to title-space-case.
- [x] The `apply` should save the filter settings when it saves the lists, also to `config/apply-selection.yml`
- [x] Rename "Unconfigured Handling" (`apply`, `sync`) to something better named, which is easier to understand.
- [x] Analyze the difference between `isthereanydeal` crawling (current commits, i.e. `9f39eff31fe5ac1dfeb44d1b56d941deb42d4810`) with a humble bundle crawl (`1a12511d471dd97d49e5c9e07f7ec725ec12f91b`), and why they are diffenrent.
  - [x] Check that the `humblebundle` crawler supports merging with existing results. Again, prefer enhancing - not overwriting.
- [x] The order of `tier-1` to `tier-3` is reversed between `humblebundle` and `isthereanydeal`, which causes full file conflicts.
  - The full bundle is the highest tier.
  - I believe `humblebundle` has it wrong.
- [x] `references` should be appended to, not overwritten.
- [x] HumbleBundle shall still be authoritative with its games, so not on humble = remove from bundle.
  - hehe, that rhymes!
- [x] Add a `--git` flag, which is alias for `--git-add` and `--git-commit`; doing exactly that.
  - It shall be using a similar commit message as the GitHub actions.
  - Have `--git=auto` and `--git=manual` (default when just `--git`), which provide slightly different texts for each usecase.
- [x] Adapt the git workflows to use `--git=auto`, but keep the manual commit code in case we missed any files (unlikely). And rephrase their text for that.
- [x] Validate by running both scrapers and comparing the list's output, if there are remaining issues to tackle.


## Todos synced from CalDAV

- [x] allow `/code-style` and suffix like `/code-style .md .py` or `/code-style md` in the query-autocommit hook to not be displayed — `todo:2eaeb8ce-67be-4878-a8df-3fb3311a4be8` _(done)_
  > • there's an array to fill
- [x] add `mcp__sync_todo__list_calendars` to allowed calls in [`ai/settings/settings.json`](./settings/settings.json). — `todo:87dac3b4-331e-4043-8f5b-cc5e45c113ab` _(done)_
- [x] add memory that if we stumble over preexisting errors in unittests or typing, those should be fixed as a separate commit automatically, too. No need to explicitly seach for those though. — `todo:8ae825eb-3ef2-4d84-8180-a937d7e2bb3c` _(done)_
- [x] Write memory to NEVER EVER run file searches from `/`. — `todo:d23bc543-c583-4dc1-a8ed-1141c92f6822` _(done)_
  > Also disallow `find / …` via [`ai/settings/settings.json`](./settings/settings.json).
- [ ] add digiphile scraper — `todo:e1bfc5d1-e6e8-4eb9-9345-4b41f2436a61`
  > • List: https://www.digiphile.co/collections
  > • Bundle examples:
  >   • currently live: https://www.digiphile.co/collections/social-multiplayer-games-collection-digiphile
  >   • expired: https://www.digiphile.co/collections/vr-games-showcase-the-new-essentials
