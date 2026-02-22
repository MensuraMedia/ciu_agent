"""Windows implementation of ``PlatformInterface``.

Uses:
- ``mss`` for fast screen capture (shared-memory, no GDI overhead).
- ``ctypes`` + Windows API for cursor, screen metrics, and window queries.
- ``pynput`` for input injection (mouse clicks, keyboard typing).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

import mss
import numpy as np
from numpy.typing import NDArray
from pynput.keyboard import Controller as KbdController
from pynput.keyboard import Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

from ciu_agent.platform.interface import PlatformInterface, WindowInfo

logger = logging.getLogger(__name__)

# -- Windows API constants -----------------------------------------
SM_CXSCREEN = 0
SM_CYSCREEN = 1

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# DPI awareness constants (Windows 8.1+)
PROCESS_PER_MONITOR_DPI_AWARE = 2

# mouse_event flags (used only as fallback reference)
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# -- ctypes structures ---------------------------------------------


class _POINT(ctypes.Structure):
    """Win32 POINT structure."""

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    """Win32 RECT structure."""

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


# -- Helpers -------------------------------------------------------

# Type alias for EnumWindows callback
_EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPARAM,
)

_BUTTON_MAP: dict[str, Button] = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
}

_KEY_MAP: dict[str, Key] = {
    "alt": Key.alt,
    "alt_l": Key.alt_l,
    "alt_r": Key.alt_r,
    "backspace": Key.backspace,
    "caps_lock": Key.caps_lock,
    "cmd": Key.cmd,
    "ctrl": Key.ctrl,
    "ctrl_l": Key.ctrl_l,
    "ctrl_r": Key.ctrl_r,
    "delete": Key.delete,
    "down": Key.down,
    "end": Key.end,
    "enter": Key.enter,
    "return": Key.enter,
    "esc": Key.esc,
    "escape": Key.esc,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
    "home": Key.home,
    "insert": Key.insert,
    "left": Key.left,
    "menu": Key.menu,
    "num_lock": Key.num_lock,
    "page_down": Key.page_down,
    "page_up": Key.page_up,
    "pause": Key.pause,
    "print_screen": Key.print_screen,
    "right": Key.right,
    "scroll_lock": Key.scroll_lock,
    "shift": Key.shift,
    "shift_l": Key.shift_l,
    "shift_r": Key.shift_r,
    "space": Key.space,
    "tab": Key.tab,
    "up": Key.up,
    "win": Key.cmd,
    "windows": Key.cmd,
    "super": Key.cmd,
}


def _resolve_key(name: str) -> Key | str:
    """Resolve a key name to a ``pynput.keyboard.Key`` or a character.

    Args:
        name: Lowercase key name (e.g. ``'ctrl'``, ``'a'``).

    Returns:
        A ``Key`` enum member for special keys, or the character itself
        for single-character names.
    """
    normalised = name.strip().lower()
    if normalised in _KEY_MAP:
        return _KEY_MAP[normalised]
    # Single character — return as-is for pynput
    if len(normalised) == 1:
        return normalised
    raise ValueError(f"Unknown key name: {name!r}")


def _enable_dpi_awareness() -> None:
    """Set process-level DPI awareness so coordinates are physical pixels.

    Falls back silently on older Windows versions that lack the API.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(  # type: ignore[attr-defined]
            PROCESS_PER_MONITOR_DPI_AWARE,
        )
        logger.debug("DPI awareness set to per-monitor.")
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            logger.debug(
                "Fell back to SetProcessDPIAware (system-level)."
            )
        except (AttributeError, OSError):
            logger.warning("Could not set DPI awareness.")


def _get_process_name(hwnd: int) -> str:
    """Attempt to retrieve the process executable name for a window.

    Args:
        hwnd: Window handle.

    Returns:
        The process executable name (e.g. ``'explorer.exe'``) or
        an empty string if retrieval fails.
    """
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(
        hwnd, ctypes.byref(pid)
    )
    if pid.value == 0:
        return ""
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.wintypes.DWORD(260)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        if ok and buf.value:
            # Return just the filename, not the full path
            return buf.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


# -- WindowsPlatform -----------------------------------------------


class WindowsPlatform(PlatformInterface):
    """Windows-specific implementation of :class:`PlatformInterface`.

    Initialises ``mss`` for screen capture, ``pynput`` controllers for
    input injection, and sets DPI awareness so all coordinates are in
    physical (unscaled) pixels.
    """

    def __init__(self) -> None:
        _enable_dpi_awareness()
        self._sct = mss.mss()
        self._mouse = MouseController()
        self._kbd = KbdController()
        logger.info("WindowsPlatform initialised.")

    # -- cleanup ---------------------------------------------------

    def close(self) -> None:
        """Release the mss screen-capture context."""
        self._sct.close()
        logger.info("WindowsPlatform closed.")

    # -- Screen capture --------------------------------------------

    def capture_frame(self) -> NDArray[np.uint8]:
        """Capture the primary monitor as a BGR numpy array.

        Uses ``mss`` which accesses the framebuffer via the Windows
        Desktop Duplication API — significantly faster than GDI-based
        alternatives.

        Returns:
            A numpy array of shape ``(H, W, 3)`` in BGR colour order
            with dtype ``uint8``.
        """
        monitor = self._sct.monitors[1]  # primary monitor
        shot = self._sct.grab(monitor)
        # mss returns BGRA; drop alpha channel for BGR
        frame: NDArray[np.uint8] = np.array(shot, dtype=np.uint8)[
            :, :, :3
        ]
        return frame

    # -- Cursor ----------------------------------------------------

    def get_cursor_pos(self) -> tuple[int, int]:
        """Get the current cursor position via the Windows API.

        Returns:
            A ``(x, y)`` tuple of the cursor position in physical
            screen coordinates.
        """
        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)

    def move_cursor(self, x: int, y: int) -> None:
        """Move the cursor to the specified screen coordinates.

        Args:
            x: Target horizontal position.
            y: Target vertical position.
        """
        ctypes.windll.user32.SetCursorPos(x, y)

    # -- Mouse actions ---------------------------------------------

    def click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Single-click at the given coordinates.

        Moves the cursor to ``(x, y)`` then performs a click with the
        specified button using ``pynput``.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.

        Raises:
            ValueError: If *button* is not a recognised name.
        """
        btn = _BUTTON_MAP.get(button.lower())
        if btn is None:
            raise ValueError(
                f"Unknown mouse button: {button!r}. "
                f"Expected one of {list(_BUTTON_MAP)}"
            )
        self._mouse.position = (x, y)
        self._mouse.click(btn, 1)

    def double_click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Double-click at the given coordinates.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.

        Raises:
            ValueError: If *button* is not a recognised name.
        """
        btn = _BUTTON_MAP.get(button.lower())
        if btn is None:
            raise ValueError(
                f"Unknown mouse button: {button!r}. "
                f"Expected one of {list(_BUTTON_MAP)}"
            )
        self._mouse.position = (x, y)
        self._mouse.click(btn, 2)

    def scroll(self, x: int, y: int, amount: int) -> None:
        """Scroll the mouse wheel at the given position.

        Args:
            x: Horizontal cursor position during scroll.
            y: Vertical cursor position during scroll.
            amount: Number of scroll increments. Positive scrolls up,
                negative scrolls down.
        """
        self._mouse.position = (x, y)
        self._mouse.scroll(0, amount)

    # -- Keyboard --------------------------------------------------

    def type_text(self, text: str) -> None:
        """Type a text string via simulated keyboard input.

        Each character is sent as an individual keystroke. For modifier
        combinations (e.g. Ctrl+C) use :meth:`key_press` instead.

        Args:
            text: The string to type.
        """
        self._kbd.type(text)

    def key_press(self, key: str) -> None:
        """Press a key or key combination.

        Modifier combos are expressed with ``+`` separators, for
        example ``'ctrl+c'``, ``'alt+tab'``, ``'ctrl+shift+s'``.
        Single keys like ``'enter'`` or ``'f5'`` are also accepted.

        The method holds all modifier keys, taps the final key, then
        releases modifiers in reverse order.

        Args:
            key: Key name or combo string (case-insensitive).

        Raises:
            ValueError: If any part of the combo is an unrecognised
                key name.
        """
        parts = [p.strip() for p in key.split("+")]
        resolved = [_resolve_key(p) for p in parts]

        if len(resolved) == 1:
            # Single key — simple tap
            self._kbd.press(resolved[0])
            self._kbd.release(resolved[0])
            return

        # Multiple keys — hold modifiers, tap final, release
        modifiers = resolved[:-1]
        final = resolved[-1]
        for mod in modifiers:
            self._kbd.press(mod)
        self._kbd.press(final)
        self._kbd.release(final)
        for mod in reversed(modifiers):
            self._kbd.release(mod)

    # -- Screen & window queries ----------------------------------

    def get_screen_size(self) -> tuple[int, int]:
        """Get the primary screen dimensions.

        Returns:
            A ``(width, height)`` tuple in physical pixels.
        """
        w = ctypes.windll.user32.GetSystemMetrics(SM_CXSCREEN)
        h = ctypes.windll.user32.GetSystemMetrics(SM_CYSCREEN)
        return (w, h)

    def get_active_window(self) -> WindowInfo:
        """Get information about the currently focused (foreground) window.

        Returns:
            A ``WindowInfo`` describing the foreground window. If no
            window is focused, fields default to empty / zero values.
        """
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo(
                title="",
                x=0,
                y=0,
                width=0,
                height=0,
                is_active=True,
            )
        title_buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(
            hwnd, title_buf, 256
        )
        rect = _RECT()
        ctypes.windll.user32.GetWindowRect(
            hwnd, ctypes.byref(rect)
        )
        return WindowInfo(
            title=title_buf.value,
            x=rect.left,
            y=rect.top,
            width=rect.right - rect.left,
            height=rect.bottom - rect.top,
            is_active=True,
            process_name=_get_process_name(hwnd),
        )

    def list_windows(self) -> list[WindowInfo]:
        """Enumerate all visible windows with non-empty titles.

        Uses the Win32 ``EnumWindows`` callback to iterate over
        top-level windows. Only windows that are visible and have
        a non-empty title are included.

        Returns:
            A list of ``WindowInfo`` objects sorted by window title.
        """
        results: list[WindowInfo] = []
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()

        def _callback(
            hwnd: int, _lparam: int
        ) -> bool:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True  # continue enumeration

            title_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(
                hwnd, title_buf, 256
            )
            title = title_buf.value
            if not title:
                return True  # skip untitled windows

            rect = _RECT()
            ctypes.windll.user32.GetWindowRect(
                hwnd, ctypes.byref(rect)
            )
            results.append(
                WindowInfo(
                    title=title,
                    x=rect.left,
                    y=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                    is_active=(hwnd == fg_hwnd),
                    process_name=_get_process_name(hwnd),
                )
            )
            return True  # continue enumeration

        proc = _EnumWindowsProc(_callback)
        ctypes.windll.user32.EnumWindows(proc, 0)
        results.sort(key=lambda w: w.title.lower())
        return results

    # -- Metadata --------------------------------------------------

    def get_platform_name(self) -> str:
        """Return the platform identifier.

        Returns:
            The string ``'windows'``.
        """
        return "windows"
