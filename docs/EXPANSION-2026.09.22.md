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

## 三、同伴武器（已完成 — subagent 99dc0ca5）

### 数据质量问题（已修复，10 行实质变更）

| 武器 | 修复前 | 修复后 | 根因 |
|---|---|---|---|
| **破坏者 Deconstructor** | 10 伤 / 0% 暴击 | **130 伤**（3×43.3 IPS 轮换）/ 0%/1.0x/25% 触发 | 投射物序列（projectileSequenceList Front/Rear/Mid 轮换）从未被读取——旧导出落到 impact 占位数据 |
| **破坏者 Prime** | 10 / 0% | **160**（160×3 IPS 轮换）/ 0%/1.0x/25% | 同上（U37 平衡后每发 160，wiki infobox 确认） |
| Cryotra | 25%/2.5x | **10%/1.75x** | 投射物为 shell 时真实暴击在投射物上（impact 的 25% 是错的） |
| Helstrum | 总伤 10 | **9**（4.95 冲击/4.05 穿刺） | 权重编码的 DT 份额（5.5/4.5 权重和 10）被当绝对值求和 |
| Prime Laser Rifle | 触发 0% | **10%** | 投射物无 ProcChance 时缺 impact 回退 |
| Vulcax | （无蓄力时间） | +chargeTime 1s | state 的 ChargeTime 被丢弃 |
| Burst Laser 家族×4 | — | +burstCount/burstDelay | 连发参数补全 |

其余 13 把数值不变（字节数据漂移消除）。

### Deconstructor / Deconstructor Prime（破坏者，用户确认的战刃类近战判定）

- `isMeleeJudged: true` + `meleeFields: {slamAttack: "SlamAoE", heavySlamAttack: "HeavySlamAoE", parryAngle: 90, empoweredMeleeChance: 0.15}`——震地伤害**有意不建模**（只记录结构）
- 近战字段实际挂在祖先 `/Lotus/Types/Game/LotusMeleeWeapon` 上（非武器文件本身）
- Zanuka hound 近战（Akaten/Batoten/Lacerten，WeaponMeleeRadiusFireBehavior）结构不同，**不标** isMeleeJudged

### 新同伴武器排查

- 2026.09.22.16.46 dump 的 SentinelWeapons 集合与旧 dump **完全一致**（双向验证）——**无新同伴武器**
- Banshee Deluxe 哨兵只带了外观（皮肤/面罩/尾/翼 + WeaponSkin 是既有武器的外观）——**无武器本体**（后续版本再上）
- 24 把同伴武器新旧 dump 语义 diff：无数值变化（只有 txt 格式的字符串-数字类型差异）

### 验证

- 21 把可对照武器的 total/crit/critx/status/fireRate/reload 与 wiki 完全一致（唯一例外：Prime Laser Rifle reload 1.0 vs wiki 1.2——raw dump 比 wiki 新，保留 raw）
- 工具：`tools/extract-companion-weapons.py`（--apply / --summary；按路径补丁 + mtime 竞争检查 + 原子写）
- 67 项测试前后一致

## 四、Banshee Deluxe 哨兵

已排查：本 build 只有外观无武器，无可收录内容（见三）。
