"""Command-line interface for game list validation and synchronization."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
import yaml

from game_collections.lists import ListLoadError, discover_game_lists
from game_collections.launchers.steam.adapter import (
    SteamAdapter,
    SteamOptions,
    owned_app_ids_from_api,
    owned_app_ids_from_installed,
)
from game_collections.launchers.steam.api import SteamApiClient
from game_collections.launchers.steam.discovery import discover_steam_root
from game_collections.launchers.steam.io import SteamFileGateway, SteamIoError, default_staging_root
from game_collections.schema import write_schema
from game_collections.schema import write_dailyindiegame_schema
from game_collections.schema import write_greenmangaming_schema
from game_collections.schema import write_humblebundle_schema
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


app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
scrape_app = typer.Typer(no_args_is_help=True)
app.add_typer(scrape_app, name="scrape")


def _lists_root(path: Path | None) -> Path:
    return path or Path.cwd() / "lists"
# end def _lists_root


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
) -> None:
    """Generate JSON Schemas from the runtime Pydantic models."""
    write_schema(output)
    write_humblebundle_schema(humblebundle_output)
    write_dailyindiegame_schema(dailyindiegame_output)
    write_greenmangaming_schema(greenmangaming_output)
    typer.echo(output)
    typer.echo(humblebundle_output)
    typer.echo(dailyindiegame_output)
    typer.echo(greenmangaming_output)
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
) -> None:
    """Complete storefront IDs in a draft YAML game list."""
    client = HumbleHttpClient()
    try:
        selected = selected_providers(providers, default="steam")
        selected_mode = completion_mode(mode)
        resolver = StorefrontResolver(client.fetch, lambda _item, _provider, _candidates: None)
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        completed, unresolved = complete_game_list(
            raw,
            selected,
            resolver,
            _choose_search_candidate,
            selected_mode,
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


def _steam_adapter(
    steam_root: Path | None,
    steam_id: str | None,
    api_key: str | None,
    source: str = "api",
) -> tuple[SteamAdapter, SteamFileGateway]:
    if source not in ("api", "installed"):
        raise ValueError(f"unknown ownership source: {source!r}; available: api, installed")
    # end if
    root = discover_steam_root(steam_root)
    gateway = SteamFileGateway.discover(root, steam_id)
    if source == "installed":
        typer.echo(
            "warning: --source installed only sees currently installed games; "
            "owned-but-uninstalled games will show as missing",
            err=True,
        )
        owned_app_ids_source = owned_app_ids_from_installed(root)
        options = SteamOptions(steam_id=gateway.steam_id, steam_root=root)
    else:
        key = api_key or os.environ.get("STEAM_WEB_API_KEY")
        if not key:
            raise ValueError("provide --api-key or STEAM_WEB_API_KEY (or use --source installed)")
        # end if
        options = SteamOptions(steam_id=gateway.steam_id, steam_root=root, api_key=key)
        owned_app_ids_source = owned_app_ids_from_api(SteamApiClient(key), options.steam_id)
    # end if
    adapter = SteamAdapter(options, owned_app_ids_source=owned_app_ids_source, gateway=gateway)
    return adapter, gateway
# end def _steam_adapter


def _print_plan(plan: object) -> None:
    from game_collections.launchers.base import SyncPlan

    if not isinstance(plan, SyncPlan):
        raise TypeError("expected SyncPlan")
    # end if
    for result in plan.eligibility:
        state = "eligible" if result.eligible else "skipped"
        typer.echo(f"{state}: {result.list_id} ({result.name})")
        if result.missing_ids:
            typer.echo(f"  missing: {', '.join(result.missing_ids)}")
        # end if
        if result.unsupported_ids:
            typer.echo(f"  no Steam ID: {', '.join(result.unsupported_ids)}")
        # end if
    # end for
    typer.echo(f"Planned collection changes: {len(plan.changes)}")
# end def _print_plan


@app.command("eligible")
def eligible_command(
    launcher: Annotated[str, typer.Argument()] = "steam",
    lists_root: Annotated[Path | None, typer.Option("--lists-root")] = None,
    steam_root: Annotated[Path | None, typer.Option("--steam-root")] = None,
    steam_id: Annotated[str | None, typer.Option("--steam-id")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", hide_input=True)] = None,
    source: Annotated[str, typer.Option("--source", help="api (Web API, needs a key) or installed (local-only approximation)")] = "api",
) -> None:
    """Report which lists are fully owned by the launcher account."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        adapter, _gateway = _steam_adapter(steam_root, steam_id, api_key, source)
        plan = adapter.plan(discover_game_lists(_lists_root(lists_root)))
        _print_plan(plan)
    except (OSError, ValueError, RuntimeError) as error:
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
    source: Annotated[str, typer.Option("--source", help="api (Web API, needs a key) or installed (local-only approximation)")] = "api",
) -> None:
    """Plan or stage and explicitly apply launcher collection changes."""
    if launcher != "steam":
        typer.echo(f"launcher is not implemented: {launcher}", err=True)
        raise typer.Exit(2)
    # end if
    try:
        adapter, gateway = _steam_adapter(steam_root, steam_id, api_key, source)
        plan = adapter.plan(discover_game_lists(_lists_root(lists_root)))
        _print_plan(plan)
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
    except (OSError, ValueError, RuntimeError, SteamIoError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def sync_command


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
