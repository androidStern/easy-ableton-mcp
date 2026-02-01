# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import struct
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"


class CommandRegistry(object):
    """Registry for command handlers with metadata."""

    def __init__(self):
        self._handlers = {}  # command_name -> method_name
        self._main_thread = set()  # commands requiring main thread

    def register(self, name, main_thread=False):
        """Decorator to register a command handler."""
        def decorator(method):
            self._handlers[name] = method.__name__
            if main_thread:
                self._main_thread.add(name)
            return method
        return decorator

    def get_handler_name(self, command):
        return self._handlers.get(command)

    def requires_main_thread(self, command):
        return command in self._main_thread

    def is_registered(self, command):
        return command in self._handlers


# Module-level instance
commands = CommandRegistry()


# Length-prefixed protocol functions
# Protocol: 4-byte big-endian length prefix + UTF-8 JSON payload

def send_message(sock, data):
    """Send a length-prefixed JSON message over the socket."""
    msg = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack('>I', len(msg)) + msg)


def recv_exact(sock, n):
    """Receive exactly n bytes from the socket."""
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise Exception("Socket closed")
        data += chunk
    return data


def recv_message(sock):
    """Receive a length-prefixed JSON message from the socket."""
    length_bytes = recv_exact(sock, 4)
    length = struct.unpack('>I', length_bytes)[0]
    data = recv_exact(sock, length)
    return json.loads(data.decode('utf-8'))

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client using length-prefixed protocol."""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket

        try:
            while self.running:
                try:
                    # Receive length-prefixed message
                    command = recv_message(client)

                    self.log_message("Received command: " + str(command.get("type", "unknown")))

                    # Process the command and get response
                    response = self._process_command(command)

                    # Send length-prefixed response
                    send_message(client, response)

                except Exception as e:
                    error_msg = str(e)
                    if error_msg == "Socket closed":
                        self.log_message("Client disconnected")
                        break

                    self.log_message("Error handling client data: " + error_msg)
                    self.log_message(traceback.format_exc())

                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": error_msg
                    }
                    try:
                        send_message(client, error_response)
                    except Exception as e:
                        self.log_message("Failed to send error response: " + str(e))
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass
            self.log_message("Client handler stopped")

    def _execute_on_main_thread(self, func):
        """Execute a function on the main thread and return result."""
        response_queue = queue.Queue()

        def task():
            try:
                result = func()
                response_queue.put({"status": "success", "result": result})
            except Exception as e:
                self.log_message("Error in main thread task: " + str(e))
                self.log_message(traceback.format_exc())
                response_queue.put({"status": "error", "message": str(e)})

        try:
            self.schedule_message(0, task)
        except AssertionError:
            # Already on main thread
            task()

        try:
            return response_queue.get(timeout=10.0)
        except queue.Empty:
            return {"status": "error", "message": "Timeout waiting for operation to complete"}

    def _require_param(self, name, value):
        """Validate that a required parameter was provided (not None)."""
        if value is None:
            raise ValueError("Missing required parameter: " + name)
        return value

    def _get_track(self, track_index):
        """Validate track_index and return the track."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        return self._song.tracks[track_index]

    def _get_clip_slot(self, track_index, clip_index):
        """Validate indices and return the clip slot."""
        track = self._get_track(track_index)
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        return track.clip_slots[clip_index]

    def _process_command(self, command):
        """Process a command from the client using the command registry."""
        command_type = command.get("type", "")
        params = command.get("params", {})

        if not commands.is_registered(command_type):
            return {"status": "error", "message": "Unknown command: " + command_type}

        handler_name = commands.get_handler_name(command_type)
        handler = getattr(self, handler_name)

        try:
            if commands.requires_main_thread(command_type):
                return self._execute_on_main_thread(lambda: handler(**params))
            else:
                return {"status": "success", "result": handler(**params)}
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            return {"status": "error", "message": str(e)}
    
    # Command implementations

    @commands.register("get_session_info")
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    @commands.register("get_track_info")
    def _get_track_info(self, track_index=None):
        """Get information about a track"""
        try:
            track_index = self._require_param("track_index", track_index)
            track = self._get_track(track_index)

            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    @commands.register("create_midi_track", main_thread=True)
    def _create_midi_track(self, index=-1):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    @commands.register("set_track_name", main_thread=True)
    def _set_track_name(self, track_index=None, name=""):
        """Set the name of a track"""
        try:
            track_index = self._require_param("track_index", track_index)
            track = self._get_track(track_index)
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    @commands.register("create_clip", main_thread=True)
    def _create_clip(self, track_index=None, clip_index=None, length=4.0):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            track_index = self._require_param("track_index", track_index)
            clip_index = self._require_param("clip_index", clip_index)
            clip_slot = self._get_clip_slot(track_index, clip_index)

            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    @commands.register("add_notes_to_clip", main_thread=True)
    def _add_notes_to_clip(self, track_index=None, clip_index=None, notes=None):
        """Add MIDI notes to a clip"""
        if notes is None:
            notes = []
        try:
            track_index = self._require_param("track_index", track_index)
            clip_index = self._require_param("clip_index", clip_index)
            clip_slot = self._get_clip_slot(track_index, clip_index)

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    @commands.register("set_clip_name", main_thread=True)
    def _set_clip_name(self, track_index=None, clip_index=None, name=""):
        """Set the name of a clip"""
        try:
            track_index = self._require_param("track_index", track_index)
            clip_index = self._require_param("clip_index", clip_index)
            clip_slot = self._get_clip_slot(track_index, clip_index)
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    @commands.register("set_tempo", main_thread=True)
    def _set_tempo(self, tempo=120.0):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    @commands.register("fire_clip", main_thread=True)
    def _fire_clip(self, track_index=None, clip_index=None):
        """Fire a clip"""
        try:
            track_index = self._require_param("track_index", track_index)
            clip_index = self._require_param("clip_index", clip_index)
            clip_slot = self._get_clip_slot(track_index, clip_index)

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    @commands.register("stop_clip", main_thread=True)
    def _stop_clip(self, track_index=None, clip_index=None):
        """Stop a clip"""
        try:
            track_index = self._require_param("track_index", track_index)
            clip_index = self._require_param("clip_index", clip_index)
            clip_slot = self._get_clip_slot(track_index, clip_index)

            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    @commands.register("start_playback", main_thread=True)
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    @commands.register("stop_playback", main_thread=True)
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    @commands.register("get_browser_item")
    def _get_browser_item(self, uri=None, path=None):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    @commands.register("load_browser_item", main_thread=True)
    def _load_browser_item(self, track_index=None, item_uri=None):
        """Load a browser item onto a track by its URI"""
        try:
            track_index = self._require_param("track_index", track_index)
            item_uri = self._require_param("item_uri", item_uri)
            track = self._get_track(track_index)

            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None

    # Device parameter control methods

    def _normalize_param_value(self, param):
        """Convert parameter's actual value to normalized 0.0-1.0 range."""
        if (param.max - param.min) == 0:
            return 0.0
        return (param.value - param.min) / (param.max - param.min)

    def _denormalize_param_value(self, param, normalized):
        """Convert normalized 0.0-1.0 value to parameter's actual range."""
        return param.min + normalized * (param.max - param.min)

    @commands.register("get_device_parameters")
    def _get_device_parameters(self, track_index=None, device_index=None, device_path=None):
        """
        Get all parameters for a device.

        Args:
            track_index: Index of the track
            device_index: Index of the device on the track
            device_path: Optional path for nested devices (see _resolve_device)

        Returns:
            Dictionary with device info and parameters list
        """
        try:
            track_index = self._require_param("track_index", track_index)
            device_index = self._require_param("device_index", device_index)
            device = self._resolve_device(track_index, device_index, device_path)
            track = self._song.tracks[track_index]

            parameters_info = []
            for i, p in enumerate(device.parameters):
                parameters_info.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "normalized_value": self._normalize_param_value(p),
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "is_enabled": p.is_enabled
                })

            return {
                "track_index": track_index,
                "track_name": track.name,
                "device_index": device_index,
                "device_name": device.name,
                "device_path": device_path,
                "parameters": parameters_info
            }
        except Exception as e:
            self.log_message("Error getting device parameters: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    @commands.register("set_device_parameter", main_thread=True)
    def _set_device_parameter(self, track_index=None, device_index=None, parameter_index=None, value=None, device_path=None):
        """
        Set a device parameter to a normalized value (0.0-1.0).

        Args:
            track_index: Index of the track
            device_index: Index of the device on the track
            parameter_index: Index of the parameter to set
            value: Normalized value between 0.0 and 1.0
            device_path: Optional path for nested devices (see _resolve_device)

        Returns:
            Dictionary with the updated parameter info
        """
        try:
            track_index = self._require_param("track_index", track_index)
            device_index = self._require_param("device_index", device_index)
            parameter_index = self._require_param("parameter_index", parameter_index)
            value = self._require_param("value", value)
            device = self._resolve_device(track_index, device_index, device_path)

            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index {0} out of range (0-{1}) for device '{2}'".format(
                    parameter_index, len(device.parameters) - 1, device.name))

            if value < 0.0 or value > 1.0:
                raise ValueError("Normalized value {0} must be between 0.0 and 1.0".format(value))

            parameter = device.parameters[parameter_index]
            parameter.value = self._denormalize_param_value(parameter, value)

            return {
                "parameter_index": parameter_index,
                "parameter_name": parameter.name,
                "value": parameter.value,
                "normalized_value": value
            }
        except Exception as e:
            self.log_message("Error setting device parameter: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    @commands.register("batch_set_device_parameters", main_thread=True)
    def _batch_set_device_parameters(self, track_index=None, device_index=None, parameters=None, device_path=None):
        """
        Set multiple device parameters atomically.

        Args:
            track_index: Index of the track
            device_index: Index of the device on the track
            parameters: List of dicts with "index" and "value" keys
            device_path: Optional path for nested devices (see _resolve_device)

        Returns:
            Dictionary with count and details of updated parameters
        """
        if parameters is None:
            parameters = []
        try:
            track_index = self._require_param("track_index", track_index)
            device_index = self._require_param("device_index", device_index)
            device = self._resolve_device(track_index, device_index, device_path)

            updated_params_info = []
            errors = []

            for param_update in parameters:
                p_idx = param_update.get("index")
                val_norm = param_update.get("value")

                if p_idx is None or val_norm is None:
                    errors.append("Missing 'index' or 'value' in parameter update")
                    continue

                if p_idx < 0 or p_idx >= len(device.parameters):
                    errors.append("Parameter index {0} out of range".format(p_idx))
                    continue

                if val_norm < 0.0 or val_norm > 1.0:
                    errors.append("Value {0} for parameter {1} out of range".format(val_norm, p_idx))
                    continue

                param = device.parameters[p_idx]
                param.value = self._denormalize_param_value(param, val_norm)
                updated_params_info.append({
                    "index": p_idx,
                    "name": param.name,
                    "normalized_value": val_norm,
                    "value": param.value
                })

            result = {
                "updated_parameters_count": len(updated_params_info),
                "details": updated_params_info
            }

            if errors:
                result["errors"] = errors

            return result
        except Exception as e:
            self.log_message("Error batch setting device parameters: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device.

        Uses the Live API device.type property:
        - 0 = undefined
        - 1 = instrument
        - 2 = audio_effect
        - 4 = midi_effect

        Also checks can_have_drum_pads/can_have_chains for rack subtypes.
        """
        # Check for rack subtypes first
        if device.can_have_drum_pads:
            return "drum_machine"
        if device.can_have_chains:
            return "rack"

        # Use the Live API type property
        device_type = device.type
        if device_type == 1:
            return "instrument"
        elif device_type == 2:
            return "audio_effect"
        elif device_type == 4:
            return "midi_effect"
        else:
            return "unknown"

    def _resolve_device(self, track_index, device_index, device_path=None):
        """
        Navigate to a device, handling nested racks.

        Args:
            track_index: Index of the track
            device_index: Index of the top-level device on the track
            device_path: Optional list for nested navigation.
                        Format: [chain_idx, device_idx, chain_idx, device_idx, ...]
                        Use negative values for drum pad notes (e.g., -36 for C1)

        Returns:
            The resolved device object

        Raises:
            IndexError: If any index is out of range
            ValueError: If device doesn't support chains/drum pads
        """
        track = self._get_track(track_index)

        # Validate device index
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index {0} out of range (0-{1}) on track '{2}'".format(
                device_index, len(track.devices) - 1, track.name))

        device = track.devices[device_index]

        # If no path, return the top-level device
        if not device_path:
            return device

        # Navigate the device path
        # Path format: [chain_idx, device_idx, chain_idx, device_idx, ...]
        # Negative chain_idx means drum pad note number
        i = 0
        while i < len(device_path):
            chain_idx = device_path[i]

            if chain_idx < 0:
                # Negative value = drum pad note number
                note = abs(chain_idx)
                if not device.can_have_drum_pads:
                    raise ValueError("Device '{0}' does not support drum pads".format(device.name))

                # Find the drum pad with this note
                pad = None
                for p in device.drum_pads:
                    if p.note == note:
                        pad = p
                        break

                if not pad:
                    raise IndexError("No drum pad found for note {0} in device '{1}'".format(
                        note, device.name))

                # Drum pads have chains, get the first chain's devices
                if not pad.chains or len(pad.chains) == 0:
                    raise ValueError("Drum pad for note {0} has no chains".format(note))

                # Get device index (next in path)
                if i + 1 >= len(device_path):
                    raise ValueError("device_path must have device index after drum pad note")

                dev_idx = device_path[i + 1]
                chain = pad.chains[0]  # Drum pads typically have one chain

                if dev_idx < 0 or dev_idx >= len(chain.devices):
                    raise IndexError("Device index {0} out of range (0-{1}) in drum pad {2}".format(
                        dev_idx, len(chain.devices) - 1, note))

                device = chain.devices[dev_idx]
                i += 2
            else:
                # Positive value = regular chain index
                if not device.can_have_chains:
                    raise ValueError("Device '{0}' does not support chains".format(device.name))

                if chain_idx >= len(device.chains):
                    raise IndexError("Chain index {0} out of range (0-{1}) in device '{2}'".format(
                        chain_idx, len(device.chains) - 1, device.name))

                # Get device index (next in path)
                if i + 1 >= len(device_path):
                    raise ValueError("device_path must have device index after chain index")

                dev_idx = device_path[i + 1]
                chain = device.chains[chain_idx]

                if dev_idx < 0 or dev_idx >= len(chain.devices):
                    raise IndexError("Device index {0} out of range (0-{1}) in chain '{2}'".format(
                        dev_idx, len(chain.devices) - 1, chain.name))

                device = chain.devices[dev_idx]
                i += 2

        return device

    def _get_device_tree(self, device):
        """Recursively build device tree including chains and drum pads."""
        try:
            node = {
                "name": device.name,
                "type": device.class_name
            }

            # Rack with chains (Instrument Rack, Audio Effect Rack, etc.)
            if device.can_have_chains and hasattr(device, 'chains') and device.chains:
                node["chains"] = []
                for chain in device.chains:
                    chain_node = {
                        "name": chain.name,
                        "devices": [self._get_device_tree(d) for d in chain.devices]
                    }
                    node["chains"].append(chain_node)

            # Drum Rack with pads
            if device.can_have_drum_pads and hasattr(device, 'drum_pads'):
                # Only include pads that have chains (i.e., have content)
                filled_pads = []
                for pad in device.drum_pads:
                    if hasattr(pad, 'chains') and pad.chains:
                        pad_node = {
                            "note": pad.note,
                            "name": pad.name,
                            "devices": []
                        }
                        for chain in pad.chains:
                            for d in chain.devices:
                                pad_node["devices"].append(self._get_device_tree(d))
                        if pad_node["devices"]:
                            filled_pads.append(pad_node)
                if filled_pads:
                    node["pads"] = filled_pads

            return node
        except Exception as e:
            self.log_message("Error in _get_device_tree: " + str(e))
            return {"name": device.name, "type": "error", "error": str(e)}

    @commands.register("get_session_tree")
    def get_session_tree(self):
        """Get a compact tree view of the entire session."""
        try:
            tree = {
                "tempo": self._song.tempo,
                "signature": "{0}/{1}".format(
                    self._song.signature_numerator,
                    self._song.signature_denominator
                ),
                "tracks": [],
                "returns": [],
                "scenes": []
            }

            # Tracks
            for i, track in enumerate(self._song.tracks):
                track_node = {
                    "id": i,
                    "name": track.name,
                    "type": "midi" if track.has_midi_input else "audio",
                    "mute": track.mute,
                    "solo": track.solo,
                    "arm": track.arm,
                    "clips": [],
                    "devices": []
                }

                # Clips (only those that exist)
                for j, slot in enumerate(track.clip_slots):
                    if slot.has_clip:
                        track_node["clips"].append({
                            "id": j,
                            "name": slot.clip.name,
                            "length": slot.clip.length
                        })

                # Devices (recursive)
                for device in track.devices:
                    track_node["devices"].append(self._get_device_tree(device))

                tree["tracks"].append(track_node)

            # Return tracks
            for i, ret in enumerate(self._song.return_tracks):
                ret_node = {
                    "id": i,
                    "name": ret.name,
                    "devices": [self._get_device_tree(d) for d in ret.devices]
                }
                tree["returns"].append(ret_node)

            # Scenes
            for i, scene in enumerate(self._song.scenes):
                tree["scenes"].append({
                    "id": i,
                    "name": scene.name
                })

            return tree
        except Exception as e:
            self.log_message("Error in get_session_tree: " + str(e))
            self.log_message(traceback.format_exc())
            raise
    
    @commands.register("get_browser_tree")
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    @commands.register("get_browser_items_at_path")
    def get_browser_items_at_path(self, path=""):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
