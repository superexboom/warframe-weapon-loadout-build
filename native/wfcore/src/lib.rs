//! Native hot paths of the Portable damage engine.
//!
//! Every function here mirrors a Python reference in vendor/wfarsenal
//! operation for operation, so results are bit-identical; the Python side
//! falls back to the reference when this library is missing.
use pyo3::prelude::*;

pub mod co;
pub mod counters;
pub mod fx;
pub mod heat;
pub mod mods;
pub mod proc;
pub mod pymath;
pub mod replay;
pub mod stackable;
pub mod sustained;
pub mod tables;

/// `HeatChains` exposed for differential tests against the Python class.
#[pyclass(name = "HeatChains", unsendable)]
struct PyHeatChains {
    inner: heat::HeatChains,
}

#[pymethods]
impl PyHeatChains {
    #[new]
    fn new() -> Self {
        PyHeatChains { inner: heat::HeatChains::new() }
    }
    fn reset(&mut self) {
        self.inner.reset()
    }
    fn active(&self) -> bool {
        self.inner.active()
    }
    fn alive(&self) -> f64 {
        self.inner.alive()
    }
    fn count(&self) -> f64 {
        self.inner.count()
    }
    fn seed(&self) -> f64 {
        self.inner.seed()
    }
    fn expire(&mut self, t: f64) {
        self.inner.expire(t)
    }
    fn add(&mut self, t: f64, absence: f64, n: f64, seed: f64, duration: f64, scale: f64) {
        self.inner.add(t, absence, n, seed, duration, scale)
    }
    fn strip(&mut self, t: f64) -> f64 {
        self.inner.strip(t)
    }
}

#[pyclass(name = "CappedPool", unsendable)]
struct PyCappedPool {
    inner: proc::CappedPool,
}

#[pymethods]
impl PyCappedPool {
    #[new]
    fn new(cap: f64) -> Self {
        PyCappedPool { inner: proc::CappedPool::new(cap) }
    }
    fn reset(&mut self) {
        self.inner.reset()
    }
    fn __bool__(&self) -> bool {
        self.inner.is_live()
    }
    fn add(&mut self, end: f64, absence: f64, count: f64) -> bool {
        self.inner.add(end, absence, count)
    }
    fn expire(&mut self, t: f64) {
        self.inner.expire(t)
    }
    fn distribution(&mut self) -> Vec<f64> {
        self.inner.distribution().clone()
    }
    fn stats(&mut self) -> (f64, f64) {
        self.inner.stats()
    }
    #[getter]
    fn version(&self) -> u64 {
        self.inner.version
    }
}

#[pyclass(name = "StatusPresence", unsendable)]
struct PyStatusPresence {
    inner: proc::StatusPresence,
}

#[pymethods]
impl PyStatusPresence {
    #[new]
    fn new() -> Self {
        PyStatusPresence { inner: proc::StatusPresence::new() }
    }
    fn add(&mut self, expiry: f64, absence: f64) {
        self.inner.add(expiry, absence)
    }
    fn probability(&mut self, time: f64) -> f64 {
        self.inner.probability(time)
    }
}

#[pyclass(name = "KillAttribution", unsendable)]
struct PyKillAttribution {
    inner: proc::KillAttribution,
}

#[pymethods]
impl PyKillAttribution {
    #[new]
    #[pyo3(signature = (period, interval=None))]
    fn new(period: f64, interval: Option<f64>) -> Self {
        PyKillAttribution { inner: proc::KillAttribution::new(period, interval) }
    }
    fn reset(&mut self) {
        self.inner.reset()
    }
    #[pyo3(signature = (time, earlier, health, cv2, weak, direct=false))]
    fn add(&mut self, time: f64, earlier: f64, health: f64, cv2: f64, weak: f64, direct: bool) {
        self.inner.add(time, earlier, health, cv2, weak, direct)
    }
    #[pyo3(signature = (time, remaining, resume=None))]
    fn crossing(&self, time: f64, remaining: f64, resume: Option<f64>) -> PyResult<(f64, f64)> {
        self.inner
            .crossing(time, remaining, resume)
            .map_err(|_| pyo3::exceptions::PyIndexError::new_err("list index out of range"))
    }
}

/// `capped_stack_add` on plain lists of distributions (test hook).
#[pyfunction]
fn capped_stack_add_dists(dists: Vec<Vec<f64>>, absence: f64, count: f64, cap: i64) -> (bool, Vec<Vec<f64>>) {
    let mut arena: Vec<proc::DotInstance> = dists
        .into_iter()
        .map(|d| proc::DotInstance { dtype: 0, per: 0.0, count: 0.0, end: 0.0, dist: Some(d) })
        .collect();
    arena.push(proc::DotInstance { dtype: 0, per: 0.0, count: 0.0, end: 0.0, dist: None });
    let instance = arena.len() - 1;
    let mut items: Vec<usize> = (0..instance).collect();
    let added = proc::capped_stack_add(&mut items, &mut arena, absence, count, instance, cap);
    let live = if added { items } else { (0..instance).collect() };
    (added, live.into_iter().map(|i| arena[i].dist.clone().unwrap()).collect())
}

/// Native timing counters: [(name, seconds, calls)].
#[pyfunction]
#[pyo3(name = "counters", signature = (reset=false, enable=None, only=None))]
fn native_counters(reset: bool, enable: Option<bool>, only: Option<Vec<String>>) -> Vec<(&'static str, f64, u64)> {
    if let Some(on) = enable {
        counters::enable(on);
    }
    if let Some(names) = only {
        counters::select(&names);
    }
    counters::snapshot(reset)
}

#[pyfunction]
fn py_sum(values: Vec<f64>) -> f64 {
    pymath::psum(values)
}

#[pyfunction]
fn c_math(name: &str, x: f64, y: f64) -> f64 {
    match name {
        "log" => pymath::log(x),
        "expm1" => pymath::expm1(x),
        "erfc" => pymath::erfc(x),
        "pow" => pymath::pow(x, y),
        _ => f64::NAN,
    }
}

#[pymodule]
fn wfcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ABI", 1)?;
    m.add("ALT_EMBEDDED_LIFECYCLE", 1)?;
    m.add("MELEE_INITIAL_COMBO_RECOVERY", 1)?;
    m.add("COMPANION_PROJECTILE_SEQUENCE", 1)?;
    m.add("PHYSICAL_PROJECTILE_LANES", 1)?;
    m.add("SOURCE_OWNED_FIELDS", 1)?;
    m.add("INDEPENDENT_FINITE_FIELDS", 1)?;
    m.add("NATIVE_FIRE_ITERATION_LOCK", 1)?;
    m.add("MAGAZINE_CHARGE_VOLLEY", 1)?;
    m.add("KILL_CHARGED_WINDUP", 1)?;
    m.add("ORDINARY_CHARGED_WINDUP", 1)?;
    m.add("FULL_CLIP_CHARGE_WAIT_POLICY", 1)?;
    m.add("NEUTRAL_FINITE_FIELD_SOURCE", 2)?;
    m.add("NATIVE_FIRE_COOLDOWN", 1)?;
    m.add("DELAYED_RADIAL_EVENTS", 2)?;
    m.add("RADIAL_VICTIM_CRIT", 1)?;
    m.add("ENERVATE_PROBABILISTIC_HITS", 1)?;
    m.add("IGNORE_HEADSHOT_BONUS", 1)?;
    m.add("STUG_IDEAL_DETONATION", 1)?;
    m.add("STUG_AREA_DIRECT", 1)?;
    m.add("SNIPER_INCARNON_COMBO", 1)?;
    m.add("PERSISTENT_RADIALS", 1)?;
    m.add("SNIPER_COMBO_STATUS", 1)?;
    m.add("RELOAD_SCALED_TRANSFORMS", 1)?;
    m.add_class::<PyHeatChains>()?;
    m.add_class::<PyCappedPool>()?;
    m.add_class::<PyStatusPresence>()?;
    m.add_class::<PyKillAttribution>()?;
    m.add_function(wrap_pyfunction!(capped_stack_add_dists, m)?)?;
    m.add_function(wrap_pyfunction!(py_sum, m)?)?;
    m.add_function(wrap_pyfunction!(native_counters, m)?)?;
    m.add_function(wrap_pyfunction!(replay::trajectory, m)?)?;
    m.add_function(wrap_pyfunction!(replay::trajectory_health_batch, m)?)?;
    m.add("NativeUnsupported", m.py().get_type::<replay::NativeUnsupported>())?;
    m.add("ReplayRunaway", m.py().get_type::<replay::ReplayRunaway>())?;
    m.add_function(wrap_pyfunction!(c_math, m)?)?;
    m.add_class::<mods::ModsPrep>()?;
    m.add_function(wrap_pyfunction!(mods::apply_mods, m)?)?;
    m.add_class::<sustained::SustainedTarget>()?;
    m.add_function(wrap_pyfunction!(sustained::sustained_status, m)?)?;
    Ok(())
}
