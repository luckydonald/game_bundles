Research complete. Since this is pure investigation/reporting (no code changes), I'm delivering the findings directly rather than writing a plan file.

**Repo check (Q5):** `grep -rniE "licensecache|appinfo|packageinfo|binary.?vdf"` across the repo returns nothing. The only hits for the broader pattern were `GetOwnedGames`/`owned.?games` in `api.py`, `models.py`, `adapter.py`, and `tests/test_steam_adapter.py` — the existing Web API client itself, not prior investigation of local files. No fixtures, comments, or binary-VDF parsing code exist anywhere in the repo. `discovery.py` only parses `config/loginusers.vdf` via the text `vdf` package with a `DuplicateRejectingDict` mapper.

**Candidate verdicts:**

1. `userdata/<accountid>/config/licensecache.vdf` — I cannot confirm this file exists with this name/path with any confidence. Confidence: low. I don't have solid recollection of Valve documenting or shipping a per-user `licensecache.vdf`; this may be a conflation with `appcache/stats/` or with third-party tools that build their own license cache from `packageinfo.vdf`. Treat as unverified — do not build logic assuming it exists.

2. `appcache/appinfo.vdf` — Contains per-app metadata (name, launch config, etc.) for apps the client has cached info for (owned + often many not-owned apps it has seen). Format: **binary VDF** (custom Valve binary KeyValues format with a magic header, not parseable by the text `vdf` package). Does not itself contain ownership/license list. Confidence: high on format, medium on scope.

3. `appcache/packageinfo.vdf` — This is the closer candidate for "what's owned": package (sub) definitions include `appids`, billing type, etc. However, ownership of *this account* is determined by the license list (packageids a user holds), which Steam client keeps elsewhere (in-memory/binary caches, not this file alone). Format: **binary VDF**, same header family as appinfo.vdf. Confidence: medium.

4. `userdata/<id>/config/localconfig.vdf` — text VDF, contains client settings, recently-played, some app overrides — **not** a full ownership list, and skews toward ever-launched/configured apps. Confidence: high.

5. `userdata/<id>/7/remote/sharedconfig.vdf` — text VDF, per-game cloud-synced UI state (collections, last-played) — **not** ownership. Confidence: high.

6. `steamapps/appmanifest_*.acf` — text ACF (VDF-like), **installed-only**, not full ownership. Confidence: high.

7. `steamapps/libraryfolders.vdf` — text VDF, lists library folders and installed appids per folder — **installed-only**. Confidence: high.

**Bottom line for Q1:** No local file reliably gives the full owned/licensed list without either binary-VDF parsing of appcache files (uncertain completeness/reliability) or the Web API.

**Q4:** No — `STEAM_WEB_API_KEY` is never cached or derivable locally; it's a developer secret issued via the web dev portal, unrelated to client-side credential/session files.