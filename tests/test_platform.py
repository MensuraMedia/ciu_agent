"""Unit tests for the CIU Agent platform layer.

Tests cover:
- WindowInfo dataclass construction and defaults
- PlatformInterface abstract base class enforcement
- create_platform() factory function
- WindowsPlatform live system calls (Windows-only)
- LinuxPlatform and MacOSPlatform stubs
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from ciu_agent.platform.interface import (
    PlatformInterface,
    WindowInfo,
    create_platform,
)
from ciu_agent.platform.linux import LinuxPlatform
from ciu_agent.platform.macos import MacOSPlatform

IS_WINDOWS = sys.platform == "win32"


# ==================================================================
# Interface tests
# ==================================================================


class TestWindowInfo:
    """Tests for the WindowInfo dataclass."""

    def test_construction_with_all_fields_stores_values(self) -> None:
        """WindowInfo stores all explicitly provided fields."""
        info = WindowInfo(
            title="My Window",
            x=10,
            y=20,
            width=800,
            height=600,
            is_active=True,
            process_name="app.exe",
        )
        assert info.title == "My Window"
        assert info.x == 10
        assert info.y == 20
        assert info.width == 800
        assert info.height == 600
        assert info.is_active is True
        assert info.process_name == "app.exe"

    def test_construction_with_defaults_sets_inactive_and_empty_process(
        self,
    ) -> None:
        """WindowInfo defaults is_active to False and process_name to ''."""
        info = WindowInfo(
            title="Test",
            x=0,
            y=0,
            width=100,
            height=100,
        )
        assert info.is_active is False
        assert info.process_name == ""


class TestPlatformInterface:
    """Tests for PlatformInterface ABC and factory."""

    def test_instantiation_directly_raises_typeerror(self) -> None:
        """PlatformInterface cannot be instantiated (abstract)."""
        with pytest.raises(TypeError):
            PlatformInterface()  # type: ignore[abstract]

    @pytest.mark.skipif(
        not IS_WINDOWS,
        reason="Factory returns WindowsPlatform only on Windows",
    )
    def test_create_platform_on_windows_returns_windows_platform(
        self,
    ) -> None:
        """create_platform() returns a WindowsPlatform on Windows."""
        from ciu_agent.platform.windows import WindowsPlatform

        plat = create_platform()
        try:
            assert isinstance(plat, WindowsPlatform)
        finally:
            plat.close()  # type: ignore[attr-defined]

    def test_create_platform_returns_object_with_get_platform_name(
        self,
    ) -> None:
        """create_platform() result has a callable get_platform_name()."""
        plat = create_platform()
        try:
            name = plat.get_platform_name()
            assert isinstance(name, str)
            assert len(name) > 0
        finally:
            if hasattr(plat, "close"):
                plat.close()  # type: ignore[attr-defined]


# ==================================================================
# Windows platform tests (live system calls)
# ==================================================================


@pytest.fixture()
def win_platform() -> "WindowsPlatform":  # type: ignore[name-defined]  # noqa: F821
    """Create and tear down a WindowsPlatform instance.

    Yields:
        A live WindowsPlatform connected to the real desktop.
    """
    from ciu_agent.platform.windows import WindowsPlatform

    plat = WindowsPlatform()
    yield plat
    plat.close()


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows only")
class TestWindowsPlatform:
    """Live tests for WindowsPlatform on a real Windows desktop."""

    def test_get_platform_name_returns_windows(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """get_platform_name() returns 'windows'."""
        assert win_platform.get_platform_name() == "windows"

    def test_get_screen_size_returns_two_positive_ints(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """get_screen_size() returns (width, height) of positive ints."""
        size = win_platform.get_screen_size()
        assert isinstance(size, tuple)
        assert len(size) == 2
        w, h = size
        assert isinstance(w, int) and w > 0
        assert isinstance(h, int) and h > 0

    def test_get_cursor_pos_returns_two_ints(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """get_cursor_pos() returns a (x, y) tuple of ints."""
        pos = win_platform.get_cursor_pos()
        assert isinstance(pos, tuple)
        assert len(pos) == 2
        x, y = pos
        assert isinstance(x, int)
        assert isinstance(y, int)

    def test_capture_frame_returns_bgr_uint8_array(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """capture_frame() returns (H, W, 3) uint8 numpy array."""
        frame = win_platform.capture_frame()
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.uint8
        assert frame.ndim == 3
        h, w, c = frame.shape
        assert h > 0
        assert w > 0
        assert c == 3

    def test_get_active_window_returns_windowinfo_with_title(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """get_active_window() returns WindowInfo with non-empty title."""
        info = win_platform.get_active_window()
        assert isinstance(info, WindowInfo)
        # There should always be a foreground window on a desktop
        assert isinstance(info.title, str)
        assert len(info.title) > 0

    def test_list_windows_returns_list_of_windowinfo(
        self,
        win_platform: "WindowsPlatform",  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        """list_windows() returns a non-empty list of WindowInfo."""
        windows = win_platform.list_windows()
        assert isinstance(windows, list)
        assert len(windows) > 0
        for w in windows:
            assert isinstance(w, WindowInfo)


# ==================================================================
# Stub tests -- Linux
# ==================================================================


class TestLinuxPlatformStub:
    """Tests for the LinuxPlatform stub implementation."""

    def test_get_platform_name_returns_linux(self) -> None:
        """LinuxPlatform.get_platform_name() returns 'linux'."""
        plat = LinuxPlatform()
        assert plat.get_platform_name() == "linux"

    def test_capture_frame_raises_not_implemented(self) -> None:
        """LinuxPlatform.capture_frame() raises NotImplementedError."""
        plat = LinuxPlatform()
        with pytest.raises(NotImplementedError):
            plat.capture_frame()


# ==================================================================
# Stub tests -- macOS
# ==================================================================


class TestMacOSPlatformStub:
    """Tests for the MacOSPlatform stub implementation."""

    def test_get_platform_name_returns_macos(self) -> None:
        """MacOSPlatform.get_platform_name() returns 'macos'."""
        plat = MacOSPlatform()
        assert plat.get_platform_name() == "macos"

    def test_capture_frame_raises_not_implemented(self) -> None:
        """MacOSPlatform.capture_frame() raises NotImplementedError."""
        plat = MacOSPlatform()
        with pytest.raises(NotImplementedError):
            plat.capture_frame()
