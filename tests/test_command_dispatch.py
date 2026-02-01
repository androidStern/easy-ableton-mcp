"""Command dispatch tests for AbletonMCP.

Tests _process_command() with real handlers, mocking only the Ableton API.
"""

import pytest
from unittest.mock import MagicMock

# Command inventories from _process_command()
DIRECT_COMMANDS = [
    ("get_session_info", {}),
    ("get_track_info", {"track_index": 0}),
    ("get_browser_tree", {"category_type": "all"}),
    ("get_browser_items_at_path", {"path": ""}),
    ("get_session_tree", {}),
    ("get_device_parameters", {"track_index": 0, "device_index": 0}),
    ("get_clip_envelope", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0}),
    ("get_envelope_value_at_time", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5}),
    ("get_scenes_info", {}),
    ("get_clip_properties", {"track_index": 0, "clip_index": 0}),
    # Transport & timing (read-only)
    ("get_current_time", {}),
    ("get_is_playing", {}),
]

MAIN_THREAD_COMMANDS = [
    ("create_midi_track", {"index": 0}),
    ("set_track_name", {"track_index": 0, "name": "X"}),
    ("create_clip", {"track_index": 0, "clip_index": 1, "length": 4.0}),  # slot 1 is empty
    ("add_notes_to_clip", {"track_index": 0, "clip_index": 0, "notes": []}),  # slot 0 has clip
    ("set_clip_name", {"track_index": 0, "clip_index": 0, "name": "Y"}),  # slot 0 has clip
    ("set_tempo", {"tempo": 140.0}),
    ("fire_clip", {"track_index": 0, "clip_index": 0}),  # slot 0 has clip
    ("stop_clip", {"track_index": 0, "clip_index": 0}),  # slot 0 has clip
    ("start_playback", {}),
    ("stop_playback", {}),
    ("load_browser_item", {"track_index": 0, "item_uri": "x"}),
    ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0, "value": 0.5}),
    ("batch_set_device_parameters", {"track_index": 0, "device_index": 0, "parameters": []}),
    ("set_track_volume", {"track_index": 0, "volume": 0.5}),
    ("set_track_pan", {"track_index": 0, "pan": 0.0}),
    ("set_track_mute", {"track_index": 0, "mute": True}),
    ("set_track_solo", {"track_index": 0, "solo": True}),
    ("insert_envelope_point", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5, "value": 0.75}),
    ("clear_clip_envelopes", {"track_index": 0, "clip_index": 0}),
    ("create_automation_envelope", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0}),
    # Scene management commands
    ("create_scene", {"index": -1}),
    ("delete_scene", {"scene_index": 0}),
    ("set_scene_name", {"scene_index": 0, "name": "Test Scene"}),
    ("fire_scene", {"scene_index": 0}),
    # Clip properties commands
    ("set_clip_loop", {"track_index": 0, "clip_index": 0, "looping": True, "loop_start": 0.0, "loop_end": 4.0}),
    ("duplicate_clip", {"track_index": 0, "clip_index": 0, "target_track_index": 0, "target_clip_index": 1}),
    ("delete_clip", {"track_index": 0, "clip_index": 0}),
    # Transport & timing commands (state-modifying)
    ("set_current_time", {"time": 4.0}),
    ("set_metronome", {"enabled": True}),
    ("undo", {}),
    ("redo", {}),
    # Audio track commands
    ("create_audio_track", {"index": -1}),
]


class TestDirectCommands:
    """Read-only commands execute synchronously, no schedule_message."""

    @pytest.mark.parametrize("cmd,params", DIRECT_COMMANDS)
    def test_returns_success(self, mcp, cmd, params):
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "success"

    @pytest.mark.parametrize("cmd,params", DIRECT_COMMANDS)
    def test_skips_schedule_message(self, mcp, cmd, params):
        calls = []
        mcp.schedule_message = lambda d, cb: calls.append(1)
        mcp._process_command({"type": cmd, "params": params})
        assert calls == []


class TestMainThreadCommands:
    """State-modifying commands use schedule_message + queue."""

    @pytest.mark.parametrize("cmd,params", MAIN_THREAD_COMMANDS)
    def test_returns_success(self, mcp, cmd, params):
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "success"

    @pytest.mark.parametrize("cmd,params", MAIN_THREAD_COMMANDS)
    def test_uses_schedule_message(self, mcp, cmd, params):
        calls = []
        original = mcp.schedule_message
        mcp.schedule_message = lambda d, cb: (calls.append(1), original(d, cb))[-1]
        mcp._process_command({"type": cmd, "params": params})
        assert len(calls) == 1


class TestQueueBehavior:
    """The async queue pattern for main-thread commands."""

    def test_timeout_when_callback_not_executed(self, mcp):
        """Queue.get times out if schedule_message doesn't run callback."""
        import queue as queue_module
        original_get = queue_module.Queue.get

        def fast_get(self, block=True, timeout=None):
            return original_get(self, block=block, timeout=0.01)  # 10ms instead of 10s

        mcp.schedule_message = lambda d, cb: None
        queue_module.Queue.get = fast_get
        try:
            response = mcp._process_command({"type": "set_tempo", "params": {"tempo": 120}})
        finally:
            queue_module.Queue.get = original_get

        assert response["status"] == "error"
        assert "Timeout" in response["message"]

    def test_error_propagates_through_queue(self, mcp):
        """Exception in callback returns error response."""
        mcp._song.tracks = []
        response = mcp._process_command({
            "type": "set_track_name",
            "params": {"track_index": 99, "name": "X"}
        })
        assert response["status"] == "error"


class TestErrorHandling:
    """Error cases in command dispatch."""

    def test_unknown_command(self, mcp):
        response = mcp._process_command({"type": "fake_command"})
        assert response["status"] == "error"
        assert "Unknown command" in response["message"]

    def test_missing_type(self, mcp):
        response = mcp._process_command({})
        assert response["status"] == "error"
