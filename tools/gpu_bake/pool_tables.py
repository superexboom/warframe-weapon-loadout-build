"""Exact status tables for offline baking. CUDA belongs to one coordinator thread."""
from __future__ import annotations

import ctypes as c
from contextlib import contextmanager
from multiprocessing import Pipe
from pathlib import Path
from threading import Thread
from time import perf_counter

from .cuda_driver import Cuda


STEPS = 24
BATCH = 128
MAX_KEYS = 512  # per shard; the device buffers are reused across all workers


class PoolDevice:
    def __init__(self, nvrtc_dir):
        self.cuda = Cuda(nvrtc_dir)
        try:
            self.cuda.compile(Path(__file__).resolve().parents[1] / 'gpu_status_probe.cu')
            self.inputs = self.cuda.allocate(MAX_KEYS * 2 * 8)
            self.output = self.cuda.allocate(MAX_KEYS * 32 * 11 * 8)
            self.name = self.cuda.name
        except BaseException:
            self.cuda.close()
            raise

    def build(self, keys, steps):
        n = len(keys)
        if not 1 <= n <= MAX_KEYS or not 1 <= steps <= 32:
            raise ValueError('pool table batch exceeds device buffers')
        wire = (c.c_double * (n * 2))(*(x for key in keys for x in key))
        result = (c.c_ubyte * (n * steps * 11 * 8))()
        self.cuda.upload(self.inputs, wire)
        self.cuda.launch('pool_prefixes', n * steps, [self.inputs, self.output, c.c_int(n), c.c_int(steps)])
        self.cuda.download(result, self.output)  # synchronous DtoH on the same stream
        return bytes(result)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cuda.close()


class PoolBroker:
    """Workers send only the observed probabilities; no fights or game objects cross processes."""
    def __init__(self, channel, nvrtc_dir):
        self.channel = channel
        self.nvrtc_dir = nvrtc_dir
        self.summary = dict(device=None, error=None, batches=0, verifiedKeys=0,
                            startupSeconds=0., deviceSeconds=0., referenceSeconds=0.)
        self.thread = Thread(target=self._serve, name='bake-cuda')

    def _serve(self):
        from wfarsenal import native_replay
        core = native_replay.wfcore
        device = None
        try:
            while (request := self.channel.get()) is not None:
                writer, keys = request
                data = None
                with writer:
                    if not self.summary['error']:
                        try:
                            if device is None:
                                start = perf_counter()
                                device = PoolDevice(self.nvrtc_dir)
                                self.summary.update(device=device.name, startupSeconds=perf_counter()-start)
                            start = perf_counter()
                            candidate = device.build(keys, STEPS)
                            end = perf_counter()
                            self.summary['deviceSeconds'] += end-start
                            if candidate != core.bake_pool_reference(keys, STEPS):
                                raise ArithmeticError('CUDA status table differs from Rust')
                            self.summary['referenceSeconds'] += perf_counter()-end
                            self.summary['verifiedKeys'] += len(keys)
                            self.summary['batches'] += 1
                            data = candidate
                        except Exception as exc:
                            self.summary['error'] = f'{type(exc).__name__}: {exc}'
                    try:
                        writer.send((data, self.summary['error']))
                    except (BrokenPipeError, EOFError, OSError):
                        pass  # The worker already left or timed out; nothing was installed there.
        finally:
            if device is not None:
                device.__exit__(None, None, None)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.channel.put(None)
        self.thread.join()
        self.channel.close()


@contextmanager
def shard_tables(mode, channel):
    from wfarsenal import native_replay, search_session
    core = native_replay.wfcore
    report = dict(mode=mode, hits=0, misses=0, keys=0, builtKeys=0, batches=0, prepareSeconds=0.)
    if not native_replay.ENABLED or not hasattr(core, 'bake_pool_capture'):
        report['error'] = 'native status table support unavailable; using normal replay'
        yield report
        return
    core.bake_pool_capture(BATCH)

    def publish(_stage=None):
        if report.get('error'):
            return
        keys = core.bake_pool_pending()
        if not keys:
            return
        start = perf_counter()
        try:
            if mode == 'rust':
                data = core.bake_pool_reference(keys, STEPS)
            else:
                reader, writer = Pipe(duplex=False)
                with reader:
                    with writer:
                        channel.put((writer, keys))
                    if not reader.poll(20.):
                        raise TimeoutError('GPU table coordinator did not answer')
                    data, error = reader.recv()
                    if error:
                        raise RuntimeError(error)
            core.bake_pool_install(keys, STEPS, data)
            report['batches'] += 1
            report['builtKeys'] += len(keys)
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            core.bake_pool_capture(0)  # Keep only previously verified tables.
        finally:
            report['prepareSeconds'] += perf_counter()-start

    token = search_session.BAKE_PROGRESS.set(publish)
    try:
        yield report
    finally:
        search_session.BAKE_PROGRESS.reset(token)
        report.update(core.bake_pool_stats())
        core.bake_pool_stop()
