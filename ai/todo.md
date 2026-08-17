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
