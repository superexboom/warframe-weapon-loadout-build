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

## 二、空战武器（进行中）

### 结构发现

- 导出映射 `SpaceGuns → arch_gun` **存在**但**空战枪全部缺失**（导出只有 8 把空战近战）
- **根因**：空战枪的射击数据不在 `FireModes`（普通武器结构）而在 **`Behaviors`**（fire:LotusWeaponProjectileFireBehavior 体系）+ **`HeavyBehaviors`（地面/Havy Weapon 形态专用）**
- 地面弹药：`HeavyAmmoCapacity/HeavyAmmoClipSize`（Heavy 前缀 = 地面）
- 枪械清单（36 条记录去重后 ~15 把 + 近战 8 把）：Imperator（ArchMachineGun）、Fluctus（ArchBurstGun）、Corvas/PrimeCorvas、Larkspur/Prime、Velocitus（?）、Dual Decurion、Cyngas、Kuva Ayanga（ArchGRNAAGun）、Phaedra、Morus（ThanoTechArchGun）、Corufell/Prime（空战镰刀，melee）、Grattler、Fluctus 等
- **空战近战已在导出**（8 把）——它们的地面数据（ArchwingAtmosphere melee）可能也要核对
- 待做：Behaviors → fire mode 提取器（damage/crit/proc/rate 从 LotusWeaponProjectileFireBehavior 的 AttackData）+ 地面口径选择（HeavyBehaviors 优先）+ mod 补全（Archgun duel stat mods：地面用 Primary mod 槽）

## 三、同伴武器（未开始）

- 待枚举：Sentinel/Pet/MOA/Kubrow/Kavat 武器（ProductCategory: SentinelWeapons——导出里 companion 类已存在？）
- **特殊：分离**（用户说判定像近战）——候选：Dethcube 的武器？或 Vulpine/「Slink」？需查证具体武器名（可能是 MOA 的 Cryoxion 或新的分离式同伴武器）
- 数据/乘区/效果自行获取，最后对照 wfsim

## 四、Banshee Deluxe 哨兵（未开始）

- 新同伴（BansheeDlxSentinel）+ 对应武器——归入同伴武器部分
