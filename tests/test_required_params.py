"""Tests for required parameter validation (Issue #4).

Commands should reject missing required parameters instead of silently
defaulting to track 0, clip 0, etc. This prevents accidental operations
on the wrong track/clip when the caller forgets a parameter.

These tests are expected to FAIL until the fix is implemented.
"""

import pytest


# Commands that require track_index - should error if omitted
TRACK_REQUIRED = [
    ("get_track_info", {}),
    ("set_track_name", {"name": "Test"}),
    ("create_clip", {"clip_index": 0, "length": 4.0}),
    ("add_notes_to_clip", {"clip_index": 0, "notes": []}),
    ("set_clip_name", {"clip_index": 0, "name": "Test"}),
    ("fire_clip", {"clip_index": 0}),
    ("stop_clip", {"clip_index": 0}),
    ("load_browser_item", {"item_uri": "test://uri"}),
    ("get_device_parameters", {"device_index": 0}),
    ("set_device_parameter", {"device_index": 0, "parameter_index": 0, "value": 0.5}),
    ("batch_set_device_parameters", {"device_index": 0, "parameters": []}),
    ("set_track_volume", {"volume": 0.5}),
    ("set_track_pan", {"pan": 0.0}),
    ("set_track_mute", {"mute": True}),
    ("set_track_solo", {"solo": True}),
    ("get_clip_envelope", {"clip_index": 0, "device_index": 0, "parameter_index": 0}),
    ("get_envelope_value_at_time", {"clip_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5}),
    ("insert_envelope_point", {"clip_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5, "value": 0.75}),
    ("clear_clip_envelopes", {"clip_index": 0}),
    ("create_automation_envelope", {"clip_index": 0, "device_index": 0, "parameter_index": 0}),
]

# Commands that require clip_index - should error if omitted
CLIP_REQUIRED = [
    ("create_clip", {"track_index": 0, "length": 4.0}),
    ("add_notes_to_clip", {"track_index": 0, "notes": []}),
    ("set_clip_name", {"track_index": 0, "name": "Test"}),
    ("fire_clip", {"track_index": 0}),
    ("stop_clip", {"track_index": 0}),
    ("get_clip_envelope", {"track_index": 0, "device_index": 0, "parameter_index": 0}),
    ("get_envelope_value_at_time", {"track_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5}),
    ("insert_envelope_point", {"track_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5, "value": 0.75}),
    ("clear_clip_envelopes", {"track_index": 0}),
    ("create_automation_envelope", {"track_index": 0, "device_index": 0, "parameter_index": 0}),
]

# Commands that require device_index - should error if omitted
DEVICE_REQUIRED = [
    ("get_device_parameters", {"track_index": 0}),
    ("set_device_parameter", {"track_index": 0, "parameter_index": 0, "value": 0.5}),
    ("batch_set_device_parameters", {"track_index": 0, "parameters": []}),
    ("get_clip_envelope", {"track_index": 0, "clip_index": 0, "parameter_index": 0}),
    ("get_envelope_value_at_time", {"track_index": 0, "clip_index": 0, "parameter_index": 0, "time": 0.5}),
    ("insert_envelope_point", {"track_index": 0, "clip_index": 0, "parameter_index": 0, "time": 0.5, "value": 0.75}),
    ("create_automation_envelope", {"track_index": 0, "clip_index": 0, "parameter_index": 0}),
]

# Commands that require parameter_index - should error if omitted
PARAM_INDEX_REQUIRED = [
    ("set_device_parameter", {"track_index": 0, "device_index": 0, "value": 0.5}),
    ("get_clip_envelope", {"track_index": 0, "clip_index": 0, "device_index": 0}),
    ("get_envelope_value_at_time", {"track_index": 0, "clip_index": 0, "device_index": 0, "time": 0.5}),
    ("insert_envelope_point", {"track_index": 0, "clip_index": 0, "device_index": 0, "time": 0.5, "value": 0.75}),
    ("create_automation_envelope", {"track_index": 0, "clip_index": 0, "device_index": 0}),
]

# Commands that require value - should error if omitted
VALUE_REQUIRED = [
    ("set_device_parameter", {"track_index": 0, "device_index": 0, "parameter_index": 0}),
]

# Commands that require item_uri - should error if omitted
URI_REQUIRED = [
    ("load_browser_item", {"track_index": 0}),
]

# Commands that require volume - should error if omitted
VOLUME_REQUIRED = [
    ("set_track_volume", {"track_index": 0}),
]

# Commands that require pan - should error if omitted
PAN_REQUIRED = [
    ("set_track_pan", {"track_index": 0}),
]

# Commands that require mute - should error if omitted
MUTE_REQUIRED = [
    ("set_track_mute", {"track_index": 0}),
]

# Commands that require solo - should error if omitted
SOLO_REQUIRED = [
    ("set_track_solo", {"track_index": 0}),
]

# Commands that require time - should error if omitted
TIME_REQUIRED = [
    ("get_envelope_value_at_time", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0}),
    ("insert_envelope_point", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0, "value": 0.75}),
]

# Commands that require value (for insert_envelope_point) - should error if omitted
ENVELOPE_VALUE_REQUIRED = [
    ("insert_envelope_point", {"track_index": 0, "clip_index": 0, "device_index": 0, "parameter_index": 0, "time": 0.5}),
]


class TestMissingTrackIndex:
    """Commands should error when track_index is missing."""

    @pytest.mark.parametrize("cmd,params", TRACK_REQUIRED)
    def test_rejects_missing_track_index(self, mcp, cmd, params):
        """Command should return error when track_index is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing track_index, got: {response}"
        )
        assert "track_index" in response["message"].lower(), (
            f"{cmd} error should mention track_index: {response['message']}"
        )


class TestMissingClipIndex:
    """Commands should error when clip_index is missing."""

    @pytest.mark.parametrize("cmd,params", CLIP_REQUIRED)
    def test_rejects_missing_clip_index(self, mcp, cmd, params):
        """Command should return error when clip_index is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing clip_index, got: {response}"
        )
        assert "clip_index" in response["message"].lower(), (
            f"{cmd} error should mention clip_index: {response['message']}"
        )


class TestMissingDeviceIndex:
    """Commands should error when device_index is missing."""

    @pytest.mark.parametrize("cmd,params", DEVICE_REQUIRED)
    def test_rejects_missing_device_index(self, mcp, cmd, params):
        """Command should return error when device_index is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing device_index, got: {response}"
        )
        assert "device_index" in response["message"].lower(), (
            f"{cmd} error should mention device_index: {response['message']}"
        )


class TestMissingParameterIndex:
    """set_device_parameter should error when parameter_index is missing."""

    @pytest.mark.parametrize("cmd,params", PARAM_INDEX_REQUIRED)
    def test_rejects_missing_parameter_index(self, mcp, cmd, params):
        """Command should return error when parameter_index is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing parameter_index, got: {response}"
        )
        assert "parameter_index" in response["message"].lower(), (
            f"{cmd} error should mention parameter_index: {response['message']}"
        )


class TestMissingValue:
    """set_device_parameter should error when value is missing."""

    @pytest.mark.parametrize("cmd,params", VALUE_REQUIRED)
    def test_rejects_missing_value(self, mcp, cmd, params):
        """Command should return error when value is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing value, got: {response}"
        )
        assert "value" in response["message"].lower(), (
            f"{cmd} error should mention value: {response['message']}"
        )


class TestMissingUri:
    """load_browser_item should error when item_uri is missing."""

    @pytest.mark.parametrize("cmd,params", URI_REQUIRED)
    def test_rejects_missing_item_uri(self, mcp, cmd, params):
        """Command should return error when item_uri is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing item_uri, got: {response}"
        )
        assert "item_uri" in response["message"].lower() or "uri" in response["message"].lower(), (
            f"{cmd} error should mention item_uri: {response['message']}"
        )


class TestMissingVolume:
    """set_track_volume should error when volume is missing."""

    @pytest.mark.parametrize("cmd,params", VOLUME_REQUIRED)
    def test_rejects_missing_volume(self, mcp, cmd, params):
        """Command should return error when volume is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing volume, got: {response}"
        )
        assert "volume" in response["message"].lower(), (
            f"{cmd} error should mention volume: {response['message']}"
        )


class TestMissingPan:
    """set_track_pan should error when pan is missing."""

    @pytest.mark.parametrize("cmd,params", PAN_REQUIRED)
    def test_rejects_missing_pan(self, mcp, cmd, params):
        """Command should return error when pan is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing pan, got: {response}"
        )
        assert "pan" in response["message"].lower(), (
            f"{cmd} error should mention pan: {response['message']}"
        )


class TestMissingMute:
    """set_track_mute should error when mute is missing."""

    @pytest.mark.parametrize("cmd,params", MUTE_REQUIRED)
    def test_rejects_missing_mute(self, mcp, cmd, params):
        """Command should return error when mute is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing mute, got: {response}"
        )
        assert "mute" in response["message"].lower(), (
            f"{cmd} error should mention mute: {response['message']}"
        )


class TestMissingSolo:
    """set_track_solo should error when solo is missing."""

    @pytest.mark.parametrize("cmd,params", SOLO_REQUIRED)
    def test_rejects_missing_solo(self, mcp, cmd, params):
        """Command should return error when solo is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing solo, got: {response}"
        )
        assert "solo" in response["message"].lower(), (
            f"{cmd} error should mention solo: {response['message']}"
        )


class TestMissingTime:
    """Envelope commands should error when time is missing."""

    @pytest.mark.parametrize("cmd,params", TIME_REQUIRED)
    def test_rejects_missing_time(self, mcp, cmd, params):
        """Command should return error when time is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing time, got: {response}"
        )
        assert "time" in response["message"].lower(), (
            f"{cmd} error should mention time: {response['message']}"
        )


class TestMissingEnvelopeValue:
    """insert_envelope_point should error when value is missing."""

    @pytest.mark.parametrize("cmd,params", ENVELOPE_VALUE_REQUIRED)
    def test_rejects_missing_envelope_value(self, mcp, cmd, params):
        """Command should return error when value is omitted."""
        response = mcp._process_command({"type": cmd, "params": params})
        assert response["status"] == "error", (
            f"{cmd} should reject missing value, got: {response}"
        )
        assert "value" in response["message"].lower(), (
            f"{cmd} error should mention value: {response['message']}"
        )


class TestExplicitZeroStillWorks:
    """Explicitly passing 0 should work (not be confused with missing)."""

    def test_track_index_zero_explicit(self, mcp):
        """Passing track_index=0 explicitly should succeed."""
        response = mcp._process_command({
            "type": "get_track_info",
            "params": {"track_index": 0}
        })
        assert response["status"] == "success"

    def test_clip_index_zero_explicit(self, mcp):
        """Passing clip_index=0 explicitly should succeed."""
        response = mcp._process_command({
            "type": "fire_clip",
            "params": {"track_index": 0, "clip_index": 0}
        })
        assert response["status"] == "success"

    def test_device_index_zero_explicit(self, mcp):
        """Passing device_index=0 explicitly should succeed."""
        response = mcp._process_command({
            "type": "get_device_parameters",
            "params": {"track_index": 0, "device_index": 0}
        })
        assert response["status"] == "success"
