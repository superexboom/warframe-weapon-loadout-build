"""Independent Cortege research reference; not a production firefield profile.

The proven primitive is pre-defense pure Heat for a declared number of contacts
from one field. It does not establish real overlap, tick count, status DoT, or
complete MOD coverage. Full scorer integration requires those remaining proofs.

Example:
    python tools/cortege_field_reference.py --base-damage-multiplier 2

The caller supplies an ordinary unconditional query base-damage multiplier and
an already known neutral/explicit victim scalar. Weapon elemental, critical,
and status parameters are deliberately absent. The victim scalar is applied
once after the Lua float32 -> int32 snapshot boundary. Contact aggregation is
arithmetic, not an emulation of engine accumulation or a predicted schedule.
"""
from __future__ import annotations

import argparse
import json
import math
import struct

SOURCE_HASHES = {
    "Warframe.x64.exe": "eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d",
    "Packages.bin_H": "00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06",
    "ThanotechArchgun.lua_B": "35dc689324bd96ca125913066a71fa5a1a266fce6c25a156f8793647cd14278a",
}
LIMITS = (
    "Independent research reference; not an enabled production firefield profile.",
    "Only ordinary unconditional base-damage query scaling is admitted; special innate, conversions, conditional, faction and actor gameplay MOD coverage is incomplete.",
    "The caller declares contacts for one field; real tick scheduling, expiry and spatial overlap are unverified.",
    "The caller supplies a known target scalar; default 1 is an explicit neutral assumption, not a discovered global actor default.",
    "Heat is pre-defense: armor, shields, resistance, weakspots and final target HP parity are outside this reference.",
    "Status DoT and status duration are omitted; weapon elemental, critical and status values are not inherited.",
)


def _nonnegative_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return result


def _float32(value: float) -> float:
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError as exc:
        raise ValueError("value exceeds finite float32 range") from exc
    if not math.isfinite(result):
        raise ValueError("value exceeds finite float32 range")
    return result


def reference(*, base_damage_multiplier: float, hit_contacts: int = 1,
              target_scalar: float = 1.0) -> dict:
    """Return a bounded direct-Heat primitive, never inferred lifetime damage.

    query = float32(2000 * B); snapshot = trunc_int32(query)
    heat_per_contact = float32(snapshot * float32(known_target_scalar))
    heat_amount = heat_per_contact * declared_contacts
    """
    multiplier = _nonnegative_finite(base_damage_multiplier, "base_damage_multiplier")
    scalar = _float32(_nonnegative_finite(target_scalar, "target_scalar"))
    if isinstance(hit_contacts, bool) or not isinstance(hit_contacts, int) or hit_contacts < 0:
        raise ValueError("hit_contacts must be a nonnegative integer")
    query = _float32(2000.0 * multiplier)
    if query >= 2 ** 31:
        raise ValueError("query amount exceeds the supported nonnegative int32 snapshot range")
    snapshot = math.trunc(query)
    heat_per_contact = _float32(snapshot * scalar)
    try:
        heat_amount = heat_per_contact * hit_contacts
    except OverflowError as exc:
        raise ValueError("contact total exceeds finite reference range") from exc
    if not math.isfinite(heat_amount):
        raise ValueError("contact total exceeds finite reference range")
    return {
        "supported": True,
        "scope": "independent-research-pre-defense-direct-heat-per-declared-contact",
        "base_damage_multiplier": multiplier,
        "hit_contacts": hit_contacts,
        "target_scalar": scalar,
        "query_base_amount_float32": query,
        "field_snapshot_int32": snapshot,
        "predefense_heat_per_contact": heat_per_contact,
        "predefense_heat_amount": heat_amount,
        "source_build": "2026.10.22.13.12",
        "source_hashes": dict(SOURCE_HASHES),
        "native_contract": {
            "query": "0x14160c5a0 -> 0x141234720; EmbedDeathAttack",
            "lua_int32": "0x141708b90 -> 0x140bd53f0; Element+0x628",
            "victim_packet": "0x141482900 -> 0x14111fa60 -> 0x140563c60",
        },
        "limits": list(LIMITS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-damage-multiplier", type=float, required=True)
    parser.add_argument("--hit-contacts", type=int, default=1)
    parser.add_argument("--target-scalar", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        result = reference(**vars(args))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
