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
#[derive(Clone)]
struct Node {
    lo: V,
    hi: V,
    left: Option<usize>,
    right: Option<usize>,
    ids: Vec<usize>,
}
#[pyclass]
pub struct SpatialIndex {
    vertices: Vec<V>,
    triangles: Vec<[usize; 3]>,
    nodes: Vec<Node>,
}
impl SpatialIndex {
    fn build(&mut self, mut ids: Vec<usize>) -> usize {
        let mut lo = [f64::INFINITY; 3];
        let mut hi = [f64::NEG_INFINITY; 3];
        for &k in &ids {
            for &v in &self.triangles[k] {
                for a in 0..3 {
                    lo[a] = lo[a].min(self.vertices[v][a]);
                    hi[a] = hi[a].max(self.vertices[v][a]);
                }
            }
        }
        let index = self.nodes.len();
        self.nodes.push(Node {
            lo,
            hi,
            left: None,
            right: None,
            ids: Vec::new(),
        });
        if ids.len() <= 12 {
            self.nodes[index].ids = ids;
        } else {
            let mut axis = 0;
            for a in 1..3 {
                if hi[a] - lo[a] > hi[axis] - lo[axis] {
                    axis = a;
                }
            }
            ids.sort_by(|&a, &b| {
                let center = |k: usize| {
                    let t = self.triangles[k];
                    (self.vertices[t[0]][axis]
                        + self.vertices[t[1]][axis]
                        + self.vertices[t[2]][axis])
                        / 3.
                };
                center(a).total_cmp(&center(b)).then(a.cmp(&b))
            });
            let other = ids.split_off(ids.len() / 2);
            let left = self.build(ids);
            let right = self.build(other);
            self.nodes[index].left = Some(left);
            self.nodes[index].right = Some(right);
        }
        index
    }
    fn boxed(node: &Node, o: V, d: V, mut lower: f64, mut upper: f64) -> bool {
        for i in 0..3 {
            if d[i].abs() < 1e-15 {
                if o[i] < node.lo[i] - 1e-8 || o[i] > node.hi[i] + 1e-8 {
                    return false;
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
                    return false;
                }
            }
        }
        true
    }
    fn triangle(&self, k: usize, o: V, d: V, lower: f64, upper: f64) -> Option<f64> {
        let t = self.triangles[k];
        let a = self.vertices[t[0]];
        let e1 = sub(self.vertices[t[1]], a);
        let e2 = sub(self.vertices[t[2]], a);
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
        let mut value = Self {
            vertices,
            triangles,
            nodes: Vec::new(),
        };
        if n > 0 {
            value.build((0..n).collect());
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
        let d = Self::ray(origin, direction, maxdist, min_distance)?;
        let mut upper = maxdist;
        let mut result: Option<(f64, usize)> = None;
        let mut stack = if self.nodes.is_empty() {
            vec![]
        } else {
            vec![0]
        };
        while let Some(k) = stack.pop() {
            let n = &self.nodes[k];
            if !Self::boxed(n, origin, d, min_distance, upper) {
                continue;
            }
            if let Some(left) = n.left {
                stack.push(n.right.unwrap());
                stack.push(left);
            } else {
                for &t in &n.ids {
                    if let Some(v) = self.triangle(t, origin, d, min_distance, upper) {
                        if result.is_none() || v < upper || (v == upper && t < result.unwrap().1) {
                            upper = v;
                            result = Some((v, t));
                        }
                    }
                }
            }
        }
        Ok(result)
    }
    #[pyo3(signature=(origin,direction,maxdist=f64::INFINITY,min_distance=1e-5,max_hits=4096))]
    fn all_hits(
        &self,
        origin: V,
        direction: V,
        maxdist: f64,
        min_distance: f64,
        max_hits: usize,
    ) -> PyResult<Vec<(f64, usize)>> {
        let d = Self::ray(origin, direction, maxdist, min_distance)?;
        let mut result = Vec::new();
        let mut stack = if self.nodes.is_empty() {
            vec![]
        } else {
            vec![0]
        };
        while let Some(k) = stack.pop() {
            let n = &self.nodes[k];
            if !Self::boxed(n, origin, d, min_distance, maxdist) {
                continue;
            }
            if let Some(left) = n.left {
                stack.push(n.right.unwrap());
                stack.push(left);
            } else {
                for &t in &n.ids {
                    if let Some(v) = self.triangle(t, origin, d, min_distance, maxdist) {
                        result.push((v, t));
                    }
                }
            }
        }
        result.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
        result.truncate(max_hits);
        Ok(result)
    }
    fn raycast_batch(&self, rays: Vec<(V, V, f64)>) -> PyResult<Vec<Option<(f64, usize)>>> {
        rays.into_iter()
            .map(|(o, d, m)| self.raycast(o, d, m, 1e-5))
            .collect()
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
            let keys: HashSet<usize> = disabled_ids.into_iter().collect();
            // A dense edge mask avoids hash lookup in the Dijkstra hot loop
            // without allocating by potentially sparse external key ID.
            let blocked: Vec<bool> = self.edges.iter()
                .map(|edge| keys.contains(&edge.key_id)).collect();
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
                    if blocked[index] {
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
