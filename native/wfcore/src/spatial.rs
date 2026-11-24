//! Optional double-sided arena triangle BVH. Python reference remains runnable.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
type V = [f64; 3];
fn sub(a: V, b: V) -> V {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn dot(a: V, b: V) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: V, b: V) -> V {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
#[derive(Clone, Copy)]
struct Tri {
    id: usize,
    a: V,
    e1: V,
    e2: V,
}
#[derive(Clone, Copy)]
struct Node {
    lo: V,
    hi: V,
    left: u32,
    right: u32,
    start: u32,
    len: u32,
}
#[pyclass]
pub struct SpatialIndex {
    nodes: Vec<Node>,
    leaf_tris: Vec<Tri>,
    normals: Vec<V>,
}
impl SpatialIndex {
    fn build(
        &mut self,
        vertices: &[V],
        triangles: &[[usize; 3]],
        tris: &[Tri],
        mut ids: Vec<usize>,
    ) -> usize {
        let mut lo = [f64::INFINITY; 3];
        let mut hi = [f64::NEG_INFINITY; 3];
        for &k in &ids {
            for &v in &triangles[k] {
                for a in 0..3 {
                    lo[a] = lo[a].min(vertices[v][a]);
                    hi[a] = hi[a].max(vertices[v][a]);
                }
            }
        }
        let index = self.nodes.len();
        self.nodes.push(Node {
            lo,
            hi,
            left: u32::MAX,
            right: u32::MAX,
            start: 0,
            len: 0,
        });
        if ids.len() <= 12 {
            let start = self.leaf_tris.len() as u32;
            let len = ids.len() as u32;
            for k in ids {
                self.leaf_tris.push(tris[k]);
            }
            self.nodes[index].start = start;
            self.nodes[index].len = len;
        } else {
            let mut axis = 0;
            for a in 1..3 {
                if hi[a] - lo[a] > hi[axis] - lo[axis] {
                    axis = a;
                }
            }
            ids.sort_by(|&a, &b| {
                let center = |k: usize| {
                    let t = triangles[k];
                    (vertices[t[0]][axis]
                        + vertices[t[1]][axis]
                        + vertices[t[2]][axis])
                        / 3.
                };
                center(a).total_cmp(&center(b)).then(a.cmp(&b))
            });
            let other = ids.split_off(ids.len() / 2);
            let left = self.build(vertices, triangles, tris, ids) as u32;
            let right = self.build(vertices, triangles, tris, other) as u32;
            self.nodes[index].left = left;
            self.nodes[index].right = right;
        }
        index
    }
    #[inline]
    fn boxed(node: &Node, o: V, d: V, mut lower: f64, mut upper: f64) -> Option<f64> {
        for i in 0..3 {
            if d[i].abs() < 1e-15 {
                if o[i] < node.lo[i] - 1e-8 || o[i] > node.hi[i] + 1e-8 {
                    return None;
                }
            } else {
                let mut a = (node.lo[i] - o[i]) / d[i];
                let mut b = (node.hi[i] - o[i]) / d[i];
                if a > b {
                    std::mem::swap(&mut a, &mut b);
                }
                lower = lower.max(a);
                upper = upper.min(b);
                if lower > upper {
                    return None;
                }
            }
        }
        Some(lower)
    }
    #[inline]
    fn triangle(tri: &Tri, o: V, d: V, lower: f64, upper: f64) -> Option<f64> {
        let a = tri.a;
        let e1 = tri.e1;
        let e2 = tri.e2;
        let h = cross(d, e2);
        let det = dot(e1, h);
        if det.abs() < 1e-10 {
            return None;
        }
        let iv = 1. / det;
        let s = sub(o, a);
        let u = dot(s, h) * iv;
        if !(-1e-8..=1. + 1e-8).contains(&u) {
            return None;
        }
        let q = cross(s, e1);
        let v = dot(d, q) * iv;
        if v < -1e-8 || u + v > 1. + 1e-8 {
            return None;
        }
        let value = dot(e2, q) * iv;
        if value >= lower && value <= upper {
            Some(value)
        } else {
            None
        }
    }
    #[inline]
    fn ray(o: V, d: V, maxdist: f64, minimum: f64) -> PyResult<V> {
        let len = dot(d, d).sqrt();
        if o.iter().chain(d.iter()).any(|x| !x.is_finite())
            || len <= 1e-15
            || maxdist.is_nan()
            || maxdist < 0.
            || !minimum.is_finite()
            || minimum < 0.
        {
            return Err(PyValueError::new_err("invalid ray"));
        }
        Ok([d[0] / len, d[1] / len, d[2] / len])
    }
    #[inline]
    fn raycast_core(
        &self,
        origin: V,
        d: V,
        maxdist: f64,
        min_distance: f64,
    ) -> Option<(f64, usize)> {
        if self.nodes.is_empty() {
            return None;
        }
        let mut upper = maxdist;
        let mut result: Option<(f64, usize)> = None;
        let mut stack = [0usize; 64];
        stack[0] = 0;
        let mut sp = 1usize;
        while sp > 0 {
            sp -= 1;
            let k = stack[sp];
            let n = &self.nodes[k];
            if Self::boxed(n, origin, d, min_distance, upper).is_none() {
                continue;
            }
            if n.left != u32::MAX {
                stack[sp] = n.right as usize;
                sp += 1;
                stack[sp] = n.left as usize;
                sp += 1;
            } else {
                let start = n.start as usize;
                let end = start + n.len as usize;
                for tri in &self.leaf_tris[start..end] {
                    if let Some(v) = Self::triangle(tri, origin, d, min_distance, upper) {
                        if result.is_none() || v < upper || (v == upper && tri.id < result.unwrap().1) {
                            upper = v;
                            result = Some((v, tri.id));
                        }
                    }
                }
            }
        }
        result
    }
    #[inline]
    fn raycast_one(
        &self,
        origin: V,
        direction: V,
        maxdist: f64,
        min_distance: f64,
    ) -> PyResult<Option<(f64, usize)>> {
        let d = Self::ray(origin, direction, maxdist, min_distance)?;
        Ok(self.raycast_core(origin, d, maxdist, min_distance))
    }
}
#[pymethods]
impl SpatialIndex {
    #[new]
    fn new(vertices: Vec<V>, triangles: Vec<[usize; 3]>) -> PyResult<Self> {
        if vertices.iter().flatten().any(|x| !x.is_finite())
            || triangles.iter().flatten().any(|&k| k >= vertices.len())
        {
            return Err(PyValueError::new_err("invalid triangle geometry"));
        }
        let n = triangles.len();
        let mut tris: Vec<Tri> = Vec::with_capacity(n);
        let mut normals: Vec<V> = Vec::with_capacity(n);
        for (id, t) in triangles.iter().enumerate() {
            let a = vertices[t[0]];
            let e1 = sub(vertices[t[1]], a);
            let e2 = sub(vertices[t[2]], a);
            let raw_n = cross(e1, e2);
            let nlen = dot(raw_n, raw_n).sqrt();
            let unit_n = if nlen != 0.0 {
                [raw_n[0] / nlen, raw_n[1] / nlen, raw_n[2] / nlen]
            } else {
                [0.0, 0.0, 0.0]
            };
            tris.push(Tri { id, a, e1, e2 });
            normals.push(unit_n);
        }
        let mut value = Self {
            nodes: Vec::with_capacity((n / 4).max(1)),
            leaf_tris: Vec::with_capacity(n),
            normals,
        };
        if n > 0 {
            value.build(&vertices, &triangles, &tris, (0..n).collect());
        }
        Ok(value)
    }
    #[pyo3(signature=(origin,direction,maxdist=f64::INFINITY,min_distance=1e-5))]
    fn raycast(
        &self,
        origin: V,
        direction: V,
        maxdist: f64,
        min_distance: f64,
    ) -> PyResult<Option<(f64, usize)>> {
        self.raycast_one(origin, direction, maxdist, min_distance)
    }
    #[pyo3(signature=(origin,direction,maxdist=f64::INFINITY,min_distance=1e-5))]
    fn raycast_hit(
        &self,
        origin: V,
        direction: V,
        maxdist: f64,
        min_distance: f64,
    ) -> PyResult<Option<(f64, usize, V, V)>> {
        let norm = dot(direction, direction).sqrt();
        if origin.iter().chain(direction.iter()).any(|x| !x.is_finite())
            || norm <= 1e-15
            || maxdist < 0.0
            || maxdist.is_nan()
            || !min_distance.is_finite()
            || min_distance < 0.0
        {
            return Err(PyValueError::new_err("invalid ray length/direction"));
        }
        let d1 = [direction[0] / norm, direction[1] / norm, direction[2] / norm];
        let d2 = Self::ray(origin, d1, maxdist, min_distance)?;
        let Some((length, k)) = self.raycast_core(origin, d2, maxdist, min_distance) else {
            return Ok(None);
        };
        let mut normal = self.normals[k];
        if dot(normal, d1) > 0.0 {
            normal = [-normal[0], -normal[1], -normal[2]];
        }
        let point = [
            origin[0] + d1[0] * length,
            origin[1] + d1[1] * length,
            origin[2] + d1[2] * length,
        ];
        Ok(Some((length, k, point, normal)))
    }
    #[pyo3(signature=(origin,direction,maxdist=f64::INFINITY,min_distance=1e-5,max_hits=4096))]
    fn all_hits(
        &self,
        py: Python<'_>,
        origin: V,
        direction: V,
        maxdist: f64,
        min_distance: f64,
        max_hits: usize,
    ) -> PyResult<Vec<(f64, usize)>> {
        let d = Self::ray(origin, direction, maxdist, min_distance)?;
        Ok(py.detach(|| {
            let mut result = Vec::new();
            if self.nodes.is_empty() {
                return result;
            }
            let mut stack = [0usize; 64];
            stack[0] = 0;
            let mut sp = 1usize;
            while sp > 0 {
                sp -= 1;
                let k = stack[sp];
                let n = &self.nodes[k];
                if Self::boxed(n, origin, d, min_distance, maxdist).is_none() {
                    continue;
                }
                if n.left != u32::MAX {
                    stack[sp] = n.right as usize;
                    sp += 1;
                    stack[sp] = n.left as usize;
                    sp += 1;
                } else {
                    let start = n.start as usize;
                    let end = start + n.len as usize;
                    for tri in &self.leaf_tris[start..end] {
                        if let Some(v) = Self::triangle(tri, origin, d, min_distance, maxdist) {
                            result.push((v, tri.id));
                        }
                    }
                }
            }
            result.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            result.truncate(max_hits);
            result
        }))
    }
    fn raycast_batch(
        &self,
        py: Python<'_>,
        rays: Vec<(V, V, f64)>,
    ) -> PyResult<Vec<Option<(f64, usize)>>> {
        py.detach(|| {
            rays.into_iter()
                .map(|(o, d, m)| self.raycast_one(o, d, m, 1e-5))
                .collect()
        })
    }
}


// Immutable per-profile path graph. Input order is preserved in both adjacency
// lists, matching Python's graph/incoming traversal and first-wins ties.
#[derive(Clone)]
struct PathEdge {
    from: usize,
    to: usize,
    cost: f64,
    key_id: usize,
}

#[derive(Copy, Clone)]
struct PathQueueEntry {
    cost: f64,
    node: usize,
}
impl PartialEq for PathQueueEntry {
    fn eq(&self, other: &Self) -> bool {
        self.cost.total_cmp(&other.cost).is_eq() && self.node == other.node
    }
}
impl Eq for PathQueueEntry {}
impl PartialOrd for PathQueueEntry {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for PathQueueEntry {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.cost.total_cmp(&other.cost).then(self.node.cmp(&other.node))
    }
}

#[pyclass]
pub struct PathGraph {
    edges: Vec<PathEdge>,
    forward: Vec<Vec<usize>>,
    incoming: Vec<Vec<usize>>,
}

#[pymethods]
impl PathGraph {
    #[new]
    #[pyo3(signature = (node_count, edges))]
    fn new(node_count: usize, edges: Vec<(usize, usize, f64, usize)>) -> PyResult<Self> {
        let mut graph = Self {
            edges: Vec::with_capacity(edges.len()),
            forward: vec![Vec::new(); node_count],
            incoming: vec![Vec::new(); node_count],
        };
        for (from, to, cost, key_id) in edges {
            if from >= node_count || to >= node_count || cost.is_nan() || cost < 0.0 {
                return Err(PyValueError::new_err("invalid path edge"));
            }
            let index = graph.edges.len();
            graph.forward[from].push(index);
            graph.incoming[to].push(index);
            graph.edges.push(PathEdge { from, to, cost, key_id });
        }
        Ok(graph)
    }

    #[pyo3(signature = (start, reverse, disabled_ids))]
    fn search(
        &self,
        py: Python<'_>,
        start: usize,
        reverse: bool,
        disabled_ids: Vec<usize>,
    ) -> PyResult<(Vec<f64>, Vec<i64>, Vec<i64>)> {
        if start >= self.forward.len() {
            return Err(PyValueError::new_err("navigation node out of range"));
        }
        Ok(py.detach(|| {
            use std::cmp::Reverse;
            use std::collections::{BinaryHeap, HashSet};
            // A dense edge mask avoids hash lookup in the Dijkstra hot loop
            // without allocating by potentially sparse external key ID.
            let blocked: Vec<bool> = if disabled_ids.is_empty() {
                Vec::new()
            } else {
                let keys: HashSet<usize> = disabled_ids.into_iter().collect();
                self.edges.iter().map(|edge| keys.contains(&edge.key_id)).collect()
            };
            let count = self.forward.len();
            let mut distances = vec![f64::INFINITY; count];
            let mut previous = vec![-1; count];
            let mut edge_indices = vec![-1; count];
            let adjacency = if reverse { &self.incoming } else { &self.forward };
            let mut heap = BinaryHeap::new();
            distances[start] = 0.0;
            heap.push(Reverse(PathQueueEntry { cost: 0.0, node: start }));
            while let Some(Reverse(PathQueueEntry { cost, node })) = heap.pop() {
                if cost != distances[node] {
                    continue;
                }
                for &index in &adjacency[node] {
                    if !blocked.is_empty() && blocked[index] {
                        continue;
                    }
                    let edge = &self.edges[index];
                    let other = if reverse { edge.from } else { edge.to };
                    let value = cost + edge.cost;
                    if value + 1e-8 < distances[other] {
                        distances[other] = value;
                        previous[other] = node as i64;
                        edge_indices[other] = index as i64;
                        heap.push(Reverse(PathQueueEntry { cost: value, node: other }));
                    }
                }
            }
            (distances, previous, edge_indices)
        }))
    }
}
