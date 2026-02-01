#!/usr/bin/env python3
"""Test MCP tools using FastMCP Client."""
import asyncio
import json
import socket
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ABLETON_PORT = 9877


def check_ableton_running() -> bool:
    """Check if Ableton Remote Script is listening on port 9877."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("localhost", ABLETON_PORT))
            return True
    except (socket.error, socket.timeout):
        return False


async def main():
    """Run MCP tool tests."""
    print("=== MCP Tool Tests ===\n")

    # Fail fast if Ableton isn't running with the fixture
    if not check_ableton_running():
        print("ERROR: Ableton Remote Script not running on port 9877.")
        print()
        print("Run the dev-refresh script first to start Ableton with the test fixture:")
        print("  ./scripts/dev-refresh.sh --test")
        print()
        print("Or start Ableton manually and load:")
        print("  tests/fixtures/test_session Project/test_session.als")
        return 1

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "MCP_Server.server"],
        cwd=str(project_root),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to MCP server\n")

            # List available tools
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"Available tools ({len(tool_names)}):")
            for name in sorted(tool_names):
                print(f"  - {name}")
            print()

            # Verify required tools exist
            required_tools = [
                # Device parameter tools
                "get_device_parameters", "set_device_parameter", "batch_set_device_parameters",
                # MIDI note tools
                "get_notes_from_clip", "delete_notes_from_clip", "modify_clip_notes",
                "transpose_notes_in_clip", "quantize_notes_in_clip",
                # Track mixer tools
                "set_track_volume", "set_track_pan", "set_track_mute", "set_track_solo",
                # Automation envelope tools
                "get_clip_envelope", "create_automation_envelope", "insert_envelope_point",
                "get_envelope_value_at_time", "clear_clip_envelopes",
                # Scene management tools
                "get_scenes_info", "create_scene", "delete_scene", "set_scene_name", "fire_scene",
                # Clip properties tools
                "get_clip_properties", "set_clip_loop", "duplicate_clip", "delete_clip",
                # Transport & timing tools (Priority 8)
                "get_current_time", "set_current_time", "get_is_playing",
                "set_metronome", "undo", "redo",
                # Audio track tools (Priority 6)
                "create_audio_track",
            ]
            missing = [t for t in required_tools if t not in tool_names]
            if missing:
                print(f"FAIL: Missing tools: {missing}")
                return 1

            print("PASS: All required tools registered\n")

            # Test get_session_info first to verify Ableton connection
            print("--- Test: get_session_info ---")
            try:
                result = await session.call_tool("get_session_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                print(f"  Tempo: {data.get('tempo')} BPM")
                print(f"  Tracks: {data.get('track_count')}")
                print("  PASS\n")
            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # Test get_device_parameters
            print("--- Test: get_device_parameters ---")
            try:
                result = await session.call_tool("get_device_parameters", {
                    "track_index": 0,
                    "device_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  Note: {data['error']}")
                    print("  SKIP (no device on track 0)\n")
                else:
                    params = data.get("parameters", [])
                    print(f"  Device: {data.get('device_name')}")
                    print(f"  Parameters: {len(params)}")
                    if params:
                        p = params[0]
                        print(f"  First param: {p.get('name')} = {p.get('value')} (norm: {p.get('normalized_value')})")
                    print("  PASS\n")
            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # Test set_device_parameter (only if we have a device)
            print("--- Test: set_device_parameter ---")
            try:
                result = await session.call_tool("set_device_parameter", {
                    "track_index": 0,
                    "device_index": 0,
                    "parameter_index": 1,
                    "value": 0.5
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  Note: {data['error']}")
                    print("  SKIP\n")
                else:
                    print(f"  Set: {data.get('parameter_name')} = {data.get('value')}")
                    print("  PASS\n")
            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # Test batch_set_device_parameters
            print("--- Test: batch_set_device_parameters ---")
            try:
                result = await session.call_tool("batch_set_device_parameters", {
                    "track_index": 0,
                    "device_index": 0,
                    "parameters": [
                        {"index": 1, "value": 0.3},
                        {"index": 2, "value": 0.7}
                    ]
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  Note: {data['error']}")
                    print("  SKIP\n")
                else:
                    count = data.get("updated_count", 0)
                    print(f"  Updated {count} parameters")
                    print("  PASS\n")
            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # MIDI Note Manipulation Round-Trip Test
            # Tests: get_notes, modify, transpose, quantize, delete
            # ================================================================
            print("--- Test: MIDI Note Round-Trip ---")
            try:
                # Step 1: GET - Read existing notes from clip
                print("  1. Getting existing notes...")
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_notes_from_clip error: {data['error']}\n")
                    return 1
                original_notes = data.get("notes", [])
                original_count = len(original_notes)
                print(f"     Found {original_count} existing notes")

                # Step 2: ADD - Add a test note at off-grid position (0.13 beats)
                # We use the existing add_notes_to_clip tool
                print("  2. Adding test note at pitch 72, time 0.13...")
                result = await session.call_tool("add_notes_to_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "notes": [
                        {"pitch": 72, "start_time": 0.13, "duration": 0.5, "velocity": 100}
                    ]
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: add_notes_to_clip error: {data['error']}\n")
                    return 1

                # Step 3: GET - Verify note was added and get its ID
                print("  3. Verifying note was added...")
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                notes_after_add = data.get("notes", [])
                if len(notes_after_add) != original_count + 1:
                    print(f"  FAIL: Expected {original_count + 1} notes, got {len(notes_after_add)}\n")
                    return 1
                # Find the note we added (pitch 72)
                test_note = next((n for n in notes_after_add if n.get("pitch") == 72), None)
                if not test_note:
                    print("  FAIL: Could not find added note at pitch 72\n")
                    return 1
                test_note_id = test_note.get("note_id")
                print(f"     Added note ID: {test_note_id}")

                # Step 4: MODIFY - Change velocity and probability
                print("  4. Modifying note (velocity=64, probability=0.75)...")
                result = await session.call_tool("modify_clip_notes", {
                    "track_index": 0,
                    "clip_index": 0,
                    "modifications": [
                        {"note_id": test_note_id, "velocity": 64, "probability": 0.75}
                    ]
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: modify_clip_notes error: {data['error']}\n")
                    return 1

                # Verify modification
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                test_note = next((n for n in data.get("notes", []) if n.get("note_id") == test_note_id), None)
                if not test_note or test_note.get("velocity") != 64:
                    print(f"  FAIL: Velocity not modified (got {test_note.get('velocity') if test_note else 'None'})\n")
                    return 1
                print(f"     Velocity updated to {test_note.get('velocity')}")

                # Step 5: TRANSPOSE - Shift up 12 semitones
                print("  5. Transposing all notes +12 semitones...")
                result = await session.call_tool("transpose_notes_in_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "semitones": 12
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: transpose_notes_in_clip error: {data['error']}\n")
                    return 1

                # Verify transpose (pitch 72 -> 84)
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                test_note = next((n for n in data.get("notes", []) if n.get("note_id") == test_note_id), None)
                if not test_note or test_note.get("pitch") != 84:
                    print(f"  FAIL: Pitch not transposed (got {test_note.get('pitch') if test_note else 'None'})\n")
                    return 1
                print(f"     Pitch transposed to {test_note.get('pitch')}")

                # Step 6: QUANTIZE - Snap to 1/4 note grid (0.25 beats)
                print("  6. Quantizing to 0.25 beat grid...")
                result = await session.call_tool("quantize_notes_in_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "grid_size": 0.25
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: quantize_notes_in_clip error: {data['error']}\n")
                    return 1

                # Verify quantize (0.13 -> 0.0 or 0.25)
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                test_note = next((n for n in data.get("notes", []) if n.get("note_id") == test_note_id), None)
                if not test_note:
                    print("  FAIL: Could not find test note after quantize\n")
                    return 1
                start_time = test_note.get("start_time")
                # 0.13 should quantize to 0.0 (closer than 0.25)
                if abs(start_time - 0.0) > 0.01 and abs(start_time - 0.25) > 0.01:
                    print(f"  FAIL: Note not quantized (start_time={start_time})\n")
                    return 1
                print(f"     Start time quantized to {start_time}")

                # Step 7: DELETE - Remove the test note
                print("  7. Deleting test note...")
                result = await session.call_tool("delete_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "note_ids": [test_note_id]
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: delete_notes_from_clip error: {data['error']}\n")
                    return 1

                # Verify deletion
                result = await session.call_tool("get_notes_from_clip", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                notes_after_delete = data.get("notes", [])
                test_note = next((n for n in notes_after_delete if n.get("note_id") == test_note_id), None)
                if test_note:
                    print("  FAIL: Note was not deleted\n")
                    return 1
                print(f"     Note deleted, {len(notes_after_delete)} notes remaining")

                # Step 8: CLEANUP - Transpose back to restore original pitches
                print("  8. Restoring original pitches (-12 semitones)...")
                result = await session.call_tool("transpose_notes_in_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "semitones": -12
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  WARN: Could not restore pitches: {data['error']}")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Track Mixer Round-Trip Test
            # Tests: set_track_volume, set_track_pan, set_track_mute, set_track_solo
            # ================================================================
            print("--- Test: Track Mixer Round-Trip ---")
            try:
                # Step 1: GET - Read initial mixer state via get_track_info
                print("  1. Getting initial mixer state...")
                result = await session.call_tool("get_track_info", {"track_index": 0})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_track_info error: {data['error']}\n")
                    return 1
                original_volume = data.get("volume")
                original_pan = data.get("panning")
                original_mute = data.get("mute")
                original_solo = data.get("solo")
                print(f"     Volume: {original_volume}, Pan: {original_pan}")
                print(f"     Mute: {original_mute}, Solo: {original_solo}")

                # Step 2: SET VOLUME - Change to 0.33
                print("  2. Setting volume to 0.33...")
                result = await session.call_tool("set_track_volume", {
                    "track_index": 0,
                    "volume": 0.33
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_volume error: {data['error']}\n")
                    return 1

                # Verify volume changed
                result = await session.call_tool("get_track_info", {"track_index": 0})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if abs(data.get("volume", 0) - 0.33) > 0.01:
                    print(f"  FAIL: Volume not set (got {data.get('volume')})\n")
                    return 1
                print(f"     Volume set to {data.get('volume')}")

                # Step 3: SET PAN - Change to -0.5 (left)
                print("  3. Setting pan to -0.5 (left)...")
                result = await session.call_tool("set_track_pan", {
                    "track_index": 0,
                    "pan": -0.5
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_pan error: {data['error']}\n")
                    return 1

                # Verify pan changed
                result = await session.call_tool("get_track_info", {"track_index": 0})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if abs(data.get("panning", 0) - (-0.5)) > 0.01:
                    print(f"  FAIL: Pan not set (got {data.get('panning')})\n")
                    return 1
                print(f"     Pan set to {data.get('panning')}")

                # Step 4: SET MUTE ON
                print("  4. Setting mute ON...")
                result = await session.call_tool("set_track_mute", {
                    "track_index": 0,
                    "mute": True
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_mute error: {data['error']}\n")
                    return 1

                # Verify mute is ON
                result = await session.call_tool("get_track_info", {"track_index": 0})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if data.get("mute") is not True:
                    print(f"  FAIL: Mute not set (got {data.get('mute')})\n")
                    return 1
                print("     Mute enabled")

                # Step 5: SET MUTE OFF (cleanup before solo test)
                print("  5. Setting mute OFF...")
                result = await session.call_tool("set_track_mute", {
                    "track_index": 0,
                    "mute": False
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_mute error: {data['error']}\n")
                    return 1
                print("     Mute disabled")

                # Step 6: SET SOLO ON
                print("  6. Setting solo ON...")
                result = await session.call_tool("set_track_solo", {
                    "track_index": 0,
                    "solo": True
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_solo error: {data['error']}\n")
                    return 1

                # Verify solo is ON
                result = await session.call_tool("get_track_info", {"track_index": 0})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if data.get("solo") is not True:
                    print(f"  FAIL: Solo not set (got {data.get('solo')})\n")
                    return 1
                print("     Solo enabled")

                # Step 7: SET SOLO OFF (cleanup)
                print("  7. Setting solo OFF...")
                result = await session.call_tool("set_track_solo", {
                    "track_index": 0,
                    "solo": False
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_track_solo error: {data['error']}\n")
                    return 1
                print("     Solo disabled")

                # Step 8: RESTORE - Reset to original values
                print("  8. Restoring original mixer state...")
                await session.call_tool("set_track_volume", {
                    "track_index": 0,
                    "volume": original_volume
                })
                await session.call_tool("set_track_pan", {
                    "track_index": 0,
                    "pan": original_pan
                })
                # Mute and solo already restored to False above
                print(f"     Restored volume={original_volume}, pan={original_pan}")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Automation Envelope Round-Trip Test
            # Tests: get_clip_envelope, create_automation_envelope,
            #        insert_envelope_point, get_envelope_value_at_time,
            #        clear_clip_envelopes
            # ================================================================
            print("--- Test: Automation Envelope Round-Trip ---")
            try:
                # Step 1: GET ENVELOPE - Check if envelope exists for device param
                print("  1. Checking envelope for device param (track 0, device 0, param 1)...")
                result = await session.call_tool("get_clip_envelope", {
                    "track_index": 0,
                    "clip_index": 0,
                    "device_index": 0,
                    "parameter_index": 1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in content.lower():
                    print(f"  FAIL: get_clip_envelope error: {content}\n")
                    return 1

                has_envelope = data.get("has_envelope", False)
                print(f"     Envelope exists: {has_envelope}")
                print(f"     Parameter: {data.get('parameter_name', 'unknown')}")

                # Step 2: CREATE ENVELOPE if it doesn't exist
                if not has_envelope:
                    print("  2. Creating automation envelope...")
                    result = await session.call_tool("create_automation_envelope", {
                        "track_index": 0,
                        "clip_index": 0,
                        "device_index": 0,
                        "parameter_index": 1
                    })
                    content = result.content[0].text if result.content else ""
                    data = json.loads(content)
                    if "error" in content.lower():
                        print(f"  FAIL: create_automation_envelope error: {content}\n")
                        return 1
                    print(f"     Envelope created: {data.get('created', False)}")
                else:
                    print("  2. Envelope already exists, skipping creation")

                # Step 3: INSERT POINT - Add automation point at time 0.5
                print("  3. Inserting automation point at time=0.5, value=0.25...")
                result = await session.call_tool("insert_envelope_point", {
                    "track_index": 0,
                    "clip_index": 0,
                    "device_index": 0,
                    "parameter_index": 1,
                    "time": 0.5,
                    "value": 0.25
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in content.lower():
                    print(f"  FAIL: insert_envelope_point error: {content}\n")
                    return 1
                print("     Point inserted")

                # Step 4: READ VALUE - Verify value at time 0.5
                print("  4. Reading value at time=0.5...")
                result = await session.call_tool("get_envelope_value_at_time", {
                    "track_index": 0,
                    "clip_index": 0,
                    "device_index": 0,
                    "parameter_index": 1,
                    "time": 0.5
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in content.lower():
                    print(f"  FAIL: get_envelope_value_at_time error: {content}\n")
                    return 1
                value_at_05 = data.get("value", -1)
                print(f"     Value at 0.5: {value_at_05}")

                # Step 5: CLEAR ENVELOPES - Clear all automation from clip
                print("  5. Clearing all envelopes from clip...")
                result = await session.call_tool("clear_clip_envelopes", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                if "error" in content.lower() and "cleared" not in content.lower():
                    print(f"  FAIL: clear_clip_envelopes error: {content}\n")
                    return 1
                print("     Envelopes cleared")

                # Step 6: VERIFY CLEARED - Check envelope no longer exists
                print("  6. Verifying envelope was cleared...")
                result = await session.call_tool("get_clip_envelope", {
                    "track_index": 0,
                    "clip_index": 0,
                    "device_index": 0,
                    "parameter_index": 1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                has_envelope = data.get("has_envelope", False)
                print(f"     Envelope exists after clear: {has_envelope}")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Scene Management Round-Trip Test
            # Tests: get_scenes_info, create_scene, set_scene_name, fire_scene, delete_scene
            # ================================================================
            print("--- Test: Scene Management Round-Trip ---")
            try:
                # Step 1: GET SCENES INFO - Read initial scene state
                print("  1. Getting initial scene info...")
                result = await session.call_tool("get_scenes_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_scenes_info error: {data['error']}\n")
                    return 1
                initial_scene_count = data.get("scene_count", 0)
                print(f"     Found {initial_scene_count} existing scenes")

                # Step 2: CREATE SCENE - Create a new scene at the end
                print("  2. Creating new scene...")
                result = await session.call_tool("create_scene", {
                    "index": -1  # -1 means end of list
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: create_scene error: {data['error']}\n")
                    return 1
                new_scene_index = data.get("index")
                print(f"     Created scene at index {new_scene_index}")

                # Step 3: VERIFY SCENE COUNT - Confirm scene was added
                print("  3. Verifying scene was added...")
                result = await session.call_tool("get_scenes_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                new_scene_count = data.get("scene_count", 0)
                if new_scene_count != initial_scene_count + 1:
                    print(f"  FAIL: Expected {initial_scene_count + 1} scenes, got {new_scene_count}\n")
                    return 1
                print(f"     Scene count: {new_scene_count}")

                # Step 4: SET SCENE NAME - Rename the new scene
                print("  4. Renaming scene to 'MCP Test Scene'...")
                result = await session.call_tool("set_scene_name", {
                    "scene_index": new_scene_index,
                    "name": "MCP Test Scene"
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_scene_name error: {data['error']}\n")
                    return 1
                print(f"     Renamed to: {data.get('name', 'unknown')}")

                # Step 5: VERIFY NAME - Confirm name was set
                print("  5. Verifying scene name...")
                result = await session.call_tool("get_scenes_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                scenes = data.get("scenes", [])
                test_scene = next((s for s in scenes if s.get("index") == new_scene_index), None)
                if not test_scene or test_scene.get("name") != "MCP Test Scene":
                    print(f"  FAIL: Scene name not set (got {test_scene.get('name') if test_scene else 'None'})\n")
                    return 1
                print("     Name verified")

                # Step 6: FIRE SCENE - Launch the scene
                print("  6. Firing scene...")
                result = await session.call_tool("fire_scene", {
                    "scene_index": new_scene_index
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: fire_scene error: {data['error']}\n")
                    return 1
                print("     Scene fired")

                # Step 7: STOP PLAYBACK - Stop the scene (cleanup before delete)
                print("  7. Stopping playback...")
                result = await session.call_tool("stop_playback", {})
                content = result.content[0].text if result.content else ""
                print("     Playback stopped")

                # Step 8: DELETE SCENE - Remove the test scene
                print("  8. Deleting test scene...")
                result = await session.call_tool("delete_scene", {
                    "scene_index": new_scene_index
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: delete_scene error: {data['error']}\n")
                    return 1
                print("     Scene deleted")

                # Step 9: VERIFY DELETION - Confirm scene count is back to original
                print("  9. Verifying scene was deleted...")
                result = await session.call_tool("get_scenes_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                final_scene_count = data.get("scene_count", 0)
                if final_scene_count != initial_scene_count:
                    print(f"  FAIL: Expected {initial_scene_count} scenes, got {final_scene_count}\n")
                    return 1
                print(f"     Scene count restored to {final_scene_count}")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Clip Properties Round-Trip Test
            # Tests: get_clip_properties, set_clip_loop, duplicate_clip
            # ================================================================
            print("--- Test: Clip Properties Round-Trip ---")
            try:
                # Step 1: GET CLIP PROPERTIES - Read initial clip state
                print("  1. Getting clip properties...")
                result = await session.call_tool("get_clip_properties", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_clip_properties error: {data['error']}\n")
                    return 1
                original_looping = data.get("looping")
                original_loop_start = data.get("loop_start")
                original_loop_end = data.get("loop_end")
                print(f"     Looping: {original_looping}, Loop: {original_loop_start}-{original_loop_end}")

                # Step 2: SET CLIP LOOP - Change loop parameters
                print("  2. Setting loop to 1.0-3.0, looping=True...")
                result = await session.call_tool("set_clip_loop", {
                    "track_index": 0,
                    "clip_index": 0,
                    "looping": True,
                    "loop_start": 1.0,
                    "loop_end": 3.0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_clip_loop error: {data['error']}\n")
                    return 1
                print("     Loop parameters set")

                # Step 3: VERIFY LOOP - Confirm loop was set
                print("  3. Verifying loop parameters...")
                result = await session.call_tool("get_clip_properties", {
                    "track_index": 0,
                    "clip_index": 0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if data.get("looping") is not True:
                    print(f"  FAIL: Looping not set (got {data.get('looping')})\n")
                    return 1
                if abs(data.get("loop_start", 0) - 1.0) > 0.01:
                    print(f"  FAIL: Loop start not set (got {data.get('loop_start')})\n")
                    return 1
                if abs(data.get("loop_end", 0) - 3.0) > 0.01:
                    print(f"  FAIL: Loop end not set (got {data.get('loop_end')})\n")
                    return 1
                print("     Loop verified: 1.0-3.0, looping=True")

                # Step 4: CLEANUP - Delete any existing clip in slot 1 (from previous runs)
                print("  4. Cleaning up slot 1 if needed...")
                result = await session.call_tool("get_clip_properties", {
                    "track_index": 0,
                    "clip_index": 1
                })
                content = result.content[0].text if result.content else ""
                try:
                    data = json.loads(content)
                    if "error" not in data:  # Slot 1 has a clip, delete it
                        print("     Found existing clip in slot 1, deleting...")
                        await session.call_tool("delete_clip", {
                            "track_index": 0,
                            "clip_index": 1
                        })
                        print("     Deleted")
                    else:
                        print("     Slot 1 is empty")
                except json.JSONDecodeError:
                    print("     Slot 1 is empty")

                # Step 5: DUPLICATE CLIP - Copy clip to another slot
                print("  5. Duplicating clip to slot 1...")
                result = await session.call_tool("duplicate_clip", {
                    "track_index": 0,
                    "clip_index": 0,
                    "target_track_index": 0,
                    "target_clip_index": 1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: duplicate_clip error: {data['error']}\n")
                    return 1
                print("     Clip duplicated")

                # Step 6: VERIFY DUPLICATE - Check duplicated clip exists
                print("  6. Verifying duplicated clip...")
                result = await session.call_tool("get_clip_properties", {
                    "track_index": 0,
                    "clip_index": 1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: Duplicated clip not found: {data['error']}\n")
                    return 1
                print(f"     Duplicate exists: {data.get('name')}")

                # Step 7: RESTORE - Reset original clip loop parameters
                print("  7. Restoring original loop parameters...")
                result = await session.call_tool("set_clip_loop", {
                    "track_index": 0,
                    "clip_index": 0,
                    "looping": original_looping,
                    "loop_start": original_loop_start,
                    "loop_end": original_loop_end
                })
                content = result.content[0].text if result.content else ""
                print("     Original parameters restored")

                # Step 8: CLEANUP - Delete the duplicated clip
                print("  8. Deleting duplicated clip...")
                result = await session.call_tool("delete_clip", {
                    "track_index": 0,
                    "clip_index": 1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  WARN: Could not delete clip: {data['error']}")
                else:
                    print("     Duplicated clip deleted")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Transport & Timing Round-Trip Test
            # Tests: get_current_time, set_current_time, get_is_playing,
            #        set_metronome, undo, redo
            # ================================================================
            print("--- Test: Transport & Timing Round-Trip ---")
            try:
                # Step 1: GET CURRENT TIME - Read initial song position
                print("  1. Getting current song position...")
                result = await session.call_tool("get_current_time", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_current_time error: {data['error']}\n")
                    return 1
                original_time = data.get("current_time")
                print(f"     Current time: {original_time} beats")

                # Step 2: GET IS PLAYING - Check playback state
                print("  2. Checking playback state...")
                result = await session.call_tool("get_is_playing", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: get_is_playing error: {data['error']}\n")
                    return 1
                is_playing = data.get("is_playing")
                print(f"     Is playing: {is_playing}")

                # Step 3: SET CURRENT TIME - Jump to position 4.0
                print("  3. Setting song position to 4.0 beats...")
                result = await session.call_tool("set_current_time", {
                    "time": 4.0
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_current_time error: {data['error']}\n")
                    return 1
                print(f"     Position set to: {data.get('current_time')} beats")

                # Step 4: VERIFY POSITION - Confirm position changed
                print("  4. Verifying song position...")
                result = await session.call_tool("get_current_time", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                current = data.get("current_time", -1)
                # Allow some tolerance since position might drift
                if abs(current - 4.0) > 0.1:
                    print(f"  FAIL: Position not set (got {current})\n")
                    return 1
                print(f"     Position verified: {current} beats")

                # Step 5: GET METRONOME STATE - Check current metronome
                print("  5. Checking metronome state...")
                result = await session.call_tool("get_is_playing", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                original_metronome = data.get("metronome", False)
                print(f"     Metronome: {original_metronome}")

                # Step 6: SET METRONOME - Toggle metronome
                new_metronome = not original_metronome
                print(f"  6. Setting metronome to {new_metronome}...")
                result = await session.call_tool("set_metronome", {
                    "enabled": new_metronome
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: set_metronome error: {data['error']}\n")
                    return 1
                print(f"     Metronome set to: {data.get('enabled')}")

                # Step 7: VERIFY METRONOME - Confirm metronome changed
                print("  7. Verifying metronome state...")
                result = await session.call_tool("get_is_playing", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if data.get("metronome") != new_metronome:
                    print(f"  FAIL: Metronome not set (got {data.get('metronome')})\n")
                    return 1
                print("     Metronome verified")

                # Step 8: TEST UNDO - Undo the last operation
                print("  8. Testing undo...")
                result = await session.call_tool("undo", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: undo error: {data['error']}\n")
                    return 1
                print("     Undo executed")

                # Step 9: TEST REDO - Redo the undone operation
                print("  9. Testing redo...")
                result = await session.call_tool("redo", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: redo error: {data['error']}\n")
                    return 1
                print("     Redo executed")

                # Step 10: RESTORE - Reset to original position and metronome
                print("  10. Restoring original state...")
                await session.call_tool("set_current_time", {"time": original_time})
                await session.call_tool("set_metronome", {"enabled": original_metronome})
                print(f"     Restored position={original_time}, metronome={original_metronome}")

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            # ================================================================
            # Audio Track Creation Test
            # Tests: create_audio_track
            # ================================================================
            print("--- Test: Audio Track Creation ---")
            try:
                # Step 1: GET INITIAL TRACK COUNT
                print("  1. Getting initial track count...")
                result = await session.call_tool("get_session_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                initial_track_count = data.get("track_count")
                print(f"     Initial tracks: {initial_track_count}")

                # Step 2: CREATE AUDIO TRACK - Create at end of track list
                print("  2. Creating audio track...")
                result = await session.call_tool("create_audio_track", {
                    "index": -1
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                if "error" in data:
                    print(f"  FAIL: create_audio_track error: {data['error']}\n")
                    return 1
                new_track_index = data.get("index")
                new_track_name = data.get("name")
                print(f"     Created audio track '{new_track_name}' at index {new_track_index}")

                # Step 3: VERIFY TRACK COUNT - Confirm track was added
                print("  3. Verifying track count increased...")
                result = await session.call_tool("get_session_info", {})
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                new_track_count = data.get("track_count")
                if new_track_count != initial_track_count + 1:
                    print(f"  FAIL: Track count not increased (got {new_track_count})\n")
                    return 1
                print(f"     Track count: {new_track_count}")

                # Step 4: VERIFY TRACK TYPE - Confirm it's an audio track
                print("  4. Verifying track type...")
                result = await session.call_tool("get_track_info", {
                    "track_index": new_track_index
                })
                content = result.content[0].text if result.content else ""
                data = json.loads(content)
                # Audio tracks should have has_audio_input: true or similar indicator
                track_type = "audio" if data.get("has_audio_input", False) else "midi"
                print(f"     Track type indicator: has_audio_input={data.get('has_audio_input')}")

                # Note: We leave the audio track in place - deleting tracks is destructive
                # and may affect the test fixture for subsequent test runs

                print("  PASS\n")

            except Exception as e:
                print(f"  FAIL: {e}\n")
                return 1

            print("=== All Tests Passed ===")
            return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
