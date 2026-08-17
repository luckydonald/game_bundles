"""Command-line interface for game list validation and synchronization."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Annotated, Literal

import typer
import yaml

from game_collections.apply.config import ApplySelection, DEFAULT_SELECTION_CONFIG_PATH, SelectionLoadError, excluded_list_ids, load_selection, save_selection
from game_collections.lists import ListLoadError, LoadedGameList, discover_game_lists
from game_collections.migrate_tiers import (
    TierMigrationError,
    apply_migration_step,
    plan_migration,
    step_would_change,
)
from game_collections.completion import MissingHandling
from game_collections.launchers.steam.adapter import (
    SteamAdapter,
    SteamOptions,
    SteamTierMode,
    owned_app_ids_from_api,
    owned_app_ids_from_collection,
    owned_app_ids_from_installed,
)
from game_collections.launchers.steam.api import SteamApiClient
from game_collections.launchers.steam.discovery import discover_steam_root
from game_collections.launchers.steam.io import SteamFileGateway, SteamIoError, default_staging_root
from game_collections.schema import write_schema
from game_collections.schema import write_dailyindiegame_schema
from game_collections.schema import write_greenmangaming_schema
from game_collections.schema import write_humblebundle_schema
from game_collections.schema import write_isthereanydeal_schema
from game_collections.schema import write_isthereanydeal_game_schema
from game_collections.search import complete_game_list, completion_mode, selected_providers
from game_collections.sources.dailyindiegame.crawler import (
    CrawledDigOffer,
    DigBrowserClient,
    crawl_dig_offers,
    write_dig_offer,
)
from game_collections.sources.greenmangaming.crawler import (
    CrawledGmgOffer,
    GmgHttpClient,
    crawl_gmg_offers,
    write_gmg_offer,
)
from game_collections.sources.greenmangaming.crawler import write_resolution_map as write_gmg_resolution_map
from game_collections.sources.greenmangaming.models import GmgItem
from game_collections.sources.greenmangaming.resolver import (
    StorefrontResolver as GmgStorefrontResolver,
    load_resolution_map as load_gmg_resolution_map,
)
from game_collections.sources.humblebundle.crawler import (
    CrawledHumbleOffer,
    HumbleHttpClient,
    crawl_humble_offers,
    write_humble_offer,
    write_resolution_map,
)
from game_collections.sources.humblebundle.models import HumbleItem
from game_collections.sources.humblebundle.resolver import (
    StoreCandidate,
    StoreName,
    StorefrontResolver,
    load_resolution_map,
)
from game_collections.sources.isthereanydeal.crawler import (
    CrawledItadOffer,
    ItadHttpClient,
    crawl_itad_offers,
    write_itad_offer,
)
from game_collections.sources.isthereanydeal.game_alias_config import load_game_alias_config
from game_collections.sources.isthereanydeal.provider_config import load_provider_config
from game_collections.sources.isthereanydeal.resolver import (
    ItadGameResolution,
    resolve_game,
    resolve_game_with_aliases,
    write_itad_game_archive,
)
from game_collections.sources.isthereanydeal.shop_config import load_shop_config


app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
scrape_app = typer.Typer(no_args_is_help=True)
app.add_typer(scrape_app, name="scrape")

class SteamAutoSourceError(ValueError):
    """Every automatic Steam ownership source failed."""

# end class SteamAutoSourceError


def _lists_root(path: Path | None) -> Path:
    return path or Path.cwd() / "lists"
# end def _lists_root


def _discover_selected_game_lists(
    lists_root: Path,
    selection_config: Path,
    on_progress: Callable[[int, int, Path], None] | None = None,
) -> list[LoadedGameList]:
    """Discover lists, dropping any explicitly excluded by a saved selection config."""
    selection = load_selection(selection_config)
    excluded = excluded_list_ids(selection)
    game_lists = discover_game_lists(lists_root, on_progress=on_progress)
    if not excluded:
        return game_lists
    # end if
    return [game_list for game_list in game_lists if game_list.id not in excluded]
# end def _discover_selected_game_lists


def _echo_list_progress(index: int, total: int, path: Path) -> None:
    typer.echo(f"Loading list {index}/{total}: {path.name}")
# end def _echo_list_progress


@app.command("validate")
def validate_command(
    path: Annotated[Path | None, typer.Argument(help="Lists root; defaults to ./lists.")] = None,
) -> None:
    """Validate every YAML game list."""
    try:
        loaded = discover_game_lists(_lists_root(path))
    except (OSError, ValueError, ListLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
    typer.echo(f"Validated {len(loaded)} game list(s).")
# end def validate_command


@app.command("list")
def list_command(
    path: Annotated[Path | None, typer.Option("--lists-root")] = None,
) -> None:
    """Print all path-derived IDs and display names."""
    try:
        loaded = discover_game_lists(_lists_root(path))
    except (OSError, ValueError, ListLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
    for game_list in loaded:
        typer.echo(f"{game_list.id}\t{game_list.data.name}")
    # end for
# end def list_command


@app.command("migrate-tiers")
def migrate_tiers_command(
    path: Annotated[Path | None, typer.Option("--lists-root")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Write changes; default is dry-run.")] = False,
) -> None:
    """Rename tier-shaped bundle lists to `bundle.yml`/`tier-N.yml` and set `tier`."""
    lists_root = _lists_root(path)
    repository_root = Path.cwd().resolve()
    try:
        steps = plan_migration(lists_root)
    except (OSError, ValueError, TierMigrationError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try

    changed = 0
    for step in steps:
        try:
            if not step_would_change(step, lists_root):
                continue
            # end if
            changed += 1
            relative_old = step.old_path.relative_to(lists_root)
            relative_new = step.new_path.relative_to(lists_root)
            tier_note = f"tier={step.tier}" if step.tier is not None else "tier=(none)"
            if apply:
                apply_migration_step(step, lists_root, repository_root)
                typer.echo(f"migrated: {relative_old} -> {relative_new} ({tier_note})")
            else:
                typer.echo(f"would migrate: {relative_old} -> {relative_new} ({tier_note})")
            # end if
        except (OSError, ValueError, ListLoadError, TierMigrationError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        # end try
    # end for
    if apply:
        typer.echo(f"Migrated {changed} list(s).")
    else:
        typer.echo(f"Dry run only: {changed} list(s) would change. Pass --apply to write.")
    # end if
# end def migrate_tiers_command


@app.command("schema")
def schema_command(
    output: Annotated[
        Path,
        typer.Option("--output", help="Generated JSON Schema path."),
    ] = Path("schemas/game-list.schema.json"),
    humblebundle_output: Annotated[
        Path,
        typer.Option("--humblebundle-output", help="Generated Humble archive JSON Schema path."),
    ] = Path("schemas/humblebundle-archive.schema.json"),
    dailyindiegame_output: Annotated[
        Path,
        typer.Option("--dailyindiegame-output", help="Generated DailyIndieGame archive JSON Schema path."),
    ] = Path("schemas/dailyindiegame-archive.schema.json"),
    greenmangaming_output: Annotated[
        Path,
        typer.Option("--greenmangaming-output", help="Generated Green Man Gaming archive JSON Schema path."),
    ] = Path("schemas/greenmangaming-archive.schema.json"),
    isthereanydeal_output: Annotated[
        Path,
        typer.Option("--isthereanydeal-output", help="Generated isthereanydeal.com archive JSON Schema path."),
    ] = Path("schemas/isthereanydeal-archive.schema.json"),
    isthereanydeal_game_output: Annotated[
        Path,
        typer.Option(
            "--isthereanydeal-game-output",
            help="Generated isthereanydeal.com per-game archive JSON Schema path.",
        ),
    ] = Path("schemas/isthereanydeal-game-archive.schema.json"),
) -> None:
    """Generate JSON Schemas from the runtime Pydantic models."""
    write_schema(output)
    write_humblebundle_schema(humblebundle_output)
    write_dailyindiegame_schema(dailyindiegame_output)
    write_greenmangaming_schema(greenmangaming_output)
    write_isthereanydeal_schema(isthereanydeal_output)
    write_isthereanydeal_game_schema(isthereanydeal_game_output)
    typer.echo(output)
    typer.echo(humblebundle_output)
    typer.echo(dailyindiegame_output)
    typer.echo(greenmangaming_output)
    typer.echo(isthereanydeal_output)
    typer.echo(isthereanydeal_game_output)
# end def schema_command


def _choose_store_candidate(
    item: HumbleItem,
    provider: StoreName,
    candidates: list[StoreCandidate],
) -> str | None:
    typer.echo(f"Resolve {item.title!r} on {provider}:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {candidate.title} — {candidate.qualified_id}")
        typer.echo(f"     {candidate.url}")
    # end for
    other = len(candidates) + 1
    typer.echo(f"  {other}. Other…")
    while True:
        selection = typer.prompt("Select a result", default=str(other))
        if selection.isdecimal() and 1 <= int(selection) <= len(candidates):
            return candidates[int(selection) - 1].qualified_id
        # end if
        if selection == str(other):
            manual = typer.prompt(
                "Paste the store URL or direct ID; leave blank for unresolved",
                default="",
                show_default=False,
            )
            return manual or None
        # end if
        typer.echo(f"Enter a number from 1 to {other}.", err=True)
    # end while
# end def _choose_store_candidate


def _choose_search_candidate(
    title: str,
    provider: StoreName,
    candidates: list[StoreCandidate],
) -> str | None:
    """Prompt for one storefront result while completing a draft list."""
    item = HumbleItem(
        machine_name="search",
        title=title,
        item_type="game",
        is_game=True,
        redeem_on=[provider],
    )
    return _choose_store_candidate(item, provider, candidates)
# end def _choose_search_candidate


def _print_search_results(
    title: str,
    providers: tuple[StoreName, ...],
    resolver: StorefrontResolver,
) -> None:
    """Print ranked candidates for a title without changing files."""
    for provider in providers:
        typer.echo(f"{provider}:")
        candidates = resolver.search(provider, title)
        if not candidates:
            typer.echo("  No results.")
            continue
        # end if
        for candidate in candidates:
            typer.echo(f"  {candidate.title} — {candidate.qualified_id}")
            typer.echo(f"    {candidate.url}")
        # end for
    # end for
# end def _print_search_results


@app.command("search")
def search_command(
    name: Annotated[str, typer.Argument(help="Game name to search for.")],
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Storefront to search; defaults to all."),
    ] = "all",
) -> None:
    """Search storefronts for a game name."""
    client = HumbleHttpClient()
    try:
        providers = selected_providers(provider, default="all")
        resolver = StorefrontResolver(client.fetch, lambda _item, _provider, _candidates: None)
        _print_search_results(name, providers, resolver)
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
    # end try
# end def search_command


@app.command("complete")
def complete_command(
    file: Annotated[Path, typer.Argument(help="Draft YAML game list to complete in place.")],
    providers: Annotated[
        list[str] | None,
        typer.Option(
            "--provider",
            "--store",
            "-p",
            help="Storefront(s) to search; repeat or comma-separate. Defaults to steam.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Selection mode: blank, missing, unresolved, or refetch_all.",
        ),
    ] = "blank",
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    game_alias_config_path: Annotated[Path, typer.Option("--game-alias-config")] = Path(
        "config/isthereanydeal-game-aliases.yml"
    ),
) -> None:
    """Complete storefront IDs in a draft YAML game list."""
    client = HumbleHttpClient()
    itad_client: ItadHttpClient | None = None
    try:
        selected = selected_providers(providers, default="steam")
        selected_mode = completion_mode(mode)
        resolver = StorefrontResolver(client.fetch, lambda _item, _provider, _candidates: None)
        itad_resolve = None
        if "isthereanydeal" in selected:
            itad_client = ItadHttpClient()
            alias_groups = load_game_alias_config(game_alias_config_path)

            def resolve_one(slug: str) -> ItadGameResolution:
                assert itad_client is not None
                resolution = resolve_game(
                    slug,
                    itad_client.fetch,
                    itad_client.fetch_deals,
                    itad_client.resolve_redirect,
                    datetime.now(UTC),
                )
                write_itad_game_archive(resolution, archive_root)
                return resolution
            # end def resolve_one

            def itad_resolve(slug: str) -> ItadGameResolution:
                return resolve_game_with_aliases(slug, alias_groups, resolve_one)
            # end def itad_resolve
        # end if
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        completed, unresolved = complete_game_list(
            raw,
            selected,
            resolver,
            _choose_search_candidate,
            selected_mode,
            itad_resolve=itad_resolve,
        )
        file.write_text(
            yaml.safe_dump(completed, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        typer.echo(f"Updated {file}.")
        for title in unresolved:
            typer.echo(f"unresolved: {title}", err=True)
        # end for
        if unresolved:
            raise typer.Exit(1)
        # end if
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
        if itad_client is not None:
            itad_client.close()
        # end if
    # end try
# end def complete_command


@scrape_app.command("humblebundle")
def scrape_humblebundle_command(
    urls: Annotated[
        list[str] | None,
        typer.Option("--url", help="Crawl only this Choice or Games URL; repeatable."),
    ] = None,
    lists_root: Annotated[Path, typer.Option("--lists-root")] = Path("lists"),
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    resolution_map: Annotated[Path, typer.Option("--resolution-map")] = Path(
        "config/humblebundle-store-ids.yml"
    ),
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Record unresolved IDs instead of prompting."),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-resolve every offer, ignoring already-archived output."),
    ] = False,
) -> None:
    """Archive current Humble Choice and active Games bundles."""
    repository_root = Path.cwd().resolve()
    client = HumbleHttpClient()
    choose = (
        (lambda _item, _provider, _candidates: None)
        if non_interactive
        else _choose_store_candidate
    )
    written_count = 0

    def on_offer(offer: CrawledHumbleOffer) -> None:
        nonlocal written_count
        paths = write_humble_offer(
            offer,
            lists_root=lists_root,
            archive_root=archive_root,
            repository_root=repository_root,
        )
        written_count += len(paths)
        typer.echo(f"Archived {offer.archive.name}: {len(paths)} file(s)")
        write_resolution_map(resolution_map, mapping)
    # end def on_offer

    try:
        mapping = load_resolution_map(resolution_map)
        resolver = StorefrontResolver(client.fetch, choose)
        report = crawl_humble_offers(
            client.fetch,
            resolver,
            mapping,
            urls,
            archive_root=None if refresh else archive_root,
            log=typer.echo,
            on_offer=on_offer,
        )
        unresolved = sorted(
            machine_name
            for machine_name, ids in mapping.games.items()
            if any(value.startswith("unresolved:") for value in ids)
        )
        for machine_name in unresolved:
            typer.echo(f"unresolved: {machine_name}", err=True)
        # end for
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        # end for
        typer.echo(
            f"Wrote {written_count} file(s) for {len(report.offers)} offer(s); "
            f"{len(unresolved)} unresolved game(s)."
        )
        if report.errors:
            raise typer.Exit(1)
        # end if
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
    # end try
# end def scrape_humblebundle_command


@scrape_app.command("dailyindiegame")
def scrape_dailyindiegame_command(
    urls: Annotated[
        list[str] | None,
        typer.Option("--url", help="Crawl only this weekly bundle URL; repeatable."),
    ] = None,
    lists_root: Annotated[Path, typer.Option("--lists-root")] = Path("lists"),
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-fetch every bundle, ignoring already-archived output."),
    ] = False,
) -> None:
    """Archive currently listed DailyIndieGame Steam bundles."""
    repository_root = Path.cwd().resolve()
    client = DigBrowserClient()
    written_count = 0

    def on_offer(offer: CrawledDigOffer) -> None:
        nonlocal written_count
        paths = write_dig_offer(
            offer,
            lists_root=lists_root,
            archive_root=archive_root,
            repository_root=repository_root,
        )
        written_count += len(paths)
        typer.echo(f"Archived {offer.archive.name}: {len(paths)} file(s)")
    # end def on_offer

    try:
        report = crawl_dig_offers(
            client.fetch,
            urls,
            archive_root=None if refresh else archive_root,
            log=typer.echo,
            on_offer=on_offer,
        )
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        # end for
        typer.echo(f"Wrote {written_count} file(s) for {len(report.offers)} offer(s).")
        if report.errors:
            raise typer.Exit(1)
        # end if
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
    # end try
# end def scrape_dailyindiegame_command


def _choose_gmg_store_candidate(
    item: GmgItem,
    provider: StoreName,
    candidates: list[StoreCandidate],
) -> str | None:
    typer.echo(f"Resolve {item.title!r} on {provider}:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {candidate.title} — {candidate.qualified_id}")
        typer.echo(f"     {candidate.url}")
    # end for
    other = len(candidates) + 1
    typer.echo(f"  {other}. Other…")
    while True:
        selection = typer.prompt("Select a result", default=str(other))
        if selection.isdecimal() and 1 <= int(selection) <= len(candidates):
            return candidates[int(selection) - 1].qualified_id
        # end if
        if selection == str(other):
            manual = typer.prompt(
                "Paste the store URL or direct ID; leave blank for unresolved",
                default="",
                show_default=False,
            )
            return manual or None
        # end if
        typer.echo(f"Enter a number from 1 to {other}.", err=True)
    # end while
# end def _choose_gmg_store_candidate


@scrape_app.command("greenmangaming")
def scrape_greenmangaming_command(
    urls: Annotated[
        list[str] | None,
        typer.Option("--url", help="Crawl only this bundle detail URL; repeatable."),
    ] = None,
    lists_root: Annotated[Path, typer.Option("--lists-root")] = Path("lists"),
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    resolution_map: Annotated[Path, typer.Option("--resolution-map")] = Path(
        "config/greenmangaming-store-ids.yml"
    ),
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", help="Record unresolved IDs instead of prompting."),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-fetch every bundle, ignoring already-archived output."),
    ] = False,
) -> None:
    """Archive currently listed Green Man Gaming video-games bundles."""
    repository_root = Path.cwd().resolve()
    client = GmgHttpClient()
    choose = (
        (lambda _item, _provider, _candidates: None)
        if non_interactive
        else _choose_gmg_store_candidate
    )
    written_count = 0

    def on_offer(offer: CrawledGmgOffer) -> None:
        nonlocal written_count
        paths = write_gmg_offer(
            offer,
            lists_root=lists_root,
            archive_root=archive_root,
            repository_root=repository_root,
        )
        written_count += len(paths)
        typer.echo(f"Archived {offer.archive.name}: {len(paths)} file(s)")
        write_gmg_resolution_map(resolution_map, mapping)
    # end def on_offer

    try:
        mapping = load_gmg_resolution_map(resolution_map)
        resolver = GmgStorefrontResolver(client.fetch, choose)
        report = crawl_gmg_offers(
            client.fetch,
            resolver,
            mapping,
            urls,
            archive_root=None if refresh else archive_root,
            log=typer.echo,
            on_offer=on_offer,
        )
        unresolved = sorted(
            product_id
            for product_id, ids in mapping.games.items()
            if any(value.startswith("unresolved:") for value in ids)
        )
        for product_id in unresolved:
            typer.echo(f"unresolved: {product_id}", err=True)
        # end for
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        # end for
        typer.echo(
            f"Wrote {written_count} file(s) for {len(report.offers)} offer(s); "
            f"{len(unresolved)} unresolved game(s)."
        )
        if report.errors:
            raise typer.Exit(1)
        # end if
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
    # end try
# end def scrape_greenmangaming_command


@scrape_app.command("isthereanydeal")
def scrape_isthereanydeal_command(
    tabs: Annotated[
        list[str] | None,
        typer.Option("--tab", help="Discovery tab(s) to crawl: live, expired, pending. Repeatable."),
    ] = None,
    lists_root: Annotated[Path, typer.Option("--lists-root")] = Path("lists"),
    archive_root: Annotated[Path, typer.Option("--archive-root")] = Path("archives"),
    provider_config_path: Annotated[Path, typer.Option("--provider-config")] = Path(
        "config/isthereanydeal-providers.yml"
    ),
    shop_config_path: Annotated[Path, typer.Option("--shop-config")] = Path("config/isthereanydeal-shops.yml"),
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-fetch every bundle, ignoring already-archived output."),
    ] = False,
) -> None:
    """Archive bundles discovered via isthereanydeal.com, writing into each provider's own lists."""
    repository_root = Path.cwd().resolve()
    client = ItadHttpClient()
    written_count = 0

    def on_offer(offer: CrawledItadOffer) -> None:
        nonlocal written_count
        paths = write_itad_offer(
            offer,
            lists_root=lists_root,
            archive_root=archive_root,
            repository_root=repository_root,
            log=typer.echo,
        )
        written_count += len(paths)
        typer.echo(f"Archived {offer.archive.title}: {len(paths)} file(s)")
    # end def on_offer

    try:
        provider_config = load_provider_config(provider_config_path)
        shop_names = load_shop_config(shop_config_path)
        report = crawl_itad_offers(
            client.fetch,
            client.list_page,
            provider_config,
            tabs=tabs or ("live",),
            archive_root=None if refresh else archive_root,
            log=typer.echo,
            on_offer=on_offer,
            shop_names=shop_names,
        )
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
        # end for
        typer.echo(f"Wrote {written_count} file(s) for {len(report.offers)} offer(s).")
        if report.errors:
            raise typer.Exit(1)
        # end if
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        client.close()
    # end try
# end def scrape_isthereanydeal_command


def _steam_adapter(
    steam_root: Path | None,
    steam_id: str | None,
    api_key: str | None,
    source: str = "auto",
    collection: str | None = None,
    min_owned: int | None = None,
    max_owned: int | None = None,
    min_missing: int | None = None,
    max_missing: int | None = None,
    unresolved_handling: MissingHandling = "ignore",
    unsupported_store_handling: MissingHandling = "ignore",
    tier_mode: SteamTierMode = "all",
    reconcile_managed: bool = False,
) -> tuple[SteamAdapter, SteamFileGateway]:
    if source not in ("api", "collection", "installed", "auto", "none"):
        raise ValueError(f"unknown ownership source: {source!r}; available: auto, api, collection, installed, none")
    # end if
    root = discover_steam_root(steam_root)
    gateway = SteamFileGateway.discover(root, steam_id)
    bounds = dict(
        min_owned=min_owned,
        max_owned=max_owned,
        min_missing=min_missing,
        max_missing=max_missing,
        unresolved_handling=unresolved_handling,
        unsupported_store_handling=unsupported_store_handling,
    )
    if collection is not None and source == "auto":
        source = "collection"
    # end if

    def adapter_for_source(resolved_source: Literal["api", "collection", "installed", "none"]) -> SteamAdapter:
        if resolved_source == "none":
            return SteamAdapter(
                SteamOptions(
                    steam_id=gateway.steam_id,
                    steam_root=root,
                    tier_mode=tier_mode,
                    reconcile_managed=reconcile_managed,
                    unverified_ownership=True,
                    **bounds,
                ),
                owned_app_ids_source=lambda: set(),
                gateway=gateway,
            )
        # end if
        if resolved_source == "installed":
            typer.echo(
                "warning: --source installed only sees currently installed games; "
                "owned-but-uninstalled games will show as missing",
                err=True,
            )
            owned_app_ids_source = owned_app_ids_from_installed(root)
            options = SteamOptions(
                steam_id=gateway.steam_id,
                steam_root=root,
                tier_mode=tier_mode,
                reconcile_managed=reconcile_managed,
                **bounds,
            )
        elif resolved_source == "collection":
            collection_name = collection or "manual-all"
            owned_app_ids_source = owned_app_ids_from_collection(gateway, collection_name)
            options = SteamOptions(
                steam_id=gateway.steam_id,
                steam_root=root,
                tier_mode=tier_mode,
                reconcile_managed=reconcile_managed,
                protected_collection_name=collection_name,
                **bounds,
            )
        else:
            key = api_key or os.environ.get("STEAM_WEB_API_KEY")
            if not key:
                raise ValueError("provide --api-key or STEAM_WEB_API_KEY (or use --source collection/installed/none)")
            # end if
            options = SteamOptions(
                steam_id=gateway.steam_id,
                steam_root=root,
                api_key=key,
                tier_mode=tier_mode,
                reconcile_managed=reconcile_managed,
                **bounds,
            )
            owned_app_ids_source = owned_app_ids_from_api(SteamApiClient(key), options.steam_id)
        # end if
        return SteamAdapter(options, owned_app_ids_source=owned_app_ids_source, gateway=gateway)
    # end def adapter_for_source

    if source != "auto":
        return adapter_for_source(source), gateway
    # end if

    failures: list[str] = []
    for candidate in ("api", "collection", "installed"):
        try:
            adapter = adapter_for_source(candidate)
            owned_app_ids = frozenset(adapter.owned_app_ids_source())
        except (OSError, ValueError, RuntimeError, SteamIoError) as error:
            failures.append(f"{candidate}: {error}")
            continue
        # end try
        return (
            SteamAdapter(adapter.options, owned_app_ids_source=lambda: set(owned_app_ids), gateway=gateway),
            gateway,
        )
    # end for
    raise SteamAutoSourceError("could not determine Steam ownership automatically:\n  " + "\n  ".join(failures))

# end def _steam_adapter


def _print_plan(plan: object, *, log_skips: bool = False) -> None:
    from game_collections.launchers.base import SyncPlan

    if not isinstance(plan, SyncPlan):
        raise TypeError("expected SyncPlan")
    # end if
    selected_ids = {
        change.list_id
        for change in plan.changes
        if change.action == "create-or-update" and change.list_id is not None
    }
    for result in plan.eligibility:
        if result.eligible and result.list_id not in selected_ids:
            continue
        # end if
        if not result.eligible and not log_skips:
            continue
        # end if
        state = "eligible" if result.eligible else "skipped"
        typer.echo(f"{state}: {result.list_id} ({result.name})")
        if log_skips and result.missing_ids:
            typer.echo(f"  missing: {', '.join(result.missing_ids)}")
        # end if
        if log_skips and result.unsupported_ids:
            typer.echo(f"  no Steam ID: {', '.join(result.unsupported_ids)}")
        # end if
    # end for
    for change in plan.changes:
        if change.action != "delete":
            continue
        # end if
        identifier = change.list_id or change.target_id
        typer.echo(f"delete: {identifier} ({change.name})")
    # end for
    update_count = sum(change.action == "create-or-update" for change in plan.changes)
    delete_count = sum(change.action == "delete" for change in plan.changes)
    typer.echo(
        f"Planned collection changes: {len(plan.changes)} "
        f"({update_count} create/update, {delete_count} delete)"
    )
# end def _print_plan


def _confirm_unverified_ownership() -> None:
    typer.echo(
        "warning: --source none does not verify Steam ownership. Every Steam ID in the selected lists "
        "will be added to its collection.",
        err=True,
    )
    if not typer.confirm("Continue without Steam ownership verification?"):
        raise typer.Abort()
    # end if
# end def _confirm_unverified_ownership


@app.command("eligible")
def eligible_command(
    launcher: Annotated[str, typer.Argument()] = "steam",
    lists_root: Annotated[Path | None, typer.Option("--lists-root")] = None,
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", hide_input=True)] = None,
    source: Annotated[str, typer.Option("--source", help="auto (API, collection, then installed), api, collection, installed, or none (unverified every-ID mode)")] = "auto",
    collection: Annotated[str | None, typer.Option("--collection", help="name of a local Steam collection to use as the ownership source; implies --source collection; defaults to 'manual-all'")] = None,
    log_skips: Annotated[bool, typer.Option("--log-skips", help="Print skipped lists and their missing or unsupported IDs.")] = False,
    min_owned: Annotated[int | None, typer.Option("--min-owned", help="Only eligible if at least this many games are owned.")] = None,
    max_owned: Annotated[int | None, typer.Option("--max-owned", help="Only eligible if at most this many games are owned.")] = None,
    min_missing: Annotated[int | None, typer.Option("--min-missing", help="Only eligible if at least this many games are missing.")] = None,
    max_missing: Annotated[int | None, typer.Option("--max-missing", help="Only eligible if at most this many games are missing.")] = 0,
    unresolved_handling: Annotated[Literal["hide", "ignore", "enforce"], typer.Option("--unresolved-handling", help="How `unresolved:` marker games count toward ownership.")] = "ignore",
    unsupported_store_handling: Annotated[Literal["hide", "ignore", "enforce"], typer.Option("--unsupported-store-handling", help="How games from stores without a URL builder count toward ownership.")] = "ignore",
    selection_config: Annotated[Path, typer.Option("--selection-config", help="Selection config from `apply`; silently ignored if absent.")] = DEFAULT_SELECTION_CONFIG_PATH,
) -> None:
    """Report which lists are fully owned by the launcher account."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        adapter, _gateway = _steam_adapter(
            steam_root,
            steam_id,
            api_key,
            source,
            collection,
            min_owned=min_owned,
            max_owned=max_owned,
            min_missing=min_missing,
            max_missing=max_missing,
            unresolved_handling=unresolved_handling,
            unsupported_store_handling=unsupported_store_handling,
        )
        if adapter.options.unverified_ownership:
            _confirm_unverified_ownership()
        # end if
        game_lists = _discover_selected_game_lists(_lists_root(lists_root), selection_config)
        plan = adapter.plan(game_lists)
        _print_plan(plan, log_skips=log_skips)
    except (OSError, ValueError, RuntimeError, SelectionLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def eligible_command


@app.command("sync")
def sync_command(
    launcher: Annotated[str, typer.Argument()] = "steam",
    apply_changes: Annotated[bool, typer.Option("--apply")] = False,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    lists_root: Annotated[Path | None, typer.Option("--lists-root")] = None,
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", hide_input=True)] = None,
    source: Annotated[str, typer.Option("--source", help="auto (API, collection, then installed), api, collection, installed, or none (unverified every-ID mode)")] = "auto",
    collection: Annotated[str | None, typer.Option("--collection", help="name of a local Steam collection to use as the ownership source; implies --source collection; defaults to 'manual-all'")] = None,
    log_skips: Annotated[bool, typer.Option("--log-skips", help="Print skipped lists and their missing or unsupported IDs.")] = False,
    min_owned: Annotated[int | None, typer.Option("--min-owned", help="Only eligible if at least this many games are owned.")] = None,
    max_owned: Annotated[int | None, typer.Option("--max-owned", help="Only eligible if at most this many games are owned.")] = None,
    min_missing: Annotated[int | None, typer.Option("--min-missing", help="Only eligible if at least this many games are missing.")] = None,
    max_missing: Annotated[int | None, typer.Option("--max-missing", help="Only eligible if at most this many games are missing.")] = 0,
    unresolved_handling: Annotated[Literal["hide", "ignore", "enforce"], typer.Option("--unresolved-handling", help="How `unresolved:` marker games count toward ownership.")] = "ignore",
    unsupported_store_handling: Annotated[Literal["hide", "ignore", "enforce"], typer.Option("--unsupported-store-handling", help="How games from stores without a URL builder count toward ownership.")] = "ignore",
    tiers: Annotated[Literal["all", "highest"], typer.Option("--tiers", help="Include all matching tiers or only the highest matching sibling tier.")] = "highest",
    selection_config: Annotated[Path, typer.Option("--selection-config", help="Selection config from `apply`; silently ignored if absent.")] = DEFAULT_SELECTION_CONFIG_PATH,
) -> None:
    """Plan or stage and explicitly apply launcher collection changes."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        adapter, gateway = _steam_adapter(
            steam_root,
            steam_id,
            api_key,
            source,
            collection,
            min_owned=min_owned,
            max_owned=max_owned,
            min_missing=min_missing,
            max_missing=max_missing,
            unresolved_handling=unresolved_handling,
            unsupported_store_handling=unsupported_store_handling,
            tier_mode=tiers,
            reconcile_managed=True,
        )
        if adapter.options.unverified_ownership:
            _confirm_unverified_ownership()
        # end if
        plan = adapter.plan(
            _discover_selected_game_lists(_lists_root(lists_root), selection_config, on_progress=_echo_list_progress)
        )
        _print_plan(plan, log_skips=log_skips)
        if not apply_changes:
            typer.echo("Dry run only. Use --apply to stage inspectable files.")
            return
        # end if
        staged = adapter.stage(plan, output_dir or default_staging_root())
        typer.echo(f"Staged candidates and backups: {staged}")
        typer.echo(f"Inspection report: {staged / 'README.txt'}")
        for record in json.loads((staged / "manifest.json").read_text(encoding="utf-8"))["replacements"]:
            typer.echo(f"  source: {record['source']['path']}")
            typer.echo(f"  candidate: {staged / record['candidate_name']}")
            typer.echo(f"  backup: {staged / record['backup_name']}")
        # end for
        if not typer.confirm("Have you inspected the candidates and closed Steam?"):
            typer.echo("Nothing in Steam was changed.")
            return
        # end if
        adapter.apply(staged, lambda prompt: typer.prompt(prompt))
        typer.echo("Steam files replaced and verified. Keep Steam closed if restoring.")
        typer.echo(f"Restore with: game-collections restore steam {staged}")
        typer.echo(f"Backups remain in: {staged}")
    except (OSError, ValueError, RuntimeError, SteamIoError, SelectionLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def sync_command


def _resolve_filter[T](cli_value: T | None, config_value: T | None, default: T) -> T:
    """Precedence for an `apply` filter: explicit CLI flag, then a saved selection's value, then the hardcoded default."""
    if cli_value is not None:
        return cli_value
    # end if
    if config_value is not None:
        return config_value
    # end if
    return default
# end def _resolve_filter


@app.command("apply")
def apply_command(
    launcher: Annotated[str, typer.Argument()] = "steam",
    apply_changes: Annotated[bool, typer.Option("--apply", help="Deprecated for `apply`; choose Apply to Steam in the picker.")] = False,
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    lists_root: Annotated[Path | None, typer.Option("--lists-root")] = None,
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", hide_input=True)] = None,
    source: Annotated[str, typer.Option("--source", help="auto (API, collection, then installed), api, collection, installed, or none (unverified every-ID mode)")] = "auto",
    collection: Annotated[str | None, typer.Option("--collection", help="name of a local Steam collection to use as the ownership source; implies --source collection; defaults to 'manual-all'")] = None,
    log_skips: Annotated[bool, typer.Option("--log-skips", help="Print skipped lists and their missing or unsupported IDs.")] = False,
    min_owned: Annotated[int | None, typer.Option("--min-owned", help="Only eligible if at least this many games are owned.")] = None,
    max_owned: Annotated[int | None, typer.Option("--max-owned", help="Only eligible if at most this many games are owned.")] = None,
    min_missing: Annotated[int | None, typer.Option("--min-missing", help="Only eligible if at least this many games are missing. Falls back to a saved selection's value, then unset (no lower bound), if not passed.")] = None,
    max_missing: Annotated[int | None, typer.Option("--max-missing", help="Only eligible if at most this many games are missing. Falls back to a saved selection's value, then 0, if not passed.")] = None,
    unresolved_handling: Annotated[Literal["hide", "ignore", "enforce"] | None, typer.Option("--unresolved-handling", help="How `unresolved:` marker games count toward ownership. Falls back to a saved selection's value, then `ignore`, if not passed.")] = None,
    unsupported_store_handling: Annotated[Literal["hide", "ignore", "enforce"] | None, typer.Option("--unsupported-store-handling", help="How games from stores without a URL builder count toward ownership. Falls back to a saved selection's value, then `ignore`, if not passed.")] = None,
    tiers: Annotated[Literal["all", "highest"] | None, typer.Option("--tiers", help="Include all matching tiers or only the highest matching sibling tier. Falls back to a saved selection's value, then `highest`, if not passed.")] = None,
    selection_config: Annotated[Path, typer.Option("--selection-config")] = DEFAULT_SELECTION_CONFIG_PATH,
) -> None:
    """Interactively pick which bundles to sync, then continue like `sync`."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        from game_collections.apply.tui import ApplyPickerApp
    except ImportError as error:
        typer.echo(
            "the `apply` command needs the optional `tui` extra: uv sync --extra tui",
            err=True,
        )
        raise typer.Exit(1) from error
    # end try
    try:
        previous_selection = load_selection(selection_config)
        previously_excluded = excluded_list_ids(previous_selection)

        # Filter-related flags default to `None` (not passed) so a saved selection's own
        # values can fill the gap; only the final hardcoded default below applies when
        # neither an explicit flag nor a saved selection provides one.
        min_missing = _resolve_filter(min_missing, previous_selection.min_missing if previous_selection is not None else None, None)
        max_missing = _resolve_filter(max_missing, previous_selection.max_missing if previous_selection is not None else None, 0)
        unresolved_handling = _resolve_filter(unresolved_handling, previous_selection.unresolved_handling if previous_selection is not None else None, "ignore")
        unsupported_store_handling = _resolve_filter(unsupported_store_handling, previous_selection.unsupported_store_handling if previous_selection is not None else None, "ignore")
        tiers = _resolve_filter(tiers, previous_selection.tier_mode if previous_selection is not None else None, "highest")
        # No CLI flags exist for these (picker-only filters); they only ever come from a
        # saved selection, else the hardcoded default.
        min_items = previous_selection.min_items if previous_selection is not None else None
        max_items = previous_selection.max_items if previous_selection is not None else None
        date_after = previous_selection.date_after if previous_selection is not None else None
        date_before = previous_selection.date_before if previous_selection is not None else None
        show_filtered = previous_selection.show_filtered if previous_selection is not None else False

        # Best-effort: resolved once up front so the picker can mark bundles/games you
        # don't own yet. Not required to open the picker or to cancel out of it - if Steam
        # access isn't set up (yet), the picker just runs without ownership marks, and a
        # real adapter is still required (and re-attempted) below once you actually save.
        owned_app_ids: frozenset[int] | None = None
        early_adapter: SteamAdapter | None = None
        early_gateway: SteamFileGateway | None = None
        ownership_resolver: Callable[[Literal["api", "collection", "installed", "none"], str | None, str | None], frozenset[int] | None] | None = None
        confirm_unverified_ownership = False
        try:
            early_adapter, early_gateway = _steam_adapter(
                steam_root,
                steam_id,
                api_key,
                source,
                collection,
                min_owned=min_owned,
                max_owned=max_owned,
                min_missing=min_missing,
                max_missing=max_missing,
                unresolved_handling=unresolved_handling,
                unsupported_store_handling=unsupported_store_handling,
                tier_mode=tiers,
                reconcile_managed=True,
            )
            if early_adapter.options.unverified_ownership:
                confirm_unverified_ownership = True
            else:
                owned_app_ids = frozenset(early_adapter.owned_app_ids_source())
            # end if
        except SteamAutoSourceError:
            # `apply` is the interactive command, so it can offer a Textual fallback
            # instead of making the user restart with a different command-line flag.
            def resolve_ownership_choice(
                chosen_source: Literal["api", "collection", "installed", "none"],
                chosen_api_key: str | None,
                chosen_collection: str | None,
            ) -> frozenset[int] | None:
                nonlocal early_adapter, early_gateway, owned_app_ids, confirm_unverified_ownership
                early_adapter, early_gateway = _steam_adapter(
                    steam_root,
                    steam_id,
                    chosen_api_key or api_key,
                    chosen_source,
                    chosen_collection,
                    min_owned=min_owned,
                    max_owned=max_owned,
                    min_missing=min_missing,
                    max_missing=max_missing,
                    unresolved_handling=unresolved_handling,
                    unsupported_store_handling=unsupported_store_handling,
                    tier_mode=tiers,
                    reconcile_managed=True,
                )
                if early_adapter.options.unverified_ownership:
                    owned_app_ids = None
                    confirm_unverified_ownership = True
                    return None
                # end if
                owned_app_ids = frozenset(early_adapter.owned_app_ids_source())
                return owned_app_ids
            # end def resolve_ownership_choice

            ownership_resolver = resolve_ownership_choice
        # end try

        resume_selection: ApplySelection | None = None
        while True:
            picker = ApplyPickerApp(
                _lists_root(lists_root),
                set(resume_selection.excluded) if resume_selection is not None else previously_excluded,
                min_missing=min_missing,
                max_missing=max_missing,
                unresolved_handling=unresolved_handling,
                unsupported_store_handling=unsupported_store_handling,
                tier_mode=tiers,
                min_items=min_items,
                max_items=max_items,
                date_after=date_after,
                date_before=date_before,
                show_filtered=show_filtered,
                owned_app_ids=owned_app_ids,
                ownership_resolver=ownership_resolver,
                confirm_unverified_ownership=confirm_unverified_ownership,
                initial_selection=resume_selection,
            )
            picker_result = picker.run()
            if picker_result is None:
                typer.echo("Cancelled. No selection was saved.")
                return
            # end if
            # Keep compatibility with test doubles and third-party wrappers built before
            # the picker grew its final action dialog.
            legacy_picker_result = isinstance(picker_result, ApplySelection)
            if legacy_picker_result:
                selection = picker_result
                action: Literal["dry-run", "apply", "close"] = "apply" if apply_changes else "dry-run"
            else:
                selection = picker_result.selection
                action = picker_result.action
            # end if
            save_selection(selection, selection_config)
            typer.echo(f"Saved selection: {selection_config}")
            if action == "close":
                return
            # end if

            excluded = set(selection.excluded)
            game_lists = [game_list for game_list in picker.all_game_lists if game_list.id not in excluded]

            if early_adapter is not None and early_gateway is not None:
                adapter = SteamAdapter(
                    replace(
                        early_adapter.options,
                        min_missing=picker.min_missing,
                        max_missing=picker.max_missing,
                        tier_mode=picker.tier_mode,
                    ),
                    owned_app_ids_source=lambda: owned_app_ids or set(),
                    gateway=early_gateway,
                )
            else:
                adapter, _gateway = _steam_adapter(
                    steam_root,
                    steam_id,
                    api_key,
                    source,
                    collection,
                    min_owned=min_owned,
                    max_owned=max_owned,
                    min_missing=picker.min_missing,
                    max_missing=picker.max_missing,
                    unresolved_handling=unresolved_handling,
                    unsupported_store_handling=unsupported_store_handling,
                    tier_mode=picker.tier_mode,
                    reconcile_managed=True,
                )
            # end if
            if adapter.options.unverified_ownership:
                typer.echo(
                    "warning: using unverified ownership; every Steam ID in selected lists is addable.",
                    err=True,
                )
            # end if
            plan = adapter.plan(game_lists)
            _print_plan(plan, log_skips=log_skips)
            if action == "dry-run":
                if legacy_picker_result:
                    typer.echo("Dry run only. Use the picker action menu to apply.")
                    return
                # end if
                typer.echo("Dry run only. Returning to the picker action menu.")
                resume_selection = selection
                previously_excluded = set(selection.excluded)
                min_missing = picker.min_missing
                max_missing = picker.max_missing
                unresolved_handling = picker.unresolved_handling
                unsupported_store_handling = picker.unsupported_store_handling
                tiers = picker.tier_mode
                min_items = picker.row_filters.min_items
                max_items = picker.row_filters.max_items
                date_after = picker.row_filters.date_after
                date_before = picker.row_filters.date_before
                show_filtered = picker.show_filtered
                ownership_resolver = None
                confirm_unverified_ownership = False
                continue
            # end if
            break
        # end while
        staged = adapter.stage(plan, output_dir or default_staging_root())
        typer.echo(f"Staged candidates and backups: {staged}")
        typer.echo(f"Inspection report: {staged / 'README.txt'}")
        for record in json.loads((staged / "manifest.json").read_text(encoding="utf-8"))["replacements"]:
            typer.echo(f"  source: {record['source']['path']}")
            typer.echo(f"  candidate: {staged / record['candidate_name']}")
            typer.echo(f"  backup: {staged / record['backup_name']}")
        # end for
        shutil.copy2(selection_config, staged / selection_config.name)
        if not typer.confirm("Have you inspected the candidates and closed Steam?"):
            typer.echo("Nothing in Steam was changed.")
            return
        # end if
        adapter.apply(staged, lambda prompt: typer.prompt(prompt))
        typer.echo("Steam files replaced and verified. Keep Steam closed if restoring.")
        typer.echo(f"Restore with: game-collections restore steam {staged}")
        typer.echo(f"Backups remain in: {staged}")
    except (OSError, ValueError, RuntimeError, SteamIoError, SelectionLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def apply_command


@app.command("restore")
def restore_command(
    launcher: Annotated[str, typer.Argument()],
    staged_dir: Annotated[Path, typer.Argument()],
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
) -> None:
    """Restore a verified launcher backup while the launcher is stopped."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        gateway = SteamFileGateway.discover(discover_steam_root(steam_root), steam_id)
        typer.echo(f"Backup directory: {staged_dir.resolve()}")
        gateway.restore(staged_dir, lambda prompt: typer.prompt(prompt))
        typer.echo("Steam backups restored and verified.")
    except (OSError, ValueError, RuntimeError, SteamIoError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def restore_command


if __name__ == "__main__":
    app()
# end if
