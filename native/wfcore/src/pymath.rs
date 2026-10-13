//! Python float semantics the reference engine relies on.
//!
//! * `PySum` is CPython 3.12+'s `sum()` over floats: the int fast path turns
//!   the first float into `0 + x`, then Neumaier-compensated accumulation, the
//!   compensation added once at the end when it is finite.
//! * The transcendental functions are the C runtime's, the same ones CPython's
//!   `math` module and `float.__pow__` call, so results agree to the last bit.

extern "C" {
    #[link_name = "log"]
    fn c_log(x: f64) -> f64;
    #[link_name = "expm1"]
    fn c_expm1(x: f64) -> f64;
    #[link_name = "erfc"]
    fn c_erfc(x: f64) -> f64;
    #[link_name = "pow"]
    fn c_pow(x: f64, y: f64) -> f64;
}

/// `math.log(x)` for the positive arguments the engine passes.
#[inline]
pub fn log(x: f64) -> f64 {
    if x == 0.0 {
        return f64::NEG_INFINITY;
    }
    unsafe { c_log(x) }
}

#[inline]
pub fn expm1(x: f64) -> f64 {
    unsafe { c_expm1(x) }
}

#[inline]
pub fn erfc(x: f64) -> f64 {
    unsafe { c_erfc(x) }
}

/// `x ** y` for floats (CPython float_pow's finite special cases, then C pow).
#[inline]
pub fn pow(x: f64, y: f64) -> f64 {
    if y == 0.0 || x == 1.0 {
        return 1.0;
    }
    unsafe { c_pow(x, y) }
}

#[inline]
pub fn sqrt(x: f64) -> f64 {
    x.sqrt()
}

/// `math.floor(x)` as an integer (the engine only floors finite values).
#[inline]
pub fn floor_i(x: f64) -> i64 {
    x.floor() as i64
}

/// `math.ceil(x)` as an integer.
#[inline]
pub fn ceil_i(x: f64) -> i64 {
    x.ceil() as i64
}

/// `int(x)`: truncation toward zero.
#[inline]
pub fn trunc_i(x: f64) -> i64 {
    x.trunc() as i64
}

/// Python's `max(a, b)`: the first argument unless the second is greater.
#[inline]
pub fn pmax(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// Python's `min(a, b)`: the first argument unless the second is smaller.
#[inline]
pub fn pmin(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

/// Accumulates exactly like CPython's `sum()` of a float sequence (start 0).
#[derive(Clone, Copy, Debug)]
pub struct PySum {
    started: bool,
    total: f64,
    comp: f64,
}

impl Default for PySum {
    fn default() -> Self {
        Self::new()
    }
}

impl PySum {
    #[inline]
    pub fn new() -> Self {
        PySum { started: false, total: 0.0, comp: 0.0 }
    }

    #[inline]
    pub fn add(&mut self, x: f64) {
        if !self.started {
            // int 0 + float x
            self.total = 0.0 + x;
            self.started = true;
            return;
        }
        let t = self.total + x;
        if self.total.abs() >= x.abs() {
            self.comp += (self.total - t) + x;
        } else {
            self.comp += (x - t) + self.total;
        }
        self.total = t;
    }

    #[inline]
    pub fn value(&self) -> f64 {
        if !self.started {
            return 0.0;
        }
        if self.comp != 0.0 && self.comp.is_finite() {
            self.total + self.comp
        } else {
            self.total
        }
    }
}

/// `sum(iterable)` over floats.
#[inline]
pub fn psum<I: IntoIterator<Item = f64>>(items: I) -> f64 {
    let mut s = PySum::new();
    for x in items {
        s.add(x);
    }
    s.value()
}
