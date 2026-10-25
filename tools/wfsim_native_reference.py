"""Use a pinned simfleet WFSim library through its documented C API."""
from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


class NativeReference:
    def __init__(self, library: Path, engine: str, sha256: str | None = None):
        self.path = library.resolve()
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if sha256 is not None and self.sha256 != sha256:
            raise ValueError('native reference library hash mismatch')
        self.library = ctypes.CDLL(str(self.path))
        self.library.sfe_engine_id.restype = ctypes.c_char_p
        self.engine = self.library.sfe_engine_id().decode('ascii')
        if self.engine != engine:
            raise ValueError(f'native engine {self.engine} differs from requested {engine}')
        self.api = self.library.sfe_api
        self.api.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                             ctypes.POINTER(ctypes.c_size_t)]
        self.api.restype = ctypes.c_void_p
        self.free = self.library.sfe_free
        self.free.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.free.restype = None

    def call(self, endpoint: str, body: dict) -> dict:
        path = endpoint.encode('utf-8')
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        size = ctypes.c_size_t()
        pointer = self.api(path, len(path), payload, len(payload), ctypes.byref(size))
        if not pointer:
            raise RuntimeError('reference engine panicked')
        try:
            result = json.loads(ctypes.string_at(pointer, size.value))
        finally:
            self.free(pointer, size.value)
        if result.get('ok') is False:
            raise ValueError(result.get('error') or result)
        return result


class WasmReference:
    """Portable fallback using only the official captured JavaScript/WASM assets."""
    def __init__(self, runtime: Path):
        self.runtime = runtime.resolve()

    def call(self, endpoint: str, body: dict) -> dict:
        runner = Path(__file__).with_name('run_reference_wasm.mjs')
        with tempfile.TemporaryDirectory(prefix='wfsim-reference-') as directory:
            source, target = Path(directory) / 'input.json', Path(directory) / 'output.json'
            source.write_text(json.dumps(body, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            process = subprocess.run(['node', str(runner), str(self.runtime), endpoint, str(source), str(target)],
                                     capture_output=True, text=True, encoding='utf-8', timeout=300)
            if not target.exists():
                raise RuntimeError('reference runner failed: ' + process.stderr[-2000:])
            result = json.loads(target.read_text(encoding='utf-8'))
            if result.get('ok') is False or process.returncode:
                raise ValueError(result.get('error') or process.stderr[-2000:])
            return result


def reference_from_manifest(runtime: Path, manifest: dict):
    if manifest.get('library'):
        return NativeReference(runtime / 'native' / manifest['library'], manifest['engine'], manifest['library_sha256'])
    return WasmReference(runtime)
