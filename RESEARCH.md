# Full Research Report: Ableton MCP Extended Improvements

## 1. Auto-Install

### Key Findings

**Remote Script Paths** (for Python-based scripts):

| Platform | Path |
|----------|------|
| macOS | `~/Music/Ableton/User Library/Remote Scripts/` |
| Windows | `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\` |

**Preferences File:**

| Platform | Path |
|----------|------|
| macOS | `~/Library/Preferences/Ableton/Live [Version]/Preferences.cfg` |
| Windows | `%APPDATA%\Ableton\Live [Version]\Preferences.cfg` |

> **Note:** There's also a `User Remote Scripts` folder in the Preferences directory, but that's only for `UserConfiguration.txt`-based simple MIDI mappings, **not** Python control surface scripts.

### What CAN be automated (100%):
- Detect Ableton User Library path
- Copy Remote Script to `Remote Scripts/` folder
- Modify `Preferences.cfg` to enable the control surface
- Support multiple Live versions (11, 12, etc.)

### Preferences.cfg Format (Reverse-Engineered)

Ableton's Preferences.cfg is a custom binary serialization format:

**File Structure:**
1. **Header:** `ab 1e 56 78` magic bytes + version info
2. **Schema section:** Type definitions with ASCII markers (`RemoteableString`, `RemoteableBool`, etc.)
3. **Data section:** Actual values following the schema order

**String Encoding:**
- ASCII strings: 1-byte length prefix + ASCII bytes
- UTF-16LE strings: 4-byte length prefix (little-endian, char count) + UTF-16LE bytes

**Control Surface Slots:**
- 7 slots, each with 3 UTF-16LE strings: (Script Name, Input Device, Output Device)
- Located immediately after the last `MidiOutDevicePreferences` section
- Empty slots use `"None"` as the value

**Robust Anchor Strategy:**
1. Find last occurrence of `MidiOutDevicePreferences` marker
2. Skip past its content (read strings until hitting zero padding)
3. Skip zero padding bytes
4. Read 21 consecutive UTF-16LE strings (7 slots × 3 fields)

This approach was validated on Live 11.3.42 and 11.3.43 with different configurations.

### Python Code for Preferences Modification

```python
import struct
from pathlib import Path
import sys
import shutil


def find_ableton_prefs_path():
    """Find the Ableton Preferences.cfg file."""
    if sys.platform == "darwin":
        prefs_base = Path.home() / "Library/Preferences/Ableton"
    elif sys.platform == "win32":
        prefs_base = Path.home() / "AppData/Roaming/Ableton"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    if not prefs_base.exists():
        raise FileNotFoundError(f"Ableton preferences folder not found: {prefs_base}")

    # Find latest Live version
    versions = sorted([d for d in prefs_base.iterdir() if d.is_dir() and d.name.startswith("Live")])
    if not versions:
        raise FileNotFoundError("No Ableton Live versions found")

    latest = versions[-1]
    prefs_file = latest / "Preferences.cfg"
    if not prefs_file.exists():
        raise FileNotFoundError(f"Preferences.cfg not found: {prefs_file}")

    return prefs_file


def find_user_library_remote_scripts():
    """Find the User Library Remote Scripts folder."""
    if sys.platform == "darwin":
        user_library = Path.home() / "Music/Ableton/User Library"
    elif sys.platform == "win32":
        user_library = Path.home() / "Documents/Ableton/User Library"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    remote_scripts = user_library / "Remote Scripts"
    remote_scripts.mkdir(parents=True, exist_ok=True)
    return remote_scripts


def read_utf16_string(data, offset):
    """Read a length-prefixed UTF-16LE string from binary data."""
    length = struct.unpack_from('<I', data, offset)[0]
    string_bytes = data[offset + 4 : offset + 4 + length * 2]
    string = string_bytes.decode('utf-16-le')
    total_size = 4 + length * 2
    return string, total_size


def find_control_surface_start(data):
    """
    Find the offset where control surface slots begin.

    Strategy: Find last MidiOutDevicePreferences marker, skip past it,
    then control surface slots follow the zero padding.
    """
    marker = b'MidiOutDevicePreferences'

    # Find last occurrence
    idx = 0
    last_marker = -1
    while True:
        idx = data.find(marker, idx)
        if idx == -1:
            break
        last_marker = idx
        idx += 1

    if last_marker == -1:
        raise ValueError("Could not find MidiOutDevicePreferences marker")

    # Skip past marker and its content
    offset = last_marker + len(marker)

    # Skip any strings that follow (device preferences content)
    while offset < len(data) - 4:
        length = struct.unpack_from('<I', data, offset)[0]
        if length == 0:
            break
        elif 0 < length < 200:
            offset += 4 + length * 2
        else:
            offset += 1

    # Skip zero padding
    while offset < len(data) and data[offset] == 0:
        offset += 1

    return offset


def parse_control_surfaces(data):
    """Parse and return all 7 control surface slots."""
    offset = find_control_surface_start(data)

    slots = []
    for slot_num in range(7):
        name, name_size = read_utf16_string(data, offset)
        offset += name_size
        input_dev, input_size = read_utf16_string(data, offset)
        offset += input_size
        output_dev, output_size = read_utf16_string(data, offset)
        offset += output_size

        slots.append({
            'slot': slot_num + 1,
            'name': name,
            'input': input_dev,
            'output': output_dev
        })

    return slots


def set_control_surface(prefs_path, script_name, slot_index=None):
    """
    Set a control surface in Ableton preferences.

    Args:
        prefs_path: Path to Preferences.cfg
        script_name: Name of the control surface script (e.g., "AbletonMCP")
        slot_index: 0-based slot index, or None to use first empty slot

    Returns:
        The slot number (1-indexed) that was set
    """
    with open(prefs_path, 'rb') as f:
        data = bytearray(f.read())

    start_offset = find_control_surface_start(data)

    # Find target slot and collect offsets
    offset = start_offset
    target_slot = slot_index
    slot_offsets = []

    for i in range(7):
        slot_start = offset
        name, name_size = read_utf16_string(data, offset)
        offset += name_size
        input_dev, input_size = read_utf16_string(data, offset)
        offset += input_size
        output_dev, output_size = read_utf16_string(data, offset)
        offset += output_size

        slot_offsets.append({
            'index': i,
            'name_offset': slot_start,
            'name': name,
            'name_size': name_size
        })

        if target_slot is None and name == "None":
            target_slot = i

    if target_slot is None:
        raise ValueError("No empty control surface slot available")

    if target_slot < 0 or target_slot >= 7:
        raise ValueError(f"Invalid slot index: {target_slot}")

    # Modify the slot
    slot = slot_offsets[target_slot]
    old_size = slot['name_size']
    name_offset = slot['name_offset']

    new_length = len(script_name)
    new_bytes = struct.pack('<I', new_length) + script_name.encode('utf-16-le')
    new_size = len(new_bytes)

    # Splice new data
    new_data = bytearray()
    new_data.extend(data[:name_offset])
    new_data.extend(new_bytes)
    new_data.extend(data[name_offset + old_size:])

    with open(prefs_path, 'wb') as f:
        f.write(new_data)

    return target_slot + 1


def install_ableton_mcp(script_source_path, script_name="AbletonMCP"):
    """
    Full installation: copy script and configure preferences.
    """
    script_source = Path(script_source_path)
    if not script_source.exists():
        raise FileNotFoundError(f"Script source not found: {script_source}")

    # Step 1: Copy script to User Library
    remote_scripts_dir = find_user_library_remote_scripts()
    dest = remote_scripts_dir / script_name

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(script_source, dest)
    print(f"Copied script to: {dest}")

    # Step 2: Modify preferences
    prefs_path = find_ableton_prefs_path()
    slot = set_control_surface(prefs_path, script_name)
    print(f"Configured Control Surface {slot} as '{script_name}'")

    print("\nInstallation complete!")
    print("Please restart Ableton Live for changes to take effect.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Install AbletonMCP Remote Script")
    parser.add_argument("script_path", help="Path to the Remote Script folder")
    parser.add_argument("--name", default="AbletonMCP", help="Name for the control surface")
    args = parser.parse_args()

    install_ableton_mcp(args.script_path, args.name)
```

### Requirements for Success
1. Script must be in `User Library/Remote Scripts/` (not `User Remote Scripts/` in Preferences)
2. Preferences must be modified **while Ableton is closed**
3. Script folder name must match the name written to preferences

---

## 2. TCP Simplification [DECIDED]

### Decision

**Keep Python. Add length-prefixed framing to both sides.**

A TypeScript rewrite was considered but rejected. The complexity is not from Python—it's from using JSON parsing as the framing mechanism. The Ableton Remote Script must stay Python anyway, so a TypeScript MCP server would still need TCP communication to Python.

### Current Complexity

| Component | Total LOC | TCP LOC | TCP % | Root Cause |
|-----------|-----------|---------|-------|------------|
| MCP Server | 661 | 268 | 40% | JSON parsing as framing |
| Remote Script | 1063 | 173 | 16% | Same + Py2/3 compat |

### Solution: Length-Prefixed Framing

```python
# Send: 4-byte length prefix (big-endian) + JSON
msg = json.dumps(command).encode('utf-8')
sock.sendall(len(msg).to_bytes(4, 'big') + msg)

# Receive: read length, then exact bytes
def recv_exact(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Socket closed")
        data += chunk
    return data

length = int.from_bytes(recv_exact(sock, 4), 'big')
data = recv_exact(sock, length)
command = json.loads(data.decode('utf-8'))
```

### Expected Impact

- Eliminates ~80 lines of fragile JSON-parsing-as-framing code
- Removes timeout-based completion detection
- Removes exception handling as control flow
- Both sides (MCP Server + Remote Script) updated together

### Not Recommended

- **TypeScript rewrite**: Doesn't solve the actual problem (protocol, not language)
- **gRPC**: Won't work in Ableton's Python environment
- **WebSockets**: Overkill for localhost IPC
- **Unix sockets**: Windows incompatible

---

## 3. MCP Auto-Start

### Current Behavior
- Lazy connection on first tool call
- 3 retry attempts with 1s delays
- Returns error if Ableton not running

### Recommended: "Smart Lazy Launch"

```
Tool call → Check if Ableton running?
  → No → Auto-launch (configurable)
    → Wait 3-8s
    → Connect
  → Yes → Connect directly
```

**Platform-specific launch:**
- **macOS:** `osascript -e 'tell application "Ableton Live" to activate'`
- **Windows:** Registry lookup + `subprocess.Popen([exe_path])`

**Configuration via env vars:**
```bash
ABLETON_MCP_AUTO_LAUNCH=true
ABLETON_MCP_LAUNCH_TIMEOUT=8
```

**UX improvements:**
- Actionable error messages with diagnostic steps
- Automatic reconnection with exponential backoff
- Detect Ableton crashes and prompt user

---

## Summary: Implementation Roadmap

| Priority | Task | Status |
|----------|------|--------|
| 1 | Create `install.py` with path detection + file copy + preferences modification | Ready |
| 2 | Add length-prefixed framing to Python code (both sides) | **DECIDED** |
| 3 | Add auto-launch with platform detection | Ready |

## Open Questions

### Auto-Install
- [x] ~~Preferences.cfg parsing uses pattern-matching for known control surfaces—what if user has none configured?~~
  **RESOLVED:** New approach uses `MidiOutDevicePreferences` marker as anchor, which exists regardless of control surface configuration.

  **Validation results:**
  | Version | File Size | Anchor Found | Slots Parsed | Configured Surfaces |
  |---------|-----------|--------------|--------------|---------------------|
  | Live 11.3.42 | 21,566 bytes | ✓ 0x52dc | ✓ | 1 (Launchpad_X) |
  | Live 11.3.43 | 22,579 bytes | ✓ 0x56cd | ✓ | 2 (Launchpad_X, FANTOM) |

  Note: Could not find public Preferences.cfg files from other users to test. The binary format uses `ab1e5678` magic bytes and exists in Ableton-specific cfg files only.
- [x] ~~Symlink vs copy: symlink allows live development, but does Ableton follow symlinks on all platforms?~~
  **RESOLVED: Symlinks work on macOS.** Tested with Live 11.3.43 - Ableton discovers and lists symlinked Remote Scripts in the Control Surface dropdown. Windows untested (likely works with directory junctions via `mklink /J`).
- [x] ~~Should we backup Preferences.cfg before modifying?~~
  **DECIDED: Yes.** Always create `Preferences.cfg.backup` before any modifications. Non-negotiable for user safety.
- [x] ~~Should we validate the install worked by reading back the preferences?~~
  **DECIDED: No.** If modification fails, Ableton will show "None" in the control surface slot—fail-fast is sufficient.

### Auto-Start
- [x] ~~How to detect if Ableton is already running? (process name varies by platform/version)~~
  **RESOLVED: macOS approach confirmed.**

  **Detection:**
  ```bash
  osascript -e 'tell application "System Events" to (name of processes) contains "Live"'
  ```

  **Graceful quit (triggers save dialog if unsaved changes):**
  ```bash
  osascript -e 'tell application id "com.ableton.live" to quit'
  ```

  **Launch:**
  ```bash
  osascript -e 'tell application id "com.ableton.live" to activate'
  ```

  Notes:
  - Process name in System Events is `"Live"` (not full app name)
  - Bundle ID `com.ableton.live` works across all versions (Suite, Standard, Intro)
  - Graceful quit prompts user to save unsaved changes before closing
  - Windows: untested (likely `tasklist` for detection, `WM_CLOSE` message for graceful quit)

- [x] ~~Should auto-launch be opt-in or opt-out?~~
  **DECIDED: Lazy launch on first tool call.**

  - MCP server loads → does nothing with Ableton
  - User calls any Ableton tool → check if Ableton running
    - Yes → connect and execute
    - No → launch Ableton, wait for TCP ready, then execute

  **Implementation (macOS):** Use AppleScript for detection and launch:
  ```bash
  # Check if running
  osascript -e 'tell application "System Events" to (name of processes) contains "Live"'

  # Launch
  osascript -e 'tell application id "com.ableton.live" to activate'
  ```

  Rationale: MCP may be in config but user isn't always using Ableton tools. Also supports remote operation (OpenClaw) where user can't manually launch.
