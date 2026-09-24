# 新版本战甲与武器拓展（2026-09-24 进行中）

**游戏 build**：2026.09.22.16.46（对照冻结导出 2026.08.13.13.24）

## 一、战甲数据审计（已完成）

### 全战甲属性 diff（冻结导出 vs 新 dump，继承链解析）

**真正变动的只有 2 条**（U38.6 Hydroid 重做）：

| 战甲 | 变动 |
|---|---|
| Hydroid（Pirate） | shield 550→140（削弱）、armour 300→465（增强） |
| Hydroid Prime | shield 550→190（削弱）、armour 300→650（增强） |

其余 115+ 战甲的血/盾/甲全部无变化。（审计方法：EE-notation 解析器 v2 + parents.json 继承链 + `MaxHealthOverride/MaxShieldOverride/ArmourRatingOverride` 字段；第一轮的 24 条「变化」是比较基线错位——Prime 记录值 vs BaseSuit 值——已修正。）

### Banshee 改动排查

- **属性**：无变化（270/270/105）
- **技能数值参数**（Lua Script._ 参数）：4 个技能全部无数值变化（Sonar/Push/Silence/SonicEarthQuake 的 diff 全是 FX/特效路径）
- **机制层新增**：`SonarWeakSpotProj`（全新声呐弱点投射物对象）+ SonicEarthQuake 的 `AbilityEvents`（OnAbilityActivate → BansheePassive 联动）+ Silence 的 ParticleEvents——**玩法机制重做，数值引擎无感知**（项目战甲引擎只消费数值）
- Banshee Deluxe 哨兵（新同伴）见武器拓展部分

### 新战甲（已合并进冻结导出，129 帧）

| 战甲 | 血/盾/甲 | 技能 | 来源 |
|---|---|---|---|
| **Citrine Prime** | 400/270/325 | 4（继承 GeodeBaseSuit 链） | Powersuits/Geode/CitrinePrime |
| **Duelist**（新普通甲，剑客） | 270/550/165 | 4（BladeDance/Leap/Riposte/Thrust——DuelistBaseSuit） | Powersuits/Duelist/Duelist |

ControllableLotusSuit（可操控 Lotus，2 技能，剧情甲）暂不收录（非常规配装对象）。

## 二、空战武器（进行中 — subagent）

**用户口径更新（2026-09-24）**：只做空战**枪**（archgun）的地面数据；**空战近战全部不要**（无地面状态）——8 把 SpaceMelee 将从导出中移除。

### 结构发现（subagent ec90cf8a 已确认）

- 20 把 SpaceGuns **已在导出**（slot=arch_gun）但 fireModes 是**空战模式**（Behaviors 的投射物口径）——将**原地替换**为地面模式（HeavyBehaviors）
- 地面数据：`HeavyBehaviors[i]` 与 Behaviors[i] 同构（fire:/state:/impact: 命名空间字典）；impact 带 AttackData + `criticalHitChance/criticalHitDamageMultiplier`；state 带 fireRate（rpm/60）+ reloadTime + trigger LocTag
- 地面弹药：`HeavyAmmoClipSize`（= 弹匣）+ `HeavyAmmoCapacity`（ammoMax）
- Imperator 地面核对（wiki 一致）：100 伤害（40/35/25 IPS）、24% 暴击、×2.0、12% 触发、16.67/s、弹匣 200、备弹 800
- **名称修正**：TnConcreteArchgun=Mandonel（辐光弩炮）；Kuva Ayanga 在 GrnHeavyGrenadeLauncher；ThanoTechArchGun=Cortege、ThanoTechLongGun=Mausolon、ThanoTechGrenadeLauncher=Morgha；ArchBurstGun=Cyngas；NokkoArchGun=Arbucep；TnShieldFrameArchGun=Larkspur；ArchCannon=Corvas；ArchRocketCrossbow=Fluctus；ArchRailgun=Velocitus

## 三、同伴武器（进行中 — subagent）

### 数据质量问题（已核实）

当前导出的 24 把同伴武器（哨兵/MOA/Zanuka）数据**不完整**：它们的射击数据在 Behaviors（fire:/impact:/state: 命名空间），现有提取器漏读字段——**Deconstructor Prime 导出 critChance=0.0 是错的**（impact 行为里有独立的 `criticalHitChance` 字段未被读取）；fireRate 也不对。

### Deconstructor / Deconstructor Prime（破坏者，用户确认的特殊武器）

- **战刃类型近战判定**（用户确认）：`GlaiveProjectileFireBehavior`（战刃投掷）+ 完整近战字段集
- 近战结构：`SlamMeleeAttack=/Lotus/Weapons/Tenno/Melee/Attacks/SlamAoE`、`HeavySlamMeleeAttack`（重击震地）、`ParryAngle`/`ParryDamagePercentBlocked`（格挡）、`BaseEmpoweredMeleeChance=0.15`（强化近战几率）、`StealthMultiplier`（偷袭）
- 导出处理：`isMeleeJudged: true` + meleeFields 结构登记（不模拟震地伤害，只记录结构）
- AttackData：Amount=10、IPS 均分、proc 0.1、DHT_NONE

### 新同伴武器

- Banshee Deluxe 哨兵（BansheeDlxSentinel）——subagent 排查其武器记录（新 dump EE 格式）

## 四、Banshee Deluxe 哨兵

并入同伴武器部分（见上）。
