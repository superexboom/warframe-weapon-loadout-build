"""Offline bounded direct-stream backend with exact CPU parity and cost gates.

This is not a general status/event simulator. The native stream compiler rejects
all unrepresented state. Callers must retain the original CPU replay fallback.
"""
from __future__ import annotations
import ctypes as c
import math
from pathlib import Path
import statistics
import time
from .cuda_driver import Cuda


class DirectBatch:
    def __init__(self, nvrtc_dir: Path):
        self.cuda = Cuda(nvrtc_dir)
        self.ptx = self.cuda.compile(Path(__file__).with_name('direct.cu'))
        self.buffer = None
        self.capacity = 0
        self.failures = 0
        self.policy = {}
        self.last_decision = {}

    @staticmethod
    def validate(rows):
        if not rows or len(rows)>65536:raise ValueError('batch requires 1..65536 fights')
        events = sum(len(row[0]) for row in rows)
        if events>10000000:raise ValueError('batch event bound exceeded')
        for damage,health,window in rows:
            if not math.isfinite(health) or health<=0 or not math.isfinite(window) or window<=0:
                raise ValueError('positive finite health/window required')
            if len(damage)>100000 or any(not math.isfinite(x) or x<0 for x in damage):
                raise ValueError('invalid immutable direct event stream')

    @staticmethod
    def cpu(rows):
        result=[]
        for values,health,window in rows:
            pool=health;total=0.;kills=0
            for value in values:
                applied=min(pool,max(0.,value));pool-=applied;total+=applied
                if pool<=1e-7:kills+=1;pool=health
            score=float(kills)+(1.-pool/health)
            result.append((score*60./window,total/window,total))
        return result

    def gpu(self, rows):
        self.validate(rows)
        started=time.perf_counter();n=len(rows);flat=[];offsets=[];lengths=[]
        for events,_,_ in rows:
            offsets.append(len(flat));lengths.append(len(events));flat.extend(events)
        arrays=[(c.c_double*max(1,len(flat)))(*flat),(c.c_int*n)(*offsets),(c.c_int*n)(*lengths),
                (c.c_double*n)(*[r[1] for r in rows]),(c.c_double*n)(*[r[2] for r in rows])]
        output=(c.c_double*(3*n))()
        sizes=[c.sizeof(a) for a in arrays]+[c.sizeof(output)]
        if self.buffer is None or any(a>b for a,b in zip(sizes,self.capacity)):
            # One bounded allocation set per coordinator; replace only after
            # prior work is synchronized, never grow without freeing.
            for ptr in self.cuda.allocations:self.cuda.check(self.cuda.driver.cuMemFree_v2(ptr))
            self.cuda.allocations.clear()
            self.buffer=[self.cuda.allocate(size) for size in sizes];self.capacity=sizes
        packed=time.perf_counter()
        for ptr,array in zip(self.buffer,arrays):self.cuda.upload(ptr,array)
        uploaded=time.perf_counter()
        self.cuda.launch('direct_batch',n,[*self.buffer,c.c_int(n)])
        self.cuda.synchronize();ran=time.perf_counter()
        self.cuda.download(output,self.buffer[-1]);finished=time.perf_counter()
        result=[tuple(output[i*3:i*3+3]) for i in range(n)]
        return result,dict(prepare=packed-started,upload=uploaded-packed,kernel=ran-uploaded,
                           download=finished-ran,total=finished-started)

    def probe(self,rows,repeats=5,cpu_reference=None):
        self.validate(rows)
        references=[];device=[];costs=[]
        cpu_reference=cpu_reference or self.cpu
        for _ in range(repeats):
            started=time.perf_counter();expected=cpu_reference(rows);references.append(time.perf_counter()-started)
            actual,cost=self.gpu(rows);device.append(cost['total']);costs.append(cost)
            if actual!=expected:
                self.failures+=1
                return dict(admitted=False,reason='CPU/GPU mismatch',exact=False)
        host=statistics.median(references);gpu=statistics.median(device)
        return dict(admitted=gpu*1.15<host,reason='verified-cost-gate',exact=True,
                    cpuSeconds=host,gpuSeconds=gpu,gain=host/gpu,candidates=len(rows),costs=costs)

    def score(self, rows, *, cpu_reference=None):
        """One offline coordinator: learn per-size cost, retain CPU fallback.

        The immutable stream compiler must already have admitted the inputs.
        The first probe validates every score; later batches sample first,
        middle and last fights and invalidate the admission on any difference.
        Packing, transfer and sampled validation all count against the gain.
        """
        self.validate(rows)
        cpu_reference = cpu_reference or self.cpu
        signature = (len(rows).bit_length(), max(len(r[0]) for r in rows).bit_length())
        policy = self.policy.get(signature)
        if policy is None:
            policy = self.probe(rows, cpu_reference=cpu_reference)
            self.policy[signature] = policy
        if not policy.get('admitted'):
            self.last_decision = dict(backend='cpu', **policy)
            return cpu_reference(rows)
        try:
            actual,cost=self.gpu(rows)
            started=time.perf_counter()
            indices=sorted({0,len(rows)//2,len(rows)-1})
            expected=cpu_reference([rows[i] for i in indices])
            check=time.perf_counter()-started
            if [actual[i] for i in indices]!=expected:
                raise ArithmeticError('sampled CPU/GPU parity failed')
        except Exception as exc:
            self.policy[signature]=dict(admitted=False,reason='device-or-parity-failure',error=type(exc).__name__)
            self.last_decision=dict(backend='cpu',**self.policy[signature]);return cpu_reference(rows)
        complete=cost['total']+check
        accepted=complete*1.15<policy['cpuSeconds']
        self.last_decision=dict(backend='gpu' if accepted else 'cpu',sampledExact=True,
                               cpuSeconds=policy['cpuSeconds'],totalSeconds=complete,
                               admitted=accepted,reason='complete-validated-cost')
        if not accepted:
            self.policy[signature]=dict(admitted=False,reason='validation-cost-exceeds-gain')
            return cpu_reference(rows)
        return actual

    def close(self):self.cuda.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
