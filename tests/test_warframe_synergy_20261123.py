"""Comprehensive tests for WarframeEngine Update 34+ scaling, capacity/Omni rules,
missing Warframe arcanes, survivability readout, catalog repairs, and weaponBridge.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

import app
from wfarsenal.simulator import SimulationError
from wfarsenal.warframe import WarframeEngine, load_warframe_catalog


EXCALIBUR = "/Lotus/Powersuits/Excalibur/Excalibur"
INAROS = "/Lotus/Powersuits/Sandman/Sandman"
HILDRYN = "/Lotus/Powersuits/IronFrame/IronFrame"
VOLT = "/Lotus/Powersuits/Volt/Volt"
RHINO = "/Lotus/Powersuits/Rhino/Rhino"
GAUSS = "/Lotus/Powersuits/Runner/Runner"
OCTAVIA = "/Lotus/Powersuits/Bard/Bard"
LAVOS = "/Lotus/Powersuits/Alchemist/Alchemist"


def _mod_by_en(name_en: str, *, slot_kind: str | None = None) -> dict:
    candidates = []
    for row in app.WARFRAME_ENGINE.mods:
        if row.get("nameEn") != name_en:
            continue
        if slot_kind and str(row.get("slotKind") or "").casefold() != slot_kind.casefold():
            continue
        if "/Beginner/" in str(row.get("path") or ""):
            continue
        candidates.append(row)
    if not candidates:
        raise KeyError(name_en)
    return max(candidates, key=lambda r: int(r.get("maxRank") or 0))


def _arcane_by_en(name_en: str) -> dict:
    return next(row for row in app.WARFRAME_ENGINE.arcanes if row.get("nameEn") == name_en)


def _shard(leaf: str, *, tau: bool = False) -> dict:
    suffix = f"{leaf}{'Mythic' if tau else ''}"
    return next(row for row in app.WARFRAME_ENGINE.shards if str(row.get("path") or "").endswith("/" + suffix))


def _frame_by_en(name_en: str) -> dict:
    return next(row for row in app.WARFRAME_ENGINE.frames if row.get("nameEn") == name_en)


def test_snapshot_sidecar_resolution_and_in_memory_catalog_repairs(tmp_path: Path):
    disk_catalog = app.ROOT / "data" / "warframe_build_data.json"
    before_sha = hashlib.sha256(disk_catalog.read_bytes()).hexdigest()

    # Simulate snapshot layout where parent directory has NO mechanics/ folder.
    snap_dir = tmp_path / "snapshots" / "snap_test"
    snap_dir.mkdir(parents=True)
    snap_catalog_file = snap_dir / "warframe_build_data.json"
    shutil.copy2(disk_catalog, snap_catalog_file)

    loaded = load_warframe_catalog(snap_catalog_file)
    assert loaded["status"] == "ready"
    assert len(loaded["warframeForms"]) == 2
    roar_h = next(row for row in loaded["helminth"] if row["path"].endswith("/RhinoRoarAbility"))
    assert roar_h["scalarSource"] == "wiki-altered"
    assert roar_h["nameEn"] == "Roar"

    # Zero raw localization placeholders remain on any shard.
    for shard in loaded["shards"]:
        for key in ("nameZh", "description"):
            text = str(shard.get(key) or "")
            assert "|AMOUNT|" not in text, shard["path"]
            assert "|max|" not in text, shard["path"]
            assert "+0.3%" not in text and "+0.45%" not in text, shard["path"]
            assert "+0.25%" not in text and "+0.375%" not in text, shard["path"]
            assert "0.01%" not in text and "0.015%" not in text, shard["path"]

    v_elec = next(s for s in loaded["shards"] if s["path"].endswith("/ArchonCrystalUpgradeWarframeElectricDamage"))
    assert "+30%" in v_elec["nameZh"] and "+10%" in v_elec["nameZh"]
    v_elec_tau = next(s for s in loaded["shards"] if s["path"].endswith("/ArchonCrystalUpgradeWarframeElectricDamageMythic"))
    assert "+45%" in v_elec_tau["nameZh"] and "+15%" in v_elec_tau["nameZh"]
    v_cd = next(s for s in loaded["shards"] if s["path"].endswith("/ArchonCrystalUpgradeWarframeCritDamageBoost"))
    assert "+25%" in v_cd["nameZh"] and "500" in v_cd["nameZh"]
    t_cc = next(s for s in loaded["shards"] if s["path"].endswith("/ArchonCrystalUpgradeWeaponCritBoostFromHeat"))
    assert "+1%" in t_cc["nameZh"] and "50%" in t_cc["nameZh"]

    status_invig = next(
        row for row in loaded["invigoration"]
        if row["path"].endswith("/UtilityInvigorationStatusResistance")
    )
    assert status_invig["nameZh"] == "状态免疫"
    assert status_invig["description"] == "状态免疫"

    # Topaz Blast-kill HP shard must NOT add +1 unconditional health.
    engine = WarframeEngine(loaded)
    base_hp = engine.calculate({"frameId": EXCALIBUR})["finalPanel"]["health"]
    topaz_hp_shard = next(s for s in loaded["shards"] if s["path"].endswith("/ArchonCrystalUpgradeWarframeHPBoostFromImpact"))
    with_topaz = engine.calculate({"frameId": EXCALIBUR, "shards": [{"path": topaz_hp_shard["path"], "tau": False}]})
    assert with_topaz["finalPanel"]["health"] == pytest.approx(base_hp)

    # Disk warframe_build_data.json must stay completely untouched.
    assert hashlib.sha256(disk_catalog.read_bytes()).hexdigest() == before_sha


def test_update_34_rank30_stat_scaling_and_zero_pool_frames():
    engine = app.WARFRAME_ENGINE
    vitality = _mod_by_en("Vitality")
    redirection = _mod_by_en("Redirection")
    steel_fiber = _mod_by_en("Steel Fiber")
    primed_flow = _mod_by_en("Primed Flow")
    rush = _mod_by_en("Rush")
    catalyzing = _mod_by_en("Catalyzing Shields")

    # Excalibur rank30Panel: health=370, shield=370, armor=240, energy=150, sprint=1.0
    res = engine.calculate({
        "frameId": EXCALIBUR,
        "normalMods": [
            {"path": vitality["path"], "rank": 10, "slot": 0},
            {"path": redirection["path"], "rank": 10, "slot": 1},
            {"path": steel_fiber["path"], "rank": 10, "slot": 2},
            {"path": primed_flow["path"], "rank": 10, "slot": 3},
            {"path": rush["path"], "rank": 5, "slot": 4},
        ],
        "shards": [
            {"path": _shard("ArchonCrystalUpgradeWarframeHealthMax", tau=True)["path"], "tau": True},
            {"path": _shard("ArchonCrystalUpgradeWarframeShieldMax", tau=True)["path"], "tau": True},
        ],
    })
    panel = res["finalPanel"]
    # Vitality/Redirection/Steel Fiber multiply rank30Panel (370/370/240), NOT rank0 basePanel (270/270/240).
    assert panel["health"] == pytest.approx(370.0 * 2.0 + 225.0, rel=1e-4)
    assert panel["shield"] == pytest.approx(370.0 * 2.0 + 225.0, rel=1e-4)
    assert panel["armor"] == pytest.approx(240.0 * 2.0, rel=1e-4)
    assert panel["energy"] == pytest.approx(150.0 * (1.0 + 1.85), rel=1e-4)
    assert panel["sprint"] == pytest.approx(1.0 * 1.30, rel=1e-5)

    # Catalyzing Shields multiplies AFTER (rank30 * (1 + pct) + flat) across ranks 0..3.
    for r, mult, gate in zip(range(4), (0.80, 0.60, 0.40, 0.20), (0.33, 0.67, 1.00, 1.33)):
        cat_res = engine.calculate({
            "frameId": EXCALIBUR,
            "normalMods": [
                {"path": redirection["path"], "rank": 10, "slot": 0},
                {"path": catalyzing["path"], "rank": r, "slot": 1},
            ],
            "shards": [{"path": _shard("ArchonCrystalUpgradeWarframeShieldMax", tau=True)["path"], "tau": True}],
        })
        assert cat_res["finalPanel"]["shield"] == pytest.approx((370.0 * 2.0 + 225.0) * mult, rel=1e-4)
        assert cat_res["survivability"]["shieldGateSeconds"] == pytest.approx(gate)

    # Shieldless Inaros stays 0 shield even with Azure Shield shards; Energyless Hildryn/Lavos stay 0 energy.
    inaros_res = engine.calculate({
        "frameId": INAROS,
        "shards": [{"path": _shard("ArchonCrystalUpgradeWarframeShieldMax", tau=True)["path"], "tau": True}],
    })
    assert inaros_res["finalPanel"]["shield"] == 0.0
    assert inaros_res["survivability"]["shieldGateSeconds"] == 0.0

    for zero_energy_frame in (HILDRYN, LAVOS):
        ze_res = engine.calculate({
            "frameId": zero_energy_frame,
            "arcanes": [{"path": _arcane_by_en("Arcane Battery")["path"], "rank": 5}],
            "shards": [{"path": _shard("ArchonCrystalUpgradeWarframeEnergyMax", tau=True)["path"], "tau": True}],
        })
        assert ze_res["finalPanel"]["energy"] == 0.0


def test_mismatched_aura_capacity_and_omni_polarity():
    engine = app.WARFRAME_ENGINE
    corrosive_proj = _mod_by_en("Corrosive Projection", slot_kind="aura")  # AP_TACTIC, raw -7 at R5
    steel_charge = _mod_by_en("Steel Charge", slot_kind="aura")  # AP_ATTACK, raw -9 at R5
    blind_rage = _mod_by_en("Blind Rage")  # AP_ATTACK, raw 16 at R10
    umbral_intensify = _mod_by_en("Umbral Intensify")  # AP_UMBRA, raw 16 at R10

    # Aura capacity: matched=14, neutral=7, mismatched=floor(7*0.8)=5
    matched = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": corrosive_proj["path"], "rank": 5},
        "slotPolarities": {"aura": "AP_TACTIC"},
    })["capacityBreakdown"]
    assert matched["auraGain"] == 14 and matched["limit"] == 74 and matched["aura"]["polarityRelation"] == "matched"

    neutral = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": corrosive_proj["path"], "rank": 5},
        "slotPolarities": {"aura": None},
    })["capacityBreakdown"]
    assert neutral["auraGain"] == 7 and neutral["limit"] == 67 and neutral["aura"]["polarityRelation"] == "unpolarized"

    mismatched = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": corrosive_proj["path"], "rank": 5},
        "slotPolarities": {"aura": "AP_ATTACK"},
    })["capacityBreakdown"]
    assert mismatched["auraGain"] == 5 and mismatched["limit"] == 65 and mismatched["aura"]["polarityRelation"] == "mismatched"

    # Steel Charge (-9): mismatched gives floor(9 * 0.8) = 7
    sc_mismatch = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": steel_charge["path"], "rank": 5},
        "slotPolarities": {"aura": "AP_TACTIC"},
    })["capacityBreakdown"]
    assert sc_mismatch["auraGain"] == 7 and sc_mismatch["limit"] == 67

    # Omni (AP_ANY): matches non-Umbra in aura and normal slots, mismatches AP_UMBRA!
    omni = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": steel_charge["path"], "rank": 5},
        "normalMods": [
            {"path": blind_rage["path"], "rank": 10, "slot": 0},
            {"path": umbral_intensify["path"], "rank": 10, "slot": 1},
        ],
        "slotPolarities": {
            "aura": "AP_ANY",
            "normal": ["AP_ANY", "AP_ANY", None, None, None, None, None, None],
        },
    })["capacityBreakdown"]
    assert omni["auraGain"] == 18 and omni["aura"]["polarityRelation"] == "matched"
    by_slot = {row["slot"]: row for row in omni["assignments"]}
    assert by_slot[0]["drain"] == 8 and by_slot[0]["polarityRelation"] == "matched"
    assert by_slot[1]["drain"] == 20 and by_slot[1]["polarityRelation"] == "mismatched"


def test_avatar_heal_rate_alias_and_non_self_auras():
    engine = app.WARFRAME_ENGINE
    rejuv = _mod_by_en("Rejuvenation", slot_kind="aura")
    dreamer = _mod_by_en("Dreamer's Bond", slot_kind="aura")
    reaper = _arcane_by_en("Arcane Reaper")
    regen_invig = next(i for i in engine.invigoration if i["path"].endswith("/UtilityInvigorationHealthRegen"))

    res = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "aura": {"path": rejuv["path"], "rank": 5},
        "arcanes": [{"path": reaper["path"], "rank": 5}],
        "shards": [
            {"path": _shard("ArchonCrystalUpgradeWarframeRegen", tau=False)["path"], "tau": False},
            {"path": _shard("ArchonCrystalUpgradeWarframeRegen", tau=True)["path"], "tau": True},
        ],
        "invigoration": [regen_invig["path"]],
    })
    # 3.0 (Rejuvenation) + 24.0 (Arcane Reaper) + 5.0 + 7.5 (Azure shards) + 25.0 (Invigoration) = 64.5
    assert res["finalPanel"]["healthRegen"] == pytest.approx(64.5)

    db_res = engine.calculate({"frameId": EXCALIBUR, "aura": {"path": dreamer["path"], "rank": 5}})
    assert db_res["finalPanel"]["healthRegen"] == pytest.approx(1.5)
    assert db_res["finalPanel"]["energyRegen"] == pytest.approx(0.3)

    # Enemy/companion auras must NOT penalize or buff the Warframe's own panel.
    base_panel = engine.calculate({"frameId": EXCALIBUR})["finalPanel"]
    for aura_name in ("Corrosive Projection", "Shield Disruption", "Infested Impedance", "Shepherd"):
        aura_card = _mod_by_en(aura_name, slot_kind="aura")
        panel = engine.calculate({"frameId": EXCALIBUR, "aura": {"path": aura_card["path"], "rank": 5}})["finalPanel"]
        for stat in ("health", "shield", "armor", "sprint"):
            assert panel[stat] == pytest.approx(base_panel[stat]), aura_name


def test_mod_family_mutual_exclusion_and_helminth_augment_rules():
    engine = app.WARFRAME_ENGINE

    conflicting_pairs = [
        ("Vitality", "Umbral Vitality"),
        ("Vitality", "Archon Vitality"),
        ("Intensify", "Umbral Intensify"),
        ("Intensify", "Archon Intensify"),
        ("Intensify", "Precision Intensify"),
        ("Redirection", "Primed Redirection"),
        ("Flow", "Primed Flow"),
        ("Flow", "Archon Flow"),
        ("Continuity", "Primed Continuity"),
        ("Continuity", "Archon Continuity"),
        ("Stretch", "Archon Stretch"),
        ("Steel Fiber", "Umbral Fiber"),
    ]
    for first_name, second_name in conflicting_pairs:
        m1, m2 = _mod_by_en(first_name), _mod_by_en(second_name)
        with pytest.raises(SimulationError, match="modFamily"):
            engine.calculate({
                "frameId": EXCALIBUR,
                "normalMods": [{"path": m1["path"], "slot": 0}, {"path": m2["path"], "slot": 1}],
            })

    # Streamline + Fleeting Expertise have distinct families and CAN stack (capped at 1.75 efficiency).
    eff = engine.calculate({
        "frameId": EXCALIBUR,
        "normalMods": [
            {"path": _mod_by_en("Streamline")["path"], "rank": 5, "slot": 0},
            {"path": _mod_by_en("Fleeting Expertise")["path"], "rank": 5, "slot": 1},
        ],
    })
    assert eff["finalPanel"]["abilityEfficiency"] == pytest.approx(1.75)

    # Duplicate native ability rejection.
    with pytest.raises(SimulationError, match="duplicate"):
        engine.calculate({
            "frameId": RHINO,
            "helminthReplacement": {"slot": 0, "abilityId": "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility"},
        })

    # Damage-buff slot exclusion across frames with native weapon damage buffs.
    roar = "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility"
    eclipse = "/Lotus/Powersuits/Harlequin/Abilities/LightAbility"
    xata = "/Lotus/Powersuits/BrokenFrame/Abilities/BrokenRotAbility"
    frame_buff_slots = [
        ("Rhino", 2, eclipse),
        ("Rhino Prime", 2, xata),
        ("Mirage", 2, roar),
        ("Chroma", 2, roar),
        ("Xaku", 0, roar),
        ("Octavia", 3, roar),
        ("Cyte-09", 1, roar),
        ("Oraxia", 3, roar),
        ("Temple", 2, roar),
    ]
    for frame_name, valid_slot, infused in frame_buff_slots:
        frow = _frame_by_en(frame_name)
        wrong_slot = 0 if valid_slot != 0 else 1
        with pytest.raises(SimulationError, match="damage-buff"):
            engine.calculate({
                "frameId": frow["id"],
                "helminthReplacement": {"slot": wrong_slot, "abilityId": infused},
            })
        ok = engine.calculate({
            "frameId": frow["id"],
            "helminthReplacement": {"slot": valid_slot, "abilityId": infused},
        })
        assert ok["abilityScalars"][valid_slot]["path"] == infused

    # Augment eligibility follows active Helminth loadout!
    shock_path = "/Lotus/Powersuits/Volt/Abilities/ShockAbility"
    shock_trooper = _mod_by_en("Shock Trooper")
    piercing_roar = _mod_by_en("Piercing Roar")

    # Excalibur CANNOT equip Shock Trooper normally, CAN equip it when Shock is infused!
    with pytest.raises(SimulationError, match="not compatible"):
        engine.calculate({"frameId": EXCALIBUR, "normalMods": [{"path": shock_trooper["path"], "slot": 0}]})
    infused_exc = engine.calculate({
        "frameId": EXCALIBUR,
        "helminthReplacement": {"slot": 0, "abilityId": shock_path},
        "normalMods": [{"path": shock_trooper["path"], "rank": 3, "slot": 0}],
    })
    aug_ids = [a["id"] for a in infused_exc["weaponBridge"]["availableAbilities"]]
    assert "shock-trooper" in aug_ids

    # Volt replacing Shock (slot 0) with Roar CANNOT equip Shock Trooper, CAN equip Piercing Roar!
    with pytest.raises(SimulationError, match="not compatible"):
        engine.calculate({
            "frameId": VOLT,
            "helminthReplacement": {"slot": 0, "abilityId": roar},
            "normalMods": [{"path": shock_trooper["path"], "rank": 3, "slot": 0}],
        })
    volt_roar_aug = engine.calculate({
        "frameId": VOLT,
        "helminthReplacement": {"slot": 0, "abilityId": roar},
        "normalMods": [{"path": piercing_roar["path"], "rank": 3, "slot": 0}],
    })
    assert volt_roar_aug["validation"]["valid"]


def test_conversion_arcanes_missing_arcanes_and_pass_ordering():
    engine = app.WARFRAME_ENGINE
    bellicose = _arcane_by_en("Arcane Bellicose")
    battery = _arcane_by_en("Arcane Battery")
    expertise = _arcane_by_en("Arcane Expertise")
    persistence = _arcane_by_en("Arcane Persistence")
    molt_eff = _arcane_by_en("Molt Efficiency")
    crepuscular = _arcane_by_en("Arcane Crepuscular")
    camisado = _arcane_by_en("Arcane Camisado")
    impetus = _arcane_by_en("Arcane Impetus")
    ice_storm = _arcane_by_en("Arcane Ice Storm")
    intention = _arcane_by_en("Arcane Intention")

    # 1. Arcane Intention (+250 HP * channels) feeds Arcane Bellicose -> feeds Arcane Expertise -> Catalyzing Shields!
    # Excalibur rank30 health=370; with 3 channeled abilities (+750 HP) -> 1120 HP.
    # Bellicose R5: round(1120 / 250 * 0.06 * 100) / 100 = round(26.88) / 100 = 0.27 -> Strength = 1.27.
    # Expertise R5: +0.27 shield pct -> (370 * 1.27) * 0.20 (Catalyzing R3) = 93.98 shield.
    chained = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "activeChanneledAbilities": 3,
        "normalMods": [{"path": _mod_by_en("Catalyzing Shields")["path"], "rank": 3, "slot": 0}],
        "arcanes": [
            {"path": intention["path"], "rank": 5},
            {"path": bellicose["path"], "rank": 5},
        ],
    })
    assert chained["finalPanel"]["health"] == pytest.approx(370.0 + 750.0)
    assert chained["finalPanel"]["abilityStrength"] == pytest.approx(1.27)

    chained_exp = engine.calculate({
        "frameId": EXCALIBUR,
        "normalMods": [
            {"path": _mod_by_en("Vitality")["path"], "rank": 10, "slot": 0},
            {"path": _mod_by_en("Catalyzing Shields")["path"], "rank": 3, "slot": 1},
        ],
        "arcanes": [
            {"path": bellicose["path"], "rank": 5},
            {"path": expertise["path"], "rank": 5},
        ],
    })
    # Health = 740 -> Bellicose = round(740/250 * 6)/100 = round(17.76)/100 = 0.18 -> Strength = 1.18
    # Shield = (370 * 1.18) * 0.20 = 87.32
    assert chained_exp["finalPanel"]["abilityStrength"] == pytest.approx(1.18)
    assert chained_exp["finalPanel"]["shield"] == pytest.approx(370.0 * 1.18 * 0.20)

    # Inaros high HP caps Bellicose at +72% (1.72 Strength).
    inaros_bel = engine.calculate({
        "frameId": INAROS,
        "normalMods": [{"path": _mod_by_en("Vitality")["path"], "rank": 10, "slot": 0}],
        "arcanes": [{"path": bellicose["path"], "rank": 5}],
    })
    assert inaros_bel["finalPanel"]["abilityStrength"] == pytest.approx(1.72)

    # 2. Arcane Battery runs AFTER Armor mods and BEFORE Violet Shard >500 Max Energy check!
    # Excalibur: base energy=150, armor=240; with Steel Fiber R10 + 3x Tau Azure Armor (+675) -> armor = 480 + 675 = 1155?
    # Simpler: Rhino Prime / Valkyr or Excalibur with UtilityInvigorationArmor (+1000) -> armor = 1240 -> Battery +372 -> energy = 522 (> 500)!
    armor_invig = next(i for i in engine.invigoration if i["path"].endswith("/UtilityInvigorationArmor"))
    violet_cd = _shard("ArchonCrystalUpgradeWarframeCritDamageBoost", tau=True)
    bat_violet = engine.calculate({
        "frameId": EXCALIBUR,
        "arcanes": [{"path": battery["path"], "rank": 5}],
        "shards": [{"path": violet_cd["path"], "tau": True}],
        "invigoration": [armor_invig["path"]],
    })
    assert bat_violet["finalPanel"]["armor"] == pytest.approx(1240.0)
    assert bat_violet["finalPanel"]["energy"] == pytest.approx(150.0 + 1240.0 * 0.30)
    assert bat_violet["finalPanel"]["energy"] > 500.0
    assert bat_violet["weaponBridge"]["shards"]["violetMeleeCritDoubled"] is True
    assert bat_violet["weaponBridge"]["shards"]["meleeCritDamage"] == pytest.approx(0.75)

    # Without Battery, energy is 150 <= 500 -> Violet Tau Melee CD is +0.375 (not doubled).
    no_bat = engine.calculate({
        "frameId": EXCALIBUR,
        "shards": [{"path": violet_cd["path"], "tau": True}],
    })
    assert no_bat["weaponBridge"]["shards"]["violetMeleeCritDoubled"] is False
    assert no_bat["weaponBridge"]["shards"]["meleeCritDamage"] == pytest.approx(0.375)

    # 3. Arcane Persistence zeroes shields and grants 500 DPS cap iff armor > 700; Molt Efficiency is suppressed at 0 shield!
    low_armor_pers = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "arcanes": [
            {"path": persistence["path"], "rank": 5},
            {"path": molt_eff["path"], "rank": 5},
        ],
    })
    assert low_armor_pers["finalPanel"]["shield"] == 0.0
    assert low_armor_pers["survivability"]["damageCapPerSecond"] is None
    assert low_armor_pers["finalPanel"]["abilityDuration"] == pytest.approx(1.0)  # 0 shield -> no Molt Efficiency!

    high_armor_pers = engine.calculate({
        "frameId": EXCALIBUR,
        "arcanes": [{"path": persistence["path"], "rank": 5}],
        "invigoration": [armor_invig["path"]],
    })
    assert high_armor_pers["finalPanel"]["shield"] == 0.0
    assert high_armor_pers["survivability"]["damageCapPerSecond"] == pytest.approx(500.0)

    # With shield > 0 and conditionals=True, Molt Efficiency R5 grants +36% Duration.
    shielded_me = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "arcanes": [{"path": molt_eff["path"], "rank": 5}],
    })
    assert shielded_me["finalPanel"]["abilityDuration"] == pytest.approx(1.36)

    # 4. Crepuscular (+30% Str), Camisado (+60% Str), Impetus (13 stacks -> +78% Str, +39% Eff), Ice Storm (20 stacks -> +40% Str & Dur).
    crep_cam = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "arcanes": [
            {"path": crepuscular["path"], "rank": 5},
            {"path": camisado["path"], "rank": 5},
        ],
    })
    assert crep_cam["finalPanel"]["abilityStrength"] == pytest.approx(1.90)

    imp_ice = engine.calculate({
        "frameId": EXCALIBUR,
        "applyConditionals": True,
        "arcanes": [
            {"path": impetus["path"], "rank": 5},
            {"path": ice_storm["path"], "rank": 5},
        ],
    })
    assert imp_ice["finalPanel"]["abilityStrength"] == pytest.approx(1.0 + 0.78 + 0.40)
    assert imp_ice["finalPanel"]["abilityDuration"] == pytest.approx(1.0 + 0.40)
    assert imp_ice["finalPanel"]["abilityEfficiency"] == pytest.approx(1.0 + 0.39)


def test_survivability_readout_curves_and_mod_flags():
    engine = app.WARFRAME_ENGINE
    brief_respite = _mod_by_en("Brief Respite", slot_kind="aura")
    combat_disc = _mod_by_en("Combat Discipline", slot_kind="aura")
    fast_def = _mod_by_en("Primed Fast Deflection")
    vig_vigor = _mod_by_en("Vigilante Vigor")
    augur_reach = _mod_by_en("Augur Reach")
    augur_message = _mod_by_en("Augur Message")
    adaptation = _mod_by_en("Adaptation")
    rolling_guard = _mod_by_en("Rolling Guard")
    status_invig = next(i for i in engine.invigoration if i["path"].endswith("/UtilityInvigorationStatusResistance"))

    res = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": brief_respite["path"], "rank": 5},
        "normalMods": [
            {"path": fast_def["path"], "rank": 10, "slot": 0},
            {"path": vig_vigor["path"], "rank": 5, "slot": 1},
            {"path": augur_reach["path"], "rank": 5, "slot": 2},
            {"path": augur_message["path"], "rank": 5, "slot": 3},
            {"path": adaptation["path"], "rank": 10, "slot": 4},
            {"path": rolling_guard["path"], "rank": 10, "slot": 5},
        ],
        "invigoration": [status_invig["path"]],
    })
    surv = res["survivability"]
    expected_gate = 0.33 + 2.17 * ((370.0 / 1150.0) ** 0.65)
    assert surv["shieldGateSeconds"] == pytest.approx(expected_gate, abs=1e-5)
    # Primed Fast Deflection R10 (+165% rate, -55% delay) + Vigilante Vigor R5 (+60% rate, -30% delay -> -85% -> clamped to 0.20x!).
    assert surv["shieldRechargeRate"] == pytest.approx((15.0 + 0.05 * 370.0) * (1.0 + 1.65 + 0.60), rel=1e-5)
    assert surv["shieldRechargeDelay"] == pytest.approx(0.20)
    assert surv["shieldDepletedDelay"] == pytest.approx(0.80)
    # Brief Respite R5 (1.50) + 2 Augur pieces (0.80) = 2.30
    assert surv["energyToShieldRatio"] == pytest.approx(2.30)
    assert surv["hasAdaptation"] is True and surv["adaptationMaxDr"] == pytest.approx(0.90)
    assert surv["hasRollingGuard"] is True
    assert surv["statusImmune"] is True

    cd_res = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": combat_disc["path"], "rank": 5},
    })
    assert cd_res["survivability"]["selfDamageOnKill"] == pytest.approx(10.0)
    assert cd_res["weaponBridge"]["aura"]["combatDisciplineSelfDamage"] == pytest.approx(10.0)


def test_weapon_bridge_shards_invigorations_aura_arcanes_and_mods():
    engine = app.WARFRAME_ENGINE
    rifle_amp = _mod_by_en("Rifle Amp", slot_kind="aura")
    coaction = _mod_by_en("Coaction Drift")
    vig_swap = _mod_by_en("Vigorous Swap")
    nira_hatred = _mod_by_en("Nira's Hatred")
    nira_anguish = _mod_by_en("Nira's Anguish")
    tek_col = _mod_by_en("Tek Collateral")
    carnis_carapace = _mod_by_en("Carnis Carapace")
    aero_vantage = _mod_by_en("Aero Vantage")

    prim_dmg_inv = next(i for i in engine.invigoration if i["path"].endswith("/OffensiveInvigorationPrimaryDamage"))
    reload_inv = next(i for i in engine.invigoration if i["path"].endswith("/UtilityInvigorationReloadSpeed"))

    # 5 Shards:
    # - 1 Tau Violet Primary Electricity (rbpCount = 3 -> 0.45 + 0.15 * 3 = 0.90)
    # - 1 Tau Crimson Primary Status (+0.375)
    # - 1 Normal Crimson Secondary Crit (+0.25)
    # - 1 Tau Emerald Corrosive Max Stacks (+3)
    # - 1 Tau Topaz Secondary Crit on Heat kills (+0.75)
    res = engine.calculate({
        "frameId": EXCALIBUR,
        "aura": {"path": rifle_amp["path"], "rank": 5},
        "exilus": {"path": nira_anguish["path"], "rank": 5},
        "normalMods": [
            {"path": coaction["path"], "rank": 5, "slot": 0},
            {"path": vig_swap["path"], "rank": 10, "slot": 1},
            {"path": nira_hatred["path"], "rank": 5, "slot": 2},
            {"path": tek_col["path"], "rank": 3, "slot": 3},
            {"path": carnis_carapace["path"], "rank": 5, "slot": 4},
            {"path": aero_vantage["path"], "rank": 3, "slot": 5},
        ],
        "arcanes": [
            {"path": _arcane_by_en("Arcane Avenger")["path"], "rank": 5},
            {"path": _arcane_by_en("Arcane Guardian")["path"], "rank": 5},
        ],
        "shards": [
            {"path": _shard("ArchonCrystalUpgradeWarframeElectricDamage", tau=True)["path"], "tau": True},
            {"path": _shard("ArchonCrystalUpgradePrimaryStatusChance", tau=True)["path"], "tau": True},
            {"path": _shard("ArchonCrystalUpgradeSecondaryCritChance", tau=False)["path"], "tau": False},
            {"path": _shard("ArchonCrystalUpgradeWarframeCorrosiveStack", tau=True)["path"], "tau": True},
            {"path": _shard("ArchonCrystalUpgradeWeaponCritBoostFromHeat", tau=True)["path"], "tau": True},
        ],
        "invigoration": [prim_dmg_inv["path"], reload_inv["path"]],
    })
    wb = res["weaponBridge"]
    assert wb["frame"]["id"] == EXCALIBUR and wb["frame"]["nameZh"]

    sh = wb["shards"]
    assert sh["rbpCount"] == 3
    assert sh["primaryElectricity"] == pytest.approx(0.90)
    assert sh["primaryStatusChance"] == pytest.approx(0.375)
    assert sh["secondaryCritChance"] == pytest.approx(0.25)
    assert sh["corrosiveMaxStacksBonus"] == 3
    assert sh["topazSecondaryCritMax"] == pytest.approx(0.75)
    assert sh["topazSecondaryCritMode"] == "additive"
    assert len(sh["summary"]) == 5

    inv = wb["invigorations"]
    assert inv["primaryDamage"] == pytest.approx(2.50)
    assert inv["reloadSpeed"] == pytest.approx(0.75)
    assert len(inv["summary"]) == 2

    au = wb["aura"]
    assert au["buffId"] == "rifle-amp"
    assert au["baseValue"] == pytest.approx(0.27)
    assert au["hasCoactionDrift"] is True
    assert au["coactionMultiplier"] == pytest.approx(1.30)
    assert au["value"] == pytest.approx(0.27 * 1.30)

    arcs = {a["nameEn"]: a for a in wb["arcanes"]}
    assert arcs["Arcane Avenger"]["triggerKind"] == "onDamaged"
    assert arcs["Arcane Avenger"]["weaponRelevant"] is True
    assert arcs["Arcane Avenger"]["effectsSpec"][0]["value"] == pytest.approx(0.45)
    assert arcs["Arcane Guardian"]["triggerKind"] == "onDamaged"
    assert arcs["Arcane Guardian"]["weaponRelevant"] is False

    mb = wb["modBonuses"]
    assert mb["vigorousSwap"] == pytest.approx(1.65)
    assert mb["niraSlamBonus"] == pytest.approx(3.00)
    assert mb["tekCollateral"] == pytest.approx(1.00)

    set_ids = {(item["setId"], item["setAlias"]) for item in wb["setModPaths"]}
    assert ("NiraSetMod", "NiraSetMod") in set_ids
    assert ("TekSetMod", "TekSetMod") in set_ids
    assert ("AshenSetMod", "CarnisSetMod") in set_ids
    assert ("HawkSetMod", "AeroSetMod") in set_ids


def test_weapon_bridge_available_abilities_and_augments_scaling():
    engine = app.WARFRAME_ENGINE
    blind_rage = _mod_by_en("Blind Rage")
    primed_cont = _mod_by_en("Primed Continuity")
    precision_int = _mod_by_en("Precision Intensify")

    # 1. Gauss Redline scales with abilityDuration + Thermal Transfer augment requires element choice!
    gauss = engine.calculate({
        "frameId": GAUSS,
        "normalMods": [
            {"path": primed_cont["path"], "rank": 10, "slot": 0},  # +55% Duration -> 1.55
            {"path": blind_rage["path"], "rank": 10, "slot": 1},   # +99% Strength -> 1.99
            {"path": _mod_by_en("Thermal Transfer")["path"], "rank": 3, "slot": 2},
        ],
    })
    ab_map = {a["id"]: a for a in gauss["weaponBridge"]["availableAbilities"]}
    assert "redline" in ab_map and "thermal-transfer" in ab_map
    redline_fx = ab_map["redline"]["effectsSpec"]
    assert redline_fx[0]["value"] == pytest.approx(0.75 * 1.55)  # gun fire rate
    assert redline_fx[1]["value"] == pytest.approx(0.40 * 1.55)  # melee attack speed
    assert redline_fx[2]["value"] == pytest.approx(0.50 * 1.55)  # reload speed
    tt = ab_map["thermal-transfer"]
    assert tt["requiresElementChoice"] is True
    assert set(tt["elementOptions"]) == {"DT_FREEZE", "DT_FIRE", "DT_EXPLOSION"}
    assert tt["effectsSpec"][0]["upgradeType"] == "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"
    assert tt["effectsSpec"][0]["value"] == pytest.approx(0.75 * 1.99)

    # 2. Octavia Amp (slot 3) + Precision Intensify (+90% slot-3 Strength) vs Helminth Roar in slot 0!
    octavia = engine.calculate({
        "frameId": OCTAVIA,
        "helminthReplacement": {"slot": 0, "abilityId": "/Lotus/Powersuits/Devourer/Abilities/DevourerConsumeAbility"},
        "normalMods": [{"path": precision_int["path"], "rank": 5, "slot": 0}],
    })
    oct_map = {a["id"]: a for a in octavia["weaponBridge"]["availableAbilities"]}
    assert octavia["finalPanel"]["abilityStrength"] == pytest.approx(1.0)
    assert octavia["finalPanel"]["abilityFourStrength"] == pytest.approx(1.90)
    # Nourish in slot 0 uses 1.0 Strength (0.45 * 1.0 = 0.45); Amp in slot 3 uses 1.90 Strength (2.0 * 1.90 = 3.80)!
    assert oct_map["nourish-helminth"]["isHelminth"] is True
    assert oct_map["nourish-helminth"]["effectsSpec"][0]["value"] == pytest.approx(0.45)
    assert oct_map["octavia-amp"]["effectsSpec"][0]["value"] == pytest.approx(2.00 * 1.90)

    # 3. Lavos Valence Formation (+200% fixed POST_COALESCE + forcedProc + 10-element selector).
    lavos = engine.calculate({
        "frameId": LAVOS,
        "normalMods": [
            {"path": blind_rage["path"], "rank": 10, "slot": 0},
            {"path": _mod_by_en("Valence Formation")["path"], "rank": 3, "slot": 1},
        ],
    })
    vf = next(a for a in lavos["weaponBridge"]["availableAbilities"] if a["id"] == "valence-formation")
    assert vf["requiresElementChoice"] is True and len(vf["elementOptions"]) == 10
    assert vf["effectsSpec"][0]["value"] == pytest.approx(2.00)  # fixed, not scaled by Strength!
    assert vf["effectsSpec"][0]["forcedProc"] is True

    # 4. Wisp Critical Surge: 250% cap stays fixed at 2.50 while perMeterValue scales with Strength!
    wisp = engine.calculate({
        "frameId": _frame_by_en("Wisp")["id"],
        "normalMods": [
            {"path": blind_rage["path"], "rank": 10, "slot": 0},
            {"path": _mod_by_en("Critical Surge")["path"], "rank": 3, "slot": 1},
        ],
    })
    wisp_map = {a["id"]: a for a in wisp["weaponBridge"]["availableAbilities"]}
    assert "haste-mote" in wisp_map and "critical-surge" in wisp_map
    cs_fx = wisp_map["critical-surge"]["effectsSpec"][0]
    assert cs_fx["value"] == pytest.approx(2.50)
    assert cs_fx["perMeterValue"] == pytest.approx(0.10 * 1.99)

    # 5. Broad frame coverage across native weapon-synergy frames & POST_COALESCE augments.
    expected_frame_abilities = [
        ("Rhino", {"roar"}),
        ("Mirage", {"hall-of-mirrors", "eclipse"}),
        ("Xaku", {"xatas-whisper"}),
        ("Grendel", {"nourish"}),
        ("Saryn", {"toxic-lash"}),
        ("Cyte-09", {"resupply"}),
        ("Chroma", {"vex-armor"}),
        ("Mesa", {"shooting-gallery"}),
        ("Equinox", {"metamorphosis", "provoke"}),
        ("Valkyr", {"warcry"}),
        ("Kullervo", {"wrathful-advance"}),
        ("Harrow", {"penance", "covenant"}),
        ("Nova", {"molecular-prime"}),
        ("Narin", {"hakchum"}),
        ("Volt", {"volt-speed", "electric-shield"}),
        ("Gyre", {"cathode-grace"}),
        ("Temple", {"overdrive", "rippers-wail"}),
        ("Dagath", {"grave-spirit"}),
        ("Caliban", {"sentient-wrath", "fusion-strike"}),
        ("Sevagoth", {"reap"}),
        ("Jade", {"jade-judgments", "symphony-deathbringer", "ophanim-eyes"}),
        ("Oraxia", {"webbed-embrace", "silken-stride"}),
    ]
    for fname, expected_ids in expected_frame_abilities:
        f_res = engine.calculate({"frameId": _frame_by_en(fname)["id"]})
        got_ids = {a["id"] for a in f_res["weaponBridge"]["availableAbilities"]}
        assert expected_ids <= got_ids, f"{fname}: expected {expected_ids} <= {got_ids}"

    # Energized Munitions via Helminth + Shadow Haze / Biting Frost / Champion's Blessing / Teeming Virulence / Conductive Sphere.
    em_res = engine.calculate({
        "frameId": EXCALIBUR,
        "helminthReplacement": {"slot": 1, "abilityId": "/Lotus/Powersuits/PowersuitAbilities/HelminthEfficiencyAbility"},
    })
    em = next(a for a in em_res["weaponBridge"]["availableAbilities"] if a["id"] == "energized-munitions")
    assert em["effectsSpec"][0]["value"] == pytest.approx(-0.75)

    for fname, aug_name, aug_id in [
        ("Ember", "Fireball Frenzy", "fireball-frenzy"),
        ("Frost", "Freeze Force", "freeze-force"),
        ("Frost", "Biting Frost", "biting-frost"),
        ("Oberon", "Smite Infusion", "smite-infusion"),
        ("Saryn", "Venom Dose", "venom-dose"),
        ("Gyre", "Conductive Sphere", "conductive-sphere"),
        ("Sevagoth", "Shadow Haze", "shadow-haze"),
        ("Trinity", "Champion's Blessing", "champions-blessing"),
        ("Nidus", "Teeming Virulence", "teeming-virulence"),
    ]:
        aug_res = engine.calculate({
            "frameId": _frame_by_en(fname)["id"],
            "normalMods": [{"path": _mod_by_en(aug_name)["path"], "rank": 3, "slot": 0}],
        })
        aug_entry = next(a for a in aug_res["weaponBridge"]["availableAbilities"] if a["id"] == aug_id)
        assert aug_entry["isAugment"] is True
