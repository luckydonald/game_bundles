from __future__ import annotations

from collections.abc import Iterator

import pytest

from game_collections.sources.prompting import (
    ChosenNames,
    EnterMultiple,
    announce_exact_match,
    choose_store_candidate,
    collect_one_name,
)
from game_collections.sources.storefronts import StoreCandidate


def _candidate(appid: int, title: str = "Sample Game") -> StoreCandidate:
    return StoreCandidate(
        title=title,
        url=f"https://store.steampowered.com/app/{appid}/",
        qualified_id=f"steam:{appid}",
    )
# end def _candidate


def _responses(monkeypatch: pytest.MonkeyPatch, values: list[str]) -> None:
    """Feed canned answers to successive `typer.prompt` calls."""
    queue: Iterator[str] = iter(values)

    def fake_prompt(_text: str, default: str = "", **_kwargs: object) -> str:
        return next(queue, default)
    # end def fake_prompt

    monkeypatch.setattr("game_collections.sources.prompting.typer.prompt", fake_prompt)
# end def _responses


def test_choose_store_candidate_includes_multiple_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _responses(monkeypatch, ["2"])  # "Other…" - the last row

    choose_store_candidate("Sample Game", "steam", [_candidate(42)])

    assert "Multiple…" in capsys.readouterr().out
# end def test_choose_store_candidate_includes_multiple_by_default


def test_choose_store_candidate_omits_multiple_when_disallowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _responses(monkeypatch, ["2"])  # "Other…" - now the last row, since Multiple is gone

    choose_store_candidate("Sample Game", "steam", [_candidate(42)], allow_multiple=False)

    assert "Multiple…" not in capsys.readouterr().out
# end def test_choose_store_candidate_omits_multiple_when_disallowed


def test_choose_store_candidate_interleaved_returns_enter_multiple_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _responses(monkeypatch, ["2"])  # candidate 1 + Multiple(2) + Other(3) -> select Multiple

    selected = choose_store_candidate("Sample Game", "steam", [_candidate(42)], interleaved=True)

    assert isinstance(selected, EnterMultiple)
# end def test_choose_store_candidate_interleaved_returns_enter_multiple_immediately


def test_choose_store_candidate_non_interleaved_collects_names_upfront(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Select Multiple(2), then two names, then a blank to finish.
    _responses(monkeypatch, ["2", "Game A", "Game B", ""])

    selected = choose_store_candidate("Sample Game", "steam", [_candidate(42)])

    assert selected == ChosenNames(names=["Game A", "Game B"])
# end def test_choose_store_candidate_non_interleaved_collects_names_upfront


def test_choose_store_candidate_rejects_name_already_known(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # "Game A" collides with a name already destined for the bundle; retry with "Game B".
    _responses(monkeypatch, ["2", "Game A", "Game B", ""])
    known_names = {"game a"}

    selected = choose_store_candidate("Sample Game", "steam", [_candidate(42)], known_names=known_names)

    assert selected == ChosenNames(names=["Game B"])
    assert "already used by another game" in capsys.readouterr().err
    assert known_names == {"game a", "game b"}
# end def test_choose_store_candidate_rejects_name_already_known


def test_choose_store_candidate_rejects_duplicate_within_same_split(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Typing "Game A" twice in the same "Multiple…" session is rejected on the second attempt.
    _responses(monkeypatch, ["2", "Game A", "Game A", "Game B", ""])

    selected = choose_store_candidate("Sample Game", "steam", [_candidate(42)], known_names=set())

    assert selected == ChosenNames(names=["Game A", "Game B"])
    assert "already used by another game" in capsys.readouterr().err
# end def test_choose_store_candidate_rejects_duplicate_within_same_split


def test_announce_exact_match_prints_id_and_url(capsys: pytest.CaptureFixture[str]) -> None:
    announce_exact_match("steam:42", "https://store.steampowered.com/app/42/")

    out = capsys.readouterr().out
    assert "Exact match found — steam:42" in out
    assert "https://store.steampowered.com/app/42/" in out
# end def test_announce_exact_match_prints_id_and_url


def test_collect_one_name_prompts_with_running_count(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_prompts: list[str] = []

    def fake_prompt(text: str, **_kwargs: object) -> str:
        seen_prompts.append(text)
        return "Torchlight 2"
    # end def fake_prompt

    monkeypatch.setattr("game_collections.sources.prompting.typer.prompt", fake_prompt)

    name = collect_one_name(1)

    assert name == "Torchlight 2"
    assert seen_prompts == ["Name of one separate game (1 so far) (blank to finish)"]
# end def test_collect_one_name_prompts_with_running_count


def test_collect_one_name_returns_none_for_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("game_collections.sources.prompting.typer.prompt", lambda _text, **_kwargs: "")

    assert collect_one_name(0) is None
# end def test_collect_one_name_returns_none_for_blank


def test_collect_one_name_rejects_name_already_known(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _responses(monkeypatch, ["Torchlight 2", "Torchlight 3"])
    known_names = {"torchlight 2"}

    name = collect_one_name(0, known_names)

    assert name == "Torchlight 3"
    assert "already used by another game" in capsys.readouterr().err
    assert known_names == {"torchlight 2", "torchlight 3"}
# end def test_collect_one_name_rejects_name_already_known
