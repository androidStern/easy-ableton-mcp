# Command Dispatch Refactor Plan

## Problem Statement

`_process_command()` in `AbletonMCP_Remote_Script/__init__.py` is a 149-line function with:
- 25+ elif branches
- **Duplicated dispatch** - command list appears TWICE (once to check main-thread, once inside `main_thread_task` to dispatch)
- Mixed concerns - routing logic tangled with queue/scheduling logic

## Solution: Decorator Registry

A decorator-based command registry that:
1. Eliminates duplicated dispatch
2. Colocates metadata with handler definition
3. Simplifies adding new commands to a single touch-point
4. Ports cleanly to TypeScript (NestJS pattern)

## Components to Build

| Component | ~Lines | Purpose |
|-----------|--------|---------|
| `CommandRegistry` class | 35 | Module-level registry storing handlers + metadata |
| `_execute_on_main_thread()` | 25 | Encapsulates queue-based scheduling |
| `_process_command()` | 25 | Simplified dispatch using registry |

## Command Inventory

### Main Thread Commands (13) - require `schedule_message()`
```
create_midi_track
set_track_name
create_clip
add_notes_to_clip
set_clip_name
set_tempo
fire_clip
stop_clip
start_playback
stop_playback
load_browser_item
set_device_parameter
batch_set_device_parameters
```

### Direct Commands (9) - execute synchronously
```
get_session_info
get_track_info
get_browser_tree
get_browser_items_at_path
get_session_tree
get_device_parameters
get_browser_item
get_browser_categories
get_browser_items
```

## Implementation

### Step 1: CommandRegistry Class

```python
# At module level, before AbletonMCP class
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
```

### Step 2: Update Handler Signatures

Add defaults to all parameters so `handler(**params)` works:

```python
# Before
def _create_clip(self, track_index, clip_index, length):

# After
@commands.register("create_clip", main_thread=True)
def _create_clip(self, track_index=0, clip_index=0, length=4.0):
```

For mutable defaults (lists/dicts), use None pattern:
```python
@commands.register("add_notes_to_clip", main_thread=True)
def _add_notes_to_clip(self, track_index=0, clip_index=0, notes=None):
    if notes is None:
        notes = []
```

### Step 3: Extract `_execute_on_main_thread()`

```python
def _execute_on_main_thread(self, func):
    """Execute a function on the main thread and return result."""
    response_queue = queue.Queue()

    def task():
        try:
            result = func()
            response_queue.put({"status": "success", "result": result})
        except Exception as e:
            self.log_message("Error in main thread task: " + str(e))
            response_queue.put({"status": "error", "message": str(e)})

    try:
        self.schedule_message(0, task)
    except AssertionError:
        # Already on main thread
        task()

    try:
        return response_queue.get(timeout=10.0)
    except queue.Empty:
        return {"status": "error", "message": "Timeout waiting for operation"}
```

### Step 4: Simplified `_process_command()`

```python
def _process_command(self, command):
    """Process a command from the client."""
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
        return {"status": "error", "message": str(e)}
```

### Step 5: Add Decorators to All Handlers

```python
@commands.register("get_session_info")
def _get_session_info(self):
    ...

@commands.register("get_track_info")
def _get_track_info(self, track_index=0):
    ...

@commands.register("create_midi_track", main_thread=True)
def _create_midi_track(self, index=-1):
    ...

# ... etc for all 22 commands
```

## Handler Default Values Reference

| Command | Parameters with Defaults |
|---------|-------------------------|
| `get_session_info` | (none) |
| `get_track_info` | `track_index=0` |
| `get_browser_tree` | `category_type="all"` |
| `get_browser_items_at_path` | `path=""` |
| `get_session_tree` | (none) |
| `get_device_parameters` | `track_index=0, device_index=0, device_path=None` |
| `create_midi_track` | `index=-1` |
| `set_track_name` | `track_index=0, name=""` |
| `create_clip` | `track_index=0, clip_index=0, length=4.0` |
| `add_notes_to_clip` | `track_index=0, clip_index=0, notes=None` |
| `set_clip_name` | `track_index=0, clip_index=0, name=""` |
| `set_tempo` | `tempo=120.0` |
| `fire_clip` | `track_index=0, clip_index=0` |
| `stop_clip` | `track_index=0, clip_index=0` |
| `start_playback` | (none) |
| `stop_playback` | (none) |
| `load_browser_item` | `track_index=0, item_uri=""` |
| `set_device_parameter` | `track_index=0, device_index=0, parameter_index=0, value=0.0, device_path=None` |
| `batch_set_device_parameters` | `track_index=0, device_index=0, parameters=None, device_path=None` |

## Known Issues to Fix

1. **`load_instrument_or_effect`** - Listed in main-thread check (line 228) but has no handler dispatch. Dead code - remove from list.

2. **`get_browser_item`, `get_browser_categories`, `get_browser_items`** - Referenced in current elif but not in our test coverage. Verify handlers exist.

## Test Coverage

Tests in `tests/test_command_dispatch.py` cover:
- All 6 direct commands return success
- All 13 main-thread commands return success
- Direct commands skip `schedule_message`
- Main-thread commands use `schedule_message`
- Queue timeout behavior
- Error propagation
- Unknown command handling

**42 tests passing** - run before and after refactor to verify parity.

## Migration Steps

1. [ ] Add `CommandRegistry` class at module level
2. [ ] Add `_execute_on_main_thread()` method
3. [ ] Update handler signatures with defaults (one at a time)
4. [ ] Add `@commands.register()` decorator to each handler
5. [ ] Replace `_process_command()` with simplified version
6. [ ] Run tests - verify 42 pass
7. [ ] Remove dead code (`load_instrument_or_effect` reference)
8. [ ] Delete old `_process_command()` implementation

## TypeScript Equivalent (for future port)

```typescript
function command(name: string, options: { mainThread?: boolean } = {}) {
  return function (target: any, key: string, descriptor: PropertyDescriptor) {
    COMMAND_REGISTRY.set(name, {
      name,
      mainThread: options.mainThread ?? false,
      handler: descriptor.value,
    });
    return descriptor;
  };
}

class AbletonMCP {
  @command("get_session_info")
  getSessionInfo() { ... }

  @command("create_midi_track", { mainThread: true })
  createMidiTrack(index = -1) { ... }
}
```

Requires `experimentalDecorators: true` in tsconfig.json.
