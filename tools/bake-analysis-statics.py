"""全量烘焙紫卡分析静态缓存（理论上限/推荐/基准配装）。

用法：
    python tools/bake-analysis-statics.py [--profile standard] [--workers N]
        [--weapon PATH ...] [--limit N]

对 catalog 中全部可分析武器 × 默认开火模式 × 指定档位跑一次完整分析
（用假想三正紫卡触发 baseline/recommended/optimal 的全 statics 计算），
statics cache 落盘到 .local/cache/riven-analysis-statics.json。
同一游戏版本内只跑一次：缓存指纹（导出+引擎哈希）变化时自动整体失效。

多进程分片：每个 worker 独立进程各自写分片缓存，全部完成后合并为主缓存。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHARD_ROOT = ROOT / ".local" / "cache"
SHARD_SCHEMA_VERSION = 3


def _catalog_weapons() -> list[dict]:
    import app  # noqa: PLC0415

    return [
        weapon
        for weapon in app.CATALOG["weapons"]
        if weapon.get("available") and weapon.get("analysisAvailable")
    ]


def _shard_worker(args: tuple[str, str, str, int]) -> dict:
    """独立进程：算一批武器的 statics，写分片 JSON。

    F14（审计修复）：worker 进程入口即关闭共享主缓存持久化
    （``_disable_analysis_statics_persistence()``）。此前 worker 只清空了
    自己进程内的 ``ANALYSIS_STATICS_CACHE``，但 ``app.analyze_payload()``
    内部仍会无条件调用 ``_persist_analysis_statics_cache()``——只要优化器
    标脏，worker 仍会把条目间接写进共享主缓存文件。现在持久化开关在
    worker 生命周期内整体关闭：worker 阶段对主缓存零写入，只有父进程在
    合并阶段执行一次写入（见 main()）。
    """
    shard_path, profile, weapon_path, fire_mode = args
    import app  # noqa: PLC0415

    persistence_guard = app._disable_analysis_statics_persistence()
    app.ANALYSIS_STATICS_CACHE.clear()
    bases = app.RIVEN_BASE_VALUES.get(_weapon_type_of(weapon_path), {})
    stats = []
    # 通用三正假想卡（数值夹进合法区间由 app 层校验放宽——直接用 nominal）。
    # 假想卡只是触发器：statics（基准/推荐/上限）不随单卡数值变化。
    codes = [code for code in ("D", "S", "0") if code in bases][:3]
    if len(codes) < 3:
        # 近战等无 S/0 的类型退化为任意三码。
        codes = list(bases)[:3]
    raw_weapon = app.optimizer.resolve_record(
        app.EXPORTS["weapons"], weapon_path, kind="weapon"
    )
    disposition = float(raw_weapon.get("omegaAttenuation") or 1.0)
    for code in codes:
        base = bases.get(code, 100.0)
        nominal = abs(base * disposition * 0.757525)
        stats.append({"code": code, "value": nominal, "negative": False})
    request = {
        "weapon": weapon_path,
        "disposition": disposition,
        "profile": profile,
        "fireMode": fire_mode,
        "_bakeStaticsOnly": True,
        "stats": stats,
    }
    try:
        app.analyze_payload(request)
    except Exception as exc:  # noqa: BLE001
        return {"weapon": weapon_path, "ok": False, "error": str(exc)[:200]}
    if not any(
        isinstance(value, dict) for value in app.ANALYSIS_STATICS_CACHE.values()
    ):
        return {
            "weapon": weapon_path,
            "ok": False,
            "error": "no statics entries produced (candidate generation failed)",
        }
    # Workers must never write the shared main cache.  They only emit their
    # own shard; the parent process performs the single atomic merge after all
    # workers finish.  Concurrent replacement of the main JSON here could
    # discard another worker's entries or leave a truncated file on failure.
    # The persistence guard above makes this structural: even the indirect
    # write path through analyze_payload() is a no-op in this process.
    assert not persistence_guard.enabled
    try:
        shard = Path(shard_path)
        shard.parent.mkdir(parents=True, exist_ok=True)
        entries = {
            key: value
            for key, value in app.ANALYSIS_STATICS_CACHE.items()
            if isinstance(value, dict)
        }
        shard.write_text(
            json.dumps(
                {
                    "schemaVersion": SHARD_SCHEMA_VERSION,
                    "cacheVersion": app.ANALYSIS_STATICS_CACHE_VERSION,
                    "inputs": _worker_inputs_fingerprint(app),
                    "profile": profile,
                    "entries": entries,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"weapon": weapon_path, "ok": False, "error": f"shard write: {exc}"}
    return {"weapon": weapon_path, "ok": True, "entries": len(app.ANALYSIS_STATICS_CACHE)}


def _worker_inputs_fingerprint(app: Any) -> str:
    """Shard fingerprint with the same fail-closed semantics as the loader.

    F13: a missing dependency must not silently degrade to an empty
    fingerprint (two different broken environments would then accept each
    other's shards).  Record the failure explicitly in the shard so the
    parent's merge step can reject it.
    """
    try:
        return app._analysis_inputs_fingerprint()
    except app.SimulationError:
        return "__unreadable_inputs__"


def _weapon_type_of(weapon_path: str) -> str:
    import app  # noqa: PLC0415

    weapon = app.CATALOG_WEAPONS_BY_PATH.get(weapon_path)
    return (weapon or {}).get("weaponType", "rifle")


def _default_analysis_modes(raw_weapon: dict) -> list[int]:
    """Mirror analyze_riven_request's default fire-mode policy (F14 boundary).

    The portable analyzer defaults Incarnon weapons with multiple modes to the
    LAST fire mode (the Incarnon form); everything else uses mode 0.  The bake
    script previously baked only mode 0 unconditionally, so baked entries could
    never be hit by a default (non-fireMode-override) request for an Incarnon
    weapon — the classic "candidate cache masquerading as a hit" gap.
    """
    modes = [
        int(mode.get("index", index))
        for index, mode in enumerate(raw_weapon.get("fireModes") or ())
        if isinstance(mode, dict) and isinstance(mode.get("damage"), dict)
    ]
    if not modes:
        return []
    if raw_weapon.get("isIncarnon") and len(modes) > 1:
        return [modes[-1]]
    return [modes[0]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="standard", choices=["fast", "standard", "deep"])
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--weapon", action="append", default=None, help="只烘焙指定武器（可多次）")
    parser.add_argument("--limit", type=int, default=None, help="只烘焙前 N 把（冒烟用）")
    parser.add_argument("--fire-modes", action="store_true", help="烘焙全部开火模式（默认与普通分析同口径：灵化取末模式，其余取主模式）")
    args = parser.parse_args()

    import app

    cache_version = app.ANALYSIS_STATICS_CACHE_VERSION
    try:
        input_fingerprint = app._analysis_inputs_fingerprint()
    except app.SimulationError as exc:
        print(f"cannot bake: {exc}")
        return 2
    shard_dir = SHARD_ROOT / f"riven-statics-shards-{args.profile}"

    def shard_is_current(path: Path) -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("schemaVersion") == SHARD_SCHEMA_VERSION
            and payload.get("cacheVersion") == cache_version
            and payload.get("inputs") == input_fingerprint
            and payload.get("profile") == args.profile
            and isinstance(payload.get("entries"), dict)
            and bool(payload.get("entries"))
        )

    weapons = _catalog_weapons()
    if args.weapon:
        weapons = [w for w in weapons if w["path"] in set(args.weapon)]
    if args.limit:
        weapons = weapons[: args.limit]
    print(f"baking {len(weapons)} weapons, profile={args.profile}, workers={args.workers}")

    shard_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    skipped = 0
    skipped_no_damage = 0
    for weapon in weapons:
        try:
            raw_weapon = app.optimizer.resolve_record(
                app.EXPORTS["weapons"], weapon["path"], kind="weapon"
            )
            raw_modes = [
                mode
                for mode in raw_weapon.get("fireModes") or ()
                if isinstance(mode, dict)
                and isinstance(mode.get("damage"), dict)
            ]
        except Exception:
            raw_modes = []
        if args.fire_modes:
            modes = [int(mode.get("index", index)) for index, mode in enumerate(raw_modes)]
        else:
            modes = _default_analysis_modes(raw_weapon)
            if not modes and raw_modes:
                # 有开火模式但都缺 damage 数据：显式跳过并计数（不静默 0 模式）。
                modes = []
        skipped_no_damage += max(0, len(weapon.get("fireModes") or ()) - len(raw_modes))
        for mode in modes:
            # 分片名用武器 path 哈希：与列表顺序解耦（--weapon 过滤/续跑稳定）。
            tag = hashlib.sha1(f"{weapon['path']}#{mode}".encode()).hexdigest()[:12]
            shard = shard_dir / f"{tag}.json"
            # 幂等续跑：分片已存在且非空则跳过（烘焙被中断后可续）。
            if shard.is_file() and shard_is_current(shard):
                skipped += 1
                continue
            tasks.append((str(shard), args.profile, weapon["path"], mode))
    if skipped:
        print(f"resuming: {skipped} shards already baked, {len(tasks)} to go")
    if skipped_no_damage:
        print(f"skipping {skipped_no_damage} raw fire modes without damage data")

    started = time.time()
    done = failed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_shard_worker, task): task for task in tasks}
        for future in as_completed(futures):
            outcome = future.result()
            done += 1
            if outcome["ok"]:
                failed = failed
            else:
                failed += 1
                print(f"  FAIL {outcome['weapon']}: {outcome['error']}")
            if done % 25 == 0:
                elapsed = time.time() - started
                print(f"  {done}/{len(tasks)} ({elapsed:.0f}s, {failed} failed)")

    # 合并分片到主缓存
    # Preserve other profiles already baked into the main cache.
    # F14：只有父进程执行这一次合并写入；worker 进程的持久化开关在各自
    # 入口已关闭（见 _shard_worker）。带 "__unreadable_inputs__" 指纹的分片
    # （依赖缺失时 worker 记录的失败标记）在合并阶段被拒绝，不会进入主缓存。
    merged: dict = {
        key: value
        for key, value in app.ANALYSIS_STATICS_CACHE.items()
        if isinstance(value, dict)
    }
    rejected_shards = 0
    for shard in sorted(shard_dir.glob("*.json")):
        try:
            payload = json.loads(shard.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rejected_shards += 1
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("schemaVersion") != SHARD_SCHEMA_VERSION
            or payload.get("cacheVersion") != cache_version
            or payload.get("inputs") != input_fingerprint
            or payload.get("inputs") == "__unreadable_inputs__"
            or payload.get("profile") != args.profile
        ):
            rejected_shards += 1
            continue
        for key, value in (payload.get("entries") or {}).items():
            if isinstance(value, dict):
                merged[key] = value
    app.ANALYSIS_STATICS_CACHE.clear()
    app.ANALYSIS_STATICS_CACHE.update(merged)
    app.ANALYSIS_STATICS_CACHE["__dirty__"] = True
    app._persist_analysis_statics_cache()
    print(f"merged {len(merged)} entries into main cache")
    if rejected_shards:
        print(f"rejected {rejected_shards} stale/unreadable shards")
    print(f"total {time.time()-started:.0f}s, {failed} failed of {len(tasks)}")
    # F14 边界：有失败时不得报 0——「条目非空、worker 没抛异常」不等于
    # 语义正确。失败数 > 0 时返回 1，让 CI/批处理能感知部分失败。
    if failed:
        return 1
    if not tasks and not skipped:
        print("nothing to bake (no weapons/modes selected)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
