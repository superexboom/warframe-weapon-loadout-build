//! The rest of `proc_probability`: CappedPool, StatusPresence,
//! KillAttribution, capped_stack_add / stack_alive. Same operation order as
//! the Python reference.

use crate::pymath::{erfc, expm1, floor_i, log, pmax, pmin, pow, psum, sqrt, ceil_i};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};

// ── CappedPool ────────────────────────────────────────────────────────────

pub type Kernel = Vec<(usize, f64)>;

pub fn arrival_kernel(absence: f64, count: f64, cap: usize) -> Option<Kernel> {
    let p = pmin(1.0, pmax(0.0, 1.0 - absence));
    if p <= 0.0 || count <= 0.0 {
        return None;
    }
    let size = count / p;
    let low = floor_i(size + 1e-9);
    let frac = pmax(0.0, size - low as f64);
    let mut kernel: Kernel = Vec::new();
    for (shift, weight) in [(0i64, 1.0 - p), (low, p * (1.0 - frac)), (low + 1, p * frac)] {
        if weight > 0.0 {
            let key = (shift.max(0) as usize).min(cap);
            if let Some(slot) = kernel.iter_mut().find(|(k, _)| *k == key) {
                slot.1 += weight;
            } else {
                kernel.push((key, weight));
            }
        }
    }
    Some(kernel)
}

pub fn fold(dist: &[f64], kernel: &Kernel, cap: usize) -> Vec<f64> {
    let mut out = vec![0.0; cap + 1];
    for &(shift, weight) in kernel {
        for (k, &value) in dist.iter().enumerate() {
            if value != 0.0 {
                out[(k + shift).min(cap)] += weight * value;
            }
        }
    }
    out
}

#[derive(Clone)]
pub struct CappedPool {
    pub cap: usize,
    front: Vec<(f64, Kernel, Vec<f64>)>,
    back: Vec<(f64, Kernel)>,
    back_dist: Vec<f64>,
    dist: Option<Vec<f64>>,
    stats: Option<(f64, f64)>,
    pub version: u64,
}

impl CappedPool {
    pub fn new(cap: f64) -> Self {
        let cap = cap as usize;
        let mut pool = CappedPool {
            cap,
            front: Vec::new(),
            back: Vec::new(),
            back_dist: Vec::new(),
            dist: None,
            stats: None,
            version: 0,
        };
        pool.reset();
        pool
    }

    fn unit(&self) -> Vec<f64> {
        let mut v = vec![0.0; self.cap + 1];
        v[0] = 1.0;
        v
    }

    pub fn reset(&mut self) {
        self.front.clear();
        self.back.clear();
        self.back_dist = self.unit();
        self.dist = None;
        self.stats = None;
        self.version += 1;
    }

    pub fn is_live(&self) -> bool {
        !self.front.is_empty() || !self.back.is_empty()
    }

    pub fn add(&mut self, end: f64, absence: f64, count: f64) -> bool {
        let kernel = match arrival_kernel(absence, count, self.cap) {
            Some(k) => k,
            None => return false,
        };
        self.back_dist = fold(&self.back_dist, &kernel, self.cap);
        self.back.push((end, kernel));
        self.dist = None;
        self.stats = None;
        self.version += 1;
        true
    }

    fn transfer(&mut self) {
        let mut dist = self.unit();
        while let Some((end, kernel)) = self.back.pop() {
            dist = fold(&dist, &kernel, self.cap);
            self.front.push((end, kernel, dist.clone()));
        }
        self.back_dist = self.unit();
    }

    pub fn expire(&mut self, t: f64) {
        loop {
            if self.front.is_empty() {
                if self.back.is_empty() || self.back[0].0 >= t - 1e-9 {
                    return;
                }
                self.transfer();
            }
            if self.front.last().unwrap().0 >= t - 1e-9 {
                return;
            }
            self.front.pop();
            self.dist = None;
            self.stats = None;
            self.version += 1;
        }
    }

    pub fn distribution(&mut self) -> &Vec<f64> {
        if self.dist.is_none() {
            let d = if self.front.is_empty() {
                self.back_dist.clone()
            } else {
                let cap = self.cap;
                let mut out = vec![0.0; cap + 1];
                let agg = &self.front.last().unwrap().2;
                for (i, &x) in agg.iter().enumerate() {
                    if x != 0.0 {
                        for (j, &y) in self.back_dist.iter().enumerate() {
                            if y != 0.0 {
                                out[(i + j).min(cap)] += x * y;
                            }
                        }
                    }
                }
                out
            };
            self.dist = Some(d);
        }
        self.dist.as_ref().unwrap()
    }

    pub fn stats(&mut self) -> (f64, f64) {
        if self.stats.is_none() {
            let dist = self.distribution().clone();
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
