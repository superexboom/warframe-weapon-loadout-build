本文件保留来源审计时的模型快照；当前落地状态与后续工作见 [PLAN.md](PLAN.md)。

# Projectile family qualification inventory, 2026-10-30

Read-only core/data/tests audit. No test file or acceptance harness was created. Existing `tools/audit_ranged_calibration.py` ran successfully; extraction used existing `AuditedPackages` in interactive Python. The outputs are research evidence, not production data.

## Identity and coverage

- Package: `C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Debug/Packages.bin_H`, SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06` verified by AuditedPackages gate.
- Referenced native client: SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d` (no new EXE consumer trace in this subtask).
- `source-inventory.json`: 80 resource identities, each raw attribute SHA256, own fields, resolved inheritance and parent; original source bytes are preserved unchanged. Engine types with no serialized attributes do not establish C++ default values.
- `child-flags-comparison.json`: seven child records with own ancestry and resolved fields, covers four production cluster families plus Phantasma ordinary/MS and Zymos.
- `model-inventory.json`: existing all-ranged inventory. 399 records / 607 explicit modes / 600 evaluable / 0 preparation errors; 571 evaluable modes show no warning. No-warning does not establish calibration. Counts are baseline before parallel production changes.
- `candidate-modes.json`: compact filtered live model rows, all explicit modes of the requested families. Inventory source commit/input identity is retained in the full report.

## 1. Phantasma versus Zymos: ordinary child, MS child and scripted child are different

Weapon `/Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/RevenantShotgun`, mode1; Prime `/Lotus/Weapons/Tenno/LongGuns/PrimePhantasma/PhantasmaPrimeShotgun`, mode1.

| Resource under RevenantShotgun | Parent | Direct / explosive declaration | Child selector / count | Notice declaration |
|---|---|---|---|---|
| AltFireClusterProj | /Lotus/Types/Game/ClusterBombProjectile | 15 impact / 73 radiation | AltFireClusterMiniProj / NumClusterProjectiles absent | SendEvents absent |
| AltFireClusterProjMS | AltFireClusterProj | 15 impact / 73 radiation | AltFireClusterMiniProjMS / 2 | SendEvents absent |
| AltFireClusterMiniProj | /EE/Types/Engine/GuidedProjectile | 3 impact / 18 radiation | no child | SendEvents=0 |
| AltFireClusterMiniProjMS | AltFireClusterMiniProj | 6 impact / 36 radiation | no child | SendEvents=0 |

The Prime counterparts inherit corresponding non-Prime resources and select `PrimeAltFireClusterMiniProj`/`PrimeAltFireClusterMiniProjMS`. The fire behavior explicitly selects the MS carrier via MultiShotProjectileType. Carrier `ClusterApplyDamageMultiplier=1`; main carrier AttackData and ExplosiveAttack declare DHT_PROJECTILE, while embedded death declares DHT_RADIAL. Mini children have no serialized HitType; missing is not a confirmed enum default. Minis declare radius2, MaxLife2.9000001, ExplodeOnImpact=1 and ExplodeOnLifeExpired=1. Main declares radius4.8000002, ExplodeOnImpact=1, MaxLife5 and DealDamageThroughImpactBehavior=1.

Current registry admits main 73 radial only, explicitly warns child payload unmodeled. This avoids fabricating full child overlap. A naive five-child total times weapon MS would ignore a distinct two-child MS carrier with doubled child packets. The default ordinary child count still requires constructor/native getter, not a guessed five from wiki.

Required native closure: selected carrier emission count, ClusterApplyDamageMultiplier snapshot, normal/MS routing, direct contact versus death activation, SendEvents=0 consumer scope and damage-controller status/kill listeners. Spatial closure is separate: homing target assignment, arrival, LOS and which recipients receive direct 3/6 and radial18/36. SendEvents=0 does not independently prove every Arcane or kill notice is suppressed.

Zymos `/Lotus/Weapons/Infested/Pistols/InfUzi/InfUziWeapon`, mode0, main `InfUziProjectile`: direct23, ordinary explosion61, head embed death953 at EmbedTime1.1. Existing registry retains separate events plus unresolved child warnings. Carrier `EmbedDeathKillClusterProj` declares ClusterSetsChildrenDamageInfo=1 and NumClusterProjectiles1; guided child `EmbedDeathKillGuidedProj` declares direct0/explosive333, DamageUpgradeTypes=[], SendEvents=0. Existing script/native evidence in registry proves five requested children per consumed embed record, not five from carrier resource default and not ten by summing OnDeath/OnRadialDamage callbacks. Existing partial proof must not be generalized to Phantasma's different ClusterApplyDamageMultiplier route. Child333 is not admitted here.

## 2. Torid and Pox: EmbedAttack area ticks are not automatically explosive radial events

| Weapon / mode | Projectile | Impact / EmbedAttack | Source/embed radius | Duration | Registry CO for field |
|---|---|---|---|---|---|
| Torid /0 | /Lotus/Weapons/ClanTech/Bio/BioGrenadeProjectile | 100 toxin / 40 toxin SC.25 | DamageRadius10 / EmbedDamageRadius3 | [10,10] | true, community reference |
| Pox /0 | /Lotus/Weapons/Infested/Pistols/InfProximityStars/InfProxomityStarsProjectile | 50 toxin / 20 toxin SC.35 | 4.8 / 2.5 | [5,5] | true, community reference |
| Coda Pox /0 | /Lotus/Weapons/Infested/InfestedLich/Pistols/CodaPoxProjectile | 55 toxin / 35 toxin SC.45 | 4.8 / 2.8 | [5,5] | false, community reference |

Pox/Coda projectile ancestry is identical apart from child overrides. Both resolve DealDamageThroughImpactBehavior=1; Torid has that field absent. All three declare EmbedDeathAttack Type=DT_EXPLOSION without a positive Amount. No actual explosion damage should be invented from the enum or DamageRadius alone. Current registry distinguishes lingering from main radial, but `manual_combat.py` 954..1011 builds the field through `__radialPart__` and unconditionally `radial_only=True`; CO effects are conditionally stripped according to the reference boolean. `combat_replay.py` 1570..1575 handles lingering damage/status, and 2108..2119 schedules per-shot ticks starting at shot time, with no flight/embed delay and no periodic on-hit notice.

Thus the current field approximation is not proof of native radial qualification, ordinary weakpoint suppression, field hit notice suppression or the Pox/Coda CO difference. The source establishes independently valued EmbedAttack and lifetime/radius declarations; it does not close the EmbedAttack native clock, head classification or modifier/event consumers. Do not blanket enable heads/CO/events either. Need native embed packet builder, damage upgrade router and callback/notice route, then separate overlap geometry. Current 1Hz tick source for Pox/Coda explicitly comes from reference; Torid profile is reference-only. These paths currently have no reported gap.

Torid mode1 has no projectile and is LotusBeamFireBehavior + LotusBeamImpactBehavior, so it must not inherit the base projectile cloud. Resolved impact declares NumChains5, SequentialChains1, ChainDistance7 and ChainDamageMultiplier.75. Current export drops these fields and single-recipient replay reports no warning. Native per-hop targeting, per-recipient head/crit/status/kill ownership is separate from geometric recipient admission. Do not multiply one-target damage by six or add cloud ticks to Incarnon.

Minimum structural fix: Pox mode1 is explicit WeaponMeleeRadiusFireBehavior + WeaponMeleeRadiusStateBehavior, 40 impact; frozen export omits behaviorKind and inventory treats it as ranged evaluable. Existing extract.py 370..372 already marks this pair auxiliary-melee; synchronizing the tag is supported without combat consumer speculation. Root notified; no shared file edited here.

## 3. Trumna and Sepulcrum: hit trace, bounces and locked GuidedProjectile

`/Lotus/Weapons/Thanotech/ThanoRifle/ThanotechRifle` modes0/1 and `/Lotus/Weapons/Tenno/LongGuns/PrimeTrumna/PrimeTrumnaWeapon` modes0/1:

- mode0 uses RadialOnMissTraceFireBehavior with fire.ApplyRadialDamageOnHit=0/miss=0; impact RadialOnMissImpactBehavior sets hit=1/miss=1, MultiShotBuffsRadialDamage=0 and RadialDamage base50heat/radius1.6/fallOff.15. Registry currently takes_multishot=false; label says reference, but native declaration agrees. This must not be changed to per-ray damage without tracing flag meaning and trace-versus-impact precedence.
- mode1 uses ThanoRifleAltProj (PrimeTrumnaAltProj), direct100impact plus1000/1150heat explosion radius6. Both resolve ExplodeOnImpact1, ExplodeOnLifeExpired1, MaxBounces7, MaxLife5, SetLifeOnImpact1. Current registry has one immediate explosion; it does not represent bounce history or expiry. This is an unresolved multiplicity/clock candidate, not a proven eight-hit undercount. Need native bounce/contact/death callbacks and gates, then admitted recipient overlap.
- mode1 impact IgnoreHeadshotBonus=1 for both base and Prime; current live `ignoreHeadshotBonus=false` and frozen damage lacks impactIgnoreHeadshotBonus. Existing `event_profiles.ignores_headshot_bonus` supports this exact flag and EXE consumer is already documented there; adding original mode/projectile identity or refreshed explicit export is a minimal reliable correction. It affects direct100 weakpoint damage qualification; it does not revoke head events or kill Arcane qualification. Root notified.

Sepulcrum `/Lotus/Weapons/Thanotech/ThanoPistol/ThanotechPistol`: mode0 ThanoPistolProj direct48+46heat radial1.6 and WeaponBurstStateBehavior.NumShots2. mode1 ThanoPistolGuidedProj derives GuidedProjectile, direct96+480heat radial3, while state LotusLockOnBurstStateBehavior has MaxTargets5, MaxStacks1, NumShotsWithoutLock0, UseNumLocksForChargeAmount1, LockOnPartHEAD, BurstDelay.079999998. Current mode1 profile has radial but no burst/target-scoped model. Do not count five missiles on one victim or assume the locking part proves a landed head event. Need lock-target-to-emission consumer and hit dispatch; lock geometry/flight remains separate. Tenet Envoy uses yet another GuidedProjectile (`/Lotus/Weapons/Corpus/LongGuns/CrpBriefcaseLauncher/CrpBriefcaseLauncherHomingProjectile`, direct100impact / explosive640cold radius8 MaxLife6); it is not evidence that all Guided children share Phantasma SendEvents0 or Zymos script classification.

## Production clusters versus Guided children: precise native-agent targets

| Family | Child path | AttackData.HitType | ExplosiveAttack.HitType | SendEvents | DealDamageThroughImpactBehavior |
|---|---|---|---|---|---|
| Kuva Bramma | /Lotus/Weapons/Grineer/Bows/GrnBow/GrnBowClusterMiniProjectile | DHT_PROJECTILE | DHT_RADIAL | absent | 1 |
| Zarr | /Lotus/Weapons/Grineer/LongGuns/GrnCannon/GrnCannonClusterMiniProjectile | DHT_PROJECTILE | DHT_RADIAL | absent | 1 |
| Kuva Zarr | /Lotus/Weapons/Grineer/KuvaLich/LongGuns/Zarr/KuvaZarrClusterMiniProjectile | DHT_PROJECTILE | DHT_RADIAL | absent | 1 |
| Kulstar | /Lotus/Weapons/Grineer/Pistols/GrnTorpedoPistol/GrnTorpedoClusterProjectile | absent | absent | absent | 1 |
| Phantasma | /Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/AltFireClusterMiniProj | absent | absent | 0 | absent |
| Phantasma MS | /Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/AltFireClusterMiniProjMS | absent | absent | 0 | absent |
| Zymos | /Lotus/Weapons/Infested/Pistols/InfUzi/EmbedDeathKillGuidedProj | absent | absent | 0 | absent |

CanHeadshot/IgnoreHeadshotBonus are absent in all seven resolved child records. Do not silently turn absent serialized fields into false C++ defaults. The first three source tags directly support maintaining separate direct-contact versus explosive branches. Kulstar requires engine default/consumer closure. Native actual dispatch remains authoritative for every row.

Current core expands both cluster.direct and cluster.radial at manual_combat.py 942 and then forces radial_only at990; it therefore loses the distinction in production despite retaining nativeField in registry. Root owns correcting that representation and validating actual consumer eligibility.

## Focused candidate order

1. Correct Trumna/Prime mode1 explicit impactIgnoreHeadshotBonus qualification using already audited consumer; one representative test suffices. Preserve head notices.
2. Preserve production cluster direct versus radial identity, starting with explicitly tagged Zarr/Bramma/KuvaZarr; root/native agent to close qualification, no unproved Guided expansion.
3. Synchronize Pox auxiliary mode tag and add explicit unresolved evidence for EmbedAttack CO/event qualification plus Trumna bounce/clock and Sepulcrum target scoped emission. Do not fabricate numerical additions.

No changes in this subtask to core/data/tests, no build or release claim, no actual in-game recipient/Arcane claim. Source inventories and existing replay probes are static/model evidence only.
