"""``damage.apply_mods_spec`` on the native core.

The reference splits into two kinds of work:

- what depends only on the weapon record, the fire mode and the scenario
  (event profiles, Incarnon / sniper / CO profiles, the base damage vector,
  which effects qualify): computed here in Python once per weapon variant and
  kept in a :class:`Prep`;
- what depends on the effects (buckets, ``_combine``, element coalescing, the
  CO tail): ``wfcore.apply_mods``, mirroring the reference's float operation
  order so results agree to the last bit (tools: the apply_mods corpus check).

A Prep is keyed by the weapon record (``record_keys.record_key``: callers
build ``{**weapon, ...}`` copies that share its values; the Prep pins them)
and by the scenario fields the weapon side reads.
``WF_NATIVE=0`` (or a missing core) keeps the Python reference;
``WF_NATIVE_SHADOW=1`` also runs the reference on every call and raises on
the first difference (types included: an int ``0`` is not a float ``0.0``).
"""
from __future__ import annotations

import math
import os
from typing import Any, Mapping

from .record_keys import pin, record_key

try:  # pragma: no cover - exercised when the native core is built
    from . import wfcore
except ImportError:  # pragma: no cover
    wfcore = None

ENABLED = (wfcore is not None and hasattr(wfcore, "ModsPrep") and getattr(wfcore, "RELOAD_SCALED_TRANSFORMS", 0) and os.environ.get("WF_NATIVE") != "0"
           and os.environ.get("WF_NATIVE_MODS") != "0")
SHADOW = os.environ.get("WF_NATIVE_SHADOW") == "1"

# Plain dict, emptied when full: request threads share it, and single dict
# operations stay atomic under the GIL where an LRU's move/pop pairs would not.
_PREPS: "dict[tuple, Prep]" = {}
_PREPS_MAX = 512


class Unsupported(Exception):
    """This call stays on the Python reference."""


class Prep:
    __slots__ = ("weapon", "pinned", "core", "zoom", "candidates", "base_obj", "base_total_obj")


def _scenario_key(scenario) -> tuple:
    state = scenario.combat_state
    return (scenario.aiming, scenario.heavy_attack, scenario.distance, scenario.incarnon_cycle,
            state.get("perfectCharge", True) is False, state.get("orbPasses", 0), state.get("orbStacks", 1),
            state.get("orbSpecialShield", False))


def prep_for(weapon: Mapping[str, Any], fire_mode: int, scenario) -> Prep:
    key = (record_key(weapon), fire_mode, _scenario_key(scenario))
    prep = _PREPS.get(key)
    if prep is not None:
        return prep
    prep = _build(weapon, fire_mode, scenario)
    if len(_PREPS) >= _PREPS_MAX:
        _PREPS.clear()
    _PREPS[key] = prep
    return prep


def _build(weapon: Mapping[str, Any], fire_mode: int, scenario) -> Prep:
    from .damage import (
        DEFERRED_WEAPON_REASON_CODES, MELEE_SLOTS, NATIVE_DEFAULT_CLIP, RUNTIME_UPGRADE_TYPES,
        SUPPORTED_WEAPON_UPGRADE_TYPES, _KNOWN_MULTIPART_PATHS, _qualifier_rejection, _read_innate_elements,
        _require_nonnegative_finite, archgun_arcane_type_applies,
    )
    from .event_profiles import (base_profile, co_profile, perfect_release, reloads_after_every_shot,
                                 super_crit_on_status, super_status_on_crit)
    from .sniper import zoom_effects
    from .beam_ramp import is_furis_beam
    from .manual_combat import reference

    modes = weapon.get("fireModes") or []
    if fire_mode >= len(modes):
        raise Unsupported("fire mode out of range")  # the reference raises its own error
    mode = modes[fire_mode]
    if mode.get('nativeIgnoreFireIterations') and not getattr(wfcore,'NATIVE_FIRE_ITERATION_LOCK',0):
        raise Unsupported('native projectile count lock needs updated core')
    if (mode.get('behaviorKind') == 'auxiliary-melee'
            and weapon.get('slot') in ('primary', 'secondary', 'arch_gun')):
        raise Unsupported("auxiliary melee")
    event_profile = base_profile(weapon, fire_mode)
    event_profile, mode = perfect_release(event_profile, mode, getattr(scenario, 'combat_state', None))
    gunco = weapon.get('__coProfile__') or co_profile(weapon, fire_mode)
    spool = event_profile.get('spool')
    if spool:
        damage = mode['damage']
        mode = {**mode, 'multishot': spool['maximum'],
                'ammoCost': math.ceil(spool['maximum'] / spool['ammoDivisor']),
                'damage': {**damage, 'types': {k: v * event_profile['playerDamageMultiplier']
                                               for k, v in damage['types'].items()}}}
        if mode.get('falloffMinDamage') is not None:
            mode['falloffMinDamage'] *= event_profile['playerDamageMultiplier']
    base = (mode.get("damage") or {}).get("types")
    if base and mode.get('chargeDamageMultiplier'):
        base = {k: v * mode['chargeDamageMultiplier'] for k, v in base.items()}
    if not base:
        raise Unsupported("no damage data")

    slot = weapon.get("slot")
    melee = slot in MELEE_SLOTS
    weapon_types = {str(path).rstrip("/") for path in (*tuple(weapon.get("ancestry") or ()), weapon.get("path")) if path}
    label = weapon.get('path') or weapon.get('name') or '?'

    def classify(effect):
        """(status, skip message, unsupported upgrade type): 0 applies,
        1 unsupported, 2 another weapon's branch (silent), 3 rejected."""
        if not effect.supported or (effect.upgrade_type not in SUPPORTED_WEAPON_UPGRADE_TYPES
                                    and effect.upgrade_type not in RUNTIME_UPGRADE_TYPES):
            code = DEFERRED_WEAPON_REASON_CODES.get(effect.upgrade_type, "no-handler")
            source = effect.source_path or effect.upgrade_type
            return 1, f"{source}: unsupported[{code}]", effect.upgrade_type
        if (effect.valid_type and effect.valid_type.rstrip("/") not in weapon_types
                and not archgun_arcane_type_applies(weapon, effect.source_path, effect.valid_type)):
            return 2, None, None
        reason = _qualifier_rejection(effect, weapon, scenario)
        if reason:
            return 3, reason, None
        return 0, None, None

    # Primary compression reads the perfect-released profile; everything
    # after the reference's second base_profile() call reads the plain one.
    compression_profile = weapon.get('__compressionProfile__') or event_profile.get('compression')
    compression = None
    if compression_profile:
        reads = compression_profile.get('reads_radius_m')
        compression = (float(compression_profile['radius']), bool(compression_profile.get('takesRadiusMods', True)),
                       None if reads is None else float(reads), float(compression_profile.get('effectiveness', 1.)),
                       compression_profile.get('stacking') == 'adds')

    innate_entries, innate_candidates = _read_innate_elements(weapon)
    notes: list[tuple[str, str]] = []  # (unsupported code, skipped line) in the reference's order
    if innate_candidates and not innate_entries:
        notes.append(("innate-element-instance-required", f"{label}: unsupported[innate-element-instance-required]"))
    damage = mode["damage"]
    plain_profile = base_profile(weapon, fire_mode)
    has_replay_profile = bool(plain_profile.get('radial') or plain_profile.get('radials')
                              or plain_profile.get('lingering') or plain_profile.get('pureRadial'))
    if damage.get("components") and not has_replay_profile:
        notes.append(("projectile-component-damage-unapplied",
                      f"{label}: unsupported[projectile-component-damage-unapplied]"))
    part = _KNOWN_MULTIPART_PATHS.get(str(weapon.get("path") or ""))
    if part:
        notes.append((f"weapon-radial-or-field-damage-not-in-export-{part}",
                      f"{label}: unsupported[radial-or-field-damage-not-in-export:{part}]"))

    innate_multishot = float(mode.get("multishot") or 1)
    exported_proc = float(damage.get("procChance", 0.0) or 0.0)
    if exported_proc == 0.0 and damage.get('source') == 'EmbedDeathAttack':
        exported_proc = plain_profile.get('statusChanceFallback', exported_proc)
    per_pellet_proc = exported_proc / innate_multishot if innate_multishot > 1.0 and exported_proc > 0.0 else exported_proc

    incarnon_form = bool(weapon.get('isIncarnonForm'))
    incarnon = reference()['incarnon'].get(weapon.get('path')) if weapon.get('isIncarnonForm') else None
    base_magazine = float(weapon.get('magazineSize') or plain_profile.get('magazine')
                          or (NATIVE_DEFAULT_CLIP if slot in ('primary', 'secondary') else 0))
    reload_every_shot = (not incarnon_form
                         and reloads_after_every_shot(weapon, weapon.get('__selectedFireMode__', fire_mode)))
    shell = None
    if plain_profile.get('reloadPerShell') is not None:
        shell = (plain_profile['reloadStart'], plain_profile['reloadPerShell'], plain_profile['reloadEnd'])
    battery = plain_profile.get('battery')
    charge = plain_profile.get('charge') or {}
    scales = charge.get('scalesWithFireRate', slot != 'arch_gun')
    continuous = (mode.get('trigger') == '/Lotus/Language/Menu/Loadout_TriggerContinous'
                  or is_furis_beam(weapon, mode, fire_mode))
    copy = (mode.get('multishotCopy') or {}).get('radial' if mode.get('__radialPart__') else 'direct')
    falloff = None
    ranges, minimum = mode.get("falloffRange"), mode.get("falloffMinDamage")
    if scenario.distance is not None and isinstance(ranges, (list, tuple)) and len(ranges) >= 2:
        try:
            falloff = (_require_nonnegative_finite("falloff start", ranges[0]),
                       _require_nonnegative_finite("falloff end", ranges[1]),
                       _require_nonnegative_finite("falloffMinDamage", minimum))
        except (TypeError, ValueError):
            falloff = None
    state = scenario.combat_state
    forced = {dtype: float((damage.get('forcedProcs') or []).count(proc))
              for proc, dtype in [('PT_KNOCKBACK', 'DT_IMPACT'), ('PT_FRAILTY', 'DT_PUNCTURE'), ('PT_BLEEDING', 'DT_SLASH'),
                                  ('PT_IMMOLATION', 'DT_FIRE'), ('PT_CHILLED', 'DT_FREEZE'), ('PT_ELECTROCUTION', 'DT_ELECTRICITY'),
                                  ('PT_POISONED', 'DT_POISON'), ('PT_FLASHBANG', 'DT_EXPLOSION'), ('PT_RAD_TOX', 'DT_RADIATION'),
                                  ('PT_ASPHYXIATION', 'DT_GAS'), ('PT_MAGNETIZED', 'DT_MAGNETIC'), ('PT_INFECTED', 'DT_VIRAL'),
                                  ('PT_CAUSTIC_BURN', 'DT_CORROSIVE')]
              if proc in (damage.get('forcedProcs') or ())}
    config = dict(
        classify=classify,
        melee=melee,
        base=list(base.items()),
        compression=compression,
        aiming=bool(scenario.aiming),
        guncoPresent=bool(gunco),
        guncoBaseFraction=gunco.get('baseFraction') if gunco else None,
        guncoExclude=list(gunco.get('excludeFlatSources') or ()) if gunco else [],
        guncoIndependent=gunco.get('behavior') == 'independent',
        coBaseFraction=gunco.get('baseFraction', 1.),
        innate=list(innate_entries),
        notes=notes,
        speedFalloff=bool(mode.get('falloffRange')),
        falloff=falloff,
        distance=scenario.distance,
        innateMultishot=innate_multishot,
        nativeIgnoreFireIterations=bool(mode.get("nativeIgnoreFireIterations")),
        perPelletProc=per_pellet_proc,
        incarnonForm=incarnon_form,
        incarnonPool=float(incarnon['pool']) if incarnon and incarnon.get('pool') else None,
        incarnonCycleSeconds=(float(incarnon['enterSeconds']) + float(incarnon['exitSeconds'])
                              if incarnon and incarnon.get('pool') and scenario.incarnon_cycle else None),
        incarnonCycle=bool(scenario.incarnon_cycle),
        baseMagazine=base_magazine,
        reloadEveryShot=reload_every_shot,
        reloadBase=mode.get('reloadTime') or 0.0,
        shell=shell,
        battery=((battery['delayEmptySeconds'], battery['regenPerSecond'], battery.get('emptyAnimationSeconds'),
                  battery['delayPartialSeconds']) if battery else None),
        critChance=damage['critChance'] if 'critChance' in damage else None,
        critMultiplier=damage.get('critMultiplier', 1.),
        fireRate=mode.get('fireRate') or 0.,
        chargeScales=bool(scales),
        chargeSeconds=charge.get('seconds', 0.),
        bowDraw=plain_profile.get('drawSeconds', 0.) if plain_profile.get('bow') else None,
        continuous=continuous,
        copy=None if not copy else (float(copy.get('scale', 1.)),
                                    copy['critChance'] if 'critChance' in copy else None,
                                    copy['critMultiplier'] if 'critMultiplier' in copy else None,
                                    float(copy['procChance']) if copy.get('procChance') is not None else None),
        superCrit=super_crit_on_status(weapon),
        superStatus=super_status_on_crit(weapon),
        orbPasses=state.get('orbPasses', 0),
        orbStacks=state.get('orbStacks', 1),
        orbSpecial=bool(state.get('orbSpecialShield', False)),
        radialOnly=damage.get('source') in ('ExplosiveAttack', 'RadialDamage', 'EmbedDeathAttack', 'StackingAttack'),
        forced=list(forced.items()),
        ammoCost=float(mode.get("ammoCost") or 1),
    )
    prep = Prep()
    prep.weapon = weapon
    prep.pinned = pin(weapon)
    prep.zoom = list(zoom_effects(weapon, fire_mode, scenario))
    prep.candidates = tuple(innate_candidates)
    prep.base_obj = base
    prep.base_total_obj = sum(base.values())
    config["zoom"] = prep.zoom
    from .damage import ModEffect
    config["effectClass"] = ModEffect
    prep.core = wfcore.ModsPrep(config)
    return prep


def apply(weapon, effects, fire_mode, scenario, *, need_spec=True):
    """(ModdedStats, CoSpec) like the reference, or Unsupported."""
    from .damage import CoSpec, ModdedStats, ModEffectList, innate_terms_for, with_innate

    if innate_terms_for(weapon, fire_mode):
        effects = with_innate(weapon, ModEffectList(list(effects), skipped=getattr(effects, "skipped", ())), fire_mode)
    heavy = weapon.get("heavyAttack")
    if scenario.heavy_attack and isinstance(heavy, Mapping) and isinstance(heavy.get("components"), list) \
            and heavy.get("components"):
        raise Unsupported("heavy components")
    skipped = list(getattr(effects, "skipped", ()))
    if SHADOW and not isinstance(effects, list):
        from .damage import ModEffectList
        effects = ModEffectList(list(effects), skipped=skipped)
    prep = prep_for(weapon, fire_mode, scenario)
    fields, spec_parts = wfcore.apply_mods(prep.core, effects, skipped, scenario.victim_status_count, need_spec)
    fields["innate_element_candidates"] = prep.candidates
    from .event_profiles import ignores_headshot_bonus
    ignored = ignores_headshot_bonus(weapon, fire_mode)
    fields = {name:value for key,value in fields.items() for name,value in
              ([(key,value),('radial_victim_crit',False),('ignore_headshot_bonus',ignored)] if key=='radial_only' else [(key,value)])}
    fields.setdefault("delayed_radial_hit_event", False)
    stats = ModdedStats.__new__(ModdedStats)
    stats.__dict__.update(fields)
    if not need_spec:
        if SHADOW:
            shadow((stats, None), weapon, effects, fire_mode, scenario)
        return stats, None
    spec = CoSpec()
    (spec.victim_status_count, spec.damage_scale_effects, spec.ordinary_scale, spec.compression_mult,
     spec.gunco_independent, spec.gunco_fraction, spec.victim_damage, spec.co_fraction, spec.melee,
     spec.melee_damage_effects, spec.slam_effects, base, spec.base_total, spec.elemental_base_total,
     spec.pre, spec.post, spec.innate_entries, spec.pool_factor, spec.copy_factor, spec.orb, spec.final,
     spec.frozen_factor) = spec_parts
    if base is None:
        spec.base = prep.base_obj
        spec.base_total = prep.base_total_obj
    else:
        spec.base = base
    if SHADOW:
        shadow((stats, spec), weapon, effects, fire_mode, scenario)
    return stats, spec


def differences(reference, candidate, limit: int = 3) -> list:
    """Where two apply_mods_spec results differ: exact float bits, number
    types, dict key order and attribute order all count."""
    from dataclasses import fields

    out: list = []

    def same(a, b, path):
        if len(out) >= limit:
            return
        if type(a) is not type(b) and not (isinstance(a, list) and isinstance(b, list)):
            out.append((path, "type", type(a).__name__, type(b).__name__))
        elif isinstance(a, float):
            if a.hex() != b.hex() and not (a != a and b != b):
                out.append((path, a, b))
        elif isinstance(a, Mapping):
            if list(a) != list(b):
                out.append((path, "keys", list(a), list(b)))
            else:
                for k in a:
                    same(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, (list, tuple)):
            if len(a) != len(b):
                out.append((path, "length", len(a), len(b)))
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    same(x, y, f"{path}[{i}]")
        elif hasattr(a, "__dataclass_fields__") and not isinstance(a, type):
            if hasattr(a, "__dict__") and list(vars(a)) != list(vars(b)):
                out.append((path, "attribute order"))
                return
            for f in fields(a):
                same(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}")
        elif a != b:
            out.append((path, a, b))

    same(reference[0], candidate[0], "stats")
    spec_a, spec_b = reference[1], candidate[1]
    if (spec_a is None) != (spec_b is None):
        out.append(("spec", spec_a, spec_b))
    elif spec_a is not None:
        for slot in type(spec_a).__slots__:
            if slot != "native":
                same(getattr(spec_a, slot, None), getattr(spec_b, slot, None), "spec." + slot)
    return out


def shadow(result, weapon, effects, fire_mode, scenario):
    """Raise when the native result differs from the Python reference."""
    from .damage import ModEffectList, _apply_mods_spec_py

    reference = _apply_mods_spec_py(weapon, ModEffectList(effects, skipped=getattr(effects, "skipped", ())),
                                    fire_mode=fire_mode, scenario=scenario)
    if result[1] is None:
        reference = (reference[0], None)
    diff = differences(reference, result)
    if diff:
        raise AssertionError(f"native apply_mods differs for {weapon.get('path')}: {diff}")
