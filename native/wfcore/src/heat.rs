//! `proc_probability.HeatChains`, operation for operation.
//!
//! Python dicts keyed by floats become `FMap` (insertion ordered, keyed by
//! the value's bits with -0.0 folded into 0.0, like Python's float equality).
//! Items the Python code shares by reference between its deques and the
//! step heap live in arenas and are referred to by index.

use crate::pymath::{pmax, pmin, psum, trunc_i};
use crate::fx::FxIndexMap;
use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};

pub const HEAT_RAMP: [f64; 5] = [0.0, 0.15, 0.30, 0.40, 0.50];
pub const HEAT_DECAY: [f64; 5] = [0.5, 0.4, 0.3, 0.15, 0.0];

#[inline]
pub fn fkey(x: f64) -> u64 {
    if x == 0.0 {
        0
    } else {
        x.to_bits()
    }
}
#[inline]
pub fn fval(k: u64) -> f64 {
    f64::from_bits(k)
}

pub type FMap = FxIndexMap<u64, f64>;

#[inline]
fn fget(m: &FMap, k: f64) -> f64 {
    *m.get(&fkey(k)).unwrap_or(&0.0)
}

pub fn ramp_index(age: f64, scale: f64) -> usize {
    let raw = trunc_i((age + 1e-9) / pmax(0.5 * scale, 1e-9));
    raw.clamp(0, 4) as usize
}

pub fn decay_steps(level: f64) -> Vec<f64> {
    HEAT_DECAY.iter().copied().filter(|v| *v <= level + 1e-9).collect()
}

pub fn decay_index(age: f64, scale: f64, steps: &[f64]) -> usize {
    let raw = trunc_i(pmax(0.0, age) / pmax(1.5 * scale, 1e-9));
    let last = steps.len() as i64 - 1;
    raw.min(last).max(0) as usize
}

pub fn heat_ramp(age: f64, scale: f64) -> f64 {
    HEAT_RAMP[ramp_index(age, scale)]
}

struct DeadItem {
    end: f64,
    scale: f64,
    levels: FMap,
    step: FxIndexMap<u64, usize>,
    steps: FxIndexMap<u64, Vec<f64>>,
    cleared: bool,
}

struct BoostItem {
    start: f64,
    scale: f64,
    levels: FMap,
    ramp: usize,
}

#[derive(Clone, Copy)]
enum Ev {
    Young { start: f64, index: usize },
    Dead { item: usize, level: u64 },
    Boost { item: usize, index: usize },
}

struct Event {
    time: f64,
    seq: u64,
    ev: Ev,
}
impl PartialEq for Event {
    fn eq(&self, o: &Self) -> bool {
        self.time == o.time && self.seq == o.seq
    }
}
impl Eq for Event {}
impl PartialOrd for Event {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Event {
    // Min-heap on (time, seq).
    fn cmp(&self, o: &Self) -> Ordering {
        o.time.total_cmp(&self.time).then(o.seq.cmp(&self.seq))
    }
}

struct Entry {
    end: f64,
    serial: u64,
    weight: f64,
    stacks: f64,
    seeds: f64,
    young: FMap,
    mature: f64,
    scale: f64,
}
impl PartialEq for Entry {
    fn eq(&self, o: &Self) -> bool {
        self.end == o.end && self.serial == o.serial
    }
}
impl Eq for Entry {}
impl PartialOrd for Entry {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Entry {
    fn cmp(&self, o: &Self) -> Ordering {
        o.end.total_cmp(&self.end).then(o.serial.cmp(&self.serial))
    }
}

pub struct HeatChains {
    g: f64,
    entries: BinaryHeap<Entry>,
    serial: u64,
    weight: f64,
    stacks: f64,
    seeds: f64,
    young: FMap,
    mature: f64,
    dead: VecDeque<usize>,
    boost: VecDeque<usize>,
    scale: f64,
    dead_arena: Vec<DeadItem>,
    boost_arena: Vec<BoostItem>,
    t: f64,
    events: BinaryHeap<Event>,
    sequence: u64,
    young_index: FxIndexMap<u64, usize>,
    dead_levels: FMap,
    up: f64,
    down: f64,
    tail: f64,
}

impl Default for HeatChains {
    fn default() -> Self {
        Self::new()
    }
}

impl HeatChains {
    pub fn new() -> Self {
        let mut h = HeatChains {
            g: 1.0,
            entries: BinaryHeap::new(),
            serial: 0,
            weight: 0.0,
            stacks: 0.0,
            seeds: 0.0,
            young: FMap::default(),
            mature: 0.0,
            dead: VecDeque::new(),
            boost: VecDeque::new(),
            scale: 1.0,
            dead_arena: Vec::new(),
            boost_arena: Vec::new(),
            t: f64::NEG_INFINITY,
            events: BinaryHeap::new(),
            sequence: 0,
            young_index: FxIndexMap::default(),
            dead_levels: FMap::default(),
            up: 0.0,
            down: 0.0,
            tail: 0.0,
        };
        h.reset();
        h
    }

    pub fn reset(&mut self) {
        self.g = 1.0;
        self.entries.clear();
        self.serial = 0;
        self.weight = 0.0;
        self.stacks = 0.0;
        self.seeds = 0.0;
        self.young = FMap::default();
        self.mature = 0.0;
        self.dead.clear();
        self.boost.clear();
        self.scale = 1.0;
        self.dead_arena.clear();
        self.boost_arena.clear();
        self.clear_incremental(f64::NEG_INFINITY);
    }

    fn clear_incremental(&mut self, t: f64) {
        self.t = t;
        self.events.clear();
        self.sequence = 0;
        self.young_index = FxIndexMap::default();
        self.dead_levels = FMap::default();
        self.up = 0.0;
        self.down = 0.0;
        self.tail = 0.0;
    }

    pub fn active(&self) -> bool {
        !self.entries.is_empty()
    }
    pub fn alive(&self) -> f64 {
        pmax(0.0, self.weight * self.g)
    }
    pub fn count(&self) -> f64 {
        pmax(0.0, self.stacks * self.g)
    }
    pub fn seed(&self) -> f64 {
        pmax(0.0, self.seeds * self.g)
    }

    fn push(&mut self, time: f64, ev: Ev) {
        self.sequence += 1;
        self.events.push(Event { time, seq: self.sequence, ev });
    }

    fn schedule_young(&mut self, start: f64) {
        let index = *self.young_index.get(&fkey(start)).unwrap_or(&0);
        if index < 4 {
            let time = start + ((index + 1) as f64 * 0.5) * self.scale;
            self.push(time, Ev::Young { start, index: index + 1 });
        }
    }

    fn schedule_dead(&mut self, item: usize, level: u64) {
        let it = &self.dead_arena[item];
        let n = it.step[&level];
        if (n as i64) < it.steps[&level].len() as i64 - 1 {
            let time = it.end + ((n + 1) as f64 * 1.5) * it.scale;
            self.push(time, Ev::Dead { item, level });
        }
    }

    fn schedule_boost(&mut self, item: usize) {
        let it = &self.boost_arena[item];
        if it.ramp < 4 && it.levels.keys().any(|l| fval(*l) > HEAT_RAMP[it.ramp]) {
            let time = it.start + ((it.ramp + 1) as f64 * 0.5) * it.scale;
            let index = it.ramp + 1;
            self.push(time, Ev::Boost { item, index });
        }
    }

    fn due(&self, ev: &Ev, t: f64) -> bool {
        match *ev {
            Ev::Young { start, index } => ramp_index(t - start, self.scale) >= index,
            Ev::Dead { item, level } => {
                let it = &self.dead_arena[item];
                decay_index(t - it.end, it.scale, &it.steps[&level]) > it.step[&level]
            }
            Ev::Boost { item, index } => {
                let it = &self.boost_arena[item];
                ramp_index(t - it.start, it.scale) >= index
            }
        }
    }

    fn advance(&mut self, t: f64) {
        if t < self.t - 1e-9 {
            self.rebuild(t);
            return;
        }
        let mut retry = Vec::new();
        while let Some(top) = self.events.peek() {
            if !(top.time <= t + 1e-7) {
                break;
            }
            let event = self.events.pop().unwrap();
            if event.time > t - 1e-7 && !self.due(&event.ev, t) {
                retry.push(event);
                continue;
            }
            match event.ev {
                Ev::Young { start, index } => {
                    let k = fkey(start);
                    if self.young.contains_key(&k) && *self.young_index.get(&k).unwrap_or(&0) < index {
                        let old = *self.young_index.get(&k).unwrap_or(&0);
                        self.up += self.young[&k] * self.g * (HEAT_RAMP[index] - HEAT_RAMP[old]);
                        self.young_index.insert(k, index);
                        self.schedule_young(start);
                    }
                }
                Ev::Dead { item, level } => {
                    let (live, cleared) = {
                        let it = &self.dead_arena[item];
                        (it.levels.get(&level).copied().unwrap_or(0.0), it.cleared)
                    };
                    if live != 0.0 && !cleared {
                        let (old, new, w, n) = {
                            let it = &self.dead_arena[item];
                            let steps = &it.steps[&level];
                            let n = it.step[&level];
                            (steps[n], steps[n + 1], it.levels[&level], n)
                        };
                        self.down += w * (new - old);
                        let ko = fkey(old);
                        let prev = *self.dead_levels.get(&ko).unwrap_or(&0.0);
                        self.dead_levels.insert(ko, prev - w);
                        if new > 0.0 {
                            let kn = fkey(new);
                            let prev = *self.dead_levels.get(&kn).unwrap_or(&0.0);
                            self.dead_levels.insert(kn, prev + w);
                        }
                        self.dead_arena[item].step.insert(level, n + 1);
                        self.schedule_dead(item, level);
                    }
                }
                Ev::Boost { item, index } => {
                    let delta = {
                        let it = &self.boost_arena[item];
                        let old = it.ramp;
                        psum(it.levels.iter().map(|(l, w)| {
                            let level = fval(*l);
                            *w * (pmax(0.0, level - HEAT_RAMP[index]) - pmax(0.0, level - HEAT_RAMP[old]))
                        }))
                    };
                    self.tail += delta;
                    self.boost_arena[item].ramp = index;
                    self.schedule_boost(item);
                }
            }
        }
        for event in retry {
            self.events.push(event);
        }
        self.t = pmax(self.t, t);
    }

    fn rebuild(&mut self, t: f64) {
        self.clear_incremental(t);
        let g = self.g;
        let starts: Vec<(u64, f64)> = self.young.iter().map(|(k, w)| (*k, *w)).collect();
        for (k, w) in starts {
            let start = fval(k);
            let index = ramp_index(t - start, self.scale);
            self.young_index.insert(k, index);
            self.up += w * g * HEAT_RAMP[index];
            self.schedule_young(start);
        }
        self.up += self.mature * g * 0.5;
        let dead: Vec<usize> = self.dead.iter().copied().collect();
        for item in dead {
            if self.dead_arena[item].cleared {
                continue;
            }
            let levels: Vec<(u64, f64)> = self.dead_arena[item].levels.iter().map(|(k, w)| (*k, *w)).collect();
            for (level, w) in levels {
                let (n, sn) = {
                    let it = &self.dead_arena[item];
                    let steps = &it.steps[&level];
                    let n = decay_index(t - it.end, it.scale, steps);
                    (n, steps[n])
                };
                self.dead_arena[item].step.insert(level, n);
                self.down += w * sn;
                if sn > 0.0 {
                    let k = fkey(sn);
                    let prev = *self.dead_levels.get(&k).unwrap_or(&0.0);
                    self.dead_levels.insert(k, prev + w);
                }
                self.schedule_dead(item, level);
            }
        }
        let boost: Vec<usize> = self.boost.iter().copied().collect();
        for item in boost {
            let ramp = {
                let it = &self.boost_arena[item];
                ramp_index(t - it.start, it.scale)
            };
            self.boost_arena[item].ramp = ramp;
            let delta = psum(
                self.boost_arena[item]
                    .levels
                    .iter()
                    .map(|(l, w)| *w * pmax(0.0, fval(*l) - HEAT_RAMP[ramp])),
            );
            self.tail += delta;
            self.schedule_boost(item);
        }
    }

    pub fn expire(&mut self, t: f64) {
        loop {
            let end = match self.entries.peek() {
                Some(e) if e.end < t - 1e-9 => e.end,
                _ => break,
            };
            self.advance(end);
            let e = self.entries.pop().unwrap();
            let g = self.g;
            self.weight -= e.weight;
            self.stacks -= e.stacks;
            self.seeds -= e.seeds;
            self.mature -= e.mature;
            self.up -= e.mature * g * 0.5;
            let mut levels = FMap::default();
            if e.mature != 0.0 {
                levels.insert(fkey(0.5), e.mature);
            }
            for (k, w) in e.young.iter() {
                let start = fval(*k);
                if let Some(v) = self.young.get_mut(k) {
                    *v -= *w;
                    let idx = *self.young_index.get(k).unwrap_or(&0);
                    self.up -= w * g * HEAT_RAMP[idx];
                } else {
                    self.mature -= w;
                    self.up -= w * g * 0.5;
                }
                let level = heat_ramp(e.end - start, e.scale);
                let lk = fkey(level);
                let prev = *levels.get(&lk).unwrap_or(&0.0);
                levels.insert(lk, prev + w);
            }
            let levels: FMap = levels.into_iter().filter(|(l, w)| fval(*l) > 0.0 && *w > 0.0).collect();
            if !levels.is_empty() {
                let step: FxIndexMap<u64, usize> = levels.keys().map(|l| (*l, 0usize)).collect();
                let steps: FxIndexMap<u64, Vec<f64>> = levels.keys().map(|l| (*l, decay_steps(fval(*l)))).collect();
                let pairs: Vec<(u64, f64)> = levels.iter().map(|(k, w)| (*k, *w)).collect();
                self.dead_arena.push(DeadItem { end: e.end, scale: e.scale, levels, step, steps, cleared: false });
                let item = self.dead_arena.len() - 1;
                self.dead.push_back(item);
                for (lk, w) in pairs {
                    self.down += w * fval(lk);
                    let prev = *self.dead_levels.get(&lk).unwrap_or(&0.0);
                    self.dead_levels.insert(lk, prev + w);
                    self.schedule_dead(item, lk);
                }
            }
        }
        if self.entries.is_empty() {
            self.weight = 0.0;
            self.stacks = 0.0;
            self.seeds = 0.0;
            self.mature = 0.0;
            self.young.clear();
            self.young_index.clear();
            self.up = 0.0;
        }
        while let Some(&front) = self.dead.front() {
            let it = &self.dead_arena[front];
            if t - it.end >= 6.0 * it.scale - 1e-9 {
                self.dead.pop_front();
            } else {
                break;
            }
        }
        while let Some(&front) = self.boost.front() {
            let it = &self.boost_arena[front];
            if t - it.start >= 2.0 * it.scale - 1e-9 {
                self.boost.pop_front();
            } else {
                break;
            }
        }
    }

    pub fn add(&mut self, t: f64, absence: f64, n: f64, seed: f64, duration: f64, scale: f64) {
        self.expire(t);
        let a = pmin(1.0, pmax(0.0, absence));
        let p = 1.0 - a;
        if p <= 0.0 {
            return;
        }
        self.advance(t);
        let g = self.g;
        let matured: Vec<u64> = self
            .young
            .keys()
            .copied()
            .filter(|k| t - fval(*k) >= 2.0 * self.scale - 1e-9)
            .collect();
        for k in matured {
            let w = self.young.shift_remove(&k).unwrap();
            self.mature += w;
            self.young_index.shift_remove(&k);
        }
        let tail: FMap = self
            .dead_levels
            .iter()
            .filter(|(l, w)| fval(**l) > 0.0 && **w > 0.0)
            .map(|(l, w)| (*l, p * *w * g))
            .collect();
        if !tail.is_empty() {
            let delta = psum(tail.iter().map(|(l, w)| fval(*l) * *w));
            self.boost_arena.push(BoostItem { start: t, scale, levels: tail, ramp: 0 });
            let item = self.boost_arena.len() - 1;
            self.boost.push_back(item);
            self.tail += delta;
            self.schedule_boost(item);
        }
        let alive = self.weight * g;
        let mut young: FMap = self.young.iter().map(|(k, v)| (*k, p * *v * g)).collect();
        let kt = fkey(t);
        let prev = *young.get(&kt).unwrap_or(&0.0);
        young.insert(kt, prev + p * pmax(0.0, 1.0 - alive));
        let v0 = p;
        let v1 = p * self.stacks * g + n;
        let v2 = p * self.seeds * g + seed;
        let v4 = p * self.mature * g;
        if a <= 0.0 {
            self.entries.clear();
            self.weight = 0.0;
            self.stacks = 0.0;
            self.seeds = 0.0;
            self.mature = 0.0;
            for &item in self.dead.iter() {
                self.dead_arena[item].cleared = true;
            }
            self.young = FMap::default();
            self.dead.clear();
            self.g = 1.0;
            self.down = 0.0;
            self.dead_levels = FMap::default();
        } else {
            self.g = g * a;
        }
        let q = self.g;
        let weight = v0 / q;
        let stacks = v1 / q;
        let seeds = v2 / q;
        let young: FMap = young.into_iter().map(|(k, v)| (k, v / q)).collect();
        let mature = v4 / q;
        self.serial += 1;
        self.weight += weight;
        self.stacks += stacks;
        self.seeds += seeds;
        self.mature += mature;
        for (k, v) in young.iter() {
            let prev = *self.young.get(k).unwrap_or(&0.0);
            self.young.insert(*k, prev + *v);
        }
        self.entries.push(Entry {
            end: t + duration,
            serial: self.serial,
            weight,
            stacks,
            seeds,
            young,
            mature,
            scale,
        });
        if scale != self.scale {
            self.scale = scale;
            self.rebuild(t);
        } else if !self.young_index.contains_key(&kt) {
            self.young_index.insert(kt, 0);
            self.schedule_young(t);
        }
        if self.g < 1e-100 {
            self.normalize();
        }
    }

    fn normalize(&mut self) {
        let q = self.g;
        let old: Vec<Entry> = std::mem::take(&mut self.entries).into_vec();
        for e in old {
            self.entries.push(Entry {
                end: e.end,
                serial: e.serial,
                weight: e.weight * q,
                stacks: e.stacks * q,
                seeds: e.seeds * q,
                young: e.young.into_iter().map(|(k, v)| (k, v * q)).collect(),
                mature: e.mature * q,
                scale: e.scale,
            });
        }
        self.weight *= q;
        self.stacks *= q;
        self.seeds *= q;
        self.mature *= q;
        self.young = std::mem::take(&mut self.young).into_iter().map(|(k, v)| (k, v * q)).collect();
        let dead: Vec<usize> = self.dead.iter().copied().collect();
        for item in dead {
            for v in self.dead_arena[item].levels.values_mut() {
                *v *= q;
            }
        }
        self.g = 1.0;
        let t = self.t;
        self.rebuild(t);
    }

    pub fn strip(&mut self, t: f64) -> f64 {
        self.advance(t);
        pmin(0.5, pmax(0.0, self.up + self.down * self.g + self.tail))
    }
}

#[allow(dead_code)]
fn _fget_used(m: &FMap) -> f64 {
    fget(m, 0.0)
}
