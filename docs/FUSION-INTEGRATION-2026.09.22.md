# 新版本（2026.09.22.16.46 词条融合更新）数据接入记录

**记录时间：2026-09-24（滚动更新）**
**游戏 build：2026.09.22.16.46**（词条融合「Riven Fusion / Advanced Traits」正式上线）
**数据来源：新 dump（EE-notation .txt 格式）+ 另一线程的数值提取（`.local/research/update-2026.09.22/`）**
**关联引擎逆向：weakpoint-multiplier-re.json（进行中）**

## 一、新词条（Advanced Traits / 灵化进阶词条）数值与类型

另一线程已提取全部新词条数值（`new_riven_stats.json`，3411 行）。相对现有 `RIVEN_RULES` 的**8 个新 UpgradeType**：

| 词条 | UpgradeType | base90（步枪/霰弹/弓） | base90（手枪） | 类型语义（待引擎裁决确认） |
|---|---|---|---|---|
| **弱点伤害** | `WEAPON_DAMAGE_WEAKPOINT` | **2.25** | 0.9 | 弱点命中的伤害加成（乘区待 RE） |
| **弱点暴击几率** | `WEAPON_CRIT_CHANCE_WEAKPOINT` | **2.475** | 0.9 | 弱点命中时 +crit chance（乘区/门槛待 RE） |
| 弹药效率 | `WEAPON_AMMO_CONSUME_RATE` | -0.09（负=减耗） | 同 | 弹药消耗乘区（不碰伤害） |
| 收枪自动装填 | `WEAPON_AUTO_RELOAD_RATE` | 0.9 | 0.9 | 收枪时自动装填速率（utility） |
| **状态伤害** | `WEAPON_PROC_DAMAGE` | 0.9 | 0.9 | DoT 伤害乘区（与既有 handler 同桶待确认） |
| 重击蓄力速度 | `WEAPON_MELEE_HEAVY_CHARGE_SPEED` | 1.197（近战） | — | 近战专属 |
| 格挡角度 | `WEAPON_PARRY_ANGLE` | 8.1（近战） | — | 近战专属 utility |
| 震地伤害 | `WEAPON_MELEE_SLAM_DAMAGE_BONUS` | 1.197（近战） | — | 近战震地加成 |

另有**新复合元素词条**（Gas/Corrosive/Viral/Radiation/Blast/Magnetic → `WEAPON_PERCENT_BASE_DAMAGE_ADDED` base90=0.9 each）与**新派系词条**（Orokin/Techrot/Scaldra → `GAMEPLAY_FACTION_DAMAGE` base90=0.45）。

### 关键观察

- **弱点伤害词条的数值远超常规词条**（base90=2.25 vs 常规 0.9-1.5）——这是新系统的核心输出词条，乘区归属决定它值多少。
- 手枪的弱点家族 base90=0.9（明显低于步枪 2.25）——手枪平衡性差异。
- `isAdvancedTrait: true` 全部标记为进阶——词条融合系统只能从进阶词条里选。

## 二、弱点条件系统（引擎数据侧已确认）

新版本新增 8 个弱点条件对象（赋能/PvP 条件用）：

- 判定脚本：`IsWeakpoint.lua::MatchAttackEvent`，**`_weakness=0.5`**（弱点系数 ≥0.5 才算弱点命中——即 body part multiplier ≥1.5x？待 RE 确认语义）
- **`IgnoreHitTypes={DHT_RADIAL, DHT_DOT}`**：**径向命中和 DoT tick 不触发弱点条件**（OnWeakPointKillAnySourceCondition 只忽略 DHT_RADIAL）
- `Injury=ANY`（任意部位命中按弱点系数判定）

## 三、新赋能（已确认 1 个）

### StatusAndAmmoEfficiencyOnWeakpointHit（弱点命中状态+弹药效率）

- 稀有度 RARE、主武器（LotusLongGun）、R5
- 效果：**弱点命中时 +5% 状态几率 +1%/层 弹药效率（-1% 消耗），最多 10 层，持续 10s**
  - R5 满级：+25% 状态几率 + -5% 弹药消耗（满层时）
- 触发：`OnWeakPointHitCondition`（弱点命中；径向/DoT 不触发）
- 参数：`_statusChanceBase=0.05 / _statusChancePerLevel=0.05 / _ammoEfficiencyBase=-0.01 / _ammoEfficiencyPerLevel=-0.01 / _duration=10 / _maxStacks=10`

其余新增 CosmeticEnhancers 文件均为条件对象（非独立赋能）；未发现用户新边框 mod（确认不存在）。

## 四、武器倾向（disposition）变化

42 把武器倾向调整（+4.3% ~ +40%），完整清单见 `disposition-table.json`。要点：

- Prime 大部队普涨：PrimeAfentis +30%、PrimePerigale +23.1%、PrimeWar +30%、TnOrion/TnSirius +40%
- 新武器入场：GrnChemstrikeNoxRiflePlayer 0.5、ThanoTechLongGun 0.5、SentOctaMiniGun 0.6
- 新增 71 条（含组件/哨兵武器）、移除 24 条

## 五、乘区解析（引擎逆向裁决完成——weakpoint-multiplier-re.json）

### 枚举索引修正（重要）

UpgradeType 枚举表（.data 0x14278d000，428 项）三重锚定确认：`WEAPON_DAMAGE_WEAKPOINT=266`、`WEAPON_CRIT_CHANCE_WEAKPOINT=246`、`WEAPON_CRIT_CHANCE=244`、`CRIT_CHANCE_BODY_PART=245`、`PROC_DAMAGE=367`。**此前一轮的索引（如 IF_VICTIM_PROC_ACTIVE=32）因构建表起始偏移假设错误全部 +24 偏差——真实索引 247。**

### 弱点伤害（WEAPON_DAMAGE_WEAKPOINT）乘区裁决

- **门槛**：伤害事件的 `mIsWeakpoint` 标志（event+0x322，fn 0x140a29d10）——引擎侧门控，词条本身无 SymbolFilter。
- **乘区**：走**条件升级管线**（与 `WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE`=259 同系统；评估器 fn 0x141cdf960/0x141ce0900，opcode dispatch 0x40a/0x40b/0x43f）。与部位倍率（hit-proxy `DamageAtten`，fn 0x140c5f9d0 只对 slot 286 应用）是**不同乘区**：
  - `最终伤害 = 基伤 × 部位倍率(DamageAtten) × (1 + 弱点加成 [+ 其他条件伤害加算])`
- **DoT/径向影响范围**：静态无法裁决（虚拟分派按事件评估；tick 事件的 mIsWeakpoint 状态未证明）——开放项，需要动态测试。

### 弱点暴击几率（WEAPON_CRIT_CHANCE_WEAKPOINT）裁决

- **与 WEAPON_CRIT_CHANCE(244)/CRIT_CHANCE_BODY_PART(245) 加算进同一次判定**（fn 0x1406dc47e 在同一链测试 244-248，IsWeakpoint(event) 门控，汇聚进同一暴击聚合 0x140889d00/0x140cb33a0）。
- 不是独立 roll；与 Latron 家族的 body-part crit 同机制族。

### 弱点基础倍率的重要澄清

- `mWeakpointWeaknessValue`（0x1420db9c8）是**挑战系统字段**（IsWeakpoint.lua `_weakness=0.5` 的挑战匹配阈值），**不进伤害公式**。
- 真实倍率在 HitProxy 字段：`mDamageAtten`（部位伤害倍率：弱点 2.0、机器人头部 0.666）、`mCriticalMultiplier`（默认 **2.0**，弱点部位可覆盖）、`mWeakness`（0-1 弱点标记）。字段表 0x142785450。

### 其余词条裁决（全部确认）

| 词条 | 裁决 |
|---|---|
| 状态伤害 PROC_DAMAGE(367) | 与既有 handler 同桶（proc 对象 pair-modifier，r8d=0x16f @0x14187e8ef → SetModifier 0x14187e720）；只缩放 tick seed，**不碰 +1 累加项** |
| 弹药效率 AMMO_CONSUME_RATE(218) | 纯 utility（负 STACKING_MULTIPLY = 减耗），不碰伤害 |
| 自动装填 AUTO_RELOAD_RATE(225) | 纯 utility（ADD，SymbolFilter=Holstered，收枪装填） |
| 复合元素（Gas/Corrosive/Viral/Radiation/Blast/Magnetic） | 与基础元素同桶：`WEAPON_PERCENT_BASE_DAMAGE_ADDED`(358) ADD、pre-coalesce、标准 mod 序合成。命名怪癖：Magnetic=DT_POISON、Blast=DT_EXPLOSION |
| 新派系（Orokin/Techrot/Scaldra） | `GAMEPLAY_FACTION_DAMAGE`(179) + SymbolFilter=Orokin/Techrot/Scaldra。融合配方：Orokin=Grineer+Corpus、Techrot=Corpus+Infested、Scaldra=Infested+Grineer |

### 开放项

1. 弱点伤害对 DoT/径向的影响范围（需动态测试或更深逆向）
2. 条件伤害加算的确切算术（与 259 是乘算还是加算进同一括号）
3. 弱点暴击与部位 mCriticalChance/mCriticalMultiplier 的交互细节

## 六、爆头→弱点击杀 系统性更名（2026-09-24 确认）

**用户观察证实**：本更新把大量爆头条件改为弱点条件。diff 新旧 dump 确认 **11 个文件发生更名**（0 个文件消失）：

| 文件 | 旧条件 | 新条件 |
|---|---|---|
| AmmoEfficiencyOnPistolHeadshot | HeadshotKillCondition | WeakPointKillCondition |
| GolemArcanePistolDamageOnHeadshot | HeadshotCondition | WeakPointHitCondition |
| LongbowDamageOnHeadshot | HeadshotCondition | WeakPointHitCondition |
| PrimaryDamageOnNoMelee | HeadshotKillCondition/AnySource | WeakPointKillCondition/AnySource |
| SecondaryDamageOnNoMelee | HeadshotKillCondition/AnySource | WeakPointKillCondition/AnySource |
| CritChanceWhileAiming{Pistol,Rifle,Shotgun}Mod | HeadshotCondition | WeakPointHitCondition |
| （+PvP Conditions 两个） | OnPistolHeadshotKill | OnPistolWeakPointKill |

**语义变化（实质更名，非表面）**：

| 维度 | 旧（Headshot） | 新（WeakPoint） |
|---|---|---|
| 判定方式 | `Part: "HEAD"`（硬编码头部） | `IsWeakpoint.lua::MatchAttackEvent` + `_weakness=0.5`（弱点系数≥0.5 的任意部位） |
| 覆盖范围 | 只有爆头 | **任意弱点部位**（机器人腿部、Golem 核心等） |
| 排除类型 | DHT_RADIAL | **DHT_RADIAL + DHT_DOT**（新排除 DoT） |

**含义**：所有原「爆头击杀触发」的赋能（PrimaryDamageOnNoMelee 家族 = Primary/Secondary Merciless 等）现在**任意弱点击杀都触发**——触发面扩大；但 **DoT 击杀不再触发**。

### 新增 mod（同名弱点家族）

- `WeaponWeakpointCriticalChanceMod`（Rifle + Pistol 版）——弱点暴击几率 mod
- `PlayerWeakpointCriticalChanceAuraMod`——光环版

## 七、接入深度（2026-09-24 盘点与补齐）

**已接入（本轮提交）**：
- ✅ 弱点乘区 handler（WEAPON_DAMAGE_WEAKPOINT / WEAPON_CRIT_CHANCE_WEAKPOINT）+ `_apply_weakpoint_folding`
- ✅ PROC_DAMAGE 同桶（既有 handler）
- ✅ 42 把武器倾向合并
- ✅ **RIVEN_RULES 新词条码**（48 码）：W=弱点伤害、Y=弱点暴击、GA/CO/VI/RA/BL/MA=复合元素、SD=状态伤害、AE=弹药效率、HR=收枪装填、FO/FT/FS=新派系
- ✅ **RIVEN_BASE_VALUES 新基值**（步枪/霰弹/弓 W=330、Y=363；手枪 W=132、Y=132 等）

**待接入（下轮）**：
- ⬜ 新赋能 StatusAndAmmoEfficiencyOnWeakpointHit 进 MANUAL_ARCANES 目录（数据在冻结导出之外——需要重建 mod/arcane 导出或手工 sidecar）
- ⬜ 新 mod（WeaponWeakpointCriticalChanceMod 等）进 mod 目录（同上）
- ⬜ 爆头→弱点更名影响模拟器 trigger 判定：`_collect_trigger_sources` 的 `"headshot" in condition_text` 分支应同时匹配 weakpoint（触发面扩大）——条件文本仍含 "hit"/"kill" 关键字所以现有匹配大体兼容，但 DoT 排除是新行为
- ⬜ 前端词条词典（新码的中文标签已在 RIVEN_RULES label 里，前端 TYPE_LABELS 无需额外改动）
- ⬜ 融合配方 UI（14 条配方数据在 fusion-riven-analysis.json，交互设计待定）
