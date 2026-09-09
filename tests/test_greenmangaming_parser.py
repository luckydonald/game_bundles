from __future__ import annotations

from datetime import UTC, datetime

import pytest

from game_collections.sources.greenmangaming.parser import (
    GmgParseError,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_product_fragment,
)


INDEX_PAGE = """
<div class="product-grid">
<div class="product-card" data-category="video-games" data-end-date="2026-07-21T18:00">
  <a href="https://www.greenmangamingbundles.com/bundles/metroidvania-madness/?utm_term=flatpage" class="packshot-link">
    <span class="product-image-wrapper"><img src="a.png" /></span>
  </a>
  <h3 class="product-title">Metroidvania</h3>
  <div class="price-cta-section">
    <a href="https://www.greenmangamingbundles.com/bundles/metroidvania-madness/?utm_term=flatpage" class="cta-button">View Bundle</a>
  </div>
</div>
<div class="product-card" data-category="books-comics" data-end-date="2026-07-23T18:00">
  <a href="https://www.greenmangamingbundles.com/bundles/the-data-ai-career-accelerator/?utm_term=flatpage" class="packshot-link">
    <span class="product-image-wrapper"><img src="b.png" /></span>
  </a>
  <h3 class="product-title">Packt</h3>
  <div class="price-cta-section">
    <a href="https://www.greenmangamingbundles.com/bundles/the-data-ai-career-accelerator/?utm_term=flatpage" class="cta-button">View Bundle</a>
  </div>
</div>
</div>
"""


def _bundle_item(product_id: str, tier_name: str, title: str) -> str:
    return f"""
<figure class="col-6 bundle-item"
        hx-get="/bundles/metroidvania-madness/product/{product_id}/"
        hx-vals='{{ "display_mode": "unlocked", "tier_name": "{tier_name}"}}'>
  <strong class="game-title">{title}</strong>
</figure>
"""
# end def _bundle_item


def _tier_radio(identifier: str, name: str, item_count: int, price: str) -> str:
    return f"""
<label data-bundle-radio-card class="custom-radio-card">
  <input type="radio" name="amount" data-upgrade-tier-id="{identifier}" value="{identifier}:{price}" />
  <span class="bundle-type">{name}</span>
  <small>{item_count} Items</small>
  <span class="price">€{price}</span>
</label>
"""
# end def _tier_radio


BUNDLE_PAGE = f"""
<h1 class="d-none d-xl-block">METROIDVANIA MADNESS</h1>
{_bundle_item("343", "Bronze", "Afterimage")}
{_bundle_item("344", "Bronze", "Vomitoreum")}
{_bundle_item("345", "Silver", "GRIME")}
{_bundle_item("341", "Silver", "Islets")}
{_bundle_item("346", "Gold", "Laika: Aged Through Blood")}
{_bundle_item("347", "Gold", "Bō: Path of the Teal Lotus")}
<input type="hidden" name="currency_code" value="EUR" />
{_tier_radio("bronze", "Bronze", 2, "8.00")}
{_tier_radio("silver", "Silver", 4, "12.00")}
{_tier_radio("gold", "Gold", 6, "14.00")}
<label class="custom-radio-card">
  <input type="radio" name="amount" value="custom_amount" />
</label>
"""


PRODUCT_FRAGMENT = """
<dl>
  <dt>DRM</dt>
  <dd>Steam</dd>
  <dt>Platform</dt>
  <dd>Windows</dd>
  <dt>Developer</dt>
  <dd>Brainwash Gang</dd>
  <dt>Publisher</dt>
  <dd>Thunderful Publishing</dd>
</dl>
<section id="gameDescriptionCollapse-346">
  <p>Laika is a coyote mother and fierce warrior.</p>
</section>
"""


def test_parse_bundle_index_page_only_returns_video_games_slugs() -> None:
    slugs = parse_bundle_index_page(INDEX_PAGE)

    assert slugs == ["metroidvania-madness"]
# end def test_parse_bundle_index_page_only_returns_video_games_slugs


def test_parse_bundle_index_page_requires_product_cards() -> None:
    with pytest.raises(GmgParseError):
        parse_bundle_index_page("<div>nothing here</div>")
    # end with
# end def test_parse_bundle_index_page_requires_product_cards


def test_parse_bundle_page_builds_cumulative_tiers() -> None:
    archive, source = parse_bundle_page(BUNDLE_PAGE, "metroidvania-madness", datetime(2026, 7, 12, tzinfo=UTC))

    assert archive.name == "METROIDVANIA MADNESS"
    assert archive.currency_code == "EUR"
    assert [tier.identifier for tier in archive.tiers] == ["bronze", "silver", "gold"]
    assert [item.title for item in archive.tiers[0].items] == ["Afterimage", "Vomitoreum"]
    assert [item.title for item in archive.tiers[1].items] == ["Afterimage", "Vomitoreum", "GRIME", "Islets"]
    assert len(archive.tiers[2].items) == 6
    assert archive.tiers[0].price is not None
    assert archive.tiers[0].price.value == 8.0
    assert archive.tiers[0].price.currency_code == "EUR"
    assert source["title_text"]
# end def test_parse_bundle_page_builds_cumulative_tiers


def test_parse_bundle_page_rejects_mismatched_tier_item_count() -> None:
    bad_page = BUNDLE_PAGE.replace("<small>2 Items</small>", "<small>3 Items</small>")
    with pytest.raises(GmgParseError, match="advertises 3 items"):
        parse_bundle_page(bad_page, "metroidvania-madness", datetime(2026, 7, 12, tzinfo=UTC))
    # end with
# end def test_parse_bundle_page_rejects_mismatched_tier_item_count


def test_parse_bundle_page_decodes_html_entities() -> None:
    entity_page = BUNDLE_PAGE.replace(
        "<h1 class=\"d-none d-xl-block\">METROIDVANIA MADNESS</h1>",
        "<h1 class=\"d-none d-xl-block\">Rock &amp; Roll&#x27;s Madness</h1>",
    ).replace(">Afterimage<", ">Tom &amp; Jerry&#x27;s Chase<")
    archive, _source = parse_bundle_page(entity_page, "metroidvania-madness", datetime(2026, 7, 12, tzinfo=UTC))

    assert archive.name == "Rock & Roll's Madness"
    assert archive.tiers[0].items[0].title == "Tom & Jerry's Chase"
# end def test_parse_bundle_page_decodes_html_entities


def test_parse_bundle_page_requires_title() -> None:
    with pytest.raises(GmgParseError):
        parse_bundle_page("<h1></h1>", "metroidvania-madness", datetime(2026, 7, 12, tzinfo=UTC))
    # end with
# end def test_parse_bundle_page_requires_title


def test_parse_product_fragment_extracts_drm_and_metadata() -> None:
    fields = parse_product_fragment(PRODUCT_FRAGMENT, "346")

    assert fields["drm"] == "Steam"
    assert fields["platform"] == "Windows"
    assert fields["developer"] == "Brainwash Gang"
    assert fields["publisher"] == "Thunderful Publishing"
    assert fields["redeem_on"] == ["steam"]
    assert "coyote mother" in fields["description"]
# end def test_parse_product_fragment_extracts_drm_and_metadata


def test_parse_product_fragment_decodes_html_entities() -> None:
    entity_fragment = PRODUCT_FRAGMENT.replace("<dd>Thunderful Publishing</dd>", "<dd>Thunderful &amp; Friends&#x27; Publishing</dd>")

    fields = parse_product_fragment(entity_fragment, "346")

    assert fields["publisher"] == "Thunderful & Friends' Publishing"
# end def test_parse_product_fragment_decodes_html_entities


def test_parse_product_fragment_requires_drm() -> None:
    with pytest.raises(GmgParseError):
        parse_product_fragment("<dl></dl>", "346")
    # end with
# end def test_parse_product_fragment_requires_drm
