…
esolved = _complete_one_target(file, selected, resolver, selected_mode, itad_resolve)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/cli.py", line 644, in _complete_one_target
    completed, unresolved = complete_game_list(
                            ~~~~~~~~~~~~~~~~~~^
        raw,
        ^^^^
    ...<4 lines>...
        itad_resolve=itad_resolve,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/user/git/luckydonald/game_collections/src/game_collections/search.py", line 222, in complete_game_list
    itad_result = resolve_isthereanydeal_markers(current, itad_resolve)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 265, in resolve_isthereanydeal_markers
    resolution = resolve(slug)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/cli.py", line 733, in itad_resolve
    return resolve_game_with_aliases(slug, alias_groups, resolve_one)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 220, in resolve_game_with_aliases
    own = resolve_one(slug)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/cli.py", line 721, in resolve_one
    resolution = resolve_game(
        slug,
    ...<3 lines>...
        datetime.now(UTC),
    )
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 173, in resolve_game
    splits = tuple(
             ^^^^^
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 174, in <genexpr>
    resolve_game(entry_slug, fetch_detail_page, fetch_deals, resolve_redirect, crawled, _seen=seen)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 150, in resolve_game
    deals_payload, deals_resolved = _deal_urls(slug, detail.gid, fetch_deals, resolve_redirect)
                                    ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py", line 74, in _deal_urls
    resolved_url = resolve_redirect(url)
  File "/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/crawler.py", line 205, in resolve_redirect
    response.raise_for_status()
    ~~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/home/user/git/luckydonald/game_collections/.venv/lib64/python3.14/site-packages/httpx/_models.py", line 829, in raise_for_status
    raise HTTPStatusError(message, request=request, response=self)
httpx.HTTPStatusError: Client error '404 Not Found' for url 'https://www.gamesload.de/product.html?REF=822173'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404

[exited with code 0]
