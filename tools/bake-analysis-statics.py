"""全量烘焙紫卡分析静态缓存（基准配装 / 推荐词条与分层 / 负面词条 / 流派基础配装）。

用法：
    python tools/bake-analysis-statics.py [--profile fast,standard] [--workers N]
        [--weapon PATH ...] [--limit N]

对 catalog 中全部可分析武器 × 开火模式 × 档位烘焙一次武器级静态结果，
statics cache 落盘到 .local/cache/riven-analysis-statics.json。
按武器校验分片：共享规则变化时重烘；仅武器数据变化时保留未受影响的分片。

一个任务 = 一把武器的一个开火模式：同一个工作进程依次烘焙所选的每个档位，
每档同时烘焙 3 条和 2 条正面词条两套推荐（基准配装与流派基础第二次直接命中），
进程内的面板 / 重放缓存在档位之间保持热状态。分析以「只算静态」模式运行：
假想紫卡自己的配装、下限修正与词条贡献不属于静态结果，跳过。

多进程分片：每个档位一个分片目录，工作进程只写自己的分片，全部完成后父进程合并为主缓存。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.run_riven_acceptance_bake import limited_workers
from tools import incremental_bake as incremental

# Select the actual Bot runtime before any app import, also in spawned workers.
# The bundle worker is part of its cache identity; Portable caches are distinct.
_bootstrap = argparse.ArgumentParser(add_help=False)
_bootstrap.add_argument('--bot-bundle', type=Path)
_bootstrap_args, _ = _bootstrap.parse_known_args()
BOT_BUNDLE = _bootstrap_args.bot_bundle or (Path(os.environ['WF_BAKE_BOT_BUNDLE'])
                                           if os.environ.get('WF_BAKE_BOT_BUNDLE') else None)
if BOT_BUNDLE:
    BOT_BUNDLE = BOT_BUNDLE.resolve()
    os.environ['WF_BAKE_BOT_BUNDLE'] = str(BOT_BUNDLE)
    os.environ['WF_RIVEN_ROOT'] = str(BOT_BUNDLE)
    os.environ['WF_ANALYSIS_STATICS_CACHE_PATH'] = str(BOT_BUNDLE / 'data/riven-analysis-statics.json')
    sys.path.insert(0, str(BOT_BUNDLE / 'src'))
    import bot_riven
    if Path(bot_riven.app.__file__).resolve() != BOT_BUNDLE / 'src/app.py':
        raise RuntimeError('Bot bake imported app outside the selected bundle')

SHARD_ROOT = ROOT / ".local" / "cache"
SHARD_SCHEMA_VERSION = incremental.SHARD_SCHEMA
_TABLE_MODE, _TABLE_CHANNEL = 'off', None


def _init_worker(table_mode, table_channel):
    global _TABLE_MODE, _TABLE_CHANNEL
    _TABLE_MODE, _TABLE_CHANNEL = table_mode, table_channel
    os.environ.update(WF_ANALYZER_SERIAL='1', WF_CONCURRENT_SEARCHES='1', WF_ENGINE_WORKERS='1')


def _catalog_weapons() -> list[dict]:
    import app  # noqa: PLC0415

    return [
        weapon
        for weapon in app.CATALOG["weapons"]
        if weapon.get("available") and weapon.get("analysisAvailable")
    ]


def _trigger_stats(app: Any, weapon_type: str, disposition: float, positives: int) -> list[dict]:
    """A legal trigger card with ``positives`` positive stats (D / S / 0 first)."""
    bases = app.RIVEN_BASE_VALUES.get(weapon_type, {})
    candidates, _ = app.optimizer._candidate_lines(
        weapon_type,
        disposition,
        (),
        negative=False,
        bases=bases,
        structure_scale=app.optimizer.theoretical_structure_scale(positives, False),
        available_fusion_codes=frozenset(),
    )
    selected = []
    for preferred in ("D", "S", "0"):
        line = next((row for row in candidates if row.code == preferred), None)
        if line is not None:
            selected.append(line)
    selected.extend(row for row in candidates if row.code not in {line.code for line in selected})
    return [{"code": line.code, "value": line.value, "negative": False} for line in selected[:positives]]


def _shard_worker(args: tuple[str, int, list[tuple[str, str]], tuple[int, ...]], dependency=None) -> list[dict]:
    """独立进程：一把武器一个开火模式，按档位各写一个分片 JSON。

    F14（审计修复）：worker 进程入口即关闭共享主缓存持久化
    （``_disable_analysis_statics_persistence()``）。此前 worker 只清空了
    自己进程内的 ``ANALYSIS_STATICS_CACHE``，但 ``app.analyze_payload()``
    内部仍会无条件调用 ``_persist_analysis_statics_cache()``——只要优化器
    标脏，worker 仍会把条目间接写进共享主缓存文件。现在持久化开关在
    worker 生命周期内整体关闭：worker 阶段对主缓存零写入，只有父进程在
    合并阶段执行一次写入（见 main()）。
    """
    weapon_path, fire_mode, profiles, positive_counts = args
    # Outer bake workers already own parallelism. Without this guard each one
    # starts an additional search pool of its own.
    os.environ['WF_ANALYZER_SERIAL'] = '1'
    import app  # noqa: PLC0415

    persistence_guard = app._disable_analysis_statics_persistence()
    # A bake worker owns its isolated shard. Refreshing the shared live cache
    # midway can import another task/test's entries and overwrite this task.
    app._refresh_analysis_statics_cache_if_newer = lambda: None
    worker_inputs = app._analysis_inputs_fingerprint()
    # Catalog rows use ``companion`` for sentinel/pet weapons, while the
    # optimizer deliberately maps that family to the ordinary riven pool by
    # slot/ancestry.  Feeding the catalog label directly produced empty
    # nominal stats and a misleading "2 to 4 stat objects" failure.
    raw_weapon = app.optimizer.resolve_record(
        app.EXPORTS["weapons"], weapon_path, kind="weapon"
    )
    weapon_type = app.optimizer._riven_type(None, raw_weapon)
    disposition = float(raw_weapon.get("omegaAttenuation") or 1.0)
    outcomes = []
    for profile, shard_path in profiles:
        app.ANALYSIS_STATICS_CACHE.clear()
        started, cpu_started = time.perf_counter(), time.process_time()
        work = {}
        try:
            # Three positives first (the trigger structure the bake always
            # used), then two: the second request finds the baseline,
            # hardness nodes and archetype bases in the statics and only adds
            # the two-positive recommendation and negatives.
            table_work = {}
            if _TABLE_MODE != 'off':
                from tools.gpu_bake.pool_tables import shard_tables
                table_scope = shard_tables(_TABLE_MODE, _TABLE_CHANNEL)
            else:
                table_scope = nullcontext(table_work)
            with table_scope as table_work:
                for positives in positive_counts:
                    payload = {
                        "weapon": weapon_path, "disposition": disposition, "profile": profile,
                        "fireMode": fire_mode, "_bakeStaticsOnly": True,
                        "stats": _trigger_stats(app, weapon_type, disposition, positives),
                    }
                    if BOT_BUNDLE:
                        import bot_riven
                        # Primary Kitguns use pistol Rivens; these are engine triggers, not OCR cards.
                        trigger_stats = payload['stats']
                        payload, _ = bot_riven._payload({**payload, 'stats': []}, profile)
                        payload.update(stats=trigger_stats, _bakeStaticsOnly=True)
                    response = app.analyze_payload(payload)
                    work[str(positives)] = response.get('searchWork') or {}
        except Exception as exc:  # noqa: BLE001
            outcomes.append({"weapon": weapon_path, "profile": profile, "ok": False, "error": str(exc)[:200]})
            continue
        entries = {}
        for key, value in app.ANALYSIS_STATICS_CACHE.items():
            if not isinstance(value, dict):
                continue
            try:
                context = json.loads(key)
            except (ValueError, TypeError):
                continue
            if (context.get('weapon') == weapon_path and context.get('fireMode') == fire_mode
                    and context.get('profile') == profile):
                entries[key] = value
        if not entries or not all(len(value.get('counts', {}).get(str(n), {}).get('recommended', [])) == n
                                  for value in entries.values() for n in positive_counts):
            outcomes.append({'weapon': weapon_path, 'profile': profile, 'ok': False,
                             'error': 'missing complete positive structures for the requested context'})
            continue
        # Workers must never write the shared main cache.  They only emit their
        # own shard; the parent process performs the single atomic merge after all
        # workers finish.  Concurrent replacement of the main JSON here could
        # discard another worker's entries or leave a truncated file on failure.
        # The persistence guard above makes this structural: even the indirect
        # write path through analyze_payload() is a no-op in this process.
        assert not persistence_guard.enabled
        if app._analysis_inputs_fingerprint() != worker_inputs:
            outcomes.append({'weapon': weapon_path, 'profile': profile, 'ok': False,
                             'error': 'inputs changed during analysis; shard rejected'})
            continue
        try:
            payload = dict(schemaVersion=SHARD_SCHEMA_VERSION, cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                           inputs=worker_inputs, profile=profile, entries=entries)
            if dependency is not None:
                payload['dependencies'] = incremental.shard_proof(*dependency, entries)
            incremental.atomic(Path(shard_path), payload)
        except OSError as exc:
            outcomes.append({"weapon": weapon_path, "profile": profile, "ok": False, "error": f"shard write: {exc}"})
            continue
        outcomes.append({"weapon": weapon_path, "fireMode": fire_mode, "profile": profile,
                         "ok": True, "entries": len(entries), "searchWork": work,
                         **({'statusTables': table_work} if table_work else {}),
                         "elapsedSeconds": time.perf_counter() - started,
                         "cpuSeconds": time.process_time() - cpu_started})
    return outcomes


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


def _supported_bake_modes(raw_weapon: dict) -> list[int]:
    # Match the analyzer's actual selectable attacks. Inherited gun-butt modes
    # cannot become successful ranged cache tasks merely because damage exists.
    return [index for index, mode in enumerate(raw_weapon.get('fireModes') or ())
            if isinstance(mode, dict) and isinstance(mode.get('damage'), dict)
            and sum(float(v or 0.) for v in (mode['damage'].get('types') or {}).values()) > 0.
            and not (mode.get('behaviorKind') == 'auxiliary-melee'
                     and raw_weapon.get('slot') in ('primary','secondary','arch_gun'))]


def _profiles(value: str) -> list[str]:
    profiles = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if not profiles or any(p not in ("fast", "standard", "deep") for p in profiles):
        raise argparse.ArgumentTypeError("profiles: comma-separated fast / standard / deep")
    return profiles


def _task_cost(raw_weapon: dict) -> tuple:
    """Longest tasks first, so the pool does not end on one long weapon:
    melee routes, Incarnon forms and multi-component projectile/AoE weapons
    replay the most."""
    modes = [m for m in (raw_weapon.get("fireModes") or ()) if isinstance(m, dict)]
    has_proj_events = any(bool(m.get("projectileEvents")) for m in modes)
    has_radial = any(bool((m.get("damage") or {}).get("radial") or (m.get("damage") or {}).get("components")) for m in modes)
    return (
        raw_weapon.get("slot") != "melee",
        not raw_weapon.get("isIncarnon"),
        not has_proj_events,
        not has_radial,
        -len(modes),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=_profiles, default=["standard"],
                        help="档位，逗号分隔（fast,standard）：一个任务池烘焙全部档位")
    parser.add_argument("--workers", type=limited_workers, default=None,
                        help="并行解算进程数，最多 10；CUDA 模式最多 9 个，另留 1 个 GPU 协调线程")
    parser.add_argument("--weapon", action="append", default=None, help="只烘焙指定武器（可多次）")
    parser.add_argument("--limit", type=int, default=None, help="只烘焙前 N 把（冒烟用）")
    parser.add_argument("--fire-modes", action="store_true", help="烘焙全部开火模式（默认与普通分析同口径：灵化取末模式，其余取主模式）")
    parser.add_argument('--report', type=Path,
                        help='覆盖与失败报告，运行时逐项更新；多个档位时路径里写 {profile}（如 out/{profile}.json）')
    parser.add_argument('--dry-run', action='store_true', help='仅列出任务和当前分片覆盖')
    parser.add_argument('--force-recompute', action='store_true', help='忽略现有分片，冷烘所选任务（用于对照）')
    parser.add_argument('--shards-only', action='store_true', help='只生成并校验分片；不发布主缓存')
    parser.add_argument('--status-tables', choices=('off', 'rust', 'cuda'), default='off',
                        help='离线预计算重复状态概率；默认关闭。cuda 使用一个共享设备，并逐字节核对 Rust 结果')
    parser.add_argument('--nvrtc-dir', type=Path, help='含 NVRTC 和 builtins 的目录；也可设置 CUDA_PATH')
    parser.add_argument('--allow-full-bake', action='store_true', help='Use only after explicit user authorization for a full-roster bake')
    parser.add_argument('--positives', default='3,2',
                        help='烘焙的正面词条数（逗号分隔，默认 3,2：两套推荐都进缓存；只写 3 与旧流程相同）')
    parser.add_argument('--shard-dir', type=Path,
                        help='分片根目录，档位子目录为 riven-statics-shards-<档位>（默认 .local/cache）；配合 --shards-only 做对照烘焙')
    parser.add_argument('--bot-bundle', type=Path,
                        help='Bake the actual Bot runtime with its fixed preset (fast only)')
    args = parser.parse_args()
    if BOT_BUNDLE and args.status_tables != 'off':
        parser.error('--status-tables is supported only by the Portable bake worker')
    if BOT_BUNDLE and getattr(bot_riven, 'BAKE_PROFILE', 'fast') != 'fast':
        parser.error('This Bot requires its owned deep bake, Incarnon routes and damage references; '
                     'use tools/wfarsenal/rebuild_cache.ps1 instead of the legacy fast adapter')
    if BOT_BUNDLE and (args.profile != ['fast'] or args.fire_modes):
        parser.error('Bot baking requires --profile fast and default fire modes')
    if not args.dry_run and not args.allow_full_bake and not (args.weapon or args.limit):
        parser.error('full-roster baking requires explicit user authorization and --allow-full-bake')
    profiles = args.profile
    try:
        positive_counts = tuple(dict.fromkeys(int(part) for part in args.positives.split(",") if part.strip()))
    except ValueError:
        parser.error("--positives: comma-separated 2 / 3")
    if not positive_counts or positive_counts[0] != 3 or any(n not in (2, 3) for n in positive_counts):
        # The three-positive bake comes first: it writes the baseline and the
        # archetype bases the two-positive one then reads.
        parser.error("--positives must start with 3 and contain only 2 and 3")
    if args.report and len(profiles) > 1 and "{profile}" not in str(args.report):
        parser.error("several profiles need {profile} in --report")

    started = time.perf_counter()
    import app
    from wfarsenal import parallel

    workers = min(args.workers or limited_workers(parallel.default_workers()),
                  9 if args.status_tables == 'cuda' else 10)
    cache_version = app.ANALYSIS_STATICS_CACHE_VERSION
    try:
        dependencies = None if BOT_BUNDLE else incremental.bake_inventory(app)
        input_fingerprint = dependencies[0] if dependencies else app._analysis_inputs_fingerprint()
        if dependencies and input_fingerprint != app.ANALYSIS_STATICS_RUNTIME_INPUTS:
            raise app.SimulationError('inputs changed after the runtime started')
    except app.SimulationError as exc:
        print(f"cannot bake: {exc}")
        return 2
    shard_root = args.shard_dir or SHARD_ROOT
    shard_dirs = {profile: shard_root / f"riven-statics-shards-{profile}" for profile in profiles}

    def proof_for(weapon):
        return (dependencies[1], dependencies[2][weapon]) if dependencies else None

    def read_qualified(path, profile, weapon, mode):
        try:
            payload = json.loads(path.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if incremental.qualified_shard(payload, profile, weapon, mode, positive_counts, cache_version, proof_for(weapon)):
            return payload
        return None

    weapons = _catalog_weapons()
    full_roster_size = len(weapons)
    if args.weapon:
        weapons = [w for w in weapons if w["path"] in set(args.weapon)]
    if args.limit:
        weapons = weapons[: args.limit]
    if not args.dry_run and not args.allow_full_bake and full_roster_size and len(weapons) == full_roster_size:
        parser.error('selected weapons cover the full roster; explicit authorization and --allow-full-bake are required')
    print(f"baking {len(weapons)} weapons, profiles={','.join(profiles)}, workers={workers}, status-tables={args.status_tables}")

    planned = []
    expected_shards = {profile: {} for profile in profiles}
    failures = {profile: [] for profile in profiles}
    completed = {profile: [] for profile in profiles}
    skipped = {profile: 0 for profile in profiles}
    reused = {profile: 0 for profile in profiles}
    reused_targets = {profile: [] for profile in profiles}
    excluded_modes = 0
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
            raw_weapon = {}
            raw_modes = []
        supported_modes = _supported_bake_modes(raw_weapon)
        excluded_modes += len(raw_modes) - len(supported_modes)
        if args.fire_modes:
            modes = supported_modes
        else:
            modes = [mode for mode in _default_analysis_modes(raw_weapon) if mode in supported_modes]
        skipped_no_damage += max(0, len(weapon.get("fireModes") or ()) - len(raw_modes))
        for mode in modes:
            # 分片名用武器 path 哈希：与列表顺序解耦（--weapon 过滤/续跑稳定）。
            tag = hashlib.sha1(f"{weapon['path']}#{mode}".encode()).hexdigest()[:12]
            pending = []
            for profile in profiles:
                shard = shard_dirs[profile] / f"{tag}.json"
                expected_shards[profile][shard] = (weapon['path'], mode)
                payload = None if args.force_recompute else read_qualified(shard, profile, weapon['path'], mode)
                if payload is not None and payload.get('inputs') == input_fingerprint:
                    skipped[profile] += 1
                elif payload is not None and dependencies:
                    reused[profile] += 1
                    reused_targets[profile].append((weapon['path'], mode))
                    if not args.dry_run:
                        payload['inputs'] = input_fingerprint
                        incremental.atomic(shard, payload)
                else:
                    pending.append((profile, str(shard)))
            if pending:
                planned.append((_task_cost(raw_weapon), (weapon["path"], mode, pending, positive_counts)))
    tasks = [task for _cost, task in sorted(planned, key=lambda item: item[0])]
    pending_shards = sum(len(task[2]) for task in tasks)
    if any(skipped.values()) or any(reused.values()):
        print(f"resuming: {sum(skipped.values())} current, {sum(reused.values())} reusable, {pending_shards} to go")
    if skipped_no_damage:
        print(f"skipping {skipped_no_damage} raw fire modes without damage data")

    coordinator = None

    def report(status_of):
        if not args.report:
            return
        for profile in profiles:
            path = Path(str(args.report).replace("{profile}", profile))
            payload = dict(status=status_of(profile), updatedAt=datetime.now(timezone.utc).isoformat(),
                           profile=profile, fireModes=args.fire_modes, workers=workers,
                           botBundle=str(BOT_BUNDLE) if BOT_BUNDLE else None,
                           gpuEnabled=(args.status_tables == 'cuda' and any(
                               row.get('statusTables', {}).get('hits', 0) for row in completed[profile])),
                           statusTableMode=args.status_tables, positiveCounts=positive_counts,
                           **({'gpuCoordinator': dict(coordinator.summary)} if coordinator is not None else {}),
                           cacheVersion=cache_version, inputs=input_fingerprint,
                           weapons=len(weapons), expectedShards=len(expected_shards[profile]),
                           skippedCurrent=skipped[profile], reusedIncremental=reused[profile],
                           pendingShards=len(expected_shards[profile])-skipped[profile]-reused[profile],
                           **(dict(reusableTargets=reused_targets[profile], pendingTargets=[(w, m) for w, m, jobs, _ in tasks
                                  if any(p == profile for p, _path in jobs)]) if args.dry_run else {}),
                           completed=len(completed[profile]),
                           excludedModes=excluded_modes, failures=failures[profile],
                           targetWork=completed[profile],
                           elapsedSeconds=round(time.perf_counter() - started, 3))
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(path)

    report(lambda _profile: 'planned' if args.dry_run else 'running')
    if args.dry_run:
        for profile in profiles:
            print(f'{profile}: expected {len(expected_shards[profile])}, current {skipped[profile]}, '
                  f'reusable {reused[profile]}, pending {len(expected_shards[profile]) - skipped[profile] - reused[profile]}, excluded {excluded_modes}')
        return 0
    if not any(expected_shards.values()):
        print('nothing to bake (no matching weapons/modes); main cache unchanged')
        return 1
    done = failed = 0
    channel = None
    if tasks and args.status_tables == 'cuda':
        from tools.gpu_bake.pool_tables import PoolBroker
        # Spawn workers share one queue and one device context. The CUDA driver never enters a worker.
        channel = multiprocessing.get_context('spawn').SimpleQueue()
        nvrtc_dir = args.nvrtc_dir or (Path(os.environ['CUDA_PATH']) / 'bin' if os.getenv('CUDA_PATH') else None)
        coordinator = PoolBroker(channel, nvrtc_dir)
    with coordinator or nullcontext(), ProcessPoolExecutor(
        max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
        initializer=_init_worker, initargs=(args.status_tables, channel),
    ) as pool:
        futures = {pool.submit(_shard_worker, task, proof_for(task[0])): task for task in tasks}
        for future in as_completed(futures):
            weapon_path, mode, pending, _counts = futures[future]
            try:
                outcomes = future.result()
            except Exception as exc:
                outcomes = [{'ok': False, 'weapon': weapon_path, 'profile': profile,
                             'error': f'{type(exc).__name__}: {exc}'} for profile, _shard in pending]
            for outcome in outcomes:
                done += 1
                table_error = outcome.get('statusTables', {}).get('error')
                if table_error:
                    print(f"  {outcome['weapon']} [{outcome['profile']}]: CPU fallback: {table_error}")
                if outcome["ok"]:
                    completed[outcome["profile"]].append(outcome)
                else:
                    failed += 1
                    failures[outcome["profile"]].append({**outcome, 'fireMode': mode})
                    print(f"  FAIL {outcome['weapon']} [{outcome['profile']}]: {outcome['error']}")
                if done % 25 == 0:
                    elapsed = time.perf_counter() - started
                    print(f"  {done}/{pending_shards} ({elapsed:.0f}s, {failed} failed)")
            report(lambda _profile: 'running')

    if args.status_tables != 'off':
        table_rows = [row['statusTables'] for group in completed.values() for row in group if 'statusTables' in row]
        print(f"{args.status_tables} status tables: {sum(row['builtKeys'] for row in table_rows)} generated, "
              f"{sum(row['hits'] for row in table_rows)} replay hits")

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
    verified = {profile: 0 for profile in profiles}
    for profile in profiles:
        missing = []
        for shard, owner in sorted(expected_shards[profile].items()):
            payload = read_qualified(shard, profile, *owner)
            if payload is None or payload.get('inputs') != input_fingerprint:
                missing.append(str(shard))
                continue
            verified[profile] += 1
            if not args.shards_only:
                merged.update(payload['entries'])
        if missing:
            failures[profile].append(dict(error='missing-current-shards', shards=sorted(missing)))
            failed = max(failed, len(missing))
    failed_profiles = {profile for profile in profiles if failures[profile]}
    changed = incremental.bake_inventory(app) != dependencies if dependencies else app._analysis_inputs_fingerprint() != input_fingerprint
    if changed:
        for profile in profiles:
            failures[profile].append(dict(error='inputs-changed-during-bake'))
        report(lambda _profile: 'failed-inputs-changed')
        print('inputs changed during bake; refusing to publish cache')
        return 1
    if args.shards_only:
        report(lambda profile: 'partial' if profile in failed_profiles else 'shards-complete')
        for profile in profiles:
            print(f'{profile}: verified {verified[profile]}/{len(expected_shards[profile])} shards; main cache unchanged')
        print(f"total {time.perf_counter() - started:.0f}s")
        return int(bool(failed))
    if failed:
        report(lambda profile: 'partial' if profile in failed_profiles else 'shards-complete')
        print('incomplete selection; main cache unchanged')
        return 1
    app.ANALYSIS_STATICS_CACHE.clear()
    app.ANALYSIS_STATICS_CACHE.update(merged)
    app.ANALYSIS_STATICS_CACHE["__dirty__"] = True
    app._persist_analysis_statics_cache()
    print(f"merged {len(merged)} entries into main cache")
    print(f"total {time.perf_counter() - started:.0f}s, {failed} failed of {pending_shards}")
    report(lambda profile: 'partial' if profile in failed_profiles else 'complete')
    # F14 边界：有失败时不得报 0——「条目非空、worker 没抛异常」不等于
    # 语义正确。失败数 > 0 时返回 1，让 CI/批处理能感知部分失败。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
