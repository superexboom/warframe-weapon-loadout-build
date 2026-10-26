"""Cost model and admission contract for future batch bake execution.

This does not enable a GPU backend. Its estimates expose their assumptions;
confirmed correctness and actual full candidate timings are mandatory to admit.
"""
from __future__ import annotations
import math


def estimate(minutes, eligible_job_share, replay_share, speedup, overhead_share=0.):
    values=(minutes,eligible_job_share,replay_share,speedup,overhead_share)
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values):
        raise ValueError('finite numeric assumptions required')
    if minutes<=0 or speedup<=0 or not all(0<=v<=1 for v in (eligible_job_share,replay_share,overhead_share)):
        raise ValueError('positive time/speedup and shares in [0,1] required')
    offload=eligible_job_share*replay_share
    serial=(1-offload)+offload/speedup+overhead_share
    # An ideal overlapping queue can leave some eligible work on the CPU.
    fraction=min(offload,speedup/(1+speedup))
    overlap=max(1-fraction,fraction/speedup)+overhead_share
    return dict(offloadShare=offload,serializedMinutes=minutes*serial,
                serializedSavedMinutes=minutes*(1-serial),
                idealOverlapMinutes=minutes*overlap,assumptions=dict(eligibleJobShare=eligible_job_share,
                    replayShare=replay_share,gpuSpeedupVsFullCpuPool=speedup,overheadShare=overhead_share))


def admission(*,scope,full_candidate_kernel,exact,resources_ok,candidates,cpu_seconds,gpu_seconds,
              prepare_seconds=0.,transfer_seconds=0.,check_seconds=0.,queue_seconds=0.,min_gain=1.15):
    """Planning gate: complete candidate parity + end-to-end throughput.

    A fast microkernel, or GPU faster than only one of many CPU workers,
    cannot authorize publishing a GPU cache shard.
    """
    if scope!='bake':return dict(backend='cpu',reason='outside-batch-bake-scope')
    if not full_candidate_kernel:return dict(backend='cpu',reason='full-candidate-kernel-not-implemented')
    if not exact:return dict(backend='cpu',reason='candidate-parity-unverified')
    if not resources_ok:return dict(backend='cpu',reason='state-or-memory-bound-exceeded')
    times=(cpu_seconds,gpu_seconds,prepare_seconds,transfer_seconds,check_seconds,queue_seconds)
    if (not isinstance(candidates,int) or isinstance(candidates,bool) or candidates<=0
            or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 for x in times)
            or not isinstance(min_gain,(int,float)) or not math.isfinite(min_gain) or min_gain<1):
        return dict(backend='cpu',reason='invalid-cost-probe')
    cost=sum(times[1:]);gain=cpu_seconds/cost if cost else 0.
    if cost<=0 or gain<min_gain:return dict(backend='cpu',reason='no-end-to-end-gain',gain=gain)
    return dict(backend='gpu',reason='verified-batch-gain',gain=gain,candidates=candidates)
