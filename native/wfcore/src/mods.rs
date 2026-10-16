//! `damage.apply_mods_spec`: the effect arithmetic of a weapon's modded stats.
//!
//! The weapon side (event profiles, base damage, which effects qualify) is
//! prepared once per weapon variant in Python (`mods_native.Prep`) and held by
//! a [`ModsPrep`]; [`apply_mods`] buckets the effects and runs every
//! `_combine`, element coalescing and the CO tail in the reference's order.
//!
//! Python number types survive where the reference passes a record value
//! through untouched or sums an empty bucket (`sum([])` is the int 0): those
//! fields reach JSON as `0`, not `0.0`, so [`Num`] keeps int and float apart.
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use crate::co::{self, Dict, Element, D};
use crate::fx::FxHashMap;
use crate::pymath::{pmax, pmin, pow, psum};

// ── numbers ──────────────────────────────────────────────────────────────

/// A Python number as the reference holds it.
#[derive(Clone, Copy, Debug)]
pub enum Num {
    I(i64),
    F(f64),
}

impl Num {
    fn f(self) -> f64 {
        match self {
            Num::I(i) => i as f64,
            Num::F(f) => f,
        }
    }
    fn truthy(self) -> bool {
        match self {
            Num::I(i) => i != 0,
            Num::F(f) => f != 0.0,
        }
    }
    fn add(self, other: Num) -> Num {
        match (self, other) {
            (Num::I(a), Num::I(b)) => Num::I(a + b),
            (a, b) => Num::F(a.f() + b.f()),
        }
    }
    fn sub(self, other: Num) -> Num {
        match (self, other) {
            (Num::I(a), Num::I(b)) => Num::I(a - b),
            (a, b) => Num::F(a.f() - b.f()),
        }
    }
    fn to_py(self, py: Python<'_>) -> Py<PyAny> {
        match self {
            Num::I(i) => i.into_pyobject(py).unwrap().into_any().unbind(),
            Num::F(f) => PyFloat::new(py, f).into_any().unbind(),
        }
    }
    fn extract(v: &Bound<'_, PyAny>) -> PyResult<Num> {
        if v.is_instance_of::<PyInt>() && !v.is_instance_of::<PyBool>() {
            Ok(Num::I(v.extract::<i64>()?))
        } else {
            Ok(Num::F(v.extract::<f64>()?))
        }
    }
}

/// `sum(values)`: the int 0 when empty.
fn pysum(values: impl IntoIterator<Item = f64>) -> Num {
    let values: Vec<f64> = values.into_iter().collect();
    if values.is_empty() {
        Num::I(0)
    } else {
        Num::F(psum(values))
    }
}

/// `quantize_base_crit_damage`
fn quantize(cd: f64) -> f64 {
    let step = 32.0 / 4095.0;
    (cd / step).round_ties_even() * step
}

/// `damage._combine` over (op, value) parts.
fn combine(base: f64, parts: &[&[(u8, f64)]]) -> f64 {
    co::combine(base, parts, None)
}

/// `damage._combine` keeping the base's type when nothing applies.
fn combine_num(base: Num, parts: &[&[(u8, f64)]]) -> Num {
    if parts.iter().all(|p| p.is_empty()) {
        base
    } else {
        Num::F(co::combine(base.f(), parts, None))
    }
}

// ── names ────────────────────────────────────────────────────────────────

struct Names {
    names: Vec<String>,
    index: FxHashMap<String, D>,
    objects: Vec<Py<PyString>>,
}

static NAMES: Mutex<Option<Names>> = Mutex::new(None);

fn with_names<R>(f: impl FnOnce(&mut Names) -> R) -> R {
    let mut guard = NAMES.lock().unwrap();
    let names = guard.get_or_insert_with(|| Names { names: Vec::new(), index: FxHashMap::default(), objects: Vec::new() });
    f(names)
}

fn intern(py: Python<'_>, name: &str) -> D {
    with_names(|n| {
        if let Some(&d) = n.index.get(name) {
            return d;
        }
        let d = n.names.len() as D;
        n.names.push(name.to_string());
        n.index.insert(name.to_string(), d);
        n.objects.push(PyString::intern(py, name).unbind());
        d
    })
}

fn name_obj(py: Python<'_>, d: D) -> Py<PyString> {
    with_names(|n| n.objects[d as usize].clone_ref(py))
}

fn elements(py: Python<'_>) -> co::Elements {
    let id = |n: &str| intern(py, n);
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
}

// ── buckets ──────────────────────────────────────────────────────────────

const BUCKETS: &[&str] = &[
    "GAMEPLAY_FACTION_DAMAGE", "RUNTIME_IMPACT_PROC_CONVERSION", "RUNTIME_INDEPENDENT_PROC", "WEAPON_AMMO_CONSUME_RATE",
    "WEAPON_AMMO_MAX", "WEAPON_DAMAGE_AMOUNT", "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE", "WEAPON_DAMAGE_WEAKPOINT",
    "WEAPON_DOUBLE_CRIT_CHANCE", "WEAPON_HEADSHOT_MULTIPLIER", "WEAPON_INIT_DAMAGE_MOD",
    "WEAPON_MELEE_COMBO_DURATION_BONUS", "WEAPON_MELEE_COMBO_GAIN_EXTRA_CHANCE", "WEAPON_MELEE_COMBO_GAIN_MISS_CHANCE",
    "WEAPON_MELEE_COMBO_INITIAL_BONUS", "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY", "WEAPON_MELEE_DAMAGE",
    "WEAPON_MELEE_HEAVY_CHARGE_SPEED", "WEAPON_MELEE_SLAM_DAMAGE_BONUS", "WEAPON_NOCRIT_DAMAGE",
    "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "WEAPON_PROC_DAMAGE",
    "WEAPON_PROC_TIME", "WEAPON_RECOIL", "WEAPON_SLASH_PROC_ON_CRIT_CHANCE", "WEAPON_SPREAD", "RUNTIME_COLD_STACK_DAMAGE",
    "RUNTIME_EXTRA_HIT", "RUNTIME_FINAL_CRIT_DAMAGE", "RUNTIME_FINAL_DAMAGE", "RUNTIME_FROZEN_DAMAGE",
    "RUNTIME_INCARNON_STAT_CONVERSION", "RUNTIME_LOCK_FIRE_RATE", "RUNTIME_LOCK_MULTISHOT", "RUNTIME_NEXT_SHOT_DAMAGE",
    "RUNTIME_PRIMARY_COMPRESSION", "WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER", "WEAPON_AMMO_POOL_MULTISHOT_DAMAGE",
    "WEAPON_CHARGE_RATE", "WEAPON_CLIP_MAX", "WEAPON_CRIT_CHANCE", "WEAPON_CRIT_CHANCE_BODY_PART",
    "WEAPON_CRIT_CHANCE_WEAKPOINT", "WEAPON_CRIT_DAMAGE", "WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS",
    "WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX", "WEAPON_EXPLOSION_RADIUS", "WEAPON_FIRE_ITERATIONS", "WEAPON_FIRE_RATE",
    "WEAPON_LOW_CRIT_DAMAGE", "WEAPON_LOW_CRIT_VALUE", "WEAPON_NOCRIT_CHANCE", "WEAPON_PROC_CHANCE",
    "WEAPON_PROJECTILE_SPEED", "WEAPON_RELOAD_SPEED", "WEAPON_RELOAD_TIME", "WEAPON_VICTIM_CRIT_CHANCE",
    "WEAPON_VICTIM_CRIT_DAMAGE", "WEAPON_VICTIM_DAMAGE_AMOUNT",
];
const OTHER: usize = BUCKETS.len();

fn bucket_of(name: &str) -> usize {
    BUCKETS.iter().position(|b| *b == name).unwrap_or(OTHER)
}

macro_rules! b {
    ($name:literal) => {{
        const fn eq(a: &str, b: &str) -> bool {
            let (a, b) = (a.as_bytes(), b.as_bytes());
            if a.len() != b.len() {
                return false;
            }
            let mut i = 0;
            while i < a.len() {
                if a[i] != b[i] {
                    return false;
                }
                i += 1;
            }
            true
        }
        const fn find(name: &str) -> usize {
            let mut i = 0;
            while i < BUCKETS.len() {
                if eq(BUCKETS[i], name) {
                    return i;
                }
                i += 1;
            }
            panic!("unknown bucket")
        }
        const I: usize = find($name);
        I
    }};
}

// Operation codes: co's combine codes, with SET_BASE kept apart where the
// reference reads the operation's name.
const OP_ADD_BASE: u8 = co::ADD_BASE;
const OP_ADD: u8 = co::ADD;
const OP_SM: u8 = co::STACKING_MULTIPLY;

/// One effect as the arithmetic reads it.
struct Row {
    bucket: usize,
    op: u8,
    set_base: bool,
    value: f64,
    damage_type: Option<String>,
    dtype: Option<D>,
    symbol: Option<String>,
    source: Option<String>,
    upgrade: String,
    zoom: bool,
    runtime_kind: Option<String>,
    runtime_damage_type: Option<String>,
    runtime_chance: Option<f64>,
    runtime_threshold: Option<f64>,
    runtime_multiplier: f64,
}

struct Entry {
    effect: Py<PyAny>,
    status: u8,
    message: Option<String>,
    unsupported: Option<String>,
    row: Row,
}

fn opt_str(o: &Bound<'_, PyAny>, attr: &str) -> PyResult<Option<String>> {
    let v = o.getattr(attr)?;
    if v.is_none() {
        Ok(None)
    } else {
        Ok(Some(v.extract::<String>()?))
    }
}

fn opt_f(o: &Bound<'_, PyAny>, attr: &str) -> PyResult<Option<f64>> {
    let v = o.getattr(attr)?;
    if v.is_none() {
        Ok(None)
    } else {
        Ok(Some(v.extract::<f64>()?))
    }
}

fn nonempty(s: &Option<String>) -> Option<&str> {
    s.as_deref().filter(|x| !x.is_empty())
}

fn row_of(py: Python<'_>, o: &Bound<'_, PyAny>) -> PyResult<Row> {
    let upgrade: String = o.getattr("upgrade_type")?.extract()?;
    let op_name: String = o.getattr("operation")?.extract()?;
    let damage_type = opt_str(o, "damage_type")?;
    let dtype = nonempty(&damage_type).map(|d| intern(py, d));
    let source = opt_str(o, "source_path")?;
    Ok(Row {
        bucket: bucket_of(&upgrade),
        op: co::op_code(&op_name),
        set_base: op_name == "SET_BASE",
        value: o.getattr("value")?.extract()?,
        dtype,
        damage_type,
        symbol: opt_str(o, "symbol_filter")?,
        zoom: source.as_deref().unwrap_or("").starts_with("zoom:"),
        source,
        upgrade,
        runtime_kind: opt_str(o, "runtime_kind")?,
        runtime_damage_type: opt_str(o, "runtime_damage_type")?,
        runtime_chance: opt_f(o, "runtime_chance")?,
        runtime_threshold: opt_f(o, "runtime_threshold")?,
        runtime_multiplier: o.getattr("runtime_multiplier")?.extract()?,
    })
}

// ── the prepared weapon ──────────────────────────────────────────────────

/// Shared by the app's request threads: the effect cache is behind a mutex
/// that is never held while Python code runs.
#[pyclass]
pub struct ModsPrep {
    classify: Py<PyAny>,
    effect_class: Py<PyAny>,
    zoom: Vec<Py<PyAny>>,
    melee: bool,
    base: Vec<(D, f64)>,
    compression: Option<(f64, bool, Option<f64>, f64, bool)>,
    aiming: bool,
    gunco_present: bool,
    gunco_base_fraction: Option<f64>,
    gunco_exclude: Vec<String>,
    gunco_independent: bool,
    co_base_fraction: f64,
    innate: Vec<(String, f64)>,
    notes: Vec<(String, String)>,
    speed_falloff: bool,
    falloff: Option<(f64, f64, f64)>,
    distance: Option<f64>,
    innate_multishot: f64,
    per_pellet_proc: f64,
    incarnon_form: bool,
    incarnon_pool: Option<f64>,
    incarnon_cycle_seconds: Option<f64>,
    incarnon_cycle: bool,
    base_magazine: f64,
    reload_every_shot: bool,
    reload_base: Num,
    shell: Option<(f64, f64, f64)>,
    battery: Option<(Num, f64)>,
    crit_chance: Num,
    crit_multiplier: Num,
    fire_rate: Num,
    charge_scales: bool,
    charge_seconds: f64,
    bow_draw: Option<f64>,
    continuous: bool,
    copy: Option<(f64, Option<Num>, Option<f64>, Option<f64>)>,
    orb_passes: i64,
    orb_stacks: i64,
    orb_special: bool,
    radial_only: bool,
    forced: Vec<(String, f64)>,
    ammo_cost: f64,
    cache: Mutex<FxHashMap<usize, Arc<Entry>>>,
}

fn get<'py>(d: &Bound<'py, PyDict>, k: &str) -> PyResult<Bound<'py, PyAny>> {
    d.get_item(k)?.ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.to_string()))
}

fn get_opt_f(d: &Bound<'_, PyDict>, k: &str) -> PyResult<Option<f64>> {
    let v = get(d, k)?;
    if v.is_none() {
        Ok(None)
    } else {
        Ok(Some(v.extract()?))
    }
}

#[pymethods]
impl ModsPrep {
    #[new]
    fn new(py: Python<'_>, config: &Bound<'_, PyDict>) -> PyResult<Self> {
        let mut base = Vec::new();
        for item in get(config, "base")?.try_iter()? {
            let (k, v): (String, f64) = item?.extract()?;
            base.push((intern(py, &k), v));
        }
        let mut zoom = Vec::new();
        for z in get(config, "zoom")?.try_iter()? {
            zoom.push(z?.unbind());
        }
        let compression = {
            let v = get(config, "compression")?;
            if v.is_none() { None } else { Some(v.extract::<(f64, bool, Option<f64>, f64, bool)>()?) }
        };
        let copy = {
            let v = get(config, "copy")?;
            if v.is_none() {
                None
            } else {
                let t = v.cast::<PyTuple>()?;
                let cc = t.get_item(1)?;
                Some((t.get_item(0)?.extract::<f64>()?,
                      if cc.is_none() { None } else { Some(Num::extract(&cc)?) },
                      t.get_item(2)?.extract::<Option<f64>>()?,
                      t.get_item(3)?.extract::<Option<f64>>()?))
            }
        };
        let crit_chance = {
            let v = get(config, "critChance")?;
            if v.is_none() { Num::F(0.0) } else { Num::extract(&v)? }
        };
        let battery = {
            let v = get(config, "battery")?;
            if v.is_none() {
                None
            } else {
                let t = v.cast::<PyTuple>()?;
                Some((Num::extract(&t.get_item(0)?)?, t.get_item(1)?.extract::<f64>()?))
            }
        };
        Ok(ModsPrep {
            classify: get(config, "classify")?.unbind(),
            effect_class: get(config, "effectClass")?.unbind(),
            zoom,
            melee: get(config, "melee")?.extract()?,
            base,
            compression,
            aiming: get(config, "aiming")?.extract()?,
            gunco_present: get(config, "guncoPresent")?.extract()?,
            gunco_base_fraction: get_opt_f(config, "guncoBaseFraction")?,
            gunco_exclude: get(config, "guncoExclude")?.extract()?,
            gunco_independent: get(config, "guncoIndependent")?.extract()?,
            co_base_fraction: get(config, "coBaseFraction")?.extract()?,
            innate: get(config, "innate")?.extract()?,
            notes: get(config, "notes")?.extract()?,
            speed_falloff: get(config, "speedFalloff")?.extract()?,
            falloff: get(config, "falloff")?.extract()?,
            distance: get_opt_f(config, "distance")?,
            innate_multishot: get(config, "innateMultishot")?.extract()?,
            per_pellet_proc: get(config, "perPelletProc")?.extract()?,
            incarnon_form: get(config, "incarnonForm")?.extract()?,
            incarnon_pool: get_opt_f(config, "incarnonPool")?,
            incarnon_cycle_seconds: get_opt_f(config, "incarnonCycleSeconds")?,
            incarnon_cycle: get(config, "incarnonCycle")?.extract()?,
            base_magazine: get(config, "baseMagazine")?.extract()?,
            reload_every_shot: get(config, "reloadEveryShot")?.extract()?,
            reload_base: Num::extract(&get(config, "reloadBase")?)?,
            shell: get(config, "shell")?.extract()?,
            battery,
            crit_chance,
            crit_multiplier: Num::extract(&get(config, "critMultiplier")?)?,
            fire_rate: Num::extract(&get(config, "fireRate")?)?,
            charge_scales: get(config, "chargeScales")?.extract()?,
            charge_seconds: get(config, "chargeSeconds")?.extract()?,
            bow_draw: get_opt_f(config, "bowDraw")?,
            continuous: get(config, "continuous")?.extract()?,
            copy,
            orb_passes: get(config, "orbPasses")?.extract()?,
            orb_stacks: get(config, "orbStacks")?.extract()?,
            orb_special: get(config, "orbSpecial")?.extract()?,
            radial_only: get(config, "radialOnly")?.extract()?,
            forced: get(config, "forced")?.extract()?,
            ammo_cost: get(config, "ammoCost")?.extract()?,
            cache: Mutex::new(FxHashMap::default()),
        })
    }
}

const CACHE_MAX: usize = 16384;
/// damage.py RELOAD_NEVER_SECONDS: a reload that never finishes.
const RELOAD_NEVER_SECONDS: f64 = 1e9;
/// damage.py AMMO_EFFICIENCY_CAP: the total Ammo Efficiency a trigger can reach.
const AMMO_EFFICIENCY_CAP: f64 = 0.75;

impl ModsPrep {
    /// The cached classification and row of one effect object.
    fn entry(&self, py: Python<'_>, effect: &Bound<'_, PyAny>) -> PyResult<Arc<Entry>> {
        let key = effect.as_ptr() as usize;
        if let Some(hit) = self.cache.lock().unwrap().get(&key) {
            return Ok(hit.clone());
        }
        // Python runs here: no lock held.
        let verdict = self.classify.bind(py).call1((effect,))?;
        let t = verdict.cast::<PyTuple>()?;
        let status: u8 = t.get_item(0)?.extract()?;
        let message: Option<String> = t.get_item(1)?.extract()?;
        let unsupported: Option<String> = t.get_item(2)?.extract()?;
        let row = row_of(py, effect)?;
        let entry = Arc::new(Entry { effect: effect.clone().unbind(), status, message, unsupported, row });
        self.cache.lock().unwrap().insert(key, entry.clone());
        Ok(entry)
    }
}

// ── apply_mods ───────────────────────────────────────────────────────────

struct Applied<'a> {
    rows: Vec<&'a Row>,
    objects: Vec<&'a Py<PyAny>>,
    buckets: Vec<Vec<usize>>,
}

impl<'a> Applied<'a> {
    fn idx(&self, b: usize) -> &[usize] {
        &self.buckets[b]
    }
    fn ops(&self, b: usize) -> Vec<(u8, f64)> {
        self.buckets[b].iter().map(|&i| (self.rows[i].op, self.rows[i].value)).collect()
    }
    fn ops_where(&self, b: usize, keep: impl Fn(&Row) -> bool) -> Vec<(u8, f64)> {
        self.buckets[b].iter().filter(|&&i| keep(self.rows[i])).map(|&i| (self.rows[i].op, self.rows[i].value)).collect()
    }
    fn values(&self, b: usize) -> Vec<f64> {
        self.buckets[b].iter().map(|&i| self.rows[i].value).collect()
    }
    fn empty(&self, b: usize) -> bool {
        self.buckets[b].is_empty()
    }
    fn list<'py>(&self, py: Python<'py>, indexes: &[usize]) -> PyResult<Bound<'py, PyList>> {
        PyList::new(py, indexes.iter().map(|&i| self.objects[i].clone_ref(py)))
    }
}

/// A damage-scale effect: an installed one or a synthetic runtime one.
enum Scale {
    Installed(usize),
    Synthetic(&'static str, &'static str, f64, Option<&'static str>),
}

fn dict_py<'py>(py: Python<'py>, d: &Dict) -> PyResult<Bound<'py, PyDict>> {
    let out = PyDict::new(py);
    for &(k, v) in d.0.iter() {
        out.set_item(name_obj(py, k), v)?;
    }
    Ok(out)
}

fn element_of(row: &Row) -> Element {
    match nonempty(&row.damage_type) {
        None | Some("DT_ANY") => (None, row.value),
        Some(_) => (row.dtype, row.value),
    }
}

/// `damage.apply_mods_spec(weapon, effects, scenario=...)` for the prepared
/// weapon: (ModdedStats fields in declaration order, CoSpec parts or None).
#[pyfunction]
#[pyo3(signature = (prep, effects, skipped, victim_status_count, need_spec))]
pub fn apply_mods<'py>(
    py: Python<'py>,
    prep: PyRef<'py, ModsPrep>,
    effects: &Bound<'py, PyAny>,
    skipped: Vec<String>,
    victim_status_count: &Bound<'py, PyAny>,
    need_spec: bool,
) -> PyResult<(Bound<'py, PyDict>, Py<PyAny>)> {
    let vsc: f64 = victim_status_count.extract()?;
    let el = elements(py);
    // Bounded: resolvers build fresh scaled effects every call.
    {
        let mut cache = prep.cache.lock().unwrap();
        if cache.len() >= CACHE_MAX {
            cache.clear();
        }
    }
    // Classify (cached per effect object), zoom buffs appended when absent.
    let mut entries: Vec<Arc<Entry>> = Vec::new();
    for e in effects.try_iter()? {
        entries.push(prep.entry(py, &e?)?);
    }
    if !entries.iter().any(|e| e.row.zoom) {
        for obj in prep.zoom.iter() {
            entries.push(prep.entry(py, obj.bind(py))?);
        }
    }
    let mut skipped = skipped;
    let mut unsupported: BTreeSet<String> = BTreeSet::new();
    let mut ap = Applied { rows: Vec::new(), objects: Vec::new(), buckets: vec![Vec::new(); OTHER + 1] };
    for entry in entries.iter() {
        match entry.status {
            0 => {
                ap.buckets[entry.row.bucket].push(ap.rows.len());
                ap.rows.push(&entry.row);
                ap.objects.push(&entry.effect);
            }
            1 => {
                if let Some(u) = &entry.unsupported {
                    unsupported.insert(u.clone());
                }
                skipped.push(entry.message.clone().unwrap_or_default());
            }
            3 => skipped.push(entry.message.clone().unwrap_or_default()),
            _ => {}
        }
    }
    let rows = &ap.rows;

    // Runtime proc conversions.
    let mut impact: Vec<(String, Vec<(f64, f64, f64)>)> = Vec::new();
    for &i in ap.idx(b!("RUNTIME_IMPACT_PROC_CONVERSION")) {
        let r = rows[i];
        let dtype = nonempty(&r.runtime_damage_type).or(nonempty(&r.damage_type));
        match (dtype, r.runtime_chance) {
            (Some(dtype), Some(chance)) => {
                let entry = (chance, r.runtime_threshold.unwrap_or(f64::INFINITY), r.runtime_multiplier);
                match impact.iter_mut().find(|x| x.0 == dtype) {
                    Some(x) => x.1.push(entry),
                    None => impact.push((dtype.to_string(), vec![entry])),
                }
            }
            _ => {
                skipped.push(format!("{}: unsupported[runtime-parameter]", r.source.as_deref().unwrap_or("?")));
                unsupported.insert(r.upgrade.clone());
            }
        }
    }
    let mut independent: Vec<(String, f64)> = Vec::new();
    for &i in ap.idx(b!("RUNTIME_INDEPENDENT_PROC")) {
        let r = rows[i];
        let dtype = nonempty(&r.runtime_damage_type).or(nonempty(&r.damage_type));
        match (dtype, r.runtime_chance) {
            (Some(dtype), Some(chance)) => match independent.iter_mut().find(|x| x.0 == dtype) {
                Some(x) => x.1 += chance,
                None => independent.push((dtype.to_string(), 0.0 + chance)),
            },
            _ => {
                skipped.push(format!("{}: unsupported[runtime-parameter]", r.source.as_deref().unwrap_or("?")));
                unsupported.insert(r.upgrade.clone());
            }
        }
    }
    let mut groups: Vec<(String, Vec<(u8, f64)>)> = Vec::new();
    for &i in ap.idx(b!("GAMEPLAY_FACTION_DAMAGE")) {
        let r = rows[i];
        let key = r.symbol.clone().unwrap_or_default();
        match groups.iter_mut().find(|g| g.0 == key) {
            Some(g) => g.1.push((r.op, r.value)),
            None => groups.push((key, vec![(r.op, r.value)])),
        }
    }
    let all_factions = match groups.iter().position(|g| g.0.is_empty()) {
        Some(p) => {
            let g = groups.remove(p);
            combine(1.0, &[&g.1])
        }
        None => 1.0,
    };
    let mut faction: Vec<(String, f64)> = groups.iter().map(|g| (g.0.clone(), combine(1.0, &[&g.1]))).collect();
    if all_factions != 1.0 {
        faction.push((String::new(), all_factions));
    }

    let co_idx: Vec<usize> = ap.idx(b!("WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE")).to_vec();
    let mut damage_flat_base = 0.0;
    let mut scale_effects: Vec<Scale> = Vec::new();
    let mut melee_idx: Vec<usize> = ap.idx(b!("WEAPON_MELEE_DAMAGE")).to_vec();
    if prep.melee {
        damage_flat_base += pysum(melee_idx.iter().filter(|&&i| rows[i].op == OP_ADD_BASE).map(|&i| rows[i].value)).f();
        melee_idx.retain(|&i| rows[i].op != OP_ADD_BASE);
    }
    for &i in ap.idx(b!("WEAPON_DAMAGE_AMOUNT")) {
        if rows[i].op == OP_ADD_BASE {
            damage_flat_base += rows[i].value;
        } else {
            scale_effects.push(Scale::Installed(i));
        }
    }
    let cold_rate = pysum(ap.values(b!("RUNTIME_COLD_STACK_DAMAGE")));
    let cold_forced = ap.idx(b!("RUNTIME_COLD_STACK_DAMAGE")).iter()
        .map(|&i| rows[i].runtime_chance.unwrap_or(0.0)).fold(None, |acc: Option<f64>, x| Some(match acc { None => x, Some(a) => pmax(a, x) }))
        .unwrap_or(0.0);
    if cold_rate.truthy() && cold_forced != 0.0 {
        scale_effects.push(Scale::Synthetic("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY",
                                            cold_rate.f() * pmin(cold_forced, 10.0), Some("runtime:cold-stack-damage")));
    }
    let mut compression_mult = 1.0 + pysum(ap.values(b!("RUNTIME_NEXT_SHOT_DAMAGE"))).f();
    let mut compression_ammo = 0.0;
    if !ap.empty(b!("RUNTIME_PRIMARY_COMPRESSION")) && prep.aiming {
        match prep.compression {
            Some((radius0, takes_mods, reads, effectiveness, adds)) => {
                let mut radius = radius0;
                if takes_mods {
                    radius = combine(radius, &[&ap.ops(b!("WEAPON_EXPLOSION_RADIUS"))]);
                }
                let considered = reads.unwrap_or(radius * effectiveness);
                let lost = pmax(considered, 0.0) * 0.8;
                let bonus = pysum(ap.values(b!("RUNTIME_PRIMARY_COMPRESSION"))).f() * lost;
                compression_ammo = pysum(ap.idx(b!("RUNTIME_PRIMARY_COMPRESSION")).iter()
                    .map(|&i| rows[i].runtime_chance.filter(|c| *c != 0.0).unwrap_or(0.0))).f() * lost;
                if adds {
                    scale_effects.push(Scale::Synthetic("WEAPON_DAMAGE_AMOUNT", "ADD", bonus, None));
                } else {
                    compression_mult += bonus;
                }
            }
            None => {
                unsupported.insert("primary-compression-weapon-profile-unverified".to_string());
            }
        }
    }
    let scale_ops: Vec<(u8, f64)> = scale_effects.iter().map(|s| match s {
        Scale::Installed(i) => (rows[*i].op, rows[*i].value),
        Scale::Synthetic(_, op, v, _) => (co::op_code(op), *v),
    }).collect();
    let ordinary_scale = combine(1.0, &[&scale_ops]);
    // The CoSpec keeps the value from here: the pool and copy factors that
    // multiply the local later reach the CO tail as their own factors.
    let spec_compression_mult = compression_mult;
    let raw_base_total = psum(prep.base.iter().map(|e| e.1));
    let mut gunco_fraction = None;
    if prep.gunco_present && !co_idx.is_empty() {
        let mut fraction = prep.gunco_base_fraction.unwrap_or(0.0);
        let excluded = pysum(ap.idx(b!("WEAPON_DAMAGE_AMOUNT")).iter()
            .filter(|&&i| rows[i].op == OP_ADD_BASE && rows[i].source.as_ref().map_or(false, |s| prep.gunco_exclude.contains(s)))
            .map(|&i| rows[i].value)).f();
        let total = raw_base_total + damage_flat_base;
        fraction *= if total != 0.0 { pmax(total - excluded, 0.0) / total } else { 0.0 };
        gunco_fraction = Some(fraction);
    }
    let victim_damage = combine(1.0, &[&ap.ops(b!("WEAPON_VICTIM_DAMAGE_AMOUNT"))]) - 1.0;
    let co_fraction = prep.co_base_fraction * raw_base_total / pmax(raw_base_total + damage_flat_base, 1e-9);
    let mut base: Vec<(D, f64)> = prep.base.clone();
    let mut base_scaled = false;
    if damage_flat_base != 0.0 && raw_base_total > 0.0 {
        let scale_up = 1.0 + damage_flat_base / raw_base_total;
        for e in base.iter_mut() {
            e.1 *= scale_up;
        }
        base_scaled = true;
    }
    let base_total = if base_scaled { psum(base.iter().map(|e| e.1)) } else { raw_base_total };
    let innate: Vec<(Option<D>, f64)> = prep.innate.iter().map(|(d, v)| (Some(intern(py, d)), *v)).collect();
    let elemental_base_total = base_total * (1.0 + pysum(prep.innate.iter().map(|e| e.1)).f());
    for (code, line) in prep.notes.iter() {
        unsupported.insert(code.clone());
        skipped.push(line.clone());
    }
    let pre_idx: Vec<usize> = ap.idx(b!("WEAPON_PERCENT_BASE_DAMAGE_ADDED")).to_vec();
    let post_idx: Vec<usize> = ap.idx(b!("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE")).to_vec();
    let speed = pmax(0.0, combine(1.0, &[&ap.ops(b!("WEAPON_PROJECTILE_SPEED"))]));
    let falloff_multiplier = match (prep.distance, prep.falloff) {
        (Some(distance), Some((start0, end0, minimum))) if base_total > 0.0 => {
            let (start, end) = if speed != 1.0 && prep.speed_falloff { (start0 * speed, end0 * speed) } else { (start0, end0) };
            if !start.is_finite() || !end.is_finite() || end <= start {
                1.0
            } else {
                let final_ = minimum / base_total;
                if distance <= start {
                    1.0
                } else if distance >= end {
                    final_
                } else {
                    let progress = (distance - start) / (end - start);
                    1.0 + (final_ - 1.0) * progress
                }
            }
        }
        _ => 1.0,
    };
    let pellets = pmax(prep.innate_multishot, 1.0);
    let proc_ops = ap.ops(b!("WEAPON_PROC_CHANCE"));
    let pellet_status = |chance: f64| combine(chance * pellets, &[&proc_ops]) / pellets;
    let mut magazine = combine(prep.base_magazine, &[&ap.ops(b!("WEAPON_CLIP_MAX"))]);
    if prep.base_magazine > 0.0 && !prep.incarnon_form {
        magazine = pmax(1.0, ((magazine as f32) as f64).floor());
    }
    if prep.reload_every_shot {
        magazine = 1.0;
    }
    let reload_base = match prep.shell {
        Some((start, per, end)) => Num::F(start + per * magazine + end),
        None => prep.reload_base,
    };
    let speed_ops = ap.ops(b!("WEAPON_RELOAD_SPEED"));
    // A reload-speed total of -100% or below never finishes a reload
    // (damage.py RELOAD_NEVER_SECONDS): a negative time sent the replay clock
    // backwards and never left the window.
    let divide = |base: Num| -> Num {
        if !base.truthy() || speed_ops.is_empty() {
            return base;
        }
        let scale = combine(1.0, &[&speed_ops]);
        if scale > 0.0 { Num::F(base.f() / scale) } else { Num::F(RELOAD_NEVER_SECONDS) }
    };
    let mut reload_time = divide(combine_num(reload_base, &[&ap.ops(b!("WEAPON_RELOAD_TIME"))]));
    if let Some((delay, regen)) = prep.battery {
        reload_time = Num::F(divide(delay).f() + magazine / regen);
    }
    if prep.incarnon_form {
        reload_time = Num::F(0.0);
        if let Some(pool) = prep.incarnon_pool {
            magazine = pool;
            if let Some(seconds) = prep.incarnon_cycle_seconds {
                reload_time = Num::F(seconds);
            }
        } else if prep.incarnon_cycle {
            unsupported.insert("incarnon-cycle-data-unavailable".to_string());
        }
    }
    let mut per_pellet_proc = prep.per_pellet_proc;
    let mut critchance = prep.crit_chance;
    let crit_ops = ap.ops(b!("WEAPON_CRIT_CHANCE"));
    for &i in ap.idx(b!("RUNTIME_INCARNON_STAT_CONVERSION")) {
        let r = rows[i];
        match r.runtime_kind.as_deref() {
            Some("WEAPON_PROC_CHANCE") => {
                let source = pellet_status(per_pellet_proc);
                let bonus = pmin(r.runtime_threshold.unwrap_or(f64::NAN), pmax(0.0, source) * r.value);
                critchance = Num::F(if critchance.truthy() { critchance.f() } else { 0.0 } + bonus);
            }
            Some("WEAPON_CRIT_CHANCE") => {
                let source = combine_num(critchance, &[&crit_ops]).f();
                let bonus = pmin(r.runtime_threshold.unwrap_or(f64::NAN), pmax(0.0, source) * r.value);
                per_pellet_proc += bonus;
            }
            _ => {}
        }
    }
    let mut crit_chance = combine_num(critchance, &[&crit_ops]);
    let fire_rate = if !ap.empty(b!("RUNTIME_LOCK_FIRE_RATE")) {
        prep.fire_rate
    } else {
        combine_num(prep.fire_rate, &[&ap.ops(b!("WEAPON_FIRE_RATE"))])
    };
    let charge_rate = pmax(1e-9, combine(1.0, &[&ap.ops(b!("WEAPON_CHARGE_RATE"))]));
    let charge_fire_scale = if prep.charge_scales { pmax(fire_rate.f() / pmax(prep.fire_rate.f(), 1e-9), 1e-9) } else { 1.0 };
    let charge_seconds = prep.charge_seconds / (charge_fire_scale * charge_rate);
    let bow_draw = prep.bow_draw.map(|d| d / (charge_fire_scale * charge_rate));
    let flat: Vec<f64> = ap.idx(b!("WEAPON_CRIT_DAMAGE")).iter().filter(|&&i| rows[i].op == OP_ADD || rows[i].op == OP_ADD_BASE)
        .map(|&i| rows[i].value).collect();
    let relative: Vec<(u8, f64)> = ap.ops_where(b!("WEAPON_CRIT_DAMAGE"), |r| !(r.op == OP_ADD || r.op == OP_ADD_BASE));
    let crit_base = prep.crit_multiplier.add(pysum(flat.iter().copied())).f();
    let mut crit_multiplier = combine(quantize(crit_base), &[&relative]);
    let anti = combine(0.0, &[&ap.ops(b!("WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX"))]);
    if anti > 0.0 && vsc < anti {
        crit_multiplier += combine(0.0, &[&ap.ops(b!("WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS"))]);
    }
    let low_threshold = if ap.empty(b!("WEAPON_LOW_CRIT_VALUE")) { None } else { Some(combine(0.0, &[&ap.ops(b!("WEAPON_LOW_CRIT_VALUE"))])) };
    let mut low_bonus = if low_threshold.is_some() {
        combine(quantize(combine(crit_base, &[&ap.ops(b!("WEAPON_LOW_CRIT_DAMAGE"))])), &[&relative])
            - combine(quantize(crit_base), &[&relative])
    } else {
        0.0
    };
    let mut multishot = if !ap.empty(b!("RUNTIME_LOCK_MULTISHOT")) {
        prep.innate_multishot
    } else {
        pmax(0.0, combine(prep.innate_multishot, &[&ap.ops(b!("WEAPON_FIRE_ITERATIONS"))]))
    };
    let continuous = prep.continuous;
    let mut pool_cost = 0.0;
    let pool_ops = ap.ops(b!("WEAPON_AMMO_POOL_MULTISHOT_DAMAGE"));
    let mut pool_multiplier = 1.0;
    let mut pool_factor = None;
    if !pool_ops.is_empty() {
        let source_base = psum(base.iter().map(|e| e.1));
        pool_multiplier = if source_base != 0.0 { combine(source_base, &[&pool_ops]) / source_base } else { 1.0 };
    }
    if !pool_ops.is_empty() && multishot > 1.0 {
        pool_cost = multishot - 1.0;
        let amplified = 1.0 + (multishot - 1.0) * pool_multiplier;
        if continuous {
            multishot = amplified;
        } else {
            let factor = amplified / multishot;
            pool_factor = Some(factor);
            compression_mult *= factor;
        }
    }
    let mut copy_factor = None;
    if let Some((share, copy_cc, copy_cm, copy_proc)) = prep.copy {
        if multishot > 1.0 && !continuous {
            let extra = multishot - 1.0;
            let total = 1.0 + extra * share;
            let factor = total / multishot;
            copy_factor = Some(factor);
            compression_mult *= factor;
            let copy_chance = combine(copy_cc.unwrap_or(critchance).f(), &[&crit_ops]);
            let copy_multiplier = combine(quantize(copy_cm.unwrap_or(prep.crit_multiplier.f()) + pysum(flat.iter().copied()).f()), &[&relative]);
            let cc = crit_chance.f();
            let blended = (cc + extra * share * copy_chance) / total;
            if blended > 0.0 {
                crit_multiplier = 1.0 + (cc * (crit_multiplier - 1.0) + extra * share * copy_chance * (copy_multiplier - 1.0)) / (total * blended);
            }
            crit_chance = Num::F(blended);
            if let Some(p) = copy_proc {
                per_pellet_proc = (per_pellet_proc + extra * p) / multishot;
            }
        }
    }
    let mut dot_basis = elemental_base_total * combine(1.0, &[&scale_ops]) * compression_mult;
    // _dot_elemental_multipliers
    let typed = |name: &str| -> Vec<(u8, f64)> {
        pre_idx.iter().chain(post_idx.iter()).filter(|&&i| nonempty(&rows[i].damage_type) == Some(name))
            .map(|&i| (rows[i].op, rows[i].value)).collect()
    };
    let mut dot_elements: Vec<(&str, f64)> = vec![
        ("DT_SLASH", 1.0),
        ("DT_FIRE", pmax(combine(1.0, &[&typed("DT_FIRE")]), 0.0)),
        ("DT_POISON", pmax(combine(1.0, &[&typed("DT_POISON")]), 0.0)),
        ("DT_ELECTRICITY", pmax(combine(1.0, &[&typed("DT_ELECTRICITY")]), 0.0)),
        ("DT_GAS", pmax(combine(1.0, &[&typed("DT_GAS")]), 0.0)),
    ];
    let weapon_crit_chance = crit_chance;
    let mut shield_crit = 1.0;
    let mut orb = None;
    if prep.orb_passes != 0 && !prep.radial_only && !prep.melee {
        let stacks = prep.orb_stacks;
        let electric = if stacks == 1 { 1.0 } else { 1.0 + 4.0 * stacks as f64 / 3.0 };
        let special = prep.orb_special;
        let shields = prep.orb_passes * if special { 2 } else { 1 };
        let atten = pow(0.66, shields as f64);
        let electric_bonus = prep.orb_passes as f64 * electric;
        orb = Some((electric_bonus, special, prep.orb_passes, atten));
        dot_basis *= atten;
        dot_elements[3].1 += electric_bonus;
        crit_chance = Num::F(crit_chance.f() + 0.25 * shields as f64);
        crit_multiplier *= 1.25;
        low_bonus *= 1.25;
        shield_crit = 1.25;
    }
    let mut final_damage = Num::I(1);
    let mut typed_final: Vec<(D, String, f64)> = Vec::new();
    for &i in ap.idx(b!("RUNTIME_FINAL_DAMAGE")) {
        let r = rows[i];
        match nonempty(&r.damage_type) {
            None => final_damage = Num::F(final_damage.f() * (1.0 + r.value)),
            Some(name) => {
                let d = r.dtype.unwrap();
                match typed_final.iter_mut().find(|x| x.0 == d) {
                    Some(x) => x.2 *= 1.0 + r.value,
                    None => typed_final.push((d, name.to_string(), 1.0 * (1.0 + r.value))),
                }
            }
        }
    }
    let final_spec = if final_damage.f() != 1.0 || !typed_final.is_empty() {
        dot_basis *= final_damage.f();
        Some((final_damage, Dict(typed_final.iter().map(|x| (x.0, x.2)).collect())))
    } else {
        None
    };
    crit_multiplier = crit_multiplier + pysum(ap.values(b!("RUNTIME_FINAL_CRIT_DAMAGE"))).f();
    let frozen_bonus = if prep.melee { pysum(ap.values(b!("RUNTIME_FROZEN_DAMAGE"))) } else { Num::F(0.0) };
    let frozen_idx = ap.idx(b!("RUNTIME_FROZEN_DAMAGE"));
    let frozen_forced = frozen_bonus.truthy() && frozen_idx.iter().any(|&i| rows[i].runtime_chance.unwrap_or(0.0) > 0.0);
    let mut frozen_factor = None;
    if frozen_forced {
        let share = frozen_idx.iter().map(|&i| rows[i].runtime_chance.unwrap_or(0.0))
            .fold(None, |acc: Option<f64>, x| Some(match acc { None => x, Some(a) => pmax(a, x) })).unwrap();
        frozen_factor = Some(1.0 + frozen_bonus.f() * pmin(share, 1.0));
    }
    let mut forced: Vec<(String, f64)> = prep.forced.clone();
    let mut extra_hits: Vec<(String, f64, bool)> = Vec::new();
    for &i in ap.idx(b!("RUNTIME_EXTRA_HIT")) {
        let r = rows[i];
        if let Some(d) = nonempty(&r.damage_type) {
            if r.value > 0.0 {
                extra_hits.push((d.to_string(), r.value, r.runtime_chance.map_or(false, |c| c != 0.0)));
            }
        }
    }
    for &i in ap.idx(b!("RUNTIME_EXTRA_HIT")) {
        let r = rows[i];
        if let (Some(d), Some(c)) = (nonempty(&r.damage_type), r.runtime_chance) {
            if r.value > 0.0 && c != 0.0 {
                match forced.iter_mut().find(|x| x.0 == d) {
                    Some(x) => x.1 += c,
                    None => forced.push((d.to_string(), 0.0 + c)),
                }
            }
        }
    }
    // The CO tail.
    let co_ops: Vec<(u8, f64)> = co_idx.iter().map(|&i| (rows[i].op, rows[i].value)).collect();
    let melee_ops: Vec<(u8, f64)> = melee_idx.iter().map(|&i| (rows[i].op, rows[i].value)).collect();
    let slam_idx: Vec<usize> = ap.idx(b!("WEAPON_MELEE_SLAM_DAMAGE_BONUS")).to_vec();
    let spec = co::CoSpec {
        victim_status_count: vsc,
        damage_scale_effects: scale_ops.clone(),
        ordinary_scale,
        compression_mult: spec_compression_mult,
        gunco_independent: prep.gunco_independent,
        gunco_fraction,
        victim_damage,
        co_fraction,
        melee: prep.melee,
        melee_damage_effects: melee_ops,
        slam_effects: slam_idx.iter().map(|&i| (rows[i].op, rows[i].value)).collect(),
        base: Dict(base.clone()),
        base_total,
        elemental_base_total,
        pre: pre_idx.iter().map(|&i| element_of(rows[i])).collect(),
        post: post_idx.iter().map(|&i| element_of(rows[i])).collect(),
        innate: innate.clone(),
        pool_factor,
        copy_factor,
        orb: orb.map(|(e, s, p, a)| (e, s, p as f64, a)),
        final_damage: final_spec.as_ref().map(|(f, d)| (f.f(), d.clone())),
        frozen_factor,
    };
    let codamage = co::co_damage(&spec, &co_ops, &el);
    let status_ops: Vec<(u8, f64)> = co_ops.iter().map(|&(op, v)| (op, v * vsc)).collect();
    let status_multiplier = combine(1.0, &[&status_ops]);

    // ── ModdedStats, in declaration order ──
    let out = PyDict::new(py);
    let crit_eff = crit_multiplier
        + match low_threshold {
            Some(t) if crit_chance.f() < t => low_bonus,
            _ => 0.0,
        };
    out.set_item("damage_types", dict_py(py, &codamage.damage_types)?)?;
    out.set_item("crit_chance", crit_chance.to_py(py))?;
    out.set_item("crit_multiplier", crit_eff)?;
    out.set_item("status_chance", pellet_status(per_pellet_proc))?;
    out.set_item("multishot", multishot)?;
    out.set_item("fire_rate", fire_rate.to_py(py))?;
    out.set_item("magazine", magazine)?;
    out.set_item("reload_time", reload_time.to_py(py))?;
    out.set_item("spread_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_SPREAD"))]))?;
    out.set_item("recoil_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_RECOIL"))]))?;
    out.set_item("ammo_max_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_AMMO_MAX"))]))?;
    out.set_item("headshot_bonus_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_HEADSHOT_MULTIPLIER"))]))?;
    out.set_item("proc_damage_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_PROC_DAMAGE"))]))?;
    out.set_item("proc_duration_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_PROC_TIME"))]))?;
    out.set_item("status_condition_damage_multiplier", status_multiplier)?;
    out.set_item("initial_combo", combine(0.0, &[&ap.ops(b!("WEAPON_MELEE_COMBO_INITIAL_BONUS"))]))?;
    out.set_item("combo_duration", combine(if prep.melee { 5.0 } else { 0.0 }, &[&ap.ops(b!("WEAPON_MELEE_COMBO_DURATION_BONUS"))]))?;
    out.set_item("heavy_attack_efficiency", combine(0.0, &[&ap.ops(b!("WEAPON_MELEE_COMBO_USAGE_EFFICIENCY"))]))?;
    out.set_item("combo_extra_chance", pysum(ap.values(b!("WEAPON_MELEE_COMBO_GAIN_EXTRA_CHANCE"))).to_py(py))?;
    out.set_item("combo_miss_chance", pysum(ap.values(b!("WEAPON_MELEE_COMBO_GAIN_MISS_CHANCE"))).to_py(py))?;
    out.set_item("heavy_charge_speed", pmax(0.05, 1.0 + pysum(ap.values(b!("WEAPON_MELEE_HEAVY_CHARGE_SPEED"))).f()))?;
    out.set_item("slam_damage_ratio", codamage.slam_damage_ratio)?;
    let factions = PyDict::new(py);
    for (k, v) in faction.iter() {
        factions.set_item(k, *v)?;
    }
    out.set_item("faction_damage_multipliers", factions)?;
    let nocrit_chance = if ap.empty(b!("WEAPON_NOCRIT_CHANCE")) {
        1.0
    } else {
        pmin(1.0, pmax(0.0, combine(0.0, &[&ap.ops(b!("WEAPON_NOCRIT_CHANCE"))])))
    };
    out.set_item("noncrit_damage_multiplier",
                 1.0 + pmax(0.0, combine(1.0, &[&ap.ops(b!("WEAPON_NOCRIT_DAMAGE"))]) - 1.0) * nocrit_chance)?;
    out.set_item("unsupported", PyList::new(py, unsupported.iter())?)?;
    let mut seen = std::collections::HashSet::new();
    let unique: Vec<&String> = skipped.iter().filter(|s| seen.insert(s.as_str())).collect();
    out.set_item("skipped", PyList::new(py, unique)?)?;
    out.set_item("falloff_multiplier", falloff_multiplier)?;
    out.set_item("dot_base_damage", dot_basis)?;
    let dots = PyDict::new(py);
    for (k, v) in dot_elements.iter() {
        dots.set_item(*k, *v)?;
    }
    out.set_item("dot_elemental_multipliers", dots)?;
    let conversions = PyDict::new(py);
    for (dtype, list) in impact.iter() {
        let rows_py = PyList::empty(py);
        for &(chance, threshold, multiplier) in list.iter() {
            let d = PyDict::new(py);
            d.set_item("chance", chance)?;
            d.set_item("fireRateThreshold", threshold)?;
            d.set_item("fireRateMultiplier", multiplier)?;
            rows_py.append(d)?;
        }
        conversions.set_item(dtype, rows_py)?;
    }
    out.set_item("impact_proc_conversions", conversions)?;
    let indep = PyDict::new(py);
    for (k, v) in independent.iter() {
        indep.set_item(k, *v)?;
    }
    out.set_item("independent_proc_chances", indep)?;
    let innate_types = PyDict::new(py);
    for (dtype, value) in prep.innate.iter() {
        innate_types.set_item(dtype, base_total * codamage.scale * value)?;
    }
    out.set_item("innate_damage_types", innate_types)?;
    out.set_item("innate_element_candidates", py.None())?;
    out.set_item("heavy_damage", py.None())?;
    out.set_item("heavy_components", PyList::empty(py))?;
    out.set_item("double_crit_chance", pmax(combine(1.0, &[&ap.ops(b!("WEAPON_DOUBLE_CRIT_CHANCE"))]) - 1.0, 0.0))?;
    out.set_item("first_shot_damage_bonus", pmax(combine(1.0, &[&ap.ops(b!("WEAPON_INIT_DAMAGE_MOD"))]) - 1.0, 0.0))?;
    out.set_item("weakpoint_damage_bonus", pmax(combine(1.0, &[&ap.ops(b!("WEAPON_DAMAGE_WEAKPOINT"))]) - 1.0, 0.0))?;
    let wcc = b!("WEAPON_CRIT_CHANCE_WEAKPOINT");
    let body = b!("WEAPON_CRIT_CHANCE_BODY_PART");
    out.set_item("weakpoint_crit_chance_bonus",
                 pysum(ap.idx(wcc).iter().filter(|&&i| rows[i].op == OP_ADD).map(|&i| rows[i].value)).to_py(py))?;
    let relative_wp = pysum(ap.idx(wcc).iter().filter(|&&i| rows[i].op == OP_SM).map(|&i| rows[i].value))
        .add(pysum(ap.idx(body).iter().filter(|&&i| rows[i].symbol.as_deref() == Some("HEAD") && rows[i].op == OP_SM)
            .map(|&i| rows[i].value)));
    out.set_item("weakpoint_crit_chance_relative", relative_wp.to_py(py))?;
    out.set_item("bodyshot_crit_multiplier",
                 combine(1.0, &[&ap.ops_where(body, |r| r.symbol.as_deref() == Some("TORSO"))]))?;
    out.set_item("base_crit_chance",
                 combine_num(critchance, &[&ap.ops_where(b!("WEAPON_CRIT_CHANCE"), |r| r.op == OP_ADD_BASE || r.set_base)]).to_py(py))?;
    // Ammo Efficiency cap (75%, damage.py AMMO_EFFICIENCY_CAP): every source,
    // Primary Compression included, keeps a quarter of the native cost.
    let ammo_cost = pmax(0.0, combine(prep.ammo_cost, &[&ap.ops(b!("WEAPON_AMMO_CONSUME_RATE"))])) * pmax(0.0, 1.0 - compression_ammo);
    out.set_item("ammo_cost", pmax(prep.ammo_cost * (1.0 - AMMO_EFFICIENCY_CAP), ammo_cost))?;
    out.set_item("co_bucket", ap.list(py, &co_idx)?)?;
    out.set_item("co_assumed_count", vsc)?;
    out.set_item("continuous", continuous)?;
    out.set_item("radial_only", prep.radial_only)?;
    out.set_item("explosion_radius_multiplier", combine(1.0, &[&ap.ops(b!("WEAPON_EXPLOSION_RADIUS"))]))?;
    let forced_py = PyDict::new(py);
    for (k, v) in forced.iter() {
        forced_py.set_item(k, *v)?;
    }
    out.set_item("native_forced_procs", forced_py)?;
    out.set_item("incarnon_charge_multiplier", pmax(0.0, combine(1.0, &[&ap.ops(b!("WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER"))])))?;
    out.set_item("low_crit_threshold", low_threshold)?;
    out.set_item("low_crit_damage_base", low_threshold.map(|_| crit_multiplier))?;
    out.set_item("low_crit_damage_bonus", low_bonus)?;
    out.set_item("ammo_pool_multishot_cost", pool_cost)?;
    out.set_item("ammo_pool_damage_bonus", if pool_ops.is_empty() { 0.0 } else { pool_multiplier - 1.0 })?;
    let mut victim_crit: Vec<(u8, f64)> = crit_ops.clone();
    victim_crit.extend(ap.ops(b!("WEAPON_VICTIM_CRIT_CHANCE")));
    out.set_item("victim_full_crit_chance", combine_num(critchance, &[&victim_crit]).sub(weapon_crit_chance).to_py(py))?;
    let victim_cd = pysum(ap.values(b!("WEAPON_VICTIM_CRIT_DAMAGE")));
    out.set_item("victim_full_crit_damage",
                 (combine(quantize(crit_base + victim_cd.f()), &[&relative]) - combine(quantize(crit_base), &[&relative])) * shield_crit)?;
    out.set_item("victim_low_health_multiplier", codamage.victim_low_health_multiplier)?;
    out.set_item("projectile_speed_multiplier", speed)?;
    out.set_item("charge_rate_multiplier", charge_rate)?;
    out.set_item("charge_seconds", charge_seconds)?;
    out.set_item("bow_draw_seconds", bow_draw)?;
    out.set_item("spread_min_deg", py.None())?;
    out.set_item("spread_max_deg", py.None())?;
    let crit_procs = PyDict::new(py);
    if !ap.empty(b!("WEAPON_SLASH_PROC_ON_CRIT_CHANCE")) {
        crit_procs.set_item("DT_SLASH", pysum(ap.values(b!("WEAPON_SLASH_PROC_ON_CRIT_CHANCE"))).to_py(py))?;
    }
    out.set_item("crit_proc_chances", crit_procs)?;
    let hits = PyTuple::new(py, extra_hits.iter().map(|(d, v, g)| (d.as_str(), *v, *g)))?;
    out.set_item("extra_hits", hits)?;
    out.set_item("cold_stack_damage", if cold_forced != 0.0 { Num::F(0.0) } else { cold_rate }.to_py(py))?;
    out.set_item("base_damage_bracket", codamage.base_bracket)?;
    out.set_item("frozen_damage_multiplier", if frozen_forced { 1.0 } else { 1.0 + frozen_bonus.f() })?;

    if !need_spec {
        return Ok((out, py.None()));
    }
    // ── CoSpec parts (mods_native.apply unpacks them in this order) ──
    let effect_class = prep.effect_class.bind(py);
    let mut scale_objs: Vec<Py<PyAny>> = Vec::new();
    for s in scale_effects.iter() {
        match s {
            Scale::Installed(i) => scale_objs.push(ap.objects[*i].clone_ref(py)),
            Scale::Synthetic(kind, op, value, source) => {
                let kwargs = PyDict::new(py);
                if let Some(source) = source {
                    kwargs.set_item("source_path", *source)?;
                }
                scale_objs.push(effect_class.call((*kind, *op, *value), Some(&kwargs))?.unbind());
            }
        }
    }
    let base_obj: Py<PyAny> = if base_scaled { dict_py(py, &Dict(base.clone()))?.into_any().unbind() } else { py.None() };
    let base_total_obj: Py<PyAny> = if base_scaled { PyFloat::new(py, base_total).into_any().unbind() } else { py.None() };
    let innate_list = PyList::new(py, prep.innate.iter().map(|(d, v)| (d.as_str(), *v)))?;
    let orb_obj: Py<PyAny> = match orb {
        Some((e, s, p, a)) => (e, s, p, a).into_pyobject(py)?.into_any().unbind(),
        None => py.None(),
    };
    let final_obj: Py<PyAny> = match &final_spec {
        Some((f, _)) => {
            let typed = PyDict::new(py);
            for (_, name, v) in typed_final.iter() {
                typed.set_item(name, *v)?;
            }
            (f.to_py(py), typed).into_pyobject(py)?.into_any().unbind()
        }
        None => py.None(),
    };
    let parts: Vec<Py<PyAny>> = vec![
        victim_status_count.clone().unbind(),
        PyList::new(py, scale_objs)?.into_any().unbind(),
        PyFloat::new(py, ordinary_scale).into_any().unbind(),
        PyFloat::new(py, spec_compression_mult).into_any().unbind(),
        PyBool::new(py, prep.gunco_independent).to_owned().into_any().unbind(),
        gunco_fraction.into_pyobject(py)?.into_any().unbind(),
        PyFloat::new(py, victim_damage).into_any().unbind(),
        PyFloat::new(py, co_fraction).into_any().unbind(),
        PyBool::new(py, prep.melee).to_owned().into_any().unbind(),
        ap.list(py, &melee_idx)?.into_any().unbind(),
        ap.list(py, &slam_idx)?.into_any().unbind(),
        base_obj,
        base_total_obj,
        PyFloat::new(py, elemental_base_total).into_any().unbind(),
        ap.list(py, &pre_idx)?.into_any().unbind(),
        ap.list(py, &post_idx)?.into_any().unbind(),
        innate_list.into_any().unbind(),
        pool_factor.into_pyobject(py)?.into_any().unbind(),
        copy_factor.into_pyobject(py)?.into_any().unbind(),
        orb_obj,
        final_obj,
        frozen_factor.into_pyobject(py)?.into_any().unbind(),
    ];
    Ok((out, PyTuple::new(py, parts)?.into_any().unbind()))
}
