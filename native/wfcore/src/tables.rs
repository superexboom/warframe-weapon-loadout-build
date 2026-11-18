//! The replay's per-hit damage tables (`attack_data`): the direct damage
//! vector from `damage_against_cached_armour` against the bare defence
//! snapshot, and the DoT / Blast rows of `expected_status_damage` against the
//! replay's unit DoT target. Target-side factors are constants of one replay
//! and come precomputed from Python (`TargetTables`); everything here is the
//! reference's arithmetic over the stats, in the same order.

use crate::pymath::{pmax, pmin, pow, psum, trunc_i, floor_i, PySum};

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
    pub area_direct: bool,
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
    pub dot_head_eligible: [bool; 2],
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

pub(crate) fn tier_factor(tier: i64, multiplier: f64) -> f64 {
    if tier == 0 { return 1.0; }
    (1.0 + tier as f32 * (multiplier as f32 - 1.0)).max(0.0) as f64
}

pub fn effective_crit_multiplier(chance: f64, multiplier: f64) -> f64 {
    if chance <= 0.0 {
        return 1.0;
    }
    let guaranteed = trunc_i(chance);
    let remainder = chance - guaranteed as f64;
    let low = tier_factor(guaranteed, multiplier);
    if remainder == 0.0 { low } else { low * (1.0 - remainder) + tier_factor(guaranteed + 1, multiplier) * remainder }
}

pub fn effective_hit_multiplier(cc: f64, cm: f64, noncrit: f64, factor: f64, double: f64) -> f64 {
    if double > 0.0 && cc > 0.0 {
        return psum(crit_tier_seed_distribution(cc, cm, noncrit, factor, double, false).map(|(p,f)| p*f));
    }
    let crit = effective_crit_multiplier(cc, cm * factor);
    let noncrit_chance = pmin(1.0, pmax(1.0 - cc, 0.0));
    let noncrit_bonus = pmax(noncrit - 1.0, 0.0);
    crit + noncrit_chance * noncrit_bonus
}

fn crit_tier_seed_distribution(cc: f64, cm: f64, noncrit: f64, factor: f64, double: f64, critical_only: bool) -> impl Clone + Iterator<Item=(f64,f64)> {
    let chance = pmax(cc, 0.0);
    let whole = trunc_i(chance);
    let fraction = chance - whole as f64;
    let promotion = pmin(1.0, pmax(0.0, double));
    let lower_promotion = if whole > 0 { promotion } else { 0.0 };
    let mut weights = [(1.0-fraction)*(1.0-lower_promotion),
        (1.0-fraction)*lower_promotion + fraction*(1.0-promotion), fraction*promotion];
    if critical_only && whole == 0 { weights[0] = 0.0; }
    let total = if critical_only { psum(weights) } else { 1.0 };
    weights.into_iter().enumerate().filter(|(_,w)| *w > 0.0).map(move |(i,w)| {
        let tier = whole + i as i64;
        (w / total, if tier == 0 { pmax(1.0, noncrit) } else { tier_factor(tier, cm * factor) })
    })
}

fn weakpoint_noncrit_scale(s: &Core, hm: f64) -> f64 {
    if s.radial_only || hm <= 1.0 + 1e-9 {
        return 1.0;
    }
    let mut scale = s.headshot_bonus_multiplier;
    if !s.ignore_headshot_bonus && !s.area_direct && s.weakpoint_damage_bonus > 0.0 {
        scale *= (hm + 1.5 * s.weakpoint_damage_bonus) / hm;
    }
    scale
}

pub(crate) fn location_hit_factor(s: &Core, hm: f64, hcm: f64) -> f64 {
    effective_hit_multiplier(location_crit_chance(s, hm > 1.0 + 1e-9), s.crit_multiplier,
        s.noncrit_damage_multiplier, hcm, s.double_crit_chance) * weakpoint_noncrit_scale(s, hm)
}

pub(crate) fn quantize(damage: &Vector, modded_base: f64) -> Vector {
    if modded_base <= 0.0 {
        return damage.clone();
    }
    let unit = modded_base / 32.0;
    damage
        .iter()
        .map(|(d, v)| (*d, if unit > 0.0 { (pmax(v / unit,0.0)+0.5).floor() * unit } else { *v }))
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
    let applied_hm = if s.ignore_headshot_bonus || s.area_direct { 1.0 } else { hm };
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
    let raw = psum(per_type.iter().map(|e| e.1)) * location_hit_factor(s, hm, hcm);
    (per_type, raw * pmax(s.multishot, 0.0))
}

fn location_crit_chance(s: &Core, head: bool) -> f64 {
    let chance = s.crit_chance;
    if s.radial_only {
        return pmax(chance, 0.0);
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

fn status_weights(s: &Core) -> Vector {
    quantize(&s.damage_types, s.dot_base_damage.unwrap_or_else(|| s.total_damage()))
}

pub fn expected_status_procs(s: &Core, forced: &Vector, head: bool) -> Vector {
    let weights = if s.status_chance > 0.0 { status_weights(s) } else { Vec::new() };
    expected_procs_with_weights(s, forced, head, &weights, psum(weights.iter().map(|e| e.1).filter(|x| *x > 0.0)))
}

fn expected_procs_with_weights(s: &Core, forced: &Vector, head: bool, weights: &Vector, total_weight: f64) -> Vector {
    let chance = pmax(s.status_chance, 0.0);
    let mut shots = pmax(s.multishot, 0.0);
    let random_total = chance * shots;
    if s.continuous {
        shots = if shots > 0.0 { 1.0 } else { 0.0 };
    }
    let mut result: Vector = Vec::new();
    if random_total != 0.0 && total_weight != 0.0 {
        for (d, a) in weights {
            if *a > 0.0 {
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

/// No application probability from the actual packet view. `multishot` is
/// one ordinary pellet, or the merged beam roll; `extra` is forced per instance.
pub fn no_status_probability(s: &Core, d: D, aim: f64, multishot: f64, extra: f64) -> f64 {
    let weights = status_weights(s);
    let total = psum(weights.iter().map(|e| e.1).filter(|x| *x > 0.0));
    let share = if total > 0.0 { get(&weights,d).unwrap_or(0.0).max(0.0)/total } else { 0.0 };
    no_status_with_share(s, d, aim, multishot, extra, share)
}

fn no_status_with_share(s: &Core, d: D, aim: f64, multishot: f64, extra: f64, share: f64) -> f64 {
    let crit = if s.crit_proc_chances.iter().any(|x| x.0 == d) {
        (1.0 - aim) * crit_proc_probability(s, d, false) + aim * crit_proc_probability(s, d, true)
    } else { 0.0 };
    let chance = pmax(s.status_chance, 0.0);
    let multishot = pmax(multishot, 0.0);
    let forced_per = s.native_forced_procs.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0);
    let independent = pmax(s.independent_proc_chances.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0), 0.0);
    let independent = 1.0 - (1.0 - pmin(1.0, independent)) * (1.0 - crit);
    let continuous = s.continuous;
    let zero_rolls = |chance: f64| -> f64 {
        let whole = chance.floor();
        pow(1.0 - share, whole) * (1.0 - (chance - whole) * share)
    };
    let zero_for_pellets = |pellets: i64| -> f64 {
        if pellets <= 0 { return 1.0; }
        let instances = if continuous { 1.0 } else { pellets as f64 };
        let natural = if continuous {
            zero_rolls(chance * pellets as f64)
        } else { pow(zero_rolls(chance), pellets as f64) };
        natural * pow(1.0 - pmin(1.0, forced_per), instances) * pow(1.0 - pmin(1.0, independent), instances)
    };
    let whole = floor_i(multishot);
    let fraction = multishot - whole as f64;
    let zero = (1.0 - fraction) * zero_for_pellets(whole) + fraction * zero_for_pellets(whole + 1);
    let extra = pmax(extra, 0.0);
    pmin(1.0, pmax(0.0, zero * (1.0 - pmin(1.0, extra))))
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

/// Conditional applying-hit mark, kept until the shared pile consumes it.
#[derive(Clone, Copy)]
pub struct LandingBranch {
    pub weight: f64,
    pub procs: f64,
    pub absence: f64,
    pub seed: f64,
    pub accumulator: f64,
    pub landing: f64,
    pub aim: f64,
    pub head: bool,
    pub weak: bool,
}

#[derive(Clone)]
pub struct Row {
    pub duration: f64,
    pub absence: f64,
    pub seed: f64,
    pub accumulator: f64,
    pub shared: bool,
    pub coefficient: f64,
    pub landing: f64,
    pub landing_head: bool,
    pub landing_weak_eligible: bool,
    pub branches: Vec<LandingBranch>,
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
    let applied_hm = if s.ignore_headshot_bonus || s.area_direct { 1.0 } else { hm };
    let forced = &tables.forced_procs;
    let weights = if s.status_chance > 0.0 { status_weights(s) } else { Vec::new() };
    let weight_sum = psum(weights.iter().map(|e| e.1).filter(|x| *x > 0.0));
    let procs = expected_procs_with_weights(s, forced, loc.head, &weights, weight_sum);
    let dot_base = pmax(match s.dot_base_damage {
        Some(v) => v,
        None => s.total_damage(),
    }, 0.0);
    let seed_tiers = crit_tier_seed_distribution(location_crit_chance(s, hm > 1.0 + 1e-9), s.crit_multiplier, s.noncrit_damage_multiplier, hcm, s.double_crit_chance, false);
    let weak_seed_scale = weakpoint_noncrit_scale(s, hm);
    let crit_seed_tiers = (!s.crit_proc_chances.is_empty()).then(||
        crit_tier_seed_distribution(location_crit_chance(s, loc.head), s.crit_multiplier, 1.0, hcm, s.double_crit_chance, true));
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
        let part_landing = d == ELECTRICITY || d == GAS;
        let landing_head = part_landing && !s.radial_only && tables.dot_head_eligible[loc_index];
        // ignore_headshot_bonus suppresses raw part/crit multipliers, not
        // the head event or its independent Deadhead-like landing bracket.
        let landing_weak_eligible = landing_head;
        let radial_scale = elemental_factor * pmax(faction_mod, 0.0) * target_multiplier;
        let landing = (if landing_weak_eligible { s.headshot_bonus_multiplier } else { 1.0 })
            * if part_landing { radial_scale } else { 1.0 };
        let accumulator_multiplier = if part_landing { coefficient } else { pmax(elemental, 0.0) * proc_damage };
        let unit = coefficient * seed_basis * seed_merge(s, d, forced);
        let unit = if part_landing {
            unit * proc_damage * s.falloff_multiplier * applied_hm * pmax(faction_mod, 0.0)
        } else {
            unit * elemental_factor * proc_damage * s.falloff_multiplier * applied_hm
                * target_multiplier * pow(pmax(faction_mod, 0.0), 2.0)
        };
        let mut crit_share = 0.0;
        if get(&s.crit_proc_chances, d).is_some() {
            let shots = if s.continuous { 1.0 } else { pmax(s.multishot, 0.0) };
            crit_share = pmin(shots * crit_proc_probability(s, d, loc.head) / count, 1.0);
        }
        let tiers = seed_tiers.clone().map(|(w,f)| ((1.0-crit_share)*w, unit*f*weak_seed_scale))
            .chain(crit_seed_tiers.clone().into_iter().flatten().map(|(w,f)| (crit_share*w, unit*f*crit_seed_scale)));
        let seed = psum(tiers.filter(|(w,_)| *w > 0.0).map(|(w,ps)| w*ps));
        let duration = 6.0 * s.duration_scale(d);
        let accumulator = accumulator * accumulator_multiplier;
        let pellets = pmax(s.multishot, 0.0);
        let instances = if s.continuous { 1.0 } else { pellets };
        let extra = if instances > 0.0 { get(forced, d).unwrap_or(0.0) / instances } else { 0.0 };
        let absence = if part_landing {
            let share = if weight_sum > 0.0 { get(&weights,d).unwrap_or(0.0).max(0.0)/weight_sum } else { 0.0 };
            no_status_with_share(s, d, if loc.head { 1.0 } else { 0.0 },
                                 if s.continuous { pellets } else { 1.0 }, extra, share)
        } else { 1.0 };
        let branches = if part_landing {
            vec![LandingBranch { weight: 1.0, procs: count, absence, seed, accumulator, landing,
                                 aim: loc_index as f64, head: landing_head, weak: landing_weak_eligible }]
        } else { Vec::new() };
        rows.push((d, Row { duration, absence, seed, accumulator, shared, coefficient,
                           landing, landing_head, landing_weak_eligible, branches }));
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
    // Include head-only status types (e.g. a weak-point conditioned proc).
    // The legacy scalar row is proc-weighted; E/G consumers use the conditional
    // branches, never E[seed] * E[landing].
    let mut row_keys: Vec<D> = b.rows.iter().map(|e| e.0).collect();
    for (d, _) in &h.rows {
        if (*d == ELECTRICITY || *d == GAS) && !row_keys.contains(d) { row_keys.push(*d); }
    }
    let rows: Vec<(D, Row)> = row_keys.into_iter().map(|d| {
        let br = b.rows.iter().find(|e| e.0 == d).map(|e| &e.1);
        let hr = h.rows.iter().find(|e| e.0 == d).map(|e| &e.1);
        let mut row = br.or(hr).unwrap().clone();
        let bp = get(&b.procs, d).unwrap_or(0.0);
        let hp = get(&h.procs, d).unwrap_or(0.0);
        let count = (1.0 - aim) * bp + aim * hp;
        row.seed = if d == ELECTRICITY || d == GAS {
            if count > 0.0 {
                ((1.0 - aim) * bp * br.map_or(0.0, |r| r.seed)
                 + aim * hp * hr.map_or(0.0, |r| r.seed)) / count
            } else { 0.0 }
        } else {
            let body_seed = br.unwrap().seed;
            body_seed * (1.0 - aim) + hr.map_or(body_seed, |r| r.seed) * aim
        };
        row.branches.clear();
        if d == ELECTRICITY || d == GAS {
            for (weight, conditional, procs, branch_aim) in [(1.0 - aim, br, bp, 0.0), (aim, hr, hp, 1.0)] {
                if weight > 0.0 {
                    if let Some(r) = conditional {
                        row.branches.push(LandingBranch { weight, procs, absence: r.absence, seed: r.seed,
                            accumulator: r.accumulator, landing: r.landing, aim: branch_aim,
                            head: r.landing_head, weak: r.landing_weak_eligible });
                    } else {
                        // An aim branch with no proc row still owns its
                        // no-application probability mass.
                        row.branches.push(LandingBranch { weight, procs: 0.0, absence: 1.0, seed: 0.0,
                            accumulator: 0.0, landing: 1.0, aim: branch_aim,
                            head: false, weak: false });
                    }
                }
            }
        }
        (d, row)
    }).collect();
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
            (*d, Row { seed: if total != 0.0 { sum / total } else { 0.0 }, ..row.clone() })
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
