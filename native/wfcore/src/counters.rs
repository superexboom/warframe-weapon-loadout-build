//! Cheap timing counters for profiling the native replay from Python.
//!
//! The first three slots are always on (one pair of clock reads per replay or
//! resolver call); the per-function slots are inclusive timers that only run
//! after `enable(true)`, since a clock read costs about as much as the work.
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Instant;

pub const TOTAL: usize = 0;
pub const RESOLVE: usize = 1;
pub const VIEW: usize = 2;
pub const CLEAN: usize = 3;
pub const TAKE: usize = 4;
pub const ADD_PROCS: usize = 5;
pub const MODEL: usize = 6;
pub const PACKET: usize = 7;
pub const SIGNAL: usize = 8;
pub const FIRE: usize = 9;
pub const SETUP: usize = 10;
pub const RESULT: usize = 11;
pub const PRESENCE: usize = 12;
pub const HEAT: usize = 13;
pub const POOLED: usize = 14;
pub const NOSTATUS: usize = 15;
const N: usize = 16;
const NAMES: [&str; N] = ["total", "resolve", "view", "clean", "take", "add_procs", "model", "packet", "signal",
                          "fire", "setup", "result", "presence", "heat", "pooled", "no_status"];

static ENABLED: AtomicBool = AtomicBool::new(false);
static NANOS: [AtomicU64; N] = [const { AtomicU64::new(0) }; N];
static CALLS: [AtomicU64; N] = [const { AtomicU64::new(0) }; N];

pub fn add(slot: usize, nanos: u64) {
    NANOS[slot].fetch_add(nanos, Ordering::Relaxed);
    CALLS[slot].fetch_add(1, Ordering::Relaxed);
}

pub fn enable(on: bool) {
    ENABLED.store(on, Ordering::Relaxed);
}

/// An inclusive timer for one call of a profiled function (no-op when off).
pub struct Timer(usize, Option<Instant>);

impl Timer {
    #[inline]
    pub fn start(slot: usize) -> Timer {
        Timer(slot, if ENABLED.load(Ordering::Relaxed) { Some(Instant::now()) } else { None })
    }
}

impl Drop for Timer {
    #[inline]
    fn drop(&mut self) {
        if let Some(t) = self.1 {
            add(self.0, t.elapsed().as_nanos() as u64);
        }
    }
}

/// (name, seconds, calls) per counter; `reset` zeroes them afterwards.
pub fn snapshot(reset: bool) -> Vec<(&'static str, f64, u64)> {
    (0..N)
        .map(|i| {
            let (n, c) = if reset {
                (NANOS[i].swap(0, Ordering::Relaxed), CALLS[i].swap(0, Ordering::Relaxed))
            } else {
                (NANOS[i].load(Ordering::Relaxed), CALLS[i].load(Ordering::Relaxed))
            };
            (NAMES[i], n as f64 * 1e-9, c)
        })
        .collect()
}
