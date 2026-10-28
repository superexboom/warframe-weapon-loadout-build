# Offline GPU bake investigation

This branch is an experimental backend, **not a production GPU bake feature**.
The released Portable build and Bot cache use the validated CPU/Rust engine.

The native `direct_bake_stream` compiles a complete fight into an immutable
health-damage event stream only when its semantics are independent of target
replacement. It rejects statuses, shield/overguard, head/body splits, kill-trigger
feedback, radial/delayed/persistent parts, melee and unsupported mechanics. CUDA
executes target replacement, clipped damage and partial-kill scoring. The CPU
replay is authoritative. `DirectBatch` bounds memory, verifies exact scores and
has a measured 15% gain gate with CPU fallback; interactive requests never import it.

## Measured result — RTX 5080, 2026-10-28

- 100 deterministic sampled real ranged weapon default-mode fights, no weapon
  data changed: 1 eligible (Paris), 99 CPU fallback. No errors.
- A separate 100-scenario zero-status fixture set is explicitly synthetic:
  54 eligible, 46 fallback. It is not production coverage.
- All 55 compiled fights exactly match all three CPU metrics (KPM, DPS, damage).
- CUDA outputs match an optimized Rust stream interpreter exactly for every
  tested batch (up to 8192 fights).
- At 100 fights, real-stream duplication: CPU 0.1965 ms / GPU 0.3274 ms (0.600x).
  Synthetic fixtures: CPU 0.7899 ms / GPU 0.9833 ms (0.803x).
- At 8192 fights: 1.082x / 1.060x, below admission; preparation and validation
  further reduce end-to-end gains. No measured configuration was admitted.
- The 100 real CPU fights total 0.0565 seconds; the extra admission/stream
  compilation total 0.0169 seconds. These are battle evaluations, **not 100
  complete optimizer bakes**. They cannot substantiate whole-bake savings.

A general full-state GPU scorer, centralized optimizer candidate batching and
100 complete bake A/B remain unfinished. Do not relabel this experiment as that
feature, and do not publish GPU-generated production caches from this branch.
The earlier plan's exit gate is met: this domain does not justify production
integration. Extending to full probabilistic state requires a different packed
combat core; moving more cheap scalar operations alone will not establish gain.

## Reproduce

```powershell
python tools/build_native.py
python -m pytest -q tests/test_gpu_direct_bake.py tests/test_finalists_batch.py
python tools/gpu_bake/benchmark.py --nvrtc-dir <NVRTC-12.9-bin> --output .local/gpu-100
```

`cuda_driver.py` is from simfleet's offline hardware adapter, AGPL-3.0-or-later.
NVRTC and CUDA driver binaries are not distributed here. Device compilation
uses double precision, no FMA contraction and no flush-to-zero. Full measurements
and selected weapon names are in `benchmark-20261028.json`.
