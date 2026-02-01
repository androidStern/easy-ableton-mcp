# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncIterator, Dict, Any, List, Union, Callable, Optional

from .protocol import send_message, recv_message
from .ableton_process import ensure_ableton_running, AbletonTCPNotReadyError, AbletonLaunchError

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response.

        Uses length-prefixed framing for reliable message boundaries.
        """
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {
            "type": command_type,
            "params": params or {}
        }

        try:
            logger.info(f"Sending command: {command_type} with params: {params}")

            # Send the command with length prefix
            send_message(self.sock, command)
            logger.info("Command sent, waiting for response...")

            # Receive the response with length prefix
            response = recv_message(self.sock)
            logger.info(f"Response received, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))

            return response.get("result", {})
        except ConnectionError as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle.

    Note: We do NOT connect to Ableton on startup (lazy launch).
    Ableton will be launched and connected on the first tool call.
    """
    try:
        logger.info("AbletonMCP server starting up (Ableton will be launched on first tool call)")
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    instructions="Ableton Live integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection.

    Implements lazy launch: if Ableton is not running, it will be launched
    automatically on the first tool call.
    """
    global _ableton_connection

    if _ableton_connection is not None and _ableton_connection.sock is not None:
        return _ableton_connection

    # Connection doesn't exist or socket is dead, create a new one
    _ableton_connection = None

    # Ensure Ableton is running before attempting to connect (lazy launch)
    try:
        was_running = ensure_ableton_running()
        if was_running:
            logger.info("Ableton Live is already running")
        else:
            logger.info("Launched Ableton Live")
    except AbletonTCPNotReadyError as e:
        raise RuntimeError(
            f"Ableton Live launched but TCP server not ready after {e.timeout}s. "
            "Make sure the AbletonMCP Remote Script is installed and enabled."
        )
    except AbletonLaunchError as e:
        raise RuntimeError(f"Failed to launch Ableton Live: {e}")

    # Try to connect up to 3 times with a short delay between attempts
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
            _ableton_connection = AbletonConnection(host="localhost", port=9877)
            if _ableton_connection.connect():
                logger.info("Created new persistent connection to Ableton")

                # Validate connection with a simple command
                try:
                    _ableton_connection.send_command("get_session_info")
                    logger.info("Connection validated successfully")
                    return _ableton_connection
                except Exception as e:
                    logger.error(f"Connection validation failed: {str(e)}")
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            else:
                _ableton_connection = None
        except Exception as e:
            logger.error(f"Connection attempt {attempt} failed: {str(e)}")
            if _ableton_connection:
                _ableton_connection.disconnect()
                _ableton_connection = None

        # Wait before trying again, but only if we have more attempts left
        if attempt < max_attempts:
            import time
            time.sleep(1.0)

    # If we get here, all connection attempts failed
    raise RuntimeError("Could not connect to Ableton. Make sure the Remote Script is running.")


def ableton_command(
    command: str,
    format_result: Optional[Callable[[dict], str]] = None,
    error_context: Optional[str] = None
):
    """Decorator that wraps an MCP tool with Ableton connection and error handling.

    The decorated function should return a params dict (or None for no params).
    The decorator handles: connection, send_command, error logging, and response formatting.

    Args:
        command: The Ableton command name to send
        format_result: Optional function to format the result. If None, returns JSON.
        error_context: Optional context string for error messages. Defaults to command name.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> str:
            ctx_name = error_context or command.replace("_", " ")
            try:
                ableton = get_ableton_connection()
                params = fn(*args, **kwargs)
                result = ableton.send_command(command, params)
                if format_result:
                    return format_result(result, params)
                return json.dumps(result, indent=2)
            except Exception as e:
                logger.error(f"Error {ctx_name}: {str(e)}")
                return f"Error {ctx_name}: {str(e)}"
        return wrapper
    return decorator


# Result formatters for tools that don't return JSON
def _format_message(msg: str) -> Callable[[dict, dict], str]:
    """Create a formatter that returns a fixed message."""
    return lambda result, params: msg


def _format_template(template: str) -> Callable[[dict, dict], str]:
    """Create a formatter using a template with result and params access."""
    def formatter(result: dict, params: dict) -> str:
        return template.format(result=result, params=params, **result, **(params or {}))
    return formatter


# Core Tool endpoints

@mcp.tool()
@ableton_command("get_session_info")
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    return None


@mcp.tool()
@ableton_command("get_session_tree")
def get_session_tree(ctx: Context) -> str:
    """Get a compact tree view of the entire Ableton session.

    Returns all tracks, clips, devices (with nested chains/racks),
    return tracks, and scenes in a single call. Use this to understand
    the full session structure before making changes.
    """
    return None


@mcp.tool()
@ableton_command("get_track_info")
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.

    Parameters:
    - track_index: The index of the track to get information about
    """
    return {"track_index": track_index}

@mcp.tool()
@ableton_command("create_midi_track",
                 format_result=lambda r, p: f"Created new MIDI track: {r.get('name', 'unknown')}")
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    return {"index": index}


@mcp.tool()
@ableton_command("set_track_name",
                 format_result=lambda r, p: f"Renamed track to: {r.get('name', p.get('name'))}")
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    return {"track_index": track_index, "name": name}


@mcp.tool()
@ableton_command("create_clip",
                 format_result=lambda r, p: f"Created new clip at track {p['track_index']}, slot {p['clip_index']} with length {p['length']} beats")
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    return {"track_index": track_index, "clip_index": clip_index, "length": length}


@mcp.tool()
@ableton_command("add_notes_to_clip",
                 format_result=lambda r, p: f"Added {len(p.get('notes', []))} notes to clip at track {p['track_index']}, slot {p['clip_index']}")
def add_notes_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    return {"track_index": track_index, "clip_index": clip_index, "notes": notes}


@mcp.tool()
@ableton_command("set_clip_name",
                 format_result=lambda r, p: f"Renamed clip at track {p['track_index']}, slot {p['clip_index']} to '{p['name']}'")
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    return {"track_index": track_index, "clip_index": clip_index, "name": name}


@mcp.tool()
@ableton_command("set_tempo",
                 format_result=lambda r, p: f"Set tempo to {p['tempo']} BPM")
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    return {"tempo": tempo}


def _format_load_instrument(result: dict, params: dict) -> str:
    """Format result for load_instrument_or_effect."""
    uri = params.get("item_uri")
    track_index = params.get("track_index")
    if result.get("loaded", False):
        new_devices = result.get("new_devices", [])
        if new_devices:
            return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
        devices = result.get("devices_after", [])
        return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
    return f"Failed to load instrument with URI '{uri}'"


@mcp.tool()
@ableton_command("load_browser_item", format_result=_format_load_instrument,
                 error_context="loading instrument by URI")
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    return {"track_index": track_index, "item_uri": uri}


@mcp.tool()
@ableton_command("fire_clip",
                 format_result=lambda r, p: f"Started playing clip at track {p['track_index']}, slot {p['clip_index']}")
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    return {"track_index": track_index, "clip_index": clip_index}


@mcp.tool()
@ableton_command("stop_clip",
                 format_result=lambda r, p: f"Stopped clip at track {p['track_index']}, slot {p['clip_index']}")
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    return {"track_index": track_index, "clip_index": clip_index}


@mcp.tool()
@ableton_command("start_playback", format_result=lambda r, p: "Started playback")
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    return None


@mcp.tool()
@ableton_command("stop_playback", format_result=lambda r, p: "Stopped playback")
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    return None

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

@mcp.tool()
@ableton_command("get_device_parameters")
def get_device_parameters(ctx: Context, track_index: int, device_index: int,
                          device_path: List[int] = None) -> str:
    """
    Get all parameters for a device.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - device_path: Optional path for nested devices in racks.
                   Format: [chain_idx, device_idx, ...] for instrument/effect racks
                   Use negative values for drum pad notes (e.g., -36 for C1)
                   Example: [0, 0] = chain 0, device 0
                   Example: [-36, 0] = drum pad C1, device 0
    """
    return {"track_index": track_index, "device_index": device_index, "device_path": device_path}


@mcp.tool()
@ableton_command("set_device_parameter")
def set_device_parameter(ctx: Context, track_index: int, device_index: int,
                         parameter_index: int, value: float,
                         device_path: List[int] = None) -> str:
    """
    Set a device parameter to a normalized value (0.0-1.0).

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to set
    - value: Normalized value between 0.0 and 1.0
    - device_path: Optional path for nested devices in racks (see get_device_parameters)
    """
    return {
        "track_index": track_index,
        "device_index": device_index,
        "parameter_index": parameter_index,
        "value": value,
        "device_path": device_path
    }


@mcp.tool()
@ableton_command("batch_set_device_parameters")
def batch_set_device_parameters(ctx: Context, track_index: int, device_index: int,
                                parameters: List[Dict[str, Union[int, float]]],
                                device_path: List[int] = None) -> str:
    """
    Set multiple device parameters atomically.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameters: List of parameter updates, each with "index" and "value" keys
                  Example: [{"index": 1, "value": 0.5}, {"index": 2, "value": 0.8}]
    - device_path: Optional path for nested devices in racks (see get_device_parameters)
    """
    return {
        "track_index": track_index,
        "device_index": device_index,
        "parameters": parameters,
        "device_path": device_path
    }

# Main execution
def main():
    """Run the MCP server or perform installation."""
    import argparse

    parser = argparse.ArgumentParser(description="Ableton MCP Server")
    parser.add_argument("--install", action="store_true",
                        help="Install Remote Script and configure Ableton preferences")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove Remote Script and restore Ableton preferences")
    args = parser.parse_args()

    if args.uninstall:
        from .platform import get_platform, get_ableton_paths, AbletonNotFoundError
        from .installer import uninstall_remote_script
        from .preferences import PreferencesWriter
        from .ableton_process import is_ableton_running, ensure_ableton_closed
        from pathlib import Path

        print("=== Ableton MCP Uninstall ===\n")
        script_name = "AbletonMCP"

        try:
            paths = get_ableton_paths()

            # Check if Ableton is running
            if is_ableton_running():
                print("Ableton Live is running. It must be closed to modify preferences.")
                print("Please save your work. Requesting quit...")
                ensure_ableton_closed(timeout=60)
                print("Ableton closed.\n")

            # Remove symlink
            symlink_path = paths.remote_scripts_dir / script_name
            if symlink_path.exists() or symlink_path.is_symlink():
                uninstall_remote_script(script_name, paths)
                print(f"Removed Remote Script symlink: {symlink_path}")
            else:
                print(f"Remote Script not installed (no symlink at {symlink_path})")

            # Restore preferences from backup or clear slot
            prefs_path = paths.find_preferences_cfg()
            backup_path = prefs_path.with_suffix(".cfg.backup")

            if backup_path.exists():
                import shutil
                shutil.copy2(backup_path, prefs_path)
                print(f"Restored preferences from backup: {backup_path}")
            else:
                # No backup - clear the slot manually
                writer = PreferencesWriter(prefs_path)
                existing = writer.find_script(script_name)
                if existing:
                    writer.clear_control_surface(existing.index, create_backup=False)
                    print(f"Cleared {script_name} from control surface slot {existing.display_index}")
                else:
                    print("No AbletonMCP entry found in preferences")

            print("\n=== Uninstall Complete ===")
            print("\nAbleton MCP has been removed. You can safely delete the source code if desired.")
            return 0

        except AbletonNotFoundError as e:
            print(f"\nERROR: {e}")
            return 1
        except Exception as e:
            print(f"\nERROR: {e}")
            return 1

    elif args.install:
        # Import here to avoid circular imports and keep server startup fast
        from .platform import get_platform, get_ableton_paths, AbletonNotFoundError
        from .installer import install_remote_script
        from .preferences import PreferencesWriter, NoEmptySlotError
        from .ableton_process import is_ableton_running, ensure_ableton_closed
        from pathlib import Path

        print("=== Ableton MCP Installation ===\n")

        # Find the Remote Script source
        # Try multiple locations: installed package, or dev repo
        import importlib.util
        script_name = "AbletonMCP"

        # Option 1: Check if AbletonMCP_Remote_Script is an installed package
        spec = importlib.util.find_spec("AbletonMCP_Remote_Script")
        if spec and spec.submodule_search_locations:
            script_source = Path(spec.submodule_search_locations[0])
        else:
            # Option 2: Development - relative to this file
            script_source = Path(__file__).parent.parent / "AbletonMCP_Remote_Script"

        if not script_source.exists():
            print(f"ERROR: Remote Script not found at {script_source}")
            return 1

        # Verify it has __init__.py
        if not (script_source / "__init__.py").exists():
            print(f"ERROR: Remote Script missing __init__.py at {script_source}")
            return 1

        try:
            paths = get_ableton_paths()
            print(f"Platform: {get_platform().name}")
            print(f"Remote Scripts: {paths.remote_scripts_dir}")

            # Check if Ableton is running
            if is_ableton_running():
                print("\nAbleton Live is running. It must be closed to modify preferences.")
                print("Please save your work. Requesting quit...")
                ensure_ableton_closed(timeout=60)
                print("Ableton closed.")

            # Install symlink
            print(f"\nInstalling Remote Script '{script_name}'...")
            install_remote_script(script_source, script_name, paths, force=True)
            print(f"  -> Symlinked to {paths.remote_scripts_dir / script_name}")

            # Configure preferences
            print("\nConfiguring Ableton preferences...")
            prefs_path = paths.find_preferences_cfg()
            writer = PreferencesWriter(prefs_path)

            # Check if already configured
            existing = writer.find_script(script_name)
            if existing:
                print(f"  -> Already configured in slot {existing.display_index}")
            else:
                slot = writer.set_control_surface(script_name)
                print(f"  -> Configured in slot {slot + 1}")
                print(f"  -> Backup saved to {prefs_path}.backup")

            print("\n=== Installation Complete ===")
            print("\nNext steps:")
            print("1. Start Ableton Live")
            print("2. The MCP server will auto-launch Ableton when needed")
            print("\nTo run the server:")
            print("  uvx easy-ableton-mcp")
            return 0

        except AbletonNotFoundError as e:
            print(f"\nERROR: {e}")
            print("Make sure Ableton Live is installed and has been run at least once.")
            return 1
        except NoEmptySlotError:
            print("\nERROR: All 7 control surface slots are in use.")
            print("Please free up a slot in Ableton's preferences.")
            return 1
        except Exception as e:
            print(f"\nERROR: {e}")
            return 1
    else:
        # Normal server mode
        mcp.run()

if __name__ == "__main__":
    main()