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
    """独立进程：算一批武器的 statics，写分片 JSON。"""
    shard_path, profile, weapon_path, fire_mode = args
    import app  # noqa: PLC0415

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
    # Workers must never write the shared main cache.  They only emit their
    # own shard; the parent process performs the single atomic merge after all
    # workers finish.  Concurrent replacement of the main JSON here could
    # discard another worker's entries or leave a truncated file on failure.
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
                    "inputs": app._analysis_inputs_fingerprint(),
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


def _weapon_type_of(weapon_path: str) -> str:
    import app  # noqa: PLC0415

    weapon = app.CATALOG_WEAPONS_BY_PATH.get(weapon_path)
    return (weapon or {}).get("weaponType", "rifle")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="standard", choices=["fast", "standard", "deep"])
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    parser.add_argument("--weapon", action="append", default=None, help="只烘焙指定武器（可多次）")
    parser.add_argument("--limit", type=int, default=None, help="只烘焙前 N 把（冒烟用）")
    parser.add_argument("--fire-modes", action="store_true", help="烘焙全部开火模式（默认只主模式）")
    args = parser.parse_args()

    import app

    cache_version = app.ANALYSIS_STATICS_CACHE_VERSION
    input_fingerprint = app._analysis_inputs_fingerprint()
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
            modes = [0] if any(int(mode.get("index", -1)) == 0 for mode in raw_modes) else []
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
    merged: dict = {
        key: value
        for key, value in app.ANALYSIS_STATICS_CACHE.items()
        if isinstance(value, dict)
    }
    for shard in sorted(shard_dir.glob("*.json")):
        try:
            payload = json.loads(shard.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("schemaVersion") != SHARD_SCHEMA_VERSION
            or payload.get("cacheVersion") != cache_version
            or payload.get("inputs") != input_fingerprint
            or payload.get("profile") != args.profile
        ):
            continue
        for key, value in (payload.get("entries") or {}).items():
            if isinstance(value, dict):
                merged[key] = value
    app.ANALYSIS_STATICS_CACHE.clear()
    app.ANALYSIS_STATICS_CACHE.update(merged)
    app.ANALYSIS_STATICS_CACHE["__dirty__"] = True
    app._persist_analysis_statics_cache()
    print(f"merged {len(merged)} entries into main cache")
    print(f"total {time.time()-started:.0f}s, {failed} failed of {len(tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
