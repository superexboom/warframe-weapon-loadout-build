"""Client-verified Squad & External Buffs resolver for Warframes, Abilities & Arena.

Bridges ``externalBuffs`` entries into:
1. ``WarframeEngine.calculate`` — additive Ability Strength first, followed by
   Nidus ``Parasitic Link`` total multiplicative Ability Strength ``(1 + 0.25 * S)``,
   plus Vitality Mote flat Health, Squad Energy Siphon, Squad Brief Respite, and
   Brightbonnet (+ Arbucep 200%) non-recursive Strength & channel-bypassing Energy/s.
2. ``ability_nuke`` & ``arena`` — Rhino ``Roar`` universal ability multiplier
   (1x direct, ``(1 + Roar)^2`` double-dip on ability DoTs), Nova U37 ``Molecular Prime``
   (Tap=Slow / Hold=Speed ``+75%`` + ``2.0x`` universal vulnerability + ``+15%`` orb drop),
   Dante ``Pageflight`` status chance & status damage vulnerability, Sevagoth ``Reap``,
   Oraxia ``Webbed Embrace``, Caliban ``Sentient Wrath``, Jade ``Light's Judgment``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def _clamp_num(val: Any, default: float, low: float, high: float) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
        return default
    return max(low, min(high, float(val)))


def _clamp_int(val: Any, default: int, low: int, high: int) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
        return default
    return max(low, min(high, int(round(float(val)))))


def evaluate_warframe_squad_buffs(
    entries: Sequence[Mapping[str, Any]] | None,
    *,
    exclude_self_ability_ids: set[str] | None = None,
    exclude_self_aura_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate externalBuffs impact on Warframe panel, energy economy, and ability nukes."""
    out: dict[str, Any] = {
        "additiveStrength": 0.0,
        "parasiticLinkMultiplier": 1.0,
        "parasiticLinkStrength": 0.0,
        "flatHealthAdd": 0.0,
        "healthRegenPerSec": 0.0,
        "shieldRechargeRateAdd": 0.0,
        "shieldRechargeDelayAdd": 0.0,
        "energySiphonPerSec": 0.0,
        "briefRespiteRatioAdd": 0.0,
        "nourishEnergyMultiplier": 1.0,
        "brightbonnetEnergyPerSec": 0.0,
        "brightbonnetPulseEnergy": 0.0,
        "brightbonnetPulseIntervalSec": 0.0,
        "brightbonnetCount": 0,
        "brightbonnetEmpowered": False,
        "triggersArchonStretch": False,
        "roarBonus": 0.0,
        "abilityVulnerabilityMultiplier": 1.0,
        "abilityStatusChanceVulnerability": 0.0,
        "abilityStatusDamageVulnerability": 0.0,
        "enemySpeedDelta": 0.0,
        "killEnergyOrbBonusChance": 0.0,
        "killHealthOrbBonusChance": 0.0,
        "auraArmorReduction": 0.0,
        "auraShieldReduction": 0.0,
        "summaryPills": [],
    }
    if not isinstance(entries, (list, tuple)) or not entries:
        return out

    skip_ab = exclude_self_ability_ids or set()
    drift = 0.0
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for raw in entries[:96]:
        if not isinstance(raw, Mapping):
            continue
        bid = str(raw.get("id") or "").strip()
        if not bid or bid in seen_ids:
            continue
        seen_ids.add(bid)
        if bid == "coaction-drift":
            if raw.get("value") is not None:
                drift = _clamp_num(raw.get("value"), 0.15, 0.0, 0.3225)
            else:
                drift = 0.15
            continue
        normalized.append(dict(raw, id=bid))

    aura_mult = 1.0 + drift

    # Family deduplication for overlapping ability buffs
    roar_best = 0.0
    provoke_best = 0.0
    bb_best_str_add = 0.0
    bb_best_eps = 0.0
    bb_best_pulse = 0.0
    bb_best_interval = 0.0
    bb_best_cnt = 0
    bb_best_emp = False
    nourish_best_mult = 1.0
    vuln_bonuses: list[float] = []

    for item in normalized:
        bid = item["id"]
        s = _clamp_num(item.get("strength"), 1.0, 0.0, 10.0)
        cnt = _clamp_int(item.get("count"), 1, 1, 6)
        explicit_val = _clamp_num(item.get("value"), -1.0, 0.0, 50.0) if item.get("value") is not None else None

        if bid == "parasitic-link" and bid not in skip_ab:
            s_nidus = _clamp_num(item.get("strength"), 3.0, 0.0, 10.0)
            bonus = explicit_val if explicit_val is not None else (0.25 * s_nidus)
            mult = max(1.0, 1.0 + bonus)
            if mult > out["parasiticLinkMultiplier"]:
                out["parasiticLinkMultiplier"] = round(mult, 6)
                out["parasiticLinkStrength"] = round(s_nidus, 4)
                out["summaryPills"].append(f"寄生链接 ×{mult:.2f}总强度")

        elif bid in {"provoke", "peaceful-provocation"} and bid not in skip_ab:
            s_eq = _clamp_num(item.get("strength"), 2.5, 0.0, 10.0)
            if bid == "peaceful-provocation":
                add_s = min(0.80, explicit_val if explicit_val is not None else 0.35 * s_eq)
            else:
                add_s = min(0.50, explicit_val if explicit_val is not None else 0.20 * s_eq)
            provoke_best = max(provoke_best, add_s)

        elif bid == "jade-power-of-seven" and bid not in skip_ab:
            s_jade = _clamp_num(item.get("strength"), 3.0, 0.0, 10.0)
            add_s = min(1.50, explicit_val if explicit_val is not None else 0.25 * s_jade)
            out["additiveStrength"] += add_s
            out["summaryPills"].append(f"七人众之力 +{round(add_s * 100):g}%强度")

        elif bid == "jade-spirit-of-resilience" and bid not in skip_ab:
            s_jade = _clamp_num(item.get("strength"), 3.0, 0.0, 10.0)
            out["shieldRechargeRateAdd"] += 0.10 * s_jade
            out["shieldRechargeDelayAdd"] -= min(0.80, 0.10 * s_jade)

        elif bid in {"brightbonnet-squad", "brightbonnet-helminth"} and bid not in skip_ab:
            is_helm = bid == "brightbonnet-helminth" or bool(item.get("helminth"))
            emp = bool(item.get("arbucepEmpowered", True if item.get("empowered") else False))
            shrooms = _clamp_int(item.get("count"), 2 if emp else 1, 1, 2)
            s_caster = _clamp_num(item.get("strength"), 3.0, 0.0, 10.0)
            base_coeff = (0.20 if is_helm else 0.30) * (2.0 if emp else 1.0)
            cap_val = (1.00 if is_helm else 1.50) * (2.0 if emp else 1.0)
            str_add = min(cap_val, explicit_val if explicit_val is not None else (base_coeff * s_caster))
            pulse_e = (10.0 if is_helm else 15.0) * s_caster
            interval = (100.0 / 75.0) if emp else (100.0 / 35.0)
            eps = shrooms * pulse_e / interval
            if str_add > bb_best_str_add or eps > bb_best_eps:
                bb_best_str_add = max(bb_best_str_add, str_add)
                bb_best_eps = max(bb_best_eps, eps)
                bb_best_pulse = pulse_e
                bb_best_interval = interval
                bb_best_cnt = shrooms
                bb_best_emp = emp

        elif bid == "growing-power":
            k = min(4, cnt)
            if exclude_self_aura_id == "growing-power":
                k = max(0, k - 1)
            if k > 0:
                add_s = 0.25 * k * aura_mult
                out["additiveStrength"] += add_s
                out["summaryPills"].append(f"成长之力×{k} +{round(add_s * 100, 1):g}%强度")

        elif bid == "power-donation":
            k = min(3, cnt)
            add_s = 0.30 * k * aura_mult
            out["additiveStrength"] += add_s
            out["summaryPills"].append(f"献出力量×{k} +{round(add_s * 100, 1):g}%强度")

        elif bid == "energy-siphon":
            k = min(4, cnt)
            if exclude_self_aura_id == "energy-siphon":
                k = max(0, k - 1)
            if k > 0:
                eps = 0.60 * k * aura_mult
                out["energySiphonPerSec"] += eps
                out["summaryPills"].append(f"能量虹吸×{k} +{eps:.2f}能量/s")

        elif bid == "brief-respite":
            k = min(4, cnt)
            if exclude_self_aura_id == "brief-respite":
                k = max(0, k - 1)
            if k > 0:
                br = 1.50 * k * aura_mult
                out["briefRespiteRatioAdd"] += br
                out["summaryPills"].append(f"快速休整×{k} +{round(br * 100):g}%转盾")

        elif bid == "corrosive-projection":
            k = min(4, cnt)
            out["auraArmorReduction"] = min(1.0, out["auraArmorReduction"] + 0.18 * k * aura_mult)

        elif bid == "shield-disruption":
            k = min(4, cnt)
            out["auraShieldReduction"] = min(1.0, out["auraShieldReduction"] + 0.18 * k * aura_mult)

        elif bid == "vitality-mote" and bid not in skip_ab:
            s_wisp = _clamp_num(item.get("strength"), 2.5, 0.0, 10.0)
            hp_add = explicit_val if explicit_val is not None else (300.0 * s_wisp)
            out["flatHealthAdd"] += hp_add
            out["healthRegenPerSec"] += 30.0 * s_wisp
            out["summaryPills"].append(f"活力储能池 +{int(round(hp_add))}生命")

        elif bid == "shock-mote":
            out["triggersArchonStretch"] = True

        elif bid in {"roar", "roar-helminth"} and "roar" not in skip_ab:
            base_r = 0.30 if bid == "roar-helminth" else 0.50
            r_val = explicit_val if explicit_val is not None else (base_r * s)
            roar_best = max(roar_best, r_val)

        elif bid in {"nourish", "nourish-helminth"} and "nourish" not in skip_ab:
            e_base = 0.60 if bid == "nourish-helminth" else 1.00
            nourish_best_mult = max(nourish_best_mult, 1.0 + e_base * s)

        elif bid == "molecular-prime":
            vuln_bonuses.append(1.0)
            variant = str(item.get("variant") or "hold").strip().casefold()
            s_nova = _clamp_num(item.get("casterStrength", item.get("strength")), 1.5, 0.1, 10.0)
            mag = min(0.75, 0.50 * s_nova)
            if variant == "hold":
                out["enemySpeedDelta"] = mag
                out["killEnergyOrbBonusChance"] = max(out["killEnergyOrbBonusChance"], 0.15)
                out["summaryPills"].append(f"分子填充(加速+{round(mag * 100):g}% / ×2易伤)")
            elif variant == "tap":
                out["enemySpeedDelta"] = -mag
                out["killHealthOrbBonusChance"] = max(out["killHealthOrbBonusChance"], 0.15)
                out["summaryPills"].append(f"分子填充(减速-{round(mag * 100):g}% / ×2易伤)")
            else:
                out["summaryPills"].append("分子填充 ×2易伤")

        elif bid == "dante-pageflight":
            s_dante = _clamp_num(item.get("strength"), 2.5, 0.0, 10.0)
            val = explicit_val if explicit_val is not None else (0.50 * s_dante)
            out["abilityStatusChanceVulnerability"] += val
            out["abilityStatusDamageVulnerability"] += val
            out["summaryPills"].append(f"书页飞羽 +{round(val * 100):g}%异常几率/异常伤")

        elif bid == "sevagoth-reap":
            val = explicit_val if explicit_val is not None else (0.50 * s)
            vuln_bonuses.append(val)
            out["summaryPills"].append(f"收割易伤 +{round(val * 100):g}%")

        elif bid == "webbed-embrace":
            val = explicit_val if explicit_val is not None else (0.50 * s)
            vuln_bonuses.append(val)
            out["summaryPills"].append(f"网缚易伤 +{round(val * 100):g}%")

        elif bid == "sentient-wrath":
            val = explicit_val if explicit_val is not None else (0.35 * s)
            vuln_bonuses.append(val)
            out["summaryPills"].append(f"Sentient之怒 +{round(val * 100):g}%易伤")

        elif bid == "jade-judgments":
            vuln_bonuses.append(0.50)
            out["summaryPills"].append("圣光审判 +50%易伤")

    if provoke_best > 0.0:
        out["additiveStrength"] += provoke_best
        out["summaryPills"].append(f"激怒 +{round(provoke_best * 100, 1):g}%强度")

    if bb_best_str_add > 0.0 or bb_best_eps > 0.0:
        out["additiveStrength"] += bb_best_str_add
        out["brightbonnetEnergyPerSec"] = round(bb_best_eps, 4)
        out["brightbonnetPulseEnergy"] = round(bb_best_pulse, 4)
        out["brightbonnetPulseIntervalSec"] = round(bb_best_interval, 6)
        out["brightbonnetCount"] = bb_best_cnt
        out["brightbonnetEmpowered"] = bb_best_emp
        emp_tag = "+蕈菇强化" if bb_best_emp else ""
        out["summaryPills"].append(f"亮帽菇{emp_tag} +{round(bb_best_str_add * 100):g}%强度 / +{bb_best_eps:.1f}蓝/s")

    if roar_best > 0.0:
        out["roarBonus"] = round(roar_best, 6)
        out["summaryPills"].append(f"战吼 +{round(roar_best * 100):g}%全伤(DoT二次乘算)")

    if nourish_best_mult > 1.0:
        out["nourishEnergyMultiplier"] = round(nourish_best_mult, 6)
        out["summaryPills"].append(f"滋养 ×{nourish_best_mult:.2f}回蓝倍率")

    if vuln_bonuses:
        # Distinct vulnerability debuffs stack additively in the victim damage-taken bracket in Warframe,
        # except Molecular Prime which multiplies damage taken independently (2.0x).
        mp_mult = 2.0 if any(item["id"] == "molecular-prime" for item in normalized) else 1.0
        other_sum = sum(v for v in vuln_bonuses) - (1.0 if mp_mult > 1.0 else 0.0)
        out["abilityVulnerabilityMultiplier"] = round(mp_mult * (1.0 + max(0.0, other_sum)), 6)

    out["additiveStrength"] = round(out["additiveStrength"], 6)
    out["flatHealthAdd"] = round(out["flatHealthAdd"], 4)
    out["healthRegenPerSec"] = round(out["healthRegenPerSec"], 4)
    out["energySiphonPerSec"] = round(out["energySiphonPerSec"], 4)
    out["briefRespiteRatioAdd"] = round(out["briefRespiteRatioAdd"], 4)
    out["abilityStatusChanceVulnerability"] = round(out["abilityStatusChanceVulnerability"], 6)
    out["abilityStatusDamageVulnerability"] = round(out["abilityStatusDamageVulnerability"], 6)
    return out


__all__ = ["evaluate_warframe_squad_buffs"]
