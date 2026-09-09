"""PyPI-vs-local version comparison and the `uv tool install`/`uv tool uninstall`
subprocess boundary backing the `install`/`uninstall` CLI commands."""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import httpx
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

PACKAGE_NAME = "game-collections"
PYPI_URL_TEMPLATE = "https://pypi.org/pypi/{package}/json"


class InstallError(RuntimeError):
    """An `install`/`uninstall` operation failed in a way that needs a human to look."""

# end class InstallError


class PyPiInfo(BaseModel):
    """The one field of PyPI's `info` object this project reads.

    PyPI's JSON API is a large, third-party-owned payload with many fields
    (`releases`, `urls`, `vulnerabilities`, `last_serial`, ...) this project
    has no stake in. Unlike this project's own strict models (see
    `models.StrictModel`, used for data this project generates or replaces
    on disk), extra fields here are expected and ignored rather than
    treated as format drift.
    """

    model_config = ConfigDict(extra="ignore")

    version: str
# end class PyPiInfo


class PyPiPackageMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    info: PyPiInfo
# end class PyPiPackageMetadata


def local_version(repository_root: Path) -> Version:
    """Read the package version out of `pyproject.toml` at the repo root."""
    pyproject_path = repository_root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        raw_version = data["project"]["version"]
        return Version(raw_version)
    except (OSError, tomllib.TOMLDecodeError, KeyError, InvalidVersion) as error:
        raise InstallError(f"could not read a version from {pyproject_path}: {error}") from error
    # end try
# end def local_version


def fetch_pypi_metadata(package_name: str, timeout: float) -> httpx.Response:
    return httpx.get(PYPI_URL_TEMPLATE.format(package=package_name), timeout=timeout)
# end def fetch_pypi_metadata


def latest_pypi_version(
    package_name: str = PACKAGE_NAME,
    *,
    timeout: float = 10.0,
    fetch: Callable[[str, float], httpx.Response] = fetch_pypi_metadata,
) -> Version | None:
    """Latest published version on PyPI, or `None` if not published yet (404)."""
    try:
        response = fetch(package_name, timeout)
    except httpx.HTTPError as error:
        raise InstallError(f"could not reach PyPI: {error}") from error
    # end try
    if response.status_code == 404:
        return None
    # end if
    try:
        response.raise_for_status()
        metadata = PyPiPackageMetadata.model_validate(response.json())
        return Version(metadata.info.version)
    except (httpx.HTTPError, ValueError, InvalidVersion) as error:
        raise InstallError(f"PyPI response for {package_name!r} failed or changed format: {error}") from error
    # end try
# end def latest_pypi_version


def choose_install_source(repository_root: Path, package_name: str = PACKAGE_NAME) -> Literal["pypi", "editable"]:
    """Pick 'pypi' only when PyPI has a strictly newer release than the local checkout.

    Covers 'editable' for: PyPI not yet published, PyPI equal to local, or
    PyPI behind the local (in-development) version.
    """
    local = local_version(repository_root)
    pypi = latest_pypi_version(package_name)
    if pypi is not None and pypi > local:
        return "pypi"
    # end if
    return "editable"
# end def choose_install_source


def run_subprocess(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True)
# end def run_subprocess


def install_uv_tool(
    repository_root: Path,
    source: Literal["pypi", "editable"],
    package_name: str = PACKAGE_NAME,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_subprocess,
) -> subprocess.CompletedProcess[str]:
    """Install `package_name` as a `uv` tool, from PyPI or editable against `repository_root`."""
    if source == "pypi":
        args = ["uv", "tool", "install", "--force", package_name]
    else:
        args = ["uv", "tool", "install", "--force", "--editable", str(repository_root)]
    # end if
    result = runner(args)
    if result.returncode != 0:
        raise InstallError(f"`{' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
    # end if
    return result
# end def install_uv_tool


def uninstall_uv_tool(
    package_name: str = PACKAGE_NAME,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_subprocess,
) -> subprocess.CompletedProcess[str]:
    args = ["uv", "tool", "uninstall", package_name]
    result = runner(args)
    if result.returncode != 0:
        raise InstallError(f"`{' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
    # end if
    return result
# end def uninstall_uv_tool
