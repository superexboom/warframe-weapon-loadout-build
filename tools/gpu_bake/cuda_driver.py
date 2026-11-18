# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small Windows CUDA Driver/NVRTC adapter for offline hardware experiments.

No CUDA SDK system installation: pass the directory containing NVRTC DLLs.
All allocations and the CUDA context are explicitly released on exit.
"""
import ctypes as c
import os
import pathlib


class Cuda:
    def __init__(self, nvrtc_dir=None, blocking=True):
        self.context = c.c_void_p()
        self.module = c.c_void_p()
        self.allocations = []
        self.dll_dir = os.add_dll_directory(str(nvrtc_dir.resolve())) if nvrtc_dir else None
        self.driver = c.WinDLL("nvcuda.dll")
        # NVRTC loads its companion by basename, outside Python's DLL loader.
        self.builtins = c.CDLL(str((nvrtc_dir / "nvrtc-builtins64_129.dll").resolve())) if nvrtc_dir else None
        self.nvrtc = c.CDLL(str((nvrtc_dir / "nvrtc64_120_0.dll").resolve())) if nvrtc_dir else None
        self.functions = {}
        for name, args in [
            ("cuInit", [c.c_uint]), ("cuDeviceGet", [c.POINTER(c.c_int), c.c_int]),
            ("cuDeviceGetName", [c.c_void_p, c.c_int, c.c_int]),
            ("cuDeviceGetAttribute", [c.POINTER(c.c_int), c.c_int, c.c_int]),
            ("cuCtxCreate_v2", [c.POINTER(c.c_void_p), c.c_uint, c.c_int]),
            ("cuCtxDestroy_v2", [c.c_void_p]), ("cuCtxSynchronize", []),
            ("cuModuleLoadData", [c.POINTER(c.c_void_p), c.c_void_p]),
            ("cuModuleUnload", [c.c_void_p]),
            ("cuModuleGetFunction", [c.POINTER(c.c_void_p), c.c_void_p, c.c_char_p]),
            ("cuMemAlloc_v2", [c.POINTER(c.c_uint64), c.c_size_t]),
            ("cuMemFree_v2", [c.c_uint64]),
            ("cuMemcpyHtoD_v2", [c.c_uint64, c.c_void_p, c.c_size_t]),
            ("cuMemcpyDtoH_v2", [c.c_void_p, c.c_uint64, c.c_size_t]),
            ("cuLaunchKernel", [c.c_void_p, c.c_uint, c.c_uint, c.c_uint, c.c_uint, c.c_uint, c.c_uint,
                                c.c_uint, c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p]),
            ("cuGetErrorName", [c.c_int, c.POINTER(c.c_char_p)]),
        ]:
            fn = getattr(self.driver, name)
            fn.argtypes, fn.restype = args, c.c_int
        for name, args in [
            ("nvrtcCreateProgram", [c.POINTER(c.c_void_p), c.c_char_p, c.c_char_p, c.c_int, c.c_void_p, c.c_void_p]),
            ("nvrtcCompileProgram", [c.c_void_p, c.c_int, c.POINTER(c.c_char_p)]),
            ("nvrtcGetProgramLogSize", [c.c_void_p, c.POINTER(c.c_size_t)]),
            ("nvrtcGetProgramLog", [c.c_void_p, c.c_void_p]),
            ("nvrtcGetPTXSize", [c.c_void_p, c.POINTER(c.c_size_t)]),
            ("nvrtcGetPTX", [c.c_void_p, c.c_void_p]),
            ("nvrtcDestroyProgram", [c.POINTER(c.c_void_p)]),
        ]:
            if self.nvrtc is None:
                break
            fn = getattr(self.nvrtc, name)
            fn.argtypes, fn.restype = args, c.c_int
        try:
            self.check(self.driver.cuInit(0))
            device = c.c_int()
            self.check(self.driver.cuDeviceGet(c.byref(device), 0))
            name = c.create_string_buffer(256)
            self.check(self.driver.cuDeviceGetName(name, len(name), device))
            self.name = name.value.decode()
            major, minor = c.c_int(), c.c_int()
            self.check(self.driver.cuDeviceGetAttribute(c.byref(major), 75, device))
            self.check(self.driver.cuDeviceGetAttribute(c.byref(minor), 76, device))
            self.arch = f"compute_{major.value}{minor.value}"
            # A long GPU batch must not spin on a CPU core needed by native lanes.
            self.check(self.driver.cuCtxCreate_v2(c.byref(self.context), 4 if blocking else 0, device))
        except BaseException:
            self.close()
            raise

    def check(self, result):
        if result:
            name = c.c_char_p()
            self.driver.cuGetErrorName(result, c.byref(name))
            raise RuntimeError(f"CUDA {result}: {name.value}")

    def compile(self, path, extra_options=(), load=True, architecture=None):
        if self.nvrtc is None:
            raise RuntimeError("NVRTC is required for compilation; precompiled modules need only the driver")
        program = c.c_void_p()
        source = path.read_text()
        if '#include "portable_hypot.cuh"' in source:
            source = source.replace('#include "portable_hypot.cuh"', (path.parent / "portable_hypot.cuh").read_text())
        source = source.encode()
        status = self.nvrtc.nvrtcCreateProgram(c.byref(program), source, path.name.encode(), 0, None, None)
        if status:
            raise RuntimeError(f"nvrtcCreateProgram: {status}")
        try:
            options = [f"--gpu-architecture={architecture or self.arch}", "--std=c++17", "--fmad=false", "--ftz=false", "--prec-div=true", "--prec-sqrt=true", *extra_options]
            opts = (c.c_char_p * len(options))(*(x.encode() for x in options))
            status = self.nvrtc.nvrtcCompileProgram(program, len(options), opts)
            size = c.c_size_t()
            self.nvrtc.nvrtcGetProgramLogSize(program, c.byref(size))
            log = c.create_string_buffer(size.value)
            self.nvrtc.nvrtcGetProgramLog(program, log)
            if status:
                raise RuntimeError(f"NVRTC {status}: {log.value.decode()}")
            self.nvrtc.nvrtcGetPTXSize(program, c.byref(size))
            ptx = c.create_string_buffer(size.value)
            status = self.nvrtc.nvrtcGetPTX(program, ptx)
            if status:
                raise RuntimeError(f"nvrtcGetPTX: {status}")
            if load:
                self.check(self.driver.cuModuleLoadData(c.byref(self.module), ptx))
            self.options = options
            return ptx.value
        finally:
            self.nvrtc.nvrtcDestroyProgram(c.byref(program))

    def allocate(self, size):
        ptr = c.c_uint64()
        self.check(self.driver.cuMemAlloc_v2(c.byref(ptr), size))
        self.allocations.append(ptr)
        return ptr

    def upload(self, ptr, data):
        self.check(self.driver.cuMemcpyHtoD_v2(ptr, data, c.sizeof(data)))

    def download(self, data, ptr):
        self.check(self.driver.cuMemcpyDtoH_v2(data, ptr, c.sizeof(data)))

    def launch(self, name, count, arguments, block_size=128):
        if name not in self.functions:
            fn = c.c_void_p()
            self.check(self.driver.cuModuleGetFunction(c.byref(fn), self.module, name.encode()))
            self.functions[name] = fn
        params = (c.c_void_p * len(arguments))(*(c.cast(c.byref(x), c.c_void_p) for x in arguments))
        self.check(self.driver.cuLaunchKernel(self.functions[name], (count + block_size - 1) // block_size, 1, 1, block_size, 1, 1, 0, None, params, None))

    def synchronize(self):
        self.check(self.driver.cuCtxSynchronize())

    def close(self):
        for ptr in reversed(self.allocations):
            self.driver.cuMemFree_v2(ptr)
        self.allocations.clear()
        if self.module:
            self.driver.cuModuleUnload(self.module)
            self.module = c.c_void_p()
        if self.context:
            self.driver.cuCtxDestroy_v2(self.context)
            self.context = c.c_void_p()
        if self.dll_dir:
            self.dll_dir.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
