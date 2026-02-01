"""Ableton Live process detection and control.

This module provides utilities for detecting if Ableton Live is running,
gracefully quitting the application (which triggers save dialogs), and
launching Ableton with TCP readiness checking.
"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from enum import Enum

from .platform import Platform, get_platform


class AbletonQuitError(Exception):
    """Raised when Ableton Live fails to quit within the timeout."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(
            f"Ableton Live did not quit within {timeout} seconds. "
            "The user may need to respond to a save dialog."
        )


class AbletonLaunchError(Exception):
    """Raised when Ableton Live fails to launch."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AbletonTCPNotReadyError(Exception):
    """Raised when the Remote Script TCP server is not ready within the timeout."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        super().__init__(
            f"Ableton Live launched but Remote Script TCP server at {host}:{port} "
            f"was not ready after {timeout} seconds. "
            "Make sure the AbletonMCP Remote Script is installed and enabled."
        )


class QuitResult(Enum):
    """Result of attempting to quit Ableton Live."""

    SUCCESS = "success"
    NOT_RUNNING = "not_running"
    TIMEOUT = "timeout"


@dataclass
class AbletonProcessStatus:
    """Status of the Ableton Live process."""

    running: bool
    platform: Platform


def is_ableton_running(platform: Platform | None = None) -> bool:
    """Check if Ableton Live is currently running.

    Args:
        platform: The platform to check on. If None, auto-detects.

    Returns:
        True if Ableton Live is running, False otherwise.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
        subprocess.SubprocessError: If the detection command fails.
    """
    if platform is None:
        platform = get_platform()

    if platform == Platform.MACOS:
        return _is_ableton_running_macos()
    elif platform == Platform.WINDOWS:
        return _is_ableton_running_windows()
    # Should never reach here due to enum exhaustiveness
    raise ValueError(f"Unhandled platform: {platform}")


def _is_ableton_running_macos() -> bool:
    """Check if Ableton Live is running on macOS.

    Uses pgrep to find processes matching "Ableton Live".
    This works across all editions (Suite/Standard/Intro) and requires
    no special permissions (unlike osascript System Events).
    """
    result = subprocess.run(
        ["pgrep", "-f", "Ableton Live"],
        capture_output=True,
        text=True,
    )
    # pgrep returns 0 if any processes matched, 1 if none matched
    return result.returncode == 0


def _is_ableton_running_windows() -> bool:
    """Check if Ableton Live is running on Windows.

    Uses tasklist to filter for processes matching "Ableton Live*".
    This matches all editions (Suite, Standard, Intro).
    """
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Ableton Live*"],
        capture_output=True,
        text=True,
        check=True,
    )
    # tasklist always outputs header lines even when no process is found.
    # If Ableton is running, "Ableton Live" will appear in the output.
    return "Ableton Live" in result.stdout


def quit_ableton_gracefully(platform: Platform | None = None) -> None:
    """Send a graceful quit request to Ableton Live.

    This triggers the application's normal quit behavior, which will
    show save dialogs if there are unsaved changes. The user may need
    to interact with these dialogs.

    Note: This function returns immediately after sending the quit request.
    Use `wait_for_ableton_quit()` to wait for Ableton to actually close.

    Args:
        platform: The platform to quit on. If None, auto-detects.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
        subprocess.SubprocessError: If the quit command fails.
    """
    if platform is None:
        platform = get_platform()

    if platform == Platform.MACOS:
        _quit_ableton_macos()
    elif platform == Platform.WINDOWS:
        _quit_ableton_windows()
    else:
        raise ValueError(f"Unhandled platform: {platform}")


def _quit_ableton_macos() -> None:
    """Gracefully quit Ableton Live on macOS.

    Uses AppleScript with the bundle ID "com.ableton.live" which works
    across all editions (Suite/Standard/Intro).
    """
    subprocess.run(
        ["osascript", "-e", 'tell application id "com.ableton.live" to quit'],
        capture_output=True,
        text=True,
        timeout=10.0,  # Don't hang indefinitely if Ableton is unresponsive
        check=True,
    )


def _quit_ableton_windows() -> None:
    """Gracefully quit Ableton Live on Windows.

    Uses taskkill without /F to send WM_CLOSE, which triggers the normal
    quit behavior including save dialogs.
    """
    subprocess.run(
        ["taskkill", "/IM", "Ableton Live*.exe"],
        capture_output=True,
        text=True,
        timeout=10.0,  # Don't hang indefinitely if taskkill is unresponsive
        # Don't check=True here because taskkill returns non-zero if no
        # matching process is found, but that's not an error for our use case.
    )


def wait_for_ableton_quit(
    timeout: float = 30.0,
    poll_interval: float = 1.0,
    platform: Platform | None = None,
) -> bool:
    """Wait for Ableton Live to quit.

    Polls to check if Ableton is still running until it quits or timeout.

    Args:
        timeout: Maximum time to wait in seconds (default: 30).
        poll_interval: Time between checks in seconds (default: 1).
        platform: The platform to check on. If None, auto-detects.

    Returns:
        True if Ableton quit within the timeout, False otherwise.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
    """
    if platform is None:
        platform = get_platform()

    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        if not is_ableton_running(platform):
            return True
        time.sleep(poll_interval)

    return False


def quit_ableton_and_wait(
    timeout: float = 30.0,
    poll_interval: float = 1.0,
    platform: Platform | None = None,
) -> QuitResult:
    """Gracefully quit Ableton Live and wait for it to close.

    This is a convenience function that combines `quit_ableton_gracefully()`
    and `wait_for_ableton_quit()`.

    Args:
        timeout: Maximum time to wait for quit in seconds (default: 30).
        poll_interval: Time between status checks in seconds (default: 1).
        platform: The platform to operate on. If None, auto-detects.

    Returns:
        QuitResult.SUCCESS: Ableton quit successfully.
        QuitResult.NOT_RUNNING: Ableton was not running.
        QuitResult.TIMEOUT: Ableton did not quit within the timeout.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
        subprocess.SubprocessError: If the quit command fails.
    """
    if platform is None:
        platform = get_platform()

    # Check if Ableton is running first
    if not is_ableton_running(platform):
        return QuitResult.NOT_RUNNING

    # Send quit request
    quit_ableton_gracefully(platform)

    # Wait for it to quit
    if wait_for_ableton_quit(timeout, poll_interval, platform):
        return QuitResult.SUCCESS

    return QuitResult.TIMEOUT


def ensure_ableton_closed(
    timeout: float = 30.0,
    poll_interval: float = 1.0,
    platform: Platform | None = None,
) -> None:
    """Ensure Ableton Live is closed, quitting it if necessary.

    This function is useful before operations that require Ableton to be
    closed, such as modifying Preferences.cfg.

    Args:
        timeout: Maximum time to wait for quit in seconds (default: 30).
        poll_interval: Time between status checks in seconds (default: 1).
        platform: The platform to operate on. If None, auto-detects.

    Raises:
        AbletonQuitError: If Ableton did not quit within the timeout.
        UnsupportedPlatformError: If platform detection fails.
        subprocess.SubprocessError: If the quit command fails.
    """
    result = quit_ableton_and_wait(timeout, poll_interval, platform)

    if result == QuitResult.TIMEOUT:
        raise AbletonQuitError(timeout)
    # QuitResult.SUCCESS or QuitResult.NOT_RUNNING are both acceptable


# =============================================================================
# Ableton Launch Functions
# =============================================================================


def launch_ableton(platform: Platform | None = None) -> None:
    """Launch Ableton Live.

    This starts Ableton Live without waiting for it to be fully ready.
    Use `wait_for_tcp_ready()` to wait for the Remote Script TCP server.

    Args:
        platform: The platform to launch on. If None, auto-detects.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
        AbletonLaunchError: If the launch command fails.
    """
    if platform is None:
        platform = get_platform()

    if platform == Platform.MACOS:
        _launch_ableton_macos()
    elif platform == Platform.WINDOWS:
        _launch_ableton_windows()
    else:
        raise ValueError(f"Unhandled platform: {platform}")


def _launch_ableton_macos() -> None:
    """Launch Ableton Live on macOS.

    Uses the open command with bundle ID "com.ableton.live" which works
    across all editions (Suite/Standard/Intro) and requires no special
    permissions (unlike osascript).
    """
    result = subprocess.run(
        ["open", "-b", "com.ableton.live"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AbletonLaunchError(
            f"Failed to launch Ableton Live on macOS: {result.stderr.strip()}"
        )


def _launch_ableton_windows() -> None:
    """Launch Ableton Live on Windows.

    Uses the 'start' command to launch Ableton Live by its registered
    application name. This works because Ableton registers itself as a
    protocol handler during installation.
    """
    # Try using 'start' with the app name - Windows will find the executable
    result = subprocess.run(
        ["cmd", "/c", "start", "", "Ableton Live"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AbletonLaunchError(
            f"Failed to launch Ableton Live on Windows: {result.stderr.strip()}. "
            "You may need to launch Ableton Live manually."
        )


def wait_for_tcp_ready(
    host: str = "localhost",
    port: int = 9877,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for the Remote Script TCP server to be ready.

    Polls the specified host:port until a TCP connection can be established
    or the timeout expires.

    Args:
        host: The host to connect to (default: "localhost").
        port: The port to connect to (default: 9877, Remote Script's TCP port).
        timeout: Maximum time to wait in seconds (default: 30).
        poll_interval: Time between connection attempts in seconds (default: 0.5).

    Returns:
        True if the TCP server is ready, False if timeout expired.
    """
    start_time = time.monotonic()

    while time.monotonic() - start_time < timeout:
        try:
            sock = socket.create_connection((host, port), timeout=1.0)
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            # Connection not ready yet - keep polling
            time.sleep(poll_interval)

    return False


def ensure_ableton_running(
    host: str = "localhost",
    port: int = 9877,
    tcp_timeout: float = 30.0,
    poll_interval: float = 0.5,
    platform: Platform | None = None,
) -> bool:
    """Ensure Ableton Live is running and TCP server is ready.

    This is the main entry point for lazy Ableton launch. It:
    1. Checks if Ableton is already running
    2. If not, launches Ableton
    3. Waits for the Remote Script TCP server to be ready

    Args:
        host: The TCP host to connect to (default: "localhost").
        port: The TCP port to connect to (default: 9877).
        tcp_timeout: Maximum time to wait for TCP ready in seconds (default: 30).
        poll_interval: Time between TCP connection attempts in seconds (default: 0.5).
        platform: The platform to operate on. If None, auto-detects.

    Returns:
        True if Ableton was already running, False if it was launched.

    Raises:
        UnsupportedPlatformError: If platform detection fails.
        AbletonLaunchError: If Ableton fails to launch.
        AbletonTCPNotReadyError: If TCP server is not ready within timeout.
    """
    if platform is None:
        platform = get_platform()

    was_running = is_ableton_running(platform)

    if not was_running:
        launch_ableton(platform)

    # Wait for TCP server to be ready (whether we launched or not)
    if not wait_for_tcp_ready(host, port, tcp_timeout, poll_interval):
        raise AbletonTCPNotReadyError(host, port, tcp_timeout)

    return was_running
