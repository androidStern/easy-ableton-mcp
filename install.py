#!/usr/bin/env python3
"""CLI tool for installing Ableton MCP Remote Script.

This script automates the installation of the Ableton MCP Remote Script by:
1. Checking if Ableton Live is running and prompting to quit
2. Creating a symlink/junction to the User Library Remote Scripts folder
3. Configuring Ableton's Preferences.cfg with the control surface

Usage:
    python install.py [--source PATH] [--name NAME]

Examples:
    python install.py
    python install.py --source ./my_script --name MyController
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory (where this script lives)."""
    return Path(__file__).parent.resolve()


def setup_import_path() -> None:
    """Add MCP_Server to the import path for standalone execution."""
    project_root = get_project_root()
    mcp_server_path = project_root / "MCP_Server"
    if mcp_server_path.exists() and str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def main() -> int:
    """Main entry point for the install CLI."""
    parser = argparse.ArgumentParser(
        description="Install Ableton MCP Remote Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
      Install using defaults (AbletonMCP_Remote_Script -> AbletonMCP)

  %(prog)s --source ./my_script --name MyController
      Install custom script with custom name

After installation, launch Ableton Live to use the MCP server.
        """,
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to the Remote Script source folder (default: AbletonMCP_Remote_Script)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="AbletonMCP",
        help="Name for the installed script in Ableton (default: AbletonMCP)",
    )

    args = parser.parse_args()

    # Resolve source path
    if args.source is None:
        source_path = get_project_root() / "AbletonMCP_Remote_Script"
    else:
        source_path = args.source.resolve()

    script_name = args.name

    # Validate source exists
    if not source_path.exists():
        print(f"Error: Source folder not found: {source_path}", file=sys.stderr)
        print(
            "Make sure the Remote Script folder exists at the specified location.",
            file=sys.stderr,
        )
        return 1

    if not source_path.is_dir():
        print(f"Error: Source path is not a directory: {source_path}", file=sys.stderr)
        return 1

    # Check for required __init__.py
    init_file = source_path / "__init__.py"
    if not init_file.exists():
        print(
            f"Error: Source folder missing __init__.py: {source_path}", file=sys.stderr
        )
        print("Remote Scripts must contain an __init__.py file.", file=sys.stderr)
        return 1

    # Setup import path and import modules
    # We import directly from module files to avoid triggering __init__.py
    # which has dependencies on external packages (mcp) not needed for installation
    setup_import_path()

    try:
        import importlib.util

        def load_module(name: str, file_path: Path):
            """Load a module directly from file, bypassing __init__.py."""
            spec = importlib.util.spec_from_file_location(name, file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load module from {file_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        mcp_server_dir = get_project_root() / "MCP_Server"

        # Load modules in dependency order
        platform_mod = load_module(
            "MCP_Server.platform", mcp_server_dir / "platform.py"
        )
        ableton_process_mod = load_module(
            "MCP_Server.ableton_process", mcp_server_dir / "ableton_process.py"
        )
        installer_mod = load_module(
            "MCP_Server.installer", mcp_server_dir / "installer.py"
        )
        preferences_mod = load_module(
            "MCP_Server.preferences", mcp_server_dir / "preferences.py"
        )

        # Extract what we need
        AbletonQuitError = ableton_process_mod.AbletonQuitError
        ensure_ableton_closed = ableton_process_mod.ensure_ableton_closed
        InstallationError = installer_mod.InstallationError
        install_remote_script = installer_mod.install_remote_script
        AbletonNotFoundError = platform_mod.AbletonNotFoundError
        UnsupportedPlatformError = platform_mod.UnsupportedPlatformError
        get_ableton_paths = platform_mod.get_ableton_paths
        NoEmptySlotError = preferences_mod.NoEmptySlotError
        PreferencesParseError = preferences_mod.PreferencesParseError
        PreferencesWriteError = preferences_mod.PreferencesWriteError
        PreferencesWriter = preferences_mod.PreferencesWriter

    except (ImportError, FileNotFoundError) as e:
        print(f"Error: Failed to import required modules: {e}", file=sys.stderr)
        print(
            "Make sure MCP_Server package exists in the project root.", file=sys.stderr
        )
        return 1

    # Step 0: Check platform support
    try:
        paths = get_ableton_paths()
    except UnsupportedPlatformError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Installing '{script_name}' from: {source_path}")
    print(f"Platform: {paths.platform.name}")

    # Step 1: Ensure Ableton is closed
    print("\nChecking if Ableton Live is running...")
    try:
        ensure_ableton_closed(timeout=30.0)
    except AbletonQuitError as e:
        print(f"\nError: {e}", file=sys.stderr)
        print(
            "\nPlease close Ableton Live manually and run this script again.",
            file=sys.stderr,
        )
        print(
            "If you have unsaved work, save it first, then quit Ableton.",
            file=sys.stderr,
        )
        return 1

    print("Ableton Live is not running. Proceeding with installation...")

    # Step 2: Create symlink to User Library
    print(f"\nInstalling Remote Script to User Library...")
    try:
        symlink_path = install_remote_script(
            source_path=source_path,
            script_name=script_name,
            paths=paths,
            force=True,
        )
        print(f"  Created: {symlink_path} -> {source_path}")
    except InstallationError as e:
        print(f"\nError: Failed to install Remote Script: {e}", file=sys.stderr)
        print(
            "\nPossible causes:",
            file=sys.stderr,
        )
        print("  - Insufficient permissions to create symlink", file=sys.stderr)
        print("  - User Library folder is read-only", file=sys.stderr)
        return 1

    # Step 3: Find and modify Preferences.cfg
    print(f"\nConfiguring Ableton preferences...")
    try:
        prefs_path = paths.find_preferences_cfg()
    except AbletonNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        print(
            "\nMake sure Ableton Live has been run at least once to create preferences.",
            file=sys.stderr,
        )
        return 1

    print(f"  Found: {prefs_path}")

    try:
        writer = PreferencesWriter(prefs_path)

        # Check if script is already installed
        existing_slot = writer.find_script(script_name)
        if existing_slot is not None:
            print(
                f"  Script '{script_name}' already configured in slot {existing_slot.display_index}"
            )
        else:
            slot_index = writer.set_control_surface(script_name)
            print(f"  Backed up: {writer.backup_path}")
            print(f"  Configured Control Surface slot {slot_index + 1}: '{script_name}'")

    except NoEmptySlotError:
        print(
            f"\nError: No empty control surface slots available.", file=sys.stderr
        )
        print(
            "\nAll 7 control surface slots are in use. To install this script:",
            file=sys.stderr,
        )
        print(
            "  1. Open Ableton Live",
            file=sys.stderr,
        )
        print(
            "  2. Go to Preferences > Link, Tempo & MIDI",
            file=sys.stderr,
        )
        print(
            "  3. Clear one of the Control Surface slots by setting it to 'None'",
            file=sys.stderr,
        )
        print(
            "  4. Quit Ableton and run this script again",
            file=sys.stderr,
        )
        return 1

    except PreferencesParseError as e:
        print(
            f"\nError: Failed to parse Preferences.cfg: {e}", file=sys.stderr
        )
        print(
            "\nThe preferences file may be corrupted or from an unsupported Ableton version.",
            file=sys.stderr,
        )
        return 1

    except PreferencesWriteError as e:
        print(
            f"\nError: Failed to write preferences: {e}", file=sys.stderr
        )
        print(
            "\nA backup was created. To restore, copy:",
            file=sys.stderr,
        )
        print(f"  {writer.backup_path} -> {prefs_path}", file=sys.stderr)
        return 1

    # Success!
    print("\n" + "=" * 60)
    print("Installation complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Launch Ableton Live")
    print(f"  2. The '{script_name}' control surface should be auto-configured")
    print("  3. Start the MCP server to connect")
    print("\nIf you encounter issues:")
    print("  - Open Preferences > Link, Tempo & MIDI")
    print(f"  - Verify '{script_name}' appears in a Control Surface slot")
    print("  - Check that the script folder exists in User Library/Remote Scripts/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
