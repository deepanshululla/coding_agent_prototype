# src/tui/clipboard.py

"""Read an image off the OS clipboard for Ctrl+V paste in the TUI.

A terminal never transmits image bytes when the user presses Ctrl+V — only text
flows through the PTY. So Ctrl+V is just a *trigger*: on that keypress we shell
out to a platform command that reads the *current clipboard image* and hands
back its bytes. Text on the clipboard is left to Textual's normal paste path.

read_clipboard_image() returns (png_bytes, mime) or None. It never raises — a
missing tool, an empty clipboard, or any subprocess error all yield None, so the
caller can degrade to a no-op (with a status hint) instead of crashing the app.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile


def to_data_url(data: bytes, mime: str = "image/png") -> str:
    """Encode raw image bytes as a base64 data: URL for a multimodal message."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def read_clipboard_image() -> tuple[bytes, str] | None:
    """Return (image_bytes, mime) from the OS clipboard, or None if there is none.

    Dispatches by platform. Any failure — unsupported OS, missing CLI tool, empty
    clipboard, subprocess error — collapses to None so the TUI never crashes on a
    stray Ctrl+V.
    """
    try:
        if sys.platform == "darwin":
            return _read_macos()
        if sys.platform.startswith("linux"):
            return _read_linux()
    except Exception:
        # Defensive: never let a clipboard read take down the TUI.
        return None
    return None


def _read_macos() -> tuple[bytes, str] | None:
    """macOS: ask osascript to write the clipboard PNG to a temp file, then read it.

    `pngpaste` is not assumed to be installed, so we go through AppleScript with
    no third-party dependency. `the clipboard as «class PNGf»` raises when the
    clipboard holds no image, which surfaces as a non-zero exit — we map that to
    None. The temp file is always cleaned up.
    """
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        script = (
            f'set theFile to (open for access POSIX file "{path}" with write permission)\n'
            "try\n"
            "    write (the clipboard as «class PNGf») to theFile\n"
            "    close access theFile\n"
            "on error errMsg\n"
            "    close access theFile\n"
            "    error errMsg\n"
            "end try"
        )
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return None
        with open(path, "rb") as fh:
            data = fh.read()
        return (data, "image/png") if data else None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _read_linux() -> tuple[bytes, str] | None:
    """Linux: prefer wl-paste (Wayland), then xclip (X11); emit PNG bytes on stdout."""
    if shutil.which("wl-paste"):
        proc = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return (proc.stdout, "image/png")
        return None
    if shutil.which("xclip"):
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return (proc.stdout, "image/png")
        return None
    return None
