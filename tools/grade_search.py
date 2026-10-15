"""配装搜索的真值评分：在小卡池上穷举，量出各档位 beam 搜索的遗憾。

用法：
    python tools/grade_search.py --weapon "Boltor Prime" --weapon "Lex Prime"
        [--profile fast,standard,deep] [--pool 16] [--extra '{"triggerPolicy": "assumed_max"}']
        [--workers N] [--report out.json]

对每把武器：
1. 用配装页同一套请求解析（``app.build_weapon_payload``）拿到候选卡、赋能/灵化被动、场景与目标；
2. 各档位直接调用 ``optimizer.optimize_for_element`` 求解并计时（不含自动 Exilus，与穷举口径一致）；
3. 按搜索器自己的单卡排序（必选卡 + 单卡评分，同族去重）取前 ``--pool`` 张，穷举其中所有
   「能放满的最多张数」组合（容量放不下就退一张），每个组合与搜索器一样尝试全部元素顺序；
4. 遗憾 = max(0, 穷举最优 − 档位得分) / 穷举最优。穷举只覆盖前 N 张，所以这是遗憾的下界：
   档位用到池外的卡而超过穷举最优时记为 0。

C(16,8) = 12,870、C(20,8) = 125,970 个组合；评分在共享计算池上分块执行。
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHUNK = 48


def _chunk_job(args: tuple) -> tuple[float | None, tuple[int, ...] | None, int]:
    """Best (score, pool indexes) of one chunk of combinations, and how many fit."""
    from wfarsenal import optimizer

    combos, ctx = args
    pool, required = ctx["pool"], ctx["required"]
    best_score: float | None = None
    best_combo: tuple[int, ...] | None = None
    valid = 0
    for combo in combos:
        evaluated = optimizer._evaluate(
            ctx["weapon"], (*required, *(pool[i] for i in combo)), None,
            scenario=ctx["scenario"], metric=ctx["metric"], passives=ctx["passives"],
            slot_limit=ctx["slot_limit"], capacity_limit=ctx["capacity_limit"],
            target_context=ctx["target_context"],
        )
        if evaluated is None:
            continue
        valid += 1
        if best_score is None or evaluated.score > best_score:
            best_score, best_combo = evaluated.score, combo
    return best_score, best_combo, valid


def _engine(app: Any, payload: dict) -> dict:
    _result, engine = app.build_weapon_payload(dict(payload, profile="fast"), return_engine_context=True)
    return engine


def _search_kwargs(engine: dict, slot_count: int) -> dict:
    return dict(
        scenario=engine["scenario"], metric=engine["metric"], passives=engine["passives"],
        slot_count=slot_count, capacity_limit=engine["capacityLimit"],
        target_context=engine["benchmarkContext"],
    )


def _ranked_pool(engine: dict, slot_count: int, size: int) -> tuple[tuple, list]:
    """The optimizer's own single-card order (required cards + one card), one card per family."""
    from dataclasses import replace

    from wfarsenal import optimizer, parallel

    candidates = engine["candidates"]
    required = tuple(card for card in candidates if card.required)
    optional = [card for card in candidates if not card.required]
    available = {card.key for card in candidates}
    optional = [card for card in optional if (card.record or {}).get("optimizerDuplicateOf") not in available]
    scenario = engine["scenario"]
    if not isinstance(scenario.conditional_stacks, dict):
        scenario = replace(scenario, conditional_stacks=dict(scenario.conditional_stacks))
    ctx = parallel.shared(dict(
        weapon=engine["weapon"], scenario=scenario, metric=engine["metric"], passives=engine["passives"],
        slot_limit=slot_count, capacity_limit=engine["capacityLimit"], target_context=engine["benchmarkContext"],
    ))
    scores = parallel.map_jobs(parallel._score_job, [((*required, card), None, ctx) for card in optional])
    ranked = sorted(
        ((score, card) for score, card in zip(scores, optional) if isinstance(score, (int, float))),
        key=lambda item: (-item[0], item[1].key),
    )
    pool, families = [], set()
    for _score, card in ranked:
        family = optimizer._mod_family(card)
        if family in families:
            continue
        families.add(family)
        pool.append(card)
        if len(pool) >= size:
            break
    return required, pool


def _exhaustive(engine: dict, required: tuple, pool: list, slot_count: int) -> dict:
    from dataclasses import replace

    from wfarsenal import parallel

    scenario = engine["scenario"]
    if not isinstance(scenario.conditional_stacks, dict):
        scenario = replace(scenario, conditional_stacks=dict(scenario.conditional_stacks))
    ctx = parallel.shared(dict(
        weapon=engine["weapon"], scenario=scenario, metric=engine["metric"], passives=engine["passives"],
        slot_limit=slot_count, capacity_limit=engine["capacityLimit"], target_context=engine["benchmarkContext"],
        pool=tuple(pool), required=required,
    ))
    started = time.perf_counter()
    evaluated = 0
    top = min(len(pool), slot_count - len(required))
    for keep in range(top, -1, -1):
        combos = list(itertools.combinations(range(len(pool)), keep))
        evaluated += len(combos)
        rows = parallel.map_jobs(_chunk_job, [(combos[i:i + CHUNK], ctx) for i in range(0, len(combos), CHUNK)])
        failures = [row for row in rows if isinstance(row, Exception)]
        if failures:
            raise failures[0]
        found = [row for row in rows if row[0] is not None]
        if found:
            score, combo, _valid = max(found, key=lambda row: row[0])
            return dict(score=score, cards=[*(c.key for c in required), *(pool[i].key for i in combo)],
                        cardsPerBuild=keep + len(required), combinations=evaluated,
                        valid=sum(row[2] for row in found), seconds=round(time.perf_counter() - started, 2))
    return dict(score=None, combinations=evaluated, seconds=round(time.perf_counter() - started, 2))


def grade(app: Any, weapon: dict, profiles: list[str], pool_size: int, extra: dict, slot_count: int = 8) -> dict:
    from wfarsenal import optimizer

    payload = {"weapon": weapon["path"], "mode": "auto", **extra}
    engine = _engine(app, payload)
    kwargs = _search_kwargs(engine, slot_count)
    searched = {}
    for profile in profiles:
        started = time.perf_counter()
        evaluation = optimizer.optimize_for_element(
            engine["weapon"], engine["candidates"], engine["riven"], profile=profile, **kwargs
        )
        searched[profile] = dict(score=evaluation.score, cards=[card.key for card in evaluation.cards],
                                 seconds=round(time.perf_counter() - started, 2))
    required, pool = _ranked_pool(engine, slot_count, pool_size)
    truth = _exhaustive(engine, required, pool, slot_count)
    pool_keys = {card.key for card in (*required, *pool)}
    for row in searched.values():
        if truth.get("score"):
            row["regretPercent"] = round(100.0 * max(0.0, truth["score"] - row["score"]) / truth["score"], 3)
        row["outsidePool"] = [key for key in row["cards"] if key not in pool_keys]
    return dict(weapon=weapon.get("nameEn"), path=weapon["path"], pool=[card.key for card in pool],
                required=[card.key for card in required], truth=truth, profiles=searched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weapon", action="append", required=True, help="catalog English name or weapon path")
    parser.add_argument("--profile", default="fast,standard,deep")
    parser.add_argument("--pool", type=int, default=16)
    parser.add_argument("--extra", default="{}", help="extra /api/build request fields (JSON)")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    profiles = [p.strip() for p in args.profile.split(",") if p.strip()]
    extra = json.loads(args.extra)

    import app
    from wfarsenal import parallel

    if args.workers:
        parallel.configure(workers=args.workers)
    by_name: dict = {}
    for w in app.CATALOG["weapons"]:  # a few English names repeat (Hek, Lato): first wins
        by_name.setdefault(w.get("nameEn"), w)
    by_path = {w["path"]: w for w in app.CATALOG["weapons"]}
    rows = []
    try:
        for name in args.weapon:
            weapon = by_name.get(name) or by_path.get(name)
            if weapon is None:
                print(f"unknown weapon: {name}", file=sys.stderr)
                return 2
            row = grade(app, weapon, profiles, args.pool, extra)
            rows.append(row)
            truth = row["truth"]
            line = (f"{row['weapon']}: exhaustive top-{args.pool} {truth.get('score') or math.nan:.4f} "
                    f"({truth['combinations']} builds, {truth['seconds']}s)")
            for profile, result in row["profiles"].items():
                line += (f" | {profile} {result['score']:.4f} {result['seconds']}s"
                         f" regret {result.get('regretPercent', math.nan):.2f}%")
            print(line, flush=True)
            if args.report:
                Path(args.report).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        parallel.shutdown_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
