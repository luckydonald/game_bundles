"""Confidence-scored bundle start/end timestamps, shared by every source's `*Dates` model."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.names import SourceName


_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ScrapedTimestamp(StrictModel):
    """One `start`/`end` value as actually derived from a source, plus how sure we are.

    `iso` preserves whatever precision the source gave us (date-only, or date+time
    down to minute/second/fraction, always with an explicit UTC offset unless it's
    date-only); `timestamp` is the same instant as a unix epoch float, cross-checked
    against `iso` on construction so the two can never silently drift apart.
    """

    iso: NonEmptyString
    timestamp: float
    confidence: float = Field(ge=0.0, le=1.0)
    source: SourceName

    @model_validator(mode="after")
    def validate_consistent(self) -> Self:
        if _DATE_ONLY_PATTERN.fullmatch(self.iso):
            parsed = datetime.strptime(self.iso, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            try:
                parsed = datetime.fromisoformat(self.iso)
            except ValueError as error:
                raise ValueError(f"ScrapedTimestamp.iso is not valid ISO 8601: {self.iso!r}") from error
            # end try
            if parsed.tzinfo is None:
                raise ValueError("ScrapedTimestamp.iso must carry a UTC offset unless it's date-only")
            # end if
        # end if
        if abs(parsed.timestamp() - self.timestamp) > 1.0:
            raise ValueError(f"ScrapedTimestamp.timestamp does not match iso: {self.timestamp} vs {parsed.timestamp()}")
        # end if
        return self
    # end def validate_consistent

# end class ScrapedTimestamp


def build_scraped_timestamp(value: datetime, source: SourceName, confidence: float) -> ScrapedTimestamp:
    """Build a `ScrapedTimestamp` from an already-parsed, timezone-aware `datetime`.

    Precision in `iso` is inferred from `value` itself: a nonzero `microsecond` keeps
    fractional-second precision, a nonzero `second` (with zero microsecond) keeps
    whole-second precision, otherwise it's rendered at minute precision - a reasonable
    proxy for what shape of field the source actually gave us, not a perfect one (a
    genuinely minute-precision source whose seconds happen to be non-zero would over-render).
    """
    if value.tzinfo is None:
        raise ValueError("build_scraped_timestamp requires a timezone-aware datetime")
    # end if
    if value.microsecond:
        precision = "microseconds"
    elif value.second:
        precision = "seconds"
    else:
        precision = "minutes"
    # end if
    return ScrapedTimestamp(
        iso=value.isoformat(timespec=precision), timestamp=value.timestamp(), confidence=confidence, source=source
    )
# end def build_scraped_timestamp


def _precision_rank(iso: str) -> int:
    """Rough "how detailed is this iso string" ranking, for the confidence==1.0 tie-break."""
    if "." in iso:
        return 4
    # end if
    if iso.count(":") >= 2:
        return 3
    # end if
    if ":" in iso:
        return 2
    # end if
    return 1
# end def _precision_rank


@dataclass(frozen=True, slots=True)
class TimestampReport:
    """One line (or block) for the end-of-run summary: an info note or an unresolved conflict."""

    kind: Literal["info", "conflict"]
    message: str

# end class TimestampReport


def _describe(role: str, value: ScrapedTimestamp, is_older: bool) -> str:
    order = "older" if is_older else "newer"
    return f"  {role:<8} ({order}): {value.iso} (confidence {value.confidence}, source={value.source})"
# end def _describe


def _prompt_conflict(label: str, existing: ScrapedTimestamp, fresh: ScrapedTimestamp) -> ScrapedTimestamp:
    print(f"CONFLICT {label}: which value should be kept?")
    print(f"  [1] existing: {existing.iso} (confidence {existing.confidence}, source={existing.source})")
    print(f"  [2] fresh:    {fresh.iso} (confidence {fresh.confidence}, source={fresh.source})")
    while True:
        choice = input("Keep [1/2]: ").strip()
        if choice == "1":
            return existing
        # end if
        if choice == "2":
            return fresh
        # end if
    # end while
# end def _prompt_conflict


def merge_scraped_timestamp(
    existing: ScrapedTimestamp | None,
    fresh: ScrapedTimestamp | None,
    *,
    label: str,
    urls: Sequence[str] = (),
    interactive: bool | None = None,
) -> tuple[ScrapedTimestamp | None, TimestampReport | None]:
    """Resolve an on-disk `start`/`end` value against a freshly-derived one.

    See `sources/README.md`/the confidence-scored-dates plan for the full rule set:
    a `0.0`-confidence (legacy, never-verified) existing value is always replaced; two
    equally-confident (1.0) agreeing values keep whichever `iso` is more precise; a real
    disagreement is never auto-resolved silently - interactively (a TTY) you're asked
    which to keep, non-interactively (CI/`--git`) the chronologically older value is
    kept and the conflict is reported either way.
    """
    if fresh is None:
        return existing, None
    # end if
    if existing is None:
        return fresh, None
    # end if
    if existing.confidence == 0.0:
        if existing.iso == fresh.iso and existing.source == fresh.source:
            return fresh, None
        # end if
        report = TimestampReport(
            "info",
            f"{label}: replaced unverified {existing.iso} (source={existing.source}) "
            f"with {fresh.iso} (confidence {fresh.confidence}, source={fresh.source})",
        )
        return fresh, report
    # end if
    if existing.confidence == 1.0 and fresh.confidence == 1.0 and abs(existing.timestamp - fresh.timestamp) < 1.0:
        chosen = fresh if _precision_rank(fresh.iso) > _precision_rank(existing.iso) else existing
        return chosen, None
    # end if

    existing_is_older = existing.timestamp <= fresh.timestamp
    is_tty = sys.stdin.isatty() if interactive is None else interactive
    if is_tty:
        chosen = _prompt_conflict(label, existing, fresh)
        kept_line = f"  kept: user-selected ({'existing' if chosen is existing else 'fresh'})"
    else:
        chosen = existing if existing_is_older else fresh
        kept_line = f"  kept: {'existing' if chosen is existing else 'fresh'} (older) - resolve by hand if wrong"
    # end if
    lines = [
        f"CONFLICT {label}:",
        _describe("existing", existing, existing_is_older),
        _describe("fresh", fresh, not existing_is_older),
        kept_line,
    ]
    if urls:
        lines.append("  urls: " + " , ".join(urls))
    # end if
    return chosen, TimestampReport("conflict", "\n".join(lines))
# end def merge_scraped_timestamp
