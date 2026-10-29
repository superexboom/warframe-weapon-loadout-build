# Larkspur/Prime contact-death parent radial v5, 2026-10-29

Two exact contact-conditioned mode1 profiles are ready for root review/merge: Larkspur and Larkspur Prime. This new independent candidate replaces ONLY their withdrawn fixed-post-impact1s proposals. Do not merge old v3 pending sourcePayload or old mode-profile-patch drafts. Candidate: larkspur-contact-candidate-v5-final-verified.json. No production JSON or shared engines were edited.

## Result

Native direct840 remains intact. Each ordinary accepted victim contact terminates that projectile and produces one independent1600 parent radial (800Blast+800Radiation), radius9.6000004,falloff.60000002,source CC.25999999/.28,CD2.2,SC.34. Multishot scales physical projectile count once. No children, fixed one-second delay, or second expiry explosion is added. Raw unmodified per-projectile sum2440 becomes2466.25 in current model replay because existing1/32 per-type quantization turns mixed direct840 into866.25; radial800+800 stays1600. This pre-existing quantization is explicitly model-side, not a new native damage claim.

## Native lifecycle

Current EXEeec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d,Packages00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06. Full raw ancestry hashes in final candidate. Both selected heavy projectiles inherit WaveProjectile vtable1423ebeb0.

- AllowNormalContactBehavior maps Wave+1822 at serializer14013dcaa. DestroyOnStaticCollision maps+1824 at14013ddb0. They are not ExplodeOnImpact or a delay. Raw BounceOnAvatars0 also remains required.
- Ray collision callback141444690 invokes14077fbb0 before optional normal contact+5781401f16d0. At140780e28..0e3b, ExplodeOnImpact native getter140eca650 reads+16d0=0, bypassing direct radial emission. Ordinary avatar contact goes through140780f0a ->1407fef60; the unchanged positive-radius/+7c00 contact check returnsfalse (cannot pierce), then140780f23..0f2d invokes projectile+56814037e980 ->+5601405ac4a0 Die. The contact callback returnsfalse, so caller does not dispatch another normal contact afterward.
- Die checks+c1d at1405ac4da and stores+c1d1 at1405ac65c. Duplicate Die skips all subsequent death-property operations. c10 property flips at1405ac8ee; enabled native delegate installed by registration140e4e218..28b is1420af3d0+20 ->14012b2c0 ->140907fec ->projectile+768140163a60. That callback sees+c101, arming0,ExplodeOnImpact0/ExplodeOnLifeExpired0 and calls radial+7b8140f360f0 once.
- c250 is maintained because native Embed constructor0 has no raw override and contact selected the Die branch. Common+630 selector14160c689..6b2 therefore chooses ExplosiveAttack+5b4, not embedded+9c8. Radius selector14160c665..67c gives9.6000004*Projectile+810(default1).
- Wave actual virtual+780140f874b0 suffix140f88871..88981 checksMaxLife,c1d,timer639 then calls actual leaf140dd80d0 to calculate MaxLife1+variance0. Because ExplodeOnLifeExpired+16d6=0, it selects named Projectile::Die thunk140273d98 at140f88917..951 with delay1; it does NOT select DieOfOldAge1409a8700. Original scheduler capture confirms callback140273d98,delay1. This is launch lifetime, not post-impact delay. Contact followed by scheduled Die and repeated contact still emit one radial total. Earlier exploratory1415b6550/140acad40 belongs to another subclass path and is excluded from Wave evidence.

## Source brackets and crit

Constructor140fbadf9 installs enum253 WEAPON_DAMAGE_AMOUNT in Projectile+db0; descriptor140da0a9f maps DamageUpgradeTypes todb0; neither source chain overrides this array. Radial builder141234bbb..c2e consumes it. The scalar route141234a75->14116ac70 applies source context then141234a7a multiplies Projectile+7b8(default1 at ctor140fba8cb). Exact weapon source retains playerDamageMultiplier1,AttenuateForCharge0,AttenuateFireIterationsForCharge0,UseClipSizeAsDamageMultiplier0,DamageMultiplier1; changed routes reject. No 1600/840 ratio, weapon-name multiplier or doubled charge factor is introduced.

Corrected crit provenance ONLY in this new candidate: Projectile+538/+570 are CriticalChance/Multiplier, copied+combined by140ede780 called at140f36187..36198 AFTER selected radial builder. The generic legacy note calling plan+118/+11c crit is incorrect and NOT used here. Root owns generic metadata correction.

## Verification

verify_larkspur_lifecycle_native.py:5 stateful original-byte trajectories plus actual lifetime-scheduler suffix and selector/radius cases. Contact produces1deathCallback/1radial; contact->expiry remains1;contact->expiry->contact remains1;expiry-alone1;second-expiry remains1. Actual c1d guard/store,c10 property branch,native delegate thunks,death callback and Wave actual virtual780 timer selection run. Scheduling storage,world collision/aim,owner/position serialization,unrelated FX/logging and radial world delivery are controlled/skipped. Radial callback is counted before external delivery.

23 dedicated tests +35 generic secondary-payload tests =58 passed. Dedicated12 actual prepare/replay cases cover2weapons*MS1/2/3*Python/native execution with no crit/status at default Scenario(distance=None), plus independent native values, semantic drift rejection, source damage factor+100% gives direct1680/radial3200 and preservation of unrelated modes/charge. Existing charge/cadence is not replaced: candidate nativeCharge preserves its source evidence separately.

## Admission limits

Ready only under existing single-target contact geometry: every selected projectile reaches its victim before launch expiry and victim is at explosion centre. impact_delay_seconds0 denotes that contact time, with launch flight omitted exactly like other admitted ordinary-contact projectiles. It does NOT promise a hit beyond100m, through obstacles or with arbitrarily changed flight speed. Current engine has no reachability gate; candidate explicitly diagnoses contact/flight geometry, maxlife launch-expiry recipient exclusion and speed/obstacle/out-of-range assumptions. If root requires real distance-based flight reachability rather than existing idealized contact scope, retain this candidate pending that engine interface; do not relabel lifetime1 as a delay. Empty-space expiry recipient overlap is not imported. Dynamic source snapshots,CO,weakpoint/Arcane notification remain bounded by existing explicit neutral diagnostics.

## Root merge

```powershell
python -m tools.import_larkspur_contact_radial --packages-bin C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Debug/Packages.bin_H --client-exe C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Warframe.x64.exe --output .local/delivery/ranged-implementation-20261029/native-payloads/larkspur-contact-root-refresh.json
python -m pytest tests/test_larkspur_contact_radial_20261029.py tests/test_native_secondary_payloads_20261029.py -q
python .local/delivery/ranged-implementation-20261029/native-payloads/verify_larkspur_lifecycle_native.py
```

Use existing tools.import_native_secondary_payloads.merge_patch(payload,patch) against final candidate, then preserve_lines and write in root's coordinated production window. Merge includes exactly2weapons/mode1. New files tools/import_larkspur_contact_radial.py,tests/test_larkspur_contact_radial_20261029.py and this case evidence only. No shared engine/data changes,bake,commit,push.
