# Code Review Investigation

Investigation of issues identified in code review. Each issue has been verified with file:line references, code snippets, and relevant context.

---

## Critical Issues

### 1. Bare `except:` Clauses ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Lines 88, 205 → `except Exception:`. Line 197 → `except Exception as e:` + logging. Line 985 → Rewrote `_get_device_type()` to use Live API `device.type` property instead of string-matching heuristics.

**Locations**:

#### `AbletonMCP_Remote_Script/__init__.py:87-89`
```python
if self.server:
    try:
        self.server.close()
    except:
        pass
```

#### `AbletonMCP_Remote_Script/__init__.py:195-197`
```python
try:
    send_message(client, error_response)
except:
    # If we can't send the error, the connection is probably dead
    break
```

#### `AbletonMCP_Remote_Script/__init__.py:203-206`
```python
finally:
    try:
        client.close()
    except:
        pass
```

#### `AbletonMCP_Remote_Script/__init__.py:984-986`
```python
except:
    return "unknown"
```

**Problem**: Bare `except:` catches all exceptions including `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`. This:
- Prevents clean shutdown signals from propagating
- Masks actual errors (e.g., `MemoryError`, `RuntimeError`)
- Makes debugging difficult when something unexpected fails

**Context**: The Remote Script runs inside Ableton's embedded Python environment. While the intent is defensive coding for cleanup operations, bare `except:` can hide bugs and prevent proper shutdown behavior.

---

### 2. Monolithic `_process_command()` Method ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Replaced 149-line if-elif dispatch with decorator-based CommandRegistry. Added `@commands.register()` decorators to all handlers, extracted `_execute_on_main_thread()`, reduced `_process_command()` to 20 lines.

**Location**: `AbletonMCP_Remote_Script/__init__.py:209-358`

**Code Structure**:
```python
def _process_command(self, command):
    command_type = command.get("type", "")
    params = command.get("params", {})

    try:
        if command_type == "get_session_info":
            response["result"] = self._get_session_info()
        elif command_type == "get_track_info":
            # ...
        elif command_type in ["create_midi_track", "set_track_name", ...]:
            # ... 80 lines of nested elif inside main_thread_task ...
        elif command_type == "get_browser_item":
            # ...
        elif command_type == "get_browser_categories":
            # ...
        # ... 12+ more elif branches ...
        else:
            response["status"] = "error"
```

**Metrics**:
- Total lines: 149 lines (209-358)
- Top-level elif branches: 11
- Nested elif branches inside main_thread_task: 14
- Total command handlers: 25+

**Problems**:
1. Violates Single Responsibility Principle
2. Difficult to test individual command handlers
3. Adding new commands requires modifying this large function
4. Error handling is mixed with routing logic
5. The inner `main_thread_task()` function has its own 14 elif branches (lines 240-297)

---

### 3. Repetitive Tool Wrappers in server.py ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added `@ableton_command()` decorator that handles connection, send_command, error logging, and response formatting. Refactored 17 of 21 tools. Remaining 3 have complex custom logic (Issues #12, #15).

**Location**: `MCP_Server/server.py:181-671`

**Pattern observed across 21 tool functions**:
```python
@mcp.tool()
def tool_name(ctx: Context, param: type) -> str:
    """Docstring"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("command_name", {"param": param})
        return json.dumps(result, indent=2)  # or f-string message
    except Exception as e:
        logger.error(f"Error doing X: {str(e)}")
        return f"Error doing X: {str(e)}"
```

**Affected functions** (21 total):
- `get_session_info` (182-191)
- `get_session_tree` (192-207)
- `get_track_info` (208-223)
- `create_midi_track` (224-239)
- `set_track_name` (241-257)
- `create_clip` (258-279)
- `add_notes_to_clip` (280-306)
- `set_clip_name` (307-328)
- `set_tempo` (329-344)
- `load_instrument_or_effect` (346-375)
- `fire_clip` (376-395)
- `stop_clip` (396-415)
- `start_playback` (416-426)
- `stop_playback` (427-437)
- `get_browser_tree` (438-500)
- `get_browser_items_at_path` (501-541)
- `load_drum_kit` (542-590)
- `get_device_parameters` (591-617)
- `set_device_parameter` (618-645)
- `batch_set_device_parameters` (646-672)

**Problems**:
1. DRY violation - identical error handling in every function
2. Inconsistent return types (some return JSON, some return f-strings, some return both)
3. Changing error handling requires modifying 21 functions
4. No consistent error type hierarchy

---

### 4. Silent Default Parameters ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added `_require_param()` helper. Changed defaults from `0`/`""` to `None`. Added validation at handler start. 25 new tests in test_required_params.py.

**Location**: `AbletonMCP_Remote_Script/__init__.py:241-297`

**Examples**:
```python
# Line 241-242
index = params.get("index", -1)
result = self._create_midi_track(index)

# Line 244-246
track_index = params.get("track_index", 0)
name = params.get("name", "")
result = self._set_track_name(track_index, name)

# Line 248-251
track_index = params.get("track_index", 0)
clip_index = params.get("clip_index", 0)
length = params.get("length", 4.0)
result = self._create_clip(track_index, clip_index, length)
```

**Pattern repeats for**:
- `track_index` defaults to `0` (13 occurrences)
- `clip_index` defaults to `0` (6 occurrences)
- `device_index` defaults to `0` (4 occurrences)
- `name` defaults to `""` (3 occurrences)

**Problems**:
1. No way to distinguish "user passed 0" from "user forgot parameter"
2. Operations silently affect track 0 when track_index is omitted
3. Empty string names are silently accepted
4. Makes debugging harder when operations affect wrong track
5. Server-side (server.py) has typed parameters, but Remote Script accepts anything

---

## Error Handling Issues

### 5. Broad `except Exception` in Connection ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Replaced broad `except Exception` with specific socket exception handling:
- `ConnectionRefusedError` → return False (recoverable, retry)
- `socket.timeout` → return False (recoverable, retry)
- `OSError` → raise (unrecoverable, fail fast)
Also added 5-second connect timeout and `_cleanup_socket()` helper.

**Location**: `MCP_Server/server.py:25-60`

---

### 6. Generic Exception Raised ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added custom exception types:
- `AbletonCommandError` - Ableton returned an error status
- `AbletonResponseError` - Invalid/unparseable JSON response
- `ConnectionError` - Re-raised as-is (built-in, already descriptive)

**Location**: `MCP_Server/server.py:15-23` (definitions), `server.py:114-126` (usage)

---

### 7. `taskkill` Without Timeout on Windows ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added `timeout=10.0` to quit subprocess calls:
- `_quit_ableton_windows()`: taskkill now has 10s timeout
- `_quit_ableton_macos()`: osascript now has 10s timeout

**Location**: `MCP_Server/ableton_process.py:158-163`, `ableton_process.py:172-179`

---

### 8. Potential Division by Zero ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Extracted helper methods to eliminate duplicate normalization logic:
- `_normalize_param_value(param)` - convert actual value to 0.0-1.0
- `_denormalize_param_value(param, normalized)` - convert 0.0-1.0 to actual

Updated 3 call sites to use helpers.

**Location**: `AbletonMCP_Remote_Script/__init__.py:784-792`

---

### 9. Linear Search for Marker in preferences.py ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Replaced loop with single `rfind()` call - the canonical solution.

**Location**: `MCP_Server/preferences.py:182-198`

---

## Simplification Opportunities

### 10. Repeated Track Index Validation ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added helper methods:
- `_get_track(track_index)` - validates and returns track (9 call sites updated)
- `_get_clip_slot(track_index, clip_index)` - validates and returns clip slot (5 call sites updated)

**Location**: `AbletonMCP_Remote_Script/__init__.py:269-280`

---

### 11. Repeated Normalization Formula ✅ COMPLETE

**Status**: COMPLETE (fixed as part of Issue #8)

**Fix**: Extracted `_normalize_param_value()` and `_denormalize_param_value()` helpers.

---

### 12. Identical Browser Error-Checking ⏭️ SKIPPED

**Status**: SKIPPED

**Reason**: The user-friendly error messages ("Make sure Ableton Live is fully loaded...") provide valuable UX. Converting to @ableton_command decorator would lose these hints. Only 2 functions affected - not worth the UX regression.

---

### 13. Platform Detection Uncached ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Added `@lru_cache(maxsize=1)` to `get_platform()`.

**Location**: `MCP_Server/platform.py:43`

---

## Technical Debt

### 14. Global `_ableton_connection` is Thread-Unsafe ⏭️ SKIPPED

**Status**: SKIPPED

**Reason**: Failure mode is socket leak (orphaned connection) if two tool calls race at startup. Likelihood is low - requires exact timing. Real bottleneck is Ableton's main thread anyway. Not worth the complexity.

---

### 15. `load_drum_kit` Multi-Step Operation Should Be Atomic

**Status**: CONFIRMED

**Location**: `MCP_Server/server.py:542-590`

```python
@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    try:
        ableton = get_ableton_connection()

        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {...})

        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"

        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {...})

        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: ..."

        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]

        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found..."

        # Step 4: Load the first loadable kit
        ableton.send_command("load_browser_item", {...})

        return f"Loaded drum rack and kit..."
```

**Problems**:
1. Four separate network roundtrips to Ableton
2. If step 2, 3, or 4 fails, step 1 has already modified state (drum rack loaded)
3. No rollback mechanism if later steps fail
4. Partial success states are confusing ("Loaded drum rack but...")

**Ideal**: Single atomic command in Remote Script that performs all steps, with rollback on failure.

---

### 16. `get_browser_tree()` Creates Empty Children Array

**Status**: CONFIRMED

**Location**: `AbletonMCP_Remote_Script/__init__.py:1226-1241`

```python
def process_item(item, depth=0):
    if not item:
        return None

    result = {
        "name": item.name if hasattr(item, 'name') else "Unknown",
        "is_folder": hasattr(item, 'children') and bool(item.children),
        "is_device": hasattr(item, 'is_device') and item.is_device,
        "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
        "uri": item.uri if hasattr(item, 'uri') else None,
        "children": []  # <-- Created but never populated
    }


    return result
```

**Problem**:
- `children: []` is created on line 1237 but never populated
- The function returns immediately after creating the dict (lines 1240-1241)
- No recursion to process child items
- `is_folder` is set based on whether children exist, but the children array is always empty

**Context**: The `get_browser_items_at_path()` function properly iterates children (lines 1407-1417). The `get_browser_tree()` function appears incomplete.

---

### 17. Magic Number in preferences.py ✅ COMPLETE

**Status**: COMPLETE

**Fix**: Extracted `MIN_ZERO_PADDING_RUN = 8` constant with docstring explaining it's empirically determined.

**Location**: `MCP_Server/preferences.py:60-61`

---

## Summary

| Category | Count | Files Affected |
|----------|-------|----------------|
| Critical | 4 | Remote Script, server.py |
| Error Handling | 5 | server.py, ableton_process.py, Remote Script, preferences.py |
| Simplification | 4 | Remote Script, server.py, platform.py |
| Technical Debt | 4 | server.py, Remote Script, preferences.py |
| **Total** | **17** | **5 files** |

---

*Generated: 2026-01-31*
