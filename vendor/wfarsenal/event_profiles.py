from __future__ import annotations

# Tenet Cycron battery: pinned WFSim b98b3d4 data/weapons/secondary/tenet_cycron.yaml
# sha256 24a9ba2a2800b940dba97f1489039775a2ec8642ede06c818b850a27304e1bc1.
# Raw build 2026.09.22.16.46 CrpBECycron.txt confirms both 0.5s delays; the
# recharge rate is reference-calibrated, not recovered from this raw child.
BATTERY_PROFILES = {
    '/Lotus/Weapons/Corpus/BoardExec/Secondary/CrpBECycron/CrpBECycron': {
        'directTotal': 22.0,
        'battery': {'regenPerSecond': 40.0, 'delayEmptySeconds': .5, 'delayPartialSeconds': .5},
    },
}

def base_profile(weapon, fire_mode=0):
    from .manual_combat import reference
    if weapon.get('isIncarnonForm') or int(weapon.get('__selectedFireMode__', fire_mode)) != 0:
        return {}
    profile = {**reference().get('auditedAttacks', {}).get(weapon.get('path'), {}),
               **BATTERY_PROFILES.get(weapon.get('path'), {})}
    mode = (weapon.get('fireModes') or [{}])[fire_mode]
    total = sum((mode.get('damage', {}).get('types') or {}).values())
    if abs(total - profile.get('directTotal', total)) > 0.02:
        return {}
    return profile
