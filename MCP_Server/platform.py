"""Platform detection and path resolution for Ableton Live.

This module provides utilities for detecting the current platform and resolving
platform-specific paths for Ableton Live's Remote Scripts folder and Preferences.cfg file.
"""

from __future__ import annotations

import sys
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class Platform(Enum):
    """Supported platforms for Ableton MCP."""

    MACOS = "darwin"
    WINDOWS = "win32"


class UnsupportedPlatformError(Exception):
    """Raised when running on an unsupported platform."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        super().__init__(
            f"Unsupported platform: {platform!r}. "
            f"Only macOS (darwin) and Windows (win32) are supported."
        )


class AbletonNotFoundError(Exception):
    """Raised when Ableton Live installation cannot be found."""

    pass


@lru_cache(maxsize=1)
def get_platform() -> Platform:
    """Detect and return the current platform.

    Returns:
        Platform: The detected platform enum value.

    Raises:
        UnsupportedPlatformError: If the platform is not macOS or Windows.
    """
    platform_str = sys.platform
    for platform in Platform:
        if platform.value == platform_str:
            return platform
    raise UnsupportedPlatformError(platform_str)


class AbletonPaths:
    """Platform-specific path resolution for Ableton Live.

    This class provides methods to locate Ableton Live's installation paths,
    including the Remote Scripts folder and Preferences.cfg file.

    Attributes:
        platform: The detected platform.
    """

    def __init__(self, platform: Platform | None = None) -> None:
        """Initialize AbletonPaths with the specified or detected platform.

        Args:
            platform: The platform to use. If None, auto-detects.

        Raises:
            UnsupportedPlatformError: If platform detection fails.
        """
        self.platform = platform if platform is not None else get_platform()

    @property
    def user_library_base(self) -> Path:
        """Get the base path for Ableton's User Library.

        Returns:
            Path to the User Library folder (parent of Remote Scripts).

        Raises:
            UnsupportedPlatformError: If platform is not supported.
        """
        if self.platform == Platform.MACOS:
            return Path.home() / "Music" / "Ableton" / "User Library"
        elif self.platform == Platform.WINDOWS:
            return Path.home() / "Documents" / "Ableton" / "User Library"
        # This should never happen due to enum validation, but satisfies type checker
        raise UnsupportedPlatformError(self.platform.value)

    @property
    def remote_scripts_dir(self) -> Path:
        """Get the path to the Remote Scripts folder.

        This is where Ableton looks for user-installed control surface scripts.

        Returns:
            Path to ~/Music/Ableton/User Library/Remote Scripts/ (macOS)
            or %USERPROFILE%\\Documents\\Ableton\\User Library\\Remote Scripts\\ (Windows).
        """
        return self.user_library_base / "Remote Scripts"

    @property
    def preferences_base(self) -> Path:
        """Get the base path for Ableton's preferences folder.

        Returns:
            Path to the preferences folder containing Live version subfolders.
        """
        if self.platform == Platform.MACOS:
            return Path.home() / "Library" / "Preferences" / "Ableton"
        elif self.platform == Platform.WINDOWS:
            # %APPDATA% expands to C:\Users\<user>\AppData\Roaming
            appdata = Path.home() / "AppData" / "Roaming"
            return appdata / "Ableton"
        raise UnsupportedPlatformError(self.platform.value)

    def _iter_live_versions(self) -> Iterator[tuple[Path, str]]:
        """Iterate over installed Live version directories.

        Yields:
            Tuples of (version_dir_path, version_name) for each found version.
        """
        prefs_base = self.preferences_base
        if not prefs_base.exists():
            return

        for entry in prefs_base.iterdir():
            if entry.is_dir() and entry.name.startswith("Live "):
                yield entry, entry.name

    def find_live_versions(self) -> list[Path]:
        """Find all installed Ableton Live version preference directories.

        Returns:
            List of paths to Live version preference directories, sorted by version.
            E.g., [~/Library/Preferences/Ableton/Live 11.3.42, ...]

        Note:
            Returns empty list if no versions are found.
        """
        versions = [path for path, _ in self._iter_live_versions()]
        return sorted(versions, key=lambda p: p.name)

    def find_latest_version(self) -> Path:
        """Find the latest installed Ableton Live version preference directory.

        Returns:
            Path to the latest Live version preference directory.

        Raises:
            AbletonNotFoundError: If no Ableton Live installation is found.
        """
        versions = self.find_live_versions()
        if not versions:
            raise AbletonNotFoundError(
                f"No Ableton Live versions found in {self.preferences_base}. "
                "Make sure Ableton Live has been run at least once."
            )
        return versions[-1]

    def find_preferences_cfg(self, version_path: Path | None = None) -> Path:
        """Find the Preferences.cfg file for an Ableton Live version.

        Args:
            version_path: Path to a specific Live version's preference directory.
                If None, uses the latest installed version.

        Returns:
            Path to the Preferences.cfg file.

        Raises:
            AbletonNotFoundError: If the preferences file doesn't exist.
        """
        if version_path is None:
            version_path = self.find_latest_version()

        prefs_file = version_path / "Preferences.cfg"
        if not prefs_file.exists():
            raise AbletonNotFoundError(
                f"Preferences.cfg not found at {prefs_file}. "
                "Make sure Ableton Live has been run at least once."
            )
        return prefs_file

    def ensure_remote_scripts_dir(self) -> Path:
        """Ensure the Remote Scripts directory exists and return its path.

        Creates the directory and any necessary parent directories if they
        don't exist.

        Returns:
            Path to the Remote Scripts directory.
        """
        remote_scripts = self.remote_scripts_dir
        remote_scripts.mkdir(parents=True, exist_ok=True)
        return remote_scripts


def get_ableton_paths() -> AbletonPaths:
    """Get an AbletonPaths instance for the current platform.

    This is a convenience function that creates an AbletonPaths instance
    with auto-detected platform.

    Returns:
        AbletonPaths instance configured for the current platform.

    Raises:
        UnsupportedPlatformError: If the platform is not supported.
    """
    return AbletonPaths()
