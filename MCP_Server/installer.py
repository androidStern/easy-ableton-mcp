"""Remote Script installation utilities.

This module provides functionality to install the Ableton MCP Remote Script
by creating symlinks (macOS) or directory junctions (Windows) to the user's
Ableton Live Remote Scripts folder.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .platform import AbletonPaths, Platform, get_ableton_paths

if TYPE_CHECKING:
    pass


class InstallationError(Exception):
    """Raised when Remote Script installation fails."""

    pass


class SymlinkExistsError(InstallationError):
    """Raised when a symlink/junction already exists at the target location."""

    def __init__(self, path: Path, target: Path | None = None) -> None:
        self.path = path
        self.target = target
        if target:
            msg = f"Symlink already exists: {path} -> {target}"
        else:
            msg = f"Path already exists: {path}"
        super().__init__(msg)


class SourceNotFoundError(InstallationError):
    """Raised when the Remote Script source folder doesn't exist."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Remote Script source folder not found: {path}")


class JunctionCreationError(InstallationError):
    """Raised when Windows junction creation fails."""

    def __init__(self, source: Path, target: Path, reason: str) -> None:
        self.source = source
        self.target = target
        super().__init__(
            f"Failed to create junction: {target} -> {source}. Reason: {reason}"
        )


def _resolve_script_source(source_path: Path | None = None) -> Path:
    """Resolve the Remote Script source directory.

    Args:
        source_path: Explicit path to the Remote Script folder.
            If None, defaults to AbletonMCP_Remote_Script in the project root.

    Returns:
        Resolved absolute path to the source directory.

    Raises:
        SourceNotFoundError: If the source directory doesn't exist.
    """
    if source_path is None:
        # Default: assume we're in MCP_Server, go up to project root
        project_root = Path(__file__).parent.parent
        source_path = project_root / "AbletonMCP_Remote_Script"

    source_path = source_path.resolve()

    if not source_path.exists():
        raise SourceNotFoundError(source_path)

    if not source_path.is_dir():
        raise SourceNotFoundError(source_path)

    return source_path


def _is_windows_junction(path: Path) -> bool:
    """Check if a path is a Windows junction (directory reparse point).

    Args:
        path: Path to check.

    Returns:
        True if the path is a junction, False otherwise.
    """
    if sys.platform != "win32":
        return False

    import os
    import stat

    try:
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        # Junctions are reparse points that appear as directories
        st = os.lstat(path)
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _remove_existing(path: Path) -> None:
    """Remove an existing file, symlink, or directory at the given path.

    Args:
        path: Path to remove.
    """
    if path.is_symlink():
        # Symlink (may point to non-existent target)
        path.unlink()
    elif sys.platform == "win32" and _is_windows_junction(path):
        # Windows junction - must use unlink, NOT rmtree
        # rmtree would follow the junction and delete the source files
        import os
        os.unlink(path)
    elif path.is_dir():
        # Regular directory
        shutil.rmtree(path)
    elif path.exists():
        # Regular file
        path.unlink()


def _create_symlink_macos(source: Path, target: Path) -> None:
    """Create a symlink on macOS.

    Args:
        source: The Remote Script source folder.
        target: The symlink path in Remote Scripts directory.
    """
    target.symlink_to(source, target_is_directory=True)


def _create_junction_windows(source: Path, target: Path) -> None:
    """Create a directory junction on Windows.

    Uses mklink /J which creates a directory junction. This is preferred over
    symlinks on Windows because:
    - No elevated privileges required
    - Works across Ableton's Python environment
    - Transparent to applications

    Args:
        source: The Remote Script source folder.
        target: The junction path in Remote Scripts directory.

    Raises:
        JunctionCreationError: If mklink fails.
    """
    # mklink /J <link> <target>
    # Note: mklink is a cmd.exe builtin, so we need to use cmd /c
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise JunctionCreationError(
            source, target, result.stderr.strip() or result.stdout.strip()
        )


def install_remote_script(
    source_path: Path | None = None,
    script_name: str = "AbletonMCP",
    paths: AbletonPaths | None = None,
    force: bool = True,
) -> Path:
    """Install the Remote Script by creating a symlink/junction.

    Creates a symlink (macOS) or directory junction (Windows) from the
    Remote Scripts folder to the source folder. This allows live development
    without copying files.

    Args:
        source_path: Path to the Remote Script source folder.
            If None, defaults to AbletonMCP_Remote_Script in the project root.
        script_name: Name for the symlink/junction in Remote Scripts folder.
            This must match the name written to Ableton's preferences.
            Defaults to "AbletonMCP".
        paths: AbletonPaths instance for path resolution.
            If None, creates one with auto-detected platform.
        force: If True, removes existing symlink/folder at target.
            If False, raises SymlinkExistsError if target exists.

    Returns:
        Path to the created symlink/junction.

    Raises:
        SourceNotFoundError: If source folder doesn't exist.
        SymlinkExistsError: If target exists and force=False.
        InstallationError: If symlink/junction creation fails.
    """
    if paths is None:
        paths = get_ableton_paths()

    # Resolve and validate source
    source = _resolve_script_source(source_path)

    # Ensure Remote Scripts directory exists
    remote_scripts_dir = paths.ensure_remote_scripts_dir()

    # Target path for symlink/junction
    target = remote_scripts_dir / script_name

    # Handle existing path
    if target.exists() or target.is_symlink():
        if not force:
            if target.is_symlink():
                existing_target = target.resolve() if target.exists() else None
                raise SymlinkExistsError(target, existing_target)
            raise SymlinkExistsError(target)
        _remove_existing(target)

    # Create symlink or junction based on platform
    if paths.platform == Platform.MACOS:
        _create_symlink_macos(source, target)
    elif paths.platform == Platform.WINDOWS:
        _create_junction_windows(source, target)

    return target


def verify_installation(script_name: str = "AbletonMCP", paths: AbletonPaths | None = None) -> bool:
    """Verify that the Remote Script is correctly installed.

    Checks that:
    1. The symlink/junction exists in Remote Scripts folder
    2. The target is accessible and contains expected files

    Args:
        script_name: Name of the installed script.
        paths: AbletonPaths instance for path resolution.

    Returns:
        True if installation is valid, False otherwise.
    """
    if paths is None:
        paths = get_ableton_paths()

    target = paths.remote_scripts_dir / script_name

    # Check symlink/junction exists
    if not target.exists():
        return False

    # Check it points to a valid directory
    if not target.is_dir():
        return False

    # Check for expected __init__.py (Remote Scripts must have this)
    init_file = target / "__init__.py"
    if not init_file.exists():
        return False

    return True


def get_installed_script_path(script_name: str = "AbletonMCP", paths: AbletonPaths | None = None) -> Path | None:
    """Get the path to an installed Remote Script.

    Args:
        script_name: Name of the installed script.
        paths: AbletonPaths instance for path resolution.

    Returns:
        Path to the installed script, or None if not found.
    """
    if paths is None:
        paths = get_ableton_paths()

    target = paths.remote_scripts_dir / script_name

    if target.exists() or target.is_symlink():
        return target

    return None


def uninstall_remote_script(script_name: str = "AbletonMCP", paths: AbletonPaths | None = None) -> bool:
    """Uninstall the Remote Script by removing the symlink/junction.

    Args:
        script_name: Name of the installed script.
        paths: AbletonPaths instance for path resolution.

    Returns:
        True if the script was uninstalled, False if it wasn't installed.
    """
    if paths is None:
        paths = get_ableton_paths()

    target = paths.remote_scripts_dir / script_name

    if not target.exists() and not target.is_symlink():
        return False

    _remove_existing(target)
    return True
