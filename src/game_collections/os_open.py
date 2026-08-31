"""Hand a URL or custom URI scheme off to the OS's own handler."""

from __future__ import annotations

import os
import subprocess
import sys


def open_url(url: str) -> None:
    """Open `url` (or a custom URI scheme like ``steam://...``) in the OS's default handler."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
    elif sys.platform.startswith("win"):
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", url])
    # end if
# end def open_url
