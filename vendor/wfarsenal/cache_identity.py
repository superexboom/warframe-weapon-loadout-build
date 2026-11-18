"""Narrow arena-only compatibility for the pre-arena score identity.

All score input files are still read and hashed. Only app.py and parallel.py
may supply audited baseline bytes, and only if a complete AST comparison after
specific arena-only reversals proves all remaining source identical. Unknown
changes keep their own identity. On newer app revisions only the bodies of
the five isolated arena entry points can be omitted; every other byte stays.
"""

from __future__ import annotations
import ast
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path

BASELINE_SHA256 = "d373d7e9bf28d9928ce19ad0d624b4ac68a47fcfddc1563eec4238c5daf4afb2"
ARENA_FUNCTIONS = frozenset(
    (
        "_arena_context",
        "arena_catalog_payload",
        "arena_start_payload",
        "arena_cancel_payload",
        "arena_standing_point_payload",
    )
)
DISPATCH_GUARD = "not (self._queue and self._running < (min(self.workers, 10) - self._external - self._external_waiting if self._external or self._external_waiting else self.workers))"
MIME_OVERRIDE = '"text/javascript" if target.suffix == ".mjs" else (mimetypes.guess_type(target.name)[0] or "application/octet-stream")'


def _dump(node):
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _same(node, expression):
    return _dump(node) == _dump(ast.parse(expression, mode="eval").body)


def _arena_entry(node):
    if not isinstance(node, ast.FunctionDef) or node.name not in ARENA_FUNCTIONS:
        return False
    expected = 'def f(): pass' if node.name == 'arena_catalog_payload' else 'def f(payload): pass'
    return not node.decorator_list and node.returns is None and _dump(node.args) == _dump(ast.parse(expected).body[0].args)


class _AppArenaOnly(ast.NodeTransformer):
    """Reverse only the reviewed arena patch, preserving all other HTTP code."""

    def __init__(self):
        self.function = None
        self.handler = False

    def visit_FunctionDef(self, node):
        if self.function is None and not self.handler and _arena_entry(node):
            return None
        before = self.function
        self.function = node.name
        node = self.generic_visit(node)
        self.function = before
        return node

    def visit_ClassDef(self, node):
        previous = self.handler
        self.handler = node.name == "PortableHandler"
        node = self.generic_visit(node)
        self.handler = previous
        return node

    def visit_ImportFrom(self, node):
        if (
            self.function == "_analysis_inputs_fingerprint"
            and node.module == "wfarsenal.cache_identity"
            and [(a.name, a.asname) for a in node.names]
            == [("score_source_bytes", None)]
        ):
            return None
        return node

    def visit_Assign(self, node):
        if self.function == "_analysis_inputs_fingerprint" and _dump(node) == _dump(
            ast.parse("data = score_source_bytes(path.name, data, ROOT)").body[0]
        ):
            return None
        if (
            self.handler
            and self.function == "_serve_static"
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "content_type"
            and _same(node.value, MIME_OVERRIDE)
        ):
            node.value = node.value.orelse
        return self.generic_visit(node)

    def visit_If(self, node):
        if self.handler and self.function == "do_GET":
            # Only explicitly addressed arena endpoints; never remove arbitrary
            # branches just because their body imports an arena module.
            allowed = (
                'path == "/api/arena/catalog"',
                'path == "/api/arena/jobs"',
                'path.startswith("/api/arena/assets/")',
            )
            if any(_same(node.test, test) for test in allowed):
                return [self.visit(child) for child in node.orelse]
        if (
            self.handler
            and self.function == "_serve_static"
            and _same(node.test, 'request_path.startswith("/arena/")')
        ):
            return [self.visit(child) for child in node.orelse]
        return self.generic_visit(node)

    def visit_Dict(self, node):
        if self.handler and self.function == "do_POST":
            pairs = [
                (k, v)
                for k, v in zip(node.keys, node.values)
                if not (
                    isinstance(k, ast.Constant)
                    and k.value
                    in (
                        "/api/arena/jobs",
                        "/api/arena/cancel",
                        "/api/arena/standing-point",
                    )
                )
            ]
            node.keys = [k for k, _ in pairs]
            node.values = [v for _, v in pairs]
        return self.generic_visit(node)


class _ParallelArenaOnly(ast.NodeTransformer):
    def __init__(self):
        self.scheduler = False
        self.function = None

    def visit_ClassDef(self, node):
        previous = self.scheduler
        self.scheduler = node.name == "_Scheduler"
        node = self.generic_visit(node)
        self.scheduler = previous
        return node

    def visit_FunctionDef(self, node):
        if self.scheduler and node.name == "external_slot":
            expected_args = (
                ast.parse("def f(self, cancelled=lambda: False): pass").body[0].args
            )
            if (
                node.returns is None
                and _dump(node.args) == _dump(expected_args)
                and [_dump(item) for item in node.decorator_list]
                == [_dump(ast.Name(id="contextmanager", ctx=ast.Load()))]
            ):
                return None
        previous = self.function
        self.function = node.name
        node = self.generic_visit(node)
        self.function = previous
        return node

    def visit_ImportFrom(self, node):
        if node.module == "contextlib" and [(a.name, a.asname) for a in node.names] == [
            ("contextmanager", None)
        ]:
            return None
        return node

    def visit_Assign(self, node):
        # Optional explicit initialization of arena reservation counters has no
        # reducer/scorer role. Every other scheduler assignment is retained.
        if (
            self.scheduler
            and self.function == "__init__"
            and any(
                _dump(node) == _dump(ast.parse(text).body[0])
                for text in ("self._external = 0", "self._external_waiting = 0")
            )
        ):
            return None
        return self.generic_visit(node)

    def visit_While(self, node):
        if (
            self.scheduler
            and self.function == "_dispatch"
            and _same(node.test, DISPATCH_GUARD)
        ):
            node.test = ast.parse(
                "not (self._queue and self._running < self.workers)", mode="eval"
            ).body
        return self.generic_visit(node)


def projected_source(name: str, source: bytes) -> str:
    tree = ast.parse(source.decode("utf-8-sig"))
    visitor = _AppArenaOnly() if name == "app.py" else _ParallelArenaOnly()
    return _dump(visitor.visit(tree))


@lru_cache(maxsize=4)
def _baseline(root: Path):
    path = root / "data/arena/score-identity-baseline.json.gz"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != BASELINE_SHA256:
        raise OSError("score identity compatibility baseline checksum mismatch")
    payload = json.loads(gzip.decompress(data))
    if payload.get("schema") != 1 or set(payload.get("files", {})) != {
        "app.py",
        "parallel.py",
    }:
        raise OSError("invalid score identity compatibility baseline")
    return {
        name: (text.encode("utf-8"), projected_source(name, text.encode("utf-8")))
        for name, text in payload["files"].items()
    }


@lru_cache(maxsize=4)
def _score_python(name, source, root):
    baseline, projected = _baseline(root)[name]
    try:
        tree = ast.parse(source.decode('utf-8-sig'))
        if name == 'app.py':
            lines = source.splitlines(keepends=True)
            # Keep the declaration as written; remove only complete standalone
            # bodies. Defaults, decorators, module statements and HTTP routes
            # still affect the cache as soon as they change.
            for node in reversed(tree.body):
                if _arena_entry(node) and node.body[0].lineno > node.lineno:
                    lines[node.lineno:node.end_lineno] = [b'    pass\n']
            current = b''.join(lines)
            visitor = _AppArenaOnly()
        else:
            current = source
            visitor = _ParallelArenaOnly()
        return baseline if _dump(visitor.visit(tree)) == projected else current
    except (SyntaxError, UnicodeError, ValueError):
        return source


def score_source_bytes(name: str, source: bytes, root: Path) -> bytes:
    """Return exact pre-arena bytes only after full retained-AST equality.

    No cached identity or cache entries are accepted by this helper. Changing
    ANY other dependency bytes keeps the original digest invalidation behavior.
    A source syntax error, unmatched transformation or scoring mutation is never
    normalized into the old identity. Frozen bundles ship the pinned baseline.
    """
    if name not in ("app.py", "parallel.py"):
        return source
    return _score_python(name, source, Path(root).resolve())
