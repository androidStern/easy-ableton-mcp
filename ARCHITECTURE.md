# Architecture Overview: Easy Ableton MCP

## What This Project Does

**Easy Ableton MCP** is a Model Context Protocol (MCP) server that enables natural language control of Ableton Live through AI assistants like Claude. It translates conversational commands into precise music production actions, including MIDI manipulation, device control, and audio generation via ElevenLabs integration.

## Project Structure

```
easy-ableton-mcp/
├── MCP_Server/                         # Main MCP server (entry point for AI assistants)
│   ├── __init__.py                     # Package exports
│   └── server.py                       # FastMCP server implementation
│
├── AbletonMCP_Remote_Script/           # Ableton Live Remote Script (runs inside Ableton)
│   └── __init__.py                     # Control surface + TCP server (1062 lines)
│
├── Ableton-MCP_hybrid-server/          # Alternative high-performance implementation
│   └── AbletonMCP_UDP/
│       └── __init__.py                 # TCP + UDP hybrid for real-time control
│
├── elevenlabs_mcp/                     # Text-to-speech audio generation
│   ├── server.py                       # ElevenLabs MCP tools
│   ├── model.py                        # Pydantic data models
│   └── utils.py                        # Utility functions
│
├── experimental_tools/                 # Experimental utilities
│   └── xy_mouse_controller/            # Mouse-to-parameter mapping
│       └── mouse_parameter_controller_udp.py
│
├── pyproject.toml                      # Python project config
└── INSTALLATION.md                     # Setup guide
```

## Technology Stack

- **Python 3.10+**
- **FastMCP** (`mcp[cli]>=1.3.0`) - Model Context Protocol framework
- **ElevenLabs SDK** (`elevenlabs>=0.2.26`) - Text-to-speech API
- **Ableton Live API** - Via `_Framework.ControlSurface`

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AI Assistant (Claude)                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ MCP Protocol (stdio)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    MCP Server (MCP_Server/server.py)                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ FastMCP Tools: get_session_info, create_clip, add_notes,    │    │
│  │ load_instrument, get_browser_tree, fire_clip, etc.          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                       │
│                    AbletonConnection                                 │
│                    (TCP client, auto-reconnect)                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ TCP Socket (localhost:9877)
                                    │ JSON commands/responses
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Ableton Remote Script (runs inside Ableton)             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ ControlSurface subclass                                      │    │
│  │ • TCP server on port 9877                                    │    │
│  │ • Multi-threaded client handling                             │    │
│  │ • Command dispatch → schedule_message() → main thread        │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Ableton Live Object Model
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Ableton Live                                │
│   song.tempo, song.tracks[], clip.set_notes(), app.browser, etc.    │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. MCP Server (`MCP_Server/server.py`)

The entry point for AI assistants. Implements FastMCP tools that translate high-level commands into TCP JSON messages.

**Key Class: `AbletonConnection`**
- Manages persistent TCP socket to Ableton (localhost:9877)
- Auto-reconnect with 3 retry attempts
- Chunked message reassembly with 15s timeout
- Connection validation via `get_session_info` ping

**Exposed MCP Tools:**

| Category | Tools |
|----------|-------|
| Transport | `get_session_info`, `start_playback`, `stop_playback`, `set_tempo` |
| Tracks | `get_track_info`, `create_midi_track`, `set_track_name` |
| Clips | `create_clip`, `add_notes_to_clip`, `set_clip_name`, `fire_clip`, `stop_clip` |
| Devices | `load_instrument_or_effect`, `load_drum_kit` |
| Browser | `get_browser_tree`, `get_browser_items_at_path` |

### 2. Ableton Remote Script (`AbletonMCP_Remote_Script/__init__.py`)

Runs inside Ableton Live as a Control Surface. Receives JSON commands and executes them via the Ableton Live API.

**Architecture:**
- Inherits from `_Framework.ControlSurface`
- TCP server on port 9877 (allows 5 concurrent connections)
- Per-client handler with JSON buffering
- Thread-safe execution via `schedule_message()` for state modifications

**Command Processing Flow:**
```
Client JSON → TCP Server → _handle_client() → _process_command()
                                                      │
                          ┌───────────────────────────┴───────────────────────────┐
                          │                                                       │
                    Query commands                                    State-modifying commands
                    (immediate execution)                             (scheduled on main thread)
                          │                                                       │
                          ▼                                                       ▼
                    Return response                              schedule_message() → queue.get()
                                                                          │
                                                                          ▼
                                                                    Return response
```

### 3. Hybrid TCP/UDP Server (`Ableton-MCP_hybrid-server/`)

High-performance alternative for real-time parameter control.

- **TCP (port 9877):** Full command set, reliable delivery
- **UDP (port 9878):** Fire-and-forget parameter updates at 50+ Hz

Extended commands include: scene management, note editing (transpose, quantize, randomize), envelope control, audio import.

### 4. ElevenLabs Integration (`elevenlabs_mcp/`)

Text-to-speech audio generation for Ableton sessions.

- Generates MP3 files from text via ElevenLabs API
- Saves to `~/Documents/Ableton/User Library/eleven_labs_audio/`
- Files can be imported via browser URI: `query:UserLibrary#eleven_labs_audio:filename.mp3`

## Communication Protocol

### JSON Command Format
```json
{
  "type": "command_name",
  "params": {
    "track_index": 0,
    "clip_index": 0,
    "notes": [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100}]
  }
}
```

### JSON Response Format
```json
{
  "status": "success",
  "result": { /* command-specific data */ }
}
```

```json
{
  "status": "error",
  "message": "Track index out of range"
}
```

## Key Data Structures

### Session Info
```python
{
  "tempo": 120.0,
  "signature_numerator": 4,
  "signature_denominator": 4,
  "track_count": 8,
  "return_track_count": 2,
  "master_track": {"name": "Master", "volume": 0.85, "panning": 0.0}
}
```

### Track Info
```python
{
  "index": 0,
  "name": "MIDI Track",
  "is_midi_track": True,
  "mute": False, "solo": False, "arm": True,
  "volume": 0.85, "panning": 0.0,
  "clip_slots": [
    {"index": 0, "has_clip": True, "clip": {"name": "Clip 1", "length": 4.0, "is_playing": False}}
  ],
  "devices": [
    {"index": 0, "name": "Wavetable", "class_name": "PluginDevice", "type": "instrument"}
  ]
}
```

### MIDI Note
```python
{
  "pitch": 60,        # MIDI note number (0-127)
  "start_time": 0.0,  # Position in beats
  "duration": 1.0,    # Length in beats
  "velocity": 100,    # 0-127
  "mute": False
}
```

## Thread Safety Model

Ableton Live's API must be called from the main thread. The Remote Script handles this:

1. **Query commands** (read-only): Execute immediately in handler thread
2. **State-modifying commands**:
   - Handler thread calls `schedule_message(0, callback)`
   - Callback executes on main thread
   - Result passed back via `queue.Queue`
   - Handler thread blocks on `queue.get(timeout=10)`

## Connection Management

**MCP Server → Remote Script:**
- Single global `_ableton_connection` instance
- Lazy connection on first tool call
- Auto-reconnect with exponential backoff (3 attempts, 1s apart)
- Health check via `get_session_info` after reconnect

**Socket Configuration:**
- `SO_REUSEADDR` enabled
- 10-15s timeout depending on command type
- 8192 byte receive buffer
- Incremental JSON parsing for chunked data

## Browser Navigation

The Remote Script provides hierarchical access to Ableton's browser:

```
get_browser_tree("instruments")
       │
       ▼
┌────────────────────────────────────────┐
│ app.browser                            │
│   ├── instruments                      │
│   │   ├── Drift (uri: "Drift")         │
│   │   ├── Wavetable (uri: "Wavetable") │
│   │   └── Packs/                       │
│   │       └── ...                      │
│   ├── sounds                           │
│   ├── drums                            │
│   └── audio_effects                    │
└────────────────────────────────────────┘
```

**Device Loading:**
1. `load_instrument_or_effect(track_index, uri)` called
2. Remote Script recursively searches browser tree for URI (max depth 10)
3. Selects target track
4. Calls `app.browser.load_item(browser_item)`

## Error Handling

- **Fail fast:** Exceptions propagate immediately
- **Descriptive messages:** Error responses include context
- **No silent failures:** Every command returns success or error status
- **Timeout protection:** 10-15s limits prevent hanging

## Entry Points

| Component | How to Run |
|-----------|------------|
| MCP Server | `python -m MCP_Server.server` or via Claude Desktop config |
| Remote Script | Loaded by Ableton (Preferences → Control Surface → AbletonMCP) |
| UDP Hybrid | Alternative remote script installation |
| XY Controller | `python experimental_tools/xy_mouse_controller/mouse_parameter_controller_udp.py` |
| ElevenLabs MCP | `python -m elevenlabs_mcp` |

## Configuration

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "AbletonMCP": {
      "command": "python",
      "args": ["/path/to/easy-ableton-mcp/MCP_Server/server.py"]
    }
  }
}
```

### Environment Variables
- `ELEVENLABS_API_KEY` - ElevenLabs API key
- `ELEVENLABS_OUTPUT_DIR` - Custom output directory for generated audio
