"""Abstract base class defining the contract for platform-specific OS operations.

Every target OS (Windows, Linux, macOS) must provide a concrete subclass of
``PlatformInterface``.  The factory function ``create_platform()`` auto-detects
the running OS and returns the appropriate implementation.
"""

from __future__ import annotations

import platform as _platform_mod
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class WindowInfo:
    """Information about an OS window.

    Attributes:
        title: The window title text.
        x: Horizontal position of the top-left corner (logical px).
        y: Vertical position of the top-left corner (logical px).
        width: Window width in logical pixels.
        height: Window height in logical pixels.
        is_active: Whether this window currently has focus.
        process_name: Name of the owning process (empty if unknown).
    """

    title: str
    x: int
    y: int
    width: int
    height: int
    is_active: bool = False
    process_name: str = ""


class PlatformInterface(ABC):
    """Abstract interface for platform-specific OS operations.

    Each target OS (Windows, Linux, macOS) provides a concrete
    implementation.  All coordinates are in logical screen space
    (DPI-normalized).
    """

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    @abstractmethod
    def capture_frame(self) -> NDArray[np.uint8]:
        """Capture the current screen as a numpy array.

        Returns:
            A numpy array of shape ``(H, W, C)`` in BGR colour order
            with dtype ``uint8``.
        """

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    @abstractmethod
    def get_cursor_pos(self) -> tuple[int, int]:
        """Get the current cursor position.

        Returns:
            A ``(x, y)`` tuple in logical coordinates.
        """

    @abstractmethod
    def move_cursor(self, x: int, y: int) -> None:
        """Move the cursor to the given logical coordinates.

        Args:
            x: Target horizontal position.
            y: Target vertical position.
        """

    # ------------------------------------------------------------------
    # Mouse actions
    # ------------------------------------------------------------------

    @abstractmethod
    def click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Click at the given coordinates.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.
        """

    @abstractmethod
    def double_click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Double-click at the given coordinates.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.
        """

    @abstractmethod
    def scroll(self, x: int, y: int, amount: int) -> None:
        """Scroll at the given position.

        Args:
            x: Horizontal position of the cursor during scroll.
            y: Vertical position of the cursor during scroll.
            amount: Scroll offset. Positive scrolls up, negative
                scrolls down.
        """

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    @abstractmethod
    def type_text(self, text: str) -> None:
        """Type the given text string using keyboard input.

        Args:
            text: The string to type. Special characters are sent
                as-is; use ``key_press`` for modifier combos.
        """

    @abstractmethod
    def key_press(self, key: str) -> None:
        """Press a keyboard key or key combination.

        Supports modifier combos expressed with ``+``, for example
        ``'ctrl+c'``, ``'alt+tab'``, ``'shift+a'``.

        Args:
            key: Key name or combo string.
        """

    # ------------------------------------------------------------------
    # Screen & window queries
    # ------------------------------------------------------------------

    @abstractmethod
    def get_screen_size(self) -> tuple[int, int]:
        """Get screen dimensions in logical coordinates.

        Returns:
            A ``(width, height)`` tuple.
        """

    @abstractmethod
    def get_active_window(self) -> WindowInfo:
        """Get information about the currently focused window.

        Returns:
            A ``WindowInfo`` describing the active window.
        """

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """List all visible windows.

        Returns:
            A list of ``WindowInfo`` objects, one per visible window.
        """

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_platform_name(self) -> str:
        """Return the platform name.

        Override in subclasses to return ``'windows'``, ``'linux'``,
        or ``'macos'``.

        Returns:
            A lowercase platform identifier string.
        """
        return "unknown"


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def create_platform() -> PlatformInterface:
    """Auto-detect the current OS and return the appropriate implementation.

    The concrete platform modules are imported lazily so that
    OS-specific dependencies are only required on the matching OS.

    Returns:
        A ``PlatformInterface`` instance for the running OS.

    Raises:
        NotImplementedError: If the current OS is not supported.
    """
    system = _platform_mod.system()

    if system == "Windows":
        from ciu_agent.platform.windows import WindowsPlatform

        return WindowsPlatform()

    if system == "Linux":
        from ciu_agent.platform.linux import LinuxPlatform

        return LinuxPlatform()

    if system == "Darwin":
        from ciu_agent.platform.macos import MacOSPlatform

        return MacOSPlatform()

    raise NotImplementedError(
        f"Unsupported operating system: {system!r}"
    )
