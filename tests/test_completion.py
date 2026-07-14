from __future__ import annotations

from game_collections.completion import evaluate_completion
from game_collections.models import Game


def _game(name: str, ids: list[str]) -> Game:
    return Game(name=name, ids=ids)
# end def _game


def test_steam_games_count_owned_and_missing() -> None:
    games = [_game("A", ["steam:10"]), _game("B", ["steam:20"]), _game("C", ["steam:30"])]

    completion = evaluate_completion(games, {10, 20})

    assert completion.total == 3
    assert completion.owned_count == 2
    assert completion.missing_count == 1
    assert completion.owned_ids == ["steam:10", "steam:20"]
    assert completion.missing_ids == ["steam:30"]
    assert completion.unsupported_ids == []
# end def test_steam_games_count_owned_and_missing


def test_game_owned_via_any_of_its_multiple_steam_ids() -> None:
    games = [_game("A", ["steam:10", "steam:11"])]

    completion = evaluate_completion(games, {11})

    assert completion.total == 1
    assert completion.owned_count == 1
    assert completion.missing_count == 0
# end def test_game_owned_via_any_of_its_multiple_steam_ids


def test_unresolved_hide_excludes_from_everything() -> None:
    games = [_game("Real", ["steam:10"]), _game("Unknown", ["unresolved:source:isthereanydeal:1:x"])]

    completion = evaluate_completion(games, set(), unresolved_handling="hide")

    assert completion.total == 1
    assert completion.missing_count == 1
    assert completion.unsupported_ids == []
    assert completion.missing_ids == ["steam:10"]
# end def test_unresolved_hide_excludes_from_everything


def test_unresolved_ignore_default_reports_unsupported_but_does_not_count() -> None:
    games = [_game("Real", ["steam:10"]), _game("Unknown", ["unresolved:source:isthereanydeal:1:x"])]

    completion = evaluate_completion(games, {10})

    assert completion.total == 1
    assert completion.owned_count == 1
    assert completion.missing_count == 0
    assert completion.unsupported_ids == ["Unknown"]
# end def test_unresolved_ignore_default_reports_unsupported_but_does_not_count


def test_unresolved_enforce_counts_as_missing() -> None:
    games = [_game("Real", ["steam:10"]), _game("Unknown", ["unresolved:source:isthereanydeal:1:x"])]

    completion = evaluate_completion(games, {10}, unresolved_handling="enforce")

    assert completion.total == 2
    assert completion.owned_count == 1
    assert completion.missing_count == 1
    assert completion.unsupported_ids == []
    assert completion.missing_ids == ["unresolved:source:isthereanydeal:1:x"]
# end def test_unresolved_enforce_counts_as_missing


def test_unconfigured_store_handling_hide_ignore_enforce() -> None:
    games = [_game("GogGame", ["gog:some-slug"])]

    hidden = evaluate_completion(games, set(), unconfigured_handling="hide")
    ignored = evaluate_completion(games, set(), unconfigured_handling="ignore")
    enforced = evaluate_completion(games, set(), unconfigured_handling="enforce")

    assert hidden.total == 0
    assert hidden.unsupported_ids == []

    assert ignored.total == 0
    assert ignored.unsupported_ids == ["GogGame"]

    assert enforced.total == 1
    assert enforced.missing_count == 1
    assert enforced.missing_ids == ["gog:some-slug"]
# end def test_unconfigured_store_handling_hide_ignore_enforce


def test_unresolved_and_unconfigured_handling_are_independent() -> None:
    games = [
        _game("Unresolved", ["unresolved:source:isthereanydeal:1:x"]),
        _game("Gog", ["gog:some-slug"]),
    ]

    completion = evaluate_completion(games, set(), unresolved_handling="enforce", unconfigured_handling="hide")

    assert completion.total == 1
    assert completion.missing_count == 1
    assert completion.missing_ids == ["unresolved:source:isthereanydeal:1:x"]
    assert completion.unsupported_ids == []
# end def test_unresolved_and_unconfigured_handling_are_independent
