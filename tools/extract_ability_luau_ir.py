from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import re
import struct
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_ability_luau_sources import (
    OPTIONAL_QUERY_TOKENS,
    REQUIRED_QUERY_TOKENS,
    UMBRA_ALIASES,
    _direct_script,
    _font_index,
    _load_json,
    _package_path,
    _script_path,
    _unique_abilities,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "warframe_build_data.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_warframe_data import parse_wiki_misc_fields, parse_wiki_scalars
from data_sources import provenance_path

# Scope deliberately stops at the current-build ability query path. This is
# not a general Luau VM; the mapping is evidence-backed by the client dispatch
# table and the 260 extracted GetAbilityUpgradeLevelInfo closures.
RAW_OPS = {
    0x01: ("GETTABLE", 1), 0x02: ("SETGLOBAL", 2), 0x04: ("LOADB", 1),
    0x06: ("SUBRK", 1), 0x07: ("SUB", 1), 0x09: ("MULK", 1),
    0x0C: ("FASTCALL2K", 2), 0x0D: ("LOADNIL", 1), 0x0E: ("MINUS", 1),
    0x10: ("FASTCALL", 1), 0x12: ("LOADN", 1), 0x13: ("GETUPVAL", 1),
    0x14: ("MOVE", 1), 0x15: ("SETTABLEKS", 2), 0x17: ("GETGLOBAL", 2),
    0x18: ("JUMPIFNOT", 1), 0x19: ("FASTCALL1", 1), 0x1A: ("DIV", 1),
    0x1B: ("FORGPREP_INEXT", 1), 0x1C: ("JUMPIFNOTLT", 2),
    0x1E: ("FORGLOOP", 2), 0x20: ("JUMPXEQKN", 2),
    0x21: ("JUMPIFLT", 1), 0x22: ("MUL", 1), 0x23: ("JUMPIFLE", 2),
    0x26: ("FASTCALL2", 2), 0x27: ("JUMPIFNOTEQ", 2), 0x28: ("CONCAT", 1),
    0x29: ("RETURN", 1), 0x2C: ("NEWTABLE", 2), 0x2D: ("NAMECALL", 2),
    0x2E: ("SETTABLEN", 1), 0x30: ("FORGPREP_NEXT", 1),
    0x32: ("DIVK", 1), 0x33: ("JUMPIFNOTLE", 2), 0x34: ("JUMPXEQKB", 2),
    0x37: ("JUMPIFEQ", 2), 0x38: ("ADDK", 1), 0x3A: ("JUMPXEQKNIL", 2),
    0x3B: ("DIVRK", 1), 0x3D: ("GETTABLEKS", 2), 0x3E: ("SUBK", 1),
    0x40: ("JUMP", 1), 0x42: ("DUPCLOSURE", 1), 0x44: ("GETTABLEN", 1),
    0x46: ("GETIMPORT", 2), 0x49: ("ADD", 1), 0x4B: ("JUMPIF", 1),
    0x4D: ("LENGTH", 1), 0x4E: ("LOADK", 1), 0x4F: ("DUPTABLE", 1),
    0x50: ("NOT", 1), 0x53: ("SETUPVAL", 1), 0x54: ("CALL", 1),
    0x11: ("PREPVARARGS", 1), 0x16: ("NEWCLOSURE", 1),
    0x35: ("CAPTURE", 1), 0x39: ("CLOSEUPVALS", 1),
}
RAW_AUX_OPCODES = {opcode for opcode, (_, width) in RAW_OPS.items() if width == 2}
MODIFIER_AXES = {3: "duration", 9: "range", 10: "strength"}

DELEGATED_QUERY_SCRIPTS = {
    "/Lotus/Powersuits/Trapper/Abilities/LevTrapAbility": "/Lotus/Powersuits/Trapper/Abilities/StasisProbe.lua",
    "/Lotus/Powersuits/Trapper/Abilities/TrapperStrikeAbility": "/Lotus/Powersuits/PowersuitAbilities/TrapperStrike.lua",
    "/Lotus/Powersuits/Trapper/Abilities/ZapTrapAbility": "/Lotus/Powersuits/Trapper/Abilities/ZapProbe.lua",
}

WIKI_FALLBACK_ABILITIES = {
    "/Lotus/Powersuits/Frost/Abilities/IcicleAbility": "Freeze",
}

WIKI_FIELD_OVERRIDES = {
    "/Lotus/Powersuits/Rhino/Abilities/RhinoDamageRoar.lua": {
        "/Lotus/Language/Game/ABILITY_RADIUS": ("Roar", r":\s*(\d+(?:\s*/\s*\d+){3})\s*m"),
        "/Lotus/Language/Menu/DURATION": ("Roar", r":\s*(\d+(?:\.\d+)?)\s*s"),
        "/Lotus/Language/Game/SYMBIOTIC_DAMAGE_BOOST_NO_UNIT": ("Roar", r":\s*(\d+(?:\s*/\s*\d+){3})\s*%"),
    },
    "/Lotus/Powersuits/Ninja/Abilities/SmokeScreen.lua": {
        "/Lotus/Language/Game/ABILITY_RADIUS": ("Smoke Screen", r"radius of\s+(\d+(?:\.\d+)?)\s+meters"),
    },
}


def _font_header_index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.lua_H"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("Debug/"):
            relative = relative[len("Debug/") :]
        internal = "/" + relative.removesuffix("_H").lstrip("/")
        result.setdefault(internal.casefold(), path)
    return result

class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError(
                f"truncated at 0x{self.offset:x}: need {size}, "
                f"remain {len(self.data) - self.offset}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack("<d", self.take(8))[0]

    def varint(self, *, bits: int = 32) -> int:
        value = 0
        shift = 0
        while True:
            byte = self.u8()
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7
            if shift >= bits + 7:
                raise ValueError(f"oversized varint ending at 0x{self.offset:x}")


def _string(strings: list[str], string_id: int) -> str | None:
    if string_id == 0:
        return None
    if string_id > len(strings):
        raise ValueError(f"invalid string id {string_id}; table has {len(strings)} entries")
    return strings[string_id - 1]


def _read_constant(reader: Reader, strings: list[str]) -> dict[str, Any]:
    offset = reader.offset
    tag = reader.u8()
    result: dict[str, Any] = {"tag": tag, "offset": offset}
    if tag == 0:
        result["kind"] = "nil"
    elif tag == 1:
        # The current client stores a four-byte private atom/hash payload in
        # the legacy boolean slot. Preserve it; treating it as bool or number
        # changes program semantics.
        result.update(kind="private32", raw=reader.u32())
    elif tag == 2:
        result.update(kind="number", value=reader.f64())
    elif tag == 3:
        string_id = reader.varint()
        result.update(kind="string", stringId=string_id, value=_string(strings, string_id))
    elif tag == 4:
        result.update(kind="import", value=reader.u32())
    elif tag == 5:
        result.update(kind="table", keys=[reader.varint() for _ in range(reader.varint())])
    elif tag == 6:
        result.update(kind="closure", proto=reader.varint())
    elif tag == 7:
        result.update(kind="vector", raw=reader.take(16).hex())
    elif tag == 8:
        result.update(
            kind="tableWithConstants",
            entries=[
                {"key": reader.varint(), "constant": reader.i32()}
                for _ in range(reader.varint())
            ],
        )
    elif tag == 9:
        negative = bool(reader.u8())
        magnitude = reader.varint(bits=64)
        result.update(kind="integer", value=-magnitude if negative else magnitude)
    else:
        # Current-build private tags have no payload. Keeping the original tag
        # lets a future decoder distinguish them without desynchronizing IR.
        result.update(kind="privateNil")
    return result


def parse_chunk(data: bytes) -> dict[str, Any]:
    reader = Reader(data)
    version = reader.u8()
    type_version = reader.u8() if version >= 4 else 0
    if (version, type_version) != (9, 3):
        raise ValueError(f"unsupported Luau header {version}/{type_version}; expected 9/3")

    strings = [
        reader.take(reader.varint()).decode("utf-8", errors="replace")
        for _ in range(reader.varint())
    ]
    userdata_remaps = []
    while True:
        index = reader.u8()
        if index == 0:
            break
        string_id = reader.varint()
        userdata_remaps.append({"index": index, "stringId": string_id, "name": _string(strings, string_id)})

    proto_count = reader.varint()
    protos: list[dict[str, Any]] = []
    all_word_low_bytes: Counter[str] = Counter()
    constant_tags: Counter[str] = Counter()
    for proto_index in range(proto_count):
        proto_offset = reader.offset
        max_stack, params, upvalues, vararg = (reader.u8() for _ in range(4))
        flags = reader.u8()
        type_info = reader.take(reader.varint())
        code_offset = reader.offset
        words = [reader.u32() for _ in range(reader.varint())]
        code_words = [f"{word:08x}" for word in words]
        all_word_low_bytes.update(f"0x{word & 0xFF:02x}" for word in words)

        constants = [_read_constant(reader, strings) for _ in range(reader.varint())]
        constant_tags.update(str(row["tag"]) for row in constants)
        children = [reader.varint() for _ in range(reader.varint())]
        line_defined = reader.varint()
        debug_name_id = reader.varint()

        if reader.u8():
            line_gap_log2 = reader.u8()
            reader.take(len(words))
            intervals = ((len(words) - 1) >> line_gap_log2) + 1 if words else 0
            reader.take(intervals * 4)
        if reader.u8():
            for _ in range(reader.varint()):
                reader.varint()  # local name
                reader.varint()  # start pc
                reader.varint()  # end pc
                reader.u8()      # register
            for _ in range(reader.varint()):
                reader.varint()  # upvalue name

        constant_strings = [row.get("value") for row in constants if row.get("kind") == "string"]
        protos.append({
            "index": proto_index,
            "offset": proto_offset,
            "endOffset": reader.offset,
            "codeOffset": code_offset,
            "maxStack": max_stack,
            "params": params,
            "upvalues": upvalues,
            "vararg": bool(vararg),
            "flags": flags,
            "typeInfo": type_info.hex(),
            "lineDefined": line_defined,
            "debugName": _string(strings, debug_name_id),
            "children": children,
            "codeWords": code_words,
            "constants": constants,
            "queryCandidate": "Label" in constant_strings and "Value" in constant_strings,
        })

    main_proto = reader.varint()
    if reader.offset != len(data):
        raise ValueError(f"trailing bytes at 0x{reader.offset:x}: {len(data) - reader.offset}")

    string_set = set(strings)
    query_tokens = {
        token: token in string_set
        for token in (*REQUIRED_QUERY_TOKENS, *OPTIONAL_QUERY_TOKENS)
    }
    upgrade_protos = []
    fallback_protos = []
    for proto in protos:
        values = {row.get("value") for row in proto["constants"] if row.get("kind") == "string"}
        if "AbilityUpgradeLevelInfo" in values:
            upgrade_protos.append(proto["index"])
        elif proto["queryCandidate"]:
            fallback_protos.append(proto["index"])
    return {
        "version": version,
        "typeVersion": type_version,
        "bytes": len(data),
        "consumed": reader.offset,
        "mainProto": main_proto,
        "strings": strings,
        "userdataRemaps": userdata_remaps,
        "protos": protos,
        "codeWordLowByteCounts": dict(sorted(all_word_low_bytes.items())),
        "constantTagCounts": dict(sorted(constant_tags.items(), key=lambda row: int(row[0]))),
        "queryTokens": query_tokens,
        "queryProtoCandidates": upgrade_protos or fallback_protos,
        "localizationKeys": sorted(value for value in string_set if value.startswith("/Lotus/Language/")),
    }


def _constant_value(constants: list[dict[str, Any]], index: int) -> Any:
    if index < 0:
        return {"kind": "dynamic"}
    if index >= len(constants):
        return {"kind": "rawAtom", "value": index}
    value = constants[index]
    if value["kind"] in {"string", "number", "integer"}:
        return value.get("value")
    if value["kind"] == "private32":
        return {"kind": "private32", "raw": value["raw"]}
    return {"kind": value["kind"]}


def _parts(word: str) -> tuple[int, int, int, int, int]:
    value = int(word, 16)
    opcode = value & 0xFF
    a = (value >> 8) & 0xFF
    b = (value >> 16) & 0xFF
    c = (value >> 24) & 0xFF
    d = (value >> 16) & 0xFFFF
    return opcode, a, b, c, d


def _signed_d(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _instructions(proto: dict[str, Any]) -> list[dict[str, Any]]:
    words = [int(value, 16) for value in proto["codeWords"]]
    result = []
    pc = 0
    while pc < len(words):
        word = words[pc]
        opcode, a, b, c, d = _parts(f"{word:08x}")
        semantic, width = RAW_OPS.get(opcode, (f"raw_0x{opcode:02x}", 1))
        if pc + width > len(words):
            raise ValueError(f"P{proto['index']} {semantic} has truncated AUX at pc {pc}")
        result.append({
            "pc": pc,
            "op": opcode,
            "semantic": semantic,
            "a": a,
            "b": b,
            "c": c,
            "d": d,
            "sd": _signed_d(d),
            "aux": words[pc + 1] if width == 2 else None,
            "width": width,
        })
        pc += width
    return result


def _aux_constant(proto: dict[str, Any], auxiliary: int | None) -> Any:
    if auxiliary is None:
        return {"kind": "missingAux"}
    return _constant_value(proto["constants"], int(auxiliary))


def _closure_graph(ir: dict[str, Any]) -> tuple[dict[int, int], dict[int, list[dict[str, int]]]]:
    main = ir["protos"][ir["mainProto"]]
    constants = main["constants"]
    register_protos: dict[int, int] = {}
    captures: dict[int, list[dict[str, int]]] = {}
    instructions = _instructions(main)
    index = 0
    while index < len(instructions):
        instruction = instructions[index]
        opcode, register, operand = instruction["op"], instruction["a"], instruction["d"]
        child = None
        if opcode == 0x16 and operand < len(main["children"]):  # NEWCLOSURE uses the parent's child ordinal.
            child = main["children"][operand]
        elif opcode == 0x42 and operand < len(constants):  # DUPCLOSURE
            constant = constants[operand]
            if constant["kind"] == "closure":
                child = int(constant["proto"])
        if child is None:
            index += 1
            continue
        upvalue_count = int(ir["protos"][child]["upvalues"])
        raw_captures = []
        for offset in range(1, upvalue_count + 1):
            if index + offset >= len(instructions):
                raw_captures = []
                break
            capture = instructions[index + offset]
            capture_opcode, kind, source = capture["op"], capture["a"], capture["b"]
            if capture_opcode != 0x35:
                raw_captures = []
                break
            raw_captures.append({"kind": kind, "source": source})
        if len(raw_captures) == upvalue_count:
            register_protos[register] = child
            captures[child] = raw_captures
            index += upvalue_count + 1
        else:
            index += 1
    return register_protos, captures


def _literal(constants: list[dict[str, Any]], opcode: int, operand: int) -> int | float | None:
    if opcode == 0x12:  # LOADN, signed D
        return operand - 0x10000 if operand & 0x8000 else operand
    if opcode == 0x4E and operand < len(constants):  # LOADK
        value = constants[operand]
        if value["kind"] in {"number", "integer"}:
            return value.get("value")
    return None


def _rank_vectors(proto: dict[str, Any]) -> dict[str, dict[int, list[int | float]]]:
    words = proto["codeWords"]
    constants = proto["constants"]

    def assignments(start: int, end: int) -> tuple[dict[int, int | float], dict[int, int | float]]:
        upvalues: dict[int, int | float] = {}
        globals_: dict[int, int | float] = {}
        for pc in range(start, min(end, len(words) - 1)):
            opcode, register, _, _, operand = _parts(words[pc])
            value = _literal(constants, opcode, operand)
            next_opcode, source_register, upvalue, _, _ = _parts(words[pc + 1])
            if value is None or source_register != register:
                continue
            if next_opcode == 0x53:  # SETUPVAL
                upvalues[upvalue] = value
            elif next_opcode == 0x02:  # SETGLOBAL, AUX contains the atom/constant id
                globals_[int(words[pc + 1], 16)] = value
        return upvalues, globals_

    comparisons = []
    for pc in range(len(words) - 1):
        opcode, _, _, _, offset = _parts(words[pc])
        if opcode != 0x20:  # JUMPXEQKN
            continue
        constant_index = int(words[pc + 1], 16) & 0xFFFFFF
        value = _constant_value(constants, constant_index)
        if value in (1, 2, 3):
            comparisons.append((pc, int(value), pc + 1 + offset))
    for index in range(len(comparisons) - 2):
        branch = comparisons[index:index + 3]
        if [row[1] for row in branch] != [1, 2, 3]:
            continue
        rank_rows = [assignments(pc + 2, target) for pc, _, target in branch]
        else_start = branch[-1][2]
        else_end = next(
            (pc for pc in range(else_start, len(words)) if _parts(words[pc])[0] == 0x29),
            len(words),
        )
        rank_rows.append(assignments(else_start, else_end))
        result = {"upvalue": {}, "global": {}}
        for kind, row_index in (("upvalue", 0), ("global", 1)):
            for row in rank_rows:
                for target, value in row[row_index].items():
                    result[kind].setdefault(target, []).append(value)
            result[kind] = {target: values for target, values in result[kind].items() if len(values) == 4}
        return result

    fallback = {"upvalue": {}, "global": {}}
    for pc in range(len(words) - 1):
        opcode, register, _, _, operand = _parts(words[pc])
        value = _literal(constants, opcode, operand)
        next_opcode, source_register, upvalue, _, _ = _parts(words[pc + 1])
        if value is None or source_register != register:
            continue
        if next_opcode == 0x53:
            fallback["upvalue"].setdefault(upvalue, []).append(value)
        elif next_opcode == 0x02:
            fallback["global"].setdefault(int(words[pc + 1], 16), []).append(value)
    for kind in fallback:
        fallback[kind] = {target: values[:4] for target, values in fallback[kind].items()}
    return fallback


def _range_vectors(proto: dict[str, Any]) -> dict[int, dict[str, list[int | float]]]:
    """Recover strict rank objects built from two numeric constructor args."""
    words = proto["codeWords"]
    constants = proto["constants"]
    comparisons = []
    for pc in range(len(words) - 1):
        opcode, _, _, _, offset = _parts(words[pc])
        if opcode != 0x20:
            continue
        value = _constant_value(constants, int(words[pc + 1], 16) & 0xFFFFFF)
        if value in (1, 2, 3):
            comparisons.append((pc, int(value), pc + 1 + offset))
    for index in range(len(comparisons) - 2):
        branch = comparisons[index:index + 3]
        if [row[1] for row in branch] != [1, 2, 3]:
            continue
        bounds = [(pc + 2, target) for pc, _, target in branch]
        else_start = branch[-1][2]
        else_end = next((pc for pc in range(else_start, len(words)) if _parts(words[pc])[0] == 0x29), len(words))
        bounds.append((else_start, else_end))
        rank_rows = []
        for start, end in bounds:
            registers: dict[int, Any] = {}
            upvalues: dict[int, dict[str, int | float]] = {}
            pc = start
            while pc < min(end, len(words)):
                opcode, a, b, c, d = _parts(words[pc])
                width = RAW_OPS.get(opcode, ("", 1))[1]
                if opcode == 0x12:
                    registers[a] = _signed_d(d)
                elif opcode == 0x4E:
                    registers[a] = _vm_constant(proto, d)
                elif opcode == 0x14:
                    registers[a] = registers.get(b)
                elif opcode == 0x46:
                    registers[a] = ("callable",)
                elif opcode == 0x54:
                    args = [registers.get(a + offset) for offset in range(1, b)]
                    registers[a] = (
                        {"minValue": args[0], "maxValue": args[1]}
                        if registers.get(a) == ("callable",) and len(args) == 2
                        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in args)
                        else None
                    )
                elif opcode == 0x53 and isinstance(registers.get(a), dict) and set(registers[a]) == {"minValue", "maxValue"}:
                    upvalues[b] = registers[a]
                pc += width
            rank_rows.append(upvalues)
        targets = set.intersection(*(set(row) for row in rank_rows)) if rank_rows else set()
        return {
            target: {
                "minValue": [row[target]["minValue"] for row in rank_rows],
                "maxValue": [row[target]["maxValue"] for row in rank_rows],
            }
            for target in targets
        }
    return {}


def _query_upvalue_vectors(ir: dict[str, Any], query_proto: int) -> dict[int, list[int | float]]:
    register_protos, captures = _closure_graph(ir)
    query_captures = captures.get(query_proto) or []
    setter_protos = {
        register_protos[capture["source"]]
        for capture in query_captures
        if capture["kind"] == 0 and capture["source"] in register_protos
    }
    result: dict[int, list[int | float]] = {}
    for query_upvalue, query_capture in enumerate(query_captures):
        if query_capture["kind"] != 1:  # only shared REF captures can be updated by a sibling closure
            continue
        for setter_proto in setter_protos:
            setter_vectors = _rank_vectors(ir["protos"][setter_proto])["upvalue"]
            for setter_upvalue, setter_capture in enumerate(captures.get(setter_proto) or []):
                if (
                    setter_capture["kind"] == 1
                    and setter_capture["source"] == query_capture["source"]
                    and setter_upvalue in setter_vectors
                ):
                    result[query_upvalue] = setter_vectors[setter_upvalue]
                    break
            if query_upvalue in result:
                break
    return result


def _rank_vectors_for_query(
    ir: dict[str, Any],
    query: dict[str, Any],
    query_proto: dict[str, Any],
    rank_helper: dict[str, Any] | None,
) -> dict[str, dict[Any, list[int | float]]]:
    """Map rank-helper assignments back to query upvalues/global atoms."""
    direct = _rank_vectors(query_proto)
    result: dict[str, dict[Any, list[int | float]]] = {
        "upvalue": dict(direct["upvalue"]),
        "global": dict(direct["global"]),
    }
    if not rank_helper:
        return result
    helper_proto = ir["protos"][rank_helper["proto"]]
    helper_vectors = _rank_vectors(helper_proto)
    helper_captures = rank_helper.get("captures") or []
    for helper_upvalue, helper_capture in enumerate(helper_captures):
        if helper_capture.get("kind") != 1:
            continue
        for query_upvalue, query_capture in enumerate(query.get("captures") or []):
            if query_capture.get("kind") == 1 and query_capture.get("sourceRegister") == helper_capture.get("sourceRegister"):
                if helper_upvalue in helper_vectors["upvalue"]:
                    result["upvalue"][query_upvalue] = helper_vectors["upvalue"][helper_upvalue]
                range_values = _range_vectors(helper_proto).get(helper_upvalue)
                if range_values:
                    for key, values in range_values.items():
                        result["upvalue"][("range", query_upvalue, key)] = values
    result["global"].update(helper_vectors["global"])
    return result


def _value_source(proto: dict[str, Any], table_constant: int) -> dict[str, Any]:
    words = proto["codeWords"]
    constants = proto["constants"]
    value_key = next(
        (index for index, value in enumerate(constants) if value.get("kind") == "string" and value.get("value") == "Value"),
        None,
    )
    if value_key is None:
        return {"kind": "dynamic"}
    for pc, word in enumerate(words):
        opcode, table_register, _, _, operand = _parts(word)
        if opcode != 0x4F or operand != table_constant:  # DUPTABLE
            continue
        for set_pc in range(pc + 1, min(pc + 14, len(words) - 1)):
            set_opcode, source_register, target_register, _, _ = _parts(words[set_pc])
            if (
                set_opcode != 0x15
                or target_register != table_register
                or int(words[set_pc + 1], 16) != value_key
            ):
                continue
            for source_pc in range(set_pc - 1, pc, -1):
                source_opcode, target, source, _, source_operand = _parts(words[source_pc])
                if target != source_register:
                    continue
                if source_opcode == 0x13:  # GETUPVAL
                    return {"kind": "upvalue", "index": source}
                if source_opcode == 0x17 and source_pc + 1 < set_pc:  # GETGLOBAL
                    index = int(words[source_pc + 1], 16)
                    return {
                        "kind": "global",
                        "atom": index,
                    }
                literal = _literal(constants, source_opcode, source_operand)
                if literal is not None:
                    return {"kind": "literal", "value": literal}
                return {"kind": "expression", "rawOpcode": f"0x{source_opcode:02x}"}
    return {"kind": "dynamic"}


def _vm_constant(proto: dict[str, Any], index: int) -> Any:
    if index < 0 or index >= len(proto["constants"]):
        return ("rawAtom", index)
    constant = proto["constants"][index]
    if constant["kind"] in {"number", "integer", "string"}:
        return constant.get("value")
    if constant["kind"] == "private32":
        return ("private32", constant["raw"])
    if constant["kind"] == "closure":
        return ("closureConstant", constant["proto"])
    return (constant["kind"], index)


def _scan_main(ir: dict[str, Any]) -> tuple[dict[int, Any], dict[int, dict[str, Any]]]:
    """Collect only the top-level closures and captured initializer values."""
    proto = ir["protos"][ir["mainProto"]]
    registers: dict[int, Any] = {}
    closures: dict[int, dict[str, Any]] = {}
    instructions = _instructions(proto)
    index = 0
    while index < len(instructions):
        row = instructions[index]
        op, a, b, d = row["op"], row["a"], row["b"], row["d"]
        if op == 0x12:  # LOADN
            registers[a] = row["sd"]
        elif op == 0x4E:  # LOADK
            registers[a] = _vm_constant(proto, d)
        elif op == 0x0D:  # LOADNIL
            registers[a] = None
        elif op == 0x14:  # MOVE
            registers[a] = registers.get(b)
        elif op in {0x16, 0x42}:  # NEWCLOSURE / DUPCLOSURE
            child = d if op == 0x16 else None
            if op == 0x16 and d < len(proto["children"]):
                child = proto["children"][d]
            if op == 0x42 and d < len(proto["constants"]):
                constant = proto["constants"][d]
                child = int(constant["proto"]) if constant["kind"] == "closure" else None
            if child is None or child >= len(ir["protos"]):
                index += 1
                continue
            captures = []
            for capture in instructions[index + 1:index + 1 + ir["protos"][child]["upvalues"]]:
                if capture["op"] != 0x35:
                    captures = []
                    break
                captures.append({
                    "kind": capture["a"],
                    "sourceRegister": capture["b"],
                    "value": registers.get(capture["b"]),
                })
            if len(captures) == ir["protos"][child]["upvalues"]:
                closure = {"proto": child, "captures": captures}
                registers[a] = closure
                closures[child] = closure
                index += len(captures)
        index += 1
    return registers, closures


def _rank_helper_capture(query: dict[str, Any], query_proto: dict[str, Any]) -> dict[str, Any] | None:
    """Find the closure actually invoked with AbilityLevelQueryParms.Level."""
    instructions = _instructions(query_proto)
    for index, row in enumerate(instructions[:-1]):
        if row["op"] != 0x13 or row["b"] >= len(query["captures"]):  # GETUPVAL
            continue
        capture = query["captures"][row["b"]]
        closure = capture.get("value")
        if not isinstance(closure, dict) or "proto" not in closure:
            continue
        target_register = row["a"]
        if any(next_row["op"] == 0x54 and next_row["a"] == target_register for next_row in instructions[index + 1:index + 7]):
            return closure
    return next(
        (
            capture["value"]
            for capture in query["captures"]
            if isinstance(capture.get("value"), dict) and "proto" in capture["value"]
        ),
        None,
    )


def _known_method(base: Any, key: Any) -> tuple[str, Any, Any]:
    return ("method", base, key)


def _pve_call(target: Any, args: list[Any]) -> Any:
    if not isinstance(target, tuple) or not target or target[0] != "method":
        return ("opaqueCall",)
    base = str(target[1] or "")
    # Every query rank helper uses the same client-only PvP probe; normal
    # Warframe builds must take its false branch.
    if base == "PVP_LIB" and len(args) == 0:
        return False
    # AbilityLib's rank/PvP helper receives (isPvp, pvpValue, pveValue).
    # Its use is limited to a captured ability library and three arguments.
    if base == "TERNARY_LIB" and len(args) == 3:
        return args[2]
    return ("opaqueCall",)


def _truthy(value: Any) -> bool | None:
    if isinstance(value, tuple) and value and value[0] == "opaqueCall":
        return None
    return bool(value)


def _run_rank_helper(
    ir: dict[str, Any],
    closure: dict[str, Any],
    rank: int,
    module_registers: dict[int, Any],
) -> tuple[dict[int, Any], dict[Any, Any]]:
    """Execute the small rank-only subset; unsupported paths fail closed."""
    proto = ir["protos"][closure["proto"]]
    ops = {row["pc"]: row for row in _instructions(proto)}
    upvalues = {index: capture.get("value") for index, capture in enumerate(closure["captures"])}
    if 0 in upvalues:
        upvalues[0] = "PVP_LIB"
    if any(row["op"] == 0x54 and row["b"] == 4 for row in ops.values()) and 1 in upvalues:
        upvalues[1] = "TERNARY_LIB"
    registers: dict[int, Any] = {0: rank}
    module = dict(module_registers)
    globals_: dict[Any, Any] = {}
    pc = 0
    steps = 0
    conditional_ops = {0x18, 0x4B, 0x20, 0x21, 0x23, 0x27, 0x33, 0x34, 0x37, 0x3A}
    while pc in ops:
        steps += 1
        if steps > 1024:
            raise ValueError(f"rank helper P{closure['proto']} did not terminate")
        row = ops[pc]
        op, a, b, c, d, aux = row["op"], row["a"], row["b"], row["c"], row["d"], row["aux"]
        next_pc = pc + row["width"]
        if op == 0x13:  # GETUPVAL
            registers[a] = upvalues.get(b)
        elif op == 0x12:  # LOADN
            registers[a] = row["sd"]
        elif op == 0x4E:  # LOADK
            registers[a] = _vm_constant(proto, d)
        elif op == 0x04:  # LOADB
            registers[a] = bool(b)
            if c:
                next_pc += 1
        elif op == 0x0D:  # LOADNIL
            registers[a] = None
        elif op == 0x14:  # MOVE
            registers[a] = registers.get(b)
        elif op == 0x3D:  # GETTABLEKS
            base = registers.get(b)
            key = _vm_constant(proto, int(aux or 0))
            registers[a] = base.get(key) if isinstance(base, dict) else _known_method(base, key)
        elif op == 0x46:  # GETIMPORT
            registers[a] = False if next_pc in ops and ops[next_pc]["op"] in conditional_ops else ("opaqueCall",)
        elif op == 0x01:  # GETTABLE
            table = registers.get(b)
            key = registers.get(c)
            registers[a] = table.get(key) if isinstance(table, dict) else _known_method(table, key)
        elif op == 0x44:  # GETTABLEN
            table = registers.get(b)
            registers[a] = table.get(c + 1) if isinstance(table, dict) else None
        elif op == 0x17:  # GETGLOBAL
            registers[a] = globals_.get(_vm_constant(proto, int(aux or 0)))
        elif op == 0x02:  # SETGLOBAL
            globals_[_vm_constant(proto, int(aux or 0))] = registers.get(a)
        elif op == 0x53:  # SETUPVAL
            upvalues[b] = registers.get(a)
            capture = closure["captures"][b]
            if capture["kind"] == 1:
                module[capture["sourceRegister"]] = registers.get(a)
        elif op == 0x54:  # CALL
            count = b - 1 if b else 0
            arguments = [registers.get(a + offset) for offset in range(1, count + 1)]
            result = _pve_call(registers.get(a), arguments)
            if isinstance(result, tuple) and result and result[0] == "opaqueCall" and next_pc in ops and ops[next_pc]["op"] in conditional_ops:
                result = False
            registers[a] = result
        elif op in {0x06, 0x07, 0x09, 0x1A, 0x22, 0x32, 0x38, 0x3B, 0x3E, 0x49}:
            left, right = registers.get(b), registers.get(c)
            if op in {0x09, 0x32, 0x38, 0x3E}:
                right = _vm_constant(proto, c)
            if op == 0x06:
                left, right = _vm_constant(proto, b), registers.get(c)
            elif op == 0x3B:
                left, right = _vm_constant(proto, b), registers.get(c)
            try:
                registers[a] = {
                    0x06: lambda: left - right, 0x07: lambda: left - right,
                    0x09: lambda: left * right, 0x1A: lambda: left / right,
                    0x22: lambda: left * right, 0x32: lambda: left / right,
                    0x38: lambda: left + right, 0x3B: lambda: left / right,
                    0x3E: lambda: left - right, 0x49: lambda: left + right,
                }[op]()
            except (TypeError, ZeroDivisionError):
                registers[a] = ("opaqueCall",)
        elif op == 0x0E:  # MINUS
            value = registers.get(b)
            registers[a] = -value if isinstance(value, (int, float)) else ("opaqueCall",)
        elif op == 0x50:  # NOT
            value = _truthy(registers.get(b))
            registers[a] = not value if value is not None else ("opaqueCall",)
        elif op == 0x40:  # JUMP
            next_pc = pc + 1 + row["sd"]
        elif op in {0x18, 0x4B}:  # JUMPIFNOT / JUMPIF
            value = _truthy(registers.get(a))
            if value is None:
                raise ValueError(f"P{closure['proto']} opaque conditional at pc {pc}")
            should_jump = not value if op == 0x18 else value
            if should_jump:
                next_pc = pc + 1 + row["sd"]
        elif op == 0x20:  # JUMPXEQKN
            equal = registers.get(a) == _vm_constant(proto, int(aux or 0) & 0xFFFFFF)
            if equal != bool((int(aux or 0) >> 31) & 1):
                next_pc = pc + 1 + row["sd"]
        elif op == 0x34:  # JUMPXEQKB
            equal = bool(registers.get(a)) == bool(int(aux or 0) & 1)
            if equal != bool((int(aux or 0) >> 31) & 1):
                next_pc = pc + 1 + row["sd"]
        elif op == 0x3A:  # JUMPXEQKNIL
            equal = registers.get(a) is None
            if equal != bool((int(aux or 0) >> 31) & 1):
                next_pc = pc + 1 + row["sd"]
        elif op in {0x1C, 0x21, 0x23, 0x27, 0x33, 0x37}:
            left, right = registers.get(a), registers.get(b)
            if op in {0x1C, 0x21, 0x23, 0x27, 0x33, 0x37} and aux is not None:
                right = registers.get(int(aux) & 0xFF)
            try:
                condition = {
                    0x1C: not (left < right), 0x21: left < right, 0x23: left <= right, 0x27: left != right,
                    0x33: not (left <= right), 0x37: left == right,
                }[op]
            except TypeError:
                raise ValueError(f"P{closure['proto']} opaque comparison at pc {pc}") from None
            if condition:
                next_pc = pc + 1 + row["sd"]
        elif op == 0x29:  # RETURN
            break
        elif op in {0x10, 0x19, 0x0C, 0x26}:  # FASTCALL hints; CALL carries the semantics.
            pass
        else:
            raise ValueError(f"P{closure['proto']} unsupported {row['semantic']} at pc {pc}")
        pc = next_pc
    return module, globals_


def _rank_branch_profile(proto: dict[str, Any]) -> dict[str, Any]:
    comparisons = []
    for row in _instructions(proto):
        if row["op"] != 0x20:
            continue
        value = _vm_constant(proto, int(row["aux"] or 0) & 0xFFFFFF)
        if isinstance(value, (int, float)):
            comparisons.append(value)
    normal_groups = sum(
        comparisons[index:index + 3] == [1, 2, 3]
        for index in range(max(0, len(comparisons) - 2))
    )
    return {
        "comparisons": comparisons,
        "normalGroups": normal_groups,
        "ambiguousStaticBranch": normal_groups != 1 or len(comparisons) != 3,
    }


def _runtime_query_rows(proto: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    instructions = _instructions(proto)
    fastcall1 = {
        candidate["pc"] + 1 + candidate["c"]: candidate
        for candidate in instructions
        if candidate["op"] == 0x19
    }
    for index, row in enumerate(instructions):
        if row["op"] != 0x4F or row["d"] >= len(proto["constants"]):  # DUPTABLE
            continue
        template = proto["constants"][row["d"]]
        if template["kind"] != "tableWithConstants":
            continue
        metadata = {
            str(_vm_constant(proto, entry["key"])): (
                _vm_constant(proto, entry["constant"]) if entry["constant"] >= 0 else None
            )
            for entry in template["entries"]
        }
        if "Label" not in metadata or "Value" not in metadata:
            continue
        definitions: dict[int, tuple[str, Any]] = {}
        source: tuple[str, Any] = ("static", metadata["Value"])
        for candidate in instructions[index + 1:]:
            if candidate["op"] == 0x4F:
                break
            if candidate["op"] == 0x13:
                definitions[candidate["a"]] = ("upvalue", candidate["b"])
            elif candidate["op"] == 0x17:
                definitions[candidate["a"]] = ("global", _vm_constant(proto, int(candidate["aux"] or 0)))
            elif candidate["op"] == 0x12:
                definitions[candidate["a"]] = ("static", candidate["sd"])
            elif candidate["op"] == 0x4E:
                definitions[candidate["a"]] = ("static", _vm_constant(proto, candidate["d"]))
            elif candidate["op"] == 0x14 and candidate["b"] in definitions:
                definitions[candidate["a"]] = definitions[candidate["b"]]
            elif candidate["op"] in {0x09, 0x32, 0x38, 0x3E} and candidate["b"] in definitions:
                constant = _vm_constant(proto, candidate["c"])
                if isinstance(constant, (int, float)):
                    definitions[candidate["a"]] = (
                        {0x09: "mulK", 0x32: "divK", 0x38: "addK", 0x3E: "subK"}[candidate["op"]],
                        definitions[candidate["b"]],
                        constant,
                    )
            elif candidate["op"] in {0x06, 0x3B} and candidate["c"] in definitions:
                constant = _vm_constant(proto, candidate["b"])
                if isinstance(constant, (int, float)):
                    definitions[candidate["a"]] = (
                        {0x06: "subRK", 0x3B: "divRK"}[candidate["op"]],
                        constant,
                        definitions[candidate["c"]],
                    )
            elif candidate["op"] in {0x07, 0x1A, 0x22, 0x49} and candidate["b"] in definitions and candidate["c"] in definitions:
                definitions[candidate["a"]] = (
                    {0x07: "sub", 0x1A: "div", 0x22: "mul", 0x49: "add"}[candidate["op"]],
                    definitions[candidate["b"]],
                    definitions[candidate["c"]],
                )
            elif candidate["op"] == 0x54 and candidate["b"] == 2:
                fastcall = fastcall1.get(candidate["pc"])
                if fastcall and fastcall["b"] in definitions:
                    definitions[candidate["a"]] = (
                        "unaryBuiltin",
                        definitions[fastcall["b"]],
                        fastcall["a"],
                    )
            elif candidate["op"] == 0x15 and candidate["b"] == row["a"]:
                if _vm_constant(proto, int(candidate["aux"] or 0)) == "Value":
                    source = definitions.get(candidate["a"], ("expression", candidate["a"]))
                    break
        rows.append({"labelKey": metadata.pop("Label"), "metadata": metadata, "source": source})
    for field in rows:
        source = field["source"]
        if source[0] != "upvalue":
            continue
        for index, row in enumerate(instructions[:-1]):
            if row["op"] != 0x13 or row["b"] != source[1]:
                continue
            following = instructions[index + 1]
            if following["op"] == 0x3D and following["b"] == row["a"]:
                key = _vm_constant(proto, int(following["aux"] or 0))
                if key in {"minValue", "maxValue"}:
                    field["source"] = ("rangeMember", source, key)
                    break
    return rows


def _source_root(source: tuple[str, Any]) -> tuple[str, Any]:
    while source and source[0] in {"mulK", "divK", "addK", "subK", "subRK", "divRK", "unaryBuiltin", "rangeMember"}:
        if source[0] == "rangeMember":
            source = source[1]
            continue
        source = source[2] if source[0] in {"subRK", "divRK"} else source[1]
    return source


def _source_values(
    source: tuple[str, Any],
    upvalues: dict[int, list[int | float]],
    globals_: dict[Any, list[int | float]],
) -> list[int | float] | None:
    kind = source[0]
    if kind == "upvalue":
        return upvalues.get(source[1])
    if kind == "global":
        return globals_.get(source[1])
    if kind == "static" and isinstance(source[1], (int, float)):
        return [source[1]] * 4
    if kind == "rangeMember":
        return upvalues.get(("range", source[1][1], source[2]))
    if kind == "unaryBuiltin":
        values = _source_values(source[1], upvalues, globals_)
        if not values:
            return None
        builtin = source[2]
        if builtin == 12:  # LBF_MATH_FLOOR
            return [math.floor(value) for value in values]
        if builtin == 19:  # LBF_MATH_MIN with one argument
            return values
        if builtin == 48:  # LBF_MATH_ROUND: C round, halfway away from zero
            return [math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5) for value in values]
        return None
    if kind in {"subRK", "divRK"}:
        values = _source_values(source[2], upvalues, globals_)
        constant = source[1]
        if not values:
            return None
        try:
            return [constant - value if kind == "subRK" else constant / value for value in values]
        except (TypeError, ZeroDivisionError):
            return None
    if kind in {"mulK", "divK", "addK", "subK"}:
        values = _source_values(source[1], upvalues, globals_)
        constant = source[2]
        if not values:
            return None
        try:
            return [
                {"mulK": value * constant, "divK": value / constant, "addK": value + constant, "subK": value - constant}[kind]
                for value in values
            ]
        except (TypeError, ZeroDivisionError):
            return None
    if kind in {"sub", "div", "mul", "add"}:
        left = _source_values(source[1], upvalues, globals_)
        right = _source_values(source[2], upvalues, globals_)
        if not left or not right:
            return None
        try:
            return [
                {"sub": a - b, "div": a / b, "mul": a * b, "add": a + b}[kind]
                for a, b in zip(left, right)
            ]
        except (TypeError, ZeroDivisionError):
            return None
    return None


def _helper_return_axes(proto: dict[str, Any]) -> dict[int, str]:
    taints: dict[int, set[str]] = {}
    returns: dict[int, set[str]] = {}
    for row in _instructions(proto):
        op, a, b, c = row["op"], row["a"], row["b"], row["c"]
        if op == 0x12:
            taints[a] = {MODIFIER_AXES[row["sd"]]} if row["sd"] in MODIFIER_AXES else set()
        elif op in {0x04, 0x0D, 0x13, 0x17, 0x46, 0x4E}:
            taints[a] = set()
        elif op == 0x14:
            taints[a] = set(taints.get(b, set()))
        elif op in {0x01, 0x3D, 0x44}:
            taints[a] = set()
        elif op == 0x2D:  # NAMECALL also copies the source object to A+1.
            taints[a] = set()
            taints[a + 1] = set(taints.get(b, set()))
        elif op in {0x06, 0x07, 0x1A, 0x22, 0x49}:
            taints[a] = set(taints.get(b, set())) | set(taints.get(c, set()))
        elif op in {0x09, 0x32, 0x38, 0x3E}:
            taints[a] = set(taints.get(b, set()))
        elif op in {0x0E, 0x50}:
            taints[a] = set(taints.get(b, set()))
        elif op == 0x54:
            arguments = set().union(*(taints.get(a + offset, set()) for offset in range(1, max(b, 1))))
            for offset in range(max(c - 1, 0)):
                taints[a + offset] = set(arguments)
        elif op == 0x29:
            for offset in range(max(b - 1, 0)):
                returns.setdefault(offset, set()).update(taints.get(a + offset, set()))
    return {
        index: next(iter(axes))
        for index, axes in returns.items()
        if len(axes) == 1
    }


def _runtime_modifiers(ir: dict[str, Any], query: dict[str, Any], query_proto: dict[str, Any]) -> dict[tuple[str, Any], dict[str, str]]:
    instructions = _instructions(query_proto)
    candidates = []
    for index, row in enumerate(instructions):
        if row["op"] != 0x13 or row["b"] >= len(query["captures"]):
            continue
        closure = query["captures"][row["b"]].get("value")
        if not isinstance(closure, dict) or "proto" not in closure:
            continue
        call = next(
            (
                candidate
                for candidate in instructions[index + 1:index + 7]
                if candidate["op"] == 0x54 and candidate["a"] == row["a"] and candidate["c"] > 1
            ),
            None,
        )
        if not call:
            continue
        writes = {}
        tail = instructions[instructions.index(call) + 1:]
        for candidate in tail:
            if candidate["op"] == 0x53 and call["a"] <= candidate["a"] < call["a"] + call["c"] - 1:
                writes[candidate["a"] - call["a"]] = ("upvalue", candidate["b"])
            elif candidate["op"] == 0x02 and call["a"] <= candidate["a"] < call["a"] + call["c"] - 1:
                writes[candidate["a"] - call["a"]] = ("global", _vm_constant(query_proto, int(candidate["aux"] or 0)))
            else:
                break
        if not writes:
            for candidate in tail:
                if candidate["op"] == 0x4F:
                    break
                if candidate["op"] == 0x02 and call["a"] <= candidate["a"] < call["a"] + call["c"] - 1:
                    writes.setdefault(candidate["a"] - call["a"], ("global", _vm_constant(query_proto, int(candidate["aux"] or 0))))
        axes = _helper_return_axes(ir["protos"][closure["proto"]])
        axis_sequence = [
            MODIFIER_AXES[candidate["sd"]]
            for candidate in _instructions(ir["protos"][closure["proto"]])
            if candidate["op"] == 0x12 and candidate["sd"] in MODIFIER_AXES
        ]
        mapped = {
            writes[position]: {"axis": axis, "method": "return-taint"}
            for position, axis in axes.items()
            if position in writes
        }
        for position, source in writes.items():
            if source not in mapped and position < len(axis_sequence):
                mapped[source] = {"axis": axis_sequence[position], "method": "axis-sequence"}
        if mapped:
            candidates.append(mapped)
    result = {}
    for candidate in candidates:
        for source, detail in candidate.items():
            if source not in result:
                result[source] = detail
            elif result[source] != detail:
                result.pop(source, None)
    return result


def _label_modifier(label_key: Any, label_en: Any) -> str | None:
    value = f"{label_key} {label_en}".upper()
    if any(token in value for token in ("DURATION", " DUARTION", "TIME", "WINDOW")):
        return "duration"
    if any(token in value for token in ("RADIUS", "RANGE", "DISTANCE", "WIDTH")):
        return "range"
    if any(token in value for token in (
        "DAMAGE", "HEALTH", "HEAL", "ARMOR", "ARMOUR", "SHIELD", "SLOW_PERCENT",
        "LIFE_STEAL", "LIFE STEAL", "CRIT", "STRENGTH", "REDUCTION",
        "VULNERABILITY", "CHANCE",
    )):
        return "strength"
    return None


def _field_modifier(
    modifiers: dict[tuple[str, Any], dict[str, str]],
    source: tuple[str, Any],
    label_key: Any,
    label_en: Any = "",
) -> tuple[str, str | None]:
    detail = modifiers.get(_source_root(source))
    if not detail:
        return "none", None
    axis = detail["axis"]
    method = detail["method"]
    if method == "axis-sequence":
        inferred = _label_modifier(label_key, label_en)
        if inferred:
            axis = inferred
            method = "axis-sequence+label"
    return axis, method


def _execute_query(ir: dict[str, Any], query_proto_index: int) -> tuple[list[dict[str, Any]], str | None]:
    module, closures = _scan_main(ir)
    query = closures.get(query_proto_index)
    if not query:
        return [], "query closure not found in module initializer"
    query_proto = ir["protos"][query_proto_index]
    rows = _runtime_query_rows(query_proto)
    modifiers = _runtime_modifiers(ir, query, query_proto)
    modifier_sources = set(modifiers)
    rank_helper = _rank_helper_capture(query, ir["protos"][query_proto_index])
    static_vectors = _rank_vectors_for_query(ir, query, query_proto, rank_helper)
    capture_vectors = {
        index: [capture["value"]] * 4
        for index, capture in enumerate(query.get("captures") or [])
        if isinstance(capture.get("value"), (int, float)) and not isinstance(capture.get("value"), bool)
        and abs(float(capture["value"])) <= 1_000_000
        and _source_root(("upvalue", index)) not in modifier_sources
    }
    rank_independent = not any(
        constant.get("kind") == "string" and constant.get("value") == "Level"
        for constant in query_proto["constants"]
    )
    independent_capture_vectors = {
        index: [capture["value"]] * 4
        for index, capture in enumerate(query.get("captures") or [])
        if rank_independent
        and capture.get("kind") == 1
        and isinstance(capture.get("value"), (int, float)) and not isinstance(capture.get("value"), bool)
        and abs(float(capture["value"])) <= 1_000_000
    }
    branch_profile = _rank_branch_profile(ir["protos"][rank_helper["proto"]]) if rank_helper else {
        "comparisons": [], "normalGroups": 0, "ambiguousStaticBranch": False,
    }
    states = None
    execution_error = None
    if rank_helper:
        try:
            states = [_run_rank_helper(ir, rank_helper, rank, module) for rank in range(1, 5)]
        except ValueError as exc:
            execution_error = str(exc)
    else:
        execution_error = "rank helper closure not found"

    state_upvalues: dict[int, list[int | float]] = {}
    state_globals: dict[Any, list[int | float]] = {}
    if states and rank_helper:
        for index, capture in enumerate(query["captures"]):
            values = [
                current_module.get(capture["sourceRegister"]) if capture["kind"] == 1 else capture.get("value")
                for current_module, _ in states
            ]
            # DE stores a few private atom/hash sentinels in numeric captures
            # (notably Wisp Reservoir). Rank helpers never write those values;
            # only accept an unchanged capture when it is in a sane display
            # range, while actual rank-helper writes remain unrestricted.
            changed = any(item != capture.get("value") for item in values)
            if (
                all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values)
                and (changed or all(abs(float(item)) <= 1_000_000 for item in values))
            ):
                state_upvalues[index] = values
        global_keys = {key for _, globals_ in states for key in globals_}
        state_globals = {key: [globals_.get(key) for _, globals_ in states] for key in global_keys}

    result = []
    for row in rows:
        static_values = _source_values(row["source"], static_vectors["upvalue"], static_vectors["global"])
        static_mode = "rank-static"
        if not static_values:
            static_values = _source_values(row["source"], capture_vectors, {})
            static_mode = "capture-static"
        executed_values = _source_values(row["source"], state_upvalues, state_globals)
        independent_values = _source_values(row["source"], independent_capture_vectors, {})
        if static_values and executed_values:
            if branch_profile["ambiguousStaticBranch"]:
                rank_values, source_mode = executed_values, "symbolic-execution"
            elif _same_vector(static_values, executed_values):
                rank_values, source_mode = executed_values, "symbolic-execution"
            else:
                rank_values, source_mode = static_values, static_mode
        elif executed_values:
            rank_values, source_mode = executed_values, "symbolic-execution"
        elif static_values:
            rank_values, source_mode = static_values, static_mode
        elif independent_values and rank_independent:
            rank_values, source_mode = independent_values, "rank-independent-capture"
        else:
            rank_values, source_mode = None, "unresolved"

        modifier, modifier_evidence = _field_modifier(modifiers, row["source"], row["labelKey"])
        if (row["metadata"] or {}).get("ValueIcon") == "<ENERGY>":
            upper_label = str(row["labelKey"]).upper()
            if any(token in upper_label for token in ("EPS", "DRAIN")):
                modifier, modifier_evidence = "drain", "energy-label"
            elif "COST" in upper_label:
                modifier, modifier_evidence = "efficiency", "energy-label"
        result.append({
            "labelKey": row["labelKey"],
            "rankValues": rank_values,
            "modifier": modifier,
            "metadata": row["metadata"],
            "valueSourceKind": row["source"][0],
            "valueSourceMode": source_mode,
            "rankBranchProfile": branch_profile,
            "modifierEvidence": modifier_evidence,
        })
    if result:
        return result, None
    return [], execution_error or "query produced no fields"


def _numeric_vector(field: dict[str, Any] | None) -> list[int | float] | None:
    if not field:
        return None
    values = field.get("rankValues")
    if isinstance(values, list) and values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return values
    value = field.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [value] * 4
    return None


def _same_vector(left: list[int | float], right: list[int | float]) -> bool:
    if len(left) == 1 and len(right) == 4:
        left = left * 4
    if len(right) == 1 and len(left) == 4:
        right = right * 4
    return len(left) == len(right) and all(
        math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
        for a, b in zip(left, right)
    )


def _reconcile_fields(
    query_schema: list[dict[str, Any]],
    query_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    schema_by_label: dict[str, list[dict[str, Any]]] = {}
    fields_by_label: dict[str, list[dict[str, Any]]] = {}
    order = []
    for field in query_schema:
        label = str(field.get("labelKey") or "")
        schema_by_label.setdefault(label, []).append(field)
        if label not in order:
            order.append(label)
    for field in query_fields:
        label = str(field.get("labelKey") or "")
        fields_by_label.setdefault(label, []).append(field)
        if label not in order:
            order.append(label)

    result = []
    for label in order:
        schema_rows = schema_by_label.get(label, [])
        field_rows = fields_by_label.get(label, [])
        for occurrence in range(max(len(schema_rows), len(field_rows))):
            schema = schema_rows[occurrence] if occurrence < len(schema_rows) else None
            field = field_rows[occurrence] if occurrence < len(field_rows) else None
            base = field or schema or {}
            left = _numeric_vector(field)
            right = _numeric_vector(schema)
            row: dict[str, Any] = {
                "displayOrder": len(result),
                "labelKey": label,
                "labelEn": base.get("labelEn") or "",
                "labelZh": base.get("labelZh") or "",
                "modifier": (field or {}).get("modifier") or "none",
            }
            for key in ("valueUnit", "valueIcon", "smallerIsBetter"):
                value = (field or {}).get(key)
                if value is None:
                    value = (schema or {}).get(key)
                if value is not None:
                    row[key] = value
            metadata = (field or {}).get("metadata") or {}
            if metadata:
                row["metadata"] = metadata
            if field:
                row["valueSourceKind"] = field.get("valueSourceKind")
                row["valueSourceMode"] = field.get("valueSourceMode")
                if field.get("sourceEvidence"):
                    row["sourceEvidence"] = field["sourceEvidence"]
                if field.get("modifierEvidence"):
                    row["modifierEvidence"] = field["modifierEvidence"]
                if field.get("rankBranchProfile"):
                    row["rankBranchProfile"] = field["rankBranchProfile"]
            if left and right and _same_vector(left, right):
                if (field or {}).get("valueSourceMode") == "symbolic-execution":
                    row.update(rankValues=left, confidence="cross-checked", valueSources=["query-interpreter", "static-dataflow"])
                else:
                    row.update(rankValues=right, confidence="single-source", valueSources=["static-dataflow"])
            elif left and right:
                candidates = {"queryInterpreter": left, "staticDataflow": right}
                if (field or {}).get("valueSourceMode") == "capture-static" and len(right) == 4 and right != sorted(right) and len(set(right)) > 1:
                    row.update(rankValues=None, confidence="conflict", candidates=candidates, disagreement="capture-constant-vs-nonmonotonic-rank-vector")
                elif (field or {}).get("valueSourceMode") == "capture-static":
                    row.update(
                        rankValues=right,
                        confidence="single-source",
                        valueSources=["static-dataflow"],
                        candidates=candidates,
                        disagreement="capture-constant-replaced-by-rank-vector",
                    )
                elif (field or {}).get("valueSourceKind") == "static":
                    row.update(
                        rankValues=left,
                        confidence="single-source",
                        valueSources=["query-template"],
                        candidates=candidates,
                        disagreement="static-dataflow-linked-another-value",
                    )
                elif ((field or {}).get("rankBranchProfile") or {}).get("ambiguousStaticBranch"):
                    row.update(
                        rankValues=left,
                        confidence="single-source",
                        valueSources=["query-interpreter"],
                        candidates=candidates,
                        disagreement="static-dataflow-cannot-select-environment-branch",
                    )
                else:
                    row.update(rankValues=None, confidence="conflict", candidates=candidates)
            elif left:
                source_name = {
                    "wiki-snapshot": "wiki-snapshot",
                    "symbolic-execution": "query-interpreter",
                    "rank-static": "static-dataflow",
                    "direct-static": "static-dataflow",
                    "capture-static": "query-capture",
                }.get((field or {}).get("valueSourceMode"), "query-interpreter")
                row.update(rankValues=left, confidence="single-source", valueSources=[source_name])
            elif right:
                row.update(rankValues=right, confidence="single-source", valueSources=["static-dataflow"])
            else:
                row.update(rankValues=None, confidence="unresolved")
            result.append(row)
    return result


def _query_schema(ir: dict[str, Any], localization_en: dict[str, str], localization_zh: dict[str, str]) -> list[dict[str, Any]]:
    candidates = set(ir["queryProtoCandidates"])
    result = []
    for proto in ir["protos"]:
        if proto["index"] not in candidates:
            continue
        constants = proto["constants"]
        rank_vectors = _query_upvalue_vectors(ir, proto["index"])
        direct_vectors = _rank_vectors(proto)
        rank_vectors.update(direct_vectors["upvalue"])
        register_protos, captures = _closure_graph(ir)
        query_captures = captures.get(proto["index"]) or []
        setter_protos = {
            register_protos[capture["source"]]
            for capture in query_captures
            if capture["kind"] == 0 and capture["source"] in register_protos
        }
        global_vectors: dict[int, list[int | float]] = {}
        for setter_proto in setter_protos:
            for atom, values in _rank_vectors(ir["protos"][setter_proto])["global"].items():
                global_vectors.setdefault(atom, values)
        global_vectors.update(direct_vectors["global"])
        for table_index, constant in enumerate(constants):
            if constant["kind"] != "tableWithConstants":
                continue
            row = {
                str(_constant_value(constants, entry["key"])): _constant_value(constants, entry["constant"])
                for entry in constant["entries"]
            }
            if "Label" not in row or "Value" not in row:
                continue
            label_key = row.get("Label")
            value_source = _value_source(proto, table_index)
            field: dict[str, Any] = {
                "displayOrder": len(result),
                "labelKey": label_key,
                "labelEn": localization_en.get(str(label_key), str(label_key or "")),
                "labelZh": localization_zh.get(str(label_key), str(label_key or "")),
                "value": row.get("Value"),
                "valueSource": value_source,
            }
            if value_source.get("kind") == "upvalue" and value_source.get("index") in rank_vectors:
                field["rankValues"] = rank_vectors[value_source["index"]]
            elif value_source.get("kind") == "global" and value_source.get("atom") in global_vectors:
                field["rankValues"] = global_vectors[value_source["atom"]]
            for source, target in (
                ("ValueUnit", "valueUnit"),
                ("ValueIcon", "valueIcon"),
                ("SmallerIsBetter", "smallerIsBetter"),
            ):
                if source in row:
                    value = row[source]
                    if source == "ValueUnit" and isinstance(value, str):
                        field[target] = {
                            "key": value,
                            "en": localization_en.get(value, value),
                            "zh": localization_zh.get(value, value),
                        }
                    else:
                        field[target] = value
            result.append(field)
    return result


def _compact_ir(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ir[key]
        for key in (
            "version", "typeVersion", "bytes", "consumed", "mainProto",
            "queryTokens", "queryProtoCandidates", "localizationKeys",
            "constantTagCounts", "codeWordLowByteCounts",
        )
    } | {"protoCount": len(ir["protos"])}


def _wiki_page(root: Path | None, title: str) -> tuple[str, Path | None]:
    if not root or not root.is_dir():
        return "", None
    for path in root.glob("*.json"):
        try:
            payload = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("title") or "").casefold() == title.casefold():
            return str(payload.get("text") or ""), path
    return "", None


def _rank_numbers(match: re.Match[str] | None) -> list[int | float] | None:
    if not match:
        return None
    values = []
    for token in re.split(r"\s*/\s*", match.group(1)):
        value = float(token)
        values.append(int(value) if value.is_integer() else value)
    return values or None


def _wiki_fallback_fields(ability_id: str, wiki_root: Path | None) -> list[dict[str, Any]]:
    title = WIKI_FALLBACK_ABILITIES.get(ability_id)
    if not title:
        return []
    text, source_path = _wiki_page(wiki_root, title)
    if not text:
        return []
    patterns = [
        ("wiki:freeze:energy-cost", "Energy Cost", "能量消耗", r"expends\s+(\d+(?:\.\d+)?)\s+Energy", "efficiency", ""),
        ("wiki:freeze:cold-main-damage", "Cold Main Damage", "冰冻主要伤害", r"(\d+(?:\s*/\s*\d+){3})\s*\(\s*main damage\s*\)", "strength", "<DT_FREEZE>"),
        ("wiki:freeze:cold-area-damage", "Cold Area Damage", "冰冻范围伤害", r"(\d+(?:\s*/\s*\d+){3})\s*\(\s*area damage\s*\)", "strength", "<DT_FREEZE>"),
        ("wiki:freeze:impact-radius", "Impact Radius", "冲击半径", r"(\d+(?:\.\d+)?)\s*\(\s*impact radius\s*\)", "range", ""),
        ("wiki:freeze:freeze-duration", "Freeze Duration", "冻结持续时间", r"(\d+(?:\s*/\s*\d+){3})\s*s\s*\(\s*freeze duration\s*\)", "duration", ""),
        ("wiki:freeze:direct-procs", "Cold Status Procs On Direct Hit", "直接命中冰冻异常层数", r"Misc:\s*(\d+(?:\.\d+)?)\s*\(\s*status procs on direct hit\s*\)", "none", ""),
        ("wiki:freeze:radius-procs", "Cold Status Procs On Impact Radius", "冲击范围冰冻异常层数", r"(\d+(?:\.\d+)?)%\s*\(\s*status procs on impact radius\s*\)", "none", ""),
    ]
    result = []
    for key, label_en, label_zh, pattern, modifier, icon in patterns:
        match = re.search(pattern, text, re.I)
        values = _rank_numbers(match)
        if values is None:
            continue
        result.append({
            "labelKey": key,
            "labelEn": label_en,
            "labelZh": label_zh,
            "rankValues": values if len(values) > 1 else values * 4,
            "modifier": modifier,
            "metadata": {
                "ValueUnit": "s" if "duration" in key else "m" if "radius" in key and "procs" not in key else "%" if "radius-procs" in key else "",
                **({"ValueIcon": icon} if icon else {}),
            },
            "valueSourceKind": "wiki",
            "valueSourceMode": "wiki-snapshot",
            "modifierEvidence": "wiki-snapshot",
            "sourceEvidence": {
                "kind": "wiki-snapshot",
                "title": title,
                "url": f"https://wiki.warframe.com/w/{title.replace(' ', '_')}",
                "path": provenance_path(source_path) if source_path else None,
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path and source_path.is_file() else None,
            },
        })
    return result


def _wiki_field_override(script_path: str, label_key: str, wiki_root: Path | None) -> tuple[list[int | float], dict[str, Any]] | None:
    rules = WIKI_FIELD_OVERRIDES.get(script_path) or {}
    rule = rules.get(label_key)
    if not rule:
        return None
    title, pattern = rule
    text, source_path = _wiki_page(wiki_root, title)
    values = _rank_numbers(re.search(pattern, text, re.I))
    if not values:
        return None
    if len(values) == 1:
        values = values * 4
    return values, {
        "kind": "wiki-snapshot",
        "title": title,
        "url": f"https://wiki.warframe.com/w/{title.replace(' ', '_')}",
        "path": provenance_path(source_path) if source_path else None,
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path and source_path.is_file() else None,
    }


def _catalog_fallback(field: dict[str, Any], catalog_fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    label = re.sub(r"[^a-z0-9]+", "", str(field.get("labelEn") or "").casefold())
    candidates = [
        candidate for candidate in catalog_fields
        if re.sub(r"[^a-z0-9]+", "", str(candidate.get("labelEn") or candidate.get("label") or candidate.get("id") or "").casefold()) == label
        and isinstance(candidate.get("rankValues"), list)
        and candidate.get("rankValues")
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    return {
        "rankValues": candidate["rankValues"],
        "modifier": candidate.get("scale"),
        "sourceKind": candidate.get("sourceKind"),
        "fieldId": candidate.get("id"),
        "matchMethod": "exact-label",
    }


def _catalog_token_fallback(field: dict[str, Any], catalog_fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    field_tokens = _wiki_label_tokens(field.get("labelEn"))
    if not field_tokens:
        return None
    candidates = []
    for candidate in catalog_fields:
        values = candidate.get("rankValues")
        if not isinstance(values, list) or not values:
            continue
        if len(values) == 1:
            values = values * 4
        candidate_tokens = _wiki_label_tokens(candidate.get("labelEn") or candidate.get("label") or candidate.get("id"))
        union = field_tokens | candidate_tokens
        score = len(field_tokens & candidate_tokens) / len(union) if union else 0
        if score >= 0.5 and _field_unit(field) == _field_unit(candidate):
            candidates.append((score, candidate, values))
    candidates.sort(key=lambda row: row[0], reverse=True)
    if not candidates or (len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0])):
        return None
    score, candidate, values = candidates[0]
    return {
        "rankValues": values,
        "modifier": candidate.get("scale"),
        "sourceKind": candidate.get("sourceKind"),
        "fieldId": candidate.get("id"),
        "matchScore": round(score, 6),
        "matchMethod": "token-overlap",
    }


_WIKI_LABEL_STOP = {"ability", "effect", "enemy", "enemies", "of", "or", "power", "the", "up"}


def _normalized_wiki_label(value: Any) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _wiki_label_tokens(value: Any) -> frozenset[str]:
    return frozenset(part for part in _normalized_wiki_label(value).split() if part not in _WIKI_LABEL_STOP)


def _field_unit(field: dict[str, Any]) -> str:
    unit = field.get("valueUnit")
    if isinstance(unit, dict):
        unit = unit.get("en") or unit.get("key") or ""
    text = str(unit or field.get("unit") or "").casefold()
    if "%" in text or "percent" in text:
        return "%"
    if "m/s" in text:
        return "m/s"
    if "meter" in text or re.search(r"(?:^|[^a-z])m(?:$|[^a-z])", text):
        return "m"
    if "second" in text or re.search(r"(?:^|[^a-z])s(?:$|[^a-z])", text):
        return "s"
    return ""


def _wiki_candidates(ability: dict[str, Any], wiki_root: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    source = next(
        (
            evidence
            for evidence in ability.get("sourceEvidence") or ()
            if evidence.get("kind") == "wiki" and evidence.get("snapshotPath")
        ),
        None,
    )
    if not source:
        return [], None
    path = Path(str(source["snapshotPath"]))
    if not path.is_file() and wiki_root:
        path = wiki_root / path.name
    if not path.is_file():
        return [], None
    page = _load_json(path)
    scalars, _issues = parse_wiki_scalars(page, str(ability.get("nameEn") or ""))
    rows = [*scalars, *parse_wiki_misc_fields(page)]
    candidates = []
    seen = set()
    for row in rows:
        values = row.get("rankValues") or row.get("values") or []
        if not isinstance(values, list) or len(values) not in {1, 4}:
            continue
        if len(values) == 1:
            values *= 4
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            continue
        label = _normalized_wiki_label(row.get("labelEn") or row.get("label"))
        unit = _field_unit(row)
        key = (label, tuple(values), unit)
        if not label or key in seen:
            continue
        seen.add(key)
        candidates.append({"label": label, "tokens": _wiki_label_tokens(label), "unit": unit, "values": values})
    evidence = {
        "kind": "wiki-snapshot",
        "title": page.get("title") or ability.get("nameEn"),
        "url": source.get("url"),
        "path": provenance_path(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return candidates, evidence


def _catalog_energy_fallback(field: dict[str, Any], ability: dict[str, Any]) -> dict[str, Any] | None:
    label = _normalized_wiki_label(field.get("labelEn"))
    cost = ability.get("energyCost")
    if not isinstance(cost, dict):
        return None
    value = None
    if ("drain" in label or "energy" in label) and "second" in label:
        value = cost.get("drainPerSecond")
    elif ("energy" in label or "drain" in label) and "shot" in label:
        value = cost.get("perShot")
    elif "energy" in label and "mark" in label:
        value = cost.get("perTarget")
    elif "energy revive" in label:
        value = cost.get("reviveMaximum")
    elif "energy shot" in label:
        value = cost.get("perShot")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return {
        "rankValues": [value] * 4,
        "value": value,
        "sourceKind": cost.get("sourceKind") or "packages",
        "field": "energyCost",
    }


def _apply_wiki_matches(fields: list[dict[str, Any]], ability: dict[str, Any], wiki_root: Path | None = None) -> int:
    candidates, evidence = _wiki_candidates(ability, wiki_root)
    if not candidates or not evidence:
        return 0
    matched = 0
    for field in fields:
        # A decoded client query is authoritative for this build. Wiki is a
        # fill-only source here; disagreements are audited separately and
        # never silently replace an actual query result.
        if field.get("rankValues"):
            continue
        aliases = {
            label
            for label in (
                _normalized_wiki_label(field.get("labelEn")),
                _normalized_wiki_label(str(field.get("labelKey") or "").rsplit("/", 1)[-1]),
            )
            if label
        }
        exact = [candidate for candidate in candidates if candidate["label"] in aliases]
        method = "exact-label"
        choices = exact
        if len(exact) != 1:
            alias_tokens = {_wiki_label_tokens(alias) for alias in aliases} - {frozenset()}
            choices = [candidate for candidate in candidates if candidate["tokens"] in alias_tokens]
            method = "token-set"
        if len(choices) != 1 or choices[0]["unit"] != _field_unit(field):
            continue
        choice = choices[0]
        field.update(
            rankValues=choice["values"],
            confidence="single-source",
            valueSources=["wiki-snapshot"],
            sourceEvidence=evidence,
            wikiMatch={"method": method, "label": choice["label"], "unit": choice["unit"]},
        )
        matched += 1
    return matched


def _decode_font_script(
    script_path: str,
    script_file: Path,
    header_file: Path,
    font_root: Path,
    localization_en: dict[str, str],
    localization_zh: dict[str, str],
    *,
    full_ir: bool = False,
) -> dict[str, Any]:
    body = script_file.read_bytes()
    header_body = header_file.read_bytes()
    script_ir = parse_chunk(body)
    query_schema = _query_schema(script_ir, localization_en, localization_zh)
    query_fields: list[dict[str, Any]] = []
    query_error = None
    if script_ir["queryProtoCandidates"]:
        query_fields, query_error = _execute_query(script_ir, script_ir["queryProtoCandidates"][0])
    for field in query_fields:
        label_key = field.get("labelKey")
        field["labelEn"] = localization_en.get(str(label_key), str(label_key or ""))
        field["labelZh"] = localization_zh.get(str(label_key), str(label_key or ""))
        metadata = field.get("metadata") or {}
        if isinstance(metadata.get("ValueUnit"), str):
            unit_key = metadata["ValueUnit"]
            field["valueUnit"] = {
                "key": unit_key,
                "en": localization_en.get(unit_key, unit_key),
                "zh": localization_zh.get(unit_key, unit_key),
            }
        if "ValueIcon" in metadata:
            field["valueIcon"] = metadata["ValueIcon"]
        if "SmallerIsBetter" in metadata:
            field["smallerIsBetter"] = metadata["SmallerIsBetter"]
    return {
        "scriptPath": script_path,
        "sourceFile": script_file.relative_to(font_root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "headerFile": header_file.relative_to(font_root).as_posix(),
        "headerSha256": hashlib.sha256(header_body).hexdigest(),
        **(script_ir if full_ir else _compact_ir(script_ir)),
        "querySchema": query_schema,
        "querySchemaStatus": "decoded" if query_schema else "delegated-or-dynamic",
        "queryFields": query_fields,
        "queryFieldsStatus": "decoded" if query_fields else (query_error or "empty"),
        "queryExecutionDiagnostic": query_error,
        "resolvedFields": _reconcile_fields(query_schema, query_fields),
    }


def build_sidecar(
    catalog_path: Path,
    packages_root: Path,
    font_root: Path,
    localization_en: dict[str, str] | None = None,
    localization_zh: dict[str, str] | None = None,
    *,
    full_ir: bool = False,
    wiki_root: Path | None = None,
) -> dict[str, Any]:
    catalog = _load_json(catalog_path)
    abilities = _unique_abilities(catalog)
    font_files = _font_index(font_root)
    header_files = _font_header_index(font_root)
    localization_en = localization_en or {}
    localization_zh = localization_zh or {}
    scripts: dict[str, dict[str, Any]] = {}
    delegated_scripts: dict[str, dict[str, Any]] = {}
    ability_rows = []
    errors = []

    for ability in abilities:
        ability_id = str(ability.get("id") or ability.get("path") or "")
        package_file = _package_path(packages_root, ability_id)
        package = _load_json(package_file) if package_file.is_file() else {}
        alias_of = None
        reference = _direct_script(package) if isinstance(package, dict) else None
        owner_id = ability_id
        if not reference:
            alias_of = UMBRA_ALIASES.get(ability_id)
            owner_id = alias_of or ability_id
            alias_file = _package_path(packages_root, owner_id)
            alias_package = _load_json(alias_file) if alias_file.is_file() else {}
            reference = _direct_script(alias_package) if isinstance(alias_package, dict) else None
        script_path = _script_path(owner_id, reference) if reference else ""
        script_file = font_files.get(script_path.casefold()) if script_path else None
        header_file = header_files.get(script_path.casefold()) if script_path else None
        if not script_file:
            errors.append(f"script missing: {ability_id} -> {script_path or '<unresolved>'}")
        elif not header_file:
            errors.append(f"Font header missing: {script_path}")
        elif script_path not in scripts:
            try:
                scripts[script_path] = _decode_font_script(
                    script_path,
                    script_file,
                    header_file,
                    font_root,
                    localization_en,
                    localization_zh,
                    full_ir=full_ir,
                )
            except (OSError, ValueError) as exc:
                errors.append(f"decode failed: {script_path}: {exc}")
        delegated_path = DELEGATED_QUERY_SCRIPTS.get(ability_id)
        delegated = None
        if delegated_path:
            delegated_file = font_files.get(delegated_path.casefold())
            delegated_header = header_files.get(delegated_path.casefold())
            if not delegated_file or not delegated_header:
                errors.append(f"delegated Font script missing: {ability_id} -> {delegated_path}")
            elif delegated_path not in delegated_scripts:
                try:
                    delegated_scripts[delegated_path] = _decode_font_script(
                        delegated_path,
                        delegated_file,
                        delegated_header,
                        font_root,
                        localization_en,
                        localization_zh,
                        full_ir=full_ir,
                    )
                except (OSError, ValueError) as exc:
                    errors.append(f"delegated decode failed: {delegated_path}: {exc}")
            delegated = delegated_scripts.get(delegated_path)
        direct = scripts.get(script_path)
        wiki_fields = _wiki_fallback_fields(ability_id, wiki_root)
        selected = delegated or direct or {}
        if wiki_fields and not delegated:
            selected = {
                "queryFields": wiki_fields,
                "querySchema": [],
                "resolvedFields": _reconcile_fields([], wiki_fields),
                "queryFieldsStatus": "wiki-fallback",
                "queryExecutionDiagnostic": "client query delegates to ProjLauncher; values parsed from local Wiki snapshot",
            }
        selected_resolved = deepcopy(selected.get("resolvedFields") or [])
        _apply_wiki_matches(selected_resolved, ability, wiki_root)
        catalog_fields = [field for field in ability.get("scalars") or [] if isinstance(field, dict)]
        for field in selected_resolved:
            override = _wiki_field_override(script_path, str(field.get("labelKey") or ""), wiki_root)
            if override:
                values, evidence = override
                field.update(
                    rankValues=values,
                    confidence="single-source",
                    valueSources=["wiki-snapshot"],
                    sourceEvidence=evidence,
                    disagreement="static-query-branch-replaced-by-local-wiki-vector",
                )
            if not field.get("rankValues"):
                energy_fallback = _catalog_energy_fallback(field, ability)
                if energy_fallback:
                    field.update(
                        rankValues=energy_fallback["rankValues"],
                        confidence="single-source",
                        valueSources=["catalog-energy-cost"],
                        sourceEvidence={
                            "kind": energy_fallback["sourceKind"],
                            "field": energy_fallback["field"],
                        },
                    )
                    continue
                fallback = _catalog_fallback(field, catalog_fields) or _catalog_token_fallback(field, catalog_fields)
                if fallback:
                    field["catalogFallback"] = fallback
        ability_rows.append({
            "abilityId": ability_id,
            "nameEn": ability.get("nameEn") or "",
            "scriptPath": script_path or None,
            "aliasOf": alias_of,
            "status": "wire-ir" if script_path in scripts else "unresolved",
            "queryStatus": selected.get("queryFieldsStatus"),
            "delegatedScriptPath": delegated_path,
            "delegatedSource": "wiki-snapshot" if wiki_fields and not delegated else "font-secondary-script" if delegated else None,
            "delegatedScriptSha256": delegated.get("sha256") if delegated else None,
            "delegatedQueryDiagnostic": selected.get("queryExecutionDiagnostic"),
            "queryFields": selected.get("queryFields") or [],
            "querySchema": selected.get("querySchema") or [],
            "resolvedFields": selected_resolved,
        })

    all_scripts = [*scripts.values(), *delegated_scripts.values()]
    query_candidates = sum(len(row["queryProtoCandidates"]) for row in scripts.values())
    query_schema_rows = sum(len(row["querySchema"]) for row in all_scripts)
    script_numeric_fields = sum(
        bool(field.get("rankValues"))
        for script in all_scripts
        for field in script.get("resolvedFields") or ()
    )
    schema_numeric_fields = sum(
        bool(field.get("rankValues"))
        for script in all_scripts
        for field in script["querySchema"]
    )
    script_resolved_field_rows = sum(len(row.get("resolvedFields") or ()) for row in all_scripts)
    script_confidence_counts = Counter(
        str(field.get("confidence") or "unresolved")
        for script in all_scripts
        for field in script.get("resolvedFields") or ()
    )
    wiki_fallback_rows = [row for row in ability_rows if row.get("delegatedSource") == "wiki-snapshot"]
    wiki_fallback_fields = [field for row in wiki_fallback_rows for field in row.get("resolvedFields") or ()]
    ability_fields = [field for row in ability_rows for field in row.get("resolvedFields") or ()]
    numeric_fields = sum(bool(field.get("rankValues")) for field in ability_fields)
    resolved_field_rows = len(ability_fields)
    confidence_counts = Counter(str(field.get("confidence") or "unresolved") for field in ability_fields)
    catalog_fallback_fields = [
        field
        for row in ability_rows
        for field in row.get("resolvedFields") or ()
        if field.get("catalogFallback")
    ]
    wiki_matched_fields = [
        field
        for row in ability_rows
        for field in row.get("resolvedFields") or ()
        if field.get("wikiMatch")
    ]
    required_coverage = {
        token: sum(bool(row["queryTokens"].get(token)) for row in scripts.values())
        for token in REQUIRED_QUERY_TOKENS
    }
    status = "query-ir-partial" if not errors else "incomplete"
    return {
        "schemaVersion": 1,
        "stage": "query-ir",
        "status": status,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "buildLabel": catalog.get("buildLabel"),
        "decoderRevision": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": {
            "catalog": provenance_path(catalog_path),
            "packagesRoot": provenance_path(packages_root),
            "fontRoot": provenance_path(font_root),
            "wikiRoot": provenance_path(wiki_root) if wiki_root else None,
        },
        "summary": {
            "abilities": len(abilities),
            "mappedAbilities": sum(row["status"] == "wire-ir" for row in ability_rows),
            "uniqueScripts": len(scripts),
            "fontBFiles": len(font_files),
            "fontHFiles": len(header_files),
            "pairedScripts": sum(bool(row.get("headerFile")) for row in scripts.values()),
            "delegatedScripts": len(delegated_scripts),
            "delegatedPairedScripts": sum(bool(row.get("headerFile")) for row in delegated_scripts.values()),
            "wikiFallbackAbilities": len(wiki_fallback_rows),
            "wikiFallbackFields": sum(len(row.get("resolvedFields") or ()) for row in wiki_fallback_rows),
            "wikiMatchedFields": len(wiki_matched_fields),
            "catalogFallbackFields": len(catalog_fallback_fields),
            "queryProtoCandidates": query_candidates,
            "querySchemaRows": query_schema_rows,
            "scriptsWithQuerySchema": sum(bool(row["querySchema"]) for row in all_scripts),
            "scriptsWithQueryFields": sum(bool(row.get("queryFields")) for row in all_scripts),
            "resolvedFieldRows": resolved_field_rows,
            "resolvedConfidence": dict(sorted(confidence_counts.items())),
            "scriptResolvedFieldRows": script_resolved_field_rows,
            "scriptResolvedConfidence": dict(sorted(script_confidence_counts.items())),
            "requiredTokenCoverage": required_coverage,
            "numericFieldsRecovered": numeric_fields,
            "scriptNumericFieldsRecovered": script_numeric_fields,
            "schemaNumericFields": schema_numeric_fields,
            "queryOpcodeMapComplete": True,
            "semanticOpcodeMapComplete": False,
        },
        "limitations": [
            "The current-build opcode map covers the 260 project ability queries and their captured helpers, not the complete Luau VM.",
            "Private 32-bit constants and payload-free private tags are preserved without coercion.",
            f"{confidence_counts.get('conflict', 0)} fields have disagreeing interpreter/static vectors and remain fail-closed.",
            f"{confidence_counts.get('unresolved', 0)} query fields still depend on unsupported engine callbacks or delegated helpers.",
            "Resolved query values remain a parallel sidecar and are not promoted into production fields yet.",
        ],
        "abilities": ability_rows,
        "scripts": [scripts[key] for key in sorted(scripts)],
        "delegatedScripts": [delegated_scripts[key] for key in sorted(delegated_scripts)],
        "errors": errors,
    }


def _write_varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _self_test() -> None:
    assert _source_values(("subRK", 1, ("static", 0.1)), {}, {}) == [0.9] * 4
    assert _source_values(("divRK", 1, ("static", 2)), {}, {}) == [0.5] * 4
    assert _source_values(("unaryBuiltin", ("static", 2.5), 48), {}, {}) == [3] * 4
    assert _source_values(("unaryBuiltin", ("static", -2.5), 48), {}, {}) == [-3] * 4
    assert _source_values(("unaryBuiltin", ("static", 2.9), 12), {}, {}) == [2] * 4
    assert _source_values(("unaryBuiltin", ("static", 2), 133), {}, {}) is None
    assert _source_values(("rangeMember", ("upvalue", 3), "minValue"), {("range", 3, "minValue"): [1, 2, 3, 4]}, {}) == [1, 2, 3, 4]
    strings = ("GetAbilityUpgradeLevelInfo", "Label", "Value", "/Lotus/Language/Game/DAMAGE")
    body = bytearray((9, 3))
    body += _write_varint(len(strings))
    for value in strings:
        raw = value.encode()
        body += _write_varint(len(raw)) + raw
    body += b"\0" + _write_varint(1)
    body += bytes((2, 0, 0, 0, 0)) + _write_varint(0)
    body += _write_varint(1) + struct.pack("<I", 0x0000000D)
    body += _write_varint(4)
    for string_id in range(1, 5):
        body += b"\3" + _write_varint(string_id)
    body += _write_varint(0) + _write_varint(1) + _write_varint(0) + b"\0\0"
    body += _write_varint(0)
    parsed = parse_chunk(bytes(body))
    assert parsed["consumed"] == len(body)
    assert parsed["queryTokens"]["GetAbilityUpgradeLevelInfo"]
    assert parsed["queryProtoCandidates"] == [0]
    assert parsed["localizationKeys"] == ["/Lotus/Language/Game/DAMAGE"]
    with tempfile.TemporaryDirectory() as directory:
        wiki_root = Path(directory)
        (wiki_root / "freeze.json").write_text(
            json.dumps({"title": "Freeze", "text": "expends 25 Energy; 150 / 225 / 275 / 350 (main damage); 5 / 7 / 12 / 15 s (freeze duration); 5 (impact radius); Misc: 10 (status procs on direct hit)600% (status procs on impact radius)"}),
            encoding="utf-8",
        )
        fields = _wiki_fallback_fields("/Lotus/Powersuits/Frost/Abilities/IcicleAbility", wiki_root)
        assert len(fields) == 6
        assert fields[1]["rankValues"] == [150, 225, 275, 350]
        assert fields[-1]["metadata"]["ValueUnit"] == "%"
        (wiki_root / "Test.json").write_text(
            json.dumps({"title": "Test", "text": "1 / 2 / 3 / 4 s (duration)"}),
            encoding="utf-8",
        )
        ability = {
            "nameEn": "Test",
            "sourceEvidence": [{"kind": "wiki", "snapshotPath": str(wiki_root / "Test.json")}],
        }
        matched = [{"labelEn": "Duration", "labelKey": "/Duration", "valueUnit": {"en": "|COUNT|s"}}]
        assert _apply_wiki_matches(matched, ability) == 1
        assert matched[0]["rankValues"] == [1, 2, 3, 4]
        mismatch = [{"labelEn": "Duration", "labelKey": "/Duration", "valueUnit": {"en": "|COUNT|%"}}]
        assert _apply_wiki_matches(mismatch, ability) == 0
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract fail-closed IR from current Warframe Luau ability chunks")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--packages-root", type=Path)
    parser.add_argument("--font-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--localization-en", type=Path)
    parser.add_argument("--localization-zh", type=Path)
    parser.add_argument("--wiki", type=Path, help="local cleaned Wiki snapshot used only for delegated fallback")
    parser.add_argument("--full-ir", action="store_true", help="include every proto, code word and constant")
    parser.add_argument("--chunk", type=Path, help="decode one .lua_B file to stdout")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if args.chunk:
        print(json.dumps(parse_chunk(args.chunk.read_bytes()), ensure_ascii=False, indent=2))
        return 0
    if not args.packages_root or not args.font_root or not args.output:
        parser.error("--packages-root, --font-root and --output are required")
    localization_en = _load_json(args.localization_en) if args.localization_en else {}
    localization_zh = _load_json(args.localization_zh) if args.localization_zh else {}
    payload = build_sidecar(
        args.catalog.resolve(),
        args.packages_root.resolve(),
        args.font_root.resolve(),
        localization_en,
        localization_zh,
        full_ir=args.full_ir,
        wiki_root=args.wiki.resolve() if args.wiki else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], **payload["summary"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if not payload["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
