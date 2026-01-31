# PRD: Ableton MCP Extended v2

## Goals

1. **Zero-config installation** - Users run one command; Remote Script is installed and Ableton preferences configured automatically
2. **Simplified TCP protocol** - Replace fragile JSON-parsing-as-framing with length-prefixed messages
3. **Lazy Ableton launch** - MCP server auto-launches Ableton on first tool call if not running

---

## Feature 1: Auto-Install

### Overview

Automatically install the Remote Script and configure Ableton preferences. No manual file copying or preference editing required.

### Requirements

1. Detect platform (macOS / Windows)
2. Symlink Remote Script to User Library (allows live development)
3. Backup `Preferences.cfg` before modification
4. Write control surface slot to preferences
5. Gracefully quit Ableton if running (prompt user to save)

### Constraints

- Preferences must be modified **while Ableton is closed**
- Script folder name must match the name written to preferences
- Script goes in `User Library/Remote Scripts/` (NOT `User Remote Scripts/` in Preferences folder)

### Platform Paths

| Platform | Remote Scripts | Preferences.cfg |
|----------|----------------|-----------------|
| macOS | `~/Music/Ableton/User Library/Remote Scripts/` | `~/Library/Preferences/Ableton/Live [Version]/Preferences.cfg` |
| Windows | `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\` | `%APPDATA%\Ableton\Live [Version]\Preferences.cfg` |

### Symlinks

- **macOS:** Native symlinks work. Tested with Live 11.3.43.
- **Windows:** Use directory junctions (`mklink /J`) - untested but expected to work.

### Preferences.cfg Binary Format

Custom binary serialization:

| Section | Description |
|---------|-------------|
| Header | `ab 1e 56 78` magic bytes + version info |
| Schema | Type definitions (`RemoteableString`, `RemoteableBool`, etc.) |
| Data | Values following schema order |

**String Encoding:**
- ASCII: 1-byte length prefix + ASCII bytes
- UTF-16LE: 4-byte length prefix (little-endian, char count) + UTF-16LE bytes

**Control Surface Slots:**
- 7 slots, each with 3 UTF-16LE strings: `(Script Name, Input Device, Output Device)`
- Empty slots use `"None"` as value
- Located after last `MidiOutDevicePreferences` marker

**Anchor Strategy:**
1. Find last occurrence of `MidiOutDevicePreferences` marker
2. Skip past its content (read strings until zero padding)
3. Skip zero padding bytes
4. Read 21 consecutive UTF-16LE strings (7 slots × 3 fields)

Validated on Live 11.3.42 and 11.3.43.

### Ableton Detection & Graceful Quit (macOS)

```bash
# Check if running
osascript -e 'tell application "System Events" to (name of processes) contains "Live"'

# Graceful quit (triggers save dialog)
osascript -e 'tell application id "com.ableton.live" to quit'
```

Notes:
- Process name is `"Live"` (not full app name)
- Bundle ID `com.ableton.live` works across Suite/Standard/Intro

### Implementation

```python
import struct
from pathlib import Path
import sys
import shutil
import subprocess


def is_ableton_running():
    """Check if Ableton Live is running (macOS)."""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Live"'],
            capture_output=True, text=True
        )
        return result.stdout.strip() == "true"
    elif sys.platform == "win32":
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Ableton Live*"], capture_output=True, text=True)
        return "Ableton Live" in result.stdout
    return False


def quit_ableton_gracefully():
    """Gracefully quit Ableton, prompting user to save (macOS)."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", 'tell application id "com.ableton.live" to quit'])
    elif sys.platform == "win32":
        # Send WM_CLOSE to window
        subprocess.run(["taskkill", "/IM", "Ableton Live*.exe"])


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
    """Find the offset where control surface slots begin."""
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


def set_control_surface(prefs_path, script_name, slot_index=None):
    """Set a control surface in Ableton preferences."""
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
    """Full installation: symlink script and configure preferences."""
    script_source = Path(script_source_path).resolve()
    if not script_source.exists():
        raise FileNotFoundError(f"Script source not found: {script_source}")

    # Step 0: Check if Ableton is running
    if is_ableton_running():
        print("Ableton Live is running. Requesting quit (you may be prompted to save)...")
        quit_ableton_gracefully()
        # Wait for quit
        import time
        for _ in range(30):  # 30 second timeout
            time.sleep(1)
            if not is_ableton_running():
                break
        else:
            raise RuntimeError("Ableton did not quit within 30 seconds")

    # Step 1: Symlink script to User Library
    remote_scripts_dir = find_user_library_remote_scripts()
    dest = remote_scripts_dir / script_name

    if dest.exists() or dest.is_symlink():
        if dest.is_symlink():
            dest.unlink()
        else:
            shutil.rmtree(dest)

    dest.symlink_to(script_source)
    print(f"Symlinked: {dest} -> {script_source}")

    # Step 2: Backup and modify preferences
    prefs_path = find_ableton_prefs_path()
    backup_path = prefs_path.with_suffix('.cfg.backup')
    shutil.copy2(prefs_path, backup_path)
    print(f"Backed up: {prefs_path} -> {backup_path}")

    slot = set_control_surface(prefs_path, script_name)
    print(f"Configured Control Surface slot {slot} as '{script_name}'")

    print("\nInstallation complete!")
    print("Start Ableton Live to use the MCP server.")
```

---

## Feature 2: TCP Simplification

### Overview

Replace JSON-parsing-as-framing with length-prefixed messages. Both MCP Server and Remote Script updated together.

### Current Problem

| Component | Total LOC | TCP LOC | TCP % | Root Cause |
|-----------|-----------|---------|-------|------------|
| MCP Server | 661 | 268 | 40% | JSON parsing as framing |
| Remote Script | 1063 | 173 | 16% | Same + Py2/3 compat |

### Solution: Length-Prefixed Framing

```python
import json

# Send: 4-byte length prefix (big-endian) + JSON
def send_message(sock, data):
    msg = json.dumps(data).encode('utf-8')
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


def recv_message(sock):
    length = int.from_bytes(recv_exact(sock, 4), 'big')
    data = recv_exact(sock, length)
    return json.loads(data.decode('utf-8'))
```

### Expected Impact

- Eliminates ~80 lines of fragile JSON-parsing-as-framing code
- Removes timeout-based completion detection
- Removes exception handling as control flow

### Rejected Alternatives

| Alternative | Why Not |
|-------------|---------|
| TypeScript rewrite | Doesn't solve the problem (protocol, not language) |
| gRPC | Won't work in Ableton's Python environment |
| WebSockets | Overkill for localhost IPC |
| Unix sockets | Windows incompatible |

---

## Feature 3: Lazy Ableton Launch

### Overview

MCP server automatically launches Ableton on first tool call if not already running. Supports both local use and remote operation (OpenClaw).

### Behavior

```
MCP server loads → does nothing with Ableton

User calls any Ableton tool (e.g., get_session_info)
  → Check if Ableton running
    → Yes → connect and execute
    → No → launch Ableton, wait for TCP ready, then execute
```

### Rationale

- MCP may be in config but user isn't always using Ableton tools
- Supports remote operation where user can't manually launch
- First-call latency is acceptable (one-time cost per session)

### Implementation (macOS)

```python
import subprocess
import time

def launch_ableton():
    """Launch Ableton Live (macOS)."""
    subprocess.run(["osascript", "-e", 'tell application id "com.ableton.live" to activate'])


def wait_for_tcp_ready(host="localhost", port=9877, timeout=30):
    """Wait for Remote Script TCP server to be ready."""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.create_connection((host, port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, socket.timeout):
            time.sleep(0.5)
    return False


def ensure_ableton_running():
    """Ensure Ableton is running and TCP server is ready."""
    if not is_ableton_running():
        print("Launching Ableton Live...")
        launch_ableton()
        if not wait_for_tcp_ready():
            raise RuntimeError("Ableton launched but TCP server not ready after 30s")
```

### Windows (Untested)

```python
# Detection
result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Ableton Live*"], capture_output=True, text=True)
is_running = "Ableton Live" in result.stdout

# Launch (requires finding exe path from registry or known locations)
subprocess.Popen([r"C:\ProgramData\Ableton\Live 11 Suite\Program\Ableton Live 11 Suite.exe"])
```

---

## Implementation Checklist

### Phase 1: Auto-Install
- [ ] Create `install.py` CLI tool
- [ ] Platform detection (macOS/Windows)
- [ ] Symlink creation (macOS: symlink, Windows: junction)
- [ ] Preferences.cfg backup
- [ ] Preferences.cfg modification
- [ ] Graceful Ableton quit if running
- [ ] Error handling with actionable messages

### Phase 2: TCP Simplification
- [ ] Add `send_message()` / `recv_message()` to MCP Server
- [ ] Add `send_message()` / `recv_message()` to Remote Script
- [ ] Remove old JSON-parsing-as-framing code
- [ ] Test with existing tools

### Phase 3: Lazy Launch
- [ ] Add `is_ableton_running()` check
- [ ] Add `launch_ableton()` function
- [ ] Add `wait_for_tcp_ready()` polling
- [ ] Integrate into connection flow
- [ ] Test cold-start scenario
