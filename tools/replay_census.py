"""Which replay features the catalog's weapons use (one bare replay each).

    python tools/replay_census.py [out.json]

Patches combat_replay._trajectory to record a feature signature of every call
made by a bare manual simulation of each weapon, then prints how many weapons
need each feature. Used to stage the native replay port.
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

COMBAT_FLAGS = ("melee", "cycle", "onosCharge", "manualDetonation", "enervate", "encumber", "empowered",
                "cryogenic", "fortifier", "syndicate", "spool", "fireRateSpool", "battery", "shellReload",
                "doubleTap", "sniperCombo", "fieldDurationOnEmptyReload", "punctureArmorStrip", "magazineRestore",
                "lastBurst", "reloadAfterEveryShot", "refillMagazineGrowth", "infiniteAmmo", "selectedIncarnon",
                "duplicate", "baseBurst", "incarnonBurst", "beamRampFloors", "projectileState", "conditionOverload",
                "onosCrits")
STATS_ATTRS = ("_lingering", "_stackable", "_primary_delay_seconds", "_bow_draw", "_charge_time", "_requires_full_ammo",
               "_charge_pool_cost", "_head_only", "_impact_delay", "_additional_radials")


def signature(stats, options):
    combat = options.get("combat") or {}
    features = {k for k in COMBAT_FLAGS if combat.get(k)}
    features |= {k for k in STATS_ATTRS if getattr(stats, k, None)}
    if options.get("trigger_sources"):
        features.add("triggers")
    if getattr(stats, "extra_hits", ()):
        features.add("extraHits")
    if options.get("weak_draw"):
        features.add("killBranches")
    if options.get("life_curve") is not None:
        features.add("lifeCurve")
    if stats.continuous:
        features.add("continuous")
    if stats.radial_only:
        features.add("radialOnly")
    return features


def main():
    import app
    from wfarsenal import combat_replay
    original = combat_replay._trajectory
    seen = []

    def spy(stats, target, **options):
        seen.append(signature(stats, options))
        return original(stats, target, **options)

    combat_replay._trajectory = spy
    per_weapon = {}
    for weapon in app.CATALOG["weapons"]:
        if not weapon.get("available"):
            continue
        seen.clear()
        try:
            app.simulate_manual_payload(dict(weapon=weapon["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH,
                                             level=170, steelPath=True))
        except Exception as exc:  # noqa: BLE001
            per_weapon[weapon["path"]] = {"error": str(exc)[:80]}
            continue
        per_weapon[weapon["path"]] = sorted(set().union(*seen)) if seen else []
    counts = collections.Counter(f for v in per_weapon.values() if isinstance(v, list) for f in v)
    plain = sum(1 for v in per_weapon.values() if isinstance(v, list) and not set(v) - {"triggers", "extraHits"})
    print(f"weapons {len(per_weapon)}; plain (no special feature) {plain}")
    for feature, n in counts.most_common():
        print(f"{n:5d} {feature}")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(per_weapon, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
