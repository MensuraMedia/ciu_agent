"""macOS platform implementation using Quartz and CGEvent.

Status: Stub -- not yet implemented. All methods raise NotImplementedError.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ciu_agent.platform.interface import PlatformInterface, WindowInfo


class MacOSPlatform(PlatformInterface):
    """macOS implementation of the platform interface.

    Will use:
    - CGWindowListCreateImage for screen capture
    - CGEventGetLocation for cursor position
    - CGEventPost for input injection
    """

    # --------------------------------------------------------------
    # Screen capture
    # --------------------------------------------------------------

    def capture_frame(self) -> NDArray[np.uint8]:
        """Capture the current screen as a numpy array.

        Returns:
            A numpy array of shape ``(H, W, C)`` in BGR colour order
            with dtype ``uint8``.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.capture_frame() not yet implemented"
        )

    # --------------------------------------------------------------
    # Cursor
    # --------------------------------------------------------------

    def get_cursor_pos(self) -> tuple[int, int]:
        """Get the current cursor position.

        Returns:
            A ``(x, y)`` tuple in logical coordinates.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.get_cursor_pos() not yet implemented"
        )

    def move_cursor(self, x: int, y: int) -> None:
        """Move the cursor to the given logical coordinates.

        Args:
            x: Target horizontal position.
            y: Target vertical position.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.move_cursor() not yet implemented"
        )

    # --------------------------------------------------------------
    # Mouse actions
    # --------------------------------------------------------------

    def click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Click at the given coordinates.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.click() not yet implemented"
        )

    def double_click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        """Double-click at the given coordinates.

        Args:
            x: Horizontal position.
            y: Vertical position.
            button: One of ``'left'``, ``'right'``, or ``'middle'``.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.double_click() not yet implemented"
        )

    def scroll(self, x: int, y: int, amount: int) -> None:
        """Scroll at the given position.

        Args:
            x: Horizontal position of the cursor during scroll.
            y: Vertical position of the cursor during scroll.
            amount: Scroll offset. Positive scrolls up, negative
                scrolls down.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.scroll() not yet implemented"
        )

    # --------------------------------------------------------------
    # Keyboard
    # --------------------------------------------------------------

    def type_text(self, text: str) -> None:
        """Type the given text string using keyboard input.

        Args:
            text: The string to type. Special characters are sent
                as-is; use ``key_press`` for modifier combos.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.type_text() not yet implemented"
        )

    def key_press(self, key: str) -> None:
        """Press a keyboard key or key combination.

        Supports modifier combos expressed with ``+``, for example
        ``'ctrl+c'``, ``'alt+tab'``, ``'shift+a'``.

        Args:
            key: Key name or combo string.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.key_press() not yet implemented"
        )

    # --------------------------------------------------------------
    # Screen & window queries
    # --------------------------------------------------------------

    def get_screen_size(self) -> tuple[int, int]:
        """Get screen dimensions in logical coordinates.

        Returns:
            A ``(width, height)`` tuple.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.get_screen_size() not yet implemented"
        )

    def get_active_window(self) -> WindowInfo:
        """Get information about the currently focused window.

        Returns:
            A ``WindowInfo`` describing the active window.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.get_active_window() not yet implemented"
        )

    def list_windows(self) -> list[WindowInfo]:
        """List all visible windows.

        Returns:
            A list of ``WindowInfo`` objects, one per visible window.

        Raises:
            NotImplementedError: Always (stub).
        """
        raise NotImplementedError(
            "MacOSPlatform.list_windows() not yet implemented"
        )

    # --------------------------------------------------------------
    # Metadata
    # --------------------------------------------------------------

    def get_platform_name(self) -> str:
        """Return the platform name.

        Returns:
            The string ``'macos'``.
        """
        return "macos"
