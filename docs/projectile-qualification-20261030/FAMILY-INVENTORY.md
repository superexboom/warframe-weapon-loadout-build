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

## R3/R4/R5 后续闭合与旧清单勘误（2026-10-30）

本节更新上述族清单的阶段状态；旧表保留原审计时点。EXE/Packages身份仍为本文件开头的同版SHA。

| 族 | 新闭合的来源／consumer事实 | 当前实现／保留的具体边界 |
|---|---|---|
| Phantasma／Prime父弹 | 普通cluster constructor默认5、MS载体2；首普通parent+额外MS carrier选择、child倍率快照、死亡防重复已闭合。full-clip charge消费A、父15/73乘A、基础蓄力.090899996*A／chargeRate | 普通reload；子弹3/18、6/36不免费乘父charge。默认子弹off；显式ideal-contact＋arrivalSeconds才计覆盖 |
| Phantasma子弹 | 真Guided表1420de498；direct fallback+820一次CO基于自身已建packet，独立CO；direct/explicit-host explosion的generic hit/crit与victim-crit均已追到消费者 | 默认body金额近似独立于parent aim；父head不抑制child。到达/LOS/重叠是显式策略；Enervate特殊分组未从generic通知推导 |
| 子弹时钟 | MaxLife2.9000001 **另有**MaxLifeVariance.69999999，原生实际约[2.2,2.9)，并非固定2.9秒 | .7是unguided/homing阶段参数；选定arrival默认值.7只是理想几何假定，不能把到期当到达 |
| Trumna／Prime | 第7次eligible contact终止；首次impact后5秒expiry，后续不续期；Die销毁同一timer队列 | 默认单体首次contact1包；没有单体7／8包保底。其余bounce接收者是空间策略 |
| Sepulcrum | 每target1 stack、最多5 target；projectile-created逐记录分配；InitialLockTime0／switch0；relock.3和rearm.01用途明确 | 现有5 kills→1 alt循环与单体1锁一致；不加5倍。多枚间隔.08是发射时钟，实际到达另属几何 |

明确撤回旧“Guided自动class搜索结果就是本体表”的解读：后缀类GroundAlignedGuidedProjectile1422c2128、StickyGuidedProjectile1423c9e28不是本族资源的准确C++本体；当前以1406e1960的vtable install确定1420de498。完整源链、constructor、原字节片段及有限执行记录在`lifecycles/NOTES.md`。本轮没有用field缺省代替C++默认，也未用来源数量乘成免费单体命中。

当前子弹调度还保留每个child的contact→explosion配对顺序，父radial先执行，下一child仅在原victim generation仍存活时接续。低HP回归确认首child的3/18两包先致死后，不再投递第二child contact；不是把5次contact聚合后才尝试5次radial。fractional MS仍为期望数量近似。


## R2／Quanta／Stug 当前接入与验收（2026-10-30）

本节覆盖上述初期清单的对应未闭合状态；完整原生调用证据仍分别保存在 `.local/delivery/projectile-qualification-20261030/embed-fields/` 和 `quanta-completion/`。这些实现没有以“爆炸”名称统一判定接收者资格。

- **R2附着毒场**：固定1秒周期与嵌入时首包已有实际DoEmbedDamage调度证明。附着目标单独递交后由plan+120从同次region枚举排除；Torid附着tick通过+820按已源修正tick基数独立CO，Pox／Coda经普通fresh source+818按父projectile50／55查询基数，对20／35tick分别为additive2.5／11⁄7。来源、附着目标和普通非ability父链边界保留。当前 `_live_co_refresh` 在每个tick读取当前victim状态与Galvanized源层数，保留普通源修正的launch snapshot；层数到期不能继续沿用发射时CO。既有Pox回归同时覆盖静态总190、真实Galvanized层数在场存续期内到期及native SHADOW。
- **Quanta显式策略**：`combatState.quantaStrategy=shoot` 必须显式选择；默认contact保留。先副射击立方体，另付一次主射击弹药与完整主射周期；基础10＋.5ammo，总延迟 `.25 + 1/主射实际射速 + .1125`。敌人不受立方体直击100／180或用于引爆的主光束额外伤害；每个实际cube仅600Blast一次。多重首seed与其余sibling分别按延迟递交，连锁不产生4的指数倍率。场接收者使用显式nativeRADIAL4，不借明确contact recipient的+c24类型；generic hit／crit按实际非零伤害、旧目标退场前递交。实际覆盖、命中一次光束、.1125为原生延迟区间均值均保留诊断。当前实现未加入自由闲置／miss retry动作策略；9秒生命周期已有静态证据，不等于这些控制策略已全部接入。
- **Stug已审事件flag**：embed、主爆炸、child的generic hit／crit通过 `take(damage_event=...)` 在原victim retirement前递交；旧后置手写hit已删除，避免同包双计。critical概率保留full-victim、当前Enervate边际、实际body／head和独立Puncture资格；普通radial child不借main的弱点或bodyshot倍率。既有area-direct伤害、head geometry及Enervate advance语义保留，未扩大flag给未知来源。

本次已运行三个相关既有模块：`test_quanta_contact_events.py`、`test_stackable_projectiles.py`、`test_delayed_radial_events_20261028.py`，共 **60 passed**。其中Quanta新功能仍只有3个参数展开合同，Stug通知修复只新增1例；测试包含实际native调用计数增长的SHADOW路径、Quanta发射前零敌人hit、10.5ammo与两次on-fire、真实manual／optimizer一致，以及Stug致命packet的hit17／crit8.875。前一次运行在旧pyd不具备新能力flag时正确拒绝native；重编译并确认QUANTA_PAID_PRIMARY／STACKABLE_CRITICAL_EVENTS／RADIAL_LIVE_CO／ZYMOS_ORDERED_CHILDREN后60例全通过。没有把旧模块存在等同当前原生实现已加载。

仍需场景输入的部分是cube standoff／LOS、同批chain邻接、瞄准和实际脉冲命中次数、field附着与移动覆盖。源consumer、CO基数、1秒场时钟与generic通知均已按上述普通source合同闭合；这些场景变量没有被伪装成native常量未知。没有烘焙、release或Bot部署。


复核补充：从真正零Galvanized层数发射的Pox仍保留live-CO callback，直接调用其同一发射快照的当前源层数0→1→0，tick结果为20→约40→20，证明初始空CO桶不会阻止后续启用／到期关闭。Quanta连续8批infiniteAmmo路径也进入当前native SHADOW且零fallback；付费primary事件没有被victim generation绑定吞掉。以上是现有路径的代表性交互检查，没有增加测试案例。

## R2 源属性时点复核：撤回“所有非CO均发射快照”（2026-10-30）

上述“普通源修正launch snapshot”只描述当时实现，不能作为原生合同。`DoEmbedDamage140297cf0→140a58cb0` 每tick重建packet，positive-radius附着分支每次调用`+628=1416373e0`。普通配置分支在`141637a03..a87`从当前source avatar的UpgradeManager遍历Projectile+db0/+db8（默认253／WEAPON_DAMAGE_AMOUNT），`141637f25..f48`每次取得当前weapon+840/+838元素次序／模式，`141637ff4..14163801d`调用`1403a6ea0→14171a350`，后者`14171b729..b81a`重新读取当前source manager的358／WEAPON_PERCENT_BASE_DAMAGE_ADDED及359／WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE。独立flat-type265查询也在`14163818b..203`每次执行。因此源damage buff层数变化可静态确定会改变后续tick；当前仅刷新CO的实现尚缺这些当前源阶段，不能借场景几何将其称为未知。

应保留的不同阶段是Projectile自身缓存：+7b8源倍率、+818保留bucket、+fe0上下文STACKING、+fe4上下文MULTIPLY、+fe8额外元素列表、+ff8额外flat CC。`+628`每tick使用这些字段，不在DoEmbedDamage入口自行重新填充。已定位的`141548510`更新来自source setter`1405efa30`及owner setter`140f84b40`（refresh参数为true且相应source存在）；这些setter与当前普通UpgradeManager查询是两条不同通道。`140a591c2/140a59259→140ede780`再将投射物保留的+538/+570暴击桶复制到附着packet／region plan，并合并packet预先CC/CD；该函数不重新查询普通244／248源暴击MOD。故最小正确修复应刷新每tick源damage／元素阶段，保留原发射暴击桶与上述context缓存；直接重跑整个field的全部源效果会错误刷新crit。原字节来源：已有`embed-fields/140a58cb0.asm`、`native-routes/1416373e0.asm`、`zymos-completion/141548510.asm`及本次由既有hash-gated disassembler提取的`stug-vectis-20261026/work/1403a6ea0.asm`、`14171a350.asm`。未新增测试或修改core/data。

同次packet的status也非全量launch snapshot：`141637ed4..f1d`对packet+23c重新query365／WEAPON_PROC_CHANCE；`140451710`还每次query281／WEAPON_FORCED_PROC_CHANCE。radius在`140a58d6e..dae`每tickquery274／WEAPON_EXPLOSION_RADIUS（source／ability gate保留），不能把数值本身标成统一launch snapshot。+7bc/+7bd/+7be等发射阶段资格latch与当前295／298／217查询须分开：保留latch资格后重新求当前源值，不借重建全entry改变本发的首发／末发身份。


### R2实现收束

上节识别的实现缺口已在本轮修复：`_live_hit_refresh`每tick通过原source mode和本发身份重建当前damage/element/status/CO，同时回填原弹体CC/CD及数量，外部source context仍按明确普通来源边界。原`_live_co_refresh`已替换，非CO属性不再一律被冻结。Pox同一用例通过真实Merciless到期、Galvanized到期以及Crosshairs当前已消失而旧弹体仍保留CC的检查。最终全轮137项聚焦验证和28项选定搜索对照见PLAN/evidence，勿将本文件中间60项与最终137相加。
