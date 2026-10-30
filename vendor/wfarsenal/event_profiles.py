from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path


def is_incarnon_mode(weapon,index):
    modes = weapon.get('__baseFireModes__') or weapon.get('fireModes') or ()
    if not weapon.get('isIncarnon') or index<0 or index>=len(modes):
        return False
    if 'isIncarnonForm' in modes[index]:
        return bool(modes[index]['isIncarnonForm'])
    # Compatibility for historical exports. Melee activation is actor state,
    # and Onos has both a charge beam and a blast in its transformed form.
    if weapon.get('slot') in {'melee','arch_melee'}:
        return False
    if weapon.get('path')=='/Lotus/Weapons/Thanotech/EntratiWristGun/EntratiWristGunWeapon':
        return index>0
    return len(modes)>1 and index==len(modes)-1


# Projectile identities whose IgnoreHeadShotBonus declaration was recovered
# from Packages 2026.10.22.13.12 (SHA256 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06).
# The inherited Omicrus declaration has the same damage-only contract already
# modelled for Nataruk: retain head events, Deadhead and weakpoint crit chance.
# Do not classify every WaveProjectile alike. Prime Alternox explicitly clears
# the projectile flag for its main shot but inherits it on the multishot-copy
# projectile. Its separate impact behavior still disables head damage bonuses.
_PROJECTILE_HEADSHOT_BONUS_OVERRIDES = {
    '/Lotus/Weapons/Tenno/Bows/Omicrus/OmicrusWavePlayerProj': True,
    '/Lotus/Weapons/Tenno/Bows/Omicrus/OmicrusPerfectWavePlayerProj': True,
    '/Lotus/Weapons/Tenno/Bows/HuntingBowIncarnonAltFireWaveProj': True,
    '/Lotus/Weapons/Tenno/Bows/MkIHuntingBowIncarnonAltFireWaveProj': True,
    '/Lotus/Weapons/Tenno/Bows/PrimeHuntingBowIncarnonAltFireWaveProj': True,
    '/Lotus/Weapons/Tenno/Bows/StalkerBowIncarnonAltFireWaveProj': True,
    '/Lotus/Weapons/Tenno/LongGuns/GyreRifle/GyrRifleWaveProj': True,
    '/Lotus/Weapons/Tenno/LongGuns/GyreRifle/GyrRifleWaveProjMS': True,
    '/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWaveProj': False,
    '/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWaveProjMS': True,
    '/Lotus/Weapons/Tenno/LongGuns/TnoLotusPodShotgun/TnoLotusPodShotgunWaveProj': True,
    '/Lotus/Weapons/Tenno/LongGuns/PrimeSteflos/PrimeSteflosShotgunWaveProj': True,
    '/Lotus/Weapons/Tenno/Pistol/LexAltFireProjectile': True,
    '/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLexAltFireProjectile': True,
    '/Lotus/Weapons/Tenno/Zariman/LongGuns/PumpShotgun/ZarimanShotgunAltWaveProj': True,
}


# Older frozen exports omitted the weapon impact behavior's separate flag.
# Match weapon, original mode and projectile together; never a name-only rule.
# Current EXE 0x141482900 branches to the same bypass when projectile +0x25c
# OR the impact getter 0x141079080 returns true (PvE byte +0x18d).
_IMPACT_HEADSHOT_BONUS_OVERRIDES = {
    ('/Lotus/Weapons/Corpus/LongGuns/CrpShotgun/CrpShotgun', 0,
     '/Lotus/Weapons/Corpus/LongGuns/CrpShotgun/CrpShotgunProjectile'),
    ('/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEArcaPlasmor/CrpBEArcaPlasmor', 0,
     '/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEArcaPlasmor/CrpBEArcaPlasmorProjectile'),
    ('/Lotus/Weapons/Tenno/LongGuns/TnWispRifle/TnWispRifle', 0,
     '/Lotus/Weapons/Tenno/LongGuns/TnWispRifle/TnWispRifleShotgunProj'),
    ('/Lotus/Weapons/Tenno/LongGuns/PrimeFulmin/PrimeFulmin', 0,
     '/Lotus/Weapons/Tenno/LongGuns/PrimeFulmin/PrimeFulminShotgunProj'),
    ('/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWeapon', 0,
     '/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWaveProj'),
}


def ignores_headshot_bonus(weapon, fire_mode=0):
    """Combine the active projectile and impact behavior's head-damage flags.

    Each explicit exported boolean takes precedence over its own legacy rule;
    a projectile false cannot override impact true. Unknown mechanisms do not
    inherit flags from the weapon name, and derived radial/field parts cannot
    borrow the direct attack's impact declaration.
    """
    modes = weapon.get('fireModes') or ()
    if not isinstance(fire_mode, int) or fire_mode < 0 or fire_mode >= len(modes):
        return False
    mode = modes[fire_mode]
    damage = mode.get('damage') or {}
    # manual_combat copies the direct damage block into derived components,
    # including both explicit flags. They are parent provenance there; radial
    # hit semantics take priority over either copied flag or legacy fallback.
    if mode.get('__radialPart__') or damage.get('source') in (
            'ExplosiveAttack', 'RadialDamage', 'EmbedDeathAttack', 'StackingAttack'):
        return False
    projectile = damage.get('projectile')
    declared = damage.get('ignoreHeadshotBonus')
    projectile_ignored = (declared if isinstance(declared, bool)
                          else bool(_PROJECTILE_HEADSHOT_BONUS_OVERRIDES.get(projectile, False)))
    impact_declared = damage.get('impactIgnoreHeadshotBonus')
    index = weapon.get('__selectedFireMode__', fire_mode)
    impact_ignored = (impact_declared if isinstance(impact_declared, bool) else
                      (weapon.get('path'), index, projectile) in _IMPACT_HEADSHOT_BONUS_OVERRIDES)
    return projectile_ignored or impact_ignored

# Battery (regenerating magazine) weapons: data/mechanics/battery-profiles.json
# (tools/import_battery_profiles.py; native package values, pinned WFSim
# battery list for membership). A battery belongs to the weapon, not to a
# fire mode or damage total, so it applies to every non-Incarnon mode.
@lru_cache(maxsize=1)
def battery_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        rows = json.loads((root / "data/mechanics/battery-profiles.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}
    return {path: {key: float(row[key]) for key in ("regenPerSecond", "delayEmptySeconds", "delayPartialSeconds",
                                                     "emptyAnimationSeconds") if key in row}
            for path, row in rows.items()}

# Weapon passives the export lacks: data/mechanics/weapon-passives.json.
@lru_cache(maxsize=1)
def weapon_passives():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return json.loads((root / "data/mechanics/weapon-passives.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}


def innate_conditionals(weapon, fire_mode):
    """The weapon's DefaultUpgrades records a replay event grants (innate rows
    with conditionalEffects) for ``fire_mode``."""
    rows = (weapon_passives().get(str(weapon.get('path') or '')) or {}).get('innate') or ()
    return [r for r in rows if r.get('conditionalEffects') and fire_mode in (r.get('fireModes') or (fire_mode,))]


def execute_below(weapon, fire_mode):
    """The health share below which the weapon's own passive kills (Enkaus's
    dissolve, an ink-stained target below 35%), or 0."""
    if weapon.get('isIncarnonForm'):
        return 0.0
    rows = (weapon_passives().get(str(weapon.get('path') or '')) or {}).get('innate') or ()
    return max((float(r['executeBelowHealth']) for r in rows if r.get('executeBelowHealth')
                and fire_mode in (r.get('fireModes') or (fire_mode,))), default=0.0)


def super_status_on_crit(weapon):
    """(chance, status chance) of the weapon's crit-armed set status, or None."""
    if weapon.get('isIncarnonForm'):
        return None
    spec = (weapon_passives().get(str(weapon.get('path') or '')) or {}).get('superStatusOnCrit')
    return (float(spec['chance']), float(spec['statusChance'])) if spec else None


def reload_projectiles(weapon):
    """The grenade a reload throws (weapon-passives.json reloadProjectiles), or None."""
    if weapon.get('isIncarnonForm'):
        return None
    return (weapon_passives().get(str(weapon.get('path') or '')) or {}).get('reloadProjectiles')


def super_crit_on_status(weapon):
    """(chance, crit chance) of the weapon's status-armed set crit, or None."""
    if weapon.get('isIncarnonForm'):
        return None
    spec = (weapon_passives().get(str(weapon.get('path') or '')) or {}).get('superCritOnStatus')
    return (float(spec['chance']), float(spec['critChance'])) if spec else None

# Round-by-round reloads: data/mechanics/shell-reload-profiles.json
# (tools/import_shell_reload_profiles.py; native AmmoTakenPerReload = 1 state
# timings). Like a battery, the loop belongs to the weapon's magazine.
@lru_cache(maxsize=1)
def shell_reload_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        rows = json.loads((root / "data/mechanics/shell-reload-profiles.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}
    return {path: {**{key: float(row[key]) for key in ("reloadStart", "reloadPerShell", "reloadEnd")},
                   "modeSwitchLoadsShell": bool(row.get("modeSwitchLoadsShell"))}
            for path, row in rows.items()}

# Burst cadence per fire mode: data/mechanics/burst-profiles.json
# (tools/import_burst_profiles.py; native WeaponBurstStateBehavior matched by
# behaviour position). An Incarnon form that is its own mode has its own entry.
@lru_cache(maxsize=1)
def burst_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        rows = json.loads((root / "data/mechanics/burst-profiles.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}
    return {path: {int(index): ({"count": int(mode["count"]), "delay_seconds": float(mode["delay_seconds"])}
                                | ({"ignoreFireRate": True} if mode.get("ignoreFireRate") else {})
                                | ({"remainingClip": True} if mode.get("remainingClip") else {}),
                                (mode.get("trigger"), mode.get("fireRate"), mode.get("behaviour")))
                   for index, mode in row["modes"].items()}
            for path, row in rows.items()}


# Native charge per fire mode: data/mechanics/charge-profiles.json
# (tools/import_charge_profiles.py). The pinned export carries chargeTime=null.
@lru_cache(maxsize=1)
def charge_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        rows = json.loads((root / "data/mechanics/charge-profiles.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}
    return {path: {int(index): ({"seconds": float(mode["seconds"]), "source": "native-ChargeTime",
                                 "scalesWithFireRate": mode.get("chargeModifier") == "WEAPON_FIRE_RATE",
                                 **({"beforeFire": bool(mode["beforeFire"])} if "beforeFire" in mode else {}),
                                 **({"perfect": {key: mode["perfect"][key] for key in ("ratio", "projectile", "damage", "fullProjectile", "fullTotal")}}
                                    if (mode.get("perfect") or {}).get("paysOff") else {})},
                                (mode.get("trigger"), mode.get("fireRate"), mode.get("behaviour")))
                   for index, mode in row["modes"].items()}
            for path, row in rows.items()}


def _mode_entry(table, weapon, fire_mode):
    """A per-mode native record, only while the mode is still that state
    behaviour (behaviour position, trigger, pull rate). A weapon reduced to
    its selected mode finds it by the behaviour position the export keeps."""
    entry = table.get(weapon.get('path'), {}).get(int(fire_mode))
    if not entry:
        return None
    trigger, rate, behaviour = entry[1]
    modes = weapon.get('__baseFireModes__') or weapon.get('fireModes') or ()
    mode = (modes[int(fire_mode)] if int(fire_mode) < len(modes) else
            next((m for m in weapon.get('fireModes') or () if m.get('index') == behaviour), None))
    if (mode is None or mode.get('index', behaviour) != behaviour or mode.get('trigger') != trigger
            or abs(float(mode.get('fireRate') or 0.) - float(rate or 0.)) > 1e-6):
        return None
    return dict(entry[0])


def native_charge(weapon, fire_mode):
    return _mode_entry(charge_profiles(), weapon, fire_mode)


def with_native_charge(profile, weapon, fire_mode):
    """Audited charge wins; the native record supplies the time otherwise and
    always says whether fire-rate mods shorten it."""
    charge = native_charge(weapon, fire_mode)
    if not charge:
        return profile
    perfect = charge.pop('perfect', None)
    if perfect:
        profile = {**profile, 'perfectCharge': perfect}
    if profile.get('bow'):
        return profile
    if profile.get('charge'):
        return {**profile, 'charge': {**profile['charge'], 'scalesWithFireRate': charge['scalesWithFireRate']}}
    return {**profile, 'charge': charge}


def perfect_release(profile, mode, combat_state=None):
    """Perfect release by default (combatState.perfectCharge): the charge or
    bow draw ends at the window's start and the perfect projectile fires."""
    perfect = profile.get('perfectCharge')
    if not perfect or (combat_state or {}).get('perfectCharge', True) is False:
        return profile, mode
    damage = mode.get('damage') or {}
    # Only the full-charge shot itself: a replay part copies the mode with its own damage.
    if (damage.get('projectile') != perfect['fullProjectile']
            or abs(sum((damage.get('types') or {}).values()) - perfect['fullTotal']) > .02):
        return profile, mode
    profile = dict(profile)
    if profile.get('bow') and profile.get('drawSeconds') is not None:
        profile['drawSeconds'] = float(profile['drawSeconds']) * perfect['ratio']
    elif profile.get('charge'):
        profile['charge'] = {**profile['charge'], 'seconds': float(profile['charge']['seconds']) * perfect['ratio']}
    return profile, {**mode, 'damage': perfect['damage'], 'perfectRelease': True}


# Kill-charged alternate fires: data/mechanics/kill-charge-profiles.json
# (tools/import_kill_charged_alts.py; native AddChargeConditions PRIMARY_KILL).
@lru_cache(maxsize=1)
def kill_charge_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return json.loads((root / "data/mechanics/kill-charge-profiles.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}


def kill_charge_cycle(weapon, fire_mode):
    """The primary + alternate cycle when the kill-charged alternate is selected."""
    entry = kill_charge_profiles().get(weapon.get('path'))
    if not entry or weapon.get('isIncarnonForm') or int(fire_mode) != entry['altMode']:
        return None
    return dict(hits=float(entry['killsPerUse']), pool=float(entry['shotsPerGauge']),
                enterSeconds=float(entry['switchInSeconds']), exitSeconds=float(entry['switchOutSeconds']),
                chargeOn='kills', killCharged=True,
                **({'chargeBeforeFire': True} if entry.get('chargeBeforeFire') else {}))


# Modes that reload after every shot: data/mechanics/reload-after-shot.json
# (tools/import_reload_after_shot.py; native ReloadAfterEveryShot, spear throws).
@lru_cache(maxsize=1)
def reload_after_shot_profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        rows = json.loads((root / "data/mechanics/reload-after-shot.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}
    return {path: {int(index): ({"reloadAfterEveryShot": True}, (mode.get("trigger"), mode.get("fireRate"), mode.get("behaviour")))
                   for index, mode in row["modes"].items()}
            for path, row in rows.items()}


def reloads_after_every_shot(weapon, fire_mode):
    return bool(_mode_entry(reload_after_shot_profiles(), weapon, fire_mode))


def native_burst(weapon, fire_mode):
    # The burst belongs to the mode's state behaviour, not its damage: the
    # mode must still be the imported one (trigger and pull rate).
    return _mode_entry(burst_profiles(), weapon, fire_mode)

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

# Fire-rate spin-up only (no multishot spool): pinned WFSim 5809c383+ release
# dc8413a8fab9, attack.sustained_fire_rate, wiki-transcribed there. Each shot
# fires at start + (end - start) * min(shots / overShots, 1) of the live rate;
# the count restarts after any pause (fight/after.rs). Kuva Kohm keeps its
# raw-path SPOOL_PROFILES entry.
FIRE_RATE_SPOOL_PROFILES = {
    '/Lotus/Weapons/Infested/InfestedLich/LongGuns/CodaBubonico/CodaBubonicoCannon': {
        'directTotal': 41.0, 'referenceId': 'coda_bubonico',
        'referenceSource': 'data/weapons/primary/coda_bubonico.yaml',
        'referenceSha256': '6270b1893dfa04558162ee1cc56495c090c3e54a0fa4bf8caffba765776e182e',
        'fireRateSpool': {'start': 0.3, 'end': 1.0, 'overShots': 6.0}},
    '/Lotus/Weapons/Tenno/Rifle/HeavyRifle': {
        'directTotal': 25.0, 'referenceId': 'gorgon',
        'referenceSource': 'data/weapons/primary/gorgon.yaml',
        'referenceSha256': 'e71249b9ef84ae2977c395cccfcd993ad0fd802ed42f736e971a97add249cfe7',
        'fireRateSpool': {'start': 0.2, 'end': 1.0, 'overShots': 7.5}},
    '/Lotus/Weapons/Grineer/LongGuns/WraithGorgon/WraithGorgon': {
        'directTotal': 27.0, 'referenceId': 'gorgon_wraith',
        'referenceSource': 'data/weapons/primary/gorgon_wraith.yaml',
        'referenceSha256': '56fbd57614df5395fe2bdce99e871dc5e970883a3a57a996a2c12e72fe8daf0c',
        'fireRateSpool': {'start': 0.2, 'end': 1.0, 'overShots': 5.0}},
    '/Lotus/Weapons/Grineer/LongGuns/VoidTraderGorgon/VTGorgon': {
        'directTotal': 23.0, 'referenceId': 'prisma_gorgon',
        'referenceSource': 'data/weapons/primary/prisma_gorgon.yaml',
        'referenceSha256': 'cb29f52000f4b5092e74d79600138bf09482f601516d6ad54e0e4cbdec9b505e',
        'fireRateSpool': {'start': 0.2, 'end': 1.0, 'overShots': 6.0}},
    '/Lotus/Weapons/Tenno/Rifle/TennoAR': {
        'directTotal': 12.0, 'referenceId': 'soma',
        'referenceSource': 'data/weapons/primary/soma.yaml',
        'referenceSha256': 'e0565854f7db45a898792bde9629c7fed2f12fd964d618a00936bcafa80d8350',
        'fireRateSpool': {'start': 0.25, 'end': 1.0, 'overShots': 5.0}},
    '/Lotus/Weapons/Tenno/LongGuns/PrimeSoma/PrimeSomaRifle': {
        'directTotal': 12.0, 'referenceId': 'soma_prime',
        'referenceSource': 'data/weapons/primary/soma_prime.yaml',
        'referenceSha256': '45b636dc0b1b47371770258bb5d055870b0383b33bdccc737f3ee3d3e575262c',
        'fireRateSpool': {'start': 0.25, 'end': 1.0, 'overShots': 2.5}},
    '/Lotus/Weapons/ClanTech/Energy/CrpHeavyRifle': {
        'directTotal': 40.0, 'referenceId': 'supra',
        'referenceSource': 'data/weapons/primary/supra.yaml',
        'referenceSha256': '0c58bdd81692baee67ce3a4becf6c786b8ad5c077e4713aee45e47603173392b',
        'fireRateSpool': {'start': 0.1, 'end': 1.0, 'overShots': 4.0}},
    '/Lotus/Weapons/Corpus/LongGuns/Machinegun/SupraVandal': {
        'directTotal': 40.0, 'referenceId': 'supra_vandal',
        'referenceSource': 'data/weapons/primary/supra_vandal.yaml',
        'referenceSha256': '8fbce17a41e381412417d1a0e44304c77c860bc6c03655f859507cc34bcea2fa',
        'fireRateSpool': {'start': 0.4, 'end': 1.0, 'overShots': 3.0}},
    '/Lotus/Weapons/Tenno/LongGuns/TnBardRifle/TnBardRifle': {
        'directTotal': 24.0, 'referenceId': 'tenora',
        'referenceSource': 'data/weapons/primary/tenora.yaml',
        'referenceSha256': '26b29d84013b59b8c93796ee05863a6535ad328abc1fc08edcb0b3d9d796d02f',
        'fireRateSpool': {'start': 0.4, 'end': 1.0, 'overShots': 8.0}},
    '/Lotus/Weapons/Tenno/LongGuns/PrimeTenora/TenoraPrimeWeapon': {
        'directTotal': 28.0, 'referenceId': 'tenora_prime',
        'referenceSource': 'data/weapons/primary/tenora_prime.yaml',
        'referenceSha256': 'e9c03745b0180a8c563727afde4822702dfd29bf80a009790e54736519fac853',
        'fireRateSpool': {'start': 0.4, 'end': 1.0, 'overShots': 8.0}},
}

def _mode_profile(weapon, fire_mode=0):
    from .manual_combat import reference
    selected = int(weapon.get('__selectedFireMode__', fire_mode))
    profile = {**reference().get('auditedAttacks', {}).get(weapon.get('path'), {}),
               **SPOOL_PROFILES.get(weapon.get('path'), {}),
               **FIRE_RATE_SPOOL_PROFILES.get(weapon.get('path'), {})}
    if selected:
        profile = profile.get('modes', {}).get(str(selected), {})
    if weapon.get('isIncarnonForm') and not profile.get('allowIncarnon'):
        return {}
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


def base_profile(weapon, fire_mode=0):
    profile = with_native_charge(_mode_profile(weapon, fire_mode), weapon, weapon.get('__selectedFireMode__', fire_mode))
    if weapon.get('isIncarnonForm'):
        return profile
    battery = battery_profiles().get(weapon.get('path'))
    if battery:
        profile = {**profile, 'battery': battery}
    shells = shell_reload_profiles().get(weapon.get('path'))
    if shells and profile.get('reloadPerShell') is None:
        profile = {**profile, **shells}
    burst = native_burst(weapon, weapon.get('__selectedFireMode__', fire_mode))
    if burst and not profile.get('burst'):
        profile = {**profile, 'burst': burst}
    return profile


def co_profile(weapon,fire_mode=0):
    from .manual_combat import reference
    selected = int(weapon.get('__selectedFireMode__',fire_mode))
    profile = reference().get('coProfiles',{}).get(weapon.get('path'),{}).get(str(selected)) or {}
    damage = (weapon.get('fireModes') or [{}])[fire_mode].get('damage') or {}
    if (profile.get('projectile')!=damage.get('projectile')
            or abs(profile.get('directTotal',-1)-sum((damage.get('types') or {}).values()))>.02):
        return {}
    return profile
