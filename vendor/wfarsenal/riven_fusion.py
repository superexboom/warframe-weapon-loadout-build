"""Riven advanced-trait identity and availability, independent of recipe coverage."""

from __future__ import annotations
from typing import Any, Mapping

TAG_CODES = {
    "WeaponWeakpointDamage": "W",
    "WeaponWeakpointCriticalChance": "Y",
    "WeaponAmmoEfficiency": "AE",
    "WeaponMagazineReloadHolstered": "HR",
    "WeaponStatusDamage": "SD",
    "WeaponGasDamageMod": "GA",
    "WeaponCorrosiveDamageMod": "CO",
    "WeaponViralDamageMod": "VI",
    "WeaponRadiationDamageMod": "RA",
    "WeaponBlastDamageMod": "BL",
    "WeaponMagneticDamageMod": "MA",
    "WeaponFactionDamageOrokin": "FO",
    "WeaponFactionDamageTechrot": "FT",
    "WeaponFactionDamageScaldra": "FS",
    "WeaponMeleeHeavyAttackDamageMod": "HD",
    "WeaponMeleeHeavyAttackChargeMod": "HC",
    "WeaponMeleeParryAngleMod": "PA",
    "WeaponMeleeSlamDamageMod": "SL",
    "WeaponDamageAmountMod": "D",
    "WeaponZoomFovMod": "H",
    "WeaponFireIterationsMod": "S",
    "WeaponCritChanceMod": "0",
    "WeaponClipMaxMod": "L",
    "WeaponReloadSpeedMod": "F",
    "WeaponRecoilReductionMod": "Z",
    "WeaponAmmoMaxMod": "M",
    "WeaponStunChanceMod": "2",
    "WeaponToxinDamageMod": "6",
    "WeaponFireDamageMod": "4",
    "WeaponElectricityDamageMod": "7",
    "WeaponFreezeDamageMod": "5",
    "WeaponFactionDamageGrineer": "G",
    "WeaponFactionDamageCorpus": "C",
    "WeaponFactionDamageInfested": "I",
    "WeaponFactionDamageInfestation": "I",
}
FUSION_CODES = frozenset(
    {
        "W",
        "Y",
        "AE",
        "HR",
        "SD",
        "GA",
        "CO",
        "VI",
        "RA",
        "BL",
        "MA",
        "FO",
        "FT",
        "FS",
        "HD",
        "HC",
        "PA",
        "SL",
    }
)


def available_codes(payload: Mapping[str, Any], weapon_type: str) -> frozenset[str]:
    """A missing MergeOptions table means recipe coverage is unknown.

    Availability comes from the canonical type's explicit IsAdvancedTrait rows.
    Legacy payloads with no template array can still provide recipe-only data.
    """
    templates = payload.get("templates")
    if isinstance(templates, list):
        candidates = [
            t
            for t in templates
            if isinstance(t, Mapping) and t.get("weaponType") == weapon_type
        ]
        canonical = [t for t in candidates if "Modular" not in str(t.get("id", ""))]
        return frozenset(
            code
            for t in (canonical or candidates)
            for s in t.get("stats") or ()
            if isinstance(s, Mapping)
            and (s.get("isAdvancedTrait") or s.get("fusionOnly"))
            if (code := TAG_CODES.get(str(s.get("tag")), str(s.get("code") or "")))
            in FUSION_CODES
        )
    return frozenset(
        str(r.get("result"))
        for r in payload.get("fusionRecipes") or ()
        if isinstance(r, Mapping)
        and r.get("weaponType") == weapon_type
        and r.get("result") in FUSION_CODES
    )
