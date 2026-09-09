from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from game_collections.install import tool_install


def _write_pyproject(tmp_path: Path, version: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "game-collections"\nversion = "{version}"\n', encoding="utf-8"
    )
    return tmp_path
# end def _write_pyproject


def test_local_version_reads_pyproject_toml(tmp_path: Path) -> None:
    repository_root = _write_pyproject(tmp_path, "1.2.3")
    assert tool_install.local_version(repository_root) == tool_install.Version("1.2.3")
# end def test_local_version_reads_pyproject_toml


def test_local_version_raises_install_error_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(tool_install.InstallError):
        tool_install.local_version(tmp_path)
    # end with
# end def test_local_version_raises_install_error_on_missing_file


def test_local_version_raises_install_error_on_malformed_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid toml", encoding="utf-8")
    with pytest.raises(tool_install.InstallError):
        tool_install.local_version(tmp_path)
    # end with
# end def test_local_version_raises_install_error_on_malformed_toml


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
    # end def __init__

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]
        # end if
    # end def raise_for_status

    def json(self) -> dict[str, object]:
        assert self._payload is not None
        return self._payload
    # end def json
# end class _FakeResponse


def test_latest_pypi_version_returns_none_on_404() -> None:
    def fetch(package_name: str, timeout: float) -> httpx.Response:
        return _FakeResponse(404)  # type: ignore[return-value]
    # end def fetch

    assert tool_install.latest_pypi_version("game-collections", fetch=fetch) is None
# end def test_latest_pypi_version_returns_none_on_404


def test_latest_pypi_version_parses_version_field() -> None:
    def fetch(package_name: str, timeout: float) -> httpx.Response:
        return _FakeResponse(200, {"info": {"version": "2.0.0"}, "releases": {}, "extra_field": "ignored"})  # type: ignore[return-value]
    # end def fetch

    assert tool_install.latest_pypi_version("game-collections", fetch=fetch) == tool_install.Version("2.0.0")
# end def test_latest_pypi_version_parses_version_field


def test_latest_pypi_version_raises_install_error_on_malformed_payload() -> None:
    def fetch(package_name: str, timeout: float) -> httpx.Response:
        return _FakeResponse(200, {"releases": {}})  # type: ignore[return-value]
    # end def fetch

    with pytest.raises(tool_install.InstallError):
        tool_install.latest_pypi_version("game-collections", fetch=fetch)
    # end with
# end def test_latest_pypi_version_raises_install_error_on_malformed_payload


def test_choose_install_source_prefers_pypi_when_strictly_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_install, "local_version", lambda repository_root: tool_install.Version("1.0.0"))
    monkeypatch.setattr(tool_install, "latest_pypi_version", lambda package_name: tool_install.Version("2.0.0"))
    assert tool_install.choose_install_source(tmp_path) == "pypi"
# end def test_choose_install_source_prefers_pypi_when_strictly_newer


def test_choose_install_source_prefers_editable_when_pypi_not_newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_install, "local_version", lambda repository_root: tool_install.Version("2.0.0"))
    monkeypatch.setattr(tool_install, "latest_pypi_version", lambda package_name: tool_install.Version("2.0.0"))
    assert tool_install.choose_install_source(tmp_path) == "editable"
# end def test_choose_install_source_prefers_editable_when_pypi_not_newer


def test_choose_install_source_prefers_editable_when_pypi_unpublished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_install, "local_version", lambda repository_root: tool_install.Version("0.1.0"))
    monkeypatch.setattr(tool_install, "latest_pypi_version", lambda package_name: None)
    assert tool_install.choose_install_source(tmp_path) == "editable"
# end def test_choose_install_source_prefers_editable_when_pypi_unpublished


def _fake_runner(returncode: int = 0) -> tuple[list[list[str]], object]:
    calls: list[list[str]] = []

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args=list(args), returncode=returncode, stdout="ok", stderr="")
    # end def runner

    return calls, runner
# end def _fake_runner


def test_install_uv_tool_builds_pypi_args(tmp_path: Path) -> None:
    calls, runner = _fake_runner()
    tool_install.install_uv_tool(tmp_path, "pypi", "game-collections", runner=runner)
    assert calls == [["uv", "tool", "install", "--force", "game-collections"]]
# end def test_install_uv_tool_builds_pypi_args


def test_install_uv_tool_builds_editable_args_with_repo_path(tmp_path: Path) -> None:
    calls, runner = _fake_runner()
    tool_install.install_uv_tool(tmp_path, "editable", "game-collections", runner=runner)
    assert calls == [["uv", "tool", "install", "--force", "--editable", str(tmp_path)]]
# end def test_install_uv_tool_builds_editable_args_with_repo_path


def test_install_uv_tool_raises_install_error_on_nonzero_exit(tmp_path: Path) -> None:
    _calls, runner = _fake_runner(returncode=1)
    with pytest.raises(tool_install.InstallError):
        tool_install.install_uv_tool(tmp_path, "editable", "game-collections", runner=runner)
    # end with
# end def test_install_uv_tool_raises_install_error_on_nonzero_exit


def test_uninstall_uv_tool_builds_expected_args() -> None:
    calls, runner = _fake_runner()
    tool_install.uninstall_uv_tool("game-collections", runner=runner)
    assert calls == [["uv", "tool", "uninstall", "game-collections"]]
# end def test_uninstall_uv_tool_builds_expected_args


def test_uninstall_uv_tool_raises_on_failure() -> None:
    _calls, runner = _fake_runner(returncode=1)
    with pytest.raises(tool_install.InstallError):
        tool_install.uninstall_uv_tool("game-collections", runner=runner)
    # end with
# end def test_uninstall_uv_tool_raises_on_failure
