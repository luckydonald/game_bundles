from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner
from pytest import CaptureFixture, MonkeyPatch

from game_collections.apply.config import ApplySelection, save_selection
from game_collections.cli import _maybe_refresh_dynamicstore_dump, _print_plan, app
from game_collections.launchers.base import CollectionEligibility, PlannedCollectionChange, SyncPlan
from game_collections.lists import discover_game_lists
from test_steam_io import STEAM_ID, build_fake_steam


def _plan_with_eligible_and_skipped_lists() -> SyncPlan:
    return SyncPlan(
        launcher="steam",
        account="123",
        eligibility=[
            CollectionEligibility(
                list_id="valve/the-orange-box",
                name="The Orange Box",
                eligible=True,
                owned_ids=["steam:440"],
                missing_ids=[],
                unsupported_ids=[],
            ),
            CollectionEligibility(
                list_id="example/skipped",
                name="Skipped",
                eligible=False,
                owned_ids=[],
                missing_ids=["steam:10"],
                unsupported_ids=["Unknown game"],
            ),
        ],
        changes=[
            PlannedCollectionChange(
                list_id="valve/the-orange-box",
                target_id="uc-9Dldt76YmGbo",
                name="🗃️ The Orange Box",
                action="create-or-update",
                added_ids=["steam:440"],
            )
        ],
    )
# end def _plan_with_eligible_and_skipped_lists


def test_print_plan_hides_skipped_lists_by_default(capsys: CaptureFixture[str]) -> None:
    _print_plan(_plan_with_eligible_and_skipped_lists())

    output = capsys.readouterr().out
    assert output == (
        "eligible: valve/the-orange-box (The Orange Box)\n"
        "Planned collection changes: 1 (1 create/update, 0 delete)\n"
    )
# end def test_print_plan_hides_skipped_lists_by_default


def test_print_plan_logs_skipped_lists_when_requested(capsys: CaptureFixture[str]) -> None:
    _print_plan(_plan_with_eligible_and_skipped_lists(), log_skips=True)

    output = capsys.readouterr().out
    assert output == (
        "eligible: valve/the-orange-box (The Orange Box)\n"
        "skipped: example/skipped (Skipped)\n"
        "  missing: steam:10\n"
        "  no Steam ID: Unknown game\n"
        "Planned collection changes: 1 (1 create/update, 0 delete)\n"
    )
# end def test_print_plan_logs_skipped_lists_when_requested


def test_print_plan_always_reports_managed_deletions(capsys: CaptureFixture[str]) -> None:
    plan = SyncPlan(
        launcher="steam",
        account="123",
        eligibility=[],
        changes=[
            PlannedCollectionChange(
                target_id="uc-orphan123",
                name="🗃️ Orphan",
                action="delete",
            )
        ],
    )

    _print_plan(plan)

    assert capsys.readouterr().out == (
        "delete: uc-orphan123 (🗃️ Orphan)\n"
        "Planned collection changes: 1 (0 create/update, 1 delete)\n"
    )
# end def test_print_plan_always_reports_managed_deletions


def test_sync_help_lists_matching_and_tier_choices() -> None:
    result = CliRunner().invoke(app, ["sync", "--help"])

    assert result.exit_code == 0
    assert "--min-owned" in result.output
    assert "--max-owned" in result.output
    assert "--min-missing" in result.output
    assert "--max-missing" in result.output
    assert "--unresolved-han" in result.output  # truncated by rich's help table at this column width
    assert "--unsupported-st" in result.output  # truncated by rich's help table at this column width
    assert "--tiers" in result.output
    assert "highest" in result.output
# end def test_sync_help_lists_matching_and_tier_choices


def test_sync_rejects_invalid_matching_mode_before_steam_discovery() -> None:
    result = CliRunner().invoke(app, ["sync", "--min-owned", "not-a-number"])

    assert result.exit_code == 2
    assert "Invalid value for '--min-owned'" in result.output
# end def test_sync_rejects_invalid_matching_mode_before_steam_discovery


def test_sync_none_requires_confirmation_and_adds_every_listed_steam_id(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")

    result = CliRunner().invoke(
        app,
        [
            "sync",
            "--source",
            "none",
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--lists-root",
            str(lists_root),
            "--selection-config",
            str(tmp_path / "missing-selection.yml"),
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "does not verify Steam ownership" in result.output
    assert "eligible: vendor/one (One)" in result.output
    assert "Planned collection changes: 1 (1 create/update, 0 delete)" in result.output
# end def test_sync_none_requires_confirmation_and_adds_every_listed_steam_id


def test_sync_auto_errors_after_every_automatic_source_fails(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    attempted: list[str] = []

    def unavailable(name: str):
        def source(*_args: object) -> object:
            def read() -> set[int]:
                attempted.append(name)
                raise RuntimeError(f"{name} unavailable")
            # end def read
            return read
        # end def source
        return source
    # end def unavailable

    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_api", unavailable("api"))
    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_collection", unavailable("collection"))
    monkeypatch.setattr("game_collections.cli.owned_app_ids_from_installed", unavailable("installed"))

    result = CliRunner().invoke(
        app,
        ["sync", "--steam-root", str(steam_root), "--steam-id", STEAM_ID, "--api-key", "test-key"],
    )

    assert result.exit_code == 1, result.output
    assert attempted == ["api", "collection", "installed"]
    assert "could not determine Steam ownership automatically" in result.output
# end def test_sync_auto_errors_after_every_automatic_source_fails


def test_scrape_help_lists_git_flag() -> None:
    result = CliRunner().invoke(app, ["scrape", "--help"])

    assert result.exit_code == 0
    assert "--git" in result.output
# end def test_scrape_help_lists_git_flag


def test_complete_requires_file_or_all() -> None:
    result = CliRunner().invoke(app, ["complete"])

    assert result.exit_code == 1
    assert "provide FILE or --all" in result.output
# end def test_complete_requires_file_or_all


def test_complete_rejects_file_and_all_together(tmp_path: Path) -> None:
    draft = tmp_path / "draft.yml"
    draft.write_text("schema: 1\nname: Draft\ngames: []\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["complete", str(draft), "--all"])

    assert result.exit_code == 1
    assert "mutually exclusive" in result.output
# end def test_complete_rejects_file_and_all_together


def test_complete_all_sweeps_every_list_under_lists_root(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    lists_root = tmp_path / "lists"
    (lists_root / "one").mkdir(parents=True)
    (lists_root / "two").mkdir(parents=True)
    (lists_root / "one" / "game.yml").write_text(
        "schema: 1\nname: One\ngames:\n  - name: Alpha\n    ids: [steam:1]\n",
        encoding="utf-8",
    )
    (lists_root / "two" / "game.yml").write_text(
        "schema: 1\nname: Two\ngames:\n  - name: Beta\n    ids: [steam:2]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose, **_kwargs: object())

    calls: list[Path] = []

    def fake_complete_game_list(raw, providers, resolver, choose, mode, *, itad_resolve=None):
        calls.append(raw["name"])
        return raw, []
    # end def fake_complete_game_list

    monkeypatch.setattr("game_collections.cli.complete_game_list", fake_complete_game_list)

    result = CliRunner().invoke(app, ["complete", "--all", "--lists-root", str(lists_root)])

    assert result.exit_code == 0, result.output
    assert sorted(calls) == ["One", "Two"]
    assert "List 1/2" in result.output
    assert "List 2/2" in result.output
    assert "Completed 2 list(s); 0 unresolved name(s), 0 error(s)." in result.output
# end def test_complete_all_sweeps_every_list_under_lists_root


def test_scrape_humblebundle_git_flag_stashes_scrapes_commits_then_restores(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from game_collections.sources.humblebundle.crawler import HumbleCrawlReport
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose, **_kwargs: object())
    monkeypatch.setattr(
        "game_collections.cli.crawl_humble_offers",
        lambda *args, **kwargs: calls.append("scrape") or HumbleCrawlReport(offers=(), errors=()),
    )

    result = CliRunner().invoke(app, ["scrape", "--git", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_humblebundle_git_flag_stashes_scrapes_commits_then_restores


def test_scrape_humblebundle_git_flag_restores_even_when_scrape_raises(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose, **_kwargs: object())

    def raising_crawl(*args: object, **kwargs: object) -> object:
        calls.append("scrape")
        raise RuntimeError("network exploded")
    # end def raising_crawl

    monkeypatch.setattr("game_collections.cli.crawl_humble_offers", raising_crawl)

    result = CliRunner().invoke(app, ["scrape", "--git", "humblebundle", "--non-interactive"])

    assert result.exit_code == 1, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_humblebundle_git_flag_restores_even_when_scrape_raises


def test_scrape_greenmangaming_git_flag_stashes_scrapes_commits_then_restores(
    monkeypatch: MonkeyPatch,
) -> None:
    from game_collections.sources.greenmangaming.crawler import GmgCrawlReport
    from game_collections.sources.greenmangaming.resolver import GmgResolutionMap

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.GmgHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_gmg_resolution_map", lambda path: GmgResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.GmgStorefrontResolver", lambda fetch, choose, **_kwargs: object())
    monkeypatch.setattr(
        "game_collections.cli.crawl_gmg_offers",
        lambda *args, **kwargs: calls.append("scrape") or GmgCrawlReport(offers=(), errors=()),
    )

    result = CliRunner().invoke(app, ["scrape", "--git", "greenmangaming", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_greenmangaming_git_flag_stashes_scrapes_commits_then_restores


def test_scrape_greenmangaming_persists_resolution_map_before_a_failed_offer_write(
    monkeypatch: MonkeyPatch,
) -> None:
    """A late failure writing the final GameList (e.g. a duplicate game name slipping through)
    must not lose already-resolved interactive answers - see `ai/errors/5.txt`, where the
    resolution map was only saved by accident because a later bundle in the same run happened
    to succeed afterward. The map write must happen unconditionally, before the risky write."""
    from game_collections.sources.greenmangaming.crawler import GmgCrawlReport
    from game_collections.sources.greenmangaming.resolver import GmgResolutionMap

    calls: list[str] = []
    monkeypatch.setattr(
        "game_collections.cli.GmgHttpClient", lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: "")
    )
    monkeypatch.setattr(
        "game_collections.cli.load_gmg_resolution_map",
        lambda path: GmgResolutionMap(schema=1, games={"1": ["steam:1"]}),
    )
    monkeypatch.setattr("game_collections.cli.GmgStorefrontResolver", lambda fetch, choose, **_kwargs: object())
    monkeypatch.setattr(
        "game_collections.cli.write_gmg_resolution_map", lambda path, mapping: calls.append("write_map")
    )

    def fake_write_gmg_offer(offer: object, **_kwargs: object) -> list[Path]:
        calls.append("write_offer")
        raise ValueError("list contains duplicate game names")
    # end def fake_write_gmg_offer

    monkeypatch.setattr("game_collections.cli.write_gmg_offer", fake_write_gmg_offer)

    fake_offer = SimpleNamespace(archive=SimpleNamespace(name="Sample Bundle"), source={})

    def fake_crawl_gmg_offers(fetch: object, resolver: object, mapping: object, urls: object, **kwargs: object) -> object:
        kwargs["on_offer"](fake_offer)
        return GmgCrawlReport(offers=(), errors=())
    # end def fake_crawl_gmg_offers

    monkeypatch.setattr("game_collections.cli.crawl_gmg_offers", fake_crawl_gmg_offers)

    result = CliRunner().invoke(app, ["scrape", "greenmangaming", "--non-interactive"])

    assert result.exit_code == 1
    assert calls == ["write_map", "write_offer"]
# end def test_scrape_greenmangaming_persists_resolution_map_before_a_failed_offer_write


def test_scrape_dailyindiegame_git_flag_stashes_scrapes_commits_then_restores(
    monkeypatch: MonkeyPatch,
) -> None:
    from game_collections.sources.dailyindiegame.crawler import DigCrawlReport

    calls: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: calls.append("head") or "deadbeef")
    monkeypatch.setattr(
        "game_collections.cli.git_ops.autostash", lambda root: calls.append("autostash") or True
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        "game_collections.cli.git_ops.restore_autostash", lambda root, head: calls.append("restore")
    )
    monkeypatch.setattr(
        "game_collections.cli.DigBrowserClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.crawl_dig_offers",
        lambda *args, **kwargs: calls.append("scrape") or DigCrawlReport(offers=(), errors=()),
    )

    result = CliRunner().invoke(app, ["scrape", "--git", "dailyindiegame"])

    assert result.exit_code == 0, result.output
    assert calls == ["head", "autostash", "scrape", "commit", "restore"]
# end def test_scrape_dailyindiegame_git_flag_stashes_scrapes_commits_then_restores


def test_git_commit_message_manual_style_has_no_ci_wording() -> None:
    from game_collections.cli import _git_commit_message

    message = _git_commit_message("humblebundle", "manual", "Archived offers", "scrape humblebundle --git", "None unresolved.")

    assert message.startswith("[crawl|humblebundle] manual scrape:\n")
    assert "scheduled CI" not in message
    assert "Manual `scrape humblebundle --git` run." in message
    assert "None unresolved." in message
# end def test_git_commit_message_manual_style_has_no_ci_wording


def test_git_commit_message_auto_style_includes_ci_wording_and_run_id(monkeypatch: MonkeyPatch) -> None:
    from game_collections.cli import _git_commit_message

    monkeypatch.setenv("GITHUB_RUN_ID", "12345")

    message = _git_commit_message("humblebundle", "auto", "Archived offers", "scrape humblebundle --git", "None unresolved.")

    assert message.startswith("[crawl|humblebundle] automated weekly scrape:\n")
    assert "via scheduled CI" in message
    assert "(run 12345)" in message
# end def test_git_commit_message_auto_style_includes_ci_wording_and_run_id


def test_git_commit_message_auto_style_omits_run_note_outside_ci(monkeypatch: MonkeyPatch) -> None:
    from game_collections.cli import _git_commit_message

    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    message = _git_commit_message("humblebundle", "auto", "Archived offers", "scrape humblebundle --git", "None unresolved.")

    assert "(run" not in message
# end def test_git_commit_message_auto_style_omits_run_note_outside_ci


def test_scrape_humblebundle_git_style_rejects_invalid_value() -> None:
    result = CliRunner().invoke(app, ["scrape", "--git", "--git-style", "bogus", "humblebundle"])

    assert result.exit_code == 2
    assert "--git-style must be 'auto' or 'manual'" in result.output
# end def test_scrape_humblebundle_git_style_rejects_invalid_value


def test_scrape_humblebundle_git_style_defaults_to_manual_wording(monkeypatch: MonkeyPatch) -> None:
    from game_collections.sources.humblebundle.crawler import HumbleCrawlReport
    from game_collections.sources.humblebundle.resolver import HumbleResolutionMap

    captured_messages: list[str] = []
    monkeypatch.setattr("game_collections.cli.git_ops.head", lambda root: "deadbeef")
    monkeypatch.setattr("game_collections.cli.git_ops.autostash", lambda root: True)
    monkeypatch.setattr(
        "game_collections.cli.git_ops.commit_changed_paths",
        lambda root, paths, message: captured_messages.append(message) or True,
    )
    monkeypatch.setattr("game_collections.cli.git_ops.restore_autostash", lambda root, head: None)
    monkeypatch.setattr(
        "game_collections.cli.HumbleHttpClient",
        lambda: SimpleNamespace(close=lambda: None, fetch=lambda url: ""),
    )
    monkeypatch.setattr(
        "game_collections.cli.load_resolution_map", lambda path: HumbleResolutionMap(schema=1, games={})
    )
    monkeypatch.setattr("game_collections.cli.StorefrontResolver", lambda fetch, choose, **_kwargs: object())
    monkeypatch.setattr(
        "game_collections.cli.crawl_humble_offers",
        lambda *args, **kwargs: HumbleCrawlReport(offers=(), errors=()),
    )

    result = CliRunner().invoke(app, ["scrape", "--git", "humblebundle", "--non-interactive"])

    assert result.exit_code == 0, result.output
    assert captured_messages == ["[crawl|humblebundle] manual scrape:\nManual `game-collections scrape --git humblebundle` run.\n\nNone unresolved.\n"]
# end def test_scrape_humblebundle_git_style_defaults_to_manual_wording


def test_apply_help_lists_options() -> None:
    result = CliRunner().invoke(app, ["apply", "--help"])

    assert result.exit_code == 0
    assert "--selection-conf" in result.output  # truncated by rich's help table at this column width
    assert "--min-missing" in result.output
    assert "--max-missing" in result.output
    assert "--tiers" in result.output
# end def test_apply_help_lists_options


def test_refresh_dynamicstore_dump_skips_by_default_when_not_interactive(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    prompted = False

    def fake_confirm(*_args: object, **_kwargs: object) -> bool:
        nonlocal prompted
        prompted = True
        return True
    # end def fake_confirm

    monkeypatch.setattr("game_collections.cli.typer.confirm", fake_confirm)

    _maybe_refresh_dynamicstore_dump(tmp_path / "dump.json", None)

    assert prompted is False
    assert not (tmp_path / "dump.json").exists()
# end def test_refresh_dynamicstore_dump_skips_by_default_when_not_interactive


def test_refresh_dynamicstore_dump_no_refresh_flag_never_prompts_even_if_interactive(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    prompted = False

    def fake_confirm(*_args: object, **_kwargs: object) -> bool:
        nonlocal prompted
        prompted = True
        return True
    # end def fake_confirm

    monkeypatch.setattr("game_collections.cli.typer.confirm", fake_confirm)

    _maybe_refresh_dynamicstore_dump(tmp_path / "dump.json", False)

    assert prompted is False
# end def test_refresh_dynamicstore_dump_no_refresh_flag_never_prompts_even_if_interactive


def test_refresh_dynamicstore_dump_force_flag_prompts_even_when_not_interactive(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    prompted = False

    def fake_confirm(*_args: object, **_kwargs: object) -> bool:
        nonlocal prompted
        prompted = True
        return False
    # end def fake_confirm

    monkeypatch.setattr("game_collections.cli.typer.confirm", fake_confirm)

    _maybe_refresh_dynamicstore_dump(tmp_path / "dump.json", True)

    assert prompted is True
# end def test_refresh_dynamicstore_dump_force_flag_prompts_even_when_not_interactive


def test_refresh_dynamicstore_dump_confirmed_paste_writes_the_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import io

    monkeypatch.setattr("game_collections.cli.typer.confirm", lambda *_a, **_k: True)
    opened_urls: list[str] = []
    monkeypatch.setattr("game_collections.cli.open_url", opened_urls.append)
    payload = json.dumps(
        {
            "rgOwnedApps": [377160, 540810],
            "bShowFilteredUserReviewScores": True,
            "rgPrimaryLanguage": 0,
            "bAllowAppImpressions": 0,
            "nCartLineItemCount": 0,
            "nRemainingCartDiscount": 0,
            "nTotalCartDiscount": 0,
        }
    )
    fake_stdin = io.StringIO(payload)
    monkeypatch.setattr(fake_stdin, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdin", fake_stdin)

    path = tmp_path / "dump.json"
    _maybe_refresh_dynamicstore_dump(path, None)

    assert opened_urls == ["steam://openurl/https://store.steampowered.com/dynamicstore/userdata"]
    assert path.exists()
# end def test_refresh_dynamicstore_dump_confirmed_paste_writes_the_file


def _write_list(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"schema: 1\nname: {name}\ngames:\n  - name: One\n    ids: [steam:440]\n", encoding="utf-8")
# end def _write_list


def test_apply_filters_excluded_list_before_planning(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    _write_list(lists_root / "vendor/two.yml", "Two")
    selection_config = tmp_path / "config/apply-selection.yml"

    fixed_selection = ApplySelection(
        schema=1,
        selected=["vendor/one"],
        excluded=["vendor/two"],
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    captured_owned_app_ids: list[object] = []

    class _StubPickerApp:
        def __init__(
            self,
            lists_root: Path,
            excluded: object,
            min_missing: int | None = None,
            max_missing: int | None = 0,
            min_missing_pct: float | None = None,
            max_missing_pct: float | None = None,
            unresolved_handling: str = "ignore",
            unsupported_store_handling: str = "ignore",
            tier_mode: str = "highest",
            min_items: int | None = None,
            max_items: int | None = None,
            date_after: str | None = None,
            date_before: str | None = None,
            show_filtered: bool = False,
            owned_app_ids: object = None,
            ownership_resolver: object = None,
            confirm_unverified_ownership: bool = False,
            initial_selection: ApplySelection | None = None,
        ) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = min_missing
            self.max_missing = max_missing
            self.min_missing_pct = min_missing_pct
            self.max_missing_pct = max_missing_pct
            self.tier_mode = tier_mode
            captured_owned_app_ids.append(owned_app_ids)
        # end def __init__

        def run(self) -> ApplySelection:
            return fixed_selection
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "eligible: vendor/one (One)" in result.output
    assert "vendor/two" not in result.output
    assert selection_config.exists()
    # valid Steam access (a real collection source here) resolves ownership up front for the picker
    assert captured_owned_app_ids == [frozenset({440})]
# end def test_apply_filters_excluded_list_before_planning


def test_apply_filter_flags_fall_back_to_saved_selection_then_default(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"
    save_selection(
        ApplySelection(
            schema=1,
            selected=["vendor/one"],
            excluded=[],
            updated_at=datetime(2026, 7, 13, tzinfo=UTC),
            min_items=2,
            max_missing=5,
            max_missing_pct=40.0,
            unresolved_handling="hide",
            unsupported_store_handling="enforce",
            tier_mode="all",
            show_filtered=True,
        ),
        selection_config,
    )

    captured_kwargs: list[dict[str, object]] = []

    class _StubPickerApp:
        def __init__(self, lists_root: Path, excluded: object, **kwargs: object) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = kwargs.get("min_missing")
            self.max_missing = kwargs.get("max_missing")
            self.min_missing_pct = kwargs.get("min_missing_pct")
            self.max_missing_pct = kwargs.get("max_missing_pct")
            self.tier_mode = kwargs.get("tier_mode")
            captured_kwargs.append(kwargs)
        # end def __init__

        def run(self) -> None:
            return None
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    # No filter flags passed: everything should come from the saved selection.
    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured_kwargs[-1]["min_items"] == 2
    assert captured_kwargs[-1]["max_missing"] == 5
    assert captured_kwargs[-1]["max_missing_pct"] == 40.0
    assert captured_kwargs[-1]["unresolved_handling"] == "hide"
    assert captured_kwargs[-1]["unsupported_store_handling"] == "enforce"
    assert captured_kwargs[-1]["tier_mode"] == "all"
    assert captured_kwargs[-1]["show_filtered"] is True

    # An explicit CLI flag overrides the saved selection's value for that field only.
    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
            "--max-missing",
            "9",
            "--max-missing-pct",
            "60",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured_kwargs[-1]["max_missing"] == 9
    assert captured_kwargs[-1]["max_missing_pct"] == 60.0
    assert captured_kwargs[-1]["unresolved_handling"] == "hide"
# end def test_apply_filter_flags_fall_back_to_saved_selection_then_default


def test_apply_dry_run_reopens_the_saved_selection_action_menu(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    steam_root = build_fake_steam(tmp_path)
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"
    fixed_selection = ApplySelection(
        schema=1,
        selected=["vendor/one"],
        excluded=[],
        updated_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    initial_selections: list[ApplySelection | None] = []

    class _PickerResult:
        def __init__(self, action: str) -> None:
            self.selection = fixed_selection
            self.action = action
        # end def __init__
    # end class _PickerResult

    class _StubPickerApp:
        def __init__(self, lists_root: Path, excluded: object, **kwargs: object) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = None
            self.max_missing = 0
            self.min_missing_pct = None
            self.max_missing_pct = None
            self.unresolved_handling = "ignore"
            self.unsupported_store_handling = "ignore"
            self.tier_mode = "highest"
            self.row_filters = SimpleNamespace(min_items=None, max_items=None, date_after=None, date_before=None)
            self.show_filtered = False
            initial_selections.append(kwargs.get("initial_selection"))
        # end def __init__

        def run(self) -> _PickerResult:
            return _PickerResult("dry-run" if len(initial_selections) == 1 else "close")
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        [
            "apply",
            "--lists-root",
            str(lists_root),
            "--steam-root",
            str(steam_root),
            "--steam-id",
            STEAM_ID,
            "--source",
            "collection",
            "--collection",
            "Favorites",
            "--selection-config",
            str(selection_config),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run only. Returning to the picker action menu." in result.output
    assert initial_selections == [None, fixed_selection]
# end def test_apply_dry_run_reopens_the_saved_selection_action_menu


def test_apply_cancelled_selection_makes_no_changes(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "vendor/one.yml", "One")
    selection_config = tmp_path / "config/apply-selection.yml"

    captured_owned_app_ids: list[object] = []

    class _StubPickerApp:
        def __init__(
            self,
            lists_root: Path,
            excluded: object,
            min_missing: int | None = None,
            max_missing: int | None = 0,
            min_missing_pct: float | None = None,
            max_missing_pct: float | None = None,
            unresolved_handling: str = "ignore",
            unsupported_store_handling: str = "ignore",
            tier_mode: str = "highest",
            min_items: int | None = None,
            max_items: int | None = None,
            date_after: str | None = None,
            date_before: str | None = None,
            show_filtered: bool = False,
            owned_app_ids: object = None,
            ownership_resolver: object = None,
            confirm_unverified_ownership: bool = False,
            initial_selection: ApplySelection | None = None,
        ) -> None:
            self.all_game_lists = discover_game_lists(lists_root)
            self.min_missing = min_missing
            self.max_missing = max_missing
            self.min_missing_pct = min_missing_pct
            self.max_missing_pct = max_missing_pct
            self.tier_mode = tier_mode
            captured_owned_app_ids.append(owned_app_ids)
        # end def __init__

        def run(self) -> None:
            return None
        # end def run
    # end class _StubPickerApp

    monkeypatch.setattr("game_collections.apply.tui.ApplyPickerApp", _StubPickerApp)

    result = CliRunner().invoke(
        app,
        ["apply", "--lists-root", str(lists_root), "--selection-config", str(selection_config)],
    )

    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.output
    assert len(captured_owned_app_ids) == 1
    assert not selection_config.exists()
# end def test_apply_cancelled_selection_makes_no_changes


def test_install_command_calls_uv_tool_install_and_writes_completion(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("game_collections.cli.git_ops.repository_root", lambda start: tmp_path)
    monkeypatch.setattr("game_collections.cli.tool_install.choose_install_source", lambda root: "editable")
    install_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "game_collections.cli.tool_install.install_uv_tool",
        lambda root, source: install_calls.append((root, source))
        or SimpleNamespace(stdout="installed", stderr=""),
    )

    result = CliRunner().invoke(app, ["install", "--shell", "bash"])

    assert result.exit_code == 0, result.output
    assert install_calls == [(tmp_path, "editable")]
    assert (home / ".config" / "game-collections" / "completion.bash").is_file()
    assert "completion written to" in result.output
# end def test_install_command_calls_uv_tool_install_and_writes_completion


def test_install_command_skip_completion_flag_skips_shell_setup(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("game_collections.cli.git_ops.repository_root", lambda start: tmp_path)
    monkeypatch.setattr("game_collections.cli.tool_install.choose_install_source", lambda root: "editable")
    monkeypatch.setattr(
        "game_collections.cli.tool_install.install_uv_tool",
        lambda root, source: SimpleNamespace(stdout="installed", stderr=""),
    )

    result = CliRunner().invoke(app, ["install", "--skip-completion"])

    assert result.exit_code == 0, result.output
    assert not (home / ".config" / "game-collections").exists()
# end def test_install_command_skip_completion_flag_skips_shell_setup


def test_install_command_rejects_invalid_shell_option() -> None:
    result = CliRunner().invoke(app, ["install", "--shell", "bogus"])

    assert result.exit_code == 2
    assert "--shell must be 'bash' or 'zsh'" in result.output
# end def test_install_command_rejects_invalid_shell_option


def test_install_command_wraps_git_repository_root_error(monkeypatch: MonkeyPatch) -> None:
    from game_collections.git_ops import GitAutocommitError

    def raise_not_a_repo(start: Path) -> Path:
        raise GitAutocommitError("not inside a git repository")
    # end def raise_not_a_repo

    monkeypatch.setattr("game_collections.cli.git_ops.repository_root", raise_not_a_repo)

    result = CliRunner().invoke(app, ["install"])

    assert result.exit_code == 1
    assert "not inside a git repository" in result.output
# end def test_install_command_wraps_git_repository_root_error


def test_install_command_wraps_uv_tool_install_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from game_collections.install.tool_install import InstallError

    monkeypatch.setattr("game_collections.cli.git_ops.repository_root", lambda start: tmp_path)
    monkeypatch.setattr("game_collections.cli.tool_install.choose_install_source", lambda root: "editable")

    def raise_install_error(root: Path, source: str) -> None:
        raise InstallError("`uv tool install` failed")
    # end def raise_install_error

    monkeypatch.setattr("game_collections.cli.tool_install.install_uv_tool", raise_install_error)

    result = CliRunner().invoke(app, ["install"])

    assert result.exit_code == 1
    assert "uv tool install" in result.output
# end def test_install_command_wraps_uv_tool_install_error


def test_uninstall_command_removes_completion_and_declines_uv_uninstall_by_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    uninstall_calls: list[str] = []
    monkeypatch.setattr(
        "game_collections.cli.tool_install.uninstall_uv_tool",
        lambda: uninstall_calls.append("uninstalled"),
    )

    result = CliRunner().invoke(app, ["uninstall", "--shell", "bash"], input="n\n")

    assert result.exit_code == 0, result.output
    assert uninstall_calls == []
# end def test_uninstall_command_removes_completion_and_declines_uv_uninstall_by_default


def test_uninstall_command_runs_uv_tool_uninstall_when_confirmed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    uninstall_calls: list[str] = []
    monkeypatch.setattr(
        "game_collections.cli.tool_install.uninstall_uv_tool",
        lambda: uninstall_calls.append("uninstalled") or SimpleNamespace(stdout="uninstalled", stderr=""),
    )

    result = CliRunner().invoke(app, ["uninstall", "--shell", "bash"], input="y\n")

    assert result.exit_code == 0, result.output
    assert uninstall_calls == ["uninstalled"]
# end def test_uninstall_command_runs_uv_tool_uninstall_when_confirmed


def test_deinstall_alias_behaves_identically_to_uninstall(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    result = CliRunner().invoke(app, ["deinstall", "--shell", "bash"], input="n\n")

    assert result.exit_code == 0, result.output
# end def test_deinstall_alias_behaves_identically_to_uninstall
