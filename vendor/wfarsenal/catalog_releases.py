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

# Exact identities: docs/evidence/radial-round-20260927/expert-catalog-evidence.json
# Do not blanket-filter Expert/codexSecret or alias a different rank.
UNRELEASED_TIER_CLONES: dict[str, str] = {
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponArmorPiercingDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponArmorPiercingDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponCritChanceModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponCritChanceMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponCritDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponCritDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponCritFireRateBonusModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponCritFireRateBonusMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponElectricityDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponElectricityDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponFireDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponFireDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponFreezeDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponFreezeDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponGlaivePowerthrowModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponGlaivePowerthrowMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponGlaiveReflectionDecreaseModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponGlaiveReflectionDecreaseMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponGlaiveReflectionIncreaseModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponGlaiveReflectionIncreaseMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponGlaiveSpeedModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponGlaiveSpeedMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponMeleeChannelingEfficiencyModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeChargeRateMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponMeleeFinisherDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponMeleeFinisherDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponPowerDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponPowerDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponSlashDamageModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponSlashDamageMod',
    '/Lotus/Upgrades/Mods/Melee/Expert/WeaponStunChanceModExpert': '/Lotus/Upgrades/Mods/Melee/WeaponStunChanceMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponAmmoMaxModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponAmmoMaxMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponArmorPiercingDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponArmorPiercingDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponCritDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponCritDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponElectricityDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponElectricityDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponFireIterationsModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponFireIterationsMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponFireRateModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponFireRateMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponFreezeDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponFreezeDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponImpactDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponImpactDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolZoomFovModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponPistolZoomFovMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPunctureDepthModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponPunctureDepthMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponSlashDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponSlashDamageMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponStatusChanceModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponStunChanceMod',
    '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponToxinDamageModExpert': '/Lotus/Upgrades/Mods/Pistol/WeaponToxinDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/BowExplosionChanceModExpert': '/Lotus/Upgrades/Mods/Rifle/BowExplosionChanceMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponAmmoMaxModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponAmmoMaxMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponArmorPiercingDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponArmorPiercingDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponBowConvertAmmoModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponBowConvertAmmoMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponCritChanceModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponCritChanceMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponCritDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponCritDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponElectricityDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponElectricityDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFactionDamageCorpusExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFactionDamageCorpus',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFactionDamageGrineerExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFactionDamageGrineer',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFactionDamageInfestedExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFactionDamageInfested',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFireDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFireDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFireIterationsModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFireRateModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponFireRateMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponImpactDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponImpactDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponPunctureDepthModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponPunctureDepthMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponSlashDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponSlashDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponStatusChanceModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponStunChanceMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponToxinDamageMod',
    '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponZoomFovModExpert': '/Lotus/Upgrades/Mods/Rifle/WeaponZoomFovMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponAmmoMaxModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponAmmoMaxMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponArmorPiercingDamageModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponArmorPiercingDamageMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponFireDamageModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireDamageMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponFireIterationsModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireIterationsMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponFireRateModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponFireRateMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponImpactDamageModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponImpactDamageMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponPunctureDepthModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponPunctureDepthMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponSlashDamageModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponSlashDamageMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponStunChanceModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponStunChanceMod',
    '/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponToxinDamageModExpert': '/Lotus/Upgrades/Mods/Shotgun/WeaponToxinDamageMod',
}

def released_mod_catalog(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    # excludeFromCodex is not a release flag; override only observed sales.
    by_path = {str(r.get('path') or ''): r for r in records}
    result = []
    for record in records:
        base_path = UNRELEASED_TIER_CLONES.get(str(record.get('path') or ''))
        base = by_path.get(base_path or '')
        if (base and record.get('maxRank') == 10
                and isinstance(base.get('maxRank'), int) and base['maxRank'] < 10
                and record.get('rarity') != 'LEGENDARY'
                and record.get('nameTag') and record.get('modFamily')
                and all(record.get(key) == base.get(key)
                        for key in ('nameTag', 'modFamily', 'compatibility'))):
            record = {**record, 'selectable': False, 'catalogExclusion': {
                'reason': 'unreleased-tier-clone', 'basePath': base_path,
                'evidence': 'expert-catalog-20260927',
            }}
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
