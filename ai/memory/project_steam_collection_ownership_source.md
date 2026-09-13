---
name: project_steam_collection_ownership_source
description: "Steam ownership lookup gained a third source reading a manually curated local collection (\"manual-all\")"
metadata: 
  node_type: memory
  type: project
  originSessionId: a808247f-045f-4315-84b5-49fb38c66f8e
---

As of 2026-07-13, `eligible steam`/`sync steam` support a third ownership source alongside `--source api` (Web API + `STEAM_WEB_API_KEY`) and `--source installed` (local appmanifest scan): `--source collection` / `--collection NAME` (implies that source, defaults to name `manual-all`). It reads a user-maintained, non-dynamic Steam collection straight out of the local cloud-storage config (`SteamFileGateway.read_collection` in `src/game_collections/launchers/steam/io.py`, `owned_app_ids_from_collection` in `adapter.py`).

**Why:** the user manually drags every owned game into a self-created Steam collection named `manual-all`, giving a full local ownership snapshot without needing `STEAM_WEB_API_KEY`. Steam's built-in "All Games" view is *not* a stored `user-collections.*` entry — it's computed client-side — so it can't be read this way; that's why the feature relies on the user's own static collection instead. Filter/dynamic collections are explicitly rejected (no static `added` list to read).

**How to apply:** if asked to extend Steam ownership sources further, `read_collection` already has the case-insensitive name-lookup + not-found/dynamic-collection error handling pattern to follow. README.md documents the exact in-Steam-UI steps for creating a `manual-all` collection — keep that wording in sync if the UI flow is described elsewhere.
