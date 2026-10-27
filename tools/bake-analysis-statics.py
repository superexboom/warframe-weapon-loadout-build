"""全量烘焙紫卡分析静态缓存（基准配装 / 推荐词条与分层 / 负面词条 / 流派基础配装）。

用法：
    python tools/bake-analysis-statics.py [--profile fast,standard] [--workers N]
        [--weapon PATH ...] [--limit N]

对 catalog 中全部可分析武器 × 开火模式 × 档位烘焙一次武器级静态结果，
statics cache 落盘到 .local/cache/riven-analysis-statics.json。
同一游戏版本内只跑一次：缓存指纹（导出+引擎哈希）变化时自动整体失效。

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
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.run_riven_acceptance_bake import MAX_BAKE_WORKERS, limited_workers

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
SHARD_SCHEMA_VERSION = 3


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


def _shard_worker(args: tuple[str, int, list[tuple[str, str]], tuple[int, ...]]) -> list[dict]:
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
    worker_inputs = app._analysis_inputs_fingerprint()
    # Catalog rows use ``companion`` for sentinel/pet weapons, while the
    # optimizer deliberately maps that family to the ordinary riven pool by
    # slot/ancestry.  Feeding the catalog label directly produced empty
    # nominal stats and a misleading "2 to 4 stat objects" failure.
    raw_weapon = app.optimizer.resolve_record(
        app.EXPORTS["weapons"], weapon_path, kind="weapon"
    )
    weapon_type = app.optimizer._weapon_type(None, raw_weapon)
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
            for positives in positive_counts:
                payload = {
                    "weapon": weapon_path,
                    "disposition": disposition,
                    "profile": profile,
                    "fireMode": fire_mode,
                    "_bakeStaticsOnly": True,
                    "stats": _trigger_stats(app, weapon_type, disposition, positives),
                }
                if BOT_BUNDLE:
                    import bot_riven
                    payload, notes = bot_riven._payload(payload, profile)
                    if notes:
                        raise RuntimeError(f'Bot bake trigger card required correction: {notes}')
                    payload['_bakeStaticsOnly'] = True
                response = app.analyze_payload(payload)
                work[str(positives)] = response.get('searchWork') or {}
        except Exception as exc:  # noqa: BLE001
            outcomes.append({"weapon": weapon_path, "profile": profile, "ok": False, "error": str(exc)[:200]})
            continue
        entries = {key: value for key, value in app.ANALYSIS_STATICS_CACHE.items() if isinstance(value, dict)}
        if not entries:
            outcomes.append({"weapon": weapon_path, "profile": profile, "ok": False,
                             "error": "no statics entries produced (candidate generation failed)"})
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
            shard = Path(shard_path)
            shard.parent.mkdir(parents=True, exist_ok=True)
            temporary = shard.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "schemaVersion": SHARD_SCHEMA_VERSION,
                        "cacheVersion": app.ANALYSIS_STATICS_CACHE_VERSION,
                        "inputs": worker_inputs,
                        "profile": profile,
                        "entries": entries,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.replace(shard)
        except OSError as exc:
            outcomes.append({"weapon": weapon_path, "profile": profile, "ok": False, "error": f"shard write: {exc}"})
            continue
        outcomes.append({"weapon": weapon_path, "fireMode": fire_mode, "profile": profile,
                         "ok": True, "entries": len(entries), "searchWork": work,
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
    melee routes and Incarnon forms replay the most."""
    return (raw_weapon.get("slot") != "melee", not raw_weapon.get("isIncarnon"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=_profiles, default=["standard"],
                        help="档位，逗号分隔（fast,standard）：一个任务池烘焙全部档位")
    parser.add_argument("--workers", type=limited_workers, default=None,
                        help="并行进程数（默认与分析计算池相同：物理核心数再加四分之一）")
    parser.add_argument("--weapon", action="append", default=None, help="只烘焙指定武器（可多次）")
    parser.add_argument("--limit", type=int, default=None, help="只烘焙前 N 把（冒烟用）")
    parser.add_argument("--fire-modes", action="store_true", help="烘焙全部开火模式（默认与普通分析同口径：灵化取末模式，其余取主模式）")
    parser.add_argument('--report', type=Path,
                        help='覆盖与失败报告，运行时逐项更新；多个档位时路径里写 {profile}（如 out/{profile}.json）')
    parser.add_argument('--dry-run', action='store_true', help='仅列出任务和当前分片覆盖')
    parser.add_argument('--shards-only', action='store_true', help='只生成并校验分片；不发布主缓存')
    parser.add_argument('--allow-full-bake', action='store_true', help='Use only after explicit user authorization for a full-roster bake')
    parser.add_argument('--positives', default='3,2',
                        help='烘焙的正面词条数（逗号分隔，默认 3,2：两套推荐都进缓存；只写 3 与旧流程相同）')
    parser.add_argument('--shard-dir', type=Path,
                        help='分片根目录，档位子目录为 riven-statics-shards-<档位>（默认 .local/cache）；配合 --shards-only 做对照烘焙')
    parser.add_argument('--bot-bundle', type=Path,
                        help='Bake the actual Bot runtime with its fixed preset (fast only)')
    args = parser.parse_args()
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

    import app
    from wfarsenal import parallel

    workers = args.workers or limited_workers(parallel.default_workers())
    cache_version = app.ANALYSIS_STATICS_CACHE_VERSION
    try:
        input_fingerprint = app._analysis_inputs_fingerprint()
    except app.SimulationError as exc:
        print(f"cannot bake: {exc}")
        return 2
    shard_root = args.shard_dir or SHARD_ROOT
    shard_dirs = {profile: shard_root / f"riven-statics-shards-{profile}" for profile in profiles}

    def shard_is_current(path: Path, profile: str) -> bool:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("schemaVersion") == SHARD_SCHEMA_VERSION
            and payload.get("cacheVersion") == cache_version
            and payload.get("inputs") == input_fingerprint
            and payload.get("profile") == profile
            and isinstance(payload.get("entries"), dict)
            and bool(payload.get("entries"))
        )

    weapons = _catalog_weapons()
    full_roster_size = len(weapons)
    if args.weapon:
        weapons = [w for w in weapons if w["path"] in set(args.weapon)]
    if args.limit:
        weapons = weapons[: args.limit]
    if not args.dry_run and not args.allow_full_bake and full_roster_size and len(weapons) == full_roster_size:
        parser.error('selected weapons cover the full roster; explicit authorization and --allow-full-bake are required')
    print(f"baking {len(weapons)} weapons, profiles={','.join(profiles)}, workers={workers}")

    for directory in shard_dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    planned = []
    expected_shards = {profile: set() for profile in profiles}
    failures = {profile: [] for profile in profiles}
    completed = {profile: [] for profile in profiles}
    skipped = {profile: 0 for profile in profiles}
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
                expected_shards[profile].add(shard)
                # 幂等续跑：分片已存在且当前则跳过（烘焙被中断后可续）。
                if shard.is_file() and shard_is_current(shard, profile):
                    skipped[profile] += 1
                else:
                    pending.append((profile, str(shard)))
            if pending:
                planned.append((_task_cost(raw_weapon), (weapon["path"], mode, pending, positive_counts)))
    tasks = [task for _cost, task in sorted(planned, key=lambda item: item[0])]
    pending_shards = sum(len(task[2]) for task in tasks)
    if any(skipped.values()):
        print(f"resuming: {sum(skipped.values())} shards already baked, {pending_shards} to go")
    if skipped_no_damage:
        print(f"skipping {skipped_no_damage} raw fire modes without damage data")

    started = time.time()

    def report(status_of):
        if not args.report:
            return
        for profile in profiles:
            path = Path(str(args.report).replace("{profile}", profile))
            payload = dict(status=status_of(profile), updatedAt=datetime.now(timezone.utc).isoformat(),
                           profile=profile, fireModes=args.fire_modes, workers=workers,
                           botBundle=str(BOT_BUNDLE) if BOT_BUNDLE else None,
                           gpuEnabled=False, positiveCounts=positive_counts,
                           cacheVersion=cache_version, inputs=input_fingerprint,
                           weapons=len(weapons), expectedShards=len(expected_shards[profile]),
                           skippedCurrent=skipped[profile], completed=len(completed[profile]),
                           excludedModes=excluded_modes, failures=failures[profile],
                           targetWork=completed[profile],
                           elapsedSeconds=round(time.time() - started, 3))
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(path)

    report(lambda _profile: 'planned' if args.dry_run else 'running')
    if args.dry_run:
        for profile in profiles:
            print(f'{profile}: expected {len(expected_shards[profile])}, current {skipped[profile]}, '
                  f'pending {len(expected_shards[profile]) - skipped[profile]}, excluded {excluded_modes}')
        return 0
    done = failed = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_shard_worker, task): task for task in tasks}
        for future in as_completed(futures):
            weapon_path, mode, pending, _counts = futures[future]
            try:
                outcomes = future.result()
            except Exception as exc:
                outcomes = [{'ok': False, 'weapon': weapon_path, 'profile': profile,
                             'error': f'{type(exc).__name__}: {exc}'} for profile, _shard in pending]
            for outcome in outcomes:
                done += 1
                if outcome["ok"]:
                    completed[outcome["profile"]].append(outcome)
                else:
                    failed += 1
                    failures[outcome["profile"]].append({**outcome, 'fireMode': mode})
                    print(f"  FAIL {outcome['weapon']} [{outcome['profile']}]: {outcome['error']}")
                if done % 25 == 0:
                    elapsed = time.time() - started
                    print(f"  {done}/{pending_shards} ({elapsed:.0f}s, {failed} failed)")
            report(lambda _profile: 'running')

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
    for profile in profiles:
        for shard in sorted(expected_shards[profile]):
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
                or payload.get("profile") != profile
            ):
                rejected_shards += 1
                continue
            for key, value in (payload.get("entries") or {}).items():
                if isinstance(value, dict):
                    merged[key] = value
        missing = [str(shard) for shard in expected_shards[profile] if not shard_is_current(shard, profile)]
        if missing:
            failures[profile].append(dict(error='missing-current-shards', shards=sorted(missing)))
            failed = max(failed, len(missing))
    failed_profiles = {profile for profile in profiles if failures[profile]}
    if app._analysis_inputs_fingerprint() != input_fingerprint:
        for profile in profiles:
            failures[profile].append(dict(error='inputs-changed-during-bake'))
        report(lambda _profile: 'failed-inputs-changed')
        print('inputs changed during bake; refusing to publish cache')
        return 1
    if args.shards_only:
        report(lambda profile: 'partial' if profile in failed_profiles else 'shards-complete')
        for profile in profiles:
            current = sum(1 for shard in expected_shards[profile] if shard_is_current(shard, profile))
            print(f'{profile}: verified {current}/{len(expected_shards[profile])} shards; main cache unchanged')
        print(f"total {time.time() - started:.0f}s")
        return int(bool(failed))
    app.ANALYSIS_STATICS_CACHE.clear()
    app.ANALYSIS_STATICS_CACHE.update(merged)
    app.ANALYSIS_STATICS_CACHE["__dirty__"] = True
    app._persist_analysis_statics_cache()
    print(f"merged {len(merged)} entries into main cache")
    if rejected_shards:
        print(f"rejected {rejected_shards} stale/unreadable shards")
    print(f"total {time.time() - started:.0f}s, {failed} failed of {pending_shards}")
    report(lambda profile: 'partial' if profile in failed_profiles else 'complete')
    # F14 边界：有失败时不得报 0——「条目非空、worker 没抛异常」不等于
    # 语义正确。失败数 > 0 时返回 1，让 CI/批处理能感知部分失败。
    if failed:
        return 1
    if not tasks and not any(skipped.values()):
        print("nothing to bake (no weapons/modes selected)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
