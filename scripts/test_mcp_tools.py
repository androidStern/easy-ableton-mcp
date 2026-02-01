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

            print("=== All Tests Passed ===")
            return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
