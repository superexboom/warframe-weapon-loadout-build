//! `stackable_projectiles.StackableProjectiles`: merging projectile groups
//! (Simulor orbs, Stug goo, Mutalist Quanta alt-fire) with their embed,
//! singularity, explosion and child-projectile clocks.
//!
//! The state machine is pure; the replay applies its hits (`Action::Hit`)
//! and schedules its events (`Action::Life` / `Action::Child`) in order.

pub const STUG: u8 = 0;
pub const SIMULOR: u8 = 1;
pub const MQ: u8 = 2;

/// A group's damage parts (replay view indices).
#[derive(Clone, Copy, Default)]
pub struct Parts {
    pub embed: Option<usize>,
    pub explosion: Option<usize>,
    pub merge: Option<usize>,
    pub singularity: Option<usize>,
    pub child: Option<usize>,
    pub orb_radial: Option<usize>,
}

pub const EMBED: u8 = 0;
pub const EXPLOSION: u8 = 1;
pub const MERGE: u8 = 2;
pub const SINGULARITY: u8 = 3;
pub const CHILD: u8 = 4;
pub const ORB_RADIAL: u8 = 5;

impl Parts {
    pub fn get(&self, kind: u8) -> Option<usize> {
        match kind {
            EMBED => self.embed,
            EXPLOSION => self.explosion,
            MERGE => self.merge,
            SINGULARITY => self.singularity,
            CHILD => self.child,
            _ => self.orb_radial,
        }
    }
}

/// The profile fields the clocks read (the Python dict, flattened).
#[derive(Clone)]
pub struct Profile {
    pub kind: u8,
    pub embed_seconds: f64,
    pub max_life: f64,
    pub embed_interval: f64,
    pub max_stack: f64,
    pub merge_low: f64,
    pub merge_high: f64,
    /// `sum(profile['merge']['damage'].values())`
    pub merge_native: f64,
    pub attach_at_stack: f64,
    pub singularity_interval: f64,
    pub reset_life: bool,
    pub stacked_life: f64,
    pub initial_stack: f64,
    pub child: bool,
    pub child_max: f64,
    pub child_min: f64,
    pub child_bounces: f64,
    pub child_life: f64,
    pub child_death_multiplier: f64,
}

/// `combat['projectileState']` as the clocks read it.
#[derive(Clone, Default)]
pub struct State {
    pub isolated: bool,
    pub manual: bool,
    pub detonate_after: Option<f64>,
    pub wait: f64,
    pub child_hits: f64,
    pub bounce_hits: f64,
    pub bounce_delay: f64,
    pub child_detonate: Option<f64>,
    pub mq_augment: bool,
}

pub const ACT_EXPLODE: u8 = 0;
pub const ACT_EMBED: u8 = 1;
pub const ACT_SINGULARITY: u8 = 2;
pub const ACT_MANUAL: u8 = 3;

pub enum Action {
    /// Deliver `part` scaled by `scale` with `multishot` instances.
    Hit { part: usize, scale: f64, weight: f64 },
    /// push(time, 'stackable-life', (group, token, action), generation)
    Life { time: f64, group: usize, token: i64, action: u8, generation: i64 },
    /// push(time, 'stackable-child', (group, multiplier, hits), generation)
    Child { time: f64, group: usize, multiplier: f64, hits: f64, generation: i64 },
}

struct Group {
    profile: std::rc::Rc<Profile>,
    parts: Parts,
    generation: i64,
    stacks: f64,
    weight: f64,
    expires: f64,
    token: i64,
    singularity: bool,
    alive: bool,
    next_embed: Option<f64>,
}

pub struct Projectiles {
    pub state: State,
    groups: Vec<Group>,
    active: Option<usize>,
    shots: i64,
    pub deployed: f64,
    pub merged: f64,
    pub explosions: i64,
    pub singularities: i64,
    pub child_projectiles: i64,
}

impl Projectiles {
    pub fn new(state: State) -> Self {
        Projectiles { state, groups: Vec::new(), active: None, shots: 0, deployed: 0.0, merged: 0.0,
                      explosions: 0, singularities: 0, child_projectiles: 0 }
    }

    fn schedule(&self, out: &mut Vec<Action>, time: f64, action: u8, id: usize) {
        let g = &self.groups[id];
        out.push(Action::Life { time, group: id, token: g.token, action, generation: g.generation });
    }

    fn hit(&self, out: &mut Vec<Action>, id: usize, kind: u8, scale: f64, weight: Option<f64>) {
        let g = &self.groups[id];
        if let Some(part) = g.parts.get(kind) {
            out.push(Action::Hit { part, scale, weight: weight.unwrap_or(g.weight) });
        }
    }

    fn create(&mut self, out: &mut Vec<Action>, time: f64, profile: &std::rc::Rc<Profile>, parts: Parts, generation: i64,
              stacks: f64, weight: f64) -> usize {
        let lifetime = if profile.kind == STUG { profile.embed_seconds } else { profile.max_life };
        self.groups.push(Group { profile: profile.clone(), parts, generation, stacks, weight, expires: time + lifetime,
                                 token: 0, singularity: false, alive: true, next_embed: None });
        let id = self.groups.len() - 1;
        let expires = self.groups[id].expires;
        self.schedule(out, expires, ACT_EXPLODE, id);
        if profile.kind == STUG {
            self.hit(out, id, EMBED, stacks, None);
            let next = time + profile.embed_interval;
            self.groups[id].next_embed = Some(next);
            self.schedule(out, next, ACT_EMBED, id);
        }
        id
    }

    fn merge(&mut self, out: &mut Vec<Action>, time: f64, id: usize, amount: f64) {
        let profile = self.groups[id].profile.clone();
        let previous = self.groups[id].stacks;
        if previous >= profile.max_stack {
            return;
        }
        let stacks = crate::pymath::pmin(profile.max_stack, previous + amount);
        self.groups[id].stacks = stacks;
        let added = stacks - previous;
        self.merged += added * self.groups[id].weight;
        if (profile.kind == SIMULOR || profile.kind == MQ) && added > 0.0 {
            let (low, high) = (profile.merge_low, profile.merge_high);
            let native = profile.merge_native;
            let over = low + (high - low) * added / profile.max_stack;
            let scale = if over > 0.0 && native != 0.0 { over / native } else { 1.0 };
            self.hit(out, id, MERGE, scale, None);
            if profile.kind == SIMULOR && !self.groups[id].singularity && stacks >= profile.attach_at_stack {
                self.groups[id].singularity = true;
                self.singularities += 1;
                self.schedule(out, time + profile.singularity_interval, ACT_SINGULARITY, id);
            }
        }
        if profile.reset_life {
            self.groups[id].expires = time + profile.stacked_life;
            self.groups[id].token += 1;
            let expires = self.groups[id].expires;
            self.schedule(out, expires, ACT_EXPLODE, id);
            if let Some(next) = self.groups[id].next_embed {
                // The refresh moves the fuse only; embed ticks keep their beat.
                self.schedule(out, next, ACT_EMBED, id);
            }
            if self.groups[id].singularity {
                self.schedule(out, time + profile.singularity_interval, ACT_SINGULARITY, id);
            }
        }
        if profile.kind == STUG && self.groups[id].stacks >= profile.max_stack {
            self.explode(out, time, id);
        }
    }

    /// One shot's deployment; returns the extra wait of a manual detonation.
    pub fn deploy(&mut self, out: &mut Vec<Action>, time: f64, profile: &std::rc::Rc<Profile>, parts: Parts,
                  multishot: f64, generation: i64) -> f64 {
        let quantity = crate::pymath::pmax(multishot, 0.0);
        self.deployed += quantity;
        self.shots += 1;
        let isolated = self.state.isolated;
        let full = quantity.trunc();
        let mut fractions: Vec<f64> = vec![1.0; full as usize];
        if quantity - full > 1e-9 {
            fractions.push(quantity - full);
        }
        for weight in fractions {
            let current = self.active.filter(|&id| {
                let g = &self.groups[id];
                g.alive && g.generation == generation && g.profile.kind == profile.kind
            });
            match (isolated, current) {
                (false, Some(id)) => self.merge(out, time, id, weight * profile.initial_stack),
                _ => {
                    let initial = profile.initial_stack;
                    let (stacks, w) = if isolated { (initial, weight) } else { (initial * weight, 1.0) };
                    let id = self.create(out, time, profile, parts, generation, stacks, w);
                    self.active = Some(id);
                }
            }
        }
        if let (SIMULOR, true, Some(batch)) = (profile.kind, self.state.manual, self.state.detonate_after) {
            if batch != 0.0 && self.shots as f64 >= batch {
                self.shots = 0;
                let wait = self.state.wait;
                for id in 0..self.groups.len() {
                    if self.groups[id].alive && self.groups[id].generation == generation {
                        self.schedule(out, time + wait, ACT_MANUAL, id);
                    }
                }
                return wait;
            }
        }
        0.0
    }

    fn explode(&mut self, out: &mut Vec<Action>, time: f64, id: usize) {
        if !self.groups[id].alive {
            return;
        }
        self.groups[id].alive = false;
        self.explosions += 1;
        let stacks = self.groups[id].stacks;
        self.hit(out, id, EXPLOSION, stacks, None);
        let profile = self.groups[id].profile.clone();
        let generation = self.groups[id].generation;
        if profile.child {
            let count = profile.child_max.min(profile.child_min.max((profile.child_max * stacks / profile.max_stack).ceil()));
            self.child_projectiles += count as i64;
            let hits = count.min(self.state.child_hits.trunc());
            let bounces = profile.child_bounces.min(self.state.bounce_hits.trunc());
            let interval = self.state.bounce_delay;
            let lifetime = profile.child_life.min(self.state.child_detonate.unwrap_or(profile.child_life));
            let mut n = 0.0;
            while n < bounces {
                if (n + 1.0) * interval < lifetime {
                    out.push(Action::Child { time: time + (n + 1.0) * interval, group: id, multiplier: 1.0, hits, generation });
                }
                n += 1.0;
            }
            out.push(Action::Child { time: time + lifetime, group: id, multiplier: profile.child_death_multiplier, hits, generation });
        }
        if profile.kind == MQ && self.state.mq_augment && self.groups[id].parts.orb_radial.is_some() {
            self.hit(out, id, ORB_RADIAL, 1.0, None);
        }
        if self.active == Some(id) {
            self.active = None;
        }
    }

    /// A 'stackable-life' event.
    pub fn life(&mut self, out: &mut Vec<Action>, time: f64, id: usize, token: i64, action: u8) {
        if id >= self.groups.len() || !self.groups[id].alive || token != self.groups[id].token {
            return;
        }
        match action {
            ACT_EXPLODE | ACT_MANUAL => self.explode(out, time, id),
            ACT_EMBED if time < self.groups[id].expires => {
                let stacks = self.groups[id].stacks;
                self.hit(out, id, EMBED, stacks, None);
                let next = time + self.groups[id].profile.embed_interval;
                self.groups[id].next_embed = Some(next);
                self.schedule(out, next, ACT_EMBED, id);
            }
            ACT_SINGULARITY if time < self.groups[id].expires => {
                let interval = self.groups[id].profile.singularity_interval;
                self.hit(out, id, SINGULARITY, interval, None);
                self.schedule(out, time + interval, ACT_SINGULARITY, id);
            }
            _ => {}
        }
    }

    /// A 'stackable-child' event.
    pub fn child(&mut self, out: &mut Vec<Action>, id: usize, multiplier: f64, hits: f64) {
        if id >= self.groups.len() {
            return;
        }
        if hits != 0.0 {
            let weight = hits * self.groups[id].weight;
            self.hit(out, id, CHILD, multiplier, Some(weight));
        }
    }
}
