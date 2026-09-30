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

# Exact raw paths: PlayerDamageMultiplier=2, Initial/MaximumFireIterations=1/12,
# INCREMENT, AmmoConsumptionDivisor=3, ContinuousMaxShots=8.
SPOOL_PROFILES = {
    '/Lotus/Weapons/Grineer/Pistols/GrnDWUniques/GrnTwinKohmaks': {
        'directTotal':15., 'playerDamageMultiplier':2.,
        'spool':{'initial':1,'maximum':5,'ammoDivisor':3,'rateStart':.2,'rateShots':20,'spindown':2.}},
    '/Lotus/Weapons/Grineer/Pistols/GrnKohmPistol/GrnKohmPistol': {
        'directTotal':15., 'playerDamageMultiplier':2.,
        'spool':{'initial':1,'maximum':5,'ammoDivisor':3,'rateStart':.2,'rateShots':5,'spindown':2.}},
    '/Lotus/Weapons/Grineer/LongGuns/GrnSpark/GrnSparkRifle': {
        'directTotal':15., 'playerDamageMultiplier':2.,
        'spool':{'initial':1,'maximum':12,'ammoDivisor':3,'rateStart':.2,'rateShots':8,'spindown':1.5}},
    '/Lotus/Weapons/Grineer/KuvaLich/LongGuns/Kohm/KuvaKohm': {
        'directTotal':10., 'playerDamageMultiplier':2.,
        'spool':{'initial':1,'maximum':12,'ammoDivisor':3,'rateStart':.2,'rateShots':8,'spindown':2.}},
}

def base_profile(weapon, fire_mode=0):
    from .manual_combat import reference
    if weapon.get('isIncarnonForm'):
        return {}
    selected = int(weapon.get('__selectedFireMode__', fire_mode))
    profile = {**reference().get('auditedAttacks', {}).get(weapon.get('path'), {}),
               **BATTERY_PROFILES.get(weapon.get('path'), {}),
               **SPOOL_PROFILES.get(weapon.get('path'), {})}
    if selected:
        profile = profile.get('modes', {}).get(str(selected), {})
    cadence = reference().get('cadenceProfiles', {}).get(weapon.get('path'), {})
    if cadence.get('fireMode') == selected:
        profile = {**profile, **cadence}
    if not profile:
        return {}
    mode = (weapon.get('fireModes') or [{}])[fire_mode]
    if profile.get('ammoCost') is not None and mode.get('ammoCost') != profile['ammoCost']:
        return {}
    if profile.get('projectile') and (mode.get('damage') or {}).get('projectile') != profile['projectile']:
        return {}
    total = sum(((mode.get('damage') or {}).get('types') or {}).values())
    if abs(total - profile.get('directTotal', total)) > 0.02:
        return {}
    return profile
