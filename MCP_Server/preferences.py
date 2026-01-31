"""Binary parser for Ableton Live Preferences.cfg files.

This module parses Ableton's custom binary preferences format to read and modify
control surface slot configurations. The binary format uses:
- Magic header: ab 1e 56 78
- UTF-16LE strings with 4-byte little-endian length prefixes (character count)
- 7 control surface slots, each containing 3 strings: (Script, Input, Output)

Binary Format Overview
----------------------
1. Header: 4-byte magic (ab 1e 56 78) + version info
2. Schema section: Type definitions (RemoteableString, RemoteableBool, etc.)
3. Data section: Values following schema order, ending with control surface slots

Control Surface Slot Structure
------------------------------
The 7 slots are stored as 21 consecutive UTF-16LE strings at the end of the file:
- Slot 1: (Script Name, Input Device, Output Device)
- Slot 2: (Script Name, Input Device, Output Device)
- ...
- Slot 7: (Script Name, Input Device, Output Device)

Empty slots use "None" as the value for all three fields.

Anchor Strategy
---------------
To locate the control surface slots:
1. Find the last occurrence of "MidiOutDevicePreferences" marker
2. Skip past its content (read strings until zero-length encountered)
3. Skip zero padding bytes
4. Read 21 consecutive UTF-16LE strings (7 slots x 3 fields)

Validated on Ableton Live 11.3.42 and 11.3.43.
"""

from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Magic bytes at the start of every Preferences.cfg file
MAGIC_HEADER = bytes.fromhex("ab1e5678")

# Marker used to anchor the control surface slots location
MIDI_OUT_DEVICE_PREFS_MARKER = b"MidiOutDevicePreferences"

# Number of control surface slots in Ableton Live
NUM_CONTROL_SURFACE_SLOTS = 7

# Maximum reasonable string length (sanity check)
MAX_STRING_LENGTH = 1000


class PreferencesParseError(Exception):
    """Raised when parsing Preferences.cfg fails."""

    pass


class InvalidPreferencesFileError(PreferencesParseError):
    """Raised when the file is not a valid Preferences.cfg."""

    pass


class ControlSurfaceSlotsNotFoundError(PreferencesParseError):
    """Raised when control surface slots cannot be located in the file."""

    pass


@dataclass(frozen=True, slots=True)
class ControlSurfaceSlot:
    """A single control surface slot configuration.

    Attributes:
        index: 0-based slot index (0-6).
        script_name: Name of the control surface script, or "None" if empty.
        input_device: MIDI input device name, or "None" if not assigned.
        output_device: MIDI output device name, or "None" if not assigned.
    """

    index: int
    script_name: str
    input_device: str
    output_device: str

    @property
    def is_empty(self) -> bool:
        """Check if this slot is empty (script name is 'None')."""
        return self.script_name == "None"

    @property
    def display_index(self) -> int:
        """Return 1-based index for display purposes."""
        return self.index + 1


@dataclass(frozen=True, slots=True)
class SlotOffset:
    """Byte offset information for a control surface slot.

    Used internally for modification operations.
    """

    index: int
    script_name_offset: int
    script_name_size: int
    input_device_offset: int
    input_device_size: int
    output_device_offset: int
    output_device_size: int


def _read_utf16_string(data: bytes, offset: int) -> tuple[str, int]:
    """Read a length-prefixed UTF-16LE string from binary data.

    Format: 4-byte little-endian length (character count) + UTF-16LE bytes.

    Args:
        data: Binary data to read from.
        offset: Byte offset to start reading.

    Returns:
        Tuple of (decoded string, total bytes consumed including length prefix).

    Raises:
        PreferencesParseError: If the string cannot be read at this offset.
    """
    if offset + 4 > len(data):
        raise PreferencesParseError(
            f"Cannot read string length at offset {offset}: "
            f"insufficient data (file size: {len(data)})"
        )

    length = struct.unpack_from("<I", data, offset)[0]

    if length > MAX_STRING_LENGTH:
        raise PreferencesParseError(
            f"String length {length} at offset {offset} exceeds maximum {MAX_STRING_LENGTH}"
        )

    string_end = offset + 4 + length * 2
    if string_end > len(data):
        raise PreferencesParseError(
            f"String at offset {offset} extends past end of file: "
            f"need {string_end} bytes, have {len(data)}"
        )

    string_bytes = data[offset + 4 : string_end]
    try:
        string = string_bytes.decode("utf-16-le")
    except UnicodeDecodeError as e:
        raise PreferencesParseError(
            f"Invalid UTF-16LE string at offset {offset}: {e}"
        ) from e

    total_size = 4 + length * 2
    return string, total_size


def _write_utf16_string(value: str) -> bytes:
    """Encode a string as length-prefixed UTF-16LE.

    Args:
        value: String to encode.

    Returns:
        Bytes containing 4-byte length prefix + UTF-16LE encoded string.
    """
    encoded = value.encode("utf-16-le")
    length = len(value)  # Character count, not byte count
    return struct.pack("<I", length) + encoded


def _find_last_marker(data: bytes, marker: bytes) -> int:
    """Find the last occurrence of a marker in binary data.

    Args:
        data: Binary data to search.
        marker: Byte sequence to find.

    Returns:
        Offset of the last occurrence.

    Raises:
        ControlSurfaceSlotsNotFoundError: If marker is not found.
    """
    idx = 0
    last_found = -1

    while True:
        idx = data.find(marker, idx)
        if idx == -1:
            break
        last_found = idx
        idx += 1

    if last_found == -1:
        raise ControlSurfaceSlotsNotFoundError(
            f"Marker {marker!r} not found in preferences file"
        )

    return last_found


def _find_control_surface_start(data: bytes) -> int:
    """Find the byte offset where control surface slots begin.

    Algorithm:
    1. Find last occurrence of MidiOutDevicePreferences marker
    2. Scan forward to find at least 8 consecutive zero bytes (padding)
    3. Skip all zero padding
    4. Return offset of first control surface slot

    The control surface slots are always preceded by a run of zero bytes
    (typically 12-16 zeros) that separates them from the MIDI device
    preferences data.

    Args:
        data: Binary preferences file data.

    Returns:
        Byte offset where the first control surface slot starts.

    Raises:
        ControlSurfaceSlotsNotFoundError: If slots cannot be located.
    """
    # Step 1: Find last MidiOutDevicePreferences marker
    marker_offset = _find_last_marker(data, MIDI_OUT_DEVICE_PREFS_MARKER)

    # Step 2: Scan forward from marker to find the zero padding
    # The zero padding is at least 8 consecutive zero bytes that separates
    # the MIDI device preferences from the control surface slots
    offset = marker_offset + len(MIDI_OUT_DEVICE_PREFS_MARKER)

    # Search for 8+ consecutive zeros (the padding before control surface slots)
    min_zero_run = 8
    found_padding = False

    while offset < len(data) - min_zero_run:
        # Check if we have a run of zeros starting here
        if data[offset : offset + min_zero_run] == b"\x00" * min_zero_run:
            found_padding = True
            break
        offset += 1

    if not found_padding:
        raise ControlSurfaceSlotsNotFoundError(
            f"Could not find zero padding after MidiOutDevicePreferences marker at {marker_offset}"
        )

    # Step 3: Skip all zero padding bytes
    while offset < len(data) and data[offset] == 0:
        offset += 1

    # Step 4: Validate we're at a valid position
    # The first control surface slot should start with a valid string length
    if offset + 4 > len(data):
        raise ControlSurfaceSlotsNotFoundError(
            f"Unexpected end of file at offset {offset}"
        )

    first_length = struct.unpack_from("<I", data, offset)[0]
    if first_length > MAX_STRING_LENGTH:
        raise ControlSurfaceSlotsNotFoundError(
            f"Invalid string length {first_length} at offset {offset}: "
            "expected control surface slot to start here"
        )

    # Validate we have enough data for 21 strings
    # Minimum: 21 * (4 bytes length + 0 bytes content) = 84 bytes
    remaining = len(data) - offset
    if remaining < 84:
        raise ControlSurfaceSlotsNotFoundError(
            f"Insufficient data for control surface slots at offset {offset}: "
            f"need at least 84 bytes, have {remaining}"
        )

    return offset


def _parse_control_surface_slots(
    data: bytes, start_offset: int
) -> tuple[list[ControlSurfaceSlot], list[SlotOffset]]:
    """Parse the 7 control surface slots from binary data.

    Args:
        data: Binary preferences file data.
        start_offset: Byte offset where first slot begins.

    Returns:
        Tuple of (list of ControlSurfaceSlot, list of SlotOffset for modification).

    Raises:
        PreferencesParseError: If slots cannot be parsed.
    """
    slots: list[ControlSurfaceSlot] = []
    offsets: list[SlotOffset] = []
    offset = start_offset

    for slot_idx in range(NUM_CONTROL_SURFACE_SLOTS):
        # Read script name
        script_name_offset = offset
        script_name, script_size = _read_utf16_string(data, offset)
        offset += script_size

        # Read input device
        input_device_offset = offset
        input_device, input_size = _read_utf16_string(data, offset)
        offset += input_size

        # Read output device
        output_device_offset = offset
        output_device, output_size = _read_utf16_string(data, offset)
        offset += output_size

        slots.append(
            ControlSurfaceSlot(
                index=slot_idx,
                script_name=script_name,
                input_device=input_device,
                output_device=output_device,
            )
        )

        offsets.append(
            SlotOffset(
                index=slot_idx,
                script_name_offset=script_name_offset,
                script_name_size=script_size,
                input_device_offset=input_device_offset,
                input_device_size=input_size,
                output_device_offset=output_device_offset,
                output_device_size=output_size,
            )
        )

    return slots, offsets


class PreferencesParser:
    """Parser for Ableton Live Preferences.cfg binary files.

    This class provides read-only access to control surface slot configurations.
    For modification, use the PreferencesWriter class.

    Example:
        parser = PreferencesParser.from_file(path)
        for slot in parser.slots:
            print(f"Slot {slot.display_index}: {slot.script_name}")
    """

    def __init__(self, data: bytes) -> None:
        """Initialize parser with raw binary data.

        Args:
            data: Raw bytes from Preferences.cfg file.

        Raises:
            InvalidPreferencesFileError: If file doesn't have valid magic header.
            ControlSurfaceSlotsNotFoundError: If control surface slots not found.
        """
        self._validate_magic_header(data)
        self._data = data
        self._start_offset = _find_control_surface_start(data)
        self._slots, self._slot_offsets = _parse_control_surface_slots(
            data, self._start_offset
        )

    @classmethod
    def from_file(cls, path: Path | str) -> PreferencesParser:
        """Create a parser from a Preferences.cfg file path.

        Args:
            path: Path to the Preferences.cfg file.

        Returns:
            PreferencesParser instance.

        Raises:
            FileNotFoundError: If file doesn't exist.
            InvalidPreferencesFileError: If file is not a valid Preferences.cfg.
            ControlSurfaceSlotsNotFoundError: If control surface slots not found.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Preferences file not found: {path}")

        data = path.read_bytes()
        return cls(data)

    @staticmethod
    def _validate_magic_header(data: bytes) -> None:
        """Validate the magic header bytes.

        Args:
            data: Binary file data.

        Raises:
            InvalidPreferencesFileError: If magic header is invalid.
        """
        if len(data) < len(MAGIC_HEADER):
            raise InvalidPreferencesFileError(
                f"File too small ({len(data)} bytes): expected at least {len(MAGIC_HEADER)} bytes"
            )

        if data[: len(MAGIC_HEADER)] != MAGIC_HEADER:
            actual = data[: len(MAGIC_HEADER)].hex()
            expected = MAGIC_HEADER.hex()
            raise InvalidPreferencesFileError(
                f"Invalid magic header: got {actual}, expected {expected}"
            )

    @property
    def slots(self) -> list[ControlSurfaceSlot]:
        """Get all 7 control surface slot configurations."""
        return self._slots

    @property
    def raw_data(self) -> bytes:
        """Get the raw binary data."""
        return self._data

    def get_slot(self, index: int) -> ControlSurfaceSlot:
        """Get a specific control surface slot by 0-based index.

        Args:
            index: 0-based slot index (0-6).

        Returns:
            ControlSurfaceSlot for the specified index.

        Raises:
            IndexError: If index is out of range.
        """
        if not 0 <= index < NUM_CONTROL_SURFACE_SLOTS:
            raise IndexError(
                f"Slot index must be 0-{NUM_CONTROL_SURFACE_SLOTS - 1}, got {index}"
            )
        return self._slots[index]

    def find_empty_slot(self) -> ControlSurfaceSlot | None:
        """Find the first empty control surface slot.

        Returns:
            First empty slot, or None if all slots are occupied.
        """
        for slot in self._slots:
            if slot.is_empty:
                return slot
        return None

    def find_slot_by_script(self, script_name: str) -> ControlSurfaceSlot | None:
        """Find a slot by script name.

        Args:
            script_name: Name of the control surface script.

        Returns:
            Matching slot, or None if not found.
        """
        for slot in self._slots:
            if slot.script_name == script_name:
                return slot
        return None

    def iter_occupied_slots(self) -> Iterator[ControlSurfaceSlot]:
        """Iterate over slots that have a script assigned."""
        for slot in self._slots:
            if not slot.is_empty:
                yield slot

    def iter_empty_slots(self) -> Iterator[ControlSurfaceSlot]:
        """Iterate over slots that are empty."""
        for slot in self._slots:
            if slot.is_empty:
                yield slot

    def get_slot_offset(self, index: int) -> SlotOffset:
        """Get the byte offset information for a specific slot.

        Args:
            index: 0-based slot index (0-6).

        Returns:
            SlotOffset containing byte positions for the slot fields.

        Raises:
            IndexError: If index is out of range.
        """
        if not 0 <= index < NUM_CONTROL_SURFACE_SLOTS:
            raise IndexError(
                f"Slot index must be 0-{NUM_CONTROL_SURFACE_SLOTS - 1}, got {index}"
            )
        return self._slot_offsets[index]


class NoEmptySlotError(PreferencesParseError):
    """Raised when no empty control surface slot is available."""

    pass


class PreferencesWriteError(Exception):
    """Raised when writing to Preferences.cfg fails."""

    pass


class PreferencesWriter:
    """Writer for modifying Ableton Live Preferences.cfg files.

    This class handles safe modification of control surface slots in Ableton's
    binary preferences file. It always creates a backup before modification
    and verifies the write by re-reading the modified file.

    Example:
        writer = PreferencesWriter(prefs_path)
        slot_index = writer.set_control_surface("AbletonMCP")
        print(f"Installed to slot {slot_index + 1}")
    """

    def __init__(self, prefs_path: Path | str) -> None:
        """Initialize writer with the path to Preferences.cfg.

        Args:
            prefs_path: Path to the Preferences.cfg file.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            InvalidPreferencesFileError: If the file is not a valid Preferences.cfg.
        """
        self._path = Path(prefs_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Preferences file not found: {self._path}")

        # Validate the file is parseable
        self._parser = PreferencesParser.from_file(self._path)

    @property
    def path(self) -> Path:
        """Get the path to the Preferences.cfg file."""
        return self._path

    @property
    def backup_path(self) -> Path:
        """Get the path where the backup will be created."""
        return self._path.with_suffix(".cfg.backup")

    def _create_backup(self) -> Path:
        """Create a backup of the Preferences.cfg file.

        Returns:
            Path to the backup file.

        Raises:
            PreferencesWriteError: If backup creation fails.
        """
        backup = self.backup_path
        try:
            shutil.copy2(self._path, backup)
        except OSError as e:
            raise PreferencesWriteError(
                f"Failed to create backup at {backup}: {e}"
            ) from e
        return backup

    def _find_target_slot(self, slot_index: int | None) -> int:
        """Find the slot to modify.

        Args:
            slot_index: Specific slot index (0-6), or None to find first empty slot.

        Returns:
            0-based slot index to modify.

        Raises:
            NoEmptySlotError: If slot_index is None and no empty slots exist.
            IndexError: If slot_index is out of range.
        """
        if slot_index is not None:
            if not 0 <= slot_index < NUM_CONTROL_SURFACE_SLOTS:
                raise IndexError(
                    f"Slot index must be 0-{NUM_CONTROL_SURFACE_SLOTS - 1}, got {slot_index}"
                )
            return slot_index

        empty_slot = self._parser.find_empty_slot()
        if empty_slot is None:
            raise NoEmptySlotError(
                "No empty control surface slots available. "
                "All 7 slots are occupied. Clear a slot in Ableton preferences first."
            )
        return empty_slot.index

    def _splice_data(
        self, data: bytes, offset: int, old_size: int, new_bytes: bytes
    ) -> bytes:
        """Splice new bytes into binary data, replacing old content.

        Args:
            data: Original binary data.
            offset: Byte offset where replacement starts.
            old_size: Number of bytes to remove.
            new_bytes: New bytes to insert.

        Returns:
            New binary data with the splice applied.
        """
        return data[:offset] + new_bytes + data[offset + old_size :]

    def set_control_surface(
        self,
        script_name: str,
        slot_index: int | None = None,
        *,
        create_backup: bool = True,
    ) -> int:
        """Set a control surface script in Ableton preferences.

        This method modifies the Preferences.cfg file to configure a control
        surface slot with the specified script name. The file is backed up
        before modification, and the write is verified by re-reading the file.

        Args:
            script_name: Name of the control surface script (folder name).
            slot_index: Specific slot to use (0-6), or None to use first empty slot.
            create_backup: Whether to create a backup before modification.
                Defaults to True. Only set to False for testing.

        Returns:
            0-based index of the slot that was modified.

        Raises:
            NoEmptySlotError: If slot_index is None and no empty slots exist.
            IndexError: If slot_index is out of range.
            PreferencesWriteError: If the write fails or verification fails.
        """
        # Read current file data
        data = self._path.read_bytes()

        # Find the target slot
        target_index = self._find_target_slot(slot_index)
        slot_offset = self._parser.get_slot_offset(target_index)

        # Encode the new script name
        new_bytes = _write_utf16_string(script_name)

        # Create backup before modification
        if create_backup:
            self._create_backup()

        # Splice the new script name into the data
        new_data = self._splice_data(
            data,
            slot_offset.script_name_offset,
            slot_offset.script_name_size,
            new_bytes,
        )

        # Write the modified data
        try:
            self._path.write_bytes(new_data)
        except OSError as e:
            raise PreferencesWriteError(
                f"Failed to write modified preferences to {self._path}: {e}"
            ) from e

        # Verify the write by re-parsing
        self._verify_write(script_name, target_index)

        return target_index

    def _verify_write(self, expected_script: str, slot_index: int) -> None:
        """Verify that the write succeeded by re-reading the file.

        Args:
            expected_script: The script name that should have been written.
            slot_index: The slot index that was modified.

        Raises:
            PreferencesWriteError: If verification fails.
        """
        try:
            parser = PreferencesParser.from_file(self._path)
        except PreferencesParseError as e:
            raise PreferencesWriteError(
                f"Verification failed: modified file is not valid. "
                f"Restore from backup at {self.backup_path}. Error: {e}"
            ) from e

        slot = parser.get_slot(slot_index)
        if slot.script_name != expected_script:
            raise PreferencesWriteError(
                f"Verification failed: slot {slot_index} contains "
                f"{slot.script_name!r}, expected {expected_script!r}. "
                f"Restore from backup at {self.backup_path}."
            )

        # Update internal parser with verified state
        self._parser = parser

    def clear_control_surface(
        self,
        slot_index: int,
        *,
        create_backup: bool = True,
    ) -> None:
        """Clear a control surface slot by setting it to "None".

        Args:
            slot_index: Slot to clear (0-6).
            create_backup: Whether to create a backup before modification.

        Raises:
            IndexError: If slot_index is out of range.
            PreferencesWriteError: If the write fails.
        """
        self.set_control_surface("None", slot_index, create_backup=create_backup)

    def get_current_slots(self) -> list[ControlSurfaceSlot]:
        """Get the current state of all control surface slots.

        Returns:
            List of all 7 control surface slots.
        """
        return self._parser.slots

    def find_script(self, script_name: str) -> ControlSurfaceSlot | None:
        """Find a slot that already has the specified script.

        Args:
            script_name: Name of the script to find.

        Returns:
            The slot containing the script, or None if not found.
        """
        return self._parser.find_slot_by_script(script_name)
