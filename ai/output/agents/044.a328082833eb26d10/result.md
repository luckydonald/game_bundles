Note: I'm in plan mode with read-only access, but this task is pure research/reporting (no edits requested), so I'll just answer directly without writing a plan file.

## 1. `complete_game_list` (src/game_collections/search.py:142-265)

```python
142	def complete_game_list(
143		raw: object,
144		providers: tuple[Provider, ...],
145		resolver: StorefrontResolver,
146		choose: SearchChooser,
147		mode: CompletionMode = "blank",
148		itad_resolve: ItadResolve | None = None,
149	) -> tuple[dict[str, Any], list[str]]:
150		"""Fill missing game IDs in a draft list and return unresolved names.
151	
152		``"isthereanydeal"`` in ``providers`` resolves
153		``unresolved:source:isthereanydeal:*`` markers via `itad_resolve` (see
154		`sources.isthereanydeal.resolver.resolve_isthereanydeal_markers`)
155		instead of the title-search flow every other provider uses.
156		"""
157		if "isthereanydeal" in providers and itad_resolve is None:
158			raise ValueError("provider 'isthereanydeal' requires itad_resolve")
159		# end if
160		if not isinstance(raw, Mapping):
161			raise ValueError("YAML list must contain an object")
162		# end if
163		completed = deepcopy(dict(raw))
164		games = completed.get("games")
165		if not isinstance(games, list) or not games:
166			raise ValueError("draft list must contain a non-empty games list")
167		# end if
168		unresolved: list[str] = []
169		games_out: list[dict[str, Any]] = []
170		for index, game in enumerate(games, start=1):
171			if not isinstance(game, dict):
172				raise ValueError(f"game {index} must contain an object")
173			# end if
174			name = game.get("name")
175			if not isinstance(name, str) or not name.strip():
176				raise ValueError(f"game {index} requires a non-empty name")
177			# end if
178			existing = game.get("ids", [])
179			if not isinstance(existing, list):
180				raise ValueError(f"game {name!r} ids must be a list")
181			# end if
182			if any(not isinstance(value, str) for value in existing):
183				raise ValueError(f"game {name!r} contains a non-string ID")
184			# end if
185			current = [QualifiedGameId.parse(value).compact() for value in existing]
186			searched = False
187			failed = False
188			resolved_any = False
189			split: list[ResolvedGame] | None = None
190			blank_eligible = not any(_is_proper_id(value) for value in current)
191			for provider in providers:
192				if provider == "isthereanydeal":
193					if not any(value.startswith(ITAD_UNRESOLVED_PREFIX) for value in current):
194						continue
195					# end if
196					searched = True
197					assert itad_resolve is not None  # checked up front
198					current = resolve_isthereanydeal_markers(current, itad_resolve)
199					if any(value.startswith(ITAD_UNRESOLVED_PREFIX) for value in current):
200						failed = True
201					# end if
202					continue
203				# end if
204				store_provider = cast(StoreName, provider)
205				should_search = blank_eligible if mode == "blank" else _should_search(
206					current, store_provider, mode
207				)
208				if not should_search:
209					continue
210				# end if
211				searched = True
212				prefix = _store_unresolved_prefix(store_provider)
213				current = [value for value in current if not value.startswith(prefix)]
214				if mode == "refetch_all":
215					current = [value for value in current if not value.startswith(f"{store_provider}:")]
216				# end if
217				results = resolve_title(name, (store_provider,), resolver, choose)
218				if len(results) > 1:
219					# The user declared "Multiple…" for this store: this title is
220					# actually several separate games. Re-resolve every requested
221					# store from scratch, per split sub-title, and stop treating
222					# this as one game entry.
223					store_providers = tuple(cast(StoreName, p) for p in providers if p != "isthereanydeal")
224					split = [
225						entry
226						for sub_title in (r.name for r in results)
227						for entry in resolve_title(sub_title, store_providers, resolver, choose)
228					]
229					break
230				# end if
231				found = results[0].ids
232				if found:
233					current.extend(found)
234					resolved_any = True
235					continue
236				# end if
237				marker_name = "-".join(name.casefold().split())
238				current.append(f"{prefix}{marker_name}")
239				failed = True
240			# end for
241			if split is not None:
242				group_id = f"multiple:{'-'.join(name.casefold().split())}"
243				for entry in split:
244					slug = "-".join(entry.name.casefold().split())
245					ids = list(dict.fromkeys(entry.ids)) or [f"unresolved:source:complete:{slug}"]
246					games_out.append({"name": entry.name, "ids": ids, "group": {"id": group_id, "name": name}})
247					if ids[0].startswith("unresolved:"):
248						unresolved.append(entry.name)
249					# end if
250				# end for
251				continue
252			# end if
253			if resolved_any:
254				current = [value for value in current if not value.startswith("unresolved:source:")]
255			# end if
256			game["ids"] = list(dict.fromkeys(current))
257			if searched and failed:
258				unresolved.append(name)
259			# end if
260			games_out.append(game)
261		# end for
262		completed["games"] = games_out
263		GameList.model_validate(completed)
264		return completed, unresolved
265	# end def complete_game_list
```

Note: when `split` is produced (line 224-228), each `entry.name` from the split (line 246) is appended into `games_out` with no check against names already added earlier in the outer `for index, game in enumerate(games...)` loop (line 170), nor against other split groups' entry names. Dedupe/name-collision would need to be inserted around line 243-249 (per-entry, before/while appending) or as a pass over `games_out` before line 262 where `GameList.model_validate(completed)` currently is the only place duplicate names get caught (and only as a hard validation error, not a merge/dedupe).

## 2. `Game` and `GameList` (src/game_collections/models.py:63-192)

```python
63	class Game(StrictModel):
64		"""A named game with one or more storefront identities."""
65	
66		name: NonEmptyString
67		ids: list[NonEmptyString] = Field(min_length=1)
68		group: GameGroup | None = None
69		# Qualified IDs of other games that must be owned/present for this entry to make sense,
70		# e.g. the free base game a DLC entry needs. Purely data, no launcher-specific behavior.
71		requires: list[NonEmptyString] = Field(default_factory=list)
72	
73		@model_validator(mode="after")
74		def validate_ids(self) -> Self:
75			parsed = [QualifiedGameId.parse(raw) for raw in self.ids]
76			compact = [identifier.compact() for identifier in parsed]
77			if len(compact) != len(set(compact)):
78				raise ValueError("game contains duplicate qualified IDs")
79			# end if
80			self.ids = compact
81	
82			if self.requires:
83				required_parsed = [QualifiedGameId.parse(raw) for raw in self.requires]
84				required_compact = [identifier.compact() for identifier in required_parsed]
85				if len(required_compact) != len(set(required_compact)):
86					raise ValueError("game contains duplicate qualified required IDs")
87				# end if
88				self.requires = required_compact
89			# end if
90			return self
91		# end def validate_ids
92	
93		@property
94		def qualified_ids(self) -> tuple[QualifiedGameId, ...]:
95			"""Return parsed identities without storing a second representation."""
96			return tuple(QualifiedGameId.parse(raw) for raw in self.ids)
97		# end def qualified_ids
98	
99		@property
100		def qualified_ids_required(self) -> tuple[QualifiedGameId, ...]:
101			"""Return parsed required-game identities without storing a second representation."""
102			return tuple(QualifiedGameId.parse(raw) for raw in self.requires)
103		# end def qualified_ids_required
104	
105	# end class Game
```

```python
129	def duplicate_qualified_ids(games: list[Game]) -> list[str]:
130		"""Return compact qualified IDs that appear on more than one game, if any."""
131		identities = [identifier.compact() for game in games for identifier in game.qualified_ids]
132		seen: set[str] = set()
133		duplicates: list[str] = []
134		for identity in identities:
135			if identity in seen and identity not in duplicates:
136				duplicates.append(identity)
137			# end if
138			seen.add(identity)
139		# end for
140		return duplicates
141	# end def duplicate_qualified_ids
142	
143	
144	class GameList(StrictModel):
145		"""The complete contents of one ``lists/**/*.yml`` file."""
146	
147		schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
148		name: NonEmptyString
149		tier: Annotated[int, Field(ge=1)] | None = None
150		pick_quota: Annotated[int, Field(ge=1)] | None = None
151		references: list[Reference] = Field(default_factory=list)
152		# Crawler module slugs (e.g. "humblebundle", "isthereanydeal") that have
153		# contributed to or verified this list. Lets a later crawler tell an
154		# already-covered bundle from one it has actually cross-checked.
155		crawlers: list[NonEmptyString] = Field(default_factory=list)
156		games: list[Game] = Field(min_length=1)
157		# Games an authoritative re-crawl no longer lists, quarantined here instead of
158		# deleted so they can be recovered if they reappear. Excluded from ownership,
159		# eligibility, and sync consideration wherever `games` is read for that purpose.
160		invalid: list[Game] = Field(default_factory=list)
161	
162		@model_validator(mode="after")
163		def validate_games(self) -> Self:
164			names = [game.name.casefold() for game in self.games]
165			if len(names) != len(set(names)):
166				raise ValueError("list contains duplicate game names")
167			# end if
168	
169			if duplicate_qualified_ids(self.games):
170				raise ValueError("list contains duplicate qualified game IDs")
171			# end if
172	
173			group_names: dict[str, str] = {}
174			for game in self.games:
175				if game.group is None:
176					continue
177				# end if
178				existing_name = group_names.get(game.group.id)
179				if existing_name is None:
180					group_names[game.group.id] = game.group.name
181				elif existing_name != game.group.name:
182					raise ValueError(f"games in group {game.group.id!r} have inconsistent group names")
183				# end if
184			# end for
185	
186			if self.pick_quota is not None and self.pick_quota > len(self.games):
187				raise ValueError(f"pick_quota {self.pick_quota} exceeds the list's {len(self.games)} game(s)")
188			# end if
189			return self
190		# end def validate_games
191	
192	# end class GameList
```

Note: `validate_games` (line 164-171) is where duplicate names/qualified-IDs across the whole list are caught (case-fold on name, line 164; `duplicate_qualified_ids` on IDs, line 169) — this is the hard-fail point `complete_game_list`'s `GameList.model_validate(completed)` call (search.py:263) hits if the split-name insertion in item 1 produces a collision; there's no soft dedupe/merge logic here, only rejection.

## 3. `_resolve_title` (src/game_collections/sources/humblebundle/resolver.py:298-398)

```python
298	    def _resolve_title(
299			self,
300			title: str,
301			stores: list[str],
302			cache_key: str,
303			mapping: HumbleResolutionMap,
304			allow_multiple: bool = True,
305		) -> list[ResolvedGame]:
306			"""Resolve one title across `stores`, caching the plain (unsplit) result under `cache_key`.
307	
308			Returns more than one `ResolvedGame` when the user declares "Multiple…" for some store -
309			names are then collected and resolved one at a time, immediately, via `_collect_name`
310			(each re-resolved from scratch across every store, `allow_multiple=False` so a name
311			collected this way can't itself be split again, cached under its own compound key so
312			re-runs don't re-prompt; a unique exact match found this way is announced via
313			`_announce_exact_match` for transparency, since it would otherwise happen silently) - or
314			when a unique exact match turns out to be a Steam package/"Sub" (e.g. an "Edition"
315			bundling a base app + its DLCs into one purchase, with no single matching app page) - that
316			Sub is expanded into one entry per app it contains instead of being kept as an inert
317			`steam:sub/<id>` (which, like a Steam retail bundle, can't drive ownership matching on its
318			own), each cached under its own compound key with the appid already known, no re-search
319			needed. `allow_multiple=False` also omits the "Multiple…" row itself from the menu.
320			"""
321			existing = mapping.games.get(cache_key)
322			if existing is not None:
323				return [ResolvedGame(name=title, ids=list(existing))]
324			# end if
325			ids: list[str] = []
326			for store_value in stores:
327				typed_provider = cast(StoreName, store_value)
328				try:
329					candidates = (
330						self._search_steam(title) if typed_provider == "steam" else self.search(typed_provider, title)
331					)
332				except (OSError, RuntimeError):
333					candidates = []
334				# end try
335				exact = [
336					candidate for candidate in candidates if normalized_title(candidate.title) == normalized_title(title)
337				]
338				if len(exact) == 1:
339					match = exact[0]
340					sub_id = (
341						match.qualified_id.removeprefix("steam:sub/")
341						if typed_provider == "steam" and match.qualified_id.startswith("steam:sub/")
343						else None
344					)
345					sub_apps = self._resolve_steam_sub(sub_id) if sub_id is not None else None
346					if sub_apps is not None:
347						results: list[ResolvedGame] = []
348						for index, (appid, name) in enumerate(sub_apps, start=1):
349							split_ids = [f"steam:{appid}"]
350							mapping.games[f"{cache_key}::{index}"] = split_ids
351							results.append(ResolvedGame(name=name, ids=split_ids))
352						# end for
353						return results
354					# end if
355					if not allow_multiple:
356						self._announce_exact_match(match.qualified_id, match.url)
357					# end if
358					ids.append(match.qualified_id)
359					continue
360				# end if
361				store_resolved = False
362				while not store_resolved:
363					selected = self._choose(
364						title, typed_provider, candidates, allow_multiple=allow_multiple, interleaved=True
365					)
366					if selected is None:
367						store_resolved = True
368						continue
369					# end if
370					if isinstance(selected, EnterMultiple):
371						multiple_results: list[ResolvedGame] = []
372						count = 0
373						while True:
374							name = self._collect_name(count)
375							if name is None:
376								break
377							# end if
378							count += 1
379							multiple_results.extend(
380								self._resolve_title(name, stores, f"{cache_key}::{count}", mapping, allow_multiple=False)
381							)
382						# end while
383						if not multiple_results:
384							continue
385						# end if
386						return multiple_results
387					# end if
388					ids.append(parse_store_identity(typed_provider, selected))
389					store_resolved = True
390				# end while
391			# end for
392			if not ids:
393				ids.append(f"unresolved:source:humblebundle:{cache_key}")
394			# end if
395			deduped = list(dict.fromkeys(ids))
396			mapping.games[cache_key] = deduped
397			return [ResolvedGame(name=title, ids=deduped)]
398		# end def _resolve_title
```

`collect_one_name` usage: only reached via `EnterMultiple` handling above, at line 374: `name = self._collect_name(count)` inside the `while True` loop (373-382) that keeps calling it until it returns `None` (376), collecting one sub-title per iteration and immediately recursing into `_resolve_title(name, stores, f"{cache_key}::{count}", mapping, allow_multiple=False)` (380) — each collected name is resolved independently, per-store, with no check against names already collected in this same loop or already resolved elsewhere in the archive (`resolve_archive`, lines 428-488, dedupes only by `item.machine_name` at line 439, not by resulting `ResolvedGame.name`). This is the analogous point where a name-collision/dedupe check would need to be inserted (either inside the `while True` loop at line 373-382, comparing new `name` against previously collected names, or in `resolve_archive` when building `resolutions`/`distinct`).