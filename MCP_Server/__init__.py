"""Ableton Live integration through the Model Context Protocol."""

__version__ = "0.1.0"

# Expose key classes and functions for easier imports
from .server import AbletonConnection, get_ableton_connection

# Platform detection and path resolution
from .platform import (
    Platform,
    UnsupportedPlatformError,
    AbletonNotFoundError,
    AbletonPaths,
    get_platform,
    get_ableton_paths,
)

# Ableton process detection and control
from .ableton_process import (
    AbletonQuitError,
    AbletonLaunchError,
    AbletonTCPNotReadyError,
    QuitResult,
    AbletonProcessStatus,
    is_ableton_running,
    quit_ableton_gracefully,
    wait_for_ableton_quit,
    quit_ableton_and_wait,
    ensure_ableton_closed,
    launch_ableton,
    wait_for_tcp_ready,
    ensure_ableton_running,
)

# Remote Script installation
from .installer import (
    InstallationError,
    SourceNotFoundError,
    SymlinkExistsError,
    JunctionCreationError,
    install_remote_script,
    verify_installation,
    get_installed_script_path,
    uninstall_remote_script,
)

# Preferences.cfg binary parser and writer
from .preferences import (
    PreferencesParseError,
    InvalidPreferencesFileError,
    ControlSurfaceSlotsNotFoundError,
    NoEmptySlotError,
    PreferencesWriteError,
    ControlSurfaceSlot,
    SlotOffset,
    PreferencesParser,
    PreferencesWriter,
)