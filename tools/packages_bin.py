"""Standalone Packages.bin reader for Warframe builds with the 2026-09 directory layout.

Works on both the old (<=2026.08.19) and new (2026.09.22+) layouts. The only observed
difference is buffer sizes drifting past the old scan bounds; this reader locates the
five key offsets with wider ranges and a validation chain.

Layout after the 16-byte magic:
    u32 headerSize (=20), u32 version (>=46), u32 flags (=1), then variable junk
    u32 refCount, refCount * (u32 len, ascii, u16)
    <variable gap>
    u32 flagsBufLen, flags payload (per-entity bitstream: hasText, isCompressed)
    <variable gap>
    u32 sizeBufLen, size payload (u32 dictSize marker, then ULEB frame sizes)
    <variable gap>
    u32 zstdBufLen, zstd payload (dict of dictSize bytes, then frames)
    u32 entityCount
    <variable gap>
    directory: repeated [u32 pkgLen, pkg, u8, u32 childCount] groups, each child
               [u32 nameLen, name, u16, u8, u32 parentLen, parent]

Attribute frames: for each entity with hasText, read ULEB size from size buffer,
slice that many bytes from the zstd buffer; if isCompressed, the frame starts with
a ULEB decompressedLen; decompress with zstd using the dictionary.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path
from typing import Iterator, NamedTuple

try:
    import zstandard as _zstd
except ImportError:  # pragma: no cover
    _zstd = None


class PackagesBinError(Exception):
    pass


class Entity(NamedTuple):
    path: str
    parent: str
    attr: bytes | None  # raw frame (maybe compressed)
    decompressed_len: int
    compressed: bool


def _u32(d: memoryview, o: int) -> int:
    return struct.unpack_from("<I", d, o)[0]


def _read_uleb(d: memoryview, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(d):
            raise PackagesBinError("ULEB out of bounds")
        b = d[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 42:
            raise PackagesBinError("ULEB too long")


class _Bitstream:
    def __init__(self, data: memoryview):
        self._d = data
        self._pos = 0
        self._bit = 0
        self._byte = data[0] if len(data) else 0

    def next(self) -> int:
        bit = self._byte >> self._bit & 1
        self._bit += 1
        if self._bit > 7:
            self._pos += 1
            self._bit -= 8
            self._byte = self._d[self._pos] if self._pos < len(self._d) else 0
        return bit


class PackagesBin:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = memoryview(self.path.read_bytes())
        d = self.data
        if len(d) < 64:
            raise PackagesBinError("file too small")
        self.header_size = _u32(d, 16)
        self.version = _u32(d, 20)
        if self.version < 46:
            raise PackagesBinError(f"unsupported version {self.version}")
        self._locate()
        self._init_decompressor()

    # ---------------- header scanning ----------------

    def _locate(self):
        d = self.data
        n = len(d)

        def scan(start: int, low: int, high: int, window: int = 4000) -> int | None:
            probe = start
            limit = min(n - 4, start + window)
            while probe <= limit:
                v = _u32(d, probe)
                if low < v < high:
                    return probe
                probe += 1
            return None

        # refCount: after the prologue. The prologue itself has junk; find refCount by
        # locating a u32 in (1,1000) whose following entries parse as ref strings.
        ref_at = None
        probe = 24
        while probe < 4096:
            at = scan(probe, 1, 1000)
            if at is None:
                raise PackagesBinError("refCount not found")
            cnt = _u32(d, at)
            pos = at + 4
            ok = True
            for _ in range(cnt):
                if pos + 4 > n:
                    ok = False
                    break
                ln = _u32(d, pos)
                if not 1 <= ln <= 2000:
                    ok = False
                    break
                pos += 4 + ln + 2
            if ok and pos < n:
                ref_at = at
                break
            probe = at + 4
        if ref_at is None:
            raise PackagesBinError("refCount not found")

        self.ref_count = _u32(d, ref_at)
        refs_end = ref_at + 4
        for _ in range(self.ref_count):
            ln = _u32(d, refs_end)
            refs_end += 4 + ln + 2

        # flags buffer length: plausible size, then payload followed later by sizeBuf
        flags_at = None
        probe = refs_end
        while probe < refs_end + 8000:
            at = scan(probe, 10_000, 200_000)
            if at is None:
                raise PackagesBinError("flagsBufLen not found")
            # validate: after payload there must eventually be a sizeBuf with dict marker
            fend = at + 4 + _u32(d, at)
            if fend < n:
                sz = scan(fend, 100_000, 400_000, 4000)
                if sz is not None and _u32(d, sz + 4) == 1_048_576:
                    flags_at = at
                    break
            probe = at + 4
        if flags_at is None:
            raise PackagesBinError("flagsBufLen not found")
        self.flags_len = _u32(d, flags_at)
        self.flags_at = flags_at + 4

        # size buffer
        sz_at = scan(flags_at + 4 + self.flags_len, 100_000, 400_000, 8000)
        if sz_at is None:
            raise PackagesBinError("sizeBufLen not found")
        self.size_len = _u32(d, sz_at)
        self.size_at = sz_at + 4
        self.dict_size = _u32(d, self.size_at)

        # zstd buffer: length must be followed by a plausible entity count
        z_at = None
        probe = sz_at + 4 + self.size_len
        while probe < probe + 400_000:
            at = scan(probe, 5_000_000, 30_000_000, 400_000)
            if at is None:
                raise PackagesBinError("zstdBufLen not found")
            v = _u32(d, at)
            ec_at = at + 4 + v
            if ec_at + 4 < n:
                ec = _u32(d, ec_at)
                if 100_000 < ec < 800_000:
                    z_at = at
                    break
            probe = at + 4
        if z_at is None:
            raise PackagesBinError("zstdBufLen not found")
        self.zstd_len = _u32(d, z_at)
        self.zstd_at = z_at + 4

        # entity count
        ec_at = z_at + 4 + self.zstd_len
        self.entity_count = _u32(d, ec_at)

        # directory start: first pkg group header
        dir_at = scan(ec_at + 4, 5, 200, 4096)
        if dir_at is None:
            raise PackagesBinError("directory start not found")
        self.dir_at = dir_at

    def _init_decompressor(self):
        if _zstd is None:
            self._ddict = None
            return
        import zstandard
        raw = bytes(self.data[self.zstd_at : self.zstd_at + self.dict_size])
        self._ddict = zstandard.ZstdCompressionDict(raw)
        self._ctx = zstandard.ZstdDecompressor(dict_data=self._ddict)

    # ---------------- iteration ----------------

    def iter_entities(self) -> Iterator[Entity]:
        d = self.data
        flags = _Bitstream(self.data[self.flags_at : self.flags_at + self.flags_len])
        size = self.data[self.size_at + 4 : self.size_at + self.size_len]  # skip dict marker
        zpos = self.zstd_at + self.dict_size
        spos = 0
        pos = self.dir_at
        seen = 0
        while seen < self.entity_count:
            pkg_len = _u32(d, pos)
            pos += 4
            pkg = str(bytes(d[pos : pos + pkg_len]), "ascii", "replace")
            pos += pkg_len
            pos += 1  # u8
            children = _u32(d, pos)
            pos += 4
            for _ in range(children):
                if seen >= self.entity_count:
                    return
                name_len = _u32(d, pos)
                pos += 4
                name = str(bytes(d[pos : pos + name_len]), "ascii", "replace")
                pos += name_len
                pos += 3  # u16 + u8
                parent_len = _u32(d, pos)
                pos += 4
                parent = str(bytes(d[pos : pos + parent_len]), "ascii", "replace")
                pos += parent_len

                attr = None
                dlen = 0
                comp = False
                if flags.next():
                    fsize, spos = _read_uleb(size, spos)
                    comp = bool(flags.next())
                    frame = bytes(d[zpos : zpos + fsize])
                    zpos += fsize
                    if comp:
                        dlen, _ = _read_uleb(memoryview(frame), 0)
                        attr = frame
                    else:
                        dlen = fsize
                        attr = frame
                seen += 1
                if parent.startswith("/"):
                    parent_path = parent
                elif parent:
                    parent_path = pkg + parent
                else:
                    parent_path = ""
                yield Entity(pkg + name, parent_path, attr, dlen, comp)

    def decompress(self, entity: Entity) -> bytes:
        if entity.attr is None:
            return b""
        if not entity.compressed:
            return entity.attr
        if _zstd is None:
            raise PackagesBinError("zstandard module not installed")
        # strip the leading ULEB decompressedLen; the engine strips the zstd magic
        _, pos = _read_uleb(memoryview(entity.attr), 0)
        frame = b"\x28\xb5\x2f\xfd" + entity.attr[pos:]
        return self._ctx.decompress(frame, max_output_size=entity.decompressed_len)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    pb = PackagesBin(args.path)
    print(f"version={pb.version} entities={pb.entity_count} refs={pb.ref_count}")
    print(f"flags={pb.flags_len}B sizes={pb.size_len}B zstd={pb.zstd_len}B dict={pb.dict_size}")
    if args.stats:
        n = 0
        with_text = 0
        for e in pb.iter_entities():
            n += 1
            if e.attr is not None:
                with_text += 1
        print(f"entities={n} with_text={with_text}")
