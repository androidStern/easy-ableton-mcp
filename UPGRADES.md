# UPGRADES.md - Feature Gap Analysis

Comprehensive inventory of features in other Ableton MCP/control projects that easy-ableton-mcp lacks.

## Projects Analyzed

| Project | Tech | Stars | Key Strength |
|---------|------|-------|--------------|
| [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) | Python | - | Original MCP implementation |
| [itsuzef/ableton-mcp](https://github.com/itsuzef/ableton-mcp) | Python | - | Enhanced fork with device params |
| [xiaolaa2/ableton-copilot-mcp](https://github.com/xiaolaa2/ableton-copilot-mcp) | TypeScript | - | Operation history, rollback |
| [leolabs/ableton-js](https://github.com/leolabs/ableton-js) | TypeScript | - | Complete LOM bindings, events |
| [ideoforms/pylive](https://github.com/ideoforms/pylive) | Python/OSC | 606 | Mature, beat sync, caching |

---

## Current easy-ableton-mcp Capabilities

### What We Have (39 tools)
- `get_session_info` - tempo, signature, track count
- `get_session_tree` - full recursive tree with devices/chains/pads
- `get_track_info` - track details with clips and devices
- `create_midi_track` - create track at index
- `set_track_name` - rename track
- `set_track_volume` / `set_track_pan` - mixer controls
- `set_track_mute` / `set_track_solo` - mixer states
- `create_clip` - create MIDI clip
- `add_notes_to_clip` - add notes (Live 11+ API with MidiNoteSpecification)
- `get_notes_from_clip` - read notes with IDs
- `delete_notes_from_clip` - delete by ID
- `modify_clip_notes` - edit velocity, probability, etc.
- `transpose_notes_in_clip` - shift by semitones
- `quantize_notes_in_clip` - snap to grid
- `set_clip_name` - rename clip
- `fire_clip` / `stop_clip` - clip playback control
- `start_playback` / `stop_playback` - transport control
- `set_tempo` - tempo control
- `load_instrument_or_effect` - load by URI
- `load_drum_kit` - load drum rack + kit
- `get_browser_tree` / `get_browser_items_at_path` - browser navigation
- `get_device_parameters` - list all params on device
- `set_device_parameter` - set param by index (normalized 0-1)
- `batch_set_device_parameters` - set multiple params at once
- `get_clip_envelope` - check if automation exists
- `create_automation_envelope` - create envelope for parameter
- `insert_envelope_point` - add automation point
- `get_envelope_value_at_time` - read automation value
- `clear_clip_envelopes` - clear all automation from clip
- `get_scenes_info` - get all scene metadata ✅ NEW
- `create_scene` - create scene at index ✅ NEW
- `delete_scene` - delete scene ✅ NEW
- `set_scene_name` - rename scene ✅ NEW
- `fire_scene` - launch entire scene ✅ NEW

### What We're Missing

Priorities 6+ below.

---

## Priority 1: Device Parameter Control ✅ DONE

**Status: IMPLEMENTED** - get_device_parameters, set_device_parameter, batch_set_device_parameters

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `get_device_parameters` | itsuzef, ableton-js, pylive | List all params on a device |
| `set_device_parameter` | itsuzef, ableton-js, pylive | Set param by index/name |
| `batch_set_device_parameters` | itsuzef (hybrid) | Set multiple params at once |
| Navigate nested devices | itsuzef | Path-based device access in racks |

### API Pattern (from ableton-js)
```typescript
device.parameters  // Array of DeviceParameter
param.name         // "Frequency"
param.value        // 0.0-1.0 normalized
param.min / max    // Bounds
param.value = 0.5  // Settable
```

### Implementation Notes
- Parameters are normalized 0.0-1.0 across all devices
- Need device path navigation: `[device_idx, chain_idx, device_idx, ...]`
- EQ Eight has ~48 parameters (bands, frequencies, gains, Q values)

---

## Priority 2: MIDI Note Manipulation ✅ DONE

**Status: IMPLEMENTED** - get_notes_from_clip, delete_notes_from_clip, modify_clip_notes, transpose_notes_in_clip, quantize_notes_in_clip

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `get_notes_from_clip` | itsuzef, ableton-copilot, ableton-js | Query notes in clip |
| `delete_notes_from_clip` | itsuzef, ableton-copilot | Delete by ID or time/pitch range |
| `move_notes_in_clip` | ableton-copilot | Move notes by time/pitch offset |
| `modify_clip_notes` | ableton-copilot | Edit any note properties |
| `transpose_notes_in_clip` | itsuzef | Transpose by semitones |
| `quantize_notes_in_clip` | itsuzef, ableton-js | Snap to grid |
| `set_note_probability` | itsuzef, ableton-copilot | Note trigger probability |
| `duplicate_clip_region` | ableton-copilot, ableton-js | Copy notes to new location |

### Extended Note Format (Live 11+)
```python
{
    "note_id": 123,              # Unique ID for modification
    "pitch": 60,
    "start_time": 0.0,
    "duration": 0.5,
    "velocity": 100,
    "mute": False,
    "probability": 0.8,          # Note trigger probability (0.0-1.0)
    "release_velocity": 64,      # Note off velocity
    "velocity_deviation": 0.1    # Random velocity variation
}
```

### API Methods (Live 11+)
```python
# Get notes with IDs
notes = clip.get_notes_extended(from_time, from_pitch, time_span, pitch_span)

# Add notes (returns note IDs)
new_ids = clip.add_new_notes([note_spec, ...])

# Modify notes - only updates fields you specify
clip.apply_note_modifications([
    {"note_id": 123, "start_time": 2.0, "pitch": 64},  # move note
    {"note_id": 456, "velocity": 80, "probability": 0.5}  # change velocity & probability
])

# Delete specific notes
clip.remove_notes_by_id([note_id, ...])
```

### Implementation Examples
```python
def move_notes(self, track_index, clip_index, note_ids, time_offset=0, pitch_offset=0):
    """Move notes by ID."""
    clip = self._get_clip(track_index, clip_index)
    notes = clip.get_notes_extended(0, 0, clip.length, 128)

    clip.apply_note_modifications([
        {
            "note_id": n["note_id"],
            "start_time": n["start_time"] + time_offset,
            "pitch": n["pitch"] + pitch_offset
        }
        for n in notes if n["note_id"] in note_ids
    ])

def quantize_notes(self, track_index, clip_index, grid_size=0.25):
    """Quantize all notes to grid."""
    clip = self._get_clip(track_index, clip_index)
    notes = clip.get_notes_extended(0, 0, clip.length, 128)

    clip.apply_note_modifications([
        {
            "note_id": n["note_id"],
            "start_time": round(n["start_time"] / grid_size) * grid_size
        }
        for n in notes
    ])
```

---

## Priority 3: Automation & Envelopes ✅ DONE

**Status: IMPLEMENTED** - get_clip_envelope, create_automation_envelope, insert_envelope_point, get_envelope_value_at_time, clear_clip_envelopes

### Features Implemented

| Feature | Description |
|---------|-------------|
| `get_clip_envelope` | Check if automation exists for parameter |
| `create_automation_envelope` | Create envelope for parameter (required before insert) |
| `insert_envelope_point` | Add automation point (time, value, step_duration) |
| `get_envelope_value_at_time` | Read automation value at specific time |
| `clear_clip_envelopes` | Clear ALL automation from clip |

### API Pattern
```python
# Check if envelope exists
envelope_info = get_clip_envelope(track_index, clip_index, device_index, parameter_index)
# Returns: {has_envelope: true/false, parameter_name: "..."}

# Create envelope if needed
create_automation_envelope(track_index, clip_index, device_index, parameter_index)

# Add point (time in beats, value 0-1)
insert_envelope_point(track, clip, device, param, time=2.0, value=0.75)

# Read value
get_envelope_value_at_time(track, clip, device, param, time=2.0)

# Clear all automation from clip
clear_clip_envelopes(track, clip)
```

### Implementation Notes
- Envelopes are per-clip, per-parameter
- Must call `create_automation_envelope` before `insert_envelope_point` if envelope doesn't exist
- `insert_step` takes 3 args: (time, value, step_duration) - use 0.0 for single point
- `clear_clip_envelopes` clears ALL params, not just one (API limitation)
- Cannot read or modify existing envelope points (API limitation)

---

## Priority 4: Track Mixer Control

**Impact: MEDIUM** - Basic mixing capabilities.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `set_track_volume` | itsuzef, pylive | Set track fader (0-1) |
| `set_track_pan` | itsuzef, pylive | Set pan (-1 to 1) |
| `set_track_mute` | pylive | Mute on/off |
| `set_track_solo` | pylive | Solo on/off |
| `set_track_arm` | pylive | Record arm |
| `set_send_level` | pylive | Send to return track |
| Return track access | itsuzef, pylive | Control return tracks |
| Master track control | all | Master volume/pan |

### API Pattern
```python
track.volume = 0.85        # 0-1 normalized
track.pan = 0.0            # -1 (left) to 1 (right)
track.mute = False
track.solo = False
track.arm = True
track.send_a = 0.5         # Send level to return A
```

---

## Priority 5: Scene Management ✅ DONE

**Status: IMPLEMENTED** - get_scenes_info, create_scene, delete_scene, set_scene_name, fire_scene

### Features Implemented

| Feature | Description |
|---------|-------------|
| `get_scenes_info` | Get all scene metadata (index, name) |
| `create_scene` | Create new scene at index (-1 = end) |
| `delete_scene` | Delete scene by index |
| `set_scene_name` | Rename scene |
| `fire_scene` | Launch entire scene |

### Not Implemented

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `duplicate_scene` | ableton-js | Clone scene |

---

## Priority 6: Audio Track Features

**Impact: MEDIUM** - Audio workflow support.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `create_audio_track` | itsuzef, ableton-js | Create audio track |
| `import_audio_file` | itsuzef | Load audio from browser |
| `create_audio_clip` | ableton-copilot | Create clip from file |
| Audio clip properties | ableton-js | Warp mode, gain, pitch |
| Recording control | ableton-copilot | Start/stop recording |

### Audio Clip Properties
```python
clip.warping = True
clip.warp_mode = WarpMode.Beats  # Beats, Tones, Texture, Repitch, Complex
clip.gain = 0.0                  # dB
clip.pitch_coarse = 0            # Semitones
clip.pitch_fine = 0              # Cents
```

---

## Priority 7: Clip Properties & Loop Control

**Impact: MEDIUM** - Clip behavior customization.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `set_clip_loop_parameters` | itsuzef | Loop start/end/enabled |
| `set_clip_follow_action` | itsuzef | Follow action settings |
| `crop_clip` | ableton-copilot, ableton-js | Trim to loop/markers |
| `duplicate_clip_loop` | ableton-copilot, ableton-js | Double loop with content |
| Launch mode/quantization | ableton-js | Trigger/Gate/Toggle/Repeat |

### Clip Loop Properties
```python
clip.loop_start = 0.0      # In beats
clip.loop_end = 4.0        # In beats
clip.looping = True        # Enable loop
clip.start_marker = 0.0    # Warp start
clip.end_marker = 8.0      # Warp end
```

### Follow Actions
```python
# Set what happens after clip plays
set_clip_follow_action(
    track, clip,
    action="next",      # stop, again, previous, next, first, last, any, other
    chance=1.0,         # 0-1 probability
    time=4.0            # In beats
)
```

---

## Priority 8: Transport & Timing

**Impact: MEDIUM** - Playback control.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `get_current_time` | ableton-js, pylive | Current song position |
| `set_current_time` | ableton-js | Jump to position |
| `get_is_playing` | pylive | Check playback state |
| Metronome control | pylive | On/off |
| Quantization setting | pylive | Global launch quantize |
| Undo/Redo | ableton-js | `undo()`, `redo()` |
| Beat callbacks | pylive | Fire on each beat |
| Cue points | ableton-js | Navigate markers |

### Beat Synchronization (pylive)
```python
def on_beat(beat_number):
    # Do something every beat
    pass

set.add_beat_callback(on_beat)
set.wait_for_next_beat()
```

---

## Priority 9: Real-Time Performance (UDP)

**Impact: LOW-MEDIUM** - High-frequency control.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| UDP protocol | itsuzef (hybrid) | Fire-and-forget params |
| Batch parameter updates | itsuzef | Bundle multiple changes |
| Low-latency control | itsuzef | Sub-10ms response |
| XY Controller | itsuzef | Mouse-to-param mapping |

### Why UDP?
- TCP has overhead for acknowledgment
- Parameter changes at 50+ Hz need fire-and-forget
- Batch updates reduce network traffic

---

## Priority 10: State Management & History

**Impact: LOW-MEDIUM** - Undo/rollback for AI operations.

### Features Needed (ableton-copilot)

| Feature | Description |
|---------|-------------|
| Operation history DB | Log all tool executions |
| Snapshot system | Capture state before changes |
| Rollback by history ID | Revert to previous state |
| Performance metrics | Track operation timing |

### Implementation Pattern
```typescript
// Before modifying clip notes
snapshot = createNoteSnapshot(clip)
operationId = logOperation("add_notes", params)

// Execute
addNotes(clip, notes)

// On error or explicit rollback
rollbackByHistoryId(operationId)  // Restores from snapshot
```

---

## Priority 11: View & Selection Control

**Impact: LOW** - UI automation.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| Select track | ableton-js | `song.view.selected_track` |
| Select scene | ableton-js | `song.view.selected_scene` |
| Select clip | ableton-js | `song.view.detail_clip` |
| Select device | ableton-js | `song.view.selectDevice()` |
| Focus view | ableton-js | Session/Arranger/Browser |
| Scroll/zoom view | ableton-js | Navigate arrangement |

---

## Priority 12: Event Listeners

**Impact: LOW** - Reactive programming.

### Features Needed (ableton-js, pylive)

| Feature | Description |
|---------|-------------|
| Property change listeners | React to tempo, track changes |
| Parameter listeners | React to device param changes |
| Playback state listeners | React to start/stop |
| Beat listeners | Sync to timeline |
| MIDI input listeners | Capture MIDI in |

### Pattern (ableton-js)
```typescript
const unsubscribe = await song.addListener("tempo", (newTempo) => {
    console.log("Tempo changed:", newTempo)
})

// Later
unsubscribe()
```

---

## Priority 13: Application & Browser

**Impact: LOW** - Utility features.

### Features Needed

| Feature | Who Has It | Description |
|---------|------------|-------------|
| `get_application_info` | ableton-copilot | Live version, etc. |
| Preview browser item | ableton-js | Audition before loading |
| Stop preview | ableton-js | Stop audition |
| Hotswap target | ableton-js | What device is selected |
| Open Live set | pylive | Open .als file |

---

## Summary: Implementation Roadmap

### Phase 1: Core Gaps (High Impact)
1. ~~**Device Parameters**~~ ✅ DONE - get/set params on any device
2. ~~**MIDI Note Read/Edit**~~ ✅ DONE - get notes, delete, modify, transpose, quantize
3. ~~**Track Mixer**~~ ✅ DONE - volume, pan, mute, solo

### Phase 2: Creative Features
4. ~~**Automation**~~ ✅ DONE - create, insert, read, clear (cannot modify existing points)
5. ~~**Scene Management**~~ ✅ DONE - get info, create, delete, rename, fire
6. **Clip Properties** - loop, follow actions

### Phase 3: Audio & Polish
7. **Audio Tracks** - create, import files
8. **Transport** - current time, undo/redo
9. **Return Tracks** - full support

### Phase 4: Advanced
10. **UDP Protocol** - high-frequency control
11. **Event Listeners** - reactive updates
12. **Operation History** - undo/rollback

---

## Quick Reference: API Parity

| Feature | Us | ahujasid | itsuzef | copilot | ableton-js | pylive |
|---------|:--:|:--------:|:-------:|:-------:|:----------:|:------:|
| Get session info | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Get session tree | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Create MIDI track | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Create audio track | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Set track volume/pan | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| Set track mute/solo | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Create clip | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Add notes | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Get notes | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Delete notes | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Transpose notes | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Quantize notes | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Note probability | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Get device params | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Set device params | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Automation points | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Clear automation | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Scene management | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| Fire scene | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| Clip loop control | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Follow actions | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Load device by URI | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Browser preview | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Transport control | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Undo/Redo | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Cue points | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Beat callbacks | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Event listeners | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| UDP protocol | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Operation history | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Rollback | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Return tracks | partial | ❌ | ✅ | ❌ | ✅ | ✅ |

**Legend:** ✅ = Has it | ❌ = Missing | partial = Limited support

---

## Unique Strengths of easy-ableton-mcp

1. **get_session_tree** - No one else has this recursive full-session dump
2. **Automatic installation** - Symlink + Preferences.cfg binary editing
3. **Lazy launch** - Auto-start Ableton on first tool call
4. **Length-prefixed protocol** - Reliable framing (vs JSON lines)
5. **Cross-platform** - macOS + Windows support

These should be preserved and highlighted as differentiators.
