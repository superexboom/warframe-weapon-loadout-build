# Sniper combo and scope audit (2026-10-04)

## Problem

The local engine had no Shot Combo Counter and no scope bonus. Rubico Prime
against Thrax Centurion (Steel Path, body shots, no arcanes) scored well under
WFSim, and its panel crit damage was missing the scope's +50%.

## Data and provenance

`data/export/*/weapons.json` has no combo minimum, combo decay period or zoom
bonus. `tools/import_sniper_profiles.py` reads them from WFSim weapon YAML
(`sniper_combo`, `scope`) into `data/mechanics/sniper-profiles.json`. The file
records the WFSim commit (`7399c9e4`), and each row records its source YAML
and SHA-256. Rows are keyed by the native weapon path, and that path must exist
in the export. Two WFSim forms of one native weapon (`lanka`,
`lanka_uncharged`) must agree, otherwise the import fails. Incarnon forms carry
neither mechanic.

## Semantics (`vendor/wfarsenal/sniper_combo.py`)

- Multiplier ladder: 1.0 below `min`, then `1.5 + 0.5k` at `min * 3^k` hits,
  with no cap.
- Each landing direct pellet reads the counter, then adds one. The counter
  loses one per `seconds` (2 s, Lanka 6 s) without a hit; it does not reset.
  A pull that lands nothing empties it. Expected multishot is tracked as a
  distribution over integer counts.
- The factor multiplies the shot's final direct and radial damage. Status
  payloads (DoT seeds) do not take it, as in WFSim, which leaves
  `InstanceScale` without the combo. WFSim's Heat DoT ratio between ADS and
  hip fire is 1.19 (the scope alone), while its direct damage rises 3.2x.
- Scope bonuses, in `apply_mods`: crit multiplier, crit chance and headshot
  damage join their ordinary buckets as `STACKING_MULTIPLY` terms. The Lanka's
  bonus is flat crit chance added after mods.
- Both mechanics apply only when `scenario.aiming` is true and only on the base
  form. WFSim gates them the same way, but its API defaults to `aiming: true`,
  while the local `Scenario` defaults to `false`.
- One path serves all modes: `manual_combat.prepare` sets `sniperCombo` and
  `combat_replay.replay` applies it. Manual simulation, optimizer scoring
  (`search_combat.window`) and Riven scoring all go through that path.

## Validation

Command: `tools/audit_sniper_combo.py`. Evidence:
`docs/evidence/sniper-combo-20261004/`. The comparison used WFSim's own
`webapi::route` at the pinned commit, built natively (see `native-driver/`),
with 400 runs, seed 12648430, a 30 s window and Thrax Centurion on Steel Path.
Body shots, no arcanes, and the same crit build on every weapon. Vectis Prime
pins its Incarnon route (Lone Enforcer, Marksman's Hand, Critical Parallel) on
both sides. All panels match.

| Case | Before (KPM) | After (KPM) | WFSim (KPM) | Delta |
|---|---|---|---|---|
| Rubico Prime L9999 ADS | 0.1142 | 0.3688 | 0.3696 | -0.20% |
| Vectis Prime L9999 ADS | 0.2373 | 0.4820 | 0.4798 | +0.46% |
| Lanka L9999 ADS | 0.0462 | 0.1481 | 0.1480 | +0.06% |
| Vulkar Wraith L9999 ADS | 0.0542 | 0.1295 | 0.1292 | +0.24% |
| Rubico Prime L170 ADS | 0.9533 | 2.5579 | 2.5759 | -0.70% |
| Vectis Prime L170 ADS | 2.0825 | 3.6840 | 3.7622 | -2.08% |
| Lanka L170 ADS | 0.5457 | 1.0578 | 1.0116 | +4.56% |
| Vulkar Wraith L170 ADS | 0.6237 | 1.1130 | 1.1004 | +1.14% |
| Rubico Prime L9999 hip | 0.1142 | 0.1142 | 0.1145 | -0.24% |

## Known gaps, not part of this change

- **Lanka L170.** The +4.6% shows up only after the 395k overguard breaks
  (5 s: -0.2%, 10 s: +0.8%, 20 s: +3.6%). Hip fire drifts the same way
  (+3.0% at 20 s). It comes from the expected-value replay's pool transition:
  14 large shots make the boundary shot a large share of the total.
- **Rubico Prime with Heat.** Hip fire alone is already +9.4% at L9999 and
  +5.0% at L170.
- **Perigale Prime.** The local engine has no burst cadence profile for it
  (48 local shots against 96 in WFSim), so it was left out.
- **Harkonar Scope.** `WEAPON_SNIPER_COMBO_DURATION_BONUS` (+2 s per rank,
  aim-gated) is still unsupported.
- **Misses.** Neither engine models a miss here, so every pellet lands.
