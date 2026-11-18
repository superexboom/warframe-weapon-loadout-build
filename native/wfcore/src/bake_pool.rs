use super::{arrival_kernel, fold};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};
use std::num::NonZeroU64;

pub const CAP: usize = 10;
const WIDTH: usize = CAP + 1;
const MAX_KEYS: usize = 512;
const MAX_STEPS: usize = 32;
type Row = [f64; WIDTH];

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Key(u64, NonZeroU64);

impl Key {
    fn new(absence: f64, count: f64) -> Option<Self> {
        // The CUDA arrival calculation uses signed 32-bit shifts.
        if !(0.0..1.0).contains(&absence) || !count.is_finite() || count <= 0.0
            || count / (1.0 - absence) + 1e-9 >= i32::MAX as f64
        {
            return None;
        }
        Some(Self(absence.to_bits(), NonZeroU64::new(count.to_bits())?))
    }

    fn matches(self, absence: f64, count: f64) -> bool {
        self.0 == absence.to_bits() && self.1.get() == count.to_bits()
    }

    fn values(self) -> (f64, f64) {
        (f64::from_bits(self.0), f64::from_bits(self.1.get()))
    }
}

#[derive(Default)]
struct State {
    limit: usize,
    pending: Vec<Key>,
    seen: HashSet<Key>,
    tables: HashMap<Key, Box<[Row]>>,
    order: VecDeque<Key>,
    hits: u64,
    misses: u64,
}

thread_local! {
    static STATE: RefCell<Option<State>> = const { RefCell::new(None) };
}

pub fn enabled() -> bool {
    STATE.with(|cell| cell.borrow().is_some())
}

pub fn copy_prefix(
    prefix: &mut Option<Key>, depth: usize, absence: f64, count: f64, dist: &mut [f64],
) -> bool {
    STATE.try_with(|cell| {
        let mut slot = cell.borrow_mut();
        let Some(state) = slot.as_mut().filter(|s| s.limit > 0 || !s.tables.is_empty()) else {
            *prefix = None;
            return false;
        };
        if depth == 1 {
            *prefix = Key::new(absence, count);
        } else if depth > MAX_STEPS || !prefix.is_some_and(|key| key.matches(absence, count)) {
            *prefix = None;
        }
        if let Some(key) = *prefix {
            if let Some(table) = state.tables.get(&key) {
                if let Some(row) = table.get(depth - 1) {
                    dist.copy_from_slice(row);
                    state.hits += 1;
                    return true;
                }
            } else if depth >= 2 && state.pending.len() < state.limit && state.seen.insert(key) {
                state.pending.push(key);
            }
        }
        state.misses += 1;
        false
    }).unwrap_or_else(|_| {
        *prefix = None;
        false
    })
}

pub fn capture(limit: usize) -> Result<(), &'static str> {
    if limit > MAX_KEYS {
        return Err("pool capture limit must be in 0..512");
    }
    STATE.with(|cell| {
        let mut slot = cell.borrow_mut();
        if limit > 0 || slot.is_some() {
            let state = slot.get_or_insert_with(State::default);
            state.limit = limit;
            state.pending.clear();
            state.seen.clear();
        }
    });
    Ok(())
}

pub fn pending() -> Vec<(f64, f64)> {
    STATE.with(|cell| {
        let mut slot = cell.borrow_mut();
        let Some(state) = slot.as_mut() else { return Vec::new() };
        state.seen.clear();
        state.pending.drain(..).map(Key::values).collect()
    })
}

fn checked(keys: Vec<(f64, f64)>, steps: usize) -> Result<Vec<Key>, &'static str> {
    if keys.len() > MAX_KEYS || !(1..=MAX_STEPS).contains(&steps) {
        return Err("pool table requires at most 512 keys and 1..32 steps");
    }
    keys.into_iter()
        .map(|(absence, count)| Key::new(absence, count).ok_or("invalid pool probability or count"))
        .collect()
}

pub fn reference(keys: Vec<(f64, f64)>, steps: usize) -> Result<Vec<u8>, &'static str> {
    let keys = checked(keys, steps)?;
    let mut out = Vec::with_capacity(keys.len() * steps * WIDTH * 8);
    for key in keys {
        let (absence, count) = key.values();
        let kernel = arrival_kernel(absence, count, CAP).ok_or("empty pool arrival kernel")?;
        let mut dist = vec![0.0; WIDTH];
        dist[0] = 1.0;
        for _ in 0..steps {
            dist = fold(&dist, &kernel, CAP);
            for value in &dist {
                out.extend_from_slice(&value.to_le_bytes());
            }
        }
    }
    Ok(out)
}

pub fn install(keys: Vec<(f64, f64)>, steps: usize, data: &[u8]) -> Result<(), &'static str> {
    let keys = checked(keys, steps)?;
    if data.len() != keys.len() * steps * WIDTH * 8 {
        return Err("pool table byte length does not match [keys, steps, 11]");
    }
    // Admission compares device bytes with reference() before installing.
    let mut tables = Vec::with_capacity(keys.len());
    let mut distinct = HashSet::with_capacity(keys.len());
    for (key, values) in keys.into_iter().zip(data.chunks_exact(steps * WIDTH * 8)) {
        let mut table = Vec::with_capacity(steps);
        for bytes in values.chunks_exact(WIDTH * 8) {
            let mut row = [0.0; WIDTH];
            for (value, chunk) in row.iter_mut().zip(bytes.chunks_exact(8)) {
                *value = f64::from_le_bytes(chunk.try_into().unwrap());
                if !value.is_finite() || *value < 0.0 {
                    return Err("pool table entries must be finite and nonnegative");
                }
            }
            table.push(row);
        }
        if !distinct.insert(key) {
            return Err("duplicate pool table key");
        }
        tables.push((key, table.into_boxed_slice()));
    }
    STATE.with(|cell| {
        let mut slot = cell.borrow_mut();
        let state = slot.get_or_insert_with(State::default);
        // Later beam layers use different builds. Retire the oldest entries in input order.
        for (key, table) in tables {
            if !state.tables.contains_key(&key) {
                if state.order.len() == MAX_KEYS {
                    state.tables.remove(&state.order.pop_front().unwrap());
                }
                state.order.push_back(key);
            }
            state.tables.insert(key, table);
        }
        let State { pending, seen, tables, .. } = state;
        pending.retain(|key| !tables.contains_key(key));
        seen.retain(|key| !tables.contains_key(key));
        Ok(())
    })
}

pub fn stats() -> (u64, u64, usize) {
    STATE.with(|cell| cell.borrow().as_ref()
        .map_or((0, 0, 0), |s| (s.hits, s.misses, s.tables.len())))
}

pub fn stop() {
    STATE.with(|cell| *cell.borrow_mut() = None);
}
