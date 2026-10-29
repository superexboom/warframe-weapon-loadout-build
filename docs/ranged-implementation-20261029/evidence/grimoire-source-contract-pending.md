# Grimoire alternate native contract, 2026-10-29

No production admission. This pass closes native chain timer/dedup and expiry producer roles, and proves that a fixed hit-relative6s radial is wrong. New evidence extractor tools/import_grimoire_static_contract.py writes weapons={} plus1pending evidence record. It cannot add250/280 to default scoring through existing merge_patch. Source artifact grimoire-static-contract-v1.json is NOT a combat-reference patch.

## Exact sources and roles

EXEeec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d;Packages00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06. Weapon TnGrimoire ->LotusGrimoire ->LotusPistol. Alt projectile TnGrimoireAltProj ->nativePlayerChainingProjectile. Full source hashes are regenerated from raw original package. Native class vtable1423910d0.

Three distinct payloads/roles:

- AttackData350Electricity,SC.25999999,forcedElectrocution is selected by normal contact and by periodic chaining builder. It is not the250 death packet.
- Periodic chain selected-recipient packet is copied from AttackData via projectile+628 at140d7fdb4..fde8, then141693108..3123 unconditionally multiplies copied amount by native ChainDamageMultiplier.80000001, producing about280 before other source brackets. This scalar is not recursive .8^depth in the inspected loop: each recursive call receives the original packet at14169332a..33a. No guarantee that a modelled target is selected at every interval is implied.
- ExplosiveAttack250Electricity,SC.25999999,CC.2/CD2,radius6/falloff.80000001 is only the launch-expiry source here; ExplodeOnImpact has native constructor0/no override. Source ExplodeOnLifeExpired1,MaxLife6,variance constructor0.

Correct crit provenance is Projectile+538/+570 copied+combined by140ede780 after radial selector. plan118/11c are not crit.

## One orb; multishot changes chain budgets

Raw alt fire IgnoreFireIterations1,fireIterations1. Original complete140f75d20 returns raw+281 through its148=1 branch without reading weapon multishot. This is1orb, not one extra orb per multishot.

Periodic updater140d7fc60 independently queries weapon+6e0 using MaxTargetsPerAttack+1758(raw3) at140d7fd38..da0, storing1750; MaxChainDepth+1718(raw2) at140d7ff87..d80086, storing1720 with fractional rounding. Multiplying entire orb contact/expiry damage by ordinary multishot would misroute this native declaration. Existing pending secondary sourcePayloads that say takes_multishot=true must stay excluded.

## Per-attack dedup and repeated attacks

TimeBetweenAttacks1 serializer140161da6 maps Projectile+1770. Remaining cooldown is1774. Native140d7fcb7..fd06 decrements1774 and skips new-attack work while positive. New attack then calls1401bc7d0 on1798 at140d7fd14..33, releasing all old selected-target handles and zeroing list.

Candidate filter140cccf60 at140ccd260..d32d removes a target already present in1798. Loop1416932a8..2db appends each selected target before recursive14169333a, preventing that target from being selected again in the same attack tree. The list resets at the next attack, so same target can be selected again on a later1s attack. That is not a once-per-projectile hit restriction. Cooldown is armed at141693034..305c using1770+existing remaining.

MaxTargetsPerAttack3,MaxChainDepth2,MaxArcs2,DirectHitChainLength8,ArcLength8 are exact declarations. They do not prove3*2*280 hits on a single victim; target list and spatial selection remain required. Chain producer141693283 calls140907cb0, which uses packet target weakref+170 and source/avatar role to select authoritative target+340 or local+348. Separate140cc8cd0 manages current chain visual/slot refs; it is not the damage producer.

Normal contact direct350 recontact gates remain separate: class+578 binds1410e2120,which uses own b58/b60 prior-hit arrays and class+750140e7ad20 clears those. StopOnAvatars0 and BounceOnAvatars0 are source declarations, not a complete proof of all callback acceptance/clearing/reset conditions. This pass does not admit an unconditional repeat-contact count or equate direct contact with chain pulse.

## Actual six-second launch expiry and one-shot scope

PlayerChainingProjectile actual+780 remains140f874b0. At140f88871..88981 MaxLife6,positive lifetime enabled6d8,noDiec1d,and timer639=0 reach140dd80d0, which computes MaxLife+variance. With16d6=1, actual branch140f888a9..88901 chooses named Projectile::DieOfOldAge callback1409a8700, delay6. It stores6391; another execution of launch suffix schedules nothing. This is launch time, NOT6s after first victim contact.

Class Die+5601413556f0 cleans active chain effects then invokes common1405ac4a0. Die+c1d blocks duplicate death-property callbacks. Death callback140163a60 sees16d61/c250 and skips its own radial. DieOfOldAge then explicitly invokes+7b8140f360f0 at1409a8785. Common630/638 selects normal ExplosiveAttack250.

Crucial counterfactual: manually invoking DieOfOldAge TWICE yields TWO radial callbacks, although death-property callback only ran once. Expiry producer itself has no once flag. Once-per-lifecycle scheduling is639 gate and external timer/lifecycle semantics, not the Die guard. Do not cite Die guard as preventing a second expiry explosion. Actual ordinary scheduling was captured once; external queue cancellation/early-destruction behavior is not emulated.

## Why production admission stays pending

The current engine has hit-relative delayed radial events bound to victim generations. Grimoire needs one orb launch clock, moving/reflecting position, periodic1s chain attack clock, per-attack target tree dedup, and expiry recipient overlap at final position. At launch speed6 and lifetime6 the endpoint need not remain within6m of an earlier victim; source post-collision speed.25,restitution.5,minspeed1.75 and other geometry alter it. Even after normal contact,250 cannot be unconditionally scheduled6s later on that host. It also cannot be treated as immediate ordinary contact explosion.

Explicit blockers: final expiry centre/recipient overlap; full direct350 prior-hit/recontact acceptance; native chain target selection/overlap over travel; source-buff/CO/event behavior for repeated chain280; single-orbMS queries to budgets rather than scalar multishot. Source script body TnGrimoire hash95f37dff... and private method bindings are captured, but UpdateAltProjectile P3 retains one unknown raw0 backedge; no complete script semantics are asserted.

## Delivered and verified

- tools/import_grimoire_static_contract.py,tests/test_grimoire_static_contract_20261029.py.
- grimoire-static-contract-v1.json:hash-gated exact source contract,0admitted,1pending.
- verify_grimoire_native_contract.py,grimoire-native-contract-results.json:17 original-byte cases.5cooldown values,3arming states,2dedup states,actual next-attack list clearing,2chain scalar values,single-orb count,actual expiry schedule-once,actual expiry emission,duplicate-expiry counterfactual. World selection and numerical query results are supplied inputs; no live-game measurement.
-18 focused tests pass,including pending never merges,source/clock/packet/orb-count mutation rejection. No shared engine,data,build,bake,commit or push. Root fullsuite freeze unaffected.

```powershell
python -m tools.import_grimoire_static_contract --packages-bin C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Debug/Packages.bin_H --client-exe C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Warframe.x64.exe --output .local/delivery/ranged-implementation-20261029/native-payloads/grimoire-root-refresh.json
python .local/delivery/ranged-implementation-20261029/native-payloads/verify_grimoire_native_contract.py
python -m pytest tests/test_grimoire_static_contract_20261029.py -q
```
