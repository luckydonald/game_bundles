from __future__ import annotations

from pathlib import Path

from game_collections.install import shell_completion


def test_detect_shell_recognizes_bash_and_zsh_by_basename() -> None:
    assert shell_completion.detect_shell("/bin/bash") == "bash"
    assert shell_completion.detect_shell("/usr/bin/zsh") == "zsh"
# end def test_detect_shell_recognizes_bash_and_zsh_by_basename


def test_detect_shell_returns_none_for_unrecognized_or_empty() -> None:
    assert shell_completion.detect_shell("/usr/bin/fish") is None
    assert shell_completion.detect_shell(None) is None
    assert shell_completion.detect_shell("") is None
# end def test_detect_shell_returns_none_for_unrecognized_or_empty


def test_write_completion_script_creates_bash_and_zsh_files(tmp_path: Path) -> None:
    bash_target = shell_completion.shell_target("bash", tmp_path)
    zsh_target = shell_completion.shell_target("zsh", tmp_path)

    bash_path = shell_completion.write_completion_script(bash_target)
    zsh_path = shell_completion.write_completion_script(zsh_target)

    assert "_GAME_COLLECTIONS_COMPLETE=complete_bash" in bash_path.read_text(encoding="utf-8")
    assert "game-collections" in bash_path.read_text(encoding="utf-8")
    assert "_GAME_COLLECTIONS_COMPLETE=complete_zsh" in zsh_path.read_text(encoding="utf-8")
    assert "game-collections" in zsh_path.read_text(encoding="utf-8")
# end def test_write_completion_script_creates_bash_and_zsh_files


def test_install_rc_hook_prefers_existing_rc_d_dir(tmp_path: Path) -> None:
    (tmp_path / ".bashrc.d").mkdir()
    target = shell_completion.shell_target("bash", tmp_path)
    shell_completion.write_completion_script(target)

    hooked = shell_completion.install_rc_hook(target)

    assert hooked == target.rc_d_file
    assert target.rc_d_file.is_file()
    assert not target.rc_path.exists()
# end def test_install_rc_hook_prefers_existing_rc_d_dir


def test_install_rc_hook_appends_marked_block_to_bashrc_when_no_rc_d(tmp_path: Path) -> None:
    target = shell_completion.shell_target("bash", tmp_path)
    shell_completion.write_completion_script(target)

    hooked = shell_completion.install_rc_hook(target)

    assert hooked == target.rc_path
    contents = target.rc_path.read_text(encoding="utf-8")
    assert shell_completion.RC_MARKER_START in contents
    assert shell_completion.RC_MARKER_END in contents
    assert str(target.completion_path) in contents
# end def test_install_rc_hook_appends_marked_block_to_bashrc_when_no_rc_d


def test_install_rc_hook_appends_to_missing_rc_file(tmp_path: Path) -> None:
    target = shell_completion.shell_target("zsh", tmp_path)
    shell_completion.write_completion_script(target)
    assert not target.rc_path.exists()

    shell_completion.install_rc_hook(target)

    assert target.rc_path.is_file()
    assert shell_completion.RC_MARKER_START in target.rc_path.read_text(encoding="utf-8")
# end def test_install_rc_hook_appends_to_missing_rc_file


def test_install_rc_hook_is_idempotent_on_second_run(tmp_path: Path) -> None:
    target = shell_completion.shell_target("bash", tmp_path)
    shell_completion.write_completion_script(target)

    shell_completion.install_rc_hook(target)
    first_contents = target.rc_path.read_text(encoding="utf-8")
    shell_completion.install_rc_hook(target)
    second_contents = target.rc_path.read_text(encoding="utf-8")

    assert first_contents == second_contents
    assert second_contents.count(shell_completion.RC_MARKER_START) == 1
# end def test_install_rc_hook_is_idempotent_on_second_run


def test_install_rc_hook_is_idempotent_for_zsh_rc_d(tmp_path: Path) -> None:
    (tmp_path / ".zshrc.d").mkdir()
    target = shell_completion.shell_target("zsh", tmp_path)
    shell_completion.write_completion_script(target)

    shell_completion.install_rc_hook(target)
    first_contents = target.rc_d_file.read_text(encoding="utf-8")
    shell_completion.install_rc_hook(target)
    second_contents = target.rc_d_file.read_text(encoding="utf-8")

    assert first_contents == second_contents
# end def test_install_rc_hook_is_idempotent_for_zsh_rc_d


def test_remove_completion_deletes_script_and_rc_d_file(tmp_path: Path) -> None:
    (tmp_path / ".bashrc.d").mkdir()
    target = shell_completion.shell_target("bash", tmp_path)
    shell_completion.write_completion_script(target)
    shell_completion.install_rc_hook(target)

    changed = shell_completion.remove_completion("bash", tmp_path)

    assert target.completion_path in changed
    assert target.rc_d_file in changed
    assert not target.completion_path.exists()
    assert not target.rc_d_file.exists()
# end def test_remove_completion_deletes_script_and_rc_d_file


def test_remove_completion_strips_marked_block_from_rc_file_preserving_other_content(tmp_path: Path) -> None:
    target = shell_completion.shell_target("bash", tmp_path)
    shell_completion.write_completion_script(target)
    target.rc_path.write_text("export PATH=foo\n", encoding="utf-8")
    shell_completion.install_rc_hook(target)
    target.rc_path.write_text(target.rc_path.read_text(encoding="utf-8") + "export EDITOR=vim\n", encoding="utf-8")

    changed = shell_completion.remove_completion("bash", tmp_path)

    assert target.rc_path in changed
    contents = target.rc_path.read_text(encoding="utf-8")
    assert "export PATH=foo" in contents
    assert "export EDITOR=vim" in contents
    assert shell_completion.RC_MARKER_START not in contents
    assert shell_completion.RC_MARKER_END not in contents
# end def test_remove_completion_strips_marked_block_from_rc_file_preserving_other_content


def test_remove_completion_is_a_noop_when_nothing_was_installed(tmp_path: Path) -> None:
    assert shell_completion.remove_completion("bash", tmp_path) == []
# end def test_remove_completion_is_a_noop_when_nothing_was_installed
