"""Versioned source-space arena geometry, directed navigation and optional native BVH.

Coordinates are source XYZ (Y up). Geometry is a qualified visual/NAV proxy,
not authoritative game BSP. Standard-library fallback has no build dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import gzip
import hashlib
import heapq
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

Vec3 = tuple[float, float, float]
ROOT = Path(
    os.environ.get("WF_RIVEN_ROOT")
    or getattr(sys, "_MEIPASS", None)
    or Path(__file__).resolve().parents[2]
).resolve()
DEFAULT_MAP = "corpus-ship-defense"


def _vec(v: Sequence[float]) -> Vec3:
    if len(v) != 3:
        raise ValueError("expected XYZ triple")
    p = tuple(float(x) for x in v)
    if not all(math.isfinite(x) for x in p):
        raise ValueError("coordinates must be finite")
    return p


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def distance(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


@dataclass(frozen=True)
class RayHit:
    distance: float
    triangle: int
    position: Vec3
    normal: Vec3
    source: Any = None

    @property
    def t(self):
        return self.distance

    def as_dict(self):
        return {
            "distance": self.distance,
            "triangle": self.triangle,
            "position": list(self.position),
            "normal": list(self.normal),
            "source": self.source,
        }


class TriangleBVH:
    """Double-sided nearest-hit BVH; Python reference for wfcore.SpatialIndex."""

    def __init__(
        self,
        vertices: Sequence[Sequence[float]],
        triangles: Sequence[Sequence[int]],
        *,
        native: bool = True,
    ):
        self.vertices = tuple(_vec(v) for v in vertices)
        self.triangles = tuple(tuple(int(i) for i in t) for t in triangles)
        if any(
            len(t) != 3 or min(t) < 0 or max(t) >= len(self.vertices)
            for t in self.triangles
        ):
            raise ValueError("invalid collision triangle")
        self.native = None
        if native and os.environ.get("WF_ARENA_PYTHON_SPATIAL") != "1":
            try:
                from . import wfcore

                cls = getattr(wfcore, "SpatialIndex", None)
                if cls is not None:
                    self.native = cls(self.vertices, self.triangles)
            except ImportError:
                pass
        self._bounds = []
        self._centers = []
        self._nodes = []
        self._root = -1
        if self.native is None:
            self._ensure_python_tree()

    def _ensure_python_tree(self):
        if self._root >= 0 or not self.triangles:
            return
        self._bounds = []
        self._centers = []
        for t in self.triangles:
            points = [self.vertices[k] for k in t]
            lo = tuple(min(p[i] for p in points) for i in range(3))
            hi = tuple(max(p[i] for p in points) for i in range(3))
            self._bounds.append((lo, hi))
            self._centers.append(tuple((lo[i] + hi[i]) * 0.5 for i in range(3)))
        self._nodes = []
        self._root = self._build(list(range(len(self.triangles))))

    def _build(self, ids):
        lo = tuple(min(self._bounds[k][0][i] for k in ids) for i in range(3))
        hi = tuple(max(self._bounds[k][1][i] for k in ids) for i in range(3))
        node = len(self._nodes)
        self._nodes.append(None)
        if len(ids) <= 12:
            self._nodes[node] = (lo, hi, -1, -1, tuple(ids))
        else:
            axis = max(range(3), key=lambda i: hi[i] - lo[i])
            ids.sort(key=lambda k: (self._centers[k][axis], k))
            mid = len(ids) // 2
            a, b = self._build(ids[:mid]), self._build(ids[mid:])
            self._nodes[node] = (lo, hi, a, b, ())
        return node

    @staticmethod
    def _box(o, d, lo, hi, lower, upper):
        for i in range(3):
            if abs(d[i]) < 1e-15:
                if o[i] < lo[i] - 1e-8 or o[i] > hi[i] + 1e-8:
                    return False
            else:
                a, b = (lo[i] - o[i]) / d[i], (hi[i] - o[i]) / d[i]
                if a > b:
                    a, b = b, a
                lower, upper = max(lower, a), min(upper, b)
                if lower > upper:
                    return False
        return True

    def _triangle(self, k, o, d, minimum, maximum):
        t = self.triangles[k]
        a, b, c = (self.vertices[i] for i in t)
        e1, e2 = _sub(b, a), _sub(c, a)
        h = _cross(d, e2)
        det = _dot(e1, h)
        if abs(det) < 1e-10:
            return None
        inv = 1.0 / det
        s = _sub(o, a)
        u = _dot(s, h) * inv
        if u < -1e-8 or u > 1.0 + 1e-8:
            return None
        q = _cross(s, e1)
        v = _dot(d, q) * inv
        if v < -1e-8 or u + v > 1.0 + 1e-8:
            return None
        length = _dot(e2, q) * inv
        return length if minimum <= length <= maximum else None

    def raycast(self, origin, direction, maxdist=math.inf, *, min_distance=1e-5):
        o, d = _vec(origin), _vec(direction)
        norm = math.sqrt(_dot(d, d))
        maximum = float(maxdist)
        minimum = float(min_distance)
        if (
            norm <= 1e-15
            or maximum < 0
            or math.isnan(maximum)
            or not math.isfinite(minimum)
            or minimum < 0
        ):
            raise ValueError("invalid ray length/direction")
        d = tuple(x / norm for x in d)
        if self.native is not None:
            value = self.native.raycast(o, d, maximum, minimum)
            nearest = (value[0], value[1]) if value is not None else None
        else:
            nearest = None
            stack = [self._root] if self._root >= 0 else []
            while stack:
                node = self._nodes[stack.pop()]
                lo, hi, left, right, ids = node
                if not self._box(o, d, lo, hi, minimum, maximum):
                    continue
                if left >= 0:
                    stack.extend((right, left))
                    continue
                for k in ids:
                    value = self._triangle(k, o, d, minimum, maximum)
                    if value is not None and (
                        nearest is None
                        or value < maximum
                        or (value == maximum and k < nearest[1])
                    ):
                        maximum, nearest = value, (value, k)
        if nearest is None:
            return None
        length, k = nearest
        a, b, c = (self.vertices[i] for i in self.triangles[k])
        normal = _cross(_sub(b, a), _sub(c, a))
        nlen = math.sqrt(_dot(normal, normal))
        normal = tuple(x / nlen for x in normal) if nlen else (0.0, 0.0, 0.0)
        if _dot(normal, d) > 0:
            normal = tuple(-x for x in normal)
        return RayHit(length, k, tuple(o[i] + d[i] * length for i in range(3)), normal)

    def all_hits(
        self, origin, direction, maxdist=math.inf, *, min_distance=1e-5, max_hits=4096
    ):
        """Sorted triangle intersections (coincident triangles retained).

        Caller must group equal distances before material-thickness reasoning;
        visual meshes do not guarantee closed or watertight solids.
        """
        o, d = _vec(origin), _vec(direction)
        norm = math.sqrt(_dot(d, d))
        if norm <= 1e-15 or maxdist < 0 or math.isnan(maxdist):
            raise ValueError("invalid ray")
        d = tuple(x / norm for x in d)
        if self.native is not None and hasattr(self.native, "all_hits"):
            pairs = self.native.all_hits(o, d, maxdist, min_distance, max_hits)
        else:
            pairs = []
            # Native BVH may be present without all_hits on an older build.
            self._ensure_python_tree()
            stack = [self._root] if self._root >= 0 else []
            while stack:
                lo, hi, left, right, ids = self._nodes[stack.pop()]
                if not self._box(o, d, lo, hi, min_distance, maxdist):
                    continue
                if left >= 0:
                    stack.extend((right, left))
                else:
                    for k in ids:
                        value = self._triangle(k, o, d, min_distance, maxdist)
                        if value is not None:
                            pairs.append((value, k))
            pairs.sort()
            pairs = pairs[:max_hits]
        found = []
        for length, k in pairs:
            a, b, c = (self.vertices[i] for i in self.triangles[k])
            normal = _cross(_sub(b, a), _sub(c, a))
            norm = math.sqrt(_dot(normal, normal))
            normal = tuple(x / norm for x in normal) if norm else (0.0, 0.0, 0.0)
            if _dot(normal, d) > 0:
                normal = tuple(-x for x in normal)
            found.append(
                RayHit(length, k, tuple(o[i] + d[i] * length for i in range(3)), normal)
            )
        return found

    first_hit = raycast

    def raycast_batch(self, rays):
        """Iterable of (origin, direction, max_distance); identical to individual casts."""
        return [self.raycast(*r) for r in rays]


@dataclass(frozen=True)
class Edge:
    from_node: int
    to_node: int
    points: tuple[Vec3, ...]
    kind: str
    seconds: float
    enemy: bool
    enemy_seconds: float
    length: float
    source: Any = None
    key: str = ""

    @property
    def node(self):
        return self.to_node

    @property
    def cost(self):
        return self.seconds

    def time(self, profile="player"):
        if profile in ("enemy", "walking") and not self.enemy:
            return math.inf
        if profile == "enemy":
            return self.enemy_seconds
        if profile == "drone":
            return self.length / 5.0
        if profile not in ("player", "walking"):
            raise ValueError("unknown movement profile")
        return self.seconds


@dataclass
class SearchResult:
    start: int
    profile: str
    reverse: bool
    distances: list[float]
    previous: list[int]
    edges: list[Edge | None]

    @property
    def d(self):
        return self.distances

    @property
    def prev(self):
        return self.previous


class ArenaScene:
    def __init__(
        self,
        raw: dict,
        navigation: dict | None = None,
        *,
        map_id=DEFAULT_MAP,
        sources=None,
        native=True,
    ):
        self.raw = raw
        self.map_id = map_id
        self.sources = sources or raw.get("metadata", {})
        self.metadata = raw.get("metadata", {})
        self.navigation = navigation or raw.get("navigation", {})
        self.policy = self.navigation.get("policy", {})
        self.points = tuple(_vec(p) for p in raw["nav"]["nodePositions"])
        self.nodes = self.points
        self.spawns = raw.get("spawns", [])
        self.start = raw["start"]
        self.graph = [[] for _ in self.points]
        self.incoming = [[] for _ in self.points]
        self.disabled: set[str] = set()
        self.metrics = {"rays": 0, "blocked": 0, "pathSearches": 0}
        for p in raw["nav"]["nativePortals"]:
            a, b = p["fromFace"], p["toFace"]
            path = [self.points[a], p["portal"], self.points[b]]
            length = sum(distance(x, y) for x, y in zip(path, path[1:]))
            for u, v, pts in ((a, b, path), (b, a, path[::-1])):
                self._add(
                    u,
                    v,
                    pts,
                    "walk",
                    length / 6,
                    True,
                    length / 3.6,
                    {"type": "native-nav-portal"},
                )
        for link in self.navigation.get("links", []):
            self._add(
                link["from"],
                link["to"],
                link["points"],
                link["kind"],
                link["seconds"],
                bool(link.get("enemy", False)),
                link.get("enemySeconds", math.inf),
                link.get("source"),
            )
        collision = raw["collision"]
        self.collision = TriangleBVH(
            collision["vertices"], collision["triangles"], native=native
        )
        self.collision_sources = collision.get("triangleSources", [])

    def reset_runtime(self):
        """Clear mutable job state; cached geometry/graph is shared between jobs.

        Concurrent jobs should instead pass a job-local disabled set to search.
        Never mutate graph/raw/metadata or share self.disabled across active jobs.
        """
        self.disabled.clear()
        for key in self.metrics:
            self.metrics[key] = 0

    def _add(self, a, b, points, kind, seconds, enemy, enemy_seconds, source):
        if not (0 <= a < len(self.points) and 0 <= b < len(self.points)):
            raise ValueError("navigation endpoint out of range")
        pts = tuple(_vec(p) for p in points)
        if len(pts) < 2 or not math.isfinite(float(seconds)) or seconds < 0:
            raise ValueError("invalid navigation edge")
        length = sum(distance(x, y) for x, y in zip(pts, pts[1:]))
        key = f"{a}:{b}:{kind}"
        edge = Edge(
            a,
            b,
            pts,
            kind,
            float(seconds),
            enemy,
            float(enemy_seconds) if enemy_seconds is not None else math.inf,
            length,
            source,
            key,
        )
        self.graph[a].append(edge)
        self.incoming[b].append(edge)

    def search(self, start: int, profile="player", reverse=False, *, disabled=None):
        if not 0 <= start < len(self.points):
            raise ValueError("navigation node out of range")
        if profile not in ("player", "enemy", "walking", "drone"):
            raise ValueError("unknown movement profile")
        self.metrics["pathSearches"] += 1
        distances = [math.inf] * len(self.points)
        previous = [-1] * len(self.points)
        edges = [None] * len(self.points)
        distances[start] = 0.0
        heap = [(0.0, start)]
        forbidden = self.disabled if disabled is None else disabled
        graph = self.incoming if reverse else self.graph
        while heap:
            cost, node = heapq.heappop(heap)
            if cost != distances[node]:
                continue
            for edge in graph[node]:
                if edge.key in forbidden:
                    continue
                other = edge.from_node if reverse else edge.to_node
                weight = edge.time(profile)
                value = cost + weight
                if value + 1e-8 < distances[other]:
                    distances[other], previous[other], edges[other] = value, node, edge
                    heapq.heappush(heap, (value, other))
        return SearchResult(start, profile, reverse, distances, previous, edges)

    def path(self, start: int, goal: int, profile="player", *, reverse=False):
        if not 0 <= goal < len(self.points):
            raise ValueError("navigation node out of range")
        result = self.search(goal if reverse else start, profile, reverse)
        if not math.isfinite(result.distances[start if reverse else goal]):
            return []
        found = []
        node = start if reverse else goal
        target = goal if reverse else start
        while node != target:
            edge = result.edges[node]
            if edge is None:
                return []
            found.append(edge)
            node = result.previous[node]
        return found if reverse else found[::-1]

    route = path

    def nearest_node(self, position, *, candidates=None):
        p = _vec(position)
        ids = range(len(self.points)) if candidates is None else candidates
        return min(ids, key=lambda k: (distance(p, self.points[k]), k))

    def raycast(self, origin, direction, maxdist=math.inf, *, min_distance=1e-5):
        self.metrics["rays"] += 1
        hit = self.collision.raycast(
            origin, direction, maxdist, min_distance=min_distance
        )
        if hit:
            self.metrics["blocked"] += 1
            if hit.triangle < len(self.collision_sources):
                hit = RayHit(
                    hit.distance,
                    hit.triangle,
                    hit.position,
                    hit.normal,
                    self.collision_sources[hit.triangle],
                )
        return hit

    def trace_segment(self, origin, target, *, endpoint_epsilon=1e-4):
        a, b = _vec(origin), _vec(target)
        delta = _sub(b, a)
        length = math.sqrt(_dot(delta, delta))
        if length <= endpoint_epsilon * 2:
            return None
        return self.raycast(
            a, delta, length - endpoint_epsilon, min_distance=endpoint_epsilon
        )

    first_hit = raycast

    def ground_support(self, position, *, max_drop=2.0, max_rise=0.5):
        """Nearest downward proxy support; not a native walkability assertion."""
        p = _vec(position)
        return self.raycast(
            (p[0], p[1] + max_rise, p[2]), (0.0, -1.0, 0.0), max_drop + max_rise
        )

    def all_hits(self, origin, direction, maxdist=math.inf, **kwargs):
        result = self.collision.all_hits(origin, direction, maxdist, **kwargs)
        return [
            RayHit(
                h.distance,
                h.triangle,
                h.position,
                h.normal,
                (
                    self.collision_sources[h.triangle]
                    if h.triangle < len(self.collision_sources)
                    else None
                ),
            )
            for h in result
        ]

    def visible(self, a, b):
        return self.trace_segment(a, b) is None

    def check_motion(
        self,
        points: Iterable[Sequence[float]],
        *,
        radius=0.22,
        heights=(0.5, 1.0, 1.65),
        ground_step=False,
    ):
        """Sampled body-rail segment sweep; not a full capsule/physics solver.

        ground_step uses the higher tread before horizontal movement. Engine must
        enforce source step-height/support policy separately; no invented support.
        """
        pts = tuple(_vec(p) for p in points)
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            if ground_step:
                y = max(a[1], b[1])
                a, b = (a[0], y, a[2]), (b[0], y, b[2])
            for x, z in (
                (0.0, 0.0),
                (radius, 0.0),
                (-radius, 0.0),
                (0.0, radius),
                (0.0, -radius),
            ):
                for h in heights:
                    hit = self.trace_segment(
                        (a[0] + x, a[1] + h, a[2] + z), (b[0] + x, b[1] + h, b[2] + z)
                    )
                    if hit:
                        return {
                            "clear": False,
                            "segment": i,
                            "hit": hit.as_dict(),
                            "qualification": "sampled body rails, not capsule sweep",
                        }
        return {
            "clear": True,
            "segments": max(0, len(pts) - 1),
            "qualification": "sampled body rails, not capsule sweep",
        }


def scene_catalog(root: Path | None = None):
    base = Path(root) if root else ROOT
    return json.loads((base / "data/arena/catalog.json").read_text(encoding="utf-8"))


def list_maps(*, root: Path | None = None):
    """Catalog metadata list, including an explicit default flag and stable IDs."""
    catalog = scene_catalog(root)
    return [
        dict(value, default=key == catalog.get("defaultMap", DEFAULT_MAP))
        for key, value in catalog["maps"].items()
    ]


def _asset_name(name):
    # Normalize known API suffixes only; lookup still uses catalog allowlist.
    name = str(name)
    for suffix in (".json.gz", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def asset_path(map_id=DEFAULT_MAP, asset="scene", *, root: Path | None = None):
    base = Path(root) if root else ROOT
    catalog = scene_catalog(base)
    asset = _asset_name(asset)
    entry = catalog["maps"].get(map_id)
    if entry is None or asset not in entry["assets"]:
        raise ValueError("unknown arena map or asset")
    path = (base / "data/arena" / entry["assets"][asset]["file"]).resolve()
    if not path.is_relative_to((base / "data/arena").resolve()):
        raise ValueError("arena asset escapes data directory")
    return path


def load_asset(map_id=DEFAULT_MAP, asset="scene", *, root: Path | None = None):
    path = asset_path(map_id, asset, root=root)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache(maxsize=2)
def load_scene(map_id=DEFAULT_MAP, *, root: Path | None = None, native=True):
    catalog = scene_catalog(root)
    entry = catalog["maps"].get(map_id)
    if entry is None:
        raise ValueError("unknown arena map")
    # Compressed bytes are verified before loading; offline package cannot silently drift.
    for kind in ("scene", "navigation"):
        path = asset_path(map_id, kind, root=root)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["assets"][kind]["sha256"]:
            raise ValueError(f"arena {kind} checksum mismatch")
    return ArenaScene(
        load_asset(map_id, "scene", root=root),
        load_asset(map_id, "navigation", root=root),
        map_id=map_id,
        sources=entry,
        native=native,
    )


def asset_bytes(map_id=DEFAULT_MAP, name="scene", *, root: Path | None = None):
    """Compressed original asset for HTTP: bytes, content type, content encoding."""
    path = asset_path(map_id, name, root=root)
    return path.read_bytes(), "application/json", "gzip"
