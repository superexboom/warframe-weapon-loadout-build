"""Released-card corrections shared by manual and automatic catalogs."""
from __future__ import annotations
from typing import Any, Mapping, Sequence

RELEASED_ARCHGUN_MODS = {
    '/Lotus/Upgrades/Mods/Archwing/Rifle/Expert/ArchwingWeaponFireDamageModExpert': {
        'nameEn': 'Primed Combustion Rounds', 'element': 'DT_FIRE',
        'released': '2026-05-15',
        'source': 'https://www.reddit.com/r/Warframe/comments/1tdvui0/baro_kiteer_inventory_and_recommendations_20260515/',
    },
    '/Lotus/Upgrades/Mods/Archwing/Rifle/Expert/ArchwingWeaponFreezeDamageModExpert': {
        'nameEn': 'Primed Polar Magazine', 'element': 'DT_FREEZE',
        'released': '2026-08-21',
        'source': 'https://www.reddit.com/r/Warframe/comments/1vufw4w/baro_kiteer_inventory_and_recommendations_20260821/',
    },
}

def released_mod_catalog(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    # excludeFromCodex is not a release flag; override only observed sales.
    result = []
    for record in records:
        evidence = RELEASED_ARCHGUN_MODS.get(str(record.get('path') or ''))
        matches = evidence and (
            record.get('nameEn') == evidence['nameEn']
            and record.get('maxRank') == 10
            and record.get('compatibility') == '/Lotus/Weapons/Tenno/Archwing/Primary/ArchGun'
            and not record.get('isSubUpgrade') and bool(record.get('icon'))
            and any(
                e.get('upgradeType') == 'WEAPON_PERCENT_BASE_DAMAGE_ADDED'
                and e.get('damageType') == evidence['element']
                and e.get('operation') == 'ADD' and e.get('valuePerRank') == 0.17
                for e in record.get('effects') or () if isinstance(e, Mapping)
            )
        )
        if matches and record.get('selectable') is False:
            record = {**record, 'selectable': True, 'releaseOverride': dict(evidence)}
        result.append(record)
    return result
