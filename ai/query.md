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

