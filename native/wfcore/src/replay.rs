#![allow(deprecated)]
//! `combat_replay._trajectory`, stage 1: the event loop of ordinary guns
//! (hitscan / projectile parts, radial parts, bursts, beams, reloads, every
//! status and DoT, triggers, kills, extra hits, magnetic breaks). Anything
//! else raises `NativeUnsupported` and the Python reference replays instead.
//!
//! Stat resolution (the combat resolver) and the per-hit damage tables
//! (attack_data / crit views) stay in Python and are called back; their
//! results are pure functions of their inputs and are cached here by value.
//! Every float operation keeps the reference's order.

use crate::heat::HeatChains;
use crate::proc::{capped_stack_add, stack_alive, CappedPool, DotInstance, KillAttribution, StatusPresence};
use crate::pymath::{ceil_i, floor_i, pmax, pmin, pow, psum, trunc_i, PySum};
use crate::tables::{self, Core, Location, TargetTables};
use crate::co;
use crate::stackable::{self, Projectiles};
use std::rc::Rc;
use crate::fx::{FxHashMap, FxIndexMap};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};

pyo3::create_exception!(wfcore, NativeUnsupported, pyo3::exceptions::PyException);

/// A Python ``{damage type: value}`` dict as a vector, interning the names.
pub(crate) fn vector_of(types: &mut Types, obj: &Bound<'_, PyAny>) -> PyResult<Vector> {
    let d = obj.downcast::<PyDict>()?;
    let mut out = Vec::with_capacity(d.len());
    for (k, v) in d.iter() {
        let name: String = k.extract()?;
        out.push((types.id(&name), v.extract::<f64>()?));
    }
    Ok(out)
}

/// The tables' view of a Python ``ModdedStats`` (``target_faction`` picks the
/// faction row); the vectors are read by the caller, which keeps them too.
pub(crate) fn core_of(obj: &Bound<'_, PyAny>, types: &mut Types, target_faction: &str, damage_types: &Vector,
                  native_forced_procs: &Vector, independent_proc_chances: &Vector) -> PyResult<Core> {
    let factions = obj.getattr("faction_damage_multipliers")?;
    let factions = factions.cast::<PyDict>()?;
    let faction_all = match factions.get_item("")? { Some(v) => v.extract::<f64>()?, None => 1.0 };
    let faction_target = if target_faction.is_empty() {
        1.0
    } else {
        match factions.get_item(target_faction)? { Some(v) => v.extract::<f64>()?, None => 1.0 }
    };
    let dot = obj.getattr("dot_base_damage")?;
    let mut conversions = Vec::new();
    for (k, adapters) in obj.getattr("impact_proc_conversions")?.cast::<PyDict>()?.iter() {
        let d = types.id(&k.extract::<String>()?);
        let mut rows = Vec::new();
        for adapter in adapters.try_iter()? {
            let adapter = adapter?;
            let a = adapter.cast::<PyDict>()?;
            rows.push((get_f(a, "chance", 0.0)?, get_f(a, "fireRateThreshold", f64::INFINITY)?,
                       get_f(a, "fireRateMultiplier", 1.0)?));
        }
        conversions.push((d, rows));
    }
    let mut extra_hits = Vec::new();
    for e in obj.getattr("extra_hits")?.try_iter()? {
        let e = e?;
        let t = e.cast::<PyTuple>()?;
        extra_hits.push((types.id(&t.get_item(0)?.extract::<String>()?), t.get_item(1)?.extract::<f64>()?,
                         t.get_item(2)?.is_truthy()?));
    }
    let low_threshold = obj.getattr("low_crit_threshold")?;
    let low_base = obj.getattr("low_crit_damage_base")?;
    Ok(Core {
        damage_types: damage_types.clone(),
        dot_base_damage: if dot.is_none() { None } else { Some(dot.extract::<f64>()?) },
        crit_chance: f(obj, "crit_chance")?,
        crit_multiplier: f(obj, "crit_multiplier")?,
        noncrit_damage_multiplier: f(obj, "noncrit_damage_multiplier")?,
        double_crit_chance: f(obj, "double_crit_chance")?,
        falloff_multiplier: f(obj, "falloff_multiplier")?,
        faction_all,
        faction_target,
        multishot: f(obj, "multishot")?,
        continuous: b(obj, "continuous")?,
        radial_only: b(obj, "radial_only")?,
        bodyshot_crit_multiplier: f(obj, "bodyshot_crit_multiplier")?,
        weakpoint_crit_chance_bonus: f(obj, "weakpoint_crit_chance_bonus")?,
        base_crit_chance: f(obj, "base_crit_chance")?,
        weakpoint_crit_chance_relative: f(obj, "weakpoint_crit_chance_relative")?,
        headshot_bonus_multiplier: f(obj, "headshot_bonus_multiplier")?,
        weakpoint_damage_bonus: match opt_attr(obj, "weakpoint_damage_bonus")? { Some(v) => v.extract::<f64>()?, None => 0.0 },
        status_chance: f(obj, "status_chance")?,
        proc_duration_multiplier: f(obj, "proc_duration_multiplier")?,
        proc_damage_multiplier: f(obj, "proc_damage_multiplier")?,
        native_forced_procs: native_forced_procs.clone(),
        independent_proc_chances: independent_proc_chances.clone(),
        crit_proc_chances: vector_of(types, &obj.getattr("crit_proc_chances")?)?,
        impact_proc_conversions: conversions,
        fire_rate: f(obj, "fire_rate")?,
        dot_elemental_multipliers: vector_of(types, &obj.getattr("dot_elemental_multipliers")?)?,
        extra_hits,
        low_crit_threshold: if low_threshold.is_none() { None } else { Some(low_threshold.extract::<f64>()?) },
        low_crit_damage_base: if low_base.is_none() { None } else { Some(low_base.extract::<f64>()?) },
        low_crit_damage_bonus: f(obj, "low_crit_damage_bonus")?,
    })
}

// ── damage-type interning ────────────────────────────────────────────────

type D = u32;

pub(crate) struct Types {
    names: Vec<String>,
    index: FxHashMap<String, D>,
}
impl Types {
    pub(crate) fn new() -> Self {
        let mut t = Types { names: Vec::new(), index: FxHashMap::default() };
        for name in [
            "DT_FIRE", "DT_FREEZE", "DT_GAS", "DT_EXPLOSION", "DT_VIRAL", "DT_CORROSIVE", "DT_MAGNETIC",
            "DT_PUNCTURE", "DT_ELECTRICITY", "DT_SLASH", "DT_CINEMATIC", "DT_VOID", "DT_RADIANT",
            "DT_IMPACT", "DT_POISON",
        ] {
            t.id(name);
        }
        t
    }
    pub(crate) fn id(&mut self, name: &str) -> D {
        if let Some(&i) = self.index.get(name) {
            return i;
        }
        let i = self.names.len() as D;
        self.names.push(name.to_string());
        self.index.insert(name.to_string(), i);
        i
    }
    pub(crate) fn name(&self, d: D) -> &str {
        &self.names[d as usize]
    }
}
const FIRE: D = 0;
const FREEZE: D = 1;
const GAS: D = 2;
const EXPLOSION: D = 3;
const VIRAL: D = 4;
const CORROSIVE: D = 5;
const MAGNETIC: D = 6;
const PUNCTURE: D = 7;
const ELECTRICITY: D = 8;
const SLASH: D = 9;
const CINEMATIC: D = 10;
const VOID: D = 11;
const RADIANT: D = 12;

fn duration_of(d: D) -> Option<f64> {
    match d {
        VIRAL => Some(6.0),
        CORROSIVE => Some(8.0),
        MAGNETIC => Some(6.0),
        FREEZE => Some(6.0),
        PUNCTURE => Some(10.0),
        _ => None,
    }
}
fn cap_of(d: D) -> Option<f64> {
    match d {
        VIRAL | CORROSIVE | MAGNETIC | FREEZE | GAS => Some(10.0),
        PUNCTURE => Some(5.0),
        _ => None,
    }
}
fn pooled_index(d: D) -> Option<usize> {
    match d {
        VIRAL => Some(0),
        CORROSIVE => Some(1),
        MAGNETIC => Some(2),
        PUNCTURE => Some(3),
        _ => None,
    }
}

type Vector = Vec<(D, f64)>;
/// (view, aim, puncture, cold, shiver, frozen, Enervate weights id) as bits.
type PacketKey = (usize, u64, u64, u64, u64, u64, u64);

// ── stats views ──────────────────────────────────────────────────────────

struct Stats {
    obj: PyObject,
    core: Core,
    magazine: f64,
    ammo_cost: f64,
    fire_rate: f64,
    reload_time: f64,
    multishot: f64,
    continuous: bool,
    radial_only: bool,
    crit_chance: f64,
    crit_multiplier: f64,
    bodyshot_crit_multiplier: f64,
    weakpoint_crit_chance_bonus: f64,
    base_crit_chance: f64,
    weakpoint_crit_chance_relative: f64,
    status_chance: f64,
    proc_duration_multiplier: f64,
    proc_damage_multiplier: f64,
    damage_types: Vector,
    native_forced_procs: Vector,
    independent_proc_chances: Vector,
    has_crit_procs: bool,
    first_shot_damage_bonus: f64,
    cold_stack_damage: f64,
    base_damage_bracket: f64,
    frozen_damage_multiplier: f64,
    requires_full_ammo: bool,
    bow_draw: Option<f64>,
    charge_time: f64,
    initial_combo: f64,
    heavy_charge_speed: f64,
    combo_duration: f64,
    combo_extra_chance: f64,
    combo_miss_chance: f64,
    heavy_attack_efficiency: f64,
    additional: Vec<usize>,
    head_only: bool,
    impact_delay: f64,
    lingering: Option<(usize, f64, f64)>,
    primary_delay: f64,
    fixed_radial: bool,
    victim_full_crit_chance: f64,
    victim_full_crit_damage: f64,
    victim_low_health_multiplier: f64,
    ammo_pool_multishot_cost: f64,
    ammo_pool_damage_bonus: f64,
    charge_pool_cost: f64,
    /// The CO bucket as (operation, value); a non-empty bucket makes the view
    /// depend on the live status count.
    co_bucket: Vec<(u8, f64)>,
    /// `_co_spec`: lets a fractional live count be derived natively.
    co_spec: Option<Rc<co::CoSpec>>,
    slam_damage_ratio: f64,
    incarnon_charge_multiplier: f64,
    /// `_stackable`: the deployment profile and its damage parts.
    stackable: Option<(Rc<stackable::Profile>, stackable::Parts)>,
}

impl Stats {
    /// What `dataclasses.replace` keeps: fields only, never instance attributes.
    fn drop_private(&mut self) {
        self.bow_draw = None;
        self.charge_time = 0.0;
        self.primary_delay = 0.0;
        self.lingering = None;
        self.charge_pool_cost = 1.0;
        self.requires_full_ammo = false;
        self.head_only = false;
        self.impact_delay = 0.0;
        self.fixed_radial = false;
        self.additional = Vec::new();
        self.co_spec = None;
        self.stackable = None;
    }

    fn clone_with(&self, py: Python<'_>) -> Stats {
        Stats {
            obj: self.obj.clone_ref(py),
            core: self.core.clone(),
            magazine: self.magazine,
            ammo_cost: self.ammo_cost,
            fire_rate: self.fire_rate,
            reload_time: self.reload_time,
            multishot: self.multishot,
            continuous: self.continuous,
            radial_only: self.radial_only,
            crit_chance: self.crit_chance,
            crit_multiplier: self.crit_multiplier,
            bodyshot_crit_multiplier: self.bodyshot_crit_multiplier,
            weakpoint_crit_chance_bonus: self.weakpoint_crit_chance_bonus,
            base_crit_chance: self.base_crit_chance,
            weakpoint_crit_chance_relative: self.weakpoint_crit_chance_relative,
            status_chance: self.status_chance,
            proc_duration_multiplier: self.proc_duration_multiplier,
            proc_damage_multiplier: self.proc_damage_multiplier,
            damage_types: self.damage_types.clone(),
            native_forced_procs: self.native_forced_procs.clone(),
            independent_proc_chances: self.independent_proc_chances.clone(),
            has_crit_procs: self.has_crit_procs,
            first_shot_damage_bonus: self.first_shot_damage_bonus,
            cold_stack_damage: self.cold_stack_damage,
            base_damage_bracket: self.base_damage_bracket,
            frozen_damage_multiplier: self.frozen_damage_multiplier,
            requires_full_ammo: self.requires_full_ammo,
            bow_draw: self.bow_draw,
            charge_time: self.charge_time,
            initial_combo: self.initial_combo,
            heavy_charge_speed: self.heavy_charge_speed,
            combo_duration: self.combo_duration,
            combo_extra_chance: self.combo_extra_chance,
            combo_miss_chance: self.combo_miss_chance,
            heavy_attack_efficiency: self.heavy_attack_efficiency,
            additional: self.additional.clone(),
            head_only: self.head_only,
            impact_delay: self.impact_delay,
            lingering: self.lingering,
            primary_delay: self.primary_delay,
            fixed_radial: self.fixed_radial,
            victim_full_crit_chance: self.victim_full_crit_chance,
            victim_full_crit_damage: self.victim_full_crit_damage,
            victim_low_health_multiplier: self.victim_low_health_multiplier,
            ammo_pool_multishot_cost: self.ammo_pool_multishot_cost,
            ammo_pool_damage_bonus: self.ammo_pool_damage_bonus,
            charge_pool_cost: self.charge_pool_cost,
            co_bucket: self.co_bucket.clone(),
            co_spec: self.co_spec.clone(),
            slam_damage_ratio: self.slam_damage_ratio,
            incarnon_charge_multiplier: self.incarnon_charge_multiplier,
            stackable: self.stackable.clone(),
        }
    }
}

const UNSUPPORTED_ATTRS: [&str; 1] = ["_mine_extra"];

/// A list of ModEffect as (operation code, value).
fn effect_ops(list: &Bound<'_, PyAny>) -> PyResult<Vec<(u8, f64)>> {
    let mut out = Vec::new();
    for e in list.try_iter()? {
        let e = e?;
        out.push((co::op_code(&e.getattr("operation")?.extract::<String>()?), f(&e, "value")?));
    }
    Ok(out)
}

pub(crate) fn f(o: &Bound<'_, PyAny>, name: &str) -> PyResult<f64> {
    o.getattr(name)?.extract::<f64>()
}
pub(crate) fn b(o: &Bound<'_, PyAny>, name: &str) -> PyResult<bool> {
    o.getattr(name)?.is_truthy()
}
pub(crate) fn opt_attr<'py>(o: &Bound<'py, PyAny>, name: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    match o.getattr(name) {
        Ok(v) => Ok(Some(v)),
        Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(o.py()) => Ok(None),
        Err(e) => Err(e),
    }
}

// ── events ───────────────────────────────────────────────────────────────

#[derive(Clone)]
enum Kind {
    Fire,
    ReloadComplete(bool),
    Heat(i64),
    Blast(usize),
    BlastAll,
    IndependentDot(usize),
    Dot(D, f64, f64),
    Actor(String),
    Energy(usize),
    Syndicate,
    ReloadShell(f64, f64),
    Transform(u8),
    DelayedRadial(usize, f64),
    DelayedAttack(usize, f64),
    Lingering(usize),
    /// A remote-mine batch: (view, generation, blast part riding a mine).
    Detonation(Rc<Vec<(usize, i64, bool)>>),
    /// 'stackable-life': (group, token, action)
    StackLife(usize, i64, u8),
    /// 'stackable-child': (group, multiplier, hits)
    StackChild(usize, f64, f64),
}

struct Event {
    t: f64,
    seq: u64,
    kind: Kind,
    gen: Option<i64>,
}

/// The remaining ticks of one DoT instance: tick k is at `t + (first + k)`
/// with sequence number `base + 1 + k`.
struct TickChain {
    t: f64,
    first: i64,
    count: usize,
    base: u64,
    next: usize,
    gen: Option<i64>,
}
impl PartialEq for Event {
    fn eq(&self, o: &Self) -> bool {
        self.t == o.t && self.seq == o.seq
    }
}
impl Eq for Event {}
impl PartialOrd for Event {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Event {
    fn cmp(&self, o: &Self) -> Ordering {
        o.t.total_cmp(&self.t).then(o.seq.cmp(&self.seq))
    }
}

// ── trigger sources ──────────────────────────────────────────────────────

struct Source {
    obj: Py<PyDict>,
    id: PyObject,
    kind: Option<String>,
    stacks: f64,
    expires: f64,
    max_stacks: f64,
    duration: f64,
    per_event: f64,
    decay: String,
    initial_stacks: f64,
    hold: bool,
    reset_on: Vec<String>,
    toggle_on: Option<String>,
    victim_proc_type: Option<D>,
    required_count: f64,
    required_time: Option<f64>,
    actor_only: bool,
    minimum_consecutive: i64,
    energy_threshold: f64,
    expiries: Vec<(f64, f64)>,
    progress: VecDeque<(f64, f64)>,
    run_distribution: Option<FxIndexMap<i64, f64>>,
}

struct Packet {
    vector: Vector,
    procs: Vector,
    rows: FxIndexMap<D, Row>,
    non: FxIndexMap<D, f64>,
}
#[derive(Clone, Copy)]
struct Row {
    duration: f64,
    seed: f64,
    accumulator: f64,
    shared: bool,
    coefficient: f64,
}

struct Blast {
    count: f64,
    per: f64,
    end: f64,
}

pub struct Replay<'py> {
    py: Python<'py>,
    helper: Bound<'py, PyAny>,
    resolver: Bound<'py, PyAny>,
    types: Types,
    // configuration
    window: f64,
    head: f64,
    rate: f64,
    status_rate_multiplier: f64,
    damage_rate_multiplier: f64,
    full: [f64; 3],
    ehp: f64,
    armour_base: f64,
    elemental_armour_strip: f64,
    forced_procs: Vector,
    faction_deltas: Vec<(D, f64)>,
    armour_bypass: Vec<D>,
    shield_bypass: Vec<D>,
    extra_hits: Vec<(D, f64)>,
    extra_scale: f64,
    weapon_slot: String,
    distance: Option<f64>,
    punchthrough: f64,
    live_types_enabled: bool,
    beam_floor: Option<f64>,
    burst: Option<(bool, i64, f64, bool)>,
    burst_rate: Option<f64>,
    infinite_ammo: bool,
    victim_before: Vec<(D, f64)>,
    syndicate: Option<(String, D, f64)>,
    target_faction: String,
    tables: TargetTables,
    battery: Option<(f64, f64, f64)>,
    spool: Option<SpoolSpec>,
    rate_spool: Option<(f64, f64, f64)>,
    shell: Option<(f64, f64, f64)>,
    shot_combo: Option<ShotCombo>,
    reload_after_every_shot: bool,
    refill_growth: bool,
    restore: Option<Restore>,
    pending_restore: f64,
    recharges: i64,
    delayed_attacks: i64,
    reload_shell_events: Vec<(f64, f64, &'static str, u8)>,
    derived: FxHashMap<(usize, u8, u64), usize>,
    selected_incarnon: bool,
    melee: Option<MeleeSpec>,
    melee_count: f64,
    melee_heavy_multiplier: f64,
    melee_last_hit: f64,
    melee_pending: Option<MeleeHit>,
    heavy_flag: bool,
    affinity_per_kill: f64,
    affinity: f64,
    syndicate_ready: f64,
    syndicate_events: Vec<(f64, f64)>,
    // state
    pools: [f64; 3],
    states: FxIndexMap<D, VecDeque<(f64, f64)>>,
    pooled: [CappedPool; 4],
    presence: FxIndexMap<D, StatusPresence>,
    gas_procs: Vec<usize>,
    dots: Vec<DotInstance>,
    blasts: Vec<Blast>,
    blast_procs: VecDeque<usize>,
    heat_acc: f64,
    heat_token: i64,
    heat_chains: HeatChains,
    attribution: KillAttribution,
    puncture_strip: f64,
    frozen_until: f64,
    frozen_scale: f64,
    heap: BinaryHeap<Event>,
    seq: u64,
    gen: i64,
    kills: i64,
    weak_kill_events: f64,
    attacks: i64,
    stale: i64,
    first_kill: Option<f64>,
    last_kill: Option<f64>,
    min_interval: Option<f64>,
    totals: [f64; 5],
    /// Arcane Fortifier: (multiplier, steal, cap, uptime) and its tallies.
    fortifier: Option<(f64, f64, f64, f64)>,
    fortifier_damage: f64,
    fortifier_stolen: f64,
    self_overguard: f64,
    /// Secondary Empowered: (damage per status, uptime), its status pool and tallies.
    empowered: Option<(f64, f64)>,
    status_pool: Vec<D>,
    empowered_count: f64,
    empowered_by_type: FxIndexMap<D, f64>,
    /// Secondary Cryogenic: (cold stacks per Puncture, uptime).
    cryogenic: Option<(f64, f64)>,
    cryogenic_expected: f64,
    /// Latron Incarnon puncture armour strip per bullet with a Puncture status.
    puncture_armor_strip: f64,
    /// Secondary Encumber: (chance, uptime), the shot it last rolled on and tallies.
    encumber: Option<(f64, f64)>,
    encumber_time: f64,
    encumber_remaining: f64,
    encumber_expected: f64,
    enervate: Option<Enervate>,
    /// Onos charge cadence: (alignment shots, post-fire seconds, ramp seconds),
    /// whether crits stack from hits, and its state.
    /// body_ttk_health's life curve of the first target, when requested.
    life_curve: Option<Vec<(f64, f64, f64, usize)>>,
    onos: Option<(f64, f64, f64)>,
    onos_crits: bool,
    onos_ticks: i64,
    onos_hits: f64,
    onos_start: f64,
    onos_condition_hits: f64,
    projectiles: Option<Projectiles>,
    projectile_state: stackable::State,
    stack_profiles: FxHashMap<usize, Rc<stackable::Profile>>,
    /// Manual detonation (Talons-style mines): (delay, max projectiles, batch size).
    mines: Option<(f64, f64, f64)>,
    pending_mines: Vec<(usize, i64, bool)>,
    pending_throws: i64,
    waiting_mines: f64,
    detonations: i64,
    mine_overflows: i64,
    form: u8,
    cycle: Option<CycleSpec>,
    gauge: f64,
    base_ammo_saved: Option<f64>,
    transforms: i64,
    shells_owed: f64,
    shell_mode_switch: bool,
    burst_base: Option<BurstSpec>,
    burst_rate_base: Option<f64>,
    burst_incarnon: Option<BurstSpec>,
    burst_rate_incarnon: Option<f64>,
    beam_floor_base: Option<f64>,
    last_burst: bool,
    tap_other: (f64, f64),
    /// Double Tap (consecutive_hits.ConsecutiveHits): (per hit, maximum, duration), hits, expiry.
    tap: Option<(f64, f64, f64)>,
    tap_hits: f64,
    tap_expires: f64,
    /// Field duration on an empty reload: multiplier, armed flag, boosted shots.
    field_duration: Option<f64>,
    field_duration_ready: bool,
    field_duration_used: i64,
    /// Per-stack crit views (raw attack data) and the interned weight lists.
    enervate_views: FxHashMap<(usize, u64, i64, u64, u64, u64, u64), Rc<Packet>>,
    enervate_weights: FxHashMap<Vec<(i64, u64)>, u64>,
    proc_counts: FxIndexMap<D, f64>,
    dot_by_type: FxIndexMap<D, f64>,
    magnetic_breaks: Vec<(f64, usize, f64, f64, i64)>,
    sources: Vec<Source>,
    ammo: f64,
    shot_in_progress: bool,
    reloads: i64,
    last_round: bool,
    current_time: f64,
    beam_progress: f64,
    beam_last: Option<f64>,
    actor_signal: bool,
    actor_signal_used: bool,
    armour_view: Option<(u64, u64, f64)>,
    // caches
    stats: Vec<Stats>,
    stats_by_ptr: FxHashMap<usize, usize>,
    model_cache: FxHashMap<(Vec<u64>, u64, bool), (usize, Option<usize>)>,
    /// model()'s key buffer, reused while lookups hit.
    model_key: Vec<u64>,
    /// DoT ticks not yet in the heap, by instance (see add_procs_data).
    tick_chains: FxHashMap<usize, TickChain>,
    co_specs: FxHashMap<usize, Option<Rc<co::CoSpec>>>,
    varied: FxHashMap<(usize, u64), Option<usize>>,
    elements: co::Elements,
    hit_specs: Vec<Option<Rc<HitSpec>>>,
    applied: FxHashMap<(usize, i64, u64), usize>,
    packets: FxHashMap<PacketKey, Rc<Packet>>,
    spreads: FxHashMap<(usize, u64), f64>,
    first_shot: FxHashMap<usize, usize>,
    no_status: FxHashMap<(usize, D, u64), f64>,
    proc_names: Vec<Option<Rc<str>>>,
}

const DIRECT: usize = 0;
const DOT: usize = 1;
const NONDOT: usize = 2;
const SYNDICATE: usize = 3;
const ARCANE: usize = 4;
/// combat_replay's `form`: the selected mode (no cycle), or a cycle's two forms.
const SELECTED: u8 = 0;
const BASE: u8 = 1;
const INCARNON: u8 = 2;

#[derive(Clone, Copy)]
struct CycleSpec {
    hits: f64,
    enter: f64,
    exit: f64,
    pool: f64,
    /// 0: headshots (default), 1: direct hits, 2: kills.
    charge_on: u8,
    kill_charged: bool,
}

type BurstSpec = (bool, i64, f64, bool);

fn get_f(d: &Bound<'_, PyDict>, key: &str, default: f64) -> PyResult<f64> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => v.extract::<f64>(),
        _ => Ok(default),
    }
}
fn truthy(d: &Bound<'_, PyDict>, key: &str) -> PyResult<bool> {
    match d.get_item(key)? {
        Some(v) => v.is_truthy(),
        None => Ok(false),
    }
}

impl<'py> Replay<'py> {
    fn unsupported(reason: &str) -> PyErr {
        NativeUnsupported::new_err(reason.to_string())
    }

    fn vector_from(&mut self, obj: &Bound<'py, PyAny>) -> PyResult<Vector> {
        vector_of(&mut self.types, obj)
    }

    fn elements_from(&mut self, obj: &Bound<'py, PyAny>) -> PyResult<Vec<co::Element>> {
        let mut out = Vec::new();
        for e in obj.try_iter()? {
            let e = e?;
            let dtype = e.getattr("damage_type")?;
            let dtype = if dtype.is_truthy()? {
                let name: String = dtype.extract()?;
                if name == "DT_ANY" { None } else { Some(self.types.id(&name)) }
            } else {
                None
            };
            out.push((dtype, f(&e, "value")?));
        }
        Ok(out)
    }

    /// `damage.CoSpec` with type ids, memoised per spec object.
    fn co_spec_from(&mut self, spec: &Bound<'py, PyAny>) -> PyResult<Option<Rc<co::CoSpec>>> {
        let ptr = spec.as_ptr() as usize;
        if let Some(hit) = self.co_specs.get(&ptr) {
            return Ok(hit.clone());
        }
        let melee = b(spec, "melee")?;
        let out = {
            let opt = |name: &str| -> PyResult<Option<f64>> {
                let v = spec.getattr(name)?;
                Ok(if v.is_none() { None } else { Some(v.extract::<f64>()?) })
            };
            let base = co::Dict(self.vector_from(&spec.getattr("base")?)?);
            let mut innate = Vec::new();
            for e in spec.getattr("innate_entries")?.try_iter()? {
                let e = e?;
                let t = e.cast::<PyTuple>()?;
                let name: String = t.get_item(0)?.extract()?;
                let dtype = if name.is_empty() { None } else { Some(self.types.id(&name)) };
                innate.push((dtype, t.get_item(1)?.extract::<f64>()?));
            }
            let orb = spec.getattr("orb")?;
            let orb = if orb.is_none() {
                None
            } else {
                let t = orb.cast::<PyTuple>()?;
                Some((t.get_item(0)?.extract::<f64>()?, t.get_item(1)?.is_truthy()?,
                      t.get_item(2)?.extract::<f64>()?, t.get_item(3)?.extract::<f64>()?))
            };
            let fin = spec.getattr("final")?;
            let final_damage = if fin.is_none() {
                None
            } else {
                let t = fin.cast::<PyTuple>()?;
                Some((t.get_item(0)?.extract::<f64>()?, co::Dict(self.vector_from(&t.get_item(1)?)?)))
            };
            Some(Rc::new(co::CoSpec {
                victim_status_count: f(spec, "victim_status_count")?,
                damage_scale_effects: effect_ops(&spec.getattr("damage_scale_effects")?)?,
                ordinary_scale: f(spec, "ordinary_scale")?,
                compression_mult: f(spec, "compression_mult")?,
                gunco_independent: b(spec, "gunco_independent")?,
                gunco_fraction: opt("gunco_fraction")?,
                victim_damage: f(spec, "victim_damage")?,
                co_fraction: f(spec, "co_fraction")?,
                melee,
                melee_damage_effects: effect_ops(&spec.getattr("melee_damage_effects")?)?,
                slam_effects: effect_ops(&spec.getattr("slam_effects")?)?,
                base,
                base_total: f(spec, "base_total")?,
                elemental_base_total: f(spec, "elemental_base_total")?,
                pre: self.elements_from(&spec.getattr("pre")?)?,
                post: self.elements_from(&spec.getattr("post")?)?,
                innate,
                pool_factor: opt("pool_factor")?,
                copy_factor: opt("copy_factor")?,
                orb,
                final_damage,
                frozen_factor: opt("frozen_factor")?,
            }))
        };
        self.co_specs.insert(ptr, out.clone());
        Ok(out)
    }

    /// `manual_combat.live_variant` for one view: `st` resolved at `ceil`
    /// live status types, seen at `live`. None when some CO-dependent part
    /// has no native spec (the resolver then answers instead).
    fn vary(&mut self, st: usize, live: f64, ceil: f64) -> Option<usize> {
        let key = (st, live.to_bits());
        if let Some(&hit) = self.varied.get(&key) {
            return hit;
        }
        let result = self.vary_uncached(st, live, ceil);
        self.varied.insert(key, result);
        result
    }

    fn vary_uncached(&mut self, st: usize, live: f64, ceil: f64) -> Option<usize> {
        let mut out = st;
        if !self.stats[st].co_bucket.is_empty() {
            let spec = self.stats[st].co_spec.clone()?;
            let scaled: Vec<(u8, f64)> = self.stats[st].co_bucket.iter().map(|&(op, v)| (op, v * live / ceil)).collect();
            let damage = co::co_damage(&spec, &scaled, &self.elements);
            let mut view = self.stats[st].clone_with(self.py);
            view.damage_types = damage.damage_types.0;
            view.core.damage_types = view.damage_types.clone();
            view.base_damage_bracket = damage.base_bracket;
            view.victim_low_health_multiplier = damage.victim_low_health_multiplier;
            view.slam_damage_ratio = damage.slam_damage_ratio;
            view.co_bucket = scaled;
            self.stats.push(view);
            out = self.stats.len() - 1;
        }
        if let Some((part, rate, duration)) = self.stats[st].lingering {
            let varied = self.vary(part, live, ceil)?;
            if varied != part {
                out = self.own(st, out);
                self.stats[out].lingering = Some((varied, rate, duration));
            }
        }
        let extra = self.stats[st].additional.clone();
        if !extra.is_empty() {
            let mut parts = Vec::with_capacity(extra.len());
            for &part in &extra {
                parts.push(self.vary(part, live, ceil)?);
            }
            if parts != extra {
                out = self.own(st, out);
                self.stats[out].additional = parts;
            }
        }
        Some(out)
    }

    /// `out` if it is already a fresh copy of `st`, else a fresh copy.
    fn own(&mut self, st: usize, out: usize) -> usize {
        if out != st {
            return out;
        }
        let view = self.stats[st].clone_with(self.py);
        self.stats.push(view);
        self.stats.len() - 1
    }

    fn core_from(&mut self, obj: &Bound<'py, PyAny>, damage_types: &Vector, native_forced_procs: &Vector,
                 independent_proc_chances: &Vector) -> PyResult<Core> {
        core_of(obj, &mut self.types, &self.target_faction, damage_types, native_forced_procs, independent_proc_chances)
    }

    fn view(&mut self, obj: &Bound<'py, PyAny>) -> PyResult<usize> {
        let ptr = obj.as_ptr() as usize;
        if let Some(&i) = self.stats_by_ptr.get(&ptr) {
            return Ok(i);
        }
        for attr in UNSUPPORTED_ATTRS {
            if let Some(v) = opt_attr(obj, attr)? {
                if v.is_truthy()? {
                    return Err(Self::unsupported(attr));
                }
            }
        }
        let damage_types = self.vector_from(&obj.getattr("damage_types")?)?;
        let native_forced_procs = self.vector_from(&obj.getattr("native_forced_procs")?)?;
        let independent_proc_chances = self.vector_from(&obj.getattr("independent_proc_chances")?)?;
        let bow_draw = match opt_attr(obj, "_bow_draw")? {
            Some(v) => Some(v.extract::<f64>()?),
            None => None,
        };
        let charge_time = match opt_attr(obj, "_charge_time")? {
            Some(v) => v.extract::<f64>()?,
            None => 0.0,
        };
        let requires_full_ammo = match opt_attr(obj, "_requires_full_ammo")? {
            Some(v) => v.is_truthy()?,
            None => false,
        };
        let core = self.core_from(obj, &damage_types, &native_forced_procs, &independent_proc_chances)?;
        let s = Stats {
            obj: obj.clone().unbind(),
            core,
            magazine: f(obj, "magazine")?,
            ammo_cost: f(obj, "ammo_cost")?,
            fire_rate: f(obj, "fire_rate")?,
            reload_time: f(obj, "reload_time")?,
            multishot: f(obj, "multishot")?,
            continuous: b(obj, "continuous")?,
            radial_only: b(obj, "radial_only")?,
            crit_chance: f(obj, "crit_chance")?,
            crit_multiplier: f(obj, "crit_multiplier")?,
            bodyshot_crit_multiplier: f(obj, "bodyshot_crit_multiplier")?,
            weakpoint_crit_chance_bonus: f(obj, "weakpoint_crit_chance_bonus")?,
            base_crit_chance: f(obj, "base_crit_chance")?,
            weakpoint_crit_chance_relative: f(obj, "weakpoint_crit_chance_relative")?,
            status_chance: f(obj, "status_chance")?,
            proc_duration_multiplier: f(obj, "proc_duration_multiplier")?,
            proc_damage_multiplier: f(obj, "proc_damage_multiplier")?,
            damage_types,
            native_forced_procs,
            independent_proc_chances,
            has_crit_procs: b(obj, "crit_proc_chances")?,
            first_shot_damage_bonus: f(obj, "first_shot_damage_bonus")?,
            cold_stack_damage: f(obj, "cold_stack_damage")?,
            base_damage_bracket: f(obj, "base_damage_bracket")?,
            frozen_damage_multiplier: f(obj, "frozen_damage_multiplier")?,
            requires_full_ammo,
            bow_draw,
            charge_time,
            initial_combo: {
                let v = obj.getattr("initial_combo")?;
                if v.is_truthy()? { v.extract::<f64>()? } else { 0.0 }
            },
            heavy_charge_speed: f(obj, "heavy_charge_speed")?,
            combo_duration: f(obj, "combo_duration")?,
            combo_extra_chance: f(obj, "combo_extra_chance")?,
            combo_miss_chance: f(obj, "combo_miss_chance")?,
            heavy_attack_efficiency: f(obj, "heavy_attack_efficiency")?,
            additional: Vec::new(),
            head_only: match opt_attr(obj, "_head_only")? { Some(v) => v.is_truthy()?, None => false },
            impact_delay: match opt_attr(obj, "_impact_delay")? { Some(v) => v.extract::<f64>()?, None => 0.0 },
            lingering: None,
            primary_delay: match opt_attr(obj, "_primary_delay_seconds")? {
                Some(v) if v.is_truthy()? => v.extract::<f64>()?,
                _ => 0.0,
            },
            fixed_radial: match opt_attr(obj, "_fixed_radial")? { Some(v) => v.is_truthy()?, None => false },
            victim_full_crit_chance: f(obj, "victim_full_crit_chance")?,
            victim_full_crit_damage: f(obj, "victim_full_crit_damage")?,
            victim_low_health_multiplier: f(obj, "victim_low_health_multiplier")?,
            ammo_pool_multishot_cost: f(obj, "ammo_pool_multishot_cost")?,
            ammo_pool_damage_bonus: f(obj, "ammo_pool_damage_bonus")?,
            charge_pool_cost: match opt_attr(obj, "_charge_pool_cost")? { Some(v) => v.extract::<f64>()?, None => 1.0 },
            co_bucket: effect_ops(&obj.getattr("co_bucket")?)?,
            co_spec: match opt_attr(obj, "_co_spec")? {
                Some(spec) if !spec.is_none() => self.co_spec_from(&spec)?,
                _ => None,
            },
            slam_damage_ratio: f(obj, "slam_damage_ratio")?,
            incarnon_charge_multiplier: f(obj, "incarnon_charge_multiplier")?,
            stackable: None,
        };
        self.stats.push(s);
        let i = self.stats.len() - 1;
        self.stats_by_ptr.insert(ptr, i);
        // Parts that ride on this view (radial bomblets, a lingering field).
        if let Some(parts) = opt_attr(obj, "_additional_radials")? {
            let mut out = Vec::new();
            for part in parts.try_iter()? {
                out.push(self.view(&part?)?);
            }
            self.stats[i].additional = out;
        }
        if let Some(spec) = opt_attr(obj, "_stackable")? {
            if spec.is_truthy()? {
                let t = spec.cast::<PyTuple>()?;
                let profile = self.stackable_profile(&t.get_item(0)?)?;
                let mut parts = stackable::Parts::default();
                for (name, part) in t.get_item(1)?.cast::<PyDict>()?.iter() {
                    let index = self.view(&part)?;
                    match name.extract::<String>()?.as_str() {
                        "embed" => parts.embed = Some(index),
                        "explosion" => parts.explosion = Some(index),
                        "merge" => parts.merge = Some(index),
                        "singularity" => parts.singularity = Some(index),
                        "child" => parts.child = Some(index),
                        "orbRadial" => parts.orb_radial = Some(index),
                        _ => {}
                    }
                }
                self.stats[i].stackable = Some((profile, parts));
            }
        }
        if let Some(field) = opt_attr(obj, "_lingering")? {
            if field.is_truthy()? {
                let t = field.cast::<PyTuple>()?;
                let part = self.view(&t.get_item(0)?)?;
                let rate: f64 = t.get_item(1)?.extract()?;
                let duration: f64 = t.get_item(2)?.extract()?;
                self.stats[i].lingering = Some((part, rate, duration));
            }
        }
        Ok(i)
    }

    /// Push the next tick of DoT instance `i`, if any is left.
    fn next_tick(&mut self, i: usize) {
        let Some(chain) = self.tick_chains.get_mut(&i) else { return };
        let k = chain.next;
        let event = Event { t: pmax(0.0, chain.t + (chain.first + k as i64) as f64), seq: chain.base + 1 + k as u64,
                            kind: Kind::IndependentDot(i), gen: chain.gen };
        chain.next += 1;
        if chain.next >= chain.count {
            self.tick_chains.remove(&i);
        }
        self.heap.push(event);
    }

    fn push(&mut self, t: f64, kind: Kind, gen: Option<i64>) {
        if t < self.window + 1e-9 {
            self.seq += 1;
            self.heap.push(Event { t: pmax(0.0, t), seq: self.seq, kind, gen });
        }
    }

    // ── status bookkeeping ──────────────────────────────────────────────

    fn count(&mut self, d: D) -> f64 {
        if d == FIRE {
            return self.heat_chains.count();
        }
        if d == FREEZE && self.frozen_until > self.current_time {
            return 10.0;
        }
        if d == GAS {
            let a = psum(self.gas_procs.iter().map(|&i| self.dots[i].count * stack_alive(&self.dots[i])));
            let b = match self.states.get(&d) { Some(r) => psum(r.iter().map(|x| x.1)), None => psum(std::iter::empty()) };
            return a + b;
        }
        if d == EXPLOSION {
            return psum(self.blast_procs.iter().map(|&i| self.blasts[i].count));
        }
        if let Some(p) = pooled_index(d) {
            return self.pooled[p].stats().1;
        }
        let cap = if d == FREEZE && self.pools[0] > 0.0 { 4.0 } else { cap_of(d).unwrap_or(f64::INFINITY) };
        let total = match self.states.get(&d) { Some(r) => psum(r.iter().map(|x| x.1)), None => psum(std::iter::empty()) };
        pmin(total, cap)
    }

    fn live_crit(&mut self) -> (f64, f64) {
        let cold = self.count(FREEZE);
        let cd = if self.frozen_until > self.current_time {
            1.0
        } else if cold < 1.0 {
            0.1 * cold
        } else {
            0.1 + 0.05 * (cold - 1.0)
        };
        (0.05 * self.count(PUNCTURE), cd)
    }

    fn clean(&mut self, t: f64) {
        let _timer = crate::counters::Timer::start(crate::counters::CLEAN);
        if self.frozen_until >= 0.0 && t >= self.frozen_until - 1e-9 {
            let end = self.frozen_until + 6.0 * self.frozen_scale_value();
            let mut rows = VecDeque::new();
            rows.push_back((end, 3.0));
            self.states.insert(FREEZE, rows);
            self.presence.entry(FREEZE).or_default().add(end, 0.0);
            self.frozen_until = -1.0;
        }
        while let Some(&front) = self.gas_procs.first() {
            if self.dots[front].end < t - 1e-9 {
                self.gas_procs.remove(0);
            } else {
                break;
            }
        }
        for rows in self.states.values_mut() {
            while let Some(&(end, _)) = rows.front() {
                if end < t - 1e-9 {
                    rows.pop_front();
                } else {
                    break;
                }
            }
        }
        for pool in self.pooled.iter_mut() {
            if pool.is_live() {
                pool.expire(t);
            }
        }
        if self.heat_chains.active() {
            self.heat_chains.expire(t);
            if !self.heat_chains.active() {
                self.heat_token += 1;
            }
        } else {
            self.heat_chains.expire(t);
        }
        for q in self.sources.iter_mut() {
            if q.duration != 0.0 && q.stacks != 0.0 && t >= q.expires {
                if q.decay == "lose_one_and_reset" {
                    let missed = 1 + trunc_i((t - q.expires) / q.duration);
                    q.stacks = pmax(0.0, q.stacks - missed as f64);
                    q.expires += missed as f64 * q.duration;
                } else if q.decay != "per-stack" {
                    q.stacks = 0.0;
                }
            }
            if q.decay == "per-stack" {
                q.expiries.retain(|x| x.0 > t);
                q.stacks = psum(q.expiries.iter().map(|x| x.1));
            }
        }
    }

    fn frozen_scale_value(&self) -> f64 {
        self.frozen_scale
    }

    fn heat_strip(&mut self, t: f64) -> f64 {
        self.heat_chains.strip(t)
    }

    fn armour_factor(&mut self, t: f64) -> f64 {
        let rest = self.armour_base * (1.0 - self.elemental_armour_strip) * (1.0 - self.heat_strip(t))
            * (1.0 - self.puncture_strip);
        let version = self.pooled[1].version;
        if let Some((v, r, value)) = self.armour_view {
            if v == version && r == rest.to_bits() {
                return value;
            }
        }
        let dist = self.pooled[1].distribution().clone();
        let mut s = PySum::new();
        for (k, w) in dist.iter().enumerate() {
            if *w > 0.0 {
                let strip = if k == 0 { 0.0 } else { pmin(0.26 + 0.06 * (k as f64 - 1.0), 0.8) };
                s.add(*w * (1.0 - armour_reduction(rest * (1.0 - strip))));
            }
        }
        let value = s.value();
        self.armour_view = Some((version, rest.to_bits(), value));
        value
    }

    fn vulnerability(&mut self, d: D) -> f64 {
        let (present, n) = self.pooled[pooled_index(d).unwrap()].stats();
        pmin(1.0 + 0.75 * present + 0.25 * n, 4.25)
    }

    // ── triggers ────────────────────────────────────────────────────────

    fn signal(&mut self, kind: &str, t: f64, weight: f64) {
        let _timer = crate::counters::Timer::start(crate::counters::SIGNAL);
        for i in 0..self.sources.len() {
            let q = &mut self.sources[i];
            if q.actor_only && !self.actor_signal {
                continue;
            }
            if q.toggle_on.as_deref() == Some(kind) && q.per_event != 0.0 {
                q.stacks = 1.0 - q.stacks;
                q.expires = f64::INFINITY;
                continue;
            }
            let gate_probability = match q.victim_proc_type {
                Some(d) => self.victim_before.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0),
                None => 1.0,
            };
            if gate_probability == 0.0 {
                continue;
            }
            if q.reset_on.iter().any(|r| r == kind) && q.per_event != 0.0 {
                q.stacks = 0.0;
                q.expires = f64::INFINITY;
                q.expiries.clear();
                q.progress.clear();
            }
            if q.kind.as_deref() != Some(kind) {
                continue;
            }
            let required = pmax(q.required_count, 1.0);
            let delta;
            if required > 1.0 {
                if let Some(rt) = q.required_time {
                    while let Some(&(when, _)) = q.progress.front() {
                        if when < t - rt {
                            q.progress.pop_front();
                        } else {
                            break;
                        }
                    }
                }
                q.progress.push_back((t, weight * gate_probability));
                let completed = floor_i((psum(q.progress.iter().map(|x| x.1)) + 1e-9) / required);
                let mut consumed = completed as f64 * required;
                while consumed > 1e-9 {
                    let (when, n) = match q.progress.pop_front() {
                        Some(x) => x,
                        None => break,
                    };
                    if n > consumed {
                        q.progress.push_front((when, n - consumed));
                    }
                    consumed -= n;
                }
                delta = completed as f64 * q.per_event;
            } else {
                delta = weight * gate_probability * q.per_event;
            }
            if delta <= 0.0 {
                continue;
            }
            if q.decay == "per-stack" {
                q.expiries.push((t + q.duration, delta));
                let mut excess = psum(q.expiries.iter().map(|x| x.1)) - q.max_stacks;
                while excess > 1e-9 && !q.expiries.is_empty() {
                    let (end, n) = q.expiries[0];
                    let removed = pmin(n, excess);
                    excess -= removed;
                    if removed >= n {
                        q.expiries.remove(0);
                    } else {
                        q.expiries[0] = (end, n - removed);
                    }
                }
            }
            q.stacks = pmin(q.max_stacks, q.stacks + delta);
            q.expires = if q.duration != 0.0 { t + q.duration } else { f64::INFINITY };
        }
    }

    fn consecutive_heads(&mut self, probability: f64) {
        for q in self.sources.iter_mut() {
            if q.kind.as_deref() != Some("on-consecutive-headshot") || q.per_event == 0.0 {
                continue;
            }
            let minimum = if q.minimum_consecutive != 0 { q.minimum_consecutive } else { 1 };
            let cap = minimum + trunc_i(q.max_stacks) - 1;
            let before = q.run_distribution.clone().unwrap_or_else(|| {
                let mut m = FxIndexMap::default();
                m.insert(0i64, 1.0);
                m
            });
            let mut after: FxIndexMap<i64, f64> = FxIndexMap::default();
            after.insert(0, 1.0 - probability);
            for (run, weight) in before.iter() {
                let n = (run + 1).min(cap);
                let prev = *after.get(&n).unwrap_or(&0.0);
                after.insert(n, prev + weight * probability);
            }
            q.stacks = psum(after.iter().map(|(run, w)| (run - minimum + 1).max(0) as f64 * *w));
            q.run_distribution = Some(after);
            q.expires = f64::INFINITY;
        }
    }

    // ── model / packets ─────────────────────────────────────────────────

    fn model(&mut self, t: f64) -> PyResult<(usize, Option<usize>)> {
        let _timer = crate::counters::Timer::start(crate::counters::MODEL);
        let live_types = if self.live_types_enabled {
            let keys: Vec<D> = self.presence.keys().copied().collect();
            let mut s = PySum::new();
            for d in keys {
                s.add(self.presence.get_mut(&d).unwrap().probability(t));
            }
            s.value()
        } else {
            0.0
        };
        let mut stacks: Vec<u64> = std::mem::take(&mut self.model_key);
        stacks.clear();
        stacks.push(self.form as u64);
        stacks.extend(self.sources.iter().map(|q| q.stacks.to_bits()));
        // Melee: combo-tier stacks and the heavy flag join the key, sorted by
        // name like the reference's sorted(extra_stacks.items()).
        let mut extra: Vec<(String, f64, PyObject)> = Vec::new();
        if let Some(spec) = &self.melee {
            let tier = spec.tier(self.melee_count) as f64;
            for (obj, name, cap) in &spec.tier_keys {
                extra.push((name.clone(), pmin(tier, *cap), obj.clone_ref(self.py)));
            }
        }
        if let (Some(_), true) = (self.onos, self.form != BASE) {
            let (power, hits, beam) = self.onos_values(t);
            stacks.push(u64::MAX - 1);
            stacks.push(power as u64);
            stacks.push(hits.to_bits());
            stacks.push(beam.to_bits());
        }
        let mut sorted: Vec<(String, u64)> = extra.iter().map(|(n, v, _)| (n.clone(), v.to_bits())).collect();
        if self.heavy_flag {
            sorted.push(("__heavy".to_string(), 1));
        }
        sorted.sort();
        for (name, bits) in &sorted {
            stacks.push(u64::MAX);
            for byte in name.bytes() {
                stacks.push(byte as u64);
            }
            stacks.push(*bits);
        }
        let key = (stacks, live_types.to_bits(), self.last_round);
        if let Some(&hit) = self.model_cache.get(&key) {
            self.model_key = key.0;
            return Ok(hit);
        }
        self.model_at(key.0, extra, live_types)
    }

    fn model_at(&mut self, stacks: Vec<u64>, extra: Vec<(String, f64, PyObject)>, live_types: f64)
        -> PyResult<(usize, Option<usize>)> {
        let key = (stacks, live_types.to_bits(), self.last_round);
        if let Some(&hit) = self.model_cache.get(&key) {
            return Ok(hit);
        }
        // A fractional live count only scales the CO bucket: derive it from
        // the count it rounds up to (manual_combat.resolve does the same).
        let ceil = live_types.ceil();
        // Onos scales the resolved damage after apply_mods: no CO variants.
        if self.live_types_enabled && self.onos.is_none() && ceil >= 1.0 && live_types != ceil && ceil.is_finite() {
            let template_extra = extra.iter().map(|(n, v, o)| (n.clone(), *v, o.clone_ref(self.py))).collect();
            let (active, radial) = self.model_at(key.0.clone(), template_extra, ceil)?;
            if let Some(a) = self.vary(active, live_types, ceil) {
                let r = match radial {
                    Some(r) => self.vary(r, live_types, ceil).map(Some),
                    None => Some(None),
                };
                if let Some(r) = r {
                    self.model_cache.insert(key, (a, r));
                    return Ok((a, r));
                }
            }
        }
        let py = self.py;
        let stacks_dict = PyDict::new(py);
        for q in &self.sources {
            stacks_dict.set_item(q.id.bind(py), q.stacks)?;
        }
        let (power, hits, beam) = self.onos_values(self.current_time);
        stacks_dict.set_item("__onosPower", power)?;
        stacks_dict.set_item("__onosHits", hits)?;
        stacks_dict.set_item("__onosBeamSeconds", beam)?;
        for (_, value, obj) in &extra {
            stacks_dict.set_item(obj.bind(py), *value)?;
        }
        if self.heavy_flag {
            stacks_dict.set_item("__heavy", true)?;
        }
        let live: PyObject = if self.live_types_enabled {
            live_types.into_pyobject(py)?.into_any().unbind()
        } else {
            0i64.into_pyobject(py)?.into_any().unbind()
        };
        let started = std::time::Instant::now();
        let form = match self.form { BASE => "base", INCARNON => "incarnon", _ => "selected" };
        let result = self.resolver.call1((form, stacks_dict, live, self.last_round))?;
        let resolved = std::time::Instant::now();
        crate::counters::add(crate::counters::RESOLVE, (resolved - started).as_nanos() as u64);
        let tuple = result.downcast::<PyTuple>()?;
        let active = self.view(&tuple.get_item(0)?)?;
        let radial_obj = tuple.get_item(1)?;
        let radial = if radial_obj.is_none() { None } else { Some(self.view(&radial_obj)?) };
        crate::counters::add(crate::counters::VIEW, resolved.elapsed().as_nanos() as u64);
        self.model_cache.insert(key, (active, radial));
        Ok((active, radial))
    }

    fn packet(&mut self, st: usize, aim: f64) -> PyResult<PacketKey> {
        let _timer = crate::counters::Timer::start(crate::counters::PACKET);
        if self.stats[st].fixed_radial {
            return Ok(self.raw_packet(st, 0.0));
        }
        let mut st = st;
        let undamaged = (self.pools[1] - self.full[1]).abs() < 1e-7 && (self.pools[2] - self.full[2]).abs() < 1e-7;
        let (vfcc, vfcd) = (self.stats[st].victim_full_crit_chance, self.stats[st].victim_full_crit_damage);
        if undamaged && (vfcc != 0.0 || vfcd != 0.0) {
            st = self.derive(st, 3, 0.0, |v| {
                v.crit_chance += vfcc;
                v.crit_multiplier += vfcd;
                v.core.crit_chance = v.crit_chance;
                v.core.crit_multiplier = v.crit_multiplier;
            });
        }
        let low = self.stats[st].victim_low_health_multiplier;
        if self.full[2] > 0.0 && self.pools[2] < self.full[2] * 0.5 && low != 1.0 {
            st = self.derive(st, 4, 0.0, |v| {
                for e in v.core.damage_types.iter_mut() {
                    e.1 *= low;
                }
                v.damage_types = v.core.damage_types.clone();
            });
        }
        let s = &self.stats[st];
        let (radial_only, csd, bracket, frozen_mult) =
            (s.radial_only, s.cold_stack_damage, s.base_damage_bracket, s.frozen_damage_multiplier);
        let (mut puncture, mut cold) = self.live_crit();
        if radial_only {
            puncture = 0.0;
            cold = 0.0;
        }
        let mut shiver = 1.0;
        let mut frozen = 1.0;
        if cold != 0.0 && (csd != 0.0 || frozen_mult != 1.0) {
            let stacks_cold = self.count(FREEZE);
            if csd != 0.0 && bracket > 0.0 {
                shiver = (bracket + csd * pmin(stacks_cold, 10.0)) / bracket;
            }
            if self.frozen_until > self.current_time || stacks_cold >= 10.0 - 1e-9 {
                frozen = frozen_mult;
            }
        }
        if self.enervate.is_some() {
            return self.enervate_packet(st, aim, puncture, cold, shiver, frozen);
        }
        let fast = puncture == 0.0 && cold == 0.0;
        let key = if fast {
            (st, aim.to_bits(), 0, 0, 0, 1, 0)
        } else {
            (st, aim.to_bits(), puncture.to_bits(), cold.to_bits(), shiver.to_bits(), frozen.to_bits(), 0)
        };
        if !self.packets.contains_key(&key) {
            let core = &self.stats[st].core;
            let (vector, procs, rows, non) = if fast {
                tables::attack_data(core, aim, &self.tables)
            } else {
                tables::crit_view_packet(core, aim, puncture, cold, shiver, frozen, &self.tables)
            };
            let packet = Packet {
                vector,
                procs,
                rows: rows.into_iter().map(|(d, r)| (d, Row {
                    duration: r.duration, seed: r.seed, accumulator: r.accumulator, shared: r.shared,
                    coefficient: r.coefficient,
                })).collect(),
                non: non.into_iter().collect(),
            };
            self.packets.insert(key, Rc::new(packet));
        }
        Ok(key)
    }

    /// combat_replay.packet under Enervate: the crit views of every stack
    /// count, weighted by the pre-hit damage distribution.
    fn enervate_packet(&mut self, st: usize, aim: f64, puncture: f64, cold: f64, shiver: f64, frozen: f64)
        -> PyResult<PacketKey> {
        let weights = self.enervate.as_ref().unwrap().damage_marginal();
        let bits: Vec<(i64, u64)> = weights.iter().map(|(s, w)| (*s, w.to_bits())).collect();
        let next = self.enervate_weights.len() as u64 + 1;
        let id = *self.enervate_weights.entry(bits).or_insert(next);
        let key = (st, aim.to_bits(), puncture.to_bits(), cold.to_bits(), shiver.to_bits(), frozen.to_bits(), id);
        if self.packets.contains_key(&key) {
            return Ok(key);
        }
        let mut vector: Vector = Vec::new();
        let mut procs: Vector = Vec::new();
        let mut rows: FxIndexMap<D, Row> = FxIndexMap::default();
        let mut non: FxIndexMap<D, f64> = FxIndexMap::default();
        let mut seed_sums: Vector = Vec::new();
        let mut non_sums: Vector = Vec::new();
        for &(stacks, weight) in &weights {
            let vkey = (st, aim.to_bits(), stacks, puncture.to_bits(), cold.to_bits(), shiver.to_bits(), frozen.to_bits());
            let view = match self.enervate_views.get(&vkey) {
                Some(v) => v.clone(),
                None => {
                    let core = tables::crit_view(&self.stats[st].core, stacks as f64 * 0.1, puncture, cold, shiver, frozen);
                    let (v, p, r, n) = tables::attack_data(&core, aim, &self.tables);
                    let packet = Rc::new(Packet {
                        vector: v,
                        procs: p,
                        rows: r.into_iter().map(|(d, r)| (d, Row {
                            duration: r.duration, seed: r.seed, accumulator: r.accumulator, shared: r.shared,
                            coefficient: r.coefficient,
                        })).collect(),
                        non: n.into_iter().collect(),
                    });
                    self.enervate_views.insert(vkey, packet.clone());
                    packet
                }
            };
            for &(k, value) in &view.vector {
                ordered_add(&mut vector, k, weight * value);
            }
            for &(k, value) in &view.procs {
                ordered_add(&mut procs, k, weight * value);
            }
            for (&k, row) in &view.rows {
                rows.insert(k, *row);
                let pk = view.procs.iter().find(|e| e.0 == k).map(|e| e.1).unwrap_or(0.0);
                ordered_add(&mut seed_sums, k, weight * pk * row.seed);
            }
            for (&k, &per) in &view.non {
                non.insert(k, per);
                let pk = view.procs.iter().find(|e| e.0 == k).map(|e| e.1).unwrap_or(0.0);
                ordered_add(&mut non_sums, k, weight * pk * per);
            }
        }
        let total = |d: D| procs.iter().find(|e| e.0 == d).map(|e| e.1).unwrap_or(0.0);
        for (k, row) in rows.iter_mut() {
            let p = total(*k);
            let sum = seed_sums.iter().find(|e| e.0 == *k).map(|e| e.1).unwrap_or(0.0);
            row.seed = if p != 0.0 { sum / p } else { 0.0 };
        }
        for (k, per) in non.iter_mut() {
            let p = total(*k);
            let sum = non_sums.iter().find(|e| e.0 == *k).map(|e| e.1).unwrap_or(0.0);
            *per = if p != 0.0 { sum / p } else { 0.0 };
        }
        self.packets.insert(key, Rc::new(Packet { vector, procs, rows, non }));
        Ok(key)
    }

    /// combat_replay.enervate_hit: advance the state by this direct hit's
    /// chance of a big (orange or red) crit at each stack count.
    fn enervate_hit(&mut self, st: usize, t: f64, puncture: f64, aim: f64) {
        let Some(en) = self.enervate.as_ref() else { return };
        // Natively the form is never 'base' (no Incarnon cycle), so an
        // ignored alternate fire never gains.
        if self.stats[st].multishot <= 0.0 || (en.ignore_selected && self.form != BASE) {
            return;
        }
        let s = &self.stats[st];
        let weak = s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative;
        let promotion = s.core.double_crit_chance;
        let pellets = if s.continuous { 1.0 } else { s.multishot };
        let probabilities: Vec<(i64, f64)> = en
            .marginal()
            .into_iter()
            .map(|(stacks, _)| {
                let cc = pmax(0.0, s.crit_chance + stacks as f64 * 0.1 + puncture);
                let mut p = (1.0 - aim) * big_crit_probability(cc * s.bodyshot_crit_multiplier, promotion);
                p += aim * big_crit_probability(cc + weak, promotion);
                (stacks, any_probability(p, pellets))
            })
            .collect();
        self.enervate.as_mut().unwrap().advance(t, Some(&probabilities));
    }

    /// attack_data(st, aim) with no crit view (lingering ticks, fixed radials).
    fn raw_packet(&mut self, st: usize, aim: f64) -> PacketKey {
        let key = (st, aim.to_bits(), 0, 0, 0, 1, 0);
        if !self.packets.contains_key(&key) {
            let (vector, procs, rows, non) = tables::attack_data(&self.stats[st].core, aim, &self.tables);
            let packet = Packet {
                vector,
                procs,
                rows: rows.into_iter().map(|(d, r)| (d, Row {
                    duration: r.duration, seed: r.seed, accumulator: r.accumulator, shared: r.shared,
                    coefficient: r.coefficient,
                })).collect(),
                non: non.into_iter().collect(),
            };
            self.packets.insert(key, Rc::new(packet));
        }
        key
    }

    fn packet_from(&mut self, result: &Bound<'py, PyAny>) -> PyResult<Packet> {
        let t = result.downcast::<PyTuple>()?;
        let vector = self.vector_from(&t.get_item(0)?)?;
        let procs = self.vector_from(&t.get_item(1)?)?;
        let mut rows = FxIndexMap::default();
        for (k, v) in t.get_item(2)?.downcast::<PyDict>()?.iter() {
            let name: String = k.extract()?;
            let r = v.downcast::<PyDict>()?;
            rows.insert(
                self.types.id(&name),
                Row {
                    duration: get_f(r, "durationSeconds", 0.0)?,
                    seed: get_f(r, "seedPerSecondPerProc", 0.0)?,
                    accumulator: get_f(r, "accumulatorPerSecondPerAttack", 0.0)?,
                    shared: truthy(r, "accumulatorSharedGroup")?,
                    coefficient: get_f(r, "coefficient", 0.0)?,
                },
            );
        }
        let mut non = FxIndexMap::default();
        for (k, v) in t.get_item(3)?.downcast::<PyDict>()?.iter() {
            let name: String = k.extract()?;
            non.insert(self.types.id(&name), get_f(v.downcast::<PyDict>()?, "perProc", 0.0)?);
        }
        Ok(Packet { vector, procs, rows, non })
    }

    /// A stats view derived natively (spool pellets, first-shot bonus), memoised
    /// by what it was derived from: the reference makes a fresh copy per
    /// shot, whose tables are a pure function of the same values.
    fn derive(&mut self, st: usize, kind: u8, param: f64, change: impl FnOnce(&mut Stats)) -> usize {
        let key = (st, kind, param.to_bits());
        if let Some(&i) = self.derived.get(&key) {
            return i;
        }
        let mut view = self.stats[st].clone_with(self.py);
        change(&mut view);
        self.stats.push(view);
        let i = self.stats.len() - 1;
        self.derived.insert(key, i);
        i
    }

    fn hit_spec(&mut self, id: i64) -> PyResult<Rc<HitSpec>> {
        let i = id as usize;
        if let Some(Some(spec)) = self.hit_specs.get(i) {
            return Ok(spec.clone());
        }
        let r = self.helper.call_method1("hit_spec", (id,))?;
        let t = r.cast::<PyTuple>()?;
        let opt = |v: Bound<'py, PyAny>| -> PyResult<Option<f64>> {
            Ok(if v.is_none() { None } else { Some(v.extract::<f64>()?) })
        };
        let target = t.get_item(4)?;
        let duplicate = t.get_item(11)?;
        let mut extra = Vec::new();
        for d in t.get_item(8)?.try_iter()? {
            extra.push(self.types.id(&d?.extract::<String>()?));
        }
        let spec = Rc::new(HitSpec {
            atten: t.get_item(0)?.extract()?,
            slam: t.get_item(1)?.extract()?,
            combo_multiplier: t.get_item(2)?.extract()?,
            pct: self.vector_from(&t.get_item(3)?)?,
            target: if target.is_none() { None } else { Some(self.types.id(&target.extract::<String>()?)) },
            crit_chance: opt(t.get_item(5)?)?,
            crit_multiplier: opt(t.get_item(6)?)?,
            can_crit: t.get_item(7)?.extract()?,
            extra_procs: extra,
            proc_atten: t.get_item(9)?.extract()?,
            radial: t.get_item(10)?.extract()?,
            duplicate: if duplicate.is_none() { None } else { Some(duplicate.extract::<(f64, f64)>()?) },
        });
        if self.hit_specs.len() <= i {
            self.hit_specs.resize(i + 1, None);
        }
        self.hit_specs[i] = Some(spec.clone());
        Ok(spec)
    }

    /// `melee_sequence.apply_hit` plus Melee Duplicate (native_replay's
    /// `melee_apply`), as a derived view.
    fn melee_apply(&mut self, st: usize, id: i64, heavy_multiplier: f64) -> PyResult<usize> {
        let key = (st, id, heavy_multiplier.to_bits());
        if let Some(&hit) = self.applied.get(&key) {
            return Ok(hit);
        }
        let hit = self.hit_spec(id)?;
        let mut v = self.stats[st].clone_with(self.py);
        let mut factor = hit.atten;
        if hit.slam {
            let ratio = v.slam_damage_ratio;
            factor *= if ratio != 0.0 { ratio } else { 1.0 };
        }
        if hit.combo_multiplier {
            factor *= heavy_multiplier;
        }
        let mut damage: Vector = v.damage_types.iter()
            .map(|&(k, x)| (k, x * factor * hit.pct.iter().find(|e| e.0 == k).map(|e| e.1).unwrap_or(1.0)))
            .collect();
        if let Some(target) = hit.target {
            let mut moved = PySum::new();
            for name in ["DT_IMPACT", "DT_PUNCTURE", "DT_SLASH"] {
                let d = self.types.id(name);
                let popped = match damage.iter().position(|e| e.0 == d) {
                    Some(i) => damage.remove(i).1,
                    None => 0.0,
                };
                moved.add(popped);
            }
            let moved = moved.value();
            match damage.iter_mut().find(|e| e.0 == target) {
                Some(e) => e.1 += moved,
                None => damage.push((target, 0.0 + moved)),
            }
        }
        let mut crit_chance = v.crit_chance;
        let mut crit_multiplier = v.crit_multiplier;
        if let Some(f) = hit.crit_chance {
            crit_chance *= f;
        }
        if let Some(f) = hit.crit_multiplier {
            crit_multiplier *= f;
        }
        if !hit.can_crit {
            crit_chance = 0.0;
        }
        let mut forced = v.native_forced_procs.clone();
        for &d in &hit.extra_procs {
            match forced.iter_mut().find(|e| e.0 == d) {
                Some(e) => e.1 += 1.0,
                None => forced.push((d, 0.0 + 1.0)),
            }
        }
        v.drop_private();
        v.damage_types = damage.clone();
        v.core.damage_types = damage;
        v.core.dot_base_damage = v.core.dot_base_damage.map(|x| x * factor);
        v.crit_chance = crit_chance;
        v.core.crit_chance = crit_chance;
        v.crit_multiplier = crit_multiplier;
        v.core.crit_multiplier = crit_multiplier;
        v.status_chance *= hit.proc_atten;
        v.core.status_chance = v.status_chance;
        v.native_forced_procs = forced.clone();
        v.core.native_forced_procs = forced;
        v.multishot = 1.0;
        v.radial_only = hit.radial;
        v.core.radial_only = hit.radial;
        if let Some((chance, uptime)) = hit.duplicate {
            let c = pmin(pmax(v.crit_chance, 0.0), 2.0);
            let yellow = if c < 1.0 { c } else { 2.0 - c };
            let f = 1.0 + chance * uptime * yellow;
            if f != 1.0 {
                v.multishot *= f;
                v.drop_private();
            }
        }
        v.core.multishot = v.multishot;
        self.stats.push(v);
        let i = self.stats.len() - 1;
        self.applied.insert(key, i);
        Ok(i)
    }

    fn melee_next(&mut self, speed: f64, charge: f64) -> PyResult<(MeleeHit, f64)> {
        let r = self.helper.call_method1("melee_next", (speed, charge))?;
        let t = r.cast::<PyTuple>()?;
        Ok((
            MeleeHit {
                id: t.get_item(0)?.extract()?,
                heavy: t.get_item(2)?.extract()?,
                combo_hits: t.get_item(3)?.extract()?,
                consumes: t.get_item(4)?.extract()?,
            },
            t.get_item(1)?.extract()?,
        ))
    }

    fn spread(&mut self, st: usize, aim: f64) -> f64 {
        let key = (st, aim.to_bits());
        if let Some(&v) = self.spreads.get(&key) {
            return v;
        }
        let s = &self.stats[st];
        let cm = pmax(s.crit_multiplier, 1.0) - 1.0;
        let weak = s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative;
        let mut mean = 0.0;
        let mut square = 0.0;
        for (weight, chance) in [(1.0 - aim, s.crit_chance * s.bodyshot_crit_multiplier), (aim, s.crit_chance + weak)] {
            if weight <= 0.0 {
                continue;
            }
            let chance = pmax(0.0, chance);
            let fr = chance - chance.floor();
            let m = 1.0 + chance * cm;
            mean += weight * m;
            square += weight * (m * m + fr * (1.0 - fr) * cm * cm);
        }
        let value = if mean <= 0.0 {
            0.0
        } else {
            let pellets = if s.continuous { 1.0 } else { pmax(s.multishot, 1.0) };
            pmax(0.0, square / (mean * mean) - 1.0) / pellets
        };
        self.spreads.insert(key, value);
        value
    }

    /// "proc-<type>", built once per type.
    fn proc_signal(&mut self, d: D) -> Rc<str> {
        let i = d as usize;
        if self.proc_names.len() <= i {
            self.proc_names.resize(i + 1, None);
        }
        if let Some(name) = &self.proc_names[i] {
            return name.clone();
        }
        let name: Rc<str> = Rc::from(format!("proc-{}", self.types.name(d)));
        self.proc_names[i] = Some(name.clone());
        name
    }

    fn no_status_probability(&mut self, st: usize, d: D, aim: f64) -> PyResult<f64> {
        let key = (st, d, aim.to_bits());
        if let Some(&hit) = self.no_status.get(&key) {
            return Ok(hit);
        }
        let value = self.no_status_probability_uncached(st, d, aim);
        self.no_status.insert(key, value);
        Ok(value)
    }

    /// A pure function of the view, the type and the aim (forced procs are
    /// fixed for the replay), so it is memoised per replay.
    fn no_status_probability_uncached(&self, st: usize, d: D, aim: f64) -> f64 {
        let crit = if self.stats[st].has_crit_procs && self.stats[st].core.crit_proc_chances.iter().any(|x| x.0 == d) {
            let core = &self.stats[st].core;
            (1.0 - aim) * tables::crit_proc_probability(core, d, false) + aim * tables::crit_proc_probability(core, d, true)
        } else {
            0.0
        };
        let s = &self.stats[st];
        let weights: Vec<(D, f64)> = s.damage_types.iter().map(|(k, v)| (*k, pmax(*v, 0.0))).collect();
        let total = psum(weights.iter().map(|x| x.1));
        let share = if total != 0.0 {
            weights.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0) / total
        } else {
            0.0
        };
        let chance = pmax(s.status_chance, 0.0);
        let multishot = pmax(s.multishot, 0.0);
        let forced_per = s.native_forced_procs.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0);
        let independent = pmax(s.independent_proc_chances.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0), 0.0);
        let independent = 1.0 - (1.0 - pmin(1.0, independent)) * (1.0 - crit);
        let continuous = s.continuous;
        let zero_rolls = |chance: f64| -> f64 {
            let whole = chance.floor();
            pow(1.0 - share, whole) * (1.0 - (chance - whole) * share)
        };
        let zero_for_pellets = |pellets: i64| -> f64 {
            if pellets <= 0 {
                return 1.0;
            }
            let instances = if continuous { 1.0 } else { pellets as f64 };
            let natural = if continuous {
                zero_rolls(chance * pellets as f64)
            } else {
                pow(zero_rolls(chance), pellets as f64)
            };
            natural * pow(1.0 - pmin(1.0, forced_per), instances) * pow(1.0 - pmin(1.0, independent), instances)
        };
        let whole = floor_i(multishot);
        let fraction = multishot - whole as f64;
        let zero = (1.0 - fraction) * zero_for_pellets(whole) + fraction * zero_for_pellets(whole + 1);
        let extra = pmax(self.forced_procs.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0), 0.0);
        pmin(1.0, pmax(0.0, zero * (1.0 - pmin(1.0, extra))))
    }

    // ── damage ──────────────────────────────────────────────────────────

    fn faction_delta(&self, d: D) -> f64 {
        self.faction_deltas.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0)
    }

    fn health_value(&mut self, d: D, raw: f64, t: f64) -> f64 {
        let mut mult = pmax(0.0, 1.0 + self.faction_delta(d)) * self.vulnerability(VIRAL);
        if !self.armour_bypass.contains(&d) {
            mult *= self.armour_factor(t);
        }
        raw * mult
    }

    fn resume_time(&mut self, t: f64) -> PyResult<Option<f64>> {
        let (active, _) = self.model(t)?;
        let a = &self.stats[active];
        if self.shot_in_progress && a.magazine > 0.0 && !self.infinite_ammo && self.ammo - pmax(a.ammo_cost, 0.0) <= 1e-9 {
            return Ok(Some(t + 1.0 / pmax(a.fire_rate, 1e-9) + a.reload_time));
        }
        let mut best: Option<f64> = None;
        for e in self.heap.iter() {
            if matches!(e.kind, Kind::Fire | Kind::ReloadComplete(_)) {
                best = Some(match best {
                    None => e.t,
                    Some(b) => pmin(b, e.t),
                });
            }
        }
        Ok(best)
    }

    fn magnetic_break(&mut self, t: f64, pool_index: usize) -> PyResult<()> {
        let stacks = pmin(self.count(MAGNETIC), 10.0);
        if stacks <= 0.0 {
            return Ok(());
        }
        let (active, _) = self.model(t)?;
        let multiplier = pmax(self.stats[active].proc_damage_multiplier, 0.0);
        let per_tick = self.full[pool_index] * 0.03 * stacks * pow(multiplier, 2.0) / 6.0;
        self.magnetic_breaks.push((t, pool_index, stacks, per_tick, self.gen));
        let probability = match self.presence.get_mut(&MAGNETIC) {
            Some(p) => p.probability(t),
            None => 1.0,
        };
        self.states.entry(ELECTRICITY).or_default().push_back((t + 6.0, probability));
        self.presence.entry(ELECTRICITY).or_default().add(t + 6.0, 1.0 - probability);
        let prev = self.proc_counts.get(&ELECTRICITY).copied();
        self.proc_counts.insert(ELECTRICITY, match prev {
            Some(v) => v + probability,
            None => 0.0 + probability,
        });
        for tick in 0..6 {
            self.push(t + tick as f64, Kind::Dot(ELECTRICITY, per_tick, t + 6.0), Some(self.gen));
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn take(&mut self, vector: &Vector, t: f64, source: usize, weak_kill: WeakKill, cv2: f64, extra: bool) -> PyResult<bool> {
        let _timer = crate::counters::Timer::start(crate::counters::TAKE);
        if let Some((alignment, _, _)) = self.onos {
            if self.onos_crits && self.form != BASE && (self.onos_ticks as f64) < alignment
                && (source == DOT || source == NONDOT) && vector.iter().any(|e| e.1 > 0.0)
            {
                self.onos_hits = pmin(50.0, self.onos_hits + 1.0);
            }
        }
        let mut left = 1.0;
        let mut applied = 0.0;
        let mut earlier_hit = 0.0;
        let mut health_hit = 0.0;
        let mut remaining = 0.0;
        if self.pools[0] > 0.0 {
            let mut value = psum(vector.iter().map(|(k, raw)| raw * if *k == VOID || *k == RADIANT { 1.5 } else { 1.0 }))
                * self.vulnerability(MAGNETIC);
            let fortifier = if source != SYNDICATE { self.fortifier } else { None };
            if let Some((multiplier, _, _, uptime)) = fortifier {
                value *= 1.0 + (multiplier - 1.0) * uptime;
            }
            if value <= 0.0 {
                return Ok(false);
            }
            let fraction = pmin(left, self.pools[0] / value);
            let drain = value * fraction;
            self.pools[0] = pmax(0.0, self.pools[0] - drain);
            earlier_hit += drain;
            if let Some((_, steal, cap, uptime)) = fortifier {
                self.fortifier_damage += drain;
                let stolen = drain * steal * uptime;
                self.fortifier_stolen += stolen;
                self.self_overguard = pmin(cap, self.self_overguard + stolen);
            }
            applied += drain;
            left -= fraction;
            if self.pools[0] <= 1e-9 {
                self.pools[0] = 0.0;
                self.magnetic_break(t, 0)?;
                self.signal("on-overguard-broken", t, 1.0);
            }
        }
        if left > 0.0 && self.pools[1] > 0.0 {
            let shield = psum(
                vector
                    .iter()
                    .filter(|(k, _)| !self.shield_bypass.contains(k))
                    .map(|(k, raw)| raw * pmax(0.0, 1.0 + self.faction_delta(*k))),
            ) * self.vulnerability(MAGNETIC);
            let mut s = PySum::new();
            for (k, raw) in vector.iter() {
                if self.shield_bypass.contains(k) {
                    s.add(self.health_value(*k, *raw, t));
                }
            }
            let bypass = s.value();
            let fraction = pmin(
                pmin(left, if shield > 0.0 { self.pools[1] / shield } else { f64::INFINITY }),
                if bypass > 0.0 { self.pools[2] / bypass } else { f64::INFINITY },
            );
            let a = pmin(self.pools[1], shield * fraction);
            let bb = pmin(self.pools[2], bypass * fraction);
            self.pools[1] -= a;
            self.pools[2] -= bb;
            applied += a + bb;
            earlier_hit += a;
            health_hit += bypass * fraction;
            remaining += bb;
            left -= fraction;
            if self.pools[1] <= 1e-9 {
                self.pools[1] = 0.0;
                self.magnetic_break(t, 1)?;
                self.signal("on-shield-broken", t, 1.0);
            }
        }
        if left > 0.0 && self.pools[1] <= 1e-9 && self.pools[2] > 0.0 {
            let mut s = PySum::new();
            for (k, raw) in vector.iter() {
                s.add(self.health_value(*k, *raw, t));
            }
            let value = s.value();
            let drain = pmin(self.pools[2], value * left);
            self.pools[2] -= drain;
            applied += drain;
            health_hit += value * left;
            remaining += drain;
        }
        self.totals[source] += applied;
        if source == DOT && vector.len() == 1 {
            let d = vector[0].0;
            let prev = *self.dot_by_type.get(&d).unwrap_or(&0.0);
            self.dot_by_type.insert(d, prev + applied);
        }
        let weak = match weak_kill {
            WeakKill::Flag(true) => self.head,
            WeakKill::Flag(false) => 0.0,
            WeakKill::Value(v) => v,
        };
        self.attribution.add(t, earlier_hit, health_hit, cv2, weak, source == DIRECT);
        if let (Some(curve), 0) = (self.life_curve.as_mut(), self.gen) {
            // One target life: (time, health damage, its variance, source).
            let hit = health_hit + earlier_hit;
            curve.push((t, hit, pow(hit, 2.0) * cv2, source));
        }
        if self.ehp > 0.0 && self.pools[0] <= 1e-7 && self.pools[2] <= 1e-7 {
            let resume = self.resume_time(t)?;
            let crossing = self
                .attribution
                .crossing(t, remaining, resume)
                .map_err(|_| PyIndexError::new_err("list index out of range"))?;
            self.die(t, crossing.0, source != SYNDICATE)?;
            return Ok(true);
        }
        if !self.extra_hits.is_empty() && source == DIRECT && !extra {
            let trigger = psum(vector.iter().map(|x| x.1));
            for i in 0..self.extra_hits.len() {
                let (d, share) = self.extra_hits[i];
                if trigger > 0.0 {
                    let v = vec![(d, trigger * share * self.extra_scale)];
                    if self.take(&v, t, source, weak_kill, cv2, true)? {
                        return Ok(true);
                    }
                }
            }
        }
        Ok(false)
    }

    fn die(&mut self, t: f64, weak_kill: f64, weapon_kill: bool) -> PyResult<()> {
        if let Some(c) = self.cycle {
            if c.charge_on == 2 && self.form == BASE && weapon_kill {
                self.gauge = pmin(c.hits, self.gauge + 1.0); // native AddChargeConditions PRIMARY_KILL
            }
        }
        self.kills += 1;
        self.gen += 1;
        if self.first_kill.is_none() {
            self.first_kill = Some(t);
        }
        if let Some(last) = self.last_kill {
            self.min_interval = Some(match self.min_interval {
                None => t - last,
                Some(m) => pmin(m, t - last),
            });
        }
        self.last_kill = Some(t);
        self.pools = self.full;
        self.states.clear();
        for pool in self.pooled.iter_mut() {
            pool.reset();
        }
        self.presence.clear();
        self.attribution.reset();
        self.frozen_until = -1.0;
        self.gas_procs.clear();
        self.blast_procs.clear();
        self.heat_token += 1;
        self.heat_chains.reset();
        self.puncture_strip = 0.0;
        self.signal("on-kill", t, 1.0);
        let slot = self.weapon_slot.to_lowercase();
        if slot.contains("longgun") || slot == "primary" || slot == "rifle" {
            self.signal("on-primary-kill", t, 1.0);
        }
        if slot.contains("melee") {
            self.signal("on-melee-kill", t, 1.0);
        }
        if let Some(distance) = self.distance {
            if distance <= 5.0 {
                self.signal("on-close-kill", t, 1.0);
            }
        }
        let weak_probability = pmin(1.0, pmax(0.0, weak_kill));
        if weak_probability != 0.0 {
            self.weak_kill_events += weak_probability;
            self.signal("on-headshot-kill", t, weak_probability);
        }
        if let Some(restore) = self.restore.clone() {
            if weapon_kill && self.magazine_form() && (restore.kind == "on-kill" || restore.kind == "on-headshot-kill") {
                let chance = restore.chance * if restore.kind == "on-headshot-kill" { weak_probability } else { 1.0 } * restore.fraction;
                if self.shot_in_progress {
                    self.pending_restore = 1.0 - (1.0 - self.pending_restore) * (1.0 - chance);
                } else {
                    let magazine = { let i = self.model(t)?.0; self.stats[i].magazine };
                    self.ammo += pmax(0.0, magazine - self.ammo) * chance;
                }
            }
        }
        if let Some((_, _, fill)) = self.syndicate {
            if weapon_kill && t >= self.syndicate_ready {
                self.affinity += self.affinity_per_kill;
                if self.affinity >= fill {
                    self.push(t, Kind::Syndicate, None);
                }
            }
        }
        Ok(())
    }

    fn add_procs(&mut self, st: usize, aim: f64, t: f64, key: PacketKey) -> PyResult<()> {
        let _timer = crate::counters::Timer::start(crate::counters::ADD_PROCS);
        let data = self.packets[&key].clone();
        self.add_procs_data(st, aim, t, &data, true)
    }

    /// `status_arcanes.encumber_roll`: the chance a shot spawns an extra
    /// status, and the seed multiplier of the merged status it spawns.
    fn encumber_roll(&self, st: usize, chance: f64, aim: f64) -> (f64, f64) {
        let s = &self.stats[st];
        let pool = &self.status_pool;
        let m = pmax(s.multishot, 0.0);
        let low = m.floor();
        let frac = m - low;
        let mut q = 1.0;
        for (d, p) in &s.independent_proc_chances {
            if pool.contains(d) {
                q *= 1.0 - pmin(pmax(*p, 0.0), 1.0);
            }
        }
        for (d, n) in &s.native_forced_procs {
            if pool.contains(d) {
                q *= 1.0 - pmin(pmax(*n, 0.0), 1.0);
            }
        }
        for (d, _) in &s.core.crit_proc_chances {
            if pool.contains(d) {
                q *= 1.0 - ((1.0 - aim) * tables::crit_proc_probability(&s.core, *d, false)
                    + aim * tables::crit_proc_probability(&s.core, *d, true));
            }
        }
        let forced = pmin(psum(self.forced_procs.iter().filter(|x| pool.contains(&x.0)).map(|x| pmax(x.1, 0.0))), 1.0);
        let sc = if s.damage_types.iter().any(|(k, v)| pool.contains(k) && *v > 0.0) { pmax(s.status_chance, 0.0) } else { 0.0 };
        let mut probability = 0.0;
        let mut seed = 0.0;
        for (pellets, weight) in [(low, 1.0 - frac), (low + 1.0, frac)] {
            if pellets <= 0.0 || weight <= 0.0 {
                continue;
            }
            let (p, merged) = if s.continuous {
                let source = 1.0 - (1.0 - pmin(sc * pellets, 1.0)) * q * (1.0 - forced);
                (chance * source, pellets)
            } else {
                let source = 1.0 - (1.0 - pmin(sc, 1.0)) * q;
                let p = 1.0 - pow(1.0 - chance * source, pellets);
                (1.0 - (1.0 - p) * (1.0 - chance * forced * (1.0 - source)), 1.0)
            };
            probability += weight * p;
            seed += weight * p * merged;
        }
        (probability, if probability != 0.0 { seed / probability } else { 1.0 })
    }

    /// A `_stackable` profile, flattened by the helper and memoised per dict.
    fn stackable_profile(&mut self, profile: &Bound<'py, PyAny>) -> PyResult<Rc<stackable::Profile>> {
        let ptr = profile.as_ptr() as usize;
        if let Some(p) = self.stack_profiles.get(&ptr) {
            return Ok(p.clone());
        }
        let r = self.helper.call_method1("stackable_profile", (profile,))?;
        let d = r.cast::<PyDict>()?;
        let p = Rc::new(stackable::Profile {
            kind: get_f(d, "kind", 3.0)? as u8,
            embed_seconds: get_f(d, "embedSeconds", 0.0)?,
            max_life: get_f(d, "maxLife", 0.0)?,
            embed_interval: get_f(d, "embedInterval", 0.0)?,
            max_stack: get_f(d, "maxStack", 0.0)?,
            merge_low: get_f(d, "mergeLow", 0.0)?,
            merge_high: get_f(d, "mergeHigh", 0.0)?,
            merge_native: get_f(d, "mergeNative", 0.0)?,
            attach_at_stack: get_f(d, "attachAtStack", f64::INFINITY)?,
            singularity_interval: get_f(d, "singularityInterval", 0.0)?,
            reset_life: truthy(d, "resetLifeOnStack")?,
            stacked_life: get_f(d, "stackedLife", 0.0)?,
            initial_stack: get_f(d, "initialStack", 1.0)?,
            child: truthy(d, "child")?,
            child_max: get_f(d, "childMaxCount", 0.0)?,
            child_min: get_f(d, "childMinCount", 0.0)?,
            child_bounces: get_f(d, "childBounceCount", 0.0)?,
            child_life: get_f(d, "childLife", 0.0)?,
            child_death_multiplier: get_f(d, "childDeathMultiplier", 1.0)?,
        });
        self.stack_profiles.insert(ptr, p.clone());
        Ok(p)
    }

    /// Apply the projectile machine's hits and events in the order it made
    /// them (combat_replay.deliver_projectile for each hit).
    fn apply_stack_actions(&mut self, actions: Vec<stackable::Action>, t: f64) -> PyResult<()> {
        for action in actions {
            match action {
                stackable::Action::Hit { part, scale, weight } => {
                    let mut part = part;
                    if scale != 1.0 {
                        part = self.derive(part, 14, scale, |v| {
                            for e in v.core.damage_types.iter_mut() {
                                e.1 *= scale;
                            }
                            v.damage_types = v.core.damage_types.clone();
                            if let Some(dot) = v.core.dot_base_damage {
                                v.core.dot_base_damage = Some(dot * scale);
                            }
                            v.drop_private();
                        });
                    }
                    let part = self.derive(part, 15, weight, |v| {
                        v.multishot = weight;
                        v.core.multishot = weight;
                        v.drop_private();
                    });
                    let key = self.packet(part, 0.0)?;
                    let packet = self.packets[&key].clone();
                    let cv2 = self.spread(part, 0.0);
                    if !self.take(&packet.vector, t, DIRECT, WeakKill::Flag(false), cv2, false)? {
                        self.add_procs(part, 0.0, t, key)?;
                    }
                    self.noncrit_no_proc_hit(part, 0.0, t);
                }
                stackable::Action::Life { time, group, token, action, generation } => {
                    self.push(time, Kind::StackLife(group, token, action), Some(generation));
                }
                stackable::Action::Child { time, group, multiplier, hits, generation } => {
                    self.push(time, Kind::StackChild(group, multiplier, hits), Some(generation));
                }
            }
        }
        Ok(())
    }

    /// combat_replay.queue_mines: the pending batch detonates after the delay.
    fn queue_mines(&mut self, t: f64) {
        let batch = std::mem::take(&mut self.pending_mines);
        self.pending_throws = 0;
        let mines = psum(batch.iter().filter(|m| !m.2).map(|m| self.stats[m.0].multishot));
        self.waiting_mines += mines;
        let delay = self.mines.unwrap().0;
        self.push(t + delay, Kind::Detonation(Rc::new(batch)), None);
    }

    /// combat_replay.model's onos_values: (power, crit hits, beam seconds).
    fn onos_values(&self, t: f64) -> (bool, f64, f64) {
        match self.onos {
            Some((alignment, _, ramp)) => {
                let beam = pmin(ramp, pmax(0.0, t - self.onos_start));
                // round(x, 6): the correctly rounded decimal, read back.
                let beam: f64 = format!("{:.6}", beam).parse().unwrap();
                (self.onos_ticks as f64 >= alignment, self.onos_hits, beam)
            }
            None => (false, 0.0, 0.0),
        }
    }

    /// `form == 'base' or (not cycle and not selectedIncarnon)`
    fn magazine_form(&self) -> bool {
        self.form == BASE || (self.cycle.is_none() && !self.selected_incarnon)
    }

    /// `form == 'incarnon' or selectedIncarnon`
    fn incarnon_form(&self) -> bool {
        self.form == INCARNON || self.selected_incarnon
    }

    /// combat_replay.form_burst: the burst (and its rate) of the current form.
    fn form_burst(&self) -> (Option<BurstSpec>, Option<f64>) {
        if self.cycle.is_none() {
            (self.burst, self.burst_rate)
        } else if self.form == BASE {
            (self.burst_base, self.burst_rate_base)
        } else {
            (self.burst_incarnon, self.burst_rate_incarnon)
        }
    }

    /// Secondary Empowered: one weapon status deals the arcane's damage.
    /// True when that hit killed the target.
    fn empowered_hit(&mut self, st: usize, d: D, n: f64, t: f64, weapon_status: bool) -> PyResult<bool> {
        let Some((damage, uptime)) = self.empowered else { return Ok(false) };
        if !weapon_status || !self.status_pool.contains(&d) {
            return Ok(false);
        }
        let n = n * uptime;
        if n <= 0.0 {
            return Ok(false);
        }
        let core = &self.stats[st].core;
        let faction = core.faction_all * core.faction_target;
        self.empowered_count += n;
        let before = self.totals[ARCANE];
        let died = self.take(&vec![(d, n * damage * faction)], t, ARCANE, WeakKill::Flag(false), 0.0, false)?;
        // The reference's `get(d, 0.0) + totals['arcane'] - before`, left to right.
        let prev = *self.empowered_by_type.get(&d).unwrap_or(&0.0);
        self.empowered_by_type.insert(d, prev + self.totals[ARCANE] - before);
        Ok(died)
    }

    /// `add_procs` for one packet's statuses; `weapon` is false for derived
    /// statuses (Cryogenic's cold), which never re-trigger weapon hooks.
    fn add_procs_data(&mut self, st: usize, aim: f64, t: f64, data: &Packet, weapon: bool) -> PyResult<()> {
        let generation = self.gen;
        if self.puncture_armor_strip != 0.0 && !self.stats[st].radial_only && weapon {
            let s = &self.stats[st];
            let forced = s.native_forced_procs.iter().find(|x| x.0 == PUNCTURE).map(|x| x.1).unwrap_or(0.0)
                + self.forced_procs.iter().find(|x| x.0 == PUNCTURE).map(|x| x.1).unwrap_or(0.0);
            let probability = if forced != 0.0 {
                1.0
            } else {
                let status = pmax(0.0, s.status_chance);
                let expected = tables::expected_status_procs(&s.core, &Vec::new(), false);
                let puncture = expected.iter().find(|x| x.0 == PUNCTURE).map(|x| x.1).unwrap_or(0.0);
                let share = pmin(1.0, pmax(0.0, puncture / pmax(status * s.multishot, 1e-9)));
                let whole = status.floor();
                1.0 - pow(1.0 - share, whole) * (1.0 - (status - whole) * share)
            };
            let bullets = if s.continuous { 1.0 } else { s.multishot };
            self.puncture_strip = pmin(1.0, self.puncture_strip + self.puncture_armor_strip * bullets * probability);
        }
        if let Some((chance, uptime)) = self.encumber {
            if weapon && self.status_rate_multiplier > 0.0 {
                if (t - self.encumber_time).abs() > 1e-9 {
                    self.encumber_time = t;
                    self.encumber_remaining = 1.0;
                }
                let (probability, merged_seed) = self.encumber_roll(st, chance, aim);
                let weight = self.encumber_remaining * probability * uptime;
                self.encumber_remaining *= 1.0 - probability * uptime;
                if weight > 0.0 {
                    self.encumber_expected += weight;
                    // One extra status of a random pool type: its seeds come
                    // from a probe that procs every pool type exactly once.
                    let pool = self.status_pool.clone();
                    let probe = self.derive(st, 8, 0.0, |v| {
                        v.status_chance = 0.0;
                        v.core.status_chance = 0.0;
                        v.continuous = false;
                        v.core.continuous = false;
                        v.multishot = 1.0;
                        v.core.multishot = 1.0;
                        v.independent_proc_chances = pool.iter().map(|&d| (d, 1.0)).collect();
                        v.core.independent_proc_chances = v.independent_proc_chances.clone();
                        v.core.impact_proc_conversions = Vec::new();
                        v.core.crit_proc_chances = Vec::new();
                        v.has_crit_procs = false;
                        v.drop_private();
                    });
                    let key = self.packet(probe, aim)?;
                    let probed = self.packets[&key].clone();
                    let mut rows = probed.rows.clone();
                    for r in rows.values_mut() {
                        r.seed *= merged_seed;
                    }
                    let mut non = probed.non.clone();
                    for v in non.values_mut() {
                        *v *= merged_seed;
                    }
                    let share = weight / pool.len() as f64;
                    let derived = Packet { vector: Vec::new(), procs: pool.iter().map(|&d| (d, share)).collect(), rows, non };
                    self.add_procs_data(st, aim, t, &derived, false)?;
                }
            }
        }
        if self.gen != generation {
            return Ok(()); // a derived status killed the original target
        }
        let scale = pmax(self.stats[st].proc_duration_multiplier, 0.0);
        let sorted;
        let procs: &Vector = if self.empowered.is_some() {
            // The reference sorts by type name for a stable grouped order.
            let mut copy = data.procs.clone();
            let types = &self.types;
            copy.sort_by(|a, b| types.name(a.0).cmp(types.name(b.0)));
            sorted = copy;
            &sorted
        } else {
            &data.procs
        };
        for &(d, n0) in procs.iter() {
            let n = n0 * pmax(self.status_rate_multiplier, 0.0);
            if n <= 0.0 || (d == FREEZE && self.frozen_until > t) {
                continue;
            }
            let prev = *self.proc_counts.get(&d).unwrap_or(&0.0);
            self.proc_counts.insert(d, prev + n);
            let name = self.proc_signal(d);
            self.signal(&name, t, n);
            self.signal("on-proc", t, n);
            if scale <= 0.0 {
                if self.empowered_hit(st, d, n, t, weapon)? {
                    return Ok(());
                }
                continue;
            }
            let row = data.rows.get(&d).copied();
            let duration = match row {
                Some(r) => r.duration,
                None => duration_of(d).unwrap_or(6.0) * scale,
            };
            if duration <= 0.0 {
                if self.empowered_hit(st, d, n, t, weapon)? {
                    return Ok(());
                }
                continue;
            }
            let _ns = crate::counters::Timer::start(crate::counters::NOSTATUS);
            let mut absence = pow(self.no_status_probability(st, d, aim)?, pmax(self.status_rate_multiplier, 0.0));
            drop(_ns);
            if absence >= 1.0 && n > 0.0 {
                absence = 1.0 - pmin(n, 1.0);
            }
            if !weapon {
                absence = pmax(absence, 1.0 - pmin(n, 1.0));
            }
            { let _t = crate::counters::Timer::start(crate::counters::PRESENCE); self.presence.entry(d).or_default().add(t + duration, absence); }
            if d == FIRE && row.is_some() {
                let r = row.unwrap();
                if !self.heat_chains.active() {
                    self.heat_token += 1;
                    let token = self.heat_token;
                    self.push(t + 1.0, Kind::Heat(token), Some(self.gen));
                }
                { let _t = crate::counters::Timer::start(crate::counters::HEAT); self.heat_chains.add(t, absence, n, n * r.seed, duration, scale); }
                self.heat_acc = r.accumulator;
            } else if let Some(p) = pooled_index(d) {
                { let _t = crate::counters::Timer::start(crate::counters::POOLED); self.pooled[p].add(t + duration, absence, n); }
            } else {
                self.states.entry(d).or_default().push_back((t + duration, n));
                if let Some(c) = cap_of(d) {
                    if d != GAS {
                        let cap = if d == FREEZE && self.pools[0] > 0.0 { 4.0 } else { c };
                        let rows = self.states.get_mut(&d).unwrap();
                        let mut excess = psum(rows.iter().map(|x| x.1)) - cap;
                        while excess > 1e-9 && !rows.is_empty() {
                            let (end, number) = rows.pop_front().unwrap();
                            let remove = pmin(number, excess);
                            if number > remove {
                                rows.push_front((end, number - remove));
                            }
                            excess -= remove;
                        }
                    }
                }
                if d == FREEZE && self.count(d) >= 10.0 - 1e-9 && self.pools[0] <= 0.0 {
                    self.frozen_until = t + 3.0 * scale;
                    self.frozen_scale = scale;
                }
                if let Some(r) = row {
                    let immediate = d == GAS || d == ELECTRICITY;
                    let (first_tick, end_tick) = if immediate {
                        (0, ceil_i(duration - 1e-9).max(1))
                    } else {
                        (1, floor_i(duration + 1e-9) + 1)
                    };
                    let mut per = r.seed;
                    if !r.shared {
                        per += r.coefficient;
                    }
                    self.dots.push(DotInstance { dtype: d, per, count: n, end: t + duration, dist: None });
                    let instance = self.dots.len() - 1;
                    if d == GAS {
                        self.states.get_mut(&d).unwrap().pop_back();
                        let mut live = self.gas_procs.clone();
                        capped_stack_add(&mut live, &mut self.dots, absence, n, instance, 10);
                        self.gas_procs = live;
                    }
                    // The ticks keep the sequence numbers they would take if all
                    // were pushed now (the reference pushes them together), but
                    // enter the heap one at a time as the previous one pops:
                    // the pop order is the same and the heap stays small.
                    let mut count = 0;
                    for j in first_tick..end_tick {
                        if t + (j as f64) < self.window + 1e-9 {
                            count += 1;
                        } else {
                            break;
                        }
                    }
                    if count > 0 {
                        let base = self.seq;
                        self.seq += count as u64;
                        self.heap.push(Event { t: pmax(0.0, t + first_tick as f64), seq: base + 1,
                                               kind: Kind::IndependentDot(instance), gen: Some(self.gen) });
                        if count > 1 {
                            self.tick_chains.insert(instance, TickChain { t, first: first_tick, count, base, next: 1,
                                                                          gen: Some(self.gen) });
                        }
                    }
                } else if let Some(&per) = data.non.get(&d) {
                    self.states.get_mut(&d).unwrap().pop_back();
                    self.blasts.push(Blast { count: n, per, end: t + 1.5 * scale });
                    let blast = self.blasts.len() - 1;
                    self.blast_procs.push_back(blast);
                    let end = self.blasts[blast].end;
                    self.push(end, Kind::Blast(blast), Some(self.gen));
                    if psum(self.blast_procs.iter().map(|&i| self.blasts[i].count)) >= 10.0 {
                        self.push(t, Kind::BlastAll, Some(self.gen));
                    }
                }
            }
            if self.empowered_hit(st, d, n, t, weapon)? {
                return Ok(());
            }
        }
        // Secondary Cryogenic: Cold applications per Puncture status, through
        // the ordinary status path; they cannot trigger themselves.
        if let Some((cold_stacks, uptime)) = self.cryogenic {
            let puncture = data.procs.iter().find(|x| x.0 == PUNCTURE).map(|x| x.1).unwrap_or(0.0);
            let extra_cold = pmax(puncture, 0.0) * cold_stacks * uptime;
            if extra_cold > 0.0 {
                let before = *self.proc_counts.get(&FREEZE).unwrap_or(&0.0);
                let derived = Packet { vector: Vec::new(), procs: vec![(FREEZE, extra_cold)],
                                       rows: FxIndexMap::default(), non: FxIndexMap::default() };
                self.add_procs_data(st, aim, t, &derived, false)?;
                self.cryogenic_expected += *self.proc_counts.get(&FREEZE).unwrap_or(&0.0) - before;
            }
        }
        Ok(())
    }

    fn radial_hit(&mut self, part: usize, sniper_factor: f64, t: f64) -> PyResult<()> {
        let rkey = self.packet(part, 0.0)?;
        let rvector: Vector = if sniper_factor == 1.0 {
            self.packets[&rkey].vector.clone()
        } else {
            self.packets[&rkey].vector.iter().map(|(k, v)| (*k, v * sniper_factor)).collect()
        };
        let cv2 = self.spread(part, 0.0);
        if !self.take(&rvector, t, DIRECT, WeakKill::Flag(false), cv2, false)? {
            self.add_procs(part, 0.0, t, rkey)?;
        }
        self.noncrit_no_proc_hit(part, 0.0, t);
        Ok(())
    }

    fn noncrit_no_proc_hit(&mut self, st: usize, aim: f64, t: f64) {
        if !self.sources.iter().any(|q| q.kind.as_deref() == Some("on-noncrit-no-proc")) {
            return;
        }
        let puncture = if self.stats[st].radial_only { 0.0 } else { self.live_crit().0 };
        let s = &self.stats[st];
        let weak = s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative;
        let marginal = match &self.enervate {
            Some(en) => en.damage_marginal(),
            None => vec![(0, 1.0)],
        };
        let mut noncrit = 0.0;
        for (stacks, weight) in marginal {
            let cc = pmax(0.0, s.crit_chance + stacks as f64 * 0.1 + puncture);
            noncrit += weight * ((1.0 - aim) * pmax(0.0, 1.0 - cc * s.bodyshot_crit_multiplier) + aim * pmax(0.0, 1.0 - cc - weak));
        }
        let mut no_proc = pmax(0.0, 1.0 - s.status_chance);
        for (_, chance) in &s.independent_proc_chances {
            no_proc *= pmax(0.0, 1.0 - chance);
        }
        for (_, c) in &s.native_forced_procs {
            no_proc *= pmax(0.0, 1.0 - c);
        }
        for (_, c) in &self.forced_procs {
            no_proc *= pmax(0.0, 1.0 - c);
        }
        let instances = if s.continuous { 1.0 } else { s.multishot };
        self.signal("on-noncrit-no-proc", t, instances * noncrit * no_proc);
    }

    fn beam_tick(&mut self, time: f64, interval: f64, floor: f64) -> f64 {
        if let Some(last) = self.beam_last {
            let idle = time - last - interval;
            if idle > 0.8 {
                self.beam_progress = pmax(0.0, self.beam_progress - (idle - 0.8) / 2.0);
            }
        }
        let value = floor + (1.0 - floor) * self.beam_progress;
        self.beam_progress = pmin(1.0, self.beam_progress + interval / 0.6);
        self.beam_last = Some(time);
        value
    }
}

#[derive(Clone, Copy)]
struct SpoolSpec {
    maximum: f64,
    initial: f64,
    rate_start: f64,
    rate_shots: f64,
    ammo_divisor: f64,
    spindown: f64,
}

struct ShotCombo {
    min: f64,
    seconds: f64,
    tier_bonus: f64,
    tier_factor: f64,
    count: f64,
    last_hit: f64,
}

impl ShotCombo {
    fn multiplier(&self, hits: f64) -> f64 {
        let hits = (hits + 1e-9).floor();
        if self.min <= 0.0 || hits < self.min {
            return 1.0;
        }
        let mut threshold = self.min;
        let mut value = 1.0 + self.tier_bonus;
        while hits >= threshold * self.tier_factor {
            threshold *= self.tier_factor;
            value += self.tier_bonus;
        }
        value
    }
    fn at(&self, t: f64) -> f64 {
        if self.seconds <= 0.0 {
            return self.count;
        }
        let lost = ((t - self.last_hit) / self.seconds + 1e-9).floor();
        if lost > 0.0 { pmax(0.0, self.count - lost) } else { self.count }
    }
    fn shot(&mut self, t: f64, pellets: f64) -> f64 {
        let now = self.at(t);
        let pellets = pmax(pellets, 0.0);
        let whole = pellets.floor();
        let part = pellets - whole;
        let mut sum = PySum::new();
        let mut i = 0.0;
        while i < whole {
            sum.add(self.multiplier(now + i));
            i += 1.0;
        }
        let mut total = sum.value();
        total += part * self.multiplier(now + whole);
        let factor = if pellets > 0.0 { total / pellets } else { self.multiplier(now) };
        if pellets > 0.0 {
            self.count = now + pellets;
            self.last_hit = t;
        }
        factor
    }
}

#[derive(Clone)]
struct Restore {
    kind: String,
    chance: f64,
    fraction: f64,
    amount: f64,
    once_per_shot: bool,
    victim_proc_type: Option<D>,
}

/// What `apply_hit` reads of one melee hit (native_replay `hit_spec`).
struct HitSpec {
    atten: f64,
    slam: bool,
    combo_multiplier: bool,
    pct: Vector,
    target: Option<D>,
    crit_chance: Option<f64>,
    crit_multiplier: Option<f64>,
    can_crit: bool,
    extra_procs: Vec<D>,
    proc_atten: f64,
    radial: bool,
    duplicate: Option<(f64, f64)>,
}

/// `enervate.EnervateState`: a joint distribution over (stacks, big crits
/// since the last reset), kept as an insertion-ordered list like its dict.
struct Enervate {
    reset_after: i64,
    min_interval: f64,
    fixed: bool,
    uptime: f64,
    ignore_selected: bool,
    last: f64,
    hits: i64,
    resets: f64,
    states: Vec<((i64, i64), f64)>,
}

fn ordered_add<K: PartialEq + Copy>(list: &mut Vec<(K, f64)>, key: K, value: f64) {
    match list.iter_mut().find(|e| e.0 == key) {
        Some(e) => e.1 += value,
        None => list.push((key, 0.0 + value)),
    }
}

impl Enervate {
    fn marginal(&self) -> Vec<(i64, f64)> {
        let mut out = Vec::new();
        for &((s, _), p) in &self.states {
            ordered_add(&mut out, s, p);
        }
        out
    }

    fn damage_marginal(&self) -> Vec<(i64, f64)> {
        let mut weights: Vec<(i64, f64)> = self.marginal().into_iter().map(|(s, p)| (s, p * self.uptime)).collect();
        match weights.iter_mut().find(|e| e.0 == 0) {
            Some(e) => e.1 = e.1 + 1.0 - self.uptime,
            None => weights.push((0, 1.0 - self.uptime)),
        }
        weights.retain(|e| e.1 > 0.0);
        weights
    }

    fn advance(&mut self, t: f64, probabilities: Option<&[(i64, f64)]>) {
        if self.fixed || self.uptime == 0.0 || t - self.last < self.min_interval - 1e-9 {
            return;
        }
        self.last = t;
        self.hits += 1;
        let mut following: Vec<((i64, i64), f64)> = Vec::new();
        for &((s, b), mass) in &self.states {
            let given = probabilities.and_then(|ps| ps.iter().find(|e| e.0 == s).map(|e| e.1)).unwrap_or(0.0);
            let prob = pmin(1.0, pmax(0.0, given));
            ordered_add(&mut following, (s + 1, b), mass * (1.0 - prob));
            if b + 1 >= self.reset_after {
                ordered_add(&mut following, (0, 0), mass * prob);
                self.resets += mass * prob;
            } else {
                ordered_add(&mut following, (s + 1, b + 1), mass * prob);
            }
        }
        following.retain(|e| e.1 > 0.0);
        self.states = following;
    }
}

/// `enervate.big_crit_probability`: tier >= 2, with one-tier promotion.
fn big_crit_probability(chance: f64, promotion: f64) -> f64 {
    let chance = pmax(0.0, chance);
    let promotion = pmin(1.0, pmax(0.0, promotion));
    pmin(1.0, pmax(0.0, chance - 1.0)) + pmin(pmin(1.0, pmax(0.0, chance)), pmax(0.0, 2.0 - chance)) * promotion
}

/// `enervate.any_probability`: integer pellets plus one fractional pellet.
fn any_probability(p: f64, pellets: f64) -> f64 {
    let n = pmax(0.0, pellets);
    let whole = n.trunc();
    1.0 - pow(1.0 - p, whole) * (1.0 - (n - whole) * p)
}

struct MeleeSpec {
    base_hits: f64,
    tier_step: f64,
    cap: f64,
    base_multiplier: f64,
    tier_keys: Vec<(PyObject, String, f64)>,
}

#[derive(Clone, Copy)]
struct MeleeHit {
    id: i64,
    heavy: bool,
    combo_hits: f64,
    consumes: bool,
}

impl MeleeSpec {
    fn multiplier(&self, count: f64) -> f64 {
        let count = pmin(pmax(count, 0.0), self.cap);
        if count < self.base_hits {
            return 1.0;
        }
        self.base_multiplier + 1.0 + floor_i((count - self.base_hits) / self.tier_step + 1e-9) as f64
    }
    fn tier(&self, count: f64) -> i64 {
        (self.multiplier(count) - 1.0).round_ties_even() as i64
    }
}

#[derive(Clone, Copy)]
enum WeakKill {
    Flag(bool),
    Value(f64),
}

fn armour_reduction(armour: f64) -> f64 {
    if armour <= 0.0 {
        return 0.0;
    }
    let effective = pmin(armour, 2700.0);
    0.9 * (effective / 2700.0).sqrt()
}

impl<'py> Replay<'py> {
    pub fn run(&mut self) -> PyResult<()> {
        let mut first_round = true;
        let mut burst_round: i64 = 0;
        let mut burst_size: i64 = 1;
        let mut burst_head_probability = 1.0;
        let mut last_fire_time = f64::NEG_INFINITY;
        let mut spool_shots: i64 = 0;
        let mut rate_spool_shots: i64 = 0;
        let mut rate_spool_due = 0.0;
        while let Some(event) = self.heap.pop() {
            if let Kind::IndependentDot(i) = &event.kind {
                self.next_tick(*i);
            }
            let t = event.t;
            self.current_time = t;
            self.clean(t);
            if let Some(g) = event.gen {
                if g != self.gen {
                    continue;
                }
            }
            match event.kind {
                Kind::Energy(i) => {
                    let q = &mut self.sources[i];
                    q.stacks = pmin(q.max_stacks, q.stacks + q.per_event);
                    q.expires = if q.duration != 0.0 { t + q.duration } else { f64::INFINITY };
                }
                Kind::Heat(token) => {
                    if self.heat_chains.active() && token == self.heat_token {
                        let generation = self.gen;
                        let value = self.heat_chains.seed() + self.heat_acc * self.heat_chains.alive();
                        let cv2 = 1.0 / pmax(self.heat_chains.count(), 1e-9);
                        self.take(&vec![(FIRE, value)], t, DOT, WeakKill::Flag(false), cv2, false)?;
                        if self.gen == generation {
                            self.push(t + 1.0, Kind::Heat(token), Some(self.gen));
                        }
                    }
                }
                Kind::Blast(_) | Kind::BlastAll => {
                    let affected: Vec<usize> = match event.kind {
                        Kind::BlastAll => self.blast_procs.iter().copied().collect(),
                        Kind::Blast(i) => vec![i],
                        _ => unreachable!(),
                    };
                    let value = psum(affected.iter().map(|&i| self.blasts[i].count * self.blasts[i].per));
                    let procs = psum(affected.iter().map(|&i| self.blasts[i].count));
                    for &i in &affected {
                        self.blasts[i].count = 0.0;
                    }
                    while let Some(&front) = self.blast_procs.front() {
                        if self.blasts[front].count == 0.0 {
                            self.blast_procs.pop_front();
                        } else {
                            break;
                        }
                    }
                    if value != 0.0 {
                        self.take(&vec![(EXPLOSION, value)], t, NONDOT, WeakKill::Flag(false), 1.0 / procs, false)?;
                        // Only natural expiration is an Enervate hit, not the 10-stack detonation.
                        if matches!(event.kind, Kind::Blast(_)) {
                            if let Some(en) = self.enervate.as_mut() {
                                en.advance(t, None);
                            }
                        }
                    }
                }
                Kind::IndependentDot(i) => {
                    let alive = stack_alive(&self.dots[i]);
                    let (count, per, end, d) = (self.dots[i].count, self.dots[i].per, self.dots[i].end, self.dots[i].dtype);
                    if count * alive > 0.0 && t <= end + 1e-9 {
                        let dtype = if d == SLASH { CINEMATIC } else { d };
                        self.take(&vec![(dtype, count * alive * per)], t, DOT, WeakKill::Flag(false), 1.0 / count, false)?;
                    }
                }
                Kind::Dot(d, value, end) => {
                    if t <= end + 1e-9 {
                        let dtype = if d == SLASH { CINEMATIC } else { d };
                        self.take(&vec![(dtype, value)], t, DOT, WeakKill::Flag(false), 0.0, false)?;
                    }
                }
                Kind::Actor(ref kind) => {
                    self.actor_signal = true;
                    self.actor_signal_used = true;
                    let kind = kind.clone();
                    self.signal(&kind, t, 1.0);
                    self.actor_signal = false;
                }
                Kind::Syndicate => {
                    let (id, d, fill) = match &self.syndicate {
                        Some(x) => x.clone(),
                        None => continue,
                    };
                    if t < self.syndicate_ready || self.affinity < fill {
                        continue;
                    }
                    self.affinity = 0.0;
                    self.syndicate_ready = t + 30.0;
                    let before = self.totals[SYNDICATE];
                    let died = self.take(&vec![(d, 1000.0)], t, SYNDICATE, WeakKill::Flag(false), 0.0, false)?;
                    self.syndicate_events.push((t, self.totals[SYNDICATE] - before));
                    if !died && id != "justice" {
                        let name = self.types.name(d).to_string();
                        let duration = if name == "DT_CORROSIVE" { 8.0 } else if name == "DT_RADIATION" { 12.0 } else { 6.0 };
                        if let Some(p) = pooled_index(d) {
                            self.pooled[p].add(t + duration, 0.0, 1.0);
                        } else {
                            self.states.entry(d).or_default().push_back((t + duration, 1.0));
                        }
                        self.presence.entry(d).or_default().add(t + duration, 0.0);
                        if name == "DT_GAS" || name == "DT_POISON" {
                            let ticks: Vec<i64> = if name == "DT_GAS" { (0..6).collect() } else { (1..7).collect() };
                            for j in ticks {
                                self.push(t + j as f64, Kind::Dot(d, 500.5, t + 6.0), Some(self.gen));
                            }
                        }
                    }
                }
                Kind::DelayedRadial(part, sniper_factor) => {
                    self.delayed_attacks += 1;
                    self.radial_hit(part, sniper_factor, t)?;
                }
                Kind::DelayedAttack(part, aim) => {
                    self.delayed_attacks += 1;
                    let key = self.packet(part, aim)?;
                    let vector: Vector = self.packets[&key].vector.iter().map(|(k, v)| (*k, v * self.damage_rate_multiplier)).collect();
                    let cv2 = self.spread(part, aim);
                    let radial_only = self.stats[part].radial_only;
                    if !self.take(&vector, t, DIRECT, WeakKill::Flag(!radial_only), cv2, false)? {
                        self.add_procs(part, aim, t, key)?;
                    }
                    let puncture = if radial_only { 0.0 } else { self.live_crit().0 };
                    self.enervate_hit(part, t, puncture, aim);
                    let (ms, cc) = (self.stats[part].multishot, self.stats[part].crit_chance);
                    self.signal("on-hit", t, ms);
                    self.signal("on-headshot", t, aim * ms);
                    self.signal("on-crit", t, pmin(cc, 1.0) * ms);
                    self.noncrit_no_proc_hit(part, aim, t);
                }
                Kind::Lingering(part) => {
                    let raw = self.raw_packet(part, 0.0);
                    let packet = self.packets[&raw].clone();
                    let cv2 = self.spread(part, 0.0);
                    if !self.take(&packet.vector, t, DIRECT, WeakKill::Flag(false), cv2, false)? {
                        let key = self.packet(part, 0.0)?;
                        self.add_procs(part, 0.0, t, key)?;
                    }
                }
                Kind::StackLife(group, token, action) => {
                    let mut out = Vec::new();
                    if let Some(p) = self.projectiles.as_mut() {
                        p.life(&mut out, t, group, token, action);
                    }
                    self.apply_stack_actions(out, t)?;
                }
                Kind::StackChild(group, multiplier, hits) => {
                    let mut out = Vec::new();
                    if let Some(p) = self.projectiles.as_mut() {
                        p.child(&mut out, group, multiplier, hits);
                    }
                    self.apply_stack_actions(out, t)?;
                }
                Kind::Detonation(batch) => {
                    self.detonations += 1;
                    let mines = psum(batch.iter().filter(|m| !m.2).map(|m| self.stats[m.0].multishot));
                    self.waiting_mines = pmax(0.0, self.waiting_mines - mines);
                    for &(part, generation, _) in batch.iter() {
                        if generation != self.gen {
                            self.stale += 1;
                            continue;
                        }
                        let key = self.packet(part, 0.0)?;
                        let packet = self.packets[&key].clone();
                        let cv2 = self.spread(part, 0.0);
                        if !self.take(&packet.vector, t, DIRECT, WeakKill::Flag(false), cv2, false)? {
                            self.add_procs(part, 0.0, t, key)?;
                        }
                        self.enervate_hit(part, t, 0.0, 0.0);
                        let (ms, cc) = (self.stats[part].multishot, self.stats[part].crit_chance);
                        self.signal("on-hit", t, ms);
                        self.signal("on-crit", t, pmin(cc, 1.0) * ms);
                    }
                }
                Kind::Transform(next) => {
                    if self.tap.is_some() {
                        // ConsecutiveHits.swap: each form keeps its own suspended streak.
                        let saved = (self.tap_hits, pmax(self.tap_expires - t, 0.0));
                        let (hits, remaining) = self.tap_other;
                        self.tap_hits = hits;
                        self.tap_expires = if remaining != 0.0 { t + remaining } else { f64::NEG_INFINITY };
                        self.tap_other = saved;
                    }
                    self.form = next;
                    if self.onos.is_some() {
                        self.onos_ticks = 0;
                        self.onos_hits = 0.0;
                        self.onos_start = t;
                    }
                    self.signal("on-transform", t, 1.0);
                    self.transforms += 1;
                    first_round = true;
                    burst_round = 0;
                    let (active, _) = self.model(t)?;
                    if self.shell.is_some() && self.shell_mode_switch {
                        let loaded = if self.form == INCARNON { pmin(1.0, self.shells_owed) } else { self.shells_owed };
                        if loaded > 0.0 {
                            self.signal("on-shell-reloaded", t, loaded);
                            self.reload_shell_events.push((t, loaded, "mode-switch", self.form));
                            self.shells_owed -= loaded;
                        }
                    }
                    let c = self.cycle.unwrap();
                    if c.kill_charged {
                        // The primary keeps its magazine across the alternate shot.
                        if self.form == INCARNON {
                            self.base_ammo_saved = Some(self.ammo);
                            self.ammo = c.pool;
                        } else {
                            self.ammo = match self.base_ammo_saved { Some(a) => a, None => self.stats[active].magazine };
                        }
                    } else {
                        self.ammo = if self.form == INCARNON { c.pool } else { self.stats[active].magazine };
                    }
                    if self.form == BASE {
                        self.gauge = 0.0;
                    }
                    self.push(t, Kind::Fire, None);
                }
                Kind::ReloadShell(amount, limit) => {
                    self.ammo = pmin(limit, self.ammo + amount);
                    self.signal("on-shell-reloaded", t, amount);
                    self.reload_shell_events.push((t, amount, "reload", self.form));
                }
                Kind::ReloadComplete(was_empty) => {
                    if self.field_duration.is_some() && was_empty {
                        self.field_duration_ready = true;
                    }
                    let old_magazine = if self.refill_growth { { let i = self.model(t)?.0; self.stats[i].magazine } } else { 0.0 };
                    self.signal("on-reload-complete", t, 1.0);
                    if was_empty {
                        self.signal("on-reload-empty-complete", t, 1.0);
                    }
                    if self.refill_growth {
                        let grown = { let i = self.model(t)?.0; self.stats[i].magazine };
                        self.ammo = pmin(grown, self.ammo + pmax(0.0, grown - old_magazine));
                    }
                    self.push(t, Kind::Fire, None);
                }
                Kind::Fire => {
                    let _timer = crate::counters::Timer::start(crate::counters::FIRE);
                    if t >= self.window - 1e-9 || self.rate <= 0.0 {
                        continue;
                    }
                    let (active, _) = self.model(t)?;
                    let a = &self.stats[active];
                    let magazine_form = self.magazine_form();
                    self.last_round = magazine_form
                        && a.magazine > 0.0 && self.ammo > 0.0 && self.ammo <= pmax(a.ammo_cost, 1.0) + 1e-9;
                    let (mut active, radial) = self.model(t)?;
                    let speed = self.stats[active].fire_rate;
                    if speed <= 0.0 {
                        continue;
                    }
                    let mut melee_hit: Option<MeleeHit> = None;
                    if self.melee.is_some() {
                        let pending = match self.melee_pending {
                            None => {
                                self.melee_count = self.stats[active].initial_combo;
                                self.melee_heavy_multiplier = self.melee.as_ref().unwrap().multiplier(self.melee_count);
                                let (hit, wait) = self.melee_next(speed, self.stats[active].heavy_charge_speed)?;
                                self.melee_pending = Some(hit);
                                self.push(t + wait, Kind::Fire, None);
                                continue;
                            }
                            Some(hit) => hit,
                        };
                        melee_hit = Some(pending);
                        if t - self.melee_last_hit > pmax(self.stats[active].combo_duration, 0.0) + 1e-9
                            && self.melee_last_hit > f64::NEG_INFINITY
                        {
                            self.melee_count = self.stats[active].initial_combo;
                        }
                        self.heavy_flag = pending.heavy;
                        let (heavy_active, _) = self.model(t)?;
                        self.heavy_flag = false;
                        active = self.melee_apply(heavy_active, pending.id, self.melee_heavy_multiplier)?;
                    }
                    let mut radial = if self.melee.is_some() { None } else { radial };
                    if let Some((delay_seconds, max_projectiles, _)) = self.mines {
                        // A player detonates the existing batch before another throw
                        // could exceed the native deployment limit.
                        let gen = self.gen;
                        self.pending_mines.retain(|m| m.1 == gen);
                        if self.pending_mines.is_empty() {
                            self.pending_throws = 0;
                        }
                        if !self.pending_mines.is_empty() {
                            let deployed = psum(self.pending_mines.iter().filter(|m| !m.2).map(|m| self.stats[m.0].multishot));
                            if deployed + self.stats[active].multishot > max_projectiles + 1e-9 {
                                self.queue_mines(t);
                                self.push(t + pmax(delay_seconds, 1.0 / speed), Kind::Fire, None);
                                continue;
                            }
                        }
                    }
                    if let Some(c) = self.cycle {
                        if self.form == BASE && self.gauge >= c.hits - 1e-9 {
                            if self.shell.is_some() {
                                let m = self.stats[active].magazine;
                                self.shells_owed = pmax(0.0, (m - pmax(self.ammo, 0.0) - 1e-9).ceil());
                            }
                            self.push(t + c.enter, Kind::Transform(INCARNON), None);
                            continue;
                        }
                    }
                    let (magazine, ammo_cost) = (self.stats[active].magazine, self.stats[active].ammo_cost);
                    if let Some((empty_delay, partial_delay, regen)) = self.battery {
                        if last_fire_time.is_finite() {
                            let delay = if self.ammo <= 1e-9 { empty_delay } else { partial_delay };
                            self.ammo = pmin(magazine, self.ammo + pmax(0.0, t - last_fire_time - delay) * regen);
                        }
                    }
                    if self.infinite_ammo && magazine > 0.0 && !(self.cycle.is_some() && self.form == INCARNON) {
                        self.ammo = pmax(self.ammo, magazine);
                    }
                    let insufficient = self.stats[active].requires_full_ammo && self.ammo + 1e-9 < pmax(ammo_cost, 0.0);
                    if (self.ammo <= 1e-9 || insufficient) && magazine > 0.0 {
                        if let (Some(c), INCARNON) = (self.cycle, self.form) {
                            self.push(t + c.exit, Kind::Transform(BASE), None);
                            continue;
                        }
                        if self.battery.is_some() {
                            self.recharges += 1;
                            self.ammo = magazine;
                            let reload = self.stats[active].reload_time;
                            self.push(t + reload, Kind::Fire, None);
                            continue;
                        }
                        self.reloads += 1;
                        first_round = true;
                        burst_round = 0;
                        let was_empty = self.ammo <= 1e-9;
                        let before_reload_ammo = self.ammo;
                        if self.shell.is_none() || !magazine_form {
                            self.ammo = magazine + pmin(self.ammo, 0.0);
                        }
                        if was_empty {
                            self.signal("on-reload-empty", t, 1.0);
                        }
                        self.signal("on-reload", t, 1.0);
                        for q in self.sources.iter_mut() {
                            if q.kind.as_deref() == Some("on-burst-hit") {
                                q.stacks = 0.0;
                            }
                        }
                        let (reloading, _) = self.model(t)?;
                        let mut reload_time = self.stats[reloading].reload_time;
                        if let (Some((start, per_shell, end)), true) = (self.shell, magazine_form) {
                            let reload_magazine = self.stats[reloading].magazine;
                            let target_ammo = reload_magazine + pmin(before_reload_ammo, 0.0);
                            let missing = pmax(0.0, target_ammo - before_reload_ammo);
                            let total_rounds = ceil_i(missing - 1e-9);
                            let raw_full_time = start + per_shell * reload_magazine + end;
                            let speed_scale = if raw_full_time > 0.0 { reload_time / raw_full_time } else { 1.0 };
                            for i in 0..total_rounds.max(0) {
                                let amount = pmin(1.0, pmax(0.0, missing - i as f64));
                                self.push(t + (start + per_shell * (i + 1) as f64) * speed_scale,
                                          Kind::ReloadShell(amount, target_ammo), None);
                            }
                            reload_time = (start + per_shell * total_rounds as f64 + end) * speed_scale;
                        }
                        for q in self.sources.iter_mut() {
                            let k = q.kind.as_deref();
                            if (k == Some("on-reload-empty") || k == Some("on-reload")) && q.duration == 0.0 && !q.hold {
                                q.stacks = if q.per_event == 0.0 { q.initial_stacks } else { 0.0 };
                            }
                        }
                        if let Some(spool) = self.spool {
                            if reload_time >= spool.spindown {
                                spool_shots = 0;
                            }
                        }
                        self.push(t + reload_time, Kind::ReloadComplete(was_empty), None);
                        continue;
                    }
                    if let Some((remaining_clip, count, _, _)) = self.form_burst().0 {
                        if burst_round == 0 {
                            burst_size = if remaining_clip {
                                ceil_i(self.ammo / pmax(ammo_cost, 1e-9) - 1e-9).max(1)
                            } else {
                                count
                            };
                        }
                    }
                    let mut speed = speed;
                    if let Some(spool) = self.spool {
                        let pellets = pmin(spool.maximum, spool.initial + spool_shots as f64);
                        speed *= spool.rate_start + (1.0 - spool.rate_start) * pmin(spool_shots as f64 / spool.rate_shots, 1.0);
                        active = self.derive(active, 2, pellets, |v| {
                            v.multishot = v.multishot * pellets / spool.maximum;
                            v.core.multishot = v.multishot;
                            v.status_chance = v.status_chance * spool.maximum / pellets;
                            v.core.status_chance = v.status_chance;
                            v.ammo_cost = v.ammo_cost * (pellets / spool.ammo_divisor).ceil()
                                / (spool.maximum / spool.ammo_divisor).ceil();
                            v.drop_private();
                        });
                        spool_shots += 1;
                    }
                    if let (Some((start, end, over)), true) = (self.rate_spool, self.form != INCARNON) {
                        if t > rate_spool_due + 1e-9 {
                            rate_spool_shots = 0;
                        }
                        speed *= start + (end - start) * pmin(rate_spool_shots as f64 / over, 1.0);
                        rate_spool_shots += 1;
                    }
                    self.attacks += 1;
                    self.shot_in_progress = true;
                    if let Some((per_hit, maximum, duration)) = self.tap {
                        // Natively the form is the selected one: Incarnon when selectedIncarnon.
                        let incarnon_form = self.incarnon_form();
                        let has_radial = radial.is_some() && self.melee.is_none();
                        let hits = self.stats[active].multishot * if incarnon_form && has_radial { 2.0 } else { 1.0 };
                        // ConsecutiveHits.shot
                        let factor = {
                            if t >= self.tap_expires {
                                self.tap_hits = 0.0;
                            }
                            if hits <= 0.0 {
                                self.tap_hits = 0.0;
                                self.tap_expires = f64::NEG_INFINITY;
                                1.0
                            } else {
                                self.tap_hits += hits;
                                self.tap_expires = t + duration;
                                1.0 + per_hit * pmin(maximum, pmax(self.tap_hits - 1.0, 0.0))
                            }
                        };
                        let scaled = |v: &mut Stats| {
                            for e in v.core.damage_types.iter_mut() {
                                e.1 *= factor;
                            }
                            v.damage_types = v.core.damage_types.clone();
                            if let Some(dot) = v.core.dot_base_damage {
                                v.core.dot_base_damage = Some(dot * factor);
                            }
                            v.drop_private();
                        };
                        if !incarnon_form {
                            active = self.derive(active, 9, factor, scaled);
                        }
                        if let (Some(r), true) = (radial, has_radial) {
                            radial = Some(self.derive(r, 9, factor, scaled));
                        }
                    }
                    last_fire_time = t;
                    let generation = self.gen;
                    if self.last_burst && self.form == BASE && self.ammo <= 3.0 {
                        active = self.derive(active, 10, 0.0, |v| {
                            v.multishot *= 6.0;
                            v.core.multishot = v.multishot;
                            v.drop_private();
                        });
                    }
                    if first_round && self.stats[active].first_shot_damage_bonus != 0.0 {
                        let factor = 1.0 + self.stats[active].first_shot_damage_bonus;
                        active = self.derive(active, 1, factor, |v| {
                            for e in v.core.damage_types.iter_mut() {
                                e.1 *= factor;
                            }
                            v.damage_types = v.core.damage_types.clone();
                            if let Some(dot) = v.core.dot_base_damage {
                                v.core.dot_base_damage = Some(dot * factor);
                            }
                        });
                    }
                    first_round = false;
                    let pool_cost = self.stats[active].ammo_pool_multishot_cost;
                    if pool_cost != 0.0 && self.incarnon_form() && self.ammo < 1.0 + pool_cost {
                        let afforded = pmax(self.ammo - 1.0, 0.0);
                        let normal = 1.0 + pool_cost;
                        let factor = 1.0 + self.stats[active].ammo_pool_damage_bonus;
                        let previous = 1.0 + pool_cost * factor;
                        let reduced = 1.0 + afforded * factor;
                        if self.stats[active].continuous {
                            active = self.derive(active, 6, afforded, |v| {
                                v.multishot = reduced;
                                v.core.multishot = reduced;
                                v.ammo_pool_multishot_cost = afforded;
                                v.drop_private();
                            });
                        } else {
                            let adjustment = (reduced / (1.0 + afforded)) / (previous / normal);
                            active = self.derive(active, 7, afforded, |v| {
                                v.multishot = 1.0 + afforded;
                                v.core.multishot = v.multishot;
                                v.ammo_pool_multishot_cost = afforded;
                                for e in v.core.damage_types.iter_mut() {
                                    e.1 *= adjustment;
                                }
                                v.damage_types = v.core.damage_types.clone();
                                if let Some(dot) = v.core.dot_base_damage {
                                    v.core.dot_base_damage = Some(dot * adjustment);
                                }
                                v.drop_private();
                            });
                        }
                    }
                    // A shot consumes an armed field boost, even when that shot kills.
                    let field_duration_boost = self.field_duration_ready;
                    self.field_duration_ready = false;
                    let s = &self.stats[active];
                    let hit_count = if s.continuous { 1.0 } else { pmax(s.multishot, 0.0) };
                    let radial_only = s.radial_only;
                    let continuous = s.continuous;
                    let mut sniper_factor = 1.0;
                    if !radial_only && !self.incarnon_form() {
                        if let Some(combo) = self.shot_combo.as_mut() {
                            sniper_factor = combo.shot(t, hit_count);
                        }
                    }
                    let victim: Vec<(D, f64)> = {
                        let keys: Vec<D> = self.presence.keys().copied().collect();
                        keys.into_iter().map(|d| (d, self.presence.get_mut(&d).unwrap().probability(t))).collect()
                    };
                    self.victim_before = victim;
                    let shot_puncture = if radial_only { 0.0 } else { self.live_crit().0 };
                    let aim = if radial_only { 0.0 } else { self.head };
                    let primary_delay = self.stats[active].primary_delay;
                    let stack = self.stats[active].stackable.clone();
                    let mut projectile_wait = 0.0;
                    if let Some((profile, parts)) = stack.clone() {
                        if self.projectiles.is_none() {
                            self.projectiles = Some(Projectiles::new(self.projectile_state.clone()));
                        }
                        let mut out = Vec::new();
                        let multishot = self.stats[active].multishot;
                        projectile_wait = self.projectiles.as_mut().unwrap().deploy(&mut out, t, &profile, parts, multishot, generation);
                        self.apply_stack_actions(out, t)?;
                    } else if let Some((_, max_projectiles, _)) = self.mines {
                        if self.stats[active].multishot > max_projectiles {
                            self.mine_overflows += 1;
                            active = self.derive(active, 12, max_projectiles, |v| {
                                v.multishot = max_projectiles;
                                v.core.multishot = max_projectiles;
                                v.drop_private();
                            });
                        }
                        self.pending_mines.push((active, generation, false));
                        // A mine with its own explosion detonates it with the mine.
                        if let Some(r) = radial {
                            let mut parts = vec![r];
                            parts.extend(self.stats[r].additional.iter().copied());
                            let ms = self.stats[active].multishot;
                            for part in parts {
                                let extra = self.derive(part, 13, ms, |v| {
                                    v.multishot = ms;
                                    v.core.multishot = ms;
                                    v.drop_private();
                                });
                                self.pending_mines.push((extra, generation, true));
                            }
                        }
                        self.pending_throws += 1;
                    } else if primary_delay != 0.0 {
                        self.push(t + primary_delay, Kind::DelayedAttack(active, aim), Some(generation));
                    } else {
                        let key = self.packet(active, aim)?;
                        let floor = if self.form == BASE { self.beam_floor_base } else { self.beam_floor };
                        let ramp = match (continuous, floor) {
                            (true, Some(floor)) => self.beam_tick(t, 1.0 / speed, floor),
                            _ => 1.0,
                        };
                        let vector: Vector = self.packets[&key]
                            .vector
                            .iter()
                            .map(|(k, v)| (*k, v * self.damage_rate_multiplier * ramp * sniper_factor))
                            .collect();
                        let cv2 = self.spread(active, aim);
                        let died = self.take(&vector, t, DIRECT, WeakKill::Flag(!radial_only), cv2, false)?;
                        self.noncrit_no_proc_hit(active, aim, t);
                        if !died {
                            self.add_procs(active, aim, t, key)?;
                            if let Some((part, tick_rate, duration)) = self.stats[active].lingering {
                                let mut duration = duration;
                                if let Some(multiplier) = self.field_duration {
                                    if field_duration_boost && magazine_form && self.gen == generation {
                                        duration *= multiplier;
                                        self.field_duration_used += 1;
                                    }
                                }
                                if self.gen == generation {
                                    let ticks = ceil_i(duration * tick_rate - 1e-9);
                                    for tick in 0..ticks.max(0) {
                                        self.push(t + tick as f64 / tick_rate, Kind::Lingering(part), Some(self.gen));
                                    }
                                }
                            }
                        }
                    }
                    let mut parts: Vec<usize> = Vec::new();
                    if let (Some(r), None, true) = (radial, self.mines, stack.is_none()) {
                        parts.push(r);
                        parts.extend(self.stats[r].additional.iter().copied());
                    }
                    for mut part in parts {
                        if self.gen != generation {
                            self.stale += 1;
                            continue;
                        }
                        if self.stats[part].head_only {
                            let ms = self.stats[part].multishot * aim;
                            part = self.derive(part, 5, aim, |v| {
                                v.multishot = ms;
                                v.core.multishot = ms;
                            });
                            if self.stats[part].multishot == 0.0 {
                                continue;
                            }
                        }
                        let delay = pmax(0.0, self.stats[part].impact_delay);
                        if delay != 0.0 {
                            self.push(t + delay, Kind::DelayedRadial(part, sniper_factor), Some(generation));
                        } else {
                            self.radial_hit(part, sniper_factor, t)?;
                        }
                    }
                    if self.form_burst().0.is_some() {
                        if hit_count > 0.0 && burst_round == burst_size - 1 {
                            self.signal("on-burst-hit", t, 1.0);
                        }
                        burst_head_probability *= 1.0 - pow(1.0 - aim, hit_count);
                        if burst_round == burst_size - 1 {
                            self.signal("on-burst-headshot", t, burst_head_probability);
                            burst_head_probability = 1.0;
                        }
                    }
                    if primary_delay == 0.0 && self.mines.is_none() && stack.is_none() {
                        self.enervate_hit(active, t, shot_puncture, aim);
                    }
                    self.signal("on-fire", t, 1.0);
                    let delayed = primary_delay != 0.0 || self.mines.is_some() || stack.is_some();
                    let through = self.punchthrough;
                    if through != 0.0 {
                        self.signal("on-punchthrough", t, through);
                        if self.form == BASE || !self.selected_incarnon {
                            self.signal("on-onos-damage-condition", t, 1.0);
                        }
                        if through >= 2.0 {
                            self.signal("on-three-enemy-punchthrough", t, 1.0);
                        }
                    }
                    if let Some((alignment, _, _)) = self.onos {
                        if self.incarnon_form() && self.onos_ticks as f64 >= alignment {
                            self.onos_condition_hits += hit_count;
                            let completed = (self.onos_condition_hits / 2.0).floor();
                            self.onos_condition_hits -= completed * 2.0;
                            if completed != 0.0 {
                                self.signal("on-onos-damage-condition", t, completed);
                            }
                        }
                    }
                    if !delayed {
                    self.signal("on-hit", t, hit_count);
                    if aim < 1.0 {
                        self.signal("on-body-hit", t, (1.0 - aim) * hit_count);
                    }
                    self.signal("on-headshot", t, aim * hit_count);
                    self.consecutive_heads(aim);
                    let s = &self.stats[active];
                    let crit = pmin(
                        (1.0 - aim) * pmin(pmax(s.crit_chance * s.bodyshot_crit_multiplier, 0.0), 1.0)
                            + aim
                                * pmin(
                                    pmax(
                                        s.crit_chance
                                            + (s.weakpoint_crit_chance_bonus + s.base_crit_chance * s.weakpoint_crit_chance_relative),
                                        0.0,
                                    ),
                                    1.0,
                                ),
                        1.0,
                    ) * hit_count;
                    self.signal("on-crit", t, crit);
                    }
                    if let Some(c) = self.cycle {
                        let a = &self.stats[active];
                        if self.form == BASE && !a.radial_only && c.charge_on != 2 {
                            let per = if c.charge_on == 1 { 1.0 } else { self.head };
                            self.gauge = pmin(c.hits, self.gauge + per * a.multishot * a.incarnon_charge_multiplier);
                        }
                    }
                    let s = &self.stats[active];
                    let cost = if self.incarnon_form() {
                        s.charge_pool_cost + s.ammo_pool_multishot_cost
                    } else if s.bow_draw.is_some() && s.ammo_cost == 0.0 {
                        1.0
                    } else {
                        pmax(s.ammo_cost, 0.0)
                    };
                    self.ammo -= cost;
                    if self.reload_after_every_shot && magazine_form {
                        self.ammo = pmin(self.ammo, 0.0);
                    }
                    let magazine_now = self.stats[active].magazine;
                    if let Some(restore) = self.restore.clone() {
                        if (restore.kind == "on-headshot" || restore.kind == "on-hit") && magazine_form {
                            let eligible = match restore.victim_proc_type {
                                None => 1.0,
                                Some(d) => self.victim_before.iter().find(|x| x.0 == d).map(|x| x.1).unwrap_or(0.0),
                            };
                            if eligible != 0.0 {
                                let probability = if restore.kind == "on-headshot" { 1.0 - pow(1.0 - aim, hit_count) } else { 1.0 };
                                let events = if restore.once_per_shot { 1.0 } else { hit_count };
                                let restored = (pmax(0.0, magazine_now - self.ammo) * restore.fraction + restore.amount * events)
                                    * probability * restore.chance * eligible;
                                self.ammo = pmin(magazine_now, self.ammo + restored);
                            }
                        }
                    }
                    if self.pending_restore != 0.0 {
                        self.ammo += pmax(0.0, magazine_now - self.ammo) * self.pending_restore;
                        self.pending_restore = 0.0;
                    }
                    self.shot_in_progress = false;
                    let s = &self.stats[active];
                    let mut delay = match s.bow_draw {
                        Some(v) => v,
                        None => 1.0 / speed + s.charge_time,
                    };
                    if let (Some((alignment, post_fire, _)), true) = (self.onos, self.form != BASE) {
                        if self.onos_ticks as f64 >= alignment {
                            self.onos_ticks = 0;
                            self.onos_hits = 0.0;
                            delay = post_fire;
                            self.onos_start = t + delay;
                        } else {
                            self.onos_ticks += 1;
                            if self.onos_crits {
                                self.onos_hits = pmin(50.0, self.onos_hits + hit_count);
                            }
                        }
                    }
                    delay += projectile_wait;
                    if delay == 0.0 && self.ammo > 0.0 {
                        delay = if s.reload_time != 0.0 { s.reload_time } else { 1.0 / speed };
                    }
                    if let Some(hit) = melee_hit {
                        let s = &self.stats[active];
                        let gained = hit.combo_hits * (1.0 + pmax(s.combo_extra_chance, 0.0));
                        self.melee_count += gained * pmin(pmax(1.0 - s.combo_miss_chance, 0.0), 1.0);
                        if hit.consumes {
                            let retained = pmin(pmax(s.heavy_attack_efficiency, 0.0), 0.9);
                            self.melee_count = pmax(s.initial_combo, self.melee_count * retained);
                        }
                        let cap = self.melee.as_ref().unwrap().cap;
                        self.melee_count = pmin(self.melee_count, cap);
                        self.melee_last_hit = t;
                        let charge = self.stats[active].heavy_charge_speed;
                        let (next, wait) = self.melee_next(speed, charge)?;
                        self.melee_pending = Some(next);
                        delay = wait;
                    }
                    let (form_burst, form_burst_rate) = self.form_burst();
                    if let Some((_, _, delay_seconds, ignore_rate)) = form_burst {
                        burst_round += 1;
                        if burst_round < burst_size && self.ammo > 0.0 {
                            let rate = match form_burst_rate {
                                Some(r) if r != 0.0 => r,
                                _ => speed,
                            };
                            delay = delay_seconds / if ignore_rate { 1.0 } else { pmax(1.0, speed / rate) };
                        } else {
                            burst_round = 0;
                        }
                    }
                    if let Some((delay_seconds, _, batch_size)) = self.mines {
                        if self.pending_throws as f64 >= batch_size || self.ammo <= 1e-9 {
                            self.queue_mines(t);
                            delay = pmax(delay, delay_seconds);
                        }
                    }
                    rate_spool_due = t + delay;
                    self.push(t + delay, Kind::Fire, None);
                }
            }
        }
        Ok(())
    }
}

// ── entry point ──────────────────────────────────────────────────────────

fn list_f(v: &Bound<'_, PyAny>) -> PyResult<Vec<f64>> {
    v.extract::<Vec<f64>>()
}

#[pyfunction]
pub fn trajectory<'py>(py: Python<'py>, config: &Bound<'py, PyDict>, helper: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let started = std::time::Instant::now();
    let result = trajectory_inner(py, config, helper);
    crate::counters::add(crate::counters::TOTAL, started.elapsed().as_nanos() as u64);
    result
}

fn trajectory_inner<'py>(py: Python<'py>, config: &Bound<'py, PyDict>, helper: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let setup_timer = crate::counters::Timer::start(crate::counters::SETUP);
    let item = |k: &str| -> PyResult<Bound<'py, PyAny>> {
        config.get_item(k)?.ok_or_else(|| PyValueError::new_err(format!("config.{k} missing")))
    };
    let mut types = Types::new();
    let mut vec_of = |obj: &Bound<'py, PyAny>, types: &mut Types| -> PyResult<Vector> {
        let mut out = Vec::new();
        if obj.is_none() {
            return Ok(out);
        }
        for (k, v) in obj.downcast::<PyDict>()?.iter() {
            out.push((types.id(&k.extract::<String>()?), v.extract::<f64>()?));
        }
        Ok(out)
    };
    let names_of = |obj: &Bound<'py, PyAny>, types: &mut Types| -> PyResult<Vec<D>> {
        let mut out = Vec::new();
        for v in obj.try_iter()? {
            out.push(types.id(&v?.extract::<String>()?));
        }
        Ok(out)
    };
    let full = list_f(&item("full")?)?;
    let forced_procs = vec_of(&item("forcedProcs")?, &mut types)?;
    let faction_deltas = vec_of(&item("factionDeltas")?, &mut types)?;
    let armour_bypass = names_of(&item("armourBypass")?, &mut types)?;
    let shield_bypass = names_of(&item("shieldBypass")?, &mut types)?;
    let mut extra_hits = Vec::new();
    for e in item("extraHits")?.try_iter()? {
        let e = e?;
        let t = e.downcast::<PyTuple>()?;
        extra_hits.push((types.id(&t.get_item(0)?.extract::<String>()?), t.get_item(1)?.extract::<f64>()?));
    }
    let victim_before = vec_of(&item("victimBefore")?, &mut types)?;
    let burst_of = |key: &str| -> PyResult<Option<BurstSpec>> {
        let v = item(key)?;
        if v.is_none() {
            Ok(None)
        } else {
            let d = v.downcast::<PyDict>()?;
            Ok(Some((truthy(d, "remainingClip")?, match d.get_item("count")? {
                Some(c) if !c.is_none() => c.extract::<f64>()? as i64,
                _ => 0,
            }, get_f(d, "delay_seconds", 0.0)?, truthy(d, "ignoreFireRate")?)))
        }
    };
    let opt_f = |key: &str| -> PyResult<Option<f64>> {
        let v = item(key)?;
        Ok(if v.is_none() { None } else { Some(v.extract::<f64>()?) })
    };
    let burst = burst_of("burst")?;
    let burst_rate = {
        let v = item("burstRate")?;
        if v.is_none() { None } else { Some(v.extract::<f64>()?) }
    };
    let beam_floor = {
        let v = item("beamFloor")?;
        if v.is_none() { None } else { Some(v.extract::<f64>()?) }
    };
    let distance = {
        let v = item("distance")?;
        if v.is_none() { None } else { Some(v.extract::<f64>()?) }
    };
    let rate: f64 = item("rate")?.extract()?;
    let target_faction: String = item("targetFaction")?.extract()?;
    let opt_dict = |key: &str| -> PyResult<Option<Bound<'py, PyDict>>> {
        let v = item(key)?;
        Ok(if v.is_none() { None } else { Some(v.cast::<PyDict>()?.clone()) })
    };
    let battery = match opt_dict("battery")? {
        Some(d) => Some((get_f(&d, "delayEmptySeconds", 0.0)?, get_f(&d, "delayPartialSeconds", 0.0)?, get_f(&d, "regenPerSecond", 0.0)?)),
        None => None,
    };
    let spool = match opt_dict("spool")? {
        Some(d) => Some(SpoolSpec {
            maximum: get_f(&d, "maximum", 1.0)?, initial: get_f(&d, "initial", 0.0)?, rate_start: get_f(&d, "rateStart", 1.0)?,
            rate_shots: get_f(&d, "rateShots", 1.0)?, ammo_divisor: get_f(&d, "ammoDivisor", 1.0)?, spindown: get_f(&d, "spindown", f64::INFINITY)?,
        }),
        None => None,
    };
    let rate_spool = match opt_dict("fireRateSpool")? {
        Some(d) => Some((get_f(&d, "start", 1.0)?, get_f(&d, "end", 1.0)?, get_f(&d, "overShots", 1.0)?)),
        None => None,
    };
    let shell = match opt_dict("shellReload")? {
        Some(d) => Some((get_f(&d, "start", 0.0)?, get_f(&d, "perShell", 0.0)?, get_f(&d, "end", 0.0)?)),
        None => None,
    };
    let shell_mode_switch = match opt_dict("shellReload")? {
        Some(d) => truthy(&d, "modeSwitchLoadsShell")?,
        None => false,
    };
    let projectile_state = {
        let d = item("projectileState")?;
        let d = d.cast::<PyDict>()?;
        let opt = |key: &str| -> PyResult<Option<f64>> {
            Ok(match d.get_item(key)? { Some(v) if !v.is_none() => Some(v.extract::<f64>()?), _ => None })
        };
        stackable::State {
            isolated: truthy(d, "isolated")?,
            manual: truthy(d, "manual")?,
            detonate_after: opt("detonateAfterShots")?,
            wait: get_f(d, "detonationWaitSeconds", 0.0)?,
            child_hits: get_f(d, "stugChildHits", 0.0)?,
            bounce_hits: get_f(d, "stugBounceHits", 0.0)?,
            bounce_delay: get_f(d, "stugBounceDelaySeconds", 0.0)?,
            child_detonate: opt("stugChildDetonateSeconds")?,
            mq_augment: truthy(d, "mqAugmentEquipped")?,
        }
    };
    let cycle = match opt_dict("cycle")? {
        Some(d) => Some(CycleSpec {
            hits: get_f(&d, "hits", 0.0)?,
            enter: get_f(&d, "enterSeconds", 0.0)?,
            exit: get_f(&d, "exitSeconds", 0.0)?,
            pool: get_f(&d, "pool", 0.0)?,
            charge_on: match d.get_item("chargeOn")? {
                Some(v) if !v.is_none() => match v.extract::<String>()?.as_str() {
                    "direct_hits" => 1,
                    "kills" => 2,
                    _ => 0,
                },
                _ => 0,
            },
            kill_charged: truthy(&d, "killCharged")?,
        }),
        None => None,
    };
    let shot_combo = match opt_dict("sniperCombo")? {
        Some(d) => Some(ShotCombo { min: get_f(&d, "min", 0.0)?, seconds: get_f(&d, "seconds", 0.0)?,
                                    tier_bonus: get_f(&d, "tierBonus", 0.0)?, tier_factor: get_f(&d, "tierFactor", 1.0)?,
                                    count: 0.0, last_hit: 0.0 }),
        None => None,
    };
    let restore = match opt_dict("magazineRestore")? {
        Some(d) => Some(Restore {
            kind: d.get_item("kind")?.map(|v| v.extract::<String>()).transpose()?.unwrap_or_default(),
            chance: get_f(&d, "chance", 1.0)?,
            fraction: get_f(&d, "fraction", 0.0)?,
            amount: get_f(&d, "amount", 0.0)?,
            once_per_shot: truthy(&d, "oncePerShot")?,
            victim_proc_type: match d.get_item("victimProcType")? {
                Some(v) if v.is_truthy()? => Some(types.id(&v.extract::<String>()?)),
                _ => None,
            },
        }),
        None => None,
    };
    let tables = {
        let t = item("tables")?;
        let t = t.cast::<PyDict>()?;
        let loc = |v: Bound<'py, PyAny>| -> PyResult<Location> {
            let x = v.cast::<PyTuple>()?;
            Ok(Location { hit_multiplier: x.get_item(0)?.extract()?, hit_critical_multiplier: x.get_item(1)?.extract()?,
                          head: x.get_item(2)?.extract()? })
        };
        let pair = |key: &str| -> PyResult<[Location; 2]> {
            let v = t.get_item(key)?.ok_or_else(|| PyValueError::new_err(key.to_string()))?;
            let l = v.cast::<PyList>()?;
            Ok([loc(l.get_item(0)?)?, loc(l.get_item(1)?)?])
        };
        let damage = pair("damage")?;
        let dot = pair("dot")?;
        let dot_multiplier = vec_of(&t.get_item("dotMultiplier")?.unwrap(), &mut types)?;
        TargetTables {
            target_faction: !target_faction.is_empty(),
            damage,
            dot,
            dot_multiplier,
            forced_procs: forced_procs.clone(),
        }
    };
    let melee = {
        let v = item("melee")?;
        if v.is_none() {
            None
        } else {
            let d = v.cast::<PyDict>()?;
            let mut tier_keys = Vec::new();
            if let Some(keys) = d.get_item("tierKeys")? {
                for (k, cap) in keys.cast::<PyDict>()?.iter() {
                    tier_keys.push((k.clone().unbind(), k.extract::<String>()?, cap.extract::<f64>()?));
                }
            }
            Some(MeleeSpec {
                base_hits: get_f(d, "baseHits", 20.0)?,
                tier_step: get_f(d, "tierStep", 20.0)?,
                cap: get_f(d, "cap", 220.0)?,
                base_multiplier: get_f(d, "baseMultiplier", 1.0)?,
                tier_keys,
            })
        }
    };
    let syndicate = {
        let v = item("syndicate")?;
        if v.is_none() {
            None
        } else {
            let d = v.cast::<PyDict>()?;
            let id: String = d.get_item("id")?.map(|x| x.extract::<String>()).transpose()?.unwrap_or_default();
            let dtype: String = d.get_item("damageType")?.map(|x| x.extract::<String>()).transpose()?.unwrap_or_default();
            Some((id, types.id(&dtype), get_f(d, "affinityToFill", 0.0)?))
        }
    };
    let mut sources = Vec::new();
    for q in item("sources")?.downcast::<PyList>()?.iter() {
        let d = q.downcast::<PyDict>()?.clone();
        let kind = match d.get_item("kind")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        let reset_on = match d.get_item("resetOn")? {
            Some(v) if !v.is_none() => v.extract::<Vec<String>>()?,
            _ => Vec::new(),
        };
        let toggle_on = match d.get_item("toggleOn")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        let victim_proc_type = match d.get_item("victimProcType")? {
            Some(v) if v.is_truthy()? => Some(types.id(&v.extract::<String>()?)),
            _ => None,
        };
        let required_time = match d.get_item("requiredTime")? {
            Some(v) if v.is_truthy()? => Some(v.extract::<f64>()?),
            _ => None,
        };
        let minimum = match d.get_item("minimumConsecutive")? {
            Some(v) if v.is_truthy()? => v.extract::<f64>()? as i64,
            _ => 0,
        };
        sources.push(Source {
            id: d.get_item("id")?.map(|v| v.unbind()).unwrap_or_else(|| py.None()),
            kind,
            stacks: get_f(&d, "stacks", 0.0)?,
            expires: get_f(&d, "expires", f64::INFINITY)?,
            max_stacks: get_f(&d, "maxStacks", 1.0)?,
            duration: get_f(&d, "duration", 0.0)?,
            per_event: get_f(&d, "perEvent", 1.0)?,
            decay: match d.get_item("decay")? {
                Some(v) if !v.is_none() => v.extract::<String>()?,
                _ => "reset".to_string(),
            },
            initial_stacks: get_f(&d, "initialStacks", 0.0)?,
            hold: truthy(&d, "hold")?,
            reset_on,
            toggle_on,
            victim_proc_type,
            required_count: get_f(&d, "requiredCount", 1.0)?,
            required_time,
            actor_only: truthy(&d, "actorOnly")?,
            minimum_consecutive: minimum,
            energy_threshold: get_f(&d, "energyThreshold", 0.0)?,
            expiries: Vec::new(),
            progress: VecDeque::new(),
            run_distribution: None,
            obj: d.unbind(),
        });
    }
    let window: f64 = item("window")?.extract()?;
    let arcane = |key: &str| -> PyResult<Option<Bound<'py, PyDict>>> {
        let v = item(key)?;
        Ok(if v.is_none() { None } else { Some(v.cast::<PyDict>()?.clone()) })
    };
    let fortifier = match arcane("fortifier")? {
        Some(d) => Some((get_f(&d, "multiplier", 1.0)?, get_f(&d, "steal", 0.0)?, get_f(&d, "cap", 0.0)?,
                         get_f(&d, "uptime", 1.0)?)),
        None => None,
    };
    let empowered = match arcane("empowered")? {
        Some(d) => Some((get_f(&d, "damage", 0.0)?, get_f(&d, "uptime", 1.0)?)),
        None => None,
    };
    let enervate = match arcane("enervate")? {
        Some(d) => {
            let uptime = pmin(1.0, pmax(0.0, get_f(&d, "uptime", 1.0)?));
            let fixed = match d.get_item("fixedStacks")? {
                Some(v) if !v.is_none() => Some(v.extract::<f64>()?),
                _ => None,
            };
            let mut states = vec![((0i64, 0i64), 1.0)];
            if let Some(value) = fixed {
                let value = pmax(0.0, value);
                let lo = value.trunc();
                let frac = value - lo;
                states = vec![((lo as i64, 0), 1.0 - frac)];
                if frac != 0.0 {
                    states.push(((lo as i64 + 1, 0), frac));
                }
            }
            Some(Enervate {
                reset_after: get_f(&d, "resetAfter", 1.0)? as i64,
                min_interval: get_f(&d, "minInterval", 0.0)?,
                fixed: fixed.is_some(),
                uptime,
                ignore_selected: truthy(&d, "ignoreSelected")?,
                last: f64::NEG_INFINITY,
                hits: 0,
                resets: 0.0,
                states,
            })
        }
        None => None,
    };
    let tap = match arcane("doubleTap")? {
        Some(d) => Some((get_f(&d, "perHit", 0.0)?, get_f(&d, "maximum", 0.0)?, get_f(&d, "duration", 0.0)?)),
        None => None,
    };
    let field_duration = match arcane("fieldDurationOnEmptyReload")? {
        Some(d) => Some(get_f(&d, "multiplier", 1.0)?),
        None => None,
    };
    let encumber = match arcane("encumber")? {
        Some(d) => Some((get_f(&d, "chance", 0.0)?, get_f(&d, "uptime", 1.0)?)),
        None => None,
    };
    let cryogenic = match arcane("cryogenic")? {
        Some(d) => Some((get_f(&d, "coldStacks", 0.0)?, get_f(&d, "uptime", 1.0)?)),
        None => None,
    };
    let mut status_pool = Vec::new();
    for name in item("statusPool")?.try_iter()? {
        status_pool.push(types.id(&name?.extract::<String>()?));
    }
    let elements = {
        let mut id = |n: &str| types.id(n);
        let (fire, cold, electricity, toxin) = (id("DT_FIRE"), id("DT_FREEZE"), id("DT_ELECTRICITY"), id("DT_POISON"));
        co::Elements {
            physical: [id("DT_IMPACT"), id("DT_PUNCTURE"), id("DT_SLASH")],
            base: [fire, cold, electricity, toxin],
            combos: vec![
                (fire, cold, id("DT_EXPLOSION")),
                (fire, electricity, id("DT_RADIATION")),
                (fire, toxin, id("DT_GAS")),
                (cold, electricity, id("DT_MAGNETIC")),
                (cold, toxin, id("DT_VIRAL")),
                (electricity, toxin, id("DT_CORROSIVE")),
            ],
            electricity,
            radiation: id("DT_RADIATION"),
        }
    };
    let mut replay = Replay {
        py,
        helper: helper.clone(),
        resolver: item("resolver")?,
        window,
        head: item("head")?.extract()?,
        rate,
        status_rate_multiplier: item("statusRateMultiplier")?.extract()?,
        damage_rate_multiplier: item("damageRateMultiplier")?.extract()?,
        full: [full[0], full[1], full[2]],
        ehp: item("ehp")?.extract()?,
        armour_base: item("armourBase")?.extract()?,
        elemental_armour_strip: item("elementalArmourStrip")?.extract()?,
        forced_procs,
        faction_deltas,
        armour_bypass,
        shield_bypass,
        extra_hits,
        extra_scale: item("extraScale")?.extract()?,
        weapon_slot: item("weaponSlot")?.extract()?,
        distance,
        punchthrough: item("punchthrough")?.extract()?,
        live_types_enabled: item("liveTypes")?.is_truthy()?,
        beam_floor,
        burst,
        burst_rate,
        infinite_ammo: item("infiniteAmmo")?.is_truthy()?,
        victim_before,
        syndicate,
        battery,
        spool,
        rate_spool,
        shell,
        shot_combo,
        reload_after_every_shot: item("reloadAfterEveryShot")?.is_truthy()?,
        refill_growth: item("refillMagazineGrowth")?.is_truthy()?,
        restore,
        pending_restore: 0.0,
        recharges: 0,
        delayed_attacks: 0,
        reload_shell_events: Vec::new(),
        derived: FxHashMap::default(),
        target_faction,
        tables,
        selected_incarnon: item("selectedIncarnon")?.is_truthy()?,
        melee,
        melee_count: 0.0,
        melee_heavy_multiplier: 1.0,
        melee_last_hit: f64::NEG_INFINITY,
        melee_pending: None,
        heavy_flag: false,
        affinity_per_kill: item("affinityPerKill")?.extract()?,
        affinity: 0.0,
        syndicate_ready: 0.0,
        syndicate_events: Vec::new(),
        pools: [full[0], full[1], full[2]],
        states: FxIndexMap::default(),
        pooled: [CappedPool::new(10.0), CappedPool::new(10.0), CappedPool::new(10.0), CappedPool::new(5.0)],
        presence: FxIndexMap::default(),
        gas_procs: Vec::new(),
        dots: Vec::new(),
        blasts: Vec::new(),
        blast_procs: VecDeque::new(),
        heat_acc: 0.0,
        heat_token: 0,
        heat_chains: HeatChains::new(),
        attribution: KillAttribution::new(
            pmax(1.0, if rate > 0.0 { 1.0 / rate } else { 0.0 }),
            if rate > 0.0 { Some(1.0 / rate) } else { None },
        ),
        puncture_strip: 0.0,
        frozen_until: -1.0,
        heap: BinaryHeap::new(),
        seq: 0,
        gen: 0,
        kills: 0,
        weak_kill_events: 0.0,
        attacks: 0,
        stale: 0,
        first_kill: None,
        last_kill: None,
        min_interval: None,
        totals: [0.0; 5],
        fortifier,
        fortifier_damage: 0.0,
        fortifier_stolen: 0.0,
        self_overguard: 0.0,
        empowered,
        status_pool,
        empowered_count: 0.0,
        empowered_by_type: FxIndexMap::default(),
        cryogenic,
        cryogenic_expected: 0.0,
        puncture_armor_strip: item("punctureArmorStrip")?.extract()?,
        encumber,
        encumber_time: f64::NEG_INFINITY,
        encumber_remaining: 1.0,
        encumber_expected: 0.0,
        enervate,
        mines: match opt_dict("manualDetonation")? {
            Some(d) => Some((get_f(&d, "delaySeconds", 0.0)?, get_f(&d, "maxProjectiles", 0.0)?, get_f(&d, "batchSize", 1.0)?)),
            None => None,
        },
        life_curve: if item("lifeCurve")?.is_truthy()? { Some(Vec::new()) } else { None },
        onos: match opt_dict("onosCharge")? {
            Some(d) => Some((get_f(&d, "alignmentShots", 0.0)?, get_f(&d, "postFireSeconds", 0.0)?, get_f(&d, "rampSeconds", 0.0)?)),
            None => None,
        },
        onos_crits: item("onosCrits")?.is_truthy()?,
        onos_ticks: 0,
        onos_hits: 0.0,
        onos_start: 0.0,
        onos_condition_hits: 0.0,
        projectiles: None,
        projectile_state,
        stack_profiles: FxHashMap::default(),
        pending_mines: Vec::new(),
        pending_throws: 0,
        waiting_mines: 0.0,
        detonations: 0,
        mine_overflows: 0,
        form: if cycle.is_some() { BASE } else { SELECTED },
        cycle,
        gauge: 0.0,
        base_ammo_saved: None,
        transforms: 0,
        shells_owed: 0.0,
        shell_mode_switch,
        burst_base: burst_of("burstBase")?,
        burst_rate_base: opt_f("burstRateBase")?,
        burst_incarnon: burst_of("burstIncarnon")?,
        burst_rate_incarnon: opt_f("burstRateIncarnon")?,
        beam_floor_base: opt_f("beamFloorBase")?,
        last_burst: item("lastBurst")?.is_truthy()?,
        tap_other: (0.0, 0.0),
        tap,
        tap_hits: 0.0,
        tap_expires: f64::NEG_INFINITY,
        field_duration,
        field_duration_ready: false,
        field_duration_used: 0,
        enervate_views: FxHashMap::default(),
        enervate_weights: FxHashMap::default(),
        proc_counts: FxIndexMap::default(),
        dot_by_type: FxIndexMap::default(),
        magnetic_breaks: Vec::new(),
        sources,
        ammo: 0.0,
        shot_in_progress: false,
        reloads: 0,
        last_round: false,
        current_time: 0.0,
        beam_progress: 0.0,
        beam_last: None,
        actor_signal: false,
        actor_signal_used: false,
        armour_view: None,
        stats: Vec::new(),
        stats_by_ptr: FxHashMap::default(),
        model_cache: FxHashMap::default(),
        model_key: Vec::new(),
        tick_chains: FxHashMap::default(),
        co_specs: FxHashMap::default(),
        varied: FxHashMap::default(),
        elements,
        hit_specs: Vec::new(),
        applied: FxHashMap::default(),
        packets: FxHashMap::default(),
        spreads: FxHashMap::default(),
        first_shot: FxHashMap::default(),
        no_status: FxHashMap::default(),
        proc_names: Vec::new(),
        types,
        frozen_scale: 1.0,
    };
    // Initial stats and ammo, then the reference's pushes in order.
    let initial = item("stats")?;
    replay.view(&initial)?;
    let (active, _) = replay.model(0.0)?;
    replay.ammo = replay.stats[active].magazine;
    replay.push(0.0, Kind::Fire, None);
    for actor in item("actorEvents")?.try_iter()? {
        let actor = actor?;
        let t = actor.downcast::<PyTuple>()?;
        let first: f64 = t.get_item(0)?.extract()?;
        let interval: f64 = t.get_item(1)?.extract()?;
        let kind: String = t.get_item(2)?.extract()?;
        let total = if interval > 0.0 { trunc_i(pmax(0.0, window - first) / interval) + 1 } else { 1 };
        for i in 0..total.min(10000) {
            replay.push(first + i as f64 * interval, Kind::Actor(kind.clone()), None);
        }
    }
    let energy_rate: f64 = item("energyRate")?.extract()?;
    for i in 0..replay.sources.len() {
        let threshold = replay.sources[i].energy_threshold;
        if threshold != 0.0 && energy_rate > 0.0 {
            let interval = threshold / energy_rate;
            for n in 1..trunc_i(window / interval) + 1 {
                replay.push(n as f64 * interval, Kind::Energy(i), None);
            }
        }
    }
    drop(setup_timer);
    replay.run()?;
    let _result_timer = crate::counters::Timer::start(crate::counters::RESULT);
    // Core results; the Python wrapper assembles the reference's result dict.
    let out = PyDict::new(py);
    let opt = |v: Option<f64>| -> PyObject {
        match v {
            Some(x) => x.into_pyobject(py).unwrap().into_any().unbind(),
            None => py.None(),
        }
    };
    let names = |m: &FxIndexMap<D, f64>, types: &Types| -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        for (k, v) in m {
            d.set_item(types.name(*k), *v)?;
        }
        Ok(d)
    };
    out.set_item("kills", replay.kills)?;
    out.set_item("fortifier", (replay.fortifier_damage, replay.fortifier_stolen, replay.self_overguard))?;
    out.set_item("empowered", (replay.empowered_count, names(&replay.empowered_by_type, &replay.types)?))?;
    out.set_item("cryogenicExpected", replay.cryogenic_expected)?;
    out.set_item("encumberExpected", replay.encumber_expected)?;
    out.set_item("transforms", replay.transforms)?;
    if let Some(curve) = &replay.life_curve {
        out.set_item("lifeCurve", curve.clone())?;
    }
    if let Some(p) = &replay.projectiles {
        out.set_item("projectiles", (p.deployed, p.merged, p.explosions, p.singularities, p.child_projectiles))?;
    }
    let pending = psum(replay.pending_mines.iter().map(|m| replay.stats[m.0].multishot));
    out.set_item("mines", (replay.detonations, pending, replay.waiting_mines, replay.mine_overflows))?;
    out.set_item("fieldDuration", (replay.field_duration_used, replay.field_duration_ready))?;
    if let Some(en) = &replay.enervate {
        let states: Vec<(i64, i64, f64)> = en.states.iter().map(|&((s, b), p)| (s, b, p)).collect();
        out.set_item("enervate", (states, en.hits, en.resets, en.last))?;
    }
    out.set_item("gen", replay.gen)?;
    out.set_item("weakKillEvents", replay.weak_kill_events)?;
    out.set_item("attacks", replay.attacks)?;
    out.set_item("stale", replay.stale)?;
    out.set_item("firstKill", opt(replay.first_kill))?;
    out.set_item("minInterval", opt(replay.min_interval))?;
    out.set_item("pools", replay.pools.to_vec())?;
    out.set_item("totals", replay.totals.to_vec())?;
    out.set_item("procCounts", names(&replay.proc_counts, &replay.types)?)?;
    out.set_item("dotByType", names(&replay.dot_by_type, &replay.types)?)?;
    let breaks = PyList::empty(py);
    for (t, pool, stacks, per, gen) in &replay.magnetic_breaks {
        let d = PyDict::new(py);
        d.set_item("time", *t)?;
        d.set_item("pool", if *pool == 0 { "overguard" } else { "shield" })?;
        d.set_item("stacks", *stacks)?;
        d.set_item("seedPerTick", *per)?;
        d.set_item("targetGeneration", *gen)?;
        breaks.append(d)?;
    }
    out.set_item("magneticBreaks", breaks)?;
    out.set_item("reloads", replay.reloads)?;
    out.set_item("recharges", replay.recharges)?;
    out.set_item("delayedAttackEvents", replay.delayed_attacks)?;
    let shells = PyList::empty(py);
    for (t, rounds, source, form) in &replay.reload_shell_events {
        let d = PyDict::new(py);
        d.set_item("time", *t)?;
        d.set_item("rounds", *rounds)?;
        d.set_item("source", *source)?;
        d.set_item("form", match *form { BASE => "base", INCARNON => "incarnon", _ => "selected" })?;
        shells.append(d)?;
    }
    out.set_item("reloadShellEvents", shells)?;
    let syndicate_events = PyList::empty(py);
    for (t, damage) in &replay.syndicate_events {
        let d = PyDict::new(py);
        d.set_item("time", *t)?;
        d.set_item("id", replay.syndicate.as_ref().map(|x| x.0.clone()).unwrap_or_default())?;
        d.set_item("damage", *damage)?;
        syndicate_events.append(d)?;
    }
    out.set_item("syndicateEvents", syndicate_events)?;
    out.set_item("lastRound", replay.last_round)?;
    let victim = PyDict::new(py);
    for (k, v) in &replay.victim_before {
        victim.set_item(replay.types.name(*k), *v)?;
    }
    out.set_item("victimBefore", victim)?;
    out.set_item("actorSignalUsed", replay.actor_signal_used)?;
    let stacks: Vec<f64> = replay.sources.iter().map(|q| q.stacks).collect();
    out.set_item("sourceStacks", stacks)?;
    let _ = &replay.first_shot;
    for q in &replay.sources {
        let _ = q.obj.bind(py);
    }
    Ok(out)
}
