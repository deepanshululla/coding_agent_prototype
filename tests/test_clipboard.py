"""Unit tests for the OS clipboard image reader (Ctrl+V image paste).

A terminal never sends image bytes on Ctrl+V — the key is only a trigger, and
the image is pulled from the OS clipboard via a platform command. These tests
mock the subprocess boundary so no real clipboard is touched:

  - macOS: osascript writes the clipboard PNG to a temp file we then read.
  - empty clipboard: osascript exits non-zero → None.
  - Linux: wl-paste / xclip emit PNG bytes on stdout.
  - unsupported platform → None.
  - to_data_url builds a base64 data: URL.
"""

import base64
import re

from tui import clipboard


def test_to_data_url_builds_base64_data_url():
    url = clipboard.to_data_url(b"PNG", "image/png")
    assert url == "data:image/png;base64," + base64.b64encode(b"PNG").decode("ascii")


def test_to_data_url_defaults_to_png():
    assert clipboard.to_data_url(b"x").startswith("data:image/png;base64,")


def test_read_macos_success(monkeypatch):
    """On darwin, osascript writes the clipboard PNG to a temp file; we read it."""
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")
    png = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    def fake_run(cmd, *args, **kwargs):
        # The AppleScript carries the destination path; emulate osascript by
        # writing the PNG bytes there, then report success.
        script = " ".join(cmd)
        m = re.search(r'POSIX file "([^"]+)"', script)
        assert m is not None
        path = m.group(1)
        with open(path, "wb") as fh:
            fh.write(png)
        return clipboard.subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    result = clipboard.read_clipboard_image()
    assert result == (png, "image/png")


def test_read_macos_empty_clipboard_returns_none(monkeypatch):
    """osascript exits non-zero when the clipboard holds no image → None."""
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")

    def fake_run(cmd, *args, **kwargs):
        return clipboard.subprocess.CompletedProcess(cmd, 1, b"", b"error")

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    assert clipboard.read_clipboard_image() is None


def test_read_linux_wl_paste(monkeypatch):
    """On linux, a present wl-paste emits PNG bytes on stdout."""
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(
        clipboard.shutil,
        "which",
        lambda name: "/usr/bin/wl-paste" if name == "wl-paste" else None,
    )
    png = b"\x89PNGlinux"

    def fake_run(cmd, *args, **kwargs):
        assert cmd[0] == "wl-paste"
        return clipboard.subprocess.CompletedProcess(cmd, 0, png, b"")

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)

    assert clipboard.read_clipboard_image() == (png, "image/png")


def test_read_linux_no_tool_returns_none(monkeypatch):
    """No wl-paste/xclip on PATH → None (feature degrades to a no-op)."""
    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    assert clipboard.read_clipboard_image() is None


def test_unsupported_platform_returns_none(monkeypatch):
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    assert clipboard.read_clipboard_image() is None


def test_never_raises_on_subprocess_error(monkeypatch):
    """A blowing-up subprocess yields None, never an exception, so the TUI keeps running."""
    monkeypatch.setattr(clipboard.sys, "platform", "darwin")

    def boom(cmd, *args, **kwargs):
        raise OSError("osascript not found")

    monkeypatch.setattr(clipboard.subprocess, "run", boom)
    assert clipboard.read_clipboard_image() is None
