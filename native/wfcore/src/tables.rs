//! The replay's per-hit damage tables (`attack_data`): the direct damage
//! vector from `damage_against_cached_armour` against the bare defence
//! snapshot, and the DoT / Blast rows of `expected_status_damage` against the
//! replay's unit DoT target. Target-side factors are constants of one replay
//! and come precomputed from Python (`TargetTables`); everything here is the
//! reference's arithmetic over the stats, in the same order.

use crate::pymath::{pmax, pmin, pow, psum, trunc_i, PySum};

pub type D = u32;
pub type Vector = Vec<(D, f64)>;

/// The stats fields the tables read (a crit view is a modified clone).
#[derive(Clone)]
pub struct Core {
    pub damage_types: Vector,
    pub dot_base_damage: Option<f64>,
    pub crit_chance: f64,
    pub crit_multiplier: f64,
    pub noncrit_damage_multiplier: f64,
    pub double_crit_chance: f64,
    pub falloff_multiplier: f64,
    pub faction_all: f64,
    pub faction_target: f64,
    /// Demolishers' 0.8 inside the faction bracket (WFSim M89); 1.0 elsewhere.
    pub faction_bracket: f64,
    pub multishot: f64,
    pub continuous: bool,
    pub radial_only: bool,
    pub ignore_headshot_bonus: bool,
    pub bodyshot_crit_multiplier: f64,
    pub weakpoint_crit_chance_bonus: f64,
    pub base_crit_chance: f64,
    pub weakpoint_crit_chance_relative: f64,
    pub headshot_bonus_multiplier: f64,
    pub weakpoint_damage_bonus: f64,
    pub status_chance: f64,
    pub proc_duration_multiplier: f64,
    /// damage.ModdedStats.proc_duration_types: one type's own duration multiplier.
    pub proc_duration_types: Vector,
    /// damage.ModdedStats.proc_max_stacks: extra victim stacks of one type.
    pub proc_max_stacks: Vector,
    pub proc_damage_multiplier: f64,
    pub native_forced_procs: Vector,
    pub independent_proc_chances: Vector,
    pub crit_proc_chances: Vector,
    pub impact_proc_conversions: Vec<(D, Vec<(f64, f64, f64)>)>,
    pub fire_rate: f64,
    pub dot_elemental_multipliers: Vector,
    pub extra_hits: Vec<(D, f64, bool)>,
    pub low_crit_threshold: Option<f64>,
    pub low_crit_damage_base: Option<f64>,
    pub low_crit_damage_bonus: f64,
}

#[derive(Clone, Copy)]
pub struct Location {
    pub hit_multiplier: f64,
    pub hit_critical_multiplier: f64,
    pub head: bool,
}

#[derive(Clone)]
pub struct TargetTables {
    pub target_faction: bool,
    /// Damage target locations (body, head).
    pub damage: [Location; 2],
    /// Unit DoT target locations (body, head).
    pub dot: [Location; 2],
    /// Unit DoT target multiplier per interaction type.
    pub dot_multiplier: Vec<(D, f64)>,
    pub forced_procs: Vector,
}

pub const IMPACT: D = 13;
pub const SLASH: D = 9;
pub const PUNCTURE: D = 7;
pub const FIRE: D = 0;
pub const POISON: D = 14;
pub const ELECTRICITY: D = 8;
pub const GAS: D = 2;
pub const EXPLOSION: D = 3;
pub const CINEMATIC: D = 10;

const DOT_COEFFICIENTS: [(D, f64); 5] = [(SLASH, 0.35), (FIRE, 0.5), (POISON, 0.5), (ELECTRICITY, 0.5), (GAS, 0.5)];

pub(crate) fn get(v: &Vector, d: D) -> Option<f64> {
    v.iter().find(|x| x.0 == d).map(|x| x.1)
}

fn add(v: &mut Vector, d: D, x: f64) {
    if let Some(slot) = v.iter_mut().find(|e| e.0 == d) {
        slot.1 += x;
    } else {
        v.push((d, 0.0 + x));
    }
}

impl Core {
    /// `damage.proc_stack_cap`: the victim's stack cap of `d` with the weapon's extra stacks.
    pub fn stack_cap(&self, d: D, cap: f64) -> f64 {
        match get(&self.proc_max_stacks, d) {
            Some(v) => cap + v,
            None => cap,
        }
    }

    /// `damage.proc_duration_scale`: status duration multiplier of `d`.
    pub fn duration_scale(&self, d: D) -> f64 {
        match get(&self.proc_duration_types, d) {
            Some(v) => pmax(v, 0.0),
            None => pmax(self.proc_duration_multiplier, 0.0),
        }
    }

    pub fn total_damage(&self) -> f64 {
        psum(self.damage_types.iter().map(|x| x.1))
    }
    fn faction_mod(&self, tables: &TargetTables) -> f64 {
        let mut m = self.faction_all;
        if tables.target_faction {
            m *= self.faction_target;
        }
        m *= self.faction_bracket;
        m
    }
}

pub fn effective_crit_multiplier(chance: f64, multiplier: f64) -> f64 {
    if multiplier <= 1.0 || chance <= 0.0 {
        return 1.0;
    }
    let guaranteed = trunc_i(chance) as f64;
    let remainder = chance - guaranteed;
    let low = 1.0 + guaranteed * (multiplier - 1.0);
    let high = 1.0 + (guaranteed + 1.0) * (multiplier - 1.0);
    low * (1.0 - remainder) + high * remainder
}

pub fn effective_hit_multiplier(cc: f64, cm: f64, noncrit: f64, factor: f64, double: f64) -> f64 {
    let crit = effective_crit_multiplier(cc, cm * factor);
    let promotion = pmin(pmax(cc, 0.0), 1.0) * pmin(double, 1.0) * pmax(cm * factor - 1.0, 0.0);
    let noncrit_chance = pmin(1.0, pmax(1.0 - cc, 0.0));
    let noncrit_bonus = pmax(noncrit - 1.0, 0.0);
    crit + promotion + noncrit_chance * noncrit_bonus
}

pub fn crit_tier_seed_distribution(cc: f64, cm: f64, noncrit: f64, factor: f64, double: f64, critical_only: bool) -> Vec<(f64, f64)> {
    let chance = pmax(cc, 0.0);
    let whole = trunc_i(chance);
    let fraction = chance - whole as f64;
    let promotion = pmin(1.0, pmax(0.0, double));
    let mut tiers: Vec<(i64, f64)> = vec![(whole, 1.0 - fraction)];
    if fraction != 0.0 {
        tiers.push((whole + 1, fraction));
    }
    let mut promoted: Vec<(i64, f64)> = Vec::new();
    let bump = |m: &mut Vec<(i64, f64)>, tier: i64, x: f64| {
        if let Some(slot) = m.iter_mut().find(|e| e.0 == tier) {
            slot.1 += x;
        } else {
            m.push((tier, 0.0 + x));
        }
    };
    for (tier, weight) in tiers {
        let rate = if tier > 0 { promotion } else { 0.0 };
        bump(&mut promoted, tier, weight * (1.0 - rate));
        if rate != 0.0 {
            bump(&mut promoted, tier + 1, weight * rate);
        }
    }
    let cd = pmax(1.0, cm * factor);
    if critical_only {
        promoted.retain(|e| e.0 > 0);
        let total = psum(promoted.iter().map(|e| e.1));
        if total > 0.0 {
            for e in promoted.iter_mut() {
                e.1 /= total;
            }
        } else {
            promoted.clear();
        }
    }
    promoted.sort_by_key(|e| e.0);
    promoted
        .into_iter()
        .filter(|e| e.1 > 0.0)
        .map(|(tier, w)| (w, if tier == 0 { pmax(1.0, noncrit) } else { 1.0 + tier as f64 * (cd - 1.0) }))
        .collect()
}

fn weakpoint_noncrit_scale(s: &Core, hm: f64) -> f64 {
    if s.radial_only || hm <= 1.0 + 1e-9 {
        return 1.0;
    }
    let mut scale = s.headshot_bonus_multiplier;
    if !s.ignore_headshot_bonus && s.weakpoint_damage_bonus > 0.0 {
        scale *= (hm + 1.5 * s.weakpoint_damage_bonus) / hm;
    }
    scale
}

pub(crate) fn apply_weakpoint_folding(raw: f64, s: &Core, hm: f64, hcm: f64) -> f64 {
    let mut raw = raw;
    if s.radial_only {
        return raw;
    }
    let share = if hm > 1.0 + 1e-9 { 1.0 } else { 0.0 };
    if share <= 0.0 {
        if s.bodyshot_crit_multiplier != 1.0 {
            let cc = pmax(s.crit_chance, 0.0);
            let cd = pmax(s.crit_multiplier, 1.0);
            let original = effective_hit_multiplier(cc, cd, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
            let modified = effective_hit_multiplier(cc * s.bodyshot_crit_multiplier, cd, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
            raw *= if original != 0.0 { modified / original } else { 1.0 };
        }
        return raw;
    }
    raw *= weakpoint_noncrit_scale(s, hm);
    let weak = s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative;
    if weak != 0.0 {
        let base = effective_hit_multiplier(s.crit_chance, s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
        let boosted = effective_hit_multiplier(pmax(s.crit_chance + weak, 0.0), s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
        if base > 0.0 {
            raw *= 1.0 + (boosted / base - 1.0);
        }
    }
    raw
}

pub(crate) fn quantize(damage: &Vector, modded_base: f64) -> Vector {
    if modded_base <= 0.0 {
        return damage.clone();
    }
    let unit = modded_base / 32.0;
    damage
        .iter()
        .map(|(d, v)| (*d, if unit > 0.0 { (v / unit).round_ties_even() * unit } else { *v }))
        .collect()
}

/// (perType, perShot) of `damage_against_cached_armour` against the bare snapshot.
fn direct(s: &Core, loc: Location, tables: &TargetTables) -> (Vector, f64) {
    let (mut hm, mut hcm) = (loc.hit_multiplier, loc.hit_critical_multiplier);
    if s.radial_only {
        hm = 1.0;
        hcm = 1.0;
    }
    if s.ignore_headshot_bonus { hcm = 1.0; }
    let applied_hm = if s.ignore_headshot_bonus { 1.0 } else { hm };
    let base = match s.dot_base_damage {
        Some(v) => v,
        None => s.total_damage(),
    };
    let quantized = quantize(&s.damage_types, base);
    let mut per_type: Vector = quantized.iter().map(|(d, a)| (*d, (1.0 * a) * s.falloff_multiplier)).collect();
    let faction = s.faction_mod(tables);
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
        * effective_hit_multiplier(s.crit_chance, s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
    raw = apply_weakpoint_folding(raw, s, hm, hcm);
    (per_type, raw * pmax(s.multishot, 0.0))
}

fn location_crit_chance(s: &Core, head: bool) -> f64 {
    let chance = pmax(s.crit_chance, 0.0);
    if s.radial_only {
        return chance;
    }
    if head {
        let weak = s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative;
        return pmax(chance + weak, 0.0);
    }
    pmax(chance * s.bodyshot_crit_multiplier, 0.0)
}

pub fn crit_proc_probability(s: &Core, d: D, head: bool) -> f64 {
    let chance = pmax(get(&s.crit_proc_chances, d).unwrap_or(0.0), 0.0);
    if chance == 0.0 {
        return 0.0;
    }
    let crit = pmin(location_crit_chance(s, head), 1.0);
    let forced = pmin(pmax(get(&s.native_forced_procs, d).unwrap_or(0.0), 0.0), 1.0);
    pmin(chance, 1.0) * crit * (1.0 - forced)
}

pub fn expected_status_procs(s: &Core, forced: &Vector, head: bool) -> Vector {
    let chance = pmax(s.status_chance, 0.0);
    let mut shots = pmax(s.multishot, 0.0);
    let random_total = chance * shots;
    if s.continuous {
        shots = if shots > 0.0 { 1.0 } else { 0.0 };
    }
    let weights: Vector = s.damage_types.iter().map(|(d, a)| (*d, pmax(*a, 0.0))).collect();
    let total_weight = psum(weights.iter().map(|e| e.1));
    let mut result: Vector = Vec::new();
    if random_total != 0.0 && total_weight != 0.0 {
        for (d, a) in &weights {
            if *a != 0.0 {
                result.push((*d, random_total * a / total_weight));
            }
        }
    }
    for (d, per) in &s.native_forced_procs {
        add(&mut result, *d, shots * per);
    }
    let crit_procs: Vector = s.crit_proc_chances.iter().map(|(d, _)| (*d, crit_proc_probability(s, *d, head))).collect();
    let impact = get(&result, IMPACT).unwrap_or(0.0);
    if impact != 0.0 {
        for (d, adapters) in &s.impact_proc_conversions {
            for &(chance, threshold, multiplier) in adapters {
                let mut conversion = chance;
                if s.fire_rate < threshold {
                    conversion *= multiplier;
                }
                conversion *= 1.0 - get(&crit_procs, *d).unwrap_or(0.0);
                add(&mut result, *d, impact * conversion);
            }
        }
    }
    for (d, pc) in &s.independent_proc_chances {
        add(&mut result, *d, shots * pmax(*pc, 0.0));
    }
    for (d, p) in &crit_procs {
        add(&mut result, *d, shots * p);
    }
    for (d, count) in forced {
        add(&mut result, *d, *count);
    }
    result.retain(|e| e.1 != 0.0);
    result
}

fn seed_merge(s: &Core, d: D, forced: &Vector) -> f64 {
    if !s.continuous || s.multishot <= 0.0 {
        return 1.0;
    }
    let low = s.multishot.floor();
    let fraction = s.multishot - low;
    let mut count = 0.0;
    let mut seed = 0.0;
    for (merged, probability) in [(low, 1.0 - fraction), (low + 1.0, fraction)] {
        if merged <= 0.0 || probability <= 0.0 {
            continue;
        }
        let mut probe = s.clone();
        probe.continuous = false;
        probe.multishot = 1.0;
        probe.status_chance = s.status_chance * merged;
        let n = get(&expected_status_procs(&probe, forced, false), d).unwrap_or(0.0);
        count += probability * n;
        seed += probability * n * merged;
    }
    if count != 0.0 {
        seed / count
    } else {
        1.0
    }
}

#[derive(Clone, Copy)]
pub struct Row {
    pub duration: f64,
    pub seed: f64,
    pub accumulator: f64,
    pub shared: bool,
    pub coefficient: f64,
}

pub struct Status {
    pub procs: Vector,
    pub rows: Vec<(D, Row)>,
    pub non: Vec<(D, f64)>,
}

fn dot_multiplier(tables: &TargetTables, d: D) -> f64 {
    get(&tables.dot_multiplier, d).unwrap_or(1.0)
}

/// `expected_status_damage` against the unit DoT target at one location.
pub(crate) fn status(s: &Core, loc_index: usize, tables: &TargetTables) -> Status {
    let loc = if s.radial_only { tables.dot[0] } else { tables.dot[loc_index] };
    let (hm, hcm) = (loc.hit_multiplier, if s.ignore_headshot_bonus { 1.0 } else { loc.hit_critical_multiplier });
    let applied_hm = if s.ignore_headshot_bonus { 1.0 } else { hm };
    let forced = &tables.forced_procs;
    let procs = expected_status_procs(s, forced, loc.head);
    let dot_base = pmax(match s.dot_base_damage {
        Some(v) => v,
        None => s.total_damage(),
    }, 0.0);
    let seed_tiers = crit_tier_seed_distribution(s.crit_chance, s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance, false);
    let weak_seed_scale = apply_weakpoint_folding(1.0, s, hm, hcm);
    let crit_seed_tiers = if !s.crit_proc_chances.is_empty() {
        crit_tier_seed_distribution(location_crit_chance(s, loc.head), s.crit_multiplier, 1.0, hcm, s.double_crit_chance, true)
    } else {
        Vec::new()
    };
    let crit_seed_scale = weakpoint_noncrit_scale(s, hm);
    let proc_damage = pmax(s.proc_damage_multiplier, 0.0);
    let faction_mod = s.faction_mod(tables);
    let mut rows = Vec::new();
    for (d, coefficient) in DOT_COEFFICIENTS {
        let count = get(&procs, d).unwrap_or(0.0);
        if count == 0.0 {
            continue;
        }
        let interaction = if d == SLASH { CINEMATIC } else { d };
        let target_multiplier = dot_multiplier(tables, interaction);
        let elemental = get(&s.dot_elemental_multipliers, d).unwrap_or(1.0);
        let mut seed_basis = dot_base;
        let mut extra = PySum::new();
        let mut any = false;
        for (kind, share, forced_hit) in &s.extra_hits {
            if *forced_hit && *kind == d {
                extra.add(*share);
                any = true;
            }
        }
        let extra_share = if any { extra.value() } else { 0.0 };
        if extra_share != 0.0 {
            let forced_count = pmin(count, if s.continuous { 1.0 } else { pmax(s.multishot, 0.0) });
            let extra_basis = extra_share * s.total_damage() * pmax(faction_mod, 0.0);
            seed_basis = ((count - forced_count) * dot_base + forced_count * extra_basis) / count;
        }
        let elemental_factor = if d == SLASH || d == IMPACT || d == PUNCTURE { 1.0 } else { pmax(elemental, 0.0) };
        let shared = d == FIRE || d == ELECTRICITY || d == GAS;
        let accumulator = if shared { 1.0 } else { pmin(count, 10.0) };
        let accumulator_multiplier = pmax(elemental, 0.0) * proc_damage;
        let mut unit = coefficient * seed_basis * seed_merge(s, d, forced) * elemental_factor * proc_damage
            * s.falloff_multiplier * applied_hm * target_multiplier * pow(pmax(faction_mod, 0.0), 2.0);
        if (d == ELECTRICITY || d == GAS) && !s.radial_only && hm > 1.0 + 1e-9 {
            // WFSim M100: an Electricity / Gas tick lands on a head with the
            // headshot bonuses once more (Python reference, same order).
            unit *= s.headshot_bonus_multiplier;
        }
        let mut crit_share = 0.0;
        if get(&s.crit_proc_chances, d).is_some() && !crit_seed_tiers.is_empty() {
            let shots = if s.continuous { 1.0 } else { pmax(s.multishot, 0.0) };
            crit_share = pmin(shots * crit_proc_probability(s, d, loc.head) / count, 1.0);
        }
        let mut tiers: Vec<(f64, f64)> = seed_tiers.iter().map(|(w, f)| ((1.0 - crit_share) * w, unit * f * weak_seed_scale)).collect();
        tiers.extend(crit_seed_tiers.iter().map(|(w, f)| (crit_share * w, unit * f * crit_seed_scale)));
        tiers.retain(|e| e.0 > 0.0);
        let seed = psum(tiers.iter().map(|(w, ps)| w * ps));
        let duration = 6.0 * s.duration_scale(d);
        rows.push((d, Row { duration, seed, accumulator: accumulator * accumulator_multiplier, shared, coefficient }));
    }
    let mut non = Vec::new();
    let blast = get(&procs, EXPLOSION).unwrap_or(0.0);
    if blast != 0.0 {
        let target_multiplier = dot_multiplier(tables, EXPLOSION);
        let crit = effective_hit_multiplier(s.crit_chance, s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance);
        let modded_base = pmax(match s.dot_base_damage {
            Some(v) => v,
            None => s.total_damage(),
        }, 0.0);
        let per_proc = 0.3 * seed_merge(s, EXPLOSION, forced) * modded_base * crit * proc_damage * s.falloff_multiplier
            * applied_hm * target_multiplier * pow(pmax(faction_mod, 0.0), 2.0);
        non.push((EXPLOSION, per_proc));
    }
    Status { procs, rows, non }
}

/// `attack_data(st, aim)`: (vector, procs, rows, non).
pub fn attack_data(s: &Core, aim: f64, tables: &TargetTables) -> (Vector, Vector, Vec<(D, Row)>, Vec<(D, f64)>) {
    let (body_types, body_shot) = direct(s, tables.damage[0], tables);
    let head_shot = if aim != 0.0 { direct(s, tables.damage[1], tables).1 } else { body_shot };
    let total = body_shot * (1.0 - aim) + head_shot * aim;
    let raw_sum = psum(body_types.iter().map(|e| e.1));
    let vector: Vector = if raw_sum != 0.0 {
        body_types.iter().map(|(d, v)| (*d, v * total / raw_sum)).collect()
    } else {
        Vec::new()
    };
    let b = status(s, 0, tables);
    let h = if aim != 0.0 { Some(status(s, 1, tables)) } else { None };
    let h = h.as_ref().unwrap_or(&b);
    let rows: Vec<(D, Row)> = b
        .rows
        .iter()
        .map(|(d, r)| {
            let hr = h.rows.iter().find(|x| x.0 == *d).map(|x| x.1).unwrap_or(*r);
            (*d, Row { seed: r.seed * (1.0 - aim) + hr.seed * aim, ..*r })
        })
        .collect();
    let mut keys: Vec<D> = b.procs.iter().map(|e| e.0).collect();
    for e in &h.procs {
        if !keys.contains(&e.0) {
            keys.push(e.0);
        }
    }
    let procs: Vector = keys
        .into_iter()
        .map(|d| (d, (1.0 - aim) * get(&b.procs, d).unwrap_or(0.0) + aim * get(&h.procs, d).unwrap_or(0.0)))
        .collect();
    let non: Vec<(D, f64)> = b
        .non
        .iter()
        .map(|(d, p)| {
            let hp = h.non.iter().find(|x| x.0 == *d).map(|x| x.1).unwrap_or(*p);
            (*d, p * (1.0 - aim) + hp * aim)
        })
        .collect();
    (vector, procs, rows, non)
}

/// packet()'s crit-view branch: the view, its tables, and the weight-1 regrouping.
/// combat_replay.packet's crit view: `extra` is Enervate's stacks * 0.1.
pub fn crit_view(s: &Core, extra: f64, puncture: f64, cold: f64, shiver: f64, frozen: f64) -> Core {
    let mut view = s.clone();
    view.crit_chance = pmax(0.0, s.crit_chance + extra + puncture);
    view.crit_multiplier = (match (s.low_crit_threshold, s.low_crit_damage_base) {
        (Some(threshold), Some(base)) => base + if view.crit_chance < threshold { s.low_crit_damage_bonus } else { 0.0 },
        _ => s.crit_multiplier,
    }) + cold;
    if shiver != 1.0 || frozen != 1.0 {
        view.damage_types = s.damage_types.iter().map(|(d, v)| (*d, v * shiver * frozen)).collect();
        if let Some(dot) = s.dot_base_damage {
            view.dot_base_damage = Some(dot * shiver);
        }
    }
    view
}

pub fn crit_view_packet(s: &Core, aim: f64, puncture: f64, cold: f64, shiver: f64, frozen: f64, tables: &TargetTables)
    -> (Vector, Vector, Vec<(D, Row)>, Vec<(D, f64)>) {
    let mut view = s.clone();
    view.crit_chance = pmax(0.0, s.crit_chance + 0.0 + puncture);
    view.crit_multiplier = (match (s.low_crit_threshold, s.low_crit_damage_base) {
        (Some(threshold), Some(base)) => base + if view.crit_chance < threshold { s.low_crit_damage_bonus } else { 0.0 },
        _ => s.crit_multiplier,
    }) + cold;
    if shiver != 1.0 || frozen != 1.0 {
        view.damage_types = s.damage_types.iter().map(|(d, v)| (*d, v * shiver * frozen)).collect();
        if let Some(dot) = s.dot_base_damage {
            view.dot_base_damage = Some(dot * shiver);
        }
    }
    let (v, p, r, n) = attack_data(&view, aim, tables);
    let vector: Vector = v.iter().map(|(d, x)| (*d, 0.0 + 1.0 * x)).collect();
    let procs: Vector = p.iter().map(|(d, x)| (*d, 0.0 + 1.0 * x)).collect();
    let rows = r
        .iter()
        .map(|(d, row)| {
            let pk = get(&p, *d).unwrap_or(0.0);
            let sum = 0.0 + 1.0 * pk * row.seed;
            let total = get(&procs, *d).unwrap_or(0.0);
            (*d, Row { seed: if total != 0.0 { sum / total } else { 0.0 }, ..*row })
        })
        .collect();
    let non = n
        .iter()
        .map(|(d, per)| {
            let pk = get(&p, *d).unwrap_or(0.0);
            let sum = 0.0 + 1.0 * pk * per;
            let total = get(&procs, *d).unwrap_or(0.0);
            (*d, if total != 0.0 { sum / total } else { 0.0 })
        })
        .collect();
    (vector, procs, rows, non)
}
