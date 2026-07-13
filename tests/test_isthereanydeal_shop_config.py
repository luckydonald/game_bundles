from __future__ import annotations

from pathlib import Path

from game_collections.sources.isthereanydeal.shop_config import load_shop_config


def test_load_shop_config_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_shop_config(tmp_path / "missing.yml") == {}
# end def test_load_shop_config_missing_file_returns_empty


def test_load_shop_config_handles_id_less_and_slug_less_entries(tmp_path: Path) -> None:
    path = tmp_path / "isthereanydeal-shops.yml"
    path.write_text(
        """
        schema: 2
        shops:
          - name: Adventure Shop
            id: 1
            slug:
          - name: Steam
            id: 61
            slug: steam
          - name: App Store
            slug: appstore
        """,
        encoding="utf-8",
    )
    shop_names = load_shop_config(path)
    assert shop_names == {1: "Adventure Shop", 61: "Steam"}
# end def test_load_shop_config_handles_id_less_and_slug_less_entries
