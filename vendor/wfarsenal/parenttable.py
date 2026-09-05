"""Extract the type-inheritance table from a raw Packages.bin.

``Warframe-Exporter-CLI --dump-pkgs`` writes each object's *own* attributes but drops
the parent reference, so a dump alone cannot tell you that Excalibur's armour lives on
ExcaliburBaseSuit. This module recovers ``path -> parent path`` by parsing the
directory region of Packages.bin directly.

Only the uncompressed directory region is read. The attribute payloads are
zstd-with-dictionary frames living in a separate buffer, and we never touch them --
the dump already provides those.

Layout (version >= 46), after a header whose field offsets are located by scanning:

    reference table:  count, then count * (u32 len, ascii, 2 bytes)
    flags buffer:     u32 len + payload   (bit-per-entity: has-text, is-compressed)
    size buffer:      u32 len + payload   (ULEB frame sizes)
    zstd buffer:      u32 len + payload   (dictionary + frames)
    entity count:     u32
    directory:        repeated package groups, each
                        u32 len, ascii package path, 1 byte,
                        u32 child count, then per child:
                          u32 len, ascii filename, 3 bytes,
                          u32 len, ascii parent type

The has-text flag bit must still be consumed per entity to stay in sync with the
flags bitstream, but the frame data itself is skipped.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO, Iterator, NamedTuple

# The five header u32s sit at build-dependent offsets, so each is located by scanning
# byte-by-byte for a value in a plausible range, backtracking when a later field fails
# to validate. Bounds mirror LotusLib's searchValueRangesWarframe; they are deliberately
# narrow because the surrounding bytes are high-entropy and wide ranges match noise.
_SEARCH_BOUNDS = (
    (45, 60, "ReferenceCount"),
    (75_000, 90_000, "ComFlagsBufLen"),
    (210_000, 240_000, "ComSizeBufferLen"),
    (18_000_000, 21_000_000, "ComZBufferLen"),
    (9, 16, "PkgNameLen"),
)
_DICT_SIZE_BOUNDS = (80_000, 1_300_000)
_ENTITY_COUNT_BOUNDS = (400_000, 600_000)

# How far past the prologue a field may be found, and the per-state scan window.
_MAX_STATE_DRIFT = 1000
_SCAN_WINDOW = 1000


class PackagesBinError(Exception):
    """Raised when Packages.bin cannot be parsed."""


class Entity(NamedTuple):
    path: str
    parent: str


def _u32(fh: BinaryIO) -> int:
    data = fh.read(4)
    if len(data) != 4:
        raise PackagesBinError("unexpected end of file reading u32")
    return struct.unpack("<I", data)[0]


def _ascii(fh: BinaryIO, length: int) -> str:
    data = fh.read(length)
    if len(data) != length:
        raise PackagesBinError("unexpected end of file reading string")
    return data.decode("ascii", errors="replace")


def _read_uleb(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a ULEB128 at ``pos``; return (value, new position)."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise PackagesBinError("unexpected end of buffer reading ULEB128")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 35:
            raise PackagesBinError("ULEB128 too long")


class _Bitstream:
    """Reads the per-entity flag bits, LSB-first within each byte."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._bit = 0
        self._byte = data[0] if data else 0

    def next(self) -> int:
        bit = self._byte >> self._bit & 1
        self._bit += 1
        if self._bit > 7:
            self._pos += 1
            self._bit -= 8
            self._byte = self._data[self._pos] if self._pos < len(self._data) else 0
        return bit


def parse(path: str | Path) -> dict[str, str]:
    """Return ``{internal path: parent path}`` for every entity in Packages.bin.

    Args:
        path: Raw Packages.bin, as written by ``--write-raw --internal-path
            /Packages.bin`` (the exporter appends a ``_H`` suffix).

    Returns:
        Mapping of absolute internal path to absolute parent path. Entities whose
        parent field is empty are omitted.
    """
    return {e.path: e.parent for e in iter_entities(path) if e.parent}


def iter_entities(path: str | Path) -> Iterator[Entity]:
    """Yield every entity's path and parent path from Packages.bin."""
    file = Path(path)
    if not file.is_file():
        raise PackagesBinError(f"not found: {file}")

    with file.open("rb") as fh:
        offsets = _find_header_offsets(fh)

        fh.seek(offsets[1])
        flags = _Bitstream(fh.read(_u32(fh)))

        fh.seek(offsets[2])
        size_buf = fh.read(_u32(fh))

        # The size buffer opens with the zstd dictionary length; frame sizes follow.
        size_pos = 4

        # The entity count sits immediately after the zstd buffer.
        fh.seek(offsets[3])
        zstd_len = _u32(fh)
        fh.seek(zstd_len, 1)
        entity_count = _u32(fh)

        fh.seek(offsets[4])
        seen = 0
        while seen < entity_count:
            pkg_len = _u32(fh)
            if not 1 <= pkg_len <= 200:
                raise PackagesBinError(f"implausible package name length {pkg_len}")
            pkg = _ascii(fh, pkg_len)

            fh.seek(1, 1)
            children = _u32(fh)

            for _ in range(children):
                if seen >= entity_count:
                    break
                name_len = _u32(fh)
                if not 1 <= name_len <= 200:
                    raise PackagesBinError(f"implausible file name length {name_len}")
                name = _ascii(fh, name_len)

                fh.seek(3, 1)  # short + byte

                parent_len = _u32(fh)
                parent_type = _ascii(fh, parent_len) if parent_len else ""

                # Keep the flag bitstream and size cursor in sync even though the
                # attribute payload itself is skipped.
                if flags.next():
                    frame_size, size_pos = _read_uleb(size_buf, size_pos)
                    del frame_size
                    flags.next()  # is-compressed

                seen += 1
                yield Entity(
                    path=pkg + name,
                    parent=parent_type if parent_type.startswith("/") else (pkg + parent_type if parent_type else ""),
                )


def _find_header_offsets(fh: BinaryIO) -> list[int]:
    """Locate the five variable-position header u32s.

    Each field is found by scanning forward for a value inside its expected range, then
    validating it by attempting to locate every *subsequent* field from the position it
    implies. A field that cannot be followed by a valid chain is rejected and the scan
    resumes past it, so an early false positive cannot derail the parse.
    """
    fh.seek(0, 2)
    file_size = fh.tell()

    fh.seek(16)
    header_size = _u32(fh)
    version = _u32(fh)
    if version < 46:
        raise PackagesBinError(
            f"Packages.bin version {version} is not supported (need >= 46); "
            "older layouts use a different directory encoding"
        )
    _u32(fh)  # flags

    offsets = [0] * len(_SEARCH_BOUNDS)
    if not _search_state(fh, offsets, 0, fh.tell(), file_size):
        raise PackagesBinError(
            f"could not locate header fields (version {version}, header size {header_size})"
        )
    return offsets


def _search_state(
    fh: BinaryIO, offsets: list[int], state: int, start: int, file_size: int
) -> bool:
    """Resolve header field ``state`` and, recursively, all fields after it.

    Returns True when this field and every later one were placed consistently.
    """
    low, high, _label = _SEARCH_BOUNDS[state]
    cursor = start

    while cursor - start <= _MAX_STATE_DRIFT:
        found = _scan_for_value(fh, cursor, low, high, file_size)
        if found is None:
            return False
        cursor = found

        fh.seek(cursor)
        value = _u32(fh)
        next_pos = _validate_state(fh, state, value, file_size)

        if next_pos is not None:
            offsets[state] = cursor
            if state == len(_SEARCH_BOUNDS) - 1:
                return True
            if _search_state(fh, offsets, state + 1, next_pos, file_size):
                return True

        cursor += 4

    return False


def _scan_for_value(
    fh: BinaryIO, start: int, low: int, high: int, file_size: int
) -> int | None:
    """Return the first offset at/after ``start`` holding a u32 in (low, high).

    Scans one byte at a time -- these fields are not guaranteed to be 4-byte aligned
    relative to the prologue.
    """
    limit = min(file_size - 4, start + _SCAN_WINDOW)
    probe = start
    while probe <= limit:
        fh.seek(probe)
        raw = fh.read(4)
        if len(raw) != 4:
            return None
        value = struct.unpack("<I", raw)[0]
        if low < value < high:
            return probe
        probe += 1
    return None


def _validate_state(
    fh: BinaryIO, state: int, value: int, file_size: int
) -> int | None:
    """Check a candidate field value; return where the next field's scan should start.

    Returns None when the value is inconsistent with the surrounding structure.
    """
    if state == 0:
        # Walk the reference table; it must stay inside the file.
        for _ in range(value):
            raw = fh.read(4)
            if len(raw) != 4:
                return None
            name_len = struct.unpack("<I", raw)[0]
            if name_len > 1000:
                return None
            fh.seek(name_len + 2, 1)
            if fh.tell() > file_size:
                return None
        return fh.tell()

    if state == 1:
        # Flags buffer: skip it.
        end = fh.tell() + value
        return end if end <= file_size else None

    if state == 2:
        # Size buffer opens with the zstd dictionary length, which has a known range.
        dict_size = _u32(fh)
        if not _DICT_SIZE_BOUNDS[0] < dict_size < _DICT_SIZE_BOUNDS[1]:
            return None
        end = fh.tell() + value - 4
        return end if end <= file_size else None

    if state == 3:
        # Zstd buffer, then the entity count must look plausible.
        end = fh.tell() + value
        if end + 4 > file_size:
            return None
        fh.seek(end)
        entity_count = _u32(fh)
        if not _ENTITY_COUNT_BOUNDS[0] < entity_count < _ENTITY_COUNT_BOUNDS[1]:
            return None
        return fh.tell()

    # state 4 is the first PkgNameLen; reaching it in range is validation enough.
    return fh.tell()
