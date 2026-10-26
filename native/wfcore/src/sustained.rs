//! `damage.sustained_status_damage`'s `totalDps` / `directDps`: the panel
//! proxy the optimizer's element-seed searches rank builds with
//! (`statusSustainedDps` / `targetSustainedDps`).
//!
//! The target side that does not depend on the build (scaled armour before
//! strips, shield, Overguard, faction deltas, bypass sets, hit locations) is
//! prepared once per target context in Python (`status_native`); the armour
//! itself depends on the build's own Corrosive / Heat stacks, so the
//! per-type target multipliers are computed here for each call. The DoT and
//! Blast rows reuse `tables::status`, the reference's `expected_dot_damage`
//! arithmetic; every operation follows the Python order.
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::pymath::{pmax, pmin, psum, sqrt};
use crate::replay::{core_of, opt_attr, vector_of, Types};
use crate::tables::{self, Core, Location, TargetTables, Vector};

type D = u32;

/// One target context (target record, level, strip, Steel Path, enhancements,
/// hit location) as `damage.sustained_status_damage` reads it.
#[pyclass(frozen)]
pub struct SustainedTarget {
    armour_base: f64,
    armour_strip: f64,
    aura_armour_reduction: f64,
    elemental_armour_strip: f64,
    overguard: f64,
    shield: f64,
    magnetic_stacks: i64,
    shielded: bool,
    faction_deltas: Vec<(String, f64)>,
    armour_bypass: Vec<String>,
    shield_bypass: Vec<String>,
    target_faction: String,
    faction_bracket: f64,
    body: (f64, f64, bool),
    located: (f64, f64, bool),
    existing_magnetic: i64,
}

#[pymethods]
impl SustainedTarget {
    #[new]
    fn new(config: &Bound<'_, PyDict>) -> PyResult<Self> {
        let get = |k: &str| -> PyResult<Bound<'_, PyAny>> {
            config.get_item(k)?.ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.to_string()))
        };
        Ok(SustainedTarget {
            armour_base: get("armourBase")?.extract()?,
            armour_strip: get("armourStrip")?.extract()?,
            aura_armour_reduction: get("auraArmourReduction")?.extract()?,
            elemental_armour_strip: get("elementalArmourStrip")?.extract()?,
            overguard: get("overguard")?.extract()?,
            shield: get("shield")?.extract()?,
            magnetic_stacks: get("magneticStacks")?.extract()?,
            shielded: get("shielded")?.extract()?,
            faction_deltas: get("factionDeltas")?.extract()?,
            armour_bypass: get("armourBypass")?.extract()?,
            shield_bypass: get("shieldBypass")?.extract()?,
            target_faction: get("targetFaction")?.extract()?,
            faction_bracket: match config.get_item("factionBracket")? { Some(v) => v.extract()?, None => 1.0 },
            body: get("body")?.extract()?,
            located: get("located")?.extract()?,
            existing_magnetic: get("existingMagnetic")?.extract()?,
        })
    }
}

/// `_magnetic_defense_multiplier`
fn magnetic_defense(stacks: i64) -> f64 {
    if stacks != 0 {
        pmin(2.0 + 0.25 * (stacks - 1) as f64, 4.25)
    } else {
        1.0
    }
}

/// `_armour_reduction`
fn armour_reduction(armour: f64) -> f64 {
    if armour <= 0.0 {
        return 0.0;
    }
    let effective = pmin(armour, 2700.0);
    0.9 * sqrt(effective / 2700.0)
}

struct Context<'a> {
    target: &'a SustainedTarget,
    types: &'a Types,
}

impl Context<'_> {
    fn in_set(set: &[String], name: &str) -> bool {
        set.iter().any(|x| x == name)
    }

    /// `enemy_defenses(...)["armour"]` at this elemental strip.
    fn armour(&self, elemental_strip: f64) -> f64 {
        let mut armour = self.target.armour_base;
        armour *= 1.0 - self.target.armour_strip;
        armour *= 1.0 - elemental_strip;
        armour *= 1.0 - self.target.aura_armour_reduction;
        armour
    }

    /// The per-type factor `damage_against` / `expected_dot_damage` apply:
    /// Overguard's, else `_target_damage_multiplier` with the shield's
    /// Magnetic factor.
    fn multiplier(&self, d: D, armour: f64) -> f64 {
        let name = self.types.name(d);
        let t = self.target;
        if t.overguard > 0.0 {
            let radiant = if name == "DT_RADIANT" || name == "DT_VOID" { 1.5 } else { 1.0 };
            return radiant * magnetic_defense(t.magnetic_stacks);
        }
        let delta = t.faction_deltas.iter().find(|x| x.0 == name).map(|x| x.1).unwrap_or(0.0);
        let mut value = pmax(0.0, 1.0 + delta);
        let hits_health = !t.shielded || Self::in_set(&t.shield_bypass, name);
        if hits_health && armour != 0.0 && !Self::in_set(&t.armour_bypass, name) {
            value *= 1.0 - armour_reduction(armour);
        }
        if t.shield > 0.0 && !Self::in_set(&t.shield_bypass, name) {
            value *= magnetic_defense(t.magnetic_stacks);
        }
        value
    }

    fn location(&self, s: &Core) -> (f64, f64, bool) {
        if s.radial_only { self.target.body } else { self.target.located }
    }

    /// `damage_against(stats, target, ...)`: (perType, perShot).
    fn damage_against(&self, s: &Core, armour: f64) -> (Vector, f64) {
        let (hm, hcm, _head) = self.location(s);
        let hcm = if s.ignore_headshot_bonus { 1.0 } else { hcm };
        let applied_hm = if s.ignore_headshot_bonus { 1.0 } else { hm };
        let base = match s.dot_base_damage {
            Some(v) => v,
            None => s.total_damage(),
        };
        let quantized = tables::quantize(&s.damage_types, base);
        let mut per_type: Vector = quantized
            .iter()
            .map(|&(d, amount)| {
                let mut value = self.multiplier(d, armour);
                value *= amount;
                (d, value * s.falloff_multiplier)
            })
            .collect();
        let mut faction = s.faction_all;
        if !self.target.target_faction.is_empty() {
            faction *= s.faction_target;
        }
        faction *= self.target.faction_bracket;
        if faction != 1.0 {
            for e in per_type.iter_mut() {
                e.1 *= faction;
            }
        }
        if applied_hm != 1.0 {
            for e in per_type.iter_mut() {
                e.1 *= applied_hm;
            }
        }
        let mut raw = psum(per_type.iter().map(|e| e.1))
            * tables::effective_hit_multiplier(s.crit_chance, s.crit_multiplier, s.noncrit_damage_multiplier, hcm,
                                               s.double_crit_chance);
        raw = tables::apply_weakpoint_folding(raw, s, hm, hcm);
        (per_type, raw * s.multishot)
    }

    /// `expected_status_damage`'s DoT and Blast rows at this armour.
    fn status(&self, s: &Core, armour: f64, types: &[D; 6]) -> tables::Status {
        let (bhm, bhcm, bhead) = self.target.body;
        let (lhm, lhcm, lhead) = self.target.located;
        let tables = TargetTables {
            target_faction: !self.target.target_faction.is_empty(),
            damage: [Location { hit_multiplier: bhm, hit_critical_multiplier: bhcm, head: bhead },
                     Location { hit_multiplier: lhm, hit_critical_multiplier: lhcm, head: lhead }],
            dot: [Location { hit_multiplier: bhm, hit_critical_multiplier: bhcm, head: bhead },
                  Location { hit_multiplier: lhm, hit_critical_multiplier: lhcm, head: lhead }],
            dot_multiplier: types.iter().map(|&d| (d, self.multiplier(d, armour))).collect(),
            forced_procs: Vec::new(),
        };
        tables::status(s, 1, &tables)
    }
}

/// `vulnerability(count)` of `sustained_status_damage`.
fn vulnerability(count: f64) -> f64 {
    if count <= 0.0 {
        return 1.0;
    }
    if count < 1.0 {
        return 1.0 + count;
    }
    pmin(2.0 + 0.25 * (count - 1.0), 4.25)
}

/// `sustained_status_damage(stats, target, ...)["totalDps"]` (``total``) or
/// `["directDps"]`.
#[pyfunction]
#[pyo3(signature = (target, stats, attacks_per_second, status_rate_multiplier, damage_rate_multiplier, total))]
pub fn sustained_status(
    target: &Bound<'_, SustainedTarget>,
    stats: &Bound<'_, PyAny>,
    attacks_per_second: f64,
    status_rate_multiplier: f64,
    damage_rate_multiplier: f64,
    total: bool,
) -> PyResult<f64> {
    let target = target.get();
    let mut types = Types::new();
    let damage_types = vector_of(&mut types, &stats.getattr("damage_types")?)?;
    let forced = vector_of(&mut types, &stats.getattr("native_forced_procs")?)?;
    let independent = vector_of(&mut types, &stats.getattr("independent_proc_chances")?)?;
    let core = core_of(stats, &mut types, &target.target_faction, target.faction_bracket, &damage_types, &forced, &independent)?;
    let id = |types: &mut Types, n: &str| types.id(n);
    let (viral, corrosive, magnetic, cold, puncture, heat) = (
        id(&mut types, "DT_VIRAL"), id(&mut types, "DT_CORROSIVE"), id(&mut types, "DT_MAGNETIC"),
        id(&mut types, "DT_FREEZE"), id(&mut types, "DT_PUNCTURE"), id(&mut types, "DT_FIRE"),
    );
    let interactions = [
        id(&mut types, "DT_CINEMATIC"), id(&mut types, "DT_FIRE"), id(&mut types, "DT_POISON"),
        id(&mut types, "DT_ELECTRICITY"), id(&mut types, "DT_GAS"), id(&mut types, "DT_EXPLOSION"),
    ];
    let (slash, cinematic, gas) = (id(&mut types, "DT_SLASH"), id(&mut types, "DT_CINEMATIC"), id(&mut types, "DT_GAS"));
    let ctx = Context { target, types: &types };

    let rate = pmax(attacks_per_second, 0.0);
    let proc_rate = rate * pmax(status_rate_multiplier, 0.0);
    let mut damage_rate = rate * pmax(damage_rate_multiplier, 0.0);
    let magazine = pmax(opt_float(stats, "magazine")?, 0.0);
    let first_shot_bonus = pmax(opt_float(stats, "first_shot_damage_bonus")?, 0.0);
    if magazine > 0.0 && first_shot_bonus > 0.0 && damage_rate > 0.0 {
        damage_rate *= 1.0 + first_shot_bonus / magazine;
    }
    // The probe's expected procs (`expected_status_procs` at its location).
    let (_, _, head) = ctx.location(&core);
    let procs = tables::expected_status_procs(&core, &Vec::new(), head);
    let proc_of = |d: D| tables::get(&procs, d).unwrap_or(0.0);
    let stacks = |d: D, duration: f64, cap: f64| pmin(pmax(proc_of(d) * proc_rate * duration * core.duration_scale(d), 0.0), cap);
    let viral_count = stacks(viral, 6.0, 10.0);
    let corrosive_count = stacks(corrosive, 8.0, 10.0);
    let magnetic_count = stacks(magnetic, 6.0, 10.0);
    let cold_count = stacks(cold, 6.0, 10.0);
    let puncture_count = stacks(puncture, 10.0, core.stack_cap(puncture, 5.0));
    let heat_count = stacks(heat, 6.0, 1.0);

    let corrosive_strip = if corrosive_count < 1.0 {
        0.26 * corrosive_count
    } else {
        pmin(0.26 + 0.06 * (corrosive_count - 1.0), 0.8)
    };
    let heat_strip = 0.5 * heat_count;
    let elemental = target.elemental_armour_strip;
    let combined_strip = 1.0 - ((1.0 - elemental) * (1.0 - corrosive_strip) * (1.0 - heat_strip));
    let cold_proc_rate = proc_of(cold) * proc_rate;
    let cold_crit = if cold_count >= 10.0 && cold_proc_rate > 0.0 {
        let freeze_duration = 3.0 * core.duration_scale(cold);
        let rebuild_duration = 7.0 / cold_proc_rate;
        let uptime = if freeze_duration > 0.0 { freeze_duration / (freeze_duration + rebuild_duration) } else { 0.0 };
        0.35 * (1.0 - uptime) + uptime
    } else if cold_count < 1.0 {
        0.1 * cold_count
    } else {
        pmin(0.1 + 0.05 * (cold_count - 1.0), 0.5)
    };
    let puncture_crit = pmin(0.05 * puncture_count, 0.05 * core.stack_cap(puncture, 5.0));
    let mut adjusted = core.clone();
    adjusted.crit_chance = pmax(core.crit_chance + puncture_crit, 0.0);
    adjusted.crit_multiplier = pmax(core.crit_multiplier + cold_crit, 1.0);

    let combined_armour = ctx.armour(combined_strip);
    let (per_type, per_shot) = ctx.damage_against(&adjusted, combined_armour);
    let viral_multiplier = vulnerability(viral_count);
    let combined_magnetic = pmin(target.existing_magnetic as f64 + magnetic_count, 10.0);
    let magnetic_multiplier = vulnerability(combined_magnetic) / vulnerability(target.existing_magnetic as f64);
    let pool_multiplier = |d: D| -> f64 {
        if target.overguard > 0.0 {
            return magnetic_multiplier;
        }
        if target.shield > 0.0 && !Context::in_set(&target.shield_bypass, types.name(d)) {
            return magnetic_multiplier;
        }
        viral_multiplier
    };
    let direct_total = psum(per_type.iter().map(|e| e.1));
    let weighted_direct = psum(per_type.iter().map(|&(d, v)| v * pool_multiplier(d)));
    let direct_dps = per_shot * (if direct_total > 0.0 { weighted_direct / direct_total } else { 1.0 }) * damage_rate;
    if !total {
        return Ok(direct_dps);
    }
    // totalDps adds only independent DoT / proc damage to directDps (the
    // reference's status-amplified direct bonus is part of directDps already).
    let status = ctx.status(&adjusted, combined_armour, &interactions);
    let mut dot = Vec::new();
    for (d, row) in status.rows.iter() {
        let expected_procs = pmax(tables::get(&status.procs, *d).unwrap_or(0.0), 0.0);
        let interaction = if *d == slash { cinematic } else { *d };
        let damage_multiplier = pool_multiplier(interaction);
        let per_second = row.seed + row.accumulator;
        let value = if *d == gas {
            let active = pmin(expected_procs * proc_rate * row.duration, 10.0);
            let average_hit = if status_rate_multiplier != 0.0 {
                pmax(damage_rate_multiplier, 0.0) / pmax(status_rate_multiplier, 0.0)
            } else {
                0.0
            };
            per_second * active * average_hit
        } else {
            let count = tables::get(&status.procs, *d).unwrap_or(0.0);
            per_second * row.duration * count * damage_rate
        };
        dot.push(value * damage_multiplier);
    }
    let dot_dps = psum(dot);
    let blast = tables::get(&status.procs, interactions[5]).unwrap_or(0.0);
    let non_dot: Vec<f64> = status
        .non
        .iter()
        .map(|&(d, per_proc)| per_proc * blast * damage_rate * pool_multiplier(d))
        .collect();
    let proc_non_dot_dps = psum(non_dot);
    Ok(direct_dps + dot_dps + proc_non_dot_dps)
}

/// `max(float(getattr(stats, name, 0.0) or 0.0), 0.0)`'s inner value.
fn opt_float(stats: &Bound<'_, PyAny>, name: &str) -> PyResult<f64> {
    Ok(match opt_attr(stats, name)? {
        Some(v) if v.is_truthy()? => v.extract::<f64>()?,
        _ => 0.0,
    })
}
