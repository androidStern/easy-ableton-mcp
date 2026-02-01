"""Shared fixtures for AbletonMCP tests.

Mocks the Ableton Live API boundary:
- _Framework.ControlSurface (base class)
- self._song (Song object)
- self.application() (Browser access)
"""

import sys
from unittest.mock import MagicMock
import pytest


# ---------------------------------------------------------------------------
# Mock ControlSurface base class (must happen before imports)
# ---------------------------------------------------------------------------

class MockControlSurface:
    def __init__(self, c_instance):
        pass

    def log_message(self, msg):
        pass

    def show_message(self, msg):
        pass

    def schedule_message(self, delay, callback):
        callback()

    def song(self):
        return MagicMock()

    def application(self):
        return MagicMock()


sys.modules['_Framework'] = MagicMock()
sys.modules['_Framework.ControlSurface'] = MagicMock(ControlSurface=MockControlSurface)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mcp():
    """AbletonMCP with mocked Ableton API."""
    from AbletonMCP_Remote_Script import AbletonMCP

    instance = AbletonMCP(MagicMock())

    # Mock _song with values the handlers check
    song = MagicMock()
    song.tempo = 120.0
    song.signature_numerator = 4
    song.signature_denominator = 4
    song.is_playing = False
    song.master_track.mixer_device.volume.value = 0.85
    song.master_track.mixer_device.panning.value = 0.0

    # One track with one clip slot and one device
    track = MagicMock()
    track.name = "Track 1"
    track.has_midi_input = True
    track.has_audio_input = False
    track.mute = False
    track.solo = False
    track.arm = False
    track.mixer_device.volume.value = 0.85
    track.mixer_device.panning.value = 0.0

    # Slot 0: has a clip (for add_notes, set_clip_name, fire_clip, stop_clip)
    slot0 = MagicMock()
    slot0.has_clip = True
    slot0.clip.name = "Clip"
    slot0.clip.length = 4.0
    slot0.clip.is_playing = False
    slot0.clip.is_recording = False

    # Slot 1: empty (for create_clip)
    slot1 = MagicMock()
    slot1.has_clip = False

    track.clip_slots = [slot0, slot1]

    # Device with parameters for set_device_parameter
    param = MagicMock()
    param.name = "Param"
    param.value = 0.5
    param.min = 0.0
    param.max = 1.0

    device = MagicMock()
    device.name = "Device"
    device.class_name = "PluginDevice"
    device.parameters = [param]
    track.devices = [device]

    song.tracks = [track]
    song.return_tracks = []
    song.scenes = []

    instance._song = song

    # Browser mock - configure so _find_browser_item_by_uri can find items
    # Create a findable browser item
    browser_item = MagicMock(spec=['uri', 'name', 'is_loadable'])
    browser_item.uri = "x"  # matches test param
    browser_item.name = "Test Item"
    browser_item.is_loadable = True

    # Category with children containing our item
    category = MagicMock(spec=['children', 'iter_children'])
    category.children = [browser_item]

    # Browser with categories (use spec to prevent infinite MagicMock expansion)
    browser = MagicMock(spec=['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects', 'load_item'])
    browser.instruments = category
    browser.sounds = MagicMock(spec=['children'])
    browser.sounds.children = []
    browser.drums = MagicMock(spec=['children'])
    browser.drums.children = []
    browser.audio_effects = MagicMock(spec=['children'])
    browser.audio_effects.children = []
    browser.midi_effects = MagicMock(spec=['children'])
    browser.midi_effects.children = []

    app = MagicMock()
    app.browser = browser
    instance.application = MagicMock(return_value=app)

    return instance
