# Arbucep independent review — three reproduced score/event bugs

Review scope: current uncommitted physical lane implementation, read-only shared production files. Baseline28Arbucep tests pass. No production shared engine/data file was edited by this review. Actual owned changes: projectile_lanes.py new merge_life_curves helper, tests/test_arbucep_review_regressions.py8new regressions. Shared fixes are isolated under review-fixed/ and packaged in arbucep-review-fixes.patch. `git apply --check` passed against reviewed shared state (SHA manifest arbucep-review-shared-input-sha256.json). Parent may apply at its integration boundary and rebuild normal native core.

## P1 — fractional trajectories append16life curves into one mutable list

combat_replay.replay's16trajectory wrapper passes the same options.life_curve to all runs. body_ttk_health in search_combat.py sums this list to derive TTK health thresholds; the bug therefore affects optimizer/calibration, not merely diagnostic presentation. Reproduction one pull total6.5, crit/status0: result.totalWindowDamage1690 but shared curve sum27040 (16x). Integer6 is1560 in both. Fractional branch trajectories have208raw events versus12for integer.

Fix: each branch owns a new list. Merge cumulative branch damage into mean at each timestamp; total variance is E(within-branch cumulative variance)+Var(branch cumulative damage). Return increments of those cumulative quantities. Averaging only per-packet variances would incorrectly discard uncertainty of projectile count and phase. New helper merge_life_curves has deterministic one-pull and converging-phase covariance tests. For count6.5 one-pull neutral result/curve mean1690 and variance16900.

## P1 — victimProcTypesBeforeHit remains the first packet's snapshot for all lanes

Python updates combat.victimProcTypesBeforeHit once before pull; Rust updates self.victim_before once. Six forced-Cold contacts at one timestamp: procCounts.DT_FREEZE6 but a Cold-gated on-hit trigger stays0 instead of5. Reproduced in Python and actual native trajectory (`nativeRuns=1`), not just parity/fallback. The first hit cannot gate on Cold it just applied; later five contacts must see previous packets' Cold.

Fix: refresh target status presence before each actual lane contact and before its independent radial packet, preserving on-hit/kill gate source. Do not reuse the pull-opening snapshot; do not let the direct proc qualify that same direct hit retroactively. Generation guard remains before model/refresh for every lane; direct killing still suppresses that projectile's blast and all remaining same-pull packet deliveries.

## P1 — native health batch bypasses fractional whole-trajectory branching

search_combat.windows builds combat and calls native_replay.trajectory(...health_targets=...) directly. Fractional16branch wrapper lives in combat_replay.replay, so this path uses only default stratum.5 and emits no fractional approximation diagnostic. Neutral6.5 one-pull scalar1690 versus health batch1560 reproduced. This can make optimizer and manual scalar scores disagree.

Fix: native supported() rejects unstratified fractional physical lane configs; native trajectory(...health_targets=...) independently returnsNone in the same case. Existing windows fallback then requests scalar replay, which supplies16strata and diagnostics. An already-stratified config remains native-eligible. Integer count keeps native health batching. Dynamic multishot also requires scalar branching per existing fractionalProjectileLanes flag.

## Performance and state review

Small warm5s unkillable-target benchmark,4runs each (host/tool timing, not whole optimizer claim): Python integer6~4.6–4.8ms/run; fractional6.5~80–83ms; native integer6~1.7–2.3ms; fractional6.5~14.7–16.8ms. The explicit16trajectory design has real9–17xcost here. It remains bounded and labeled approximate; this review did not silently replace phase distribution by uniform averaged elements.

Current sources initialize new trigger records per replay; combat branch dictionaries carry independent scalar ephemeral flags. Resolver cache keys include per-lane index and relevant stack/live status state. Actual generation guards discard same-pull remainder while advancing full emitted count; existing kill/reload/on-fire tests pass. New life-curve lists remove the demonstrated shared mutable output state. This is not a proof that every arbitrary external custom resolver is pure.

## Native source identity

Re-extracted hash-pinned original package through current importer and confirmed structural equality with arbucep-projectile-lanes-patch.json. Exact path /Lotus/Weapons/Tenno/Archwing/Primary/NokkoArchGun/NokkoArchGun; slotarch_gun; bankHeavyBehaviors; modeCount1/modeindex0/baseMS6. Six distinct lane packet elements,32direct/228radial, own rawSC2.0940001/base6 retained. SHA/field gates pass; evidence arbucep-review-source-identity.json. Source assertions do not establish full game calibration or unresolved innate/geometry/CO/weakpoint consumer behavior.

## Verification and integration

- Existing production implementation28focused passed before review fixes.
- Independent stage Python/native release build succeeded (two pre-existing unused warnings).
- Isolated reviewed implementation36focused passed:28existing+8new, native regressions enabled via WF_ARBUCEP_REVIEW_NATIVE=1.
- git apply --check .local/delivery/ranged-implementation-20261029/native-payloads/arbucep-review-fixes.patch passed.
- Shared files to apply: combat_replay.py, native_replay.py, native/wfcore/src/replay.rs. Owned projectile_lanes.py helper and new tests already in workspace. Stage DLL installed only inside review-fixed/vendor; normal vendor/wfarsenal/wfcore.pyd unchanged by this review.
- No fullsuite, commit, cache bake, or production data mutation.

Model setting: this environment exposes no model-settings read/switch capability; cannot independently attest requested gpt-6.1-sol/high. No model override was attempted.
