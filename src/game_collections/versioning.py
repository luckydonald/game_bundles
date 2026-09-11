"""Generic on-disk version envelope and migration machinery shared by every source.

Every archived `metadata.json`/`source.json` is wrapped as `{"version": ..., "data": ...}`
(`Versioned[VERSION, DATA]`). `SchemaDateVersion` is the version type: a comparable,
precision-honest date/time tuple, hand-bumped in each source's own model file on every
shape change. `trajectory()` advances one file one migration step at a time (a generator,
not an eager end-to-end transform) so an outer wavefront driver can group many files by
"which step they're currently on" and commit one group at a time - see
`sources/README.md` and the `swift-sauteeing-dream` plan for the full design rationale.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Annotated, Any, NamedTuple

from pydantic import AfterValidator, BaseModel, ConfigDict


class SchemaDateVersion(NamedTuple):
    """A comparable version tag: the date/time this shape was declared, at whatever precision is known.

    Valid precisions only: date-only, or date + hour+minute (together), optionally
    extended by second, optionally further extended by fraction. Never hour or minute
    alone, never second/fraction without the coarser fields - see `_validate_precision`.
    """

    year: int
    month: int
    day: int
    hour: int | None = None
    minute: int | None = None
    second: int | None = None
    fraction: float | None = None

    def render(self) -> str:
        """Human string at whatever precision this value actually carries."""
        if self.hour is None:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        # end if
        assert self.minute is not None
        text = f"{self.year:04d}-{self.month:02d}-{self.day:02d} {self.hour:02d}:{self.minute:02d}"
        if self.second is None:
            return text
        # end if
        text += f":{self.second:02d}"
        if self.fraction:
            text += f"{self.fraction:.6f}".lstrip("0")
        # end if
        return text
    # end def render

    def sort_key(self) -> tuple[int, int, int, int, int, int, float]:
        """A total-ordering key so two values of different precision still compare sanely."""
        return (self.year, self.month, self.day, self.hour or 0, self.minute or 0, self.second or 0, self.fraction or 0.0)
    # end def sort_key

# end class SchemaDateVersion


def _validate_precision(value: SchemaDateVersion) -> SchemaDateVersion:
    """Enforce: date-only, or hour+minute together, optionally +second, optionally +fraction."""
    has_hour, has_minute = value.hour is not None, value.minute is not None
    if has_hour != has_minute:
        raise ValueError("SchemaDateVersion: hour and minute must be given together - minute-accurate time, or none")
    # end if
    if value.second is not None and not has_minute:
        raise ValueError("SchemaDateVersion: second requires hour and minute")
    # end if
    if value.fraction is not None and value.second is None:
        raise ValueError("SchemaDateVersion: fraction requires hour, minute, and second")
    # end if
    return value
# end def _validate_precision


CheckedSchemaDateVersion = Annotated[SchemaDateVersion, AfterValidator(_validate_precision)]

# The sentinel for "no version envelope at all" - every file on disk before this plan
# shipped. Passes `_validate_precision` trivially (date-only).
LEGACY_VERSION = SchemaDateVersion(1970, 1, 1)


class Versioned[VERSION, DATA](BaseModel):
    """The on-disk envelope: `{"version": ..., "data": ...}`, replacing each source's
    old embedded `schema_version`/`schema`-aliased field entirely."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: VERSION
    data: DATA

# end class Versioned


class _VersionPeek(BaseModel):
    """Cheaply read just `version` off a raw JSON object, without validating `data`
    against any particular model - `data` may be an arbitrary older shape that won't
    validate until it's been migrated."""

    model_config = ConfigDict(extra="ignore")

    version: CheckedSchemaDateVersion


def peek_version(raw: Mapping[str, Any]) -> tuple[SchemaDateVersion, Any]:
    """Return `(version, data)` for one raw JSON object, enveloped or not.

    A pre-envelope legacy file has no top-level `version`/`data` keys at all - the
    entire raw object *is* `data`, and its version is `LEGACY_VERSION`. This is the
    common case for every file that predates this plan, not a hypothetical edge case.
    """
    if "version" in raw and "data" in raw:
        return _VersionPeek.model_validate({"version": raw["version"]}).version, raw["data"]
    # end if
    return LEGACY_VERSION, raw
# end def peek_version


MigrationStep = tuple[SchemaDateVersion, Callable[[Any], Any]]


def trajectory(
    initial_version: SchemaDateVersion,
    initial_data: Any,
    steps: Sequence[MigrationStep],
) -> Iterator[Versioned[SchemaDateVersion, Any]]:
    """Yield one `Versioned` snapshot per outstanding migration step for one file, lazily.

    `steps` must be sorted ascending by target version. No `current_version` parameter:
    every step whose target is ahead of the file's own version runs, in the list's own
    order, and "latest" is simply the list's last entry. Returning a generator (rather
    than the single collapsed end state) lets an outer wavefront driver advance many
    files exactly one step at a time and group them by "which step they're on" for
    commit purposes, without ever materializing a file's whole future trajectory.
    """
    version, data = initial_version, initial_data
    for target_version, migrate_fn in steps:
        if version.sort_key() >= target_version.sort_key():
            continue
        # end if
        data = migrate_fn(data)
        version = target_version
        yield Versioned[SchemaDateVersion, Any](version=version, data=data)
    # end for
# end def trajectory
