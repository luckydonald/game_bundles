"""Bash/zsh completion script generation and rc-file wiring for `install`/`uninstall`.

Only bash and zsh are supported (macOS's non-bash default shell is zsh; no
other shell is in scope). Detection is by `$SHELL`'s basename only.

The generated scripts reuse Typer/Click's own completion protocol
(`_GAME_COLLECTIONS_COMPLETE=complete_bash`/`complete_zsh`, the same
env-var contract `--show-completion` already emits — not a private
internal) and additionally dispatch `uv run game-collections <TAB>` to
that same completion function, since a plain `complete -F fn
game-collections` registration (what Typer's own `--install-completion`
writes) is only ever consulted by the shell when the command word typed
is literally `game-collections`, never `uv`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Shell = Literal["bash", "zsh"]

CONFIG_DIR_NAME = ".config/game-collections"
RC_MARKER_START = "# game-collections completion (managed by game-collections install)"
RC_MARKER_END = "# end game-collections completion"
PROG_NAME = "game-collections"


def detect_shell(shell_env: str | None) -> Shell | None:
    """Classify `$SHELL`'s basename; anything else is unsupported."""
    if not shell_env:
        return None
    # end if
    name = Path(shell_env).name
    if name in ("bash", "zsh"):
        return name
    # end if
    return None
# end def detect_shell


@dataclass(frozen=True, slots=True)
class ShellTarget:
    shell: Shell
    completion_path: Path
    rc_path: Path
    rc_d_dir: Path
    rc_d_file: Path
# end class ShellTarget


def shell_target(shell: Shell, home: Path) -> ShellTarget:
    config_dir = home / CONFIG_DIR_NAME
    if shell == "bash":
        return ShellTarget(
            shell="bash",
            completion_path=config_dir / "completion.bash",
            rc_path=home / ".bashrc",
            rc_d_dir=home / ".bashrc.d",
            rc_d_file=home / ".bashrc.d" / "50-game-collections-completion.sh",
        )
    # end if
    return ShellTarget(
        shell="zsh",
        completion_path=config_dir / "completion.zsh",
        rc_path=home / ".zshrc",
        rc_d_dir=home / ".zshrc.d",
        rc_d_file=home / ".zshrc.d" / "50-game-collections-completion.sh",
    )
# end def shell_target


def bash_completion_script() -> str:
    return f"""{RC_MARKER_START}
_game_collections_completion() {{
    local IFS=$'\\n'
    COMPREPLY=( $( env COMP_WORDS="${{COMP_WORDS[*]}}" \\
                   COMP_CWORD=$COMP_CWORD \\
                   _GAME_COLLECTIONS_COMPLETE=complete_bash "$1" ) )
    return 0
}}
complete -o default -F _game_collections_completion {PROG_NAME}

# Dispatch completion for `uv run game-collections ...` without breaking
# uv's own completion for `uv sync`, `uv add`, etc. We capture whatever
# function was already bound to `uv` at source time (e.g. from a prior
# `uv generate-shell-completion bash` line sourced earlier in the rc file)
# and delegate to it for every case except `uv run game-collections`.
_game_collections_uv_run_dispatch() {{
    if [[ "${{COMP_WORDS[1]}}" == "run" && "${{COMP_WORDS[2]}}" == "{PROG_NAME}" ]]; then
        local -a COMP_WORDS=("${{COMP_WORDS[@]:2}}")
        local COMP_CWORD=$((COMP_CWORD - 2))
        _game_collections_completion "{PROG_NAME}"
        return 0
    fi
    if declare -F _game_collections_uv_orig_completion >/dev/null; then
        _game_collections_uv_orig_completion "$@"
        return $?
    fi
    return 1
}}

_game_collections_uv_prior="$(complete -p uv 2>/dev/null | sed -n 's/.*-F \\([^ ]*\\) uv$/\\1/p')"
if [[ -n "$_game_collections_uv_prior" && "$_game_collections_uv_prior" != "_game_collections_uv_run_dispatch" ]]; then
    eval "_game_collections_uv_orig_completion() {{ \\"\\$_game_collections_uv_prior\\" \\"\\$@\\"; }}"
fi
unset _game_collections_uv_prior
complete -o default -F _game_collections_uv_run_dispatch uv
{RC_MARKER_END}
"""
# end def bash_completion_script


def zsh_completion_script() -> str:
    return f"""{RC_MARKER_START}
#compdef {PROG_NAME}

_game_collections_completion() {{
  eval $(env _TYPER_COMPLETE_ARGS="${{words[1,$CURRENT]}}" _GAME_COLLECTIONS_COMPLETE=complete_zsh {PROG_NAME})
}}
compdef _game_collections_completion {PROG_NAME}

# Wrap whatever `_uv` completion function already exists at source time so
# `uv sync`/`uv add`/... keep working; only `uv run game-collections ...`
# is intercepted. If `_uv` is still an unautoloaded stub at this point,
# this captures the stub, not the real completer - degrades to `_default`
# for plain `uv` completion in that case, never breaks anything.
if (( ${{+functions[_uv]}} )); then
  functions[_game_collections_uv_orig]=$functions[_uv]
fi

_game_collections_uv_dispatch() {{
  if [[ "${{words[2]}}" == "run" && "${{words[3]}}" == "{PROG_NAME}" ]]; then
    local -a words
    words=("${{words[@]:2}}")
    local CURRENT=$((CURRENT - 2))
    _game_collections_completion
    return
  fi
  if (( ${{+functions[_game_collections_uv_orig]}} )); then
    _game_collections_uv_orig "$@"
    return
  fi
  _default
}}
compdef _game_collections_uv_dispatch uv
{RC_MARKER_END}
"""
# end def zsh_completion_script


def write_completion_script(target: ShellTarget) -> Path:
    """Write the generated script, creating parent dirs as needed."""
    target.completion_path.parent.mkdir(parents=True, exist_ok=True)
    script = bash_completion_script() if target.shell == "bash" else zsh_completion_script()
    target.completion_path.write_text(script, encoding="utf-8")
    return target.completion_path
# end def write_completion_script


def install_rc_hook(target: ShellTarget) -> Path:
    """Idempotently wire `source <completion_path>` into the shell's rc setup.

    Prefers a conventional `~/.bashrc.d/`/`~/.zshrc.d/` directory if it
    already exists (never created by us - only used if the user's own
    dotfile framework already has one), else appends a marked block to the
    rc file itself, guarded by RC_MARKER_START so re-running `install`
    never duplicates it.
    """
    if target.rc_d_dir.is_dir():
        target.rc_d_file.write_text(f'source "{target.completion_path}"\n', encoding="utf-8")
        return target.rc_d_file
    # end if
    existing = target.rc_path.read_text(encoding="utf-8") if target.rc_path.is_file() else ""
    if RC_MARKER_START in existing:
        return target.rc_path
    # end if
    block = f'{RC_MARKER_START}\nsource "{target.completion_path}"\n{RC_MARKER_END}\n'
    separator = "" if not existing or existing.endswith("\n") else "\n"
    target.rc_path.write_text(existing + separator + block, encoding="utf-8")
    return target.rc_path
# end def install_rc_hook


def remove_completion(shell: Shell, home: Path) -> list[Path]:
    """Undo `write_completion_script` + `install_rc_hook`.

    Returns the paths actually removed/modified (empty if nothing was
    installed - a safe no-op, not an error).
    """
    target = shell_target(shell, home)
    changed: list[Path] = []
    if target.completion_path.is_file():
        target.completion_path.unlink()
        changed.append(target.completion_path)
    # end if
    if target.rc_d_file.is_file():
        target.rc_d_file.unlink()
        changed.append(target.rc_d_file)
    # end if
    if target.rc_path.is_file():
        text = target.rc_path.read_text(encoding="utf-8")
        if RC_MARKER_START in text:
            lines = text.splitlines(keepends=True)
            kept: list[str] = []
            skipping = False
            for line in lines:
                if line.strip() == RC_MARKER_START:
                    skipping = True
                    continue
                # end if
                if skipping and line.strip() == RC_MARKER_END:
                    skipping = False
                    continue
                # end if
                if skipping:
                    continue
                # end if
                kept.append(line)
            # end for
            target.rc_path.write_text("".join(kept), encoding="utf-8")
            changed.append(target.rc_path)
        # end if
    # end if
    return changed
# end def remove_completion
