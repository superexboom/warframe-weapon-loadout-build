# Portable 离线 GPU 烘焙

正式烘焙器现可通过 `--status-tables cuda` 让显卡生成状态概率表，Rust 在正常战斗中使用这些表。**默认 `off`，继续用原 Rust 算法。** RTX 5080 上两把武器的完整对照未显示端到端提速。在线分析和 Bot 不启用这个后端。

## 可以交给 GPU 的部分

病毒、腐蚀和磁力在此引擎中用 0–10 层的概率分布表示。从空队列出发，若连续命中的「无触发概率、期望触发数」位模式完全相同，前 24 次命中后的 11 个概率均可提前计算。离线 worker 只采集实际重复的键，每批至多 128 组；父进程的一个线程持有 CUDA 设备，批量制表、与 Rust 参考字节比较，再发回 worker。每个分片最多保留最近安装的 512 组。状态到期、换目标、混合概率和超出表深度时仍按原算法更新，其他武器机制、候选排序和缓存写入仍由 CPU 负责。无 CUDA、编译失败或发生数值差异时继续常规回放；不会安装未验证的表。

`--status-tables rust` 在各 worker 内用 Rust 生成相同的表，便于区分查表收益与设备收益。`--report` 的 `statusTableMode` 为请求模式，`gpuEnabled` 仅在分片真的使用过 GPU 表时为真。`targetWork[].statusTables.hits` 是替代的状态计算次数，`builtKeys` 是累计制表数，`keys` 是当时驻留数；它们都不是击杀数或被 GPU 完整解算的配装数。

## 复现正式分片

```powershell
python tools/build_native.py
$weapon = '/Lotus/Weapons/Grineer/LongGuns/GrineerM16Homage/GrineerM16Rifle'
$companion = '/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/CryoxionWeapon'
$nvrtc = Join-Path $env:CUDA_PATH 'bin'  # 或直接给出 NVRTC 与 builtins 所在目录
foreach ($mode in 'off','cuda','rust') {
    $out = ".local/gpu-compare/$mode"
    python tools/bake-analysis-statics.py --profile fast --workers 2 --weapon $weapon --weapon $companion --shards-only --shard-dir $out --report "$out/report.json" --status-tables $mode --nvrtc-dir $nvrtc
}
python tools/gpu_bake/benchmark.py --pool-prefixes --nvrtc-dir $nvrtc --output .local/gpu-compare/pool100
```

首次对照为三种模式各选一个**新分片目录**；已有当前分片会跳过，不能用续跑时间估算提速。`--shards-only` 不会发布或覆盖主缓存。CPU 烘焙最多 10 个解算进程，CUDA 模式最多 9 个，另留 1 个设备协调线程。

## 2026-11-18 实测与后续方向

RTX 5080，NVRTC 12.9，固定种子 20261118。100 把不同主副武器分别装兼容的病毒、腐蚀或磁力 MOD，30 秒身体命中，目标生命 30,000、护盾 4,000、护甲 200。这组有意选择非零触发的可配武器，用于检验机制，不代表全武器覆盖率。实际取得 65 组重复概率、命中 6,813 次。Rust 与 CUDA 制表逐字节相同，两种模式分别在 100/100 场与原回放的 KPM、窗口 DPS、总伤害逐位一致。这里的 100 场不含搜索。

完整的冷分片对照使用上述两把武器、默认开火模式、fast、两种正面词条结构、2 个进程。各模式各跑一次，均产出两份逐字节相同的分片；输入指纹 `5ed976bf545120d9`。[机器可读记录](benchmark-20261118.json)包含原始计数、计时和分片 SHA-256。

| 模式 | 两把武器总用时 | 相对原 CPU |
| --- | ---: | ---: |
| 原 CPU，不制表 | 121.647 秒 | 基线 |
| Rust 制表 | 115.918 秒 | 少 4.7% |
| CUDA 制表，Rust 校验 | 125.352 秒 | 多 3.0% |

CUDA 共 167 批，生成并校验 12,026 组概率表，卡拉克命中 5,152,726 次，急冻喷枪命中 147,186 次。所有批次的打包、传输、计算及取回合计约 51 毫秒，同批 Rust 参考制表约 16 毫秒。**这组数据不足以建议默认开启 CUDA 或 Rust 制表，也不能换算成四小时全量能省多少。**

扩大投入应先测同一搜索层内的整批候选：一次提交多组配装及各自的目标硬度，在设备上完成有界状态的整段战斗，而不只是其中一次概率运算。先按原顺序验证评分、排序、最终分片，再在同一总线程预算下做端到端对照。下文的旧直击实验单独保留。

## Historical direct-stream prototype

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

This direct-stream experiment is still benchmark-only. It does not score full
optimizer candidates on the device. The status-prefix option above is a separate
implementation; the complete combat replay remains authoritative on the CPU.

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
