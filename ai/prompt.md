# AI query log file

#### General AI development guidelines:
- You may refer to `ai/refrences` for code examples of other plugins or extra documentation provided for tasks, if mentioned.
- When writing code, follow these guidelines:
  - Always prefer the early-return pattern to reduce nesting of `if`s, etc.
  - Similarly, prefer `if …` -> `continue`/`return`/`break` early in loops over large nested blocks.
- Language/stack-specific style constraints (Vue/TS frontend, Python backend, …), including test-writing expectations, now live in the `code-style` skill under `ai/skills/code-style/references/` — apply those instead of repeating them here.
- Remember to update the `/CHANGELOG.md` and `/README.md` if existent (including other pre-existing documentation).
- If you need to write Markdown summaries of the task you just did (only if specifically asked for by the user!) write those to `ai/summaries/` folder, and never into the root folder.
  - However, usually you don't need to write Markdown summaries.
- Please prefer to use the read file tool over weird constructs with `cat` etc. Terminal should not be needed for searches most of the time, either.

----

#### Previous user prompts:

› This is to be a resource for collections of games.
The idea initially stems from "Oh it would be nice if I could have the humble bundle sepearted in my steam library."

I want two things here.
A) A easy to maintain format of adding games to such collections. For now my goal is steam, but it could be epic store or other stuff later.
So it should be an extendable format for that later, too.
But it's inital version will be using the game ids on steam, i.e. `440` would be `Team Fortress 2`, and so on. So for now I think `id: ["steam:440"]` could be enough.
Maybe YAML.
B) A tool to possibly sync those game lists into your steam account.
So it would create collections there, if it detects you have all games of a bundle or collection in your steam account.
All python.

Check out ai/query.md for universal guidence.
Also, generally speaking, for python, close indention levels with an `# end …` - e.g. `if …:` will be closed with `# end if`, similarly `# end while/for/with/def/class` etc.
Generate a AGENTS.md in the end, like /init would.

› Ignore the plan, instead Investigate why the plan we just created was not commited by any AI hooks (`scripts/°base/ai/hooks` etc.).

› Alright, for initial test data, add the valve orange box and their games.

› Question answered.
> <details><summary>
>
>> 1. How far should the first implementation go with creating Steam collections?
>> 2. Should each YAML game entry carry a human-readable name alongside its storefront IDs?
>
> (click to expand)
>
> </summary>
>
>> **Steam write** (1/2) <kbd>Single Select</kbd><br>
>> How far should the first implementation go with creating Steam collections?
> - [x] 1\. Dry-run plus apply (Recommended)
>   - _Implement local Steam configuration writing with backups, Steam-closed checks, and explicit --apply._
> - [ ] 2\. Dry-run only
>   - _Detect owned games and report intended collections, postponing all Steam file mutation._
> - [ ] 3\. Data tooling only
>   - _Implement the collection format and validation now, postponing ownership lookup and synchronization._
> - [ ] 4\. _Type something._
>
>> **Game names** (2/2) <kbd>Single Select</kbd><br>
>> Should each YAML game entry carry a human-readable name alongside its storefront IDs?
> - [x] 1\. Names required (Recommended)
>   - _Makes collection files reviewable while IDs remain the authoritative identity._
> - [ ] 2\. Names optional
>   - _Allows terse ID-only entries but produces less readable collection files._
> - [ ] 3\. IDs only
>   - _Keep files minimal and resolve names from storefront metadata when displaying them._
> - [ ] 4\. _Type something._
>
> </details>
>

› Also the yaml shall be pydantic verified and get an schema to help autocomplete in IDEs etc. If possible generated from the pydantic.

› Activate the LPLP commit skill once switching to implementation.

› The id of the library corresponds to the filepath + `.yml`, in a `/lists/` root folder which contains a helpful `README.md`.
Now figure out the steam library tagging in detail and add it to the plan.
I have logged into my main steam account, so you can investigate. Do not attempt to write without asking, though. I'll be sad if you break my steam account. (famous last words)

› Question answered.
> <details><summary>
>
>> 1. For `lists/valve/the-orange-box.yml`, what is the derived collection ID?
>> 2. What confirmation should the CLI require before touching Steam’s cloud-storage cache?
>
> (click to expand)
>
> </summary>
>
>> **List ID** (1/2) <kbd>Single Select</kbd><br>
>> For `lists/valve/the-orange-box.yml`, what is the derived collection ID?
> - [x] 1\. valve/the-orange-box (Recommended)
>   - _Use the path relative to lists with the .yml suffix removed; the file itself contains no id field._
>   - > sktop App
> - [ ] 2\. valve/the-orange-box.yml
>   - _Include the filename suffix in the logical ID exposed by the tool._
> - [ ] 3\. _Type something._
>
>> **Apply guard** (2/2) <kbd>Single Select</kbd><br>
>> What confirmation should the CLI require before touching Steam’s cloud-storage cache?
> - [x] 1\. Flag plus typed prompt (Recommended)
>   - _Require --apply and an interactive confirmation naming the account and exact files; provide no bypass in v1._
>   - > `--apply` switches from dry run to actually doing something. It will write the new file into a easy to reach directory, print out the pathes of where they are and where they shall go. A tech savvy user (or me while developing) can then inspect and compare. Then it will check for safty, to _once Steam is stopped and backups are ready_ ask the user if the script should replace them. Again noticing the backup pathes before, to inspect. Lastly, with the confirmation, we can replace. Once more list the backups and tell exactly how to restore to the previous state.
> - [ ] 2\. Apply flag only
>   - _Treat --apply itself as sufficient consent once Steam is stopped and backups are ready._
> - [ ] 3\. Export patch only
>   - _Generate proposed replacement files elsewhere and leave installation into Steam entirely manual._
> - [ ] 4\. _Type something._
>
> </details>
>

› Create complete pydantic models for the important and/or touched steam files, so we can detect version/schema updates, which could be dangerous, immediatly.
The full steam file IO shall be locked down in the plan already.
Additionally, make it extendible, so later e.g. a gog launcher or epic launcher module could be added besides steam as well.

> › Implement the [Plan](./plans/002_game-collections-v1.md).

› Alright, write  up the expected result of running the generation for the given orange box file. Add a unittest to confirm they are equal. Commit. Only then run the test, and see if the expected result and actual result match, and fix if needed. Keep commiting as usual.

› implement a script for parsing humblebundle bundles.
It offers the monthly changing "choice", `humblebundle/choice/YYYY-MM.yml`, https://www.humblebundle.com/membership .
And sepearatly changing offers at https://www.humblebundle.com/bundles .
Those are a bit more tricky, as they often have different tiers.
They do seem to have a fixed ID as seen in the url, which is however not that helpful when looking at the files.
Therefore if you can figure out from when to when the bundle offer runs, that would be wonderful metadata.
Either the start or, if unavailable, the end date shall be the prefix of the id/name.
E.g. `humblebundle/bundle/YYYY-MM-DD_something-foobar-bundle-name/entire-16-item-bundle.yml`.
While already scraping that page, I'd like to save as much of the available metadata as possible.
If the listing format disallows for easy extending of the format of a collection, it shall be stored separately.
However, please collect and archive - one way or another:
1. Bundle URL, e.g. `https://www.humblebundle.com/games/arc-system-works-evo-collection`
2. Headline, e.g. _Play Fighting Games. Fight for Something Bigger._
3. Description, e.g. _What’s better than … disease treatment and research._
4. Category of the bundle, _Games_ (We skip _Books_ and _Software_)
5. Dates: from, to, crawl.
6. Charity, _Fight 4 Rare/Raiden Science Foundation_
7. Key expiration text, _Keys expire. Please redeem before July 17th, 2027._
8. Tiers, with their games:
   1. Name of the tier, e.g. _Entire 16 Item Bundle_, _13 Item Bundle_, _10 Item Bundle_
   2. Count of items.
   3. Price (minimal price) `{ "raw": "€5.11", value: 5.11, currency: "€" }
   4. List of games in that tier (including duplicates to other tiers). Those games need to store:
      1. Title, e.g. _KILL la KILL - IF_
      2. Retail price, _€19.99_ as split into an `Price` object as above.
      3. Youtube Link
      4. Coverart link
      5. Developer: `[{ "name": "Arc System Works", "url": "https://www.arcsystemworks.com/" }, { "name": "APLUS Co., Ltd.", "url": "https://www.arcsystemworks.com/developers/aplus-co-ltd/" }]`
      6. Redeem on, _Steam_, _GOG_, _Epic_, _Ubisoft_, …
      7. Platform, _Windows_, _Mac_, _Linux_ (list of one or multiple)
      8. Description, _The critically acclaimed 2013 anime … , the defender wins._
      9. Extra tags on the product, _Coupon_

› Ah, description shall use markdown conversion.

› Question answered.
> <details><summary>
>
>> 1. How should scraped games satisfy the current required `ids` field when Humble exposes no launcher app ID?
>> 2. How much source data should be retained beyond the normalized metadata you requested?
>> 3. What should one scraper invocation crawl by default?
>
> (click to expand)
>
> </summary>
>
>> **Game IDs** (1/3) <kbd>Single Select</kbd><br>
>> How should scraped games satisfy the current required `ids` field when Humble exposes no launcher app ID?
> - [ ] 1\. Humble IDs (Recommended)
>   - _Write `humblebundle:<machine-name>` now; lists validate but require later Steam/GOG ID enrichment before launcher sync._
> - [ ] 2\. Archive only
>   - _Write metadata archives but no standard game-list files until real storefront IDs can be resolved._
> - [x] 3\. Resolve stores
>   - _Add separate storefront searches/matching, with ambiguity handling, to try to produce Steam/GOG/Epic IDs automatically._
> - [ ] 4\. _Type something._
>
>> **Raw archive** (2/3) <kbd>Single Select</kbd><br>
>> How much source data should be retained beyond the normalized metadata you requested?
> - [ ] 1\. Embedded JSON (Recommended)
>   - _Keep normalized YAML plus the exact relevant embedded JSON payload for future reparsing, without archiving the full page._
> - [ ] 2\. Normalized only
>   - _Keep only strict normalized YAML, minimizing repository size but losing unmodeled source fields._
> - [ ] 3\. Full HTML
>   - _Keep normalized YAML and the complete fetched HTML for maximum fidelity at substantial repository growth._
> - [x] 4\. _Type something:_
>   - > What's embedded json mean? Does the humblebundle page already has a json providing all the data? in that case, yes. But make sure it's indented with 2 spaces and key sorted for best possible diff.
>
>> **Command scope** (3/3) <kbd>Single Select</kbd><br>
>> What should one scraper invocation crawl by default?
> - [x] 1\. Choice + all games (Recommended)
>   - _Discover the current Choice and every active Games bundle, with optional URL filters for focused reruns._
> - [ ] 2\. Explicit URLs
>   - _Require one or more bundle/Choice URLs and never crawl the listing automatically._
> - [ ] 3\. Separate modes
>   - _Require the caller to select either current Choice or discovered active Games bundles each run._
> - [ ] 4\. _Type something._
>
> </details>
>

› Question answered.
> <details><summary>
>
>> 1. What should happen when an item cannot be matched uniquely to a storefront ID?
>> 2. How should title mismatches and ambiguous storefront matches be corrected durably?
>> 3. Which storefront resolvers belong in this first implementation?
>
> (click to expand)
>
> </summary>
>
>> **Unresolved** (1/3) <kbd>Single Select</kbd><br>
>> What should happen when an item cannot be matched uniquely to a storefront ID?
> - [ ] 1\. Write partial + report (Recommended)
>   - _Archive every item, generate tier lists from resolved games only, and exit nonzero with a clear unresolved/ambiguous report._
> - [ ] 2\. Abort all output
>   - _Write nothing for that crawl unless every real game in every offer resolves uniquely._
> - [ ] 3\. Humble fallback
>   - _Use `humblebundle:<machine-name>` for unresolved items so every tier list is complete but not fully launcher-eligible._
> - [x] 4\. _Type something:_
>   - > If not clear, provide a list of possible results, so the user can easily choose. If that fails too (or the user presses the last "Other…" option), have the user paste in the store URL or direct numeric ID, or enter to "abort" finding it. In that case it will be `unresolved:humblebundle:…` in the standartised output. Note that `humble:…` ids can be used for the Humblebundle store.
>
>> **Overrides** (2/3) <kbd>Single Select</kbd><br>
>> How should title mismatches and ambiguous storefront matches be corrected durably?
> - [x] 1\. Checked-in map (Recommended)
>   - _Maintain a reviewed YAML mapping from Humble machine names to qualified storefront IDs or explicit ignore decisions._
> - [ ] 2\. Interactive prompts
>   - _Prompt during each crawl and save the selected result only in generated output._
> - [ ] 3\. Exact match only
>   - _Provide no override mechanism; unresolved items remain unresolved until upstream names align._
> - [ ] 4\. _Type something._
>
>> **Providers** (3/3) <kbd>Single Select</kbd><br>
>> Which storefront resolvers belong in this first implementation?
> - [ ] 1\. Steam first (Recommended)
>   - _Resolve Steam AppIDs through Valve's official catalog; archive other redeem methods as unresolved metadata behind a resolver interface._
> - [x] 2\. All via web search
>   - _Scrape/search GOG, Epic, and Ubisoft too, accepting brittle provider-specific heuristics._
>   - > Using the store's own search should lead to good results, because they usually sort by popularity etc.
> - [ ] 3\. Require overrides
>   - _Do no live catalog resolution; all qualified IDs must come from the checked-in override map._
> - [ ] 4\. _Type something._
>
> </details>
>

› Question answered.
> <details><summary>
>
>> 1. Which archived tier items should appear in the standard `.yml` game list?
>> 2. Where should normalized and source metadata live?
>
> (click to expand)
>
> </summary>
>
>> **List items** (1/2) <kbd>Single Select</kbd><br>
>> Which archived tier items should appear in the standard `.yml` game list?
> - [ ] 1\. All tier items (Recommended)
>   - _Preserve the advertised tier exactly; coupons/bonuses and unresolved games receive `unresolved:humblebundle:<machine-name>` unless mapped or ignored._
> - [x] 2\. Games only
>   - _Exclude coupons and bonuses from standard lists while retaining them fully in metadata._
> - [ ] 3\. Resolved only
>   - _Include only products with real storefront IDs, making lists syncable but potentially incomplete._
> - [ ] 4\. _Type something._
>
>> **Metadata** (2/2) <kbd>Single Select</kbd><br>
>> Where should normalized and source metadata live?
> - [ ] 1\. Beside lists (Recommended)
>   - _Store sorted two-space JSON sidecars beside each Choice file or tier directory; list discovery continues to read only `.yml`._
> - [x] 2\. Archive tree
>   - _Mirror list IDs under a separate top-level `archives/humblebundle/` tree._
> - [ ] 3\. Single catalog
>   - _Store all normalized and source data in centralized Humble catalog JSON files._
> - [ ] 4\. _Type something._
>
> </details>
>

› Run LPLP style from the beginnng of implementation

> › Implement the [Plan](./plans/003_humble-bundle-crawler-and-archive.md).

› For the lists, add a new item before the games, called references,
which shall contain either local file pathes (`../../../archives/humblebundle/choice/2026-07/metadata.json`)
or absolute repo pathes (similar to websites - so still relative to the repo root, `/archives/humblebundle/choice/2026-07/source.json`, the leading slash optional).
Format of a reference would be `{ name: str, path?: RelativePath|RepoPath, url?: URL }`.
Here it should be automatically filled with our written crawl extra data in the archive folder, and the sourced url (bundle URL).
If possible to mark the field as filepath in the schema to aid IDE completion, do so.

› You can complete my drafts in those files. Priotise adapting the scripts.

› You can complete & fix my drafts in those files. Priotise adapting the scripts.

› Write a `metadata.json` next to the lists in `/lists/humblebundle/bundle/YYYY-MM-DD_*/` consisting of a compact `{"name": "Bundle name", "version": "YYYY-MM-DD - YYYY-MM-DD"}`. JetBrains IDEs like PyCharm do show those in the folder tree view as folder annotations, which is helpful here as well. In the choice folder where every choice is a single item and no folder it however would not add any benifit.
Similarly, add the crawl date as `"version": "YYYY-MM-DD HH:MM:SS"` field to the already written `/archives/humblebundle/{bundle/YYYY-MM-DD_*,choice/YYYY-MM}/metadata.json` files.

