//! The rest of `proc_probability`: CappedPool, StatusPresence,
//! KillAttribution, capped_stack_add / stack_alive. Same operation order as
//! the Python reference.

use crate::pymath::{erfc, expm1, floor_i, log, pmax, pmin, pow, psum, sqrt, ceil_i};
use std::cmp::Ordering;
use std::collections::{BTreeMap, BinaryHeap, VecDeque};
use std::rc::Rc;

// Electricity/Gas conditional moments, in reference operation order.
#[derive(Clone, Copy)]
pub struct PileOutcome {
    pub probability: f64,
    pub count: usize,
    pub seed: f64,
    pub accumulator: f64,
    pub landing: f64,
    pub weak: bool,
}

#[derive(Clone)]
pub struct PileBucket {
    pub count: usize,
    // Q, seed, accumulator, landing, weak landing and their joint moments.
    pub values: [f64; 9],
}

#[derive(Clone)]
pub struct PileKernel {
    pub rows: Vec<PileBucket>,
    pub mass: f64,
    low: Vec<PileOutcome>,
}

impl PileKernel {
    pub fn new(outcomes: &[PileOutcome]) -> Self {
        let mut rows: Vec<PileBucket> = Vec::new();
        let mut low = Vec::new();
        for o in outcomes {
            let q = o.probability;
            if q <= 0.0 { continue; }
            let index = match rows.iter().position(|r|r.count==o.count) {
                Some(i) => i,
                None => { rows.push(PileBucket {count:o.count,values:[0.0;9]}); rows.len()-1 }
            };
            let v = &mut rows[index].values;
            v[0] += q;
            if o.count > 0 {
                if o.seed < 0.5 { low.push(*o); }
                v[1] += q*o.seed;
                v[2] += q*o.accumulator;
                v[3] += q*o.landing;
                if o.weak { v[4] += q*o.landing; }
                v[5] += (q*o.seed)*o.landing;
                if o.weak { v[6] += (q*o.seed)*o.landing; }
                v[7] += (q*o.accumulator)*o.landing;
                if o.weak { v[8] += (q*o.accumulator)*o.landing; }
            }
        }
        rows.sort_by_key(|r|r.count);
        let mass=psum(rows.iter().map(|r|r.values[0]));
        Self {rows,mass,low}
    }
}

#[derive(Clone)]
struct PileEvent {
    end: f64,
    kernel: Rc<PileKernel>,
    origin: Option<u8>,
    source: Option<usize>,
}

#[derive(Clone)]
pub struct ProcPile {
    cap: Option<usize>,
    events: Vec<PileEvent>,
    pub next: Option<f64>,
    pub token: u64,
    cached: Option<(f64, [f64; 4], Option<u8>, Option<usize>)>,
    low_count: usize,
    pub radial_floor_limited: bool,
}

pub struct PileTick {
    pub damage: f64,
    pub weak_damage: f64,
    pub count: f64,
    pub presence: f64,
    pub origin: Option<u8>,
    pub source: Option<usize>,
    pub schedule: Option<(f64, u64)>,
}

impl ProcPile {
    pub fn new(cap: Option<usize>) -> Self {
        Self { cap, events: Vec::new(), next: None, token: 1, cached: None,
            low_count: 0, radial_floor_limited: false }
    }
    pub fn reset(&mut self) {
        self.events.clear();
        self.low_count = 0;
        self.next = None;
        self.token += 1;
        self.cached = None;
    }
    pub fn add(&mut self, t: f64, duration: f64, kernel: Rc<PileKernel>, origin: Option<u8>, source: Option<usize>) -> Option<(f64, u64)> {
        if duration <= 0.0 || !kernel.rows.iter().any(|r| r.values[0] > 0.0 && r.count > 0) { return None; }
        let schedule = if self.next.is_none() {
            self.next = Some(t);
            self.token += 1;
            Some((t, self.token))
        } else { None };
        let end = self.next.unwrap() + (ceil_i(duration - 1e-9).max(1) as f64) - 1.0;
        self.low_count += usize::from(!kernel.low.is_empty());
        self.events.push(PileEvent { end, kernel, origin, source });
        self.cached = None;
        schedule
    }
    pub fn moments(&mut self, t: f64) -> [f64; 4] {
        if let Some((when, value, _, _)) = self.cached { if when == t { return value; } }
        let _timer = crate::counters::Timer::start(crate::counters::PILE_MOMENTS);
        let (mut result, origin, source) = match self.cap {
            Some(10) => self.compute_moments::<true, 11>(10, t),
            Some(cap) => self.compute_moments::<true, 11>(cap, t),
            None => self.compute_moments::<false, 2>(1, t),
        };
        if self.low_count != 0 {
            if let Some(correction) = self.floor_correction(t) {
                result[0] += correction[0]; result[1] += correction[1];
            } else {
                self.radial_floor_limited = true;
            }
        }
        self.cached = Some((t, result, origin, source));
        result
    }
    fn compute_moments<const BOUNDED: bool, const ROWS: usize>(&self, cap: usize, t: f64)
        -> ([f64; 4], Option<u8>, Option<usize>) {
        let cutoff = t - 1e-9;
        let mut dp = [[0.0; 9]; ROWS];
        dp[0][0] = 1.0;
        let (mut origin, mut source) = (None, None);
        for event in self.events.iter().rev() {
            let live = event.end >= cutoff;
            let mut next = [[0.0; 9]; ROWS];
            for (k, row) in dp[..=cap].iter().enumerate() {
                if row[0] <= 0.0 { continue; }
                if BOUNDED && k == cap {
                    for (i, value) in row.iter().enumerate() { next[cap][i] += event.kernel.mass * value; }
                    continue;
                }
                for bucket in &event.kernel.rows {
                    let [q,b,c,l,hn,bl,bh,cl,ch] = bucket.values;
                    if q <= 0.0 { continue; }
                    let n = bucket.count;
                    let dest = if BOUNDED { cap.min(k + n) } else { usize::from(k > 0 || n > 0) };
                    let mut values = row.map(|x|q*x);
                    if n > 0 && k == 0 {
                        values[1] = row[0]*l;
                        values[2] = row[0]*hn;
                    }
                    let kept = if BOUNDED { n.min(cap-k) } else { n };
                    if kept > 0 && live {
                        origin = event.origin; source = event.source;
                        if k == 0 {
                            values[3] += kept as f64 * row[0] * bl;
                            values[4] += kept as f64 * row[0] * bh;
                            values[5] = row[0]*cl;
                            values[6] = row[0]*ch;
                        } else {
                            values[3] += kept as f64 * row[1] * b;
                            values[4] += kept as f64 * row[2] * b;
                            values[5] = row[1]*c;
                            values[6] = row[2]*c;
                        }
                        values[7] += kept as f64 * row[0] * q;
                        values[8] = row[0]*q;
                    }
                    for (i, value) in values.iter().enumerate() { next[dest][i] += value; }
                }
            }
            dp = next;
        }
        let total = |i: usize| psum(dp[..=cap].iter().map(|row| row[i]));
        let result = [total(3) + total(5), total(4) + total(6), total(7), total(8)];
        (result, origin, source)
    }
    fn floor_correction(&self, t: f64) -> Option<[f64; 2]> {
        // Only worlds below a summed half-seed of .5 need a correction.
        let mut dp = BTreeMap::from([((0usize, 0u64, false), [1.0, 0.0, 0.0])]);
        for event in self.events.iter().rev() {
            let live = event.end >= t - 1e-9;
            let mut next = BTreeMap::<_, [f64; 3]>::new();
            for (&(k, bits, paid), &[p, f, h]) in &dp {
                if p <= 0.0 { continue; }
                let mut add = |key, values: [f64; 3]| {
                    for (row, v) in next.entry(key).or_insert([0.0; 3]).iter_mut().zip(values) { *row += v; }
                    next.len() <= 4096
                };
                if self.cap == Some(k) {
                    let mass = event.kernel.mass;
                    if !add((k, bits, paid), [mass*p, mass*f, mass*h]) { return None; }
                    continue;
                }
                let mut visit = |n: usize, q: f64, half_seed: f64, landing: f64, weak: f64| {
                    let kept = if live { self.cap.map_or(n, |cap| n.min(cap-k)) } else { 0 };
                    let seed = f64::from_bits(bits) + kept as f64 * half_seed;
                    if q <= 0.0 || seed >= 0.5 { return true; }
                    let rank = self.cap.map_or(usize::from(k != 0 || n != 0), |cap| cap.min(k+n));
                    let values = if n != 0 && k == 0 { [q*p, p*landing, p*weak] } else { [q*p,q*f,q*h] };
                    add((rank, seed.to_bits(), paid || kept != 0), values)
                };
                for bucket in &event.kernel.rows {
                    let r = bucket.values;
                    if (!live || bucket.count == 0) && !visit(bucket.count, r[0], 0.0, r[3], r[4]) { return None; }
                }
                if live {
                    for o in &event.kernel.low {
                        let landing = o.probability * o.landing;
                        if !visit(o.count, o.probability, o.seed, landing, if o.weak { landing } else { 0.0 }) { return None; }
                    }
                }
            }
            dp = next;
            if dp.is_empty() { break; }
        }
        Some([1, 2].map(|i| psum(dp.iter().filter(|((_, _, paid), _)| *paid)
            .map(|((_, bits, _), v)| (0.5 - f64::from_bits(*bits)) * v[i]))))
    }
    pub fn tick(&mut self, t: f64, token: u64) -> Option<PileTick> {
        if token != self.token || self.next.is_none() || (t-self.next.unwrap()).abs() > 1e-8 { return None; }
        let result = self.moments(t);
        let (_, _, origin, source) = self.cached.unwrap();
        self.next = Some(t + 1.0);
        let oldest = self.events.iter().position(|e| e.end >= t+1.0-1e-9);
        let schedule = match oldest {
            None => { self.reset(); None },
            Some(i) => {
                self.low_count -= self.events[..i].iter().filter(|e| !e.kernel.low.is_empty()).count();
                self.events.drain(..i);
                self.cached = None;
                Some((t + 1.0, self.token))
            }
        };
        Some(PileTick { damage: result[0], weak_damage: result[1], count: result[2], presence: result[3], origin, source, schedule })
    }
}

// ── CappedPool ────────────────────────────────────────────────────────────

#[path = "bake_pool.rs"]
pub(crate) mod bake_pool;

pub type Kernel = Vec<(usize, f64)>;

#[derive(Clone)]
struct Arrival {
    terms: [(usize, f64); 3],
    len: usize,
}

impl Arrival {
    fn terms(&self) -> &[(usize, f64)] {
        &self.terms[..self.len]
    }
}

fn arrival(absence: f64, count: f64, cap: usize) -> Option<Arrival> {
    let p = pmin(1.0, pmax(0.0, 1.0 - absence));
    if p <= 0.0 || count <= 0.0 {
        return None;
    }
    let size = count / p;
    let low = floor_i(size + 1e-9);
    let frac = pmax(0.0, size - low as f64);
    let mut kernel = Arrival { terms: [(0, 0.0); 3], len: 0 };
    for (shift, weight) in [(0i64, 1.0 - p), (low, p * (1.0 - frac)), (low + 1, p * frac)] {
        if weight > 0.0 {
            let key = (shift.max(0) as usize).min(cap);
            if let Some(slot) = kernel.terms[..kernel.len].iter_mut().find(|(k, _)| *k == key) {
                slot.1 += weight;
            } else {
                kernel.terms[kernel.len] = (key, weight);
                kernel.len += 1;
            }
        }
    }
    Some(kernel)
}

pub fn arrival_kernel(absence: f64, count: f64, cap: usize) -> Option<Kernel> {
    arrival(absence, count, cap).map(|kernel| kernel.terms().to_vec())
}

pub fn fold(dist: &[f64], kernel: &Kernel, cap: usize) -> Vec<f64> {
    let mut out = vec![0.0; cap + 1];
    fold_into(dist, kernel, cap, &mut out);
    out
}

fn fold_into(dist: &[f64], kernel: &[(usize, f64)], cap: usize, out: &mut [f64]) {
    for &(shift, weight) in kernel {
        for (k, &value) in dist.iter().enumerate() {
            if value != 0.0 {
                out[(k + shift).min(cap)] += weight * value;
            }
        }
    }
}

#[derive(Clone)]
pub struct CappedPool {
    pub cap: usize,
    front: Vec<f64>,
    front_dists: Vec<f64>,
    back: Vec<(f64, Arrival)>,
    back_dist: Vec<f64>,
    fold_scratch: Vec<f64>,
    bake_prefix: Option<bake_pool::Key>,
    bake_enabled: bool,
    dist: Vec<f64>,
    dist_valid: bool,
    stats: Option<(f64, f64)>,
    pub version: u64,
}

impl CappedPool {
    pub fn new(cap: f64) -> Self {
        let cap = cap as usize;
        let mut back_dist = vec![0.0; cap + 1];
        back_dist[0] = 1.0;
        CappedPool {
            cap,
            front: Vec::new(),
            front_dists: Vec::new(),
            back: Vec::new(),
            back_dist,
            fold_scratch: Vec::new(),
            bake_prefix: None,
            bake_enabled: cap == bake_pool::CAP && bake_pool::enabled(),
            dist: Vec::new(),
            dist_valid: false,
            stats: None,
            version: 1,
        }
    }

    fn reset_back_distribution(&mut self) {
        self.back_dist.fill(0.0);
        self.back_dist[0] = 1.0;
        self.bake_prefix = None;
    }

    pub fn reset(&mut self) {
        self.front.clear();
        self.front_dists.clear();
        self.back.clear();
        self.reset_back_distribution();
        self.dist_valid = false;
        self.stats = None;
        self.version += 1;
    }

    pub fn is_live(&self) -> bool {
        !self.front.is_empty() || !self.back.is_empty()
    }

    pub fn add(&mut self, end: f64, absence: f64, count: f64) -> bool {
        let kernel = match arrival(absence, count, self.cap) {
            Some(k) => k,
            None => return false,
        };
        if !self.bake_enabled || !bake_pool::copy_prefix(
            &mut self.bake_prefix, self.back.len() + 1, absence, count, &mut self.back_dist,
        ) {
            self.fold_scratch.resize(self.cap + 1, 0.0);
            self.fold_scratch.fill(0.0);
            fold_into(&self.back_dist, kernel.terms(), self.cap, &mut self.fold_scratch);
            std::mem::swap(&mut self.back_dist, &mut self.fold_scratch);
        }
        self.back.push((end, kernel));
        self.dist_valid = false;
        self.stats = None;
        self.version += 1;
        true
    }

    fn transfer(&mut self) {
        self.reset_back_distribution();
        let width = self.cap + 1;
        self.front.reserve(self.back.len());
        self.front_dists.reserve(width * self.back.len());
        // Rolling front suffixes occupy one buffer; each fold reads the
        // preceding suffix and writes directly into the newly appended row.
        while let Some((end, kernel)) = self.back.pop() {
            let offset = self.front_dists.len();
            self.front_dists.resize(offset + width, 0.0);
            let (previous, out) = self.front_dists.split_at_mut(offset);
            let dist = if offset == 0 { &self.back_dist } else { &previous[offset - width..] };
            fold_into(dist, kernel.terms(), self.cap, out);
            self.front.push(end);
        }
    }

    pub fn expire(&mut self, t: f64) {
        loop {
            if self.front.is_empty() {
                if self.back.is_empty() || self.back[0].0 >= t - 1e-9 {
                    return;
                }
                self.transfer();
            }
            if *self.front.last().unwrap() >= t - 1e-9 {
                return;
            }
            self.front.pop();
            self.front_dists.truncate(self.front.len() * (self.cap + 1));
            self.dist_valid = false;
            self.stats = None;
            self.version += 1;
        }
    }

    pub fn distribution(&mut self) -> &Vec<f64> {
        if self.front.is_empty() {
            return &self.back_dist;
        }
        if !self.dist_valid {
            let cap = self.cap;
            self.dist.resize(cap + 1, 0.0);
            self.dist.fill(0.0);
            let agg = &self.front_dists[self.front_dists.len() - (cap + 1)..];
            for (i, &x) in agg.iter().enumerate() {
                if x != 0.0 {
                    for (j, &y) in self.back_dist.iter().enumerate() {
                        if y != 0.0 {
                            self.dist[(i + j).min(cap)] += x * y;
                        }
                    }
                }
            }
            self.dist_valid = true;
        }
        &self.dist
    }

    pub fn stats(&mut self) -> (f64, f64) {
        if self.stats.is_none() {
            let dist = self.distribution();
            let present = 1.0 - dist[0];
            let mean = psum(dist.iter().enumerate().map(|(k, v)| k as f64 * *v));
            self.stats = Some((present, mean));
        }
        self.stats.unwrap()
    }
}

// ── StatusPresence ────────────────────────────────────────────────────────

#[derive(Clone)]
struct PresenceEvent {
    expiry: f64,
    serial: u64,
    value: Option<f64>,
}
impl PartialEq for PresenceEvent {
    fn eq(&self, o: &Self) -> bool {
        self.expiry == o.expiry && self.serial == o.serial
    }
}
impl Eq for PresenceEvent {}
impl PartialOrd for PresenceEvent {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for PresenceEvent {
    fn cmp(&self, o: &Self) -> Ordering {
        o.expiry.total_cmp(&self.expiry).then(o.serial.cmp(&self.serial))
    }
}

#[derive(Clone, Default)]
pub struct StatusPresence {
    events: BinaryHeap<PresenceEvent>,
    log_absence: f64,
    certain: i64,
    serial: u64,
}

impl StatusPresence {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add(&mut self, expiry: f64, absence: f64) {
        if absence >= 1.0 {
            return;
        }
        let value = if absence > 0.0 { Some(log(absence)) } else { None };
        self.serial += 1;
        self.events.push(PresenceEvent { expiry, serial: self.serial, value });
        match value {
            None => self.certain += 1,
            Some(v) => self.log_absence += v,
        }
    }

    pub fn probability(&mut self, time: f64) -> f64 {
        while let Some(top) = self.events.peek() {
            if !(top.expiry < time - 1e-9) {
                break;
            }
            let e = self.events.pop().unwrap();
            match e.value {
                None => self.certain -= 1,
                Some(v) => self.log_absence -= v,
            }
        }
        if self.certain != 0 {
            1.0
        } else {
            -expm1(pmin(self.log_absence, 0.0))
        }
    }
}

// ── capped_stack_add / stack_alive (gas) ──────────────────────────────────

#[derive(Clone, Debug)]
pub struct DotInstance {
    pub dtype: u32,
    pub per: f64,
    pub count: f64,
    pub end: f64,
    pub dist: Option<Vec<f64>>,
}

pub fn stack_alive(instance: &DotInstance) -> f64 {
    match &instance.dist {
        None => 1.0,
        Some(d) => psum(d.iter().copied()),
    }
}

/// Returns whether the application was added (Python's return value).
pub fn capped_stack_add(items: &mut Vec<usize>, arena: &mut [DotInstance], absence: f64, count: f64,
                        instance: usize, cap: i64) -> bool {
    let p = pmin(1.0, pmax(0.0, 1.0 - absence));
    if p <= 0.0 || count <= 0.0 {
        return false;
    }
    let size = count / p;
    let low = floor_i(size + 1e-9);
    let frac = pmax(0.0, size - low as f64);
    let mut shifts: Vec<(i64, f64)> = Vec::new();
    if p < 1.0 {
        shifts.push((0, 1.0 - p));
    }
    if low != 0 && frac < 1.0 - 1e-9 {
        shifts.push((low, p * (1.0 - frac)));
    }
    if frac > 1e-9 {
        shifts.push((low + 1, p * frac));
    }
    for &item in items.iter() {
        let dist = arena[item].dist.clone().unwrap_or_default();
        let limit = dist.len() as i64;
        let mut new = vec![0.0; dist.len()];
        for &(shift, weight) in &shifts {
            if weight <= 0.0 {
                continue;
            }
            let mut k = 0i64;
            while k < limit - shift {
                new[(k + shift) as usize] += weight * dist[k as usize];
                k += 1;
            }
        }
        arena[item].dist = Some(new);
    }
    items.retain(|&item| psum(arena[item].dist.as_ref().unwrap().iter().copied()) > 1e-9);
    let zeros = (cap - ceil_i(size - 1e-9)).max(0) as usize;
    let mut dist = vec![1.0];
    dist.extend(std::iter::repeat_n(0.0, zeros));
    arena[instance].dist = Some(dist);
    items.push(instance);
    true
}

// ── KillAttribution ───────────────────────────────────────────────────────

#[derive(Clone, Copy)]
pub struct Row {
    pub time: f64,
    pub health: f64,
    pub weak: f64,
    pub variance: f64,
    pub own: f64,
    pub direct: bool,
}

#[derive(Clone)]
pub struct KillAttribution {
    period: f64,
    interval: f64,
    horizon: i64,
    limit: usize,
    rows: VecDeque<Row>,
    health_variance: f64,
    earlier: [f64; 4],
}

pub struct EmptyRecent;

impl KillAttribution {
    pub fn new(period: f64, interval: Option<f64>) -> Self {
        let interval = match interval {
            Some(v) if v != 0.0 => v,
            _ => period,
        };
        let mut k = KillAttribution {
            period,
            interval,
            horizon: 3,
            limit: 4096,
            rows: VecDeque::new(),
            health_variance: 0.0,
            earlier: [0.0; 4],
        };
        k.reset();
        k
    }

    pub fn reset(&mut self) {
        self.rows.clear();
        self.health_variance = 0.0;
        self.earlier = [0.0, 0.0, f64::INFINITY, f64::NEG_INFINITY];
    }

    pub fn add(&mut self, time: f64, earlier: f64, health: f64, cv2: f64, weak: f64, direct: bool) {
        let cv2 = pmax(0.0, cv2);
        if earlier > 0.0 {
            let e = &mut self.earlier;
            e[0] += earlier * earlier * cv2;
            e[1] += earlier;
            e[2] = pmin(e[2], time);
            e[3] = pmax(e[3], time);
        }
        if health > 0.0 {
            self.health_variance += health * health * cv2;
            if self.rows.len() == self.limit {
                self.rows.pop_front();
            }
            self.rows.push_back(Row {
                time,
                health,
                weak,
                variance: self.health_variance,
                own: health * health * cv2,
                direct,
            });
        }
    }

    /// (P(weak-point kill), renewal shift); Err when Python would raise
    /// (no recent row in the attribution period).
    pub fn crossing(&self, time: f64, remaining: f64, resume: Option<f64>) -> Result<(f64, f64), EmptyRecent> {
        let last = match self.rows.back() {
            None => return Ok((0.0, 0.0)),
            Some(r) => *r,
        };
        let recent: Vec<Row> = self.rows.iter().copied().filter(|r| r.time > time - self.period + 1e-9).collect();
        let mut offset = 0.0;
        let [variance_e, damage_e, first, lastt] = self.earlier;
        if damage_e > 0.0 && variance_e > 0.0 {
            let rate_e = damage_e / pmax(lastt - first, self.period);
            let rate_h = psum(recent.iter().map(|r| r.health)) / self.period;
            offset = variance_e * pow(rate_h / rate_e, 2.0);
        }
        if self.health_variance + offset <= 0.0 {
            return Ok((last.weak, 0.0));
        }
        let dead = |after: f64, variance: f64| -> f64 {
            let sigma = sqrt(pmax(variance + offset, 1e-300));
            0.5 * erfc(after / sigma / sqrt(2.0))
        };
        let mut events: Vec<(f64, f64, f64)> = Vec::new();
        let mut after = remaining - last.health;
        for r in self.rows.iter().rev() {
            if after > 8.0 * sqrt(r.variance + offset) {
                break;
            }
            events.push((r.time, dead(after, r.variance), r.weak));
            after += r.health;
        }
        events.reverse();
        if recent.is_empty() {
            return Err(EmptyRecent);
        }
        let times: Vec<f64> = recent.iter().map(|r| r.time).collect();
        let gap = if times.len() > 1 {
            (times[times.len() - 1] - times[0]) / (times.len() - 1) as f64
        } else {
            self.interval
        };
        let cycle_length = times[times.len() - 1] - times[0] + gap;
        let delay = match resume {
            Some(r) => pmax(0.0, r - (time + gap)),
            None => 0.0,
        };
        let mut future: Vec<(f64, f64, f64, f64, bool)> = Vec::with_capacity(recent.len() * self.horizon as usize);
        for cycle in 1..=self.horizon {
            for r in &recent {
                let when = r.time + cycle as f64 * cycle_length + if r.direct { delay } else { 0.0 };
                future.push((when, r.health, r.weak, r.own, r.direct));
            }
        }
        future.sort_by(|a, b| {
            a.0.partial_cmp(&b.0)
                .unwrap()
                .then(a.1.partial_cmp(&b.1).unwrap())
                .then(a.2.partial_cmp(&b.2).unwrap())
                .then(a.3.partial_cmp(&b.3).unwrap())
                .then(a.4.cmp(&b.4))
        });
        let mut after = remaining - last.health;
        let mut variance = self.health_variance;
        for f in &future {
            after -= f.1;
            variance += f.3;
            events.push((f.0, dead(after, variance), f.2));
        }
        let mut hits: Vec<f64> = self.rows.iter().filter(|r| r.direct).map(|r| r.time).collect();
        hits.extend(future.iter().filter(|f| f.4).map(|f| f.0));
        if let Some(r) = resume {
            hits.push(r);
        }
        hits.sort_by(|a, b| a.partial_cmp(b).unwrap());
        hits.dedup_by(|a, b| a == b);
        let next_hit = |when: f64| -> f64 {
            let key = when + 1e-9;
            let index = hits.partition_point(|h| *h <= key);
            if index < hits.len() {
                hits[index]
            } else {
                when + gap
            }
        };
        let (mut total, mut weak, mut start, mut reached) = (0.0f64, 0.0f64, 0.0f64, 0.0f64);
        for (when, probability, w) in events {
            let probability = pmax(probability, reached);
            let p = probability - reached;
            reached = probability;
            total += p;
            weak += p * w;
            start += p * next_hit(when);
        }
        if total <= 0.0 {
            return Ok((last.weak, 0.0));
        }
        Ok((pmin(1.0, pmax(0.0, weak / total)), start / total - next_hit(time)))
    }
}
