"""Static audit of weapon MOD mechanics that cannot be represented by a flat panel.

The report is deliberately fail-closed: a MOD with runtime/conditional/script
semantics is listed for review instead of being silently treated as a normal
damage bucket.  It is an inventory tool, not a gameplay approximation.

F16锛堝璁′慨澶嶏級璁℃暟鍚堝悓锛?
- weaponMods              鈫?閫氳繃姝﹀櫒鍏煎绛涢€夛紙compatibility 鍚?/Weapons/锛夌殑
                            鍏ㄩ儴 MOD 琛屾暟锛堝垎姣嶏細姝﹀櫒 MOD 鎬绘暟锛夈€?
- auditedRows             鈫?杩涘叆瀹¤鏄庣粏鐨勮鏁帮紙鍚潯浠?鑴氭湰/鏈敮鎸?鐗规畩椤癸級銆?
- compatibilityWithoutWeaponSupport 鈫?compatibility 鍛戒腑浣?support.weapon
                            涓哄亣鐨勮鏁帮紙鍚屼竴鍒嗘瘝锛夈€?
- eventUnmodeledCandidates 鈫?unsupported 鎴?scripts 闈炵┖鐨勮鏁帮紙鍚屼竴鍒嗘瘝锛夈€?
- 鍚勮鏁版樉寮忔惡甯﹁嚜宸辩殑鍒嗘瘝锛屼笉鍐嶆妸涓嶅悓绛涢€夐樁娈电殑鏁板瓧褰撴垚鍚屽垎姣嶇殑
  銆屾満鍒跺畬鎴愮巼銆嶃€?

Usage:
    python tools/audit_weapon_mod_mechanics.py
    python tools/audit_weapon_mod_mechanics.py --output .local/reports/mod-mechanics.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "data" / "export" / "2026.08.13.13.24"


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data") if isinstance(payload, Mapping) else payload
    if isinstance(rows, Mapping):
        rows = rows.values()
    return [row for row in rows or () if isinstance(row, Mapping)]


def _find_scripts(value: Any, out: set[str]) -> None:
    if isinstance(value, Mapping):
        for key in ("Script", "script"):
            if value.get(key):
                out.add(str(value[key]))
        for child in value.values():
            _find_scripts(child, out)
    elif isinstance(value, list):
        for child in value:
            _find_scripts(child, out)


def audit() -> dict[str, Any]:
    mods = _records(EXPORT_DIR / "mods.json")
    weapon_mod_total = 0
    rows: list[dict[str, Any]] = []
    compatibility_without_support = 0
    event_unmodeled_candidates = 0
    for mod in mods:
        support = mod.get("support") or {}
        compatibility = str(mod.get("compatibility") or "")
        weapon_compatible = bool(support.get("weapon")) or (
            "/Weapons/" in compatibility and "Powersuit" not in compatibility
        )
        if not weapon_compatible:
            continue
        weapon_mod_total += 1
        if not bool(support.get("weapon")):
            compatibility_without_support += 1
        effects = [effect for effect in mod.get("effects") or () if isinstance(effect, Mapping)]
        conditional = [effect for effect in mod.get("conditionalEffects") or () if isinstance(effect, Mapping)]
        scripts: set[str] = set()
        _find_scripts(mod.get("runtimeScripts"), scripts)
        _find_scripts(mod.get("effects"), scripts)
        _find_scripts(mod.get("conditionalEffects"), scripts)
        unsupported = [
            {
                "upgradeType": effect.get("upgradeType"),
                "supported": effect.get("supported"),
                "validType": effect.get("validType"),
                "validProcTypes": effect.get("validProcTypes"),
                "symbolFilter": effect.get("symbolFilter"),
            }
            for effect in effects
            if effect.get("supported") is False
        ]
        special = [
            {
                "upgradeType": effect.get("upgradeType"),
                "valuePerRank": effect.get("valuePerRank"),
                "validType": effect.get("validType"),
                "validProcTypes": effect.get("validProcTypes"),
                "symbolFilter": effect.get("symbolFilter"),
            }
            for effect in effects
            if effect.get("validType")
            or effect.get("validProcTypes")
            or effect.get("symbolFilter")
            or effect.get("upgradeType") in {
                "WEAPON_PROC_DAMAGE",
                "WEAPON_AREA_OF_EFFECT",
                "WEAPON_HEADSHOT_MULTIPLIER",
                "WEAPON_RELOAD_SPEED",
            }
        ]
        if not (conditional or scripts or unsupported or special):
            continue
        mechanic_status = (
            "runtime-or-conditional"
            if conditional or scripts
            else "static-qualified"
        )
        if unsupported or scripts:
            event_unmodeled_candidates += 1
        rows.append(
            {
                "path": mod.get("path"),
                "nameEn": mod.get("nameEn"),
                "nameZh": mod.get("nameZh"),
                "compatibility": mod.get("compatibility"),
                "supportWeapon": bool(support.get("weapon")),
                "modFamily": mod.get("modFamily"),
                "effects": special,
                "unsupportedEffects": unsupported,
                "conditionalEffectCount": len(conditional),
                "scripts": sorted(scripts),
                "mechanicStatus": mechanic_status,
                "supportGap": not bool(support.get("weapon")),
                "eventModelRequired": bool(conditional or scripts or unsupported),
            }
        )
    rows.sort(key=lambda row: (str(row.get("nameEn") or "").casefold(), str(row.get("path") or "")))
    return {
        "schemaVersion": 2,
        "buildLabel": "2026.08.13.13.24",
        "summary": {
            # F16锛氭瘡涓鏁版樉寮忓０鏄庤嚜宸辩殑绛涢€夐樁娈典笌鍒嗘瘝銆?
            "weaponMods": weapon_mod_total,
            "weaponModsDenominator": "compatibility 鍚?/Weapons/ 鐨勫叏閮?MOD",
            "auditedRows": len(rows),
            "auditedRowsDenominator": "weaponMods锛堣繘鍏ユ槑缁?鍚潯浠?鑴氭湰/鏈敮鎸?鐗规畩椤癸級",
            "runtimeOrConditional": sum(row["mechanicStatus"] == "runtime-or-conditional" for row in rows),
            "staticQualified": sum(row["mechanicStatus"] == "static-qualified" for row in rows),
            "compatibilityWithoutWeaponSupport": compatibility_without_support,
            "compatibilityWithoutWeaponSupportDenominator": "weaponMods",
            "eventUnmodeledCandidates": event_unmodeled_candidates,
            "eventUnmodeledCandidatesDenominator": "weaponMods锛坲nsupported 鎴?scripts 闈炵┖锛?,
            "coverageNote": (
                "杩欐槸搴撳瓨瀹¤鑰岄潪杩愯鏃舵秷璐硅鐩栬瘉鏄庯細auditedRows 鏄瓫閫夊悗鐨勮鏁帮紝"
                "涓嶆槸鍏ㄩ儴 MOD 鐨勬満鍒跺畬鎴愮巼銆?
            ),
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".local" / "reports" / "weapon-mod-mechanics-audit.json",
    )
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
